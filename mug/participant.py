"""Wire the participant flow and the game onto the realtime transport.

This module joins the content flow service and the game stepping loop to the
realtime session. ``build_open`` opens a flow when a participant connects and
queues the first activity. ``build_dispatch`` routes the ``flow.advance`` command
to the flow service and queues the next activity. When the next activity is the
game, it marks the session ready, and ``build_on_game`` runs the stepping loop:
it reads input frames, pushes render packets, and then advances the flow past the
game to the debrief.

With the launch gate set, a fresh connection redeems a launch ticket, enrolls the
participant, and starts the visit before the flow materializes, so a durable
pseudonymous enrollment gates entry (API-03); a reconnection restores that same
enrollment. Without the gate the demo bootstraps an anonymous per-connection
subject. Casting and multi-seat grouping stay out of this slice. The module lives
above the transport and the gateway, so it may mint a context, yet no inner layer
imports it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import (
    Awaitable,
    Callable,
    Coroutine,
    Generator,
    Mapping,
    Sequence,
)
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, TypeVar, cast

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from mug.agents import (
    AgentGameSpec,
    HumanSeatSpec,
    MultiAgentEpisode,
    SeatMemory,
    TurnBasedGameSpec,
    build_agent_episode,
    build_turnbased_episode,
    warm_up_seats,
)
from mug.agents.generation import RecordedGeneration
from mug.authoring import Message
from mug.client import RealtimeCommand
from mug.content import (
    AdvanceFlowCommand,
    FlowState,
    MaterializeFlowCommand,
    Rounds,
    Study,
    advance_flow,
    demo_study,
    flow_of,
    materialize_flow,
    present,
)
from mug.content.forms import read_answers, record_form_answers, recorded_answers
from mug.content.plan import occurrence_id_for, spec_for
from mug.content.service import RecordAnswers
from mug.content.treatments import (
    AnswerLookup,
    MintContext,
    assign_visit,
    manipulates,
    record_exposures,
    visit_orders,
)
from mug.content.types import FormSpec
from mug.conversation import ChatMessage
from mug.conversation.anchors import (
    MESSAGE_ANCHOR_MEDIA_TYPE,
    MessageAnchor,
    anchor_bytes,
    verify_anchors,
)
from mug.conversation.room import ChatRoom, RoomChannel, RoomMember
from mug.diagnostics import Diagnostics, NullDiagnostics
from mug.game import RenderPacket
from mug.game.aec import TurnBasedSummary, TurnStepInfo
from mug.game.browser import (
    BrowserGameSpec,
    ClientEpisodeError,
    client_manifest,
    parse_client_part,
)
from mug.game.capture import capture_episode, recorded_trajectory
from mug.game.capture_parts import (
    PartOutOfOrder,
    RunIdentity,
    progress_aggregate_id,
    read_progress,
    record_part,
)
from mug.game.env import GymEnv
from mug.game.keys import Bindings
from mug.game.mesh_session import (
    MeshEpisode,
    MeshGameSpec,
    MeshSession,
    SeatWiring,
)
from mug.game.multiseat import (
    MultiSeatEnv,
    MultiSeatStepInfo,
    MultiSeatSummary,
    MultiStepResult,
)
from mug.game.p2p_room import P2PRoomError
from mug.game.p2p_room_types import RoomEffect
from mug.game.runtime import (
    EpisodeSummary,
    InputState,
    render_packet,
    run_episode,
    watched_state,
)
from mug.game.seams import SeatActionSource
from mug.game.server_session import ServerEpisode, ServerSeat, ServerSeatSession
from mug.game.spec import GameSpec, HudFn, RenderFn
from mug.game.surface import Surface
from mug.gateway import Gateway
from mug.identity import EnrollCommand, LaunchTicket, enroll
from mug.interactions import FormationResult, MeshFormationService
from mug.interactions.bus import NodeMessage
from mug.interactions.lifecycle import (
    finalize_interaction,
    membership_id_for,
    open_interaction,
    record_channel,
    record_membership,
)
from mug.interactions.pool import GroupConfig, MeshFormationPool
from mug.interactions.rendezvous import Ticket
from mug.interactions.rooms import ChannelSpec, RoomFormation, RoomResult
from mug.interactions.types import FifoMatch, Interaction, Membership
from mug.kernel import (
    ArtifactRef,
    CommandReceipt,
    CommandTypeRef,
    DataHandlingRef,
    Digest,
    PrincipalRef,
    VersionStamp,
    WireCommandEnvelope,
    compute_digest,
    etag,
)
from mug.kernel.refs import DeploymentRevisionRef, StudyVersionRef
from mug.nodes import ENDED, FRAME, INPUT, SEATED, Node, RemoteSeat, SeatRelay
from mug.observability import log_line
from mug.participant_chat import (
    ChatDurability,
    ChatSpec,
    RoomSeat,
    run_chat_activity,
)
from mug.participant_comparison import ComparisonOutcome, run_comparison_activity
from mug.participant_p2p import P2PConnection, P2PCoordinator
from mug.participant_p2p_edge import (
    P2PFrameError,
    apply_frame,
    bootstrap_frame,
    effect_frame,
    is_p2p_frame,
)
from mug.participant_p2p_types import (
    P2PConnectionIdentity,
    P2PEdgeError,
    RoomEnd,
    browser_session_handle,
)
from mug.participant_screening import screen_frame
from mug.platform.deployment import is_live
from mug.providers import ModelCallResult
from mug.realtime import (
    Establish,
    FrameChannel,
    OnClose,
    OnGame,
    OnMeasure,
    OnOpen,
    RealtimeDispatch,
    Session,
    SessionRejected,
    read_frames,
)
from mug.replay import ReplayBundle, build_decision_tape, build_replay_bundle
from mug.replay.seal import SealOutcome, seal_run
from mug.returns import ReturnClaims, sign_return_link, verify_return_link
from mug.runtime import CommandContext, reject_command
from mug.storage import ArtifactStore, Store, stage_artifact
from mug.visits import StartVisitCommand, start_visit
from mug.visits.eligibility import eligibility_id_for, read_decision
from mug.visits.state import (
    StaleState,
    UndeclaredState,
    carry_state,
    read_all,
    readable,
    state_id,
    write_state,
)

_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_ENVELOPE_DIGEST = Digest(algorithm="sha-256", hex="0" * 64)
# Every draw a treatment makes is seeded from the server secret under this role, so
# a participant can not predict the condition they are about to be given.
_TREATMENT_SEED_ROLE = "treatment"


def _recorder(
    gateway: Gateway, store: Store, activity_key: str | None = None
) -> dict[str, Any]:
    """The staging arguments a capture needs to record what happened.

    Every backend is both an event store and an artifact store, so one instance
    serves both; the gateway stays the one identifier boundary. A capture given
    these records its trajectory artifact beside the ledger digests, so the study
    holds its data and can check it against the stream.

    ``activity_key`` names the study step the run belongs to, so a study that plays
    a practice round and a real one can later ask about one of them in particular.
    """
    return {
        "artifacts": cast("ArtifactStore", store),
        "new_artifact_id": lambda: gateway.new_id("artifact"),
        "new_upload_id": lambda: gateway.new_id("upload"),
        "now": _instant,
        "activity_key": activity_key,
    }


def _activity_key(session: Session) -> str | None:
    """Return the key of the game activity the session is at, if it is at one."""
    key = session.state.get("game_activity_key")
    return key if isinstance(key, str) else None


# Return the public client manifest for one browser game activity, minting its run
# identity the first time that activity is reached and holding it afterwards. A
# study with a practice round and a real round mints one identity for each, so the
# two runs are recorded beside each other. The establish hook builds this and puts
# it on the session, because the game activity is reached long after the mount is
# configured and every step in between only holds the session.
MintBrowserGame = Callable[["Session", str], dict[str, Any]]

# One game specification: the settings a study may name per game activity.
_Spec = TypeVar("_Spec")
_ADVANCE_CHANNEL = "flow.advance"
_CAPTURE_CHANNEL = "game.capture"
_STATE_CHANNEL = "state.set"
_CAPTURE_COMMAND = CommandTypeRef(name="game.capture", version=0)
_STATE_COMMAND = CommandTypeRef(name="state.set", version=0)
_SEAT_KEY = "player"
# The channel a single-participant game runs on, for its interaction record.
_GAME_CHANNEL = "game"
_INSTANT_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
# The return window: a participant resumes the visit with the return token for a
# day after entry. It outlasts the one-time launch ticket, so a participant can
# come back and finish after the ticket that admitted them has expired.
_RETURN_TTL_SECONDS = 86400


def _instant() -> str:
    """Return the current instant in the wire format the transitions carry."""
    return datetime.now(timezone.utc).strftime(_INSTANT_FORMAT)


def _fresh_idem(gateway: Gateway) -> str:
    """Mint one fresh, well-formed idempotency key for a server-side command."""
    body = gateway.new_id("request").split("_", 1)[1].replace("-", "")
    return "idem_" + body[:21] + "A"


def _envelope(
    command_name: str, target_id: str, data: dict[str, Any], idem: str
) -> WireCommandEnvelope:
    """Build a wire envelope for one server-side participant command."""
    schema = {
        "name": "mug.command-envelope",
        "version": 0,
        "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
    }
    return WireCommandEnvelope.model_validate(
        {
            "schema": schema,
            "protocol_version": "0.1.0",
            "command": {"name": command_name, "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-000000000001",
            "idempotency_key": idem,
            "target": {"id": target_id},
            "payload": {
                "schema": {
                    "name": "mug.edge.payload",
                    "version": 0,
                    "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
                },
                "data": data,
            },
        }
    )


def _queue(session: Session, delivery: dict[str, Any]) -> None:
    """Queue one activity delivery, and route the activity by its execution mode.

    A comparison activity marks the session ready as well, and the comparison mount
    owns the socket for it: what it asks about is the participant's own recorded
    runs, so it has to read the store before it can present anything.

    A server-mode game marks the session ready, so the transport runs the server
    stepping loop. A browser-mode game ships the public client manifest instead
    and waits for the client to report its run, so no server loop runs. A
    peer-mode game ships the mesh manifest and still marks the session ready: the
    hook owns the socket for the room, and the browsers play over their own data
    channels rather than over this one. A chat
    activity marks the session ready too: the chat mount owns the socket for the
    conversation exactly as the stepping loop owns it for an episode, so the client
    renders a conversation rather than a canvas.

    A study may hold more than one game activity. The activity the session is at
    is recorded here, because everything downstream is per activity: which
    specification runs, which run identity the episode is recorded under, and how
    long the countdown is.
    """
    kind = delivery.get("kind")
    session.state["activity_kind"] = kind
    # The occurrence is the step; the activity is what the author wrote. They differ
    # when a within-subject factor repeats an activity, and every record of what
    # happened at this step names the occurrence.
    session.state["occurrence_key"] = delivery.get("occurrence_key")
    if kind == "complete":
        return_url = session.state.get("return_url")
        if isinstance(return_url, str):
            delivery = {**delivery, "return_url": return_url}
    if kind == "comparison":
        session.state["comparison_activity_key"] = delivery.get("activity_key")
        session.deliver(delivery)
        session.state["run_game"] = True
        return
    if kind == "chat":
        # A conversation owns the socket the way a game does, so it is routed on the
        # same activity key. What is different is that it says what it is: the study
        # wrote a conversation, the record says "chat", and the screen that renders it
        # is asked for by name rather than inferred from a mode on a game.
        session.state["game_activity_key"] = delivery.get("activity_key")
        session.deliver(delivery)
        session.state["run_game"] = True
        return
    if kind == "game":
        activity_key = delivery.get("activity_key")
        session.state["game_activity_key"] = activity_key
        manifest = _browser_manifest(session)
        mesh_manifest = session.state.get("mesh_manifest")
        if session.state.get("chat_mode"):
            delivery = {**delivery, "mode": "chat"}
        elif manifest is not None:
            delivery = {**delivery, "mode": "browser", "manifest": manifest}
        elif isinstance(mesh_manifest, dict):
            delivery = {**delivery, "mode": "peer", "manifest": mesh_manifest}
        else:
            delivery = {**delivery, "mode": "server"}
        delivery = {**delivery, "countdown": _countdown(session)}
        caption = _caption_at(session)
        if caption is not None:
            delivery = {**delivery, "caption": caption}
        size = _size_at(session)
        if size is not None:
            delivery = {**delivery, "size": list(size)}
        composed = _composed_chat(session)
        if composed is not None:
            delivery = {**delivery, "chat": composed}
    session.deliver(delivery)
    if kind == "game" and (
        session.state.get("chat_mode") or _browser_manifest(session) is None
    ):
        session.state["run_game"] = True


def _composed_chat(session: Session) -> dict[str, Any] | None:
    """Say that this game activity also carries a conversation, and where it sits.

    It is what tells the client to mount two panes rather than one screen. Which
    channels this participant is in is *not* said here: that arrives once the room
    has formed, and only ever names channels they are in. Until then the pane says
    the conversation is forming, which is the truth.
    """
    activity_key = session.state.get("game_activity_key")
    if not isinstance(activity_key, str):
        return None
    study = _study_of(session)
    spec = study.chats.get(activity_key)
    if spec is None:
        return None
    placement = getattr(spec, "placement", "beside")
    return {"placement": placement if isinstance(placement, str) else "beside"}


def _countdown(session: Session) -> int:
    """Return the countdown for the game activity the session is at.

    A study that gives one game activity its own specification -- a practice round
    that starts at once, say -- gets that activity's countdown, not the mounted
    game's.
    """
    spec = _activity_spec(session)
    countdown = getattr(spec, "countdown_seconds", None)
    if isinstance(countdown, int):
        return countdown
    return cast("int", session.state.get("countdown_seconds", 0))


def _one_seat_interaction(
    interaction_id: str, session: Session, study_version: StudyVersionRef
) -> Interaction:
    """Build the interaction record one participant playing alone is in.

    A solo game is still an interaction: one visit, one seat, one channel. Recording
    it is what lets an operator see a single-participant study at all, and what
    gives a terminal reason somewhere to be written.
    """
    visit_id = cast("str", session.state.get("visit_id"))
    body = {"visit": visit_id, "interaction": interaction_id}
    return Interaction(
        interaction_id=interaction_id,  # pyright: ignore[reportArgumentType]
        study_version=study_version,
        visit_ids=[visit_id],  # pyright: ignore[reportArgumentType]
        cast={  # pyright: ignore[reportArgumentType]
            _SEAT_KEY: session.principal.id.replace("participant_", "actor_")
        },
        channels=[_GAME_CHANNEL],  # pyright: ignore[reportArgumentType]
        status="active",
        version=VersionStamp(revision=1, etag=etag(body)),
    )


async def _open_lifecycle(
    gateway: Gateway,
    store: Store,
    session: Session,
    interaction: Interaction,
) -> None:
    """Record that one interaction opened, at the activity it belongs to."""
    context = gateway.mint(
        _envelope(
            "interaction.open",
            interaction.interaction_id,
            {"interaction_id": interaction.interaction_id},
            _fresh_idem(gateway),
        ),
        principal=session.principal,
        data_handling=_RESEARCH,
    )
    await open_interaction(
        interaction,
        activity_key=_activity_key(session),
        opened_at=_instant(),
        context=context,
        store=store,
    )


async def _close_lifecycle(
    gateway: Gateway,
    store: Store,
    session: Session,
    interaction_id: str,
    reason: str,
    left: Sequence[str] = (),
) -> None:
    """Record why one interaction ended, once."""
    context = gateway.mint(
        _envelope(
            "interaction.finalize",
            interaction_id,
            {"interaction_id": interaction_id},
            _fresh_idem(gateway),
        ),
        principal=session.principal,
        data_handling=_RESEARCH,
    )
    await finalize_interaction(
        interaction_id=interaction_id,
        reason=reason,
        closed_at=_instant(),
        context=context,
        store=store,
        left=left,
    )


def _caption_at(session: Session) -> str | None:
    """Return what the participant reads beside the game activity they are at.

    A study that wrote none gives none, and the game stands on its own. This is
    where the hard-coded line about arrow keys and a flag used to be: one study's
    instructions, shipped to every study the platform ran.
    """
    key = session.state.get("game_activity_key")
    if not isinstance(key, str):
        return None
    return _study_of(session).captions.get(key)


def _size_at(session: Session) -> tuple[int, int] | None:
    """Return how large the picture the game activity draws is, if the study said.

    A drawing is relative, so it fills whatever it is given and only the study knows
    how large that should be. With none said the screen keeps its own 600 by 400.
    """
    key = session.state.get("game_activity_key")
    if not isinstance(key, str):
        return None
    return _study_of(session).sizes.get(key)


def _rounds_at(session: Session) -> Rounds:
    """Return how many rounds the game activity the session is at plays.

    A study that said nothing plays one round, which is what every study did before
    rounds existed.
    """
    key = session.state.get("game_activity_key")
    if not isinstance(key, str):
        return Rounds()
    return _study_of(session).rounds.get(key, Rounds())


def _activity_spec(session: Session) -> Any:
    """Return the specification the study named on the current game activity.

    An author writes ``Game("practice", spec)`` when one game activity runs
    different settings from another. With none named, this is None and the
    activity runs whatever the application mounted. When the author named a
    treatment there instead, the specification is the one this participant's
    assigned level names.
    """
    key = session.state.get("game_activity_key")
    if not isinstance(key, str):
        return None
    levels = session.state.get("levels")
    assigned = cast("dict[str, str]", levels) if isinstance(levels, dict) else {}
    return spec_for(_study_of(session), key, assigned)


def _spec_for(
    session: Session, kind: type[_Spec], mounted: _Spec | None
) -> _Spec | None:
    """Return the specification the game activity the session is at runs.

    The application mounts one game runtime, and a study may give one of its game
    activities its own settings under it -- a shorter practice round before the
    real one -- or name the whole specification there and mount nothing. A
    specification of another kind belongs to another mount, so it is not applied
    here.
    """
    spec = _activity_spec(session)
    return spec if isinstance(spec, kind) else mounted


def _browser_manifest(session: Session) -> dict[str, Any] | None:
    """Return the public client manifest for the game activity the session is at.

    The manifest carries the run identity, so each game activity gets its own: a
    study that plays a practice round and then the real one records two episodes
    beside each other, rather than the second overwriting the first. The identity
    is minted once per activity and held for the rest of the connection, so the
    capture that follows names the same episode the manifest announced.

    Returns None when the mount is not a browser game.
    """
    mint = session.state.get("mint_browser_game")
    key = session.state.get("game_activity_key")
    if mint is None or not isinstance(key, str):
        return None
    return cast("MintBrowserGame", mint)(session, key)


def _preload_manifest(session: Session) -> dict[str, Any] | None:
    """Return the bundle to boot the client runtime with, ahead of the game.

    The runtime downloads while the participant reads the consent page, so the
    game never waits at a blank canvas. A peer game boots the mesh bundle, which
    holds no room and no run identity and so is the same for every browser. A
    browser game boots the manifest of the study's first game activity; a later
    game activity boots nothing more, because the runtime is already there.
    """
    mesh = session.state.get("mesh_manifest")
    if isinstance(mesh, dict):
        return cast("dict[str, Any]", mesh)
    mint = session.state.get("mint_browser_game")
    keys = _study_of(session).game_keys
    if mint is None or not keys:
        return None
    return cast("MintBrowserGame", mint)(session, keys[0])


def _study_of(session: Session) -> Study:
    """Return the study this connection's flow was materialized from.

    The establish hook puts it there, so every later step -- presenting an
    activity, checking an answer, routing the game -- reads the same authored
    study the flow was opened with. A session that somehow carries none falls back
    to the demo study, which is what an unconfigured application runs anyway.
    """
    study = session.state.get("study")
    return study if isinstance(study, Study) else demo_study()


def _study_version_of(gateway: Gateway, session: Session) -> StudyVersionRef:
    """Return the study version this connection's visit runs against.

    An application built with ``build_study_app`` publishes its study before the
    first connection and puts the version here, so a plan names the real one. A
    connection with none -- a test that mounts the flow directly -- gets a derived
    stand-in rather than a refusal, and it is marked ``unpublished`` so nothing
    reads it as a published version.
    """
    found = session.state.get("study_version")
    if isinstance(found, StudyVersionRef):
        return found
    return StudyVersionRef(
        study_id=gateway.derived_id("study", "unpublished"),
        study_version_id=gateway.derived_id("studyver", "unpublished"),
        version_number=1,
        manifest_digest=compute_digest({"study": "unpublished"}),
    )


def _minting(gateway: Gateway, session: Session) -> MintContext:
    """Build the authority minter the treatment runtime asks for."""

    async def mint(command_name: str, aggregate_id: str) -> CommandContext:
        return gateway.mint(
            _envelope(
                command_name,
                aggregate_id,
                {"visit_id": session.state.get("visit_id")},
                _fresh_idem(gateway),
            ),
            principal=session.principal,
            data_handling=_RESEARCH,
        )

    return mint


def _answer_lookup(store: Store, gateway: Gateway, session: Session) -> AnswerLookup:
    """Build the reader a stratified factor waits on.

    It walks the same occurrence a form response was written to and opens the
    answers artifact, so the stratum is what the participant actually said rather
    than anything the connection carries.
    """

    async def answer(activity_key: str, field_key: str) -> Any:
        visit_id = session.state.get("visit_id")
        if not isinstance(visit_id, str):
            return None
        occurrence_id = occurrence_id_for(gateway.derived_id, visit_id, activity_key)
        reference = recorded_answers(store, occurrence_id)
        if reference is None:
            return None
        data = await cast("ArtifactStore", store).read_artifact(reference.artifact_id)
        return read_answers(data).get("answers", {}).get(field_key)

    return answer


async def _levels(gateway: Gateway, store: Store, session: Session) -> dict[str, str]:
    """Return what this participant is assigned, assigning anything now decidable.

    A study that manipulates nothing costs nothing: no derivation, no store read,
    no commit. Everything else reads the assignments it already has and writes only
    the ones that have become possible since -- a stratified factor whose form has
    now been answered.
    """
    study = _study_of(session)
    visit_id = session.state.get("visit_id")
    if not manipulates(study) or not isinstance(visit_id, str):
        return {}
    levels = await assign_visit(
        study,
        visit_id=visit_id,
        study_version=_study_version_of(gateway, session),
        store=store,
        derive=gateway.derived_id,
        seed=_seeding(gateway),
        now=_instant,
        mint=_minting(gateway, session),
        answer=_answer_lookup(store, gateway, session),
    )
    # The game hooks resolve their specification synchronously, so the levels are
    # held here for them rather than read from the store again mid-episode.
    session.state["levels"] = levels
    return levels


async def _advance(
    gateway: Gateway,
    store: Store,
    session: Session,
    answers: dict[str, Any],
    idem: str,
    captured_streams: list[str] | None = None,
) -> tuple[CommandReceipt, dict[str, Any] | None]:
    """Advance the flow one step and return the receipt and the next delivery."""
    flow_id = cast("str", session.state["flow_id"])
    revision = int(session.state["flow_revision"])
    streams = captured_streams or []
    envelope = _envelope(
        "flow.advance",
        flow_id,
        {
            "answers": answers,
            "expected_revision": revision,
            "captured_streams": streams,
        },
        idem,
    )
    context = gateway.mint(
        envelope, principal=session.principal, data_handling=_RESEARCH
    )
    study = _study_of(session)
    receipt = await advance_flow(
        AdvanceFlowCommand(
            answers=answers, expected_revision=revision, captured_streams=streams
        ),
        study=study,
        context=context,
        store=store,
        on_answers=_answer_recorder(gateway, store, session),
        levels=lambda: _levels(gateway, store, session),
    )
    if receipt.outcome != "accepted":
        return receipt, None
    session.state["flow_revision"] = revision + 1
    # The advance may have answered the form a stratified factor was waiting on, so
    # the levels are read again here: the step now being presented is the first one
    # that can carry that condition.
    return receipt, await _at_pointer(gateway, store, session)


async def _at_pointer(
    gateway: Gateway, store: Store, session: Session
) -> dict[str, Any] | None:
    """Return the delivery for the step the flow is on, and record its exposure.

    The exposure is written here rather than at materialization because this is
    where the participant actually meets the activity. An assignment says what they
    were given; an exposure says they arrived to be given it.
    """
    flow_id = cast("str", session.state["flow_id"])
    state = flow_of(store.load_aggregate(flow_id))
    if state is None:
        return None
    study = _study_of(session)
    levels = await _levels(gateway, store, session)
    delivery = present(state, study, levels)
    carried = await _readable_state(gateway, store, session)
    if carried is not None:
        # What the participant carries travels with the step they are on, so a page
        # renders from what earlier activities wrote without asking for it first.
        delivery["state"] = carried
    await _expose(gateway, store, session, state, levels)
    return delivery


async def _readable_state(
    gateway: Gateway, store: Store, session: Session
) -> dict[str, dict[str, Any]] | None:
    """Return what this participant may read of their own state, if the study keeps any.

    A study that declares no namespace gets none, and every delivery is exactly what
    it was before a study could keep anything. Only the namespaces declared readable
    by the participant travel: one a study keeps to itself never reaches the page
    that would otherwise show it to them.
    """
    study = _study_of(session)
    visit_id = session.state.get("visit_id")
    if not study.state or not isinstance(visit_id, str):
        return None
    return await read_all(
        store,
        derive=gateway.derived_id,
        visit_id=visit_id,
        namespaces=readable(study.state),
    )


async def _expose(
    gateway: Gateway,
    store: Store,
    session: Session,
    state: FlowState,
    levels: dict[str, str],
) -> None:
    """Record that the step the flow is on delivered the levels in force there."""
    study = _study_of(session)
    visit_id = session.state.get("visit_id")
    if state.status == "completed" or not manipulates(study):
        return
    if not isinstance(visit_id, str):
        return
    active = state.activities[state.pointer]
    await record_exposures(
        study,
        activity_key=active.activity_key,
        occurrence_id=occurrence_id_for(gateway.derived_id, visit_id, active.key),
        visit_id=visit_id,
        levels={**levels, **active.within},
        store=store,
        derive=gateway.derived_id,
        now=_instant,
        mint=_minting(gateway, session),
    )


def _answer_recorder(gateway: Gateway, store: Store, session: Session) -> RecordAnswers:
    """Build the recorder that turns one validated form submission into evidence.

    This is the impure half the content layer does not hold: the derivation, the
    clock, and the object store. The occurrence identifier derives from the visit
    and the form key, so a participant who submits twice reaches one aggregate and
    the store replays the second submission instead of recording it again.
    """

    async def record(form: FormSpec, answers: dict[str, Any]) -> bool:
        visit_id = session.state.get("visit_id")
        if not isinstance(visit_id, str):
            return False
        # A form the study repeats is answered once per occurrence, so the record
        # is written to the step the participant is on rather than to the form.
        step = session.state.get("occurrence_key")
        occurrence_id = occurrence_id_for(
            gateway.derived_id,
            visit_id,
            step if isinstance(step, str) else form.form_key,
        )
        if recorded_answers(store, occurrence_id) is not None:
            # Already answered on an earlier connection: the first submission is
            # canonical and the flow may move on.
            return True
        context = gateway.mint(
            _envelope(
                "form.submit",
                occurrence_id,
                {"form_key": form.form_key, "visit_id": visit_id},
                _fresh_idem(gateway),
            ),
            principal=session.principal,
            data_handling=_RESEARCH,
        )
        receipt, _ = await record_form_answers(
            form=form,
            answers=answers,
            visit_id=visit_id,
            occurrence_id=occurrence_id,
            submitted_at=_instant(),
            context=context,
            store=store,
            artifacts=cast("ArtifactStore", store),
            new_artifact_id=lambda: gateway.new_id("artifact"),
            new_upload_id=lambda: gateway.new_id("upload"),
            now=_instant,
        )
        return receipt.outcome == "accepted"

    return record


async def _materialize(
    gateway: Gateway, store: Store, session: Session, visit_id: str
) -> str | None:
    """Materialize one flow for a visit and seed the session pointers.

    The factors are assigned before the plan is drafted, because the plan records
    what each step will deliver and it can not say that without the levels. A
    stratified factor is not assignable yet -- its form has not been answered --
    and the advance that answers it restates the steps ahead.

    Returns the flow id, or None when the materialize command does not commit.
    """
    flow_id = gateway.new_id("visitplan")
    envelope = _envelope(
        "flow.materialize", flow_id, {"visit_id": visit_id}, _fresh_idem(gateway)
    )
    context = gateway.mint(
        envelope, principal=session.principal, data_handling=_RESEARCH
    )
    session.state["visit_id"] = visit_id
    study = _study_of(session)
    study_version = _study_version_of(gateway, session)
    seed = _seeding(gateway)
    levels = await _levels(gateway, store, session)
    orders = (
        await visit_orders(
            study,
            visit_id=visit_id,
            study_version=study_version,
            store=store,
            derive=gateway.derived_id,
            seed=seed,
            mint=_minting(gateway, session),
        )
        if manipulates(study)
        else {}
    )
    receipt = await materialize_flow(
        MaterializeFlowCommand(visit_id=visit_id),
        study=study,
        study_version=study_version,
        context=context,
        store=store,
        derive=gateway.derived_id,
        seed=seed,
        levels=levels,
        orders=orders,
        materialized_at=_instant(),
    )
    if receipt.outcome != "accepted":
        return None
    session.state["flow_id"] = flow_id
    session.state["flow_revision"] = 1
    return flow_id


def _refuse_a_part_this_deployment_cannot_serve(
    store: Store, session: Session, study_version: StudyVersionRef | None
) -> None:
    """Refuse a return into an unfinished part this deployment does not serve.

    One deployment serves one study version. A participant who was **part way
    through** a part when a newer version was deployed cannot be presented that
    part -- the activities they were on are not in the study now running -- and
    they must not be moved into the next part either, because that would abandon
    the part they were in and the plan committed for it (D05-1).

    So they are refused, safely and explicitly, rather than shown an activity from
    a study nobody is running. Serving several versions at once is what would fix
    it for them, and that is a deployment question this platform has not answered.
    """
    visit_id = session.state.get("visit_id")
    if study_version is None or not isinstance(visit_id, str):
        return
    visit = store.load_aggregate(visit_id)
    if not isinstance(visit, dict):
        return
    pinned = cast("dict[str, Any]", visit).get("study_version")
    if not isinstance(pinned, dict):
        return
    was = cast("dict[str, Any]", pinned).get("study_version_id")
    if was == study_version.study_version_id:
        return
    raise SessionRejected(
        "policy.version_unavailable",
        "policy",
        "the part you were in is not the one this deployment is serving",
    )


async def _next_part(
    gateway: Gateway,
    store: Store,
    session: Session,
    study_version: StudyVersionRef | None,
    deployment: DeploymentRevisionRef | None,
) -> str | None:
    """Open the next part of a multi-part study, when the participant is due one.

    A participant is due one when they have **finished** the part they were in and
    the deployment now serves a **different** study version from the one that visit
    was pinned to. That is what a second part is: the same person, the same
    enrollment, a new visit under the version now running (NS-08). Any other return
    -- mid-part, or the same version -- resumes what they were doing, which is what
    a return link has always done.

    What they built up is carried into the new visit, for the namespaces this part
    declares and no others. Returns the new flow id, or None when no new part is
    due.
    """
    flow_id = session.state.get("flow_id")
    visit_id = session.state.get("visit_id")
    enrollment_id = session.state.get("enrollment_id")
    if study_version is None or not isinstance(flow_id, str):
        return None
    if not isinstance(visit_id, str) or not isinstance(enrollment_id, str):
        return None
    state = flow_of(store.load_aggregate(flow_id))
    if state is None or state.status != "completed":
        return None
    visit = store.load_aggregate(visit_id)
    if not isinstance(visit, dict):
        return None
    pinned = cast("dict[str, Any]", visit).get("study_version")
    if not isinstance(pinned, dict):
        return None
    was = cast("dict[str, Any]", pinned).get("study_version_id")
    if was == study_version.study_version_id:
        return None

    if deployment is None:
        return None
    started = gateway.new_id("visit")
    receipt = await start_visit(
        StartVisitCommand(
            enrollment_id=enrollment_id,
            study_id=study_version.study_id,
            study_version=study_version,
            deployment=deployment,
        ),
        context=gateway.mint(
            _envelope(
                "visit.start",
                started,
                {"enrollment_id": enrollment_id},
                _fresh_idem(gateway),
            ),
            principal=session.principal,
            data_handling=_RESEARCH,
        ),
        store=store,
    )
    if receipt.outcome != "accepted":
        return None
    await _carry_earlier_state(gateway, store, session, enrollment_id, started)
    return await _materialize(gateway, store, session, started)


def _seeding(gateway: Gateway) -> Callable[[str], bytes]:
    """Return the seed source every treatment draw reads."""
    return lambda role: gateway.derived_seed(_TREATMENT_SEED_ROLE, role)


async def _resume(store: Store, session: Session, flow_id: str) -> bool:
    """Rehydrate the flow pointer, and restore the enrollment identity if present.

    A launch-gated flow was started for a durable enrollment: the resume walks the
    flow to its visit to its enrollment and rebinds the session principal, so a
    reconnection continues the same pseudonymous participant rather than minting a
    second research identity. A non-gated flow has no visit or enrollment record,
    so the walk finds none and the provisional principal stands.
    """
    state = flow_of(store.load_aggregate(flow_id))
    if state is None:
        return False
    visit = store.load_aggregate(state.visit_id)
    if isinstance(visit, dict):
        enrollment_id = cast("dict[str, Any]", visit).get("enrollment_id")
        enrollment = (
            store.load_aggregate(enrollment_id)
            if isinstance(enrollment_id, str)
            else None
        )
        if isinstance(enrollment, dict):
            session.state["enrollment_id"] = enrollment_id
            principal = cast("dict[str, Any]", enrollment).get("principal")
            if isinstance(principal, dict):
                session.principal = PrincipalRef.model_validate(principal)
    session.state["flow_id"] = flow_id
    session.state["visit_id"] = state.visit_id
    session.state["flow_revision"] = state.version.revision
    return True


def _refuse_ineligible(gateway: Gateway, store: Store, session: Session) -> None:
    """Refuse a reconnection to a visit that was already screened out.

    The decision is durable, so reloading the page is not a way to be judged again.
    It is checked before the handshake, so a refused participant never reaches an
    activity a second time.
    """
    visit_id = session.state.get("visit_id")
    if not isinstance(visit_id, str):
        return
    decision = read_decision(store, eligibility_id_for(gateway.derived_id, visit_id))
    if decision is not None and not decision.admitted:
        raise SessionRejected("policy.excluded", "policy", decision.reason)


def _redeem_ticket(store: Store, session: Session) -> LaunchTicket:
    """Redeem the presented launch ticket, or refuse the connection.

    The ticket handle rides the connection as the ``ticket`` query parameter. A
    missing, unknown, malformed, or expired ticket refuses entry with a safe
    authentication error that names no ticket value.
    """
    handle = session.state.get("ticket")
    if not isinstance(handle, str):
        raise SessionRejected(
            "auth.unauthenticated",
            "authentication",
            "a launch ticket is required to enter",
        )
    raw = store.load_token(handle)
    if raw is None:
        raise SessionRejected(
            "auth.unauthenticated", "authentication", "the launch ticket is not valid"
        )
    try:
        ticket = LaunchTicket.model_validate(raw)
    except ValidationError as error:
        raise SessionRejected(
            "auth.unauthenticated", "authentication", "the launch ticket is not valid"
        ) from error
    expires_at = datetime.strptime(ticket.expires_at, _INSTANT_FORMAT).replace(
        tzinfo=timezone.utc
    )
    if expires_at <= datetime.now(timezone.utc):
        raise SessionRejected(
            "auth.ticket_expired", "authentication", "the launch ticket has expired"
        )
    return ticket


async def _enter_with_ticket(
    gateway: Gateway, store: Store, session: Session
) -> str | None:
    """Redeem the ticket, enroll the participant, start the visit, open the flow.

    The provisional principal the transport minted becomes the enrollment's
    durable pseudonymous participant. The visit gates on that active enrollment,
    and the flow materializes for the visit. Returns the flow id, or None when a
    step after redemption does not commit. Refusal to redeem raises upward.
    """
    ticket = _redeem_ticket(store, session)

    enrollment_id = gateway.new_id("enrollment")
    envelope = _envelope(
        "enrollment.enroll",
        enrollment_id,
        {"study_id": ticket.study_id},
        _fresh_idem(gateway),
    )
    context = gateway.mint(
        envelope, principal=session.principal, data_handling=_RESEARCH
    )
    enrolled = await enroll(
        EnrollCommand(study_id=ticket.study_id), context=context, store=store
    )
    if enrolled.outcome != "accepted":
        return None

    visit_id = gateway.new_id("visit")
    envelope = _envelope(
        "visit.start", visit_id, {"enrollment_id": enrollment_id}, _fresh_idem(gateway)
    )
    context = gateway.mint(
        envelope, principal=session.principal, data_handling=_RESEARCH
    )
    started = await start_visit(
        StartVisitCommand(
            enrollment_id=enrollment_id,
            study_id=ticket.study_id,
            study_version=ticket.deployment.study_version,
            deployment=ticket.deployment,
        ),
        context=context,
        store=store,
    )
    if started.outcome != "accepted":
        return None

    session.state["enrollment_id"] = enrollment_id
    await _carry_earlier_state(gateway, store, session, enrollment_id, visit_id)
    return await _materialize(gateway, store, session, visit_id)


def _earlier_visit(store: Store, enrollment_id: str, visit_id: str) -> str | None:
    """Return the most recent earlier visit of one enrollment, if it had one.

    A participant who comes back for a later part of a study enters a **new** visit
    under the enrollment they already hold. The visits are ordered by their own
    identifiers, which are time-ordered, so the latest earlier one is the part they
    were last in.
    """
    found: list[str] = []
    for aggregate_id, state in store.scan_aggregates():
        if not aggregate_id.startswith("visit_") or aggregate_id == visit_id:
            continue
        if not isinstance(state, dict):
            continue
        head = cast("dict[str, Any]", state)
        if head.get("enrollment_id") == enrollment_id:
            found.append(aggregate_id)
    return max(found) if found else None


async def _carry_earlier_state(
    gateway: Gateway,
    store: Store,
    session: Session,
    enrollment_id: str,
    visit_id: str,
) -> None:
    """Carry what an earlier part of this study kept into the part now starting.

    **Only the namespaces this part declares are carried** (NS-08). A study version
    that dropped a namespace does not receive it, which is a statement about scope
    rather than about storage: state a later part never declared is state its
    participants were never told it would read.
    """
    study = _study_of(session)
    if not study.state:
        return
    earlier = _earlier_visit(store, enrollment_id, visit_id)
    if earlier is None:
        return
    await carry_state(
        store,
        new_context=lambda aggregate_id: gateway.mint(
            _envelope(
                "state.carry",
                aggregate_id,
                {"from_visit": earlier, "into_visit": visit_id},
                _fresh_idem(gateway),
            ),
            principal=session.principal,
            data_handling=_RESEARCH,
        ),
        states=study.state,
        derive=gateway.derived_id,
        new_id=gateway.new_id,
        now=_instant,
        from_visit=earlier,
        into_visit=visit_id,
    )


def _return_token(signing_key: bytes, flow_id: str) -> str:
    """Sign one return token for a flow, with the return window as its expiry."""
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=_RETURN_TTL_SECONDS)
    ).strftime(_INSTANT_FORMAT)
    claims = ReturnClaims(flow_id=flow_id, expires_at=expires_at)
    return sign_return_link(signing_key, claims)


def _resume_flow_id(signing_key: bytes, token: str) -> tuple[str | None, str]:
    """Verify one return token and return ``(flow_id, status)``.

    ``status`` is ``"ok"`` with a flow id when the signature matches and the
    token is in its window, ``"expired"`` when the signature matches but the
    window has passed, or ``"invalid"`` when the token is malformed or the
    signature does not match. A tampered token never reports ``"ok"``, so it can
    not resume another participant's visit.
    """
    claims = verify_return_link(signing_key, token)
    if claims is None:
        return None, "invalid"
    expires_at = datetime.strptime(claims.expires_at, _INSTANT_FORMAT).replace(
        tzinfo=timezone.utc
    )
    if expires_at <= datetime.now(timezone.utc):
        return None, "expired"
    return claims.flow_id, "ok"


def _refuse_return(status: str) -> None:
    """Refuse a reconnection whose return token does not verify (gated study).

    A gated study carries no launch ticket on a reconnection, so a bad return
    token can not fall back to a fresh entry. An expired token reports its own
    code, so the client can prompt for a new launch link; any other failure is a
    generic authentication refusal that names no token value.
    """
    if status == "expired":
        raise SessionRejected(
            "auth.return_link_expired",
            "authentication",
            "the return link has expired",
        )
    raise SessionRejected(
        "auth.unauthenticated",
        "authentication",
        "the return link is not valid",
    )


def _build_mint_browser_game(
    gateway: Gateway, mounted: BrowserGameSpec
) -> MintBrowserGame:
    """Build the per-activity manifest minter for a browser game mount.

    The server never trusts a client for identity: the episode and interaction ids
    are minted here and shipped in the manifest the activity announces. One
    activity is minted once, however many times it is presented, so a reconnection
    that lands back on the same game reports its run under the identity it was
    already given.
    """

    def mint(session: Session, activity_key: str) -> dict[str, Any]:
        minted = cast(
            "dict[str, dict[str, Any]]",
            session.state.setdefault("browser_manifests", {}),
        )
        if activity_key not in minted:
            spec = _study_of(session).games.get(activity_key)
            minted[activity_key] = client_manifest(
                spec if isinstance(spec, BrowserGameSpec) else mounted,
                episode_id=gateway.new_id("episode"),
                interaction_id=gateway.new_id("interaction"),
                seat_key=_SEAT_KEY,
            )
        return minted[activity_key]

    return mint


def build_establish(
    gateway: Gateway,
    store: Store,
    return_url: str | None = None,
    browser: BrowserGameSpec | None = None,
    countdown_seconds: int = 0,
    launch: bool = False,
    *,
    signing_key: bytes,
    chat: bool = False,
    mesh_manifest: dict[str, Any] | None = None,
    study: Study | None = None,
    deployment: DeploymentRevisionRef | None = None,
    study_version: StudyVersionRef | None = None,
    assets: Mapping[str, Any] | None = None,
) -> Establish:
    """Build the establish hook that resumes or opens the flow before handshake.

    On a reconnection that presents a ``resume_token``, it verifies the token
    under ``signing_key`` and, when the signature matches and the window holds,
    rehydrates that flow instead of starting over, so the participant continues
    where they stopped. On a fresh connection with ``launch`` set it redeems the
    launch ticket, enrolls the participant, starts the visit, and materializes the
    flow -- and refuses entry without a valid ticket. With ``launch`` unset it
    materializes a flow for an anonymous per-connection subject (the open demo
    mode). It returns a signed return token as the ``resume_token`` for the
    handshake, so the client stores it and presents it on its next connection.

    A gated study refuses a reconnection whose return token does not verify or has
    expired, because it carries no launch ticket to fall back on; the open demo
    instead opens a fresh flow. The token is signed, so a stolen or guessed flow
    id can not resume a visit -- only a token the server issued does.

    ``return_url`` is the deployment's return link; the completed flow presents it
    with the completion code. ``browser`` is set for a browser-executed game: the
    server mints the episode and interaction ids and the public client manifest,
    so the client runs the environment and reports its run under those ids. ``chat``
    is set when the study's activity is a conversation rather than a game, so the
    delivery names the chat mode and the client renders a conversation.
    ``mesh_manifest`` is the public bundle for a browser-executed peer-to-peer
    game. It holds no room and no actor, so it is the same for every browser: the
    client boots it during the forms and joins its mesh with the runtime ready.
    ``study`` is the ordered activities the participant walks through; it defaults
    to the demo study, so an application that configures none still runs.

    ``deployment`` is the revision this process serves. When it is set the hook
    refuses entry to a **stopped** deployment -- which is what pausing recruitment
    means -- and tells the client which revision it is running against, so a client
    built for another one can say so and be refused (see ``mug.platform.deployment``).
    """

    async def establish(session: Session) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if deployment is not None:
            if not is_live(store, deployment.deployment_id):
                raise SessionRejected(
                    "resource.conflict",
                    "conflict",
                    "this study is not accepting participants",
                )
            session.state["deployment_revision_id"] = deployment.deployment_revision_id
            # The client is told which revision it is running against, so a build
            # made for another one can pin what it accepted and be refused.
            extra["deployment"] = {
                "deployment_id": deployment.deployment_id,
                "deployment_revision_id": deployment.deployment_revision_id,
                "revision_number": deployment.revision_number,
            }
        # The study is fixed for the deployment, and every later step reads it
        # from here: the activities the flow opens with, the form an answer is
        # checked against, and the activity the game hook runs.
        running = study or demo_study()
        session.state["study"] = running
        if assets:
            # The pictures the study declared, each at the address of its own
            # bytes. The client loads them while the participant is on the forms,
            # so the first frame that draws one is not the frame that fetches it.
            extra["assets"] = dict(assets)
        if running.screen is not None:
            # The client is told to measure and how often. A study that declares no
            # screen is told nothing, so its clients send no samples at all.
            extra["screening"] = {"sample_every_ms": running.screen.sample_every_ms}
        if study_version is not None:
            # The plan names the version it runs against, so a study that was
            # published (every application built by ``build_study_app``) plans
            # against the real one rather than a stand-in.
            session.state["study_version"] = study_version
        if return_url is not None:
            session.state["return_url"] = return_url
        session.state["countdown_seconds"] = countdown_seconds
        if chat:
            session.state["chat_mode"] = True
        if mesh_manifest is not None:
            session.state["mesh_manifest"] = mesh_manifest
        if browser is not None:
            session.state["mint_browser_game"] = _build_mint_browser_game(
                gateway, browser
            )
        token = session.state.get("resume_token")
        if isinstance(token, str):
            resumed_id, status = _resume_flow_id(signing_key, token)
            if resumed_id is not None and await _resume(store, session, resumed_id):
                _refuse_ineligible(gateway, store, session)
                # A return link brings a participant back. If the part they
                # finished is not the part now being served, it brings them into
                # the next one instead of re-presenting the one they completed.
                nxt = await _next_part(
                    gateway, store, session, study_version, deployment
                )
                if nxt is not None:
                    return {
                        **extra,
                        "resume_token": _return_token(signing_key, nxt),
                    }
                _refuse_a_part_this_deployment_cannot_serve(
                    store, session, study_version
                )
                return {**extra, "resume_token": token}
            if launch:
                _refuse_return(status)
        if launch:
            flow_id = await _enter_with_ticket(gateway, store, session)
        else:
            flow_id = await _materialize(
                gateway, store, session, gateway.new_id("visit")
            )
        if flow_id is None:
            return extra
        return {**extra, "resume_token": _return_token(signing_key, flow_id)}

    return establish


def build_close(
    gateway: Gateway, store: Store, browser: BrowserGameSpec | None
) -> OnClose:
    """Build the hook that seals a run the participant walked away from.

    A browser game is reported in parts while it is played, and the last part is the
    one that says the round ended. A participant who shuts the tab, loses their
    network, or puts the machine to sleep never sends it -- so the run sits open with
    everything they did already staged, and this is what turns that into a recorded
    episode rather than nothing.

    A study with no browser game has no such run and the hook does nothing, so it
    costs one comparison per disconnect.

    Sealing here is best effort by design. The connection has already gone, so there
    is nobody to tell and nothing to retry into; what makes this safe rather than
    lossy is that the parts are durable already and the sweep
    (``mug.game.capture_parts.unsealed_runs``) seals anything this misses.
    """

    async def on_close(session: Session) -> None:
        if browser is None:
            return
        manifest = _browser_manifest(session)
        if manifest is None:
            return
        episode_id = cast("str", manifest.get("episode_id", ""))
        progress = read_progress(store, episode_id) if episode_id else None
        if progress is None or progress.sealed:
            return
        spec = _activity_spec(session)
        outcome = await _seal_client_episode(
            gateway,
            store,
            session,
            spec if isinstance(spec, BrowserGameSpec) else browser,
            episode_id,
        )
        log_line(
            "browser.sealed_on_close",
            episode_id=episode_id,
            frames=outcome.frames,
            recorded=outcome.recorded,
            reason=outcome.reason or "",
        )

    return on_close


def build_measure(gateway: Gateway, store: Store) -> OnMeasure:
    """Build the hook that screens one client quality frame.

    A study that declares no screen and no entry rule answers None to everything, so
    it costs one dictionary lookup per frame and writes nothing.
    """

    async def on_measure(
        session: Session, frame: dict[str, Any]
    ) -> dict[str, Any] | None:
        study = _study_of(session)
        if study.screen is None and study.admit is None:
            return None
        return await screen_frame(
            frame,
            session=session,
            study=study,
            study_version_id=_study_version_of(gateway, session).study_version_id,
            store=store,
            derive=gateway.derived_id,
            mint=_minting(gateway, session),
            now=_instant,
        )

    return on_measure


def build_open(gateway: Gateway, store: Store) -> OnOpen:
    """Build the open hook that presents the flow's current activity.

    The flow is already established (fresh or resumed). A browser game announces
    its bundle first, so the client boots Pyodide and installs the packages during
    the forms and the game never waits on a blank canvas. A browser peer-to-peer
    game announces its mesh bundle the same way, which matters more there: the
    peers cross a start barrier together, so a browser that booted late would hold
    up every other browser in its room. Then the current activity is presented, so
    a reconnection resumes where the participant stopped.
    """

    async def on_open(session: Session) -> None:
        flow_id = session.state.get("flow_id")
        if not isinstance(flow_id, str):
            return
        manifest = _preload_manifest(session)
        if manifest is not None:
            session.deliver({"kind": "preload", "manifest": manifest})
        delivery = await _at_pointer(gateway, store, session)
        if delivery is not None:
            _queue(session, delivery)

    return on_open


def build_dispatch(
    gateway: Gateway, store: Store, browser: BrowserGameSpec | None = None
) -> RealtimeDispatch:
    """Build the dispatch that advances the flow on a participant command.

    ``flow.advance`` steps the flow forward as the participant answers a form. A
    browser game also routes ``game.capture``: the client reports its finished
    run, the server validates it into the transition contract, commits it under
    browser authority and a producer generation, and advances past the game.
    ``state.set`` writes one namespace of what the participant carries between
    activities, against the revision the page read.
    """

    async def dispatch(
        command: RealtimeCommand, payload: Any, session: Session
    ) -> CommandReceipt | None:
        if not isinstance(session.state.get("flow_id"), str):
            return None
        data = cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}
        if command.channel_key == _STATE_CHANNEL:
            return await _write_participant_state(
                gateway, store, session, data, command.idempotency_key
            )
        if command.channel_key == _ADVANCE_CHANNEL:
            answers = cast("dict[str, Any]", data.get("answers", {}))
            receipt, delivery = await _advance(
                gateway, store, session, answers, command.idempotency_key
            )
            if delivery is not None:
                _queue(session, delivery)
            return receipt
        if command.channel_key == _CAPTURE_CHANNEL and browser is not None:
            return await _capture_client_episode(
                gateway, store, session, browser, data, command.idempotency_key
            )
        return None

    return dispatch


async def _write_participant_state(
    gateway: Gateway,
    store: Store,
    session: Session,
    data: dict[str, Any],
    idem: str,
) -> CommandReceipt | None:
    """Write one namespace the page named, against the revision it read.

    Everything the page asserts is checked against what the **study** declared: a
    namespace nobody declared, and one the participant may not write, are both
    refused rather than opened. A write that names a revision the namespace has
    moved past is refused as a conflict and told the revision it lost to, so the
    page re-reads instead of overwriting somebody else's tab.
    """
    study = _study_of(session)
    visit_id = session.state.get("visit_id")
    namespace = data.get("namespace")
    value = data.get("value")
    if not isinstance(visit_id, str) or not isinstance(namespace, str):
        return None
    if not isinstance(value, dict):
        return None
    revision = data.get("revision", 0)
    context = gateway.mint(
        _envelope(
            _STATE_CHANNEL,
            state_id(gateway.derived_id, visit_id, namespace),
            {"namespace": namespace, "revision": revision},
            idem,
        ),
        principal=session.principal,
        data_handling=_RESEARCH,
    )
    try:
        written = await write_state(
            store,
            context=context,
            states=study.state,
            derive=gateway.derived_id,
            new_id=gateway.new_id,
            now=_instant,
            visit_id=visit_id,
            namespace=namespace,
            value=cast("dict[str, Any]", value),
            revision=int(revision) if isinstance(revision, int) else 0,
        )
    except UndeclaredState as refusal:
        return reject_command(
            context,
            command=_STATE_COMMAND,
            code="request.invalid",
            category="validation",
            message=str(refusal),
            retry="never",
        )
    except StaleState as conflict:
        return reject_command(
            context,
            command=_STATE_COMMAND,
            code="command.state_conflict",
            category="conflict",
            message=str(conflict),
            retry="refresh_then_new_command",
        )
    return written.receipt


def _run_identity(
    session: Session, manifest: dict[str, Any], browser: BrowserGameSpec, data: Any
) -> RunIdentity:
    """Everything the seal will need, written where a later process can read it."""
    return RunIdentity(
        episode_id=cast("str", manifest["episode_id"]),
        interaction_id=cast("str", manifest["interaction_id"]),
        channel_key=browser.channel_key,
        visit_id=cast("str", session.state["visit_id"]),
        seat_key=_SEAT_KEY,
        activity_key=_activity_key(session),
        generation=_generation_of(data),
    )


async def _seal_client_episode(
    gateway: Gateway,
    store: Store,
    session: Session,
    browser: BrowserGameSpec,
    episode_id: str,
) -> SealOutcome:
    """Close one reported run: assemble the parts, verify them, record the episode."""
    progress = read_progress(store, episode_id)
    if progress is None:
        return SealOutcome(recorded=False, frames=0, closed=False, reason="no-parts")
    return await seal_run(
        progress,
        spec=browser,
        capture_context=gateway.mint(
            _envelope(
                "game.capture",
                episode_id,
                {"episode_id": episode_id},
                _fresh_idem(gateway),
            ),
            principal=session.principal,
            data_handling=_RESEARCH,
        ),
        sealed_context=gateway.mint(
            _envelope(
                "game.capture",
                progress_aggregate_id(episode_id),
                {"episode_id": episode_id, "sealed": True},
                _fresh_idem(gateway),
            ),
            principal=session.principal,
            data_handling=_RESEARCH,
        ),
        epoch_id=gateway.new_id("prodepoch"),
        store=store,
        artifacts=cast("ArtifactStore", store),
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=_instant,
    )


async def _capture_client_episode(
    gateway: Gateway,
    store: Store,
    session: Session,
    browser: BrowserGameSpec,
    data: dict[str, Any],
    idem: str,
) -> CommandReceipt:
    """Take one reported part of a run, and seal the run when the client closes it.

    A browser game is written by the participant's own client and reported while it
    is played. A part that is not the last is staged and acknowledged and the flow
    stays where it is; the closing part seals the run, which is where the server
    re-executes what arrived, matches every state hash, and commits the episode.

    A client that reports the whole run in one command names no ``first_frame`` and
    no ``final``, so it is one part that is also the last, and it behaves exactly as
    it always did.
    """
    manifest = _browser_manifest(session) or {}
    activity_spec = _activity_spec(session)
    if isinstance(activity_spec, BrowserGameSpec):
        browser = activity_spec
    episode_id = cast("str", manifest["episode_id"])
    run = _run_identity(session, manifest, browser, data)
    part_context = gateway.mint(
        _envelope(
            "game.capture",
            progress_aggregate_id(episode_id),
            {"episode_id": episode_id},
            idem,
        ),
        principal=session.principal,
        data_handling=_RESEARCH,
    )
    try:
        part = parse_client_part(
            data,
            expected_channel_key=browser.channel_key,
            expected_episode_id=episode_id,
        )
    except ClientEpisodeError:
        return reject_command(
            part_context,
            command=_CAPTURE_COMMAND,
            code="schema.validation_failed",
            category="validation",
            message="the reported part did not validate",
            retry="never",
        )
    try:
        receipt = await record_part(
            part,
            run=run,
            context=part_context,
            store=store,
            artifacts=cast("ArtifactStore", store),
            new_artifact_id=lambda: gateway.new_id("artifact"),
            new_upload_id=lambda: gateway.new_id("upload"),
            now=_instant,
        )
    except PartOutOfOrder as refusal:
        return reject_command(
            part_context,
            command=_CAPTURE_COMMAND,
            code="request.invalid",
            category="validation",
            message=str(refusal),
            retry="never",
        )
    if not part.final:
        # The round is still being played. The part is durable now, which is the
        # whole point: what happens to the tab from here costs the tail and not the
        # run. Nothing advances, because the participant is still in the game.
        return receipt

    outcome = await _seal_client_episode(gateway, store, session, browser, episode_id)
    if not outcome.recorded:
        return reject_command(
            part_context,
            command=_CAPTURE_COMMAND,
            code="game.verification_failed",
            category="validation",
            message="the reported episode did not match the re-execution",
            retry="never",
        )
    sealed = outcome.receipt
    assert sealed is not None
    # The visit records the stream the *episode* landed on, not the stream the
    # parts were reported on: the export follows it to find the run's boundary.
    _, delivery = await _advance(
        gateway, store, session, {}, _fresh_idem(gateway), [outcome.stream_id or ""]
    )
    if delivery is not None:
        _queue(session, delivery)
    return sealed


def _generation_of(data: dict[str, Any]) -> int:
    """Read the client writer generation, clamped to a positive integer."""
    raw = data.get("generation", 1)
    return raw if isinstance(raw, int) and raw >= 1 else 1


async def _interval(
    websocket: WebSocket,
    rounds: Rounds,
    index: int,
    frames: FrameChannel | None,
) -> bool:
    """Show the between-rounds screen and wait for the participant to go on.

    The interval is participant-paced rather than timed: a rest that ends while
    someone is still reading is not a rest. Returns False when they left.

    A composed activity keeps talking through it: only the game pane is
    repainted, and the conversation goes on reading its own frames, which is
    what "chat stays usable in an intermission" means in practice.
    """
    try:
        await websocket.send_json(
            {
                "type": "interval",
                "markdown": rounds.between or "",
                "round": index + 1,
                "of": rounds.count,
            }
        )
        while True:
            frame = await _next(websocket, frames)
            if frame is None:
                return False
            if frame.get("type") == "interval_done":
                return True
    except (WebSocketDisconnect, ValueError):
        return False


class _AnchorTape:
    """Collect where in the game each message of a composed activity was said.

    The room orders a conversation and knows nothing about an episode; the
    stepping loop steps an episode and knows nothing about a conversation. This
    watches both and writes down the pair, so the two orderings can be laid
    against each other without one being merged into the other (NS-06).

    A message said before a round begins -- while the room is forming, or during an
    interval -- is anchored to the round that follows it, at frame zero. That is
    the true statement: it was said before that run had stepped anything.
    """

    def __init__(self) -> None:
        self._episode: str | None = None
        self._frame = 0
        self._anchors: list[MessageAnchor] = []
        self._pending: list[ChatMessage] = []

    def begin(self, episode_id: str) -> None:
        """Start a round, and place every message said before it at frame zero."""
        self._episode = episode_id
        self._frame = 0
        for message in self._pending:
            self._anchors.append(self._anchor(message))
        self._pending.clear()

    def saw(self, packet: RenderPacket) -> None:
        """Note the frame the participant has been shown."""
        self.reached(packet.frame_number)

    def reached(self, frame: int) -> None:
        """Note the frame the run has reached, however the loop reports it."""
        self._frame = frame

    def note(self, message: ChatMessage) -> None:
        """Anchor one message to the frame that was on screen when it was said."""
        if self._episode is None:
            self._pending.append(message)
            return
        self._anchors.append(self._anchor(message))

    def take(self) -> list[MessageAnchor]:
        """Take the anchors of the round that just ended, leaving the tape empty."""
        taken = self._anchors
        self._anchors = []
        self._episode = None
        return taken

    def _anchor(self, message: ChatMessage) -> MessageAnchor:
        """Build one anchor for a message at the tape's current position."""
        assert self._episode is not None
        return MessageAnchor(
            message_id=message.message_id,
            channel_key=message.channel_key,
            sequence=message.sequence,
            episode_id=self._episode,
            frame_number=self._frame,
            said_at=message.submitted_at,
        )


@dataclass(frozen=True)
class _Seated:
    """Hand back the seat a composed mount already took in the room.

    The mount joins the room before it starts either pane, because the game needs
    the interaction the room formed. The conversation must then not join again: a
    second join is read as a refresh and fences the lease of the connection that is
    about to use it.
    """

    seat: RoomSeat

    async def join(self, *, visit_id: str, activity_key: str | None) -> RoomSeat:
        """Return the seat this connection already holds."""
        del visit_id, activity_key
        return self.seat


def build_on_game(
    gateway: Gateway,
    store: Store,
    game: GameSpec | None,
    *,
    conversations: Conversations | None = None,
) -> OnGame:
    """Build the hook that runs the study game over the socket, then advances.

    The study supplies the ``game`` specification: its environment, its key
    bindings, and its drawing. The loop owns the socket while it runs -- one task
    reads input frames into the seat input state, and the loop pushes a render
    packet per frame. When the episode ends the run is captured to the ledger and
    the flow advances past the game, recording the episode stream on the visit. If
    no game is configured the flow advances straight past the game activity.

    A study with more than one game activity runs this hook once for each, and
    each run is its own episode. An activity that names its own specification runs
    that one -- a practice round of twenty steps, then the real one -- and the rest
    run the mounted game.

    ``conversations`` carries the conversations the study wrote on its game
    activities. An activity that has one runs a game **and** a conversation in one
    interaction: the room forms first and gives the interaction both its game
    channel and its chat channels, one reader hands each frame to the pane that
    owns it, and each episode records what was said while it played. An activity
    with none plays exactly as it always did.
    """

    async def on_game(websocket: WebSocket, session: Session) -> None:
        captured: list[str] = []
        spec = _spec_for(session, GameSpec, game)
        if spec is not None:
            talk = (
                conversations.at(session, spec.channel_key)
                if conversations is not None
                else None
            )
            if talk is None:
                captured = await _alone(websocket, session, spec)
            else:
                captured = await _together(websocket, session, spec, talk)
        _, delivery = await _advance(
            gateway, store, session, {}, _fresh_idem(gateway), captured
        )
        if delivery is not None:
            _queue(session, delivery)

    async def _alone(
        websocket: WebSocket, session: Session, spec: GameSpec
    ) -> list[str]:
        """Play the rounds of an activity that carries no conversation."""
        interaction_id = gateway.new_id("interaction")
        await _open_lifecycle(
            gateway,
            store,
            session,
            _one_seat_interaction(
                interaction_id, session, _study_version_of(gateway, session)
            ),
        )
        captured, reason = await _rounds(websocket, session, spec, interaction_id)
        visit_id = session.state.get("visit_id")
        await _close_lifecycle(
            gateway,
            store,
            session,
            interaction_id,
            reason,
            left=(
                [visit_id]
                if reason != "completed" and isinstance(visit_id, str)
                else []
            ),
        )
        return captured

    async def _together(
        websocket: WebSocket,
        session: Session,
        spec: GameSpec,
        talk: ChatMatchmaker,
    ) -> list[str]:
        """Play and talk at once: one interaction, two orderings, one socket."""
        visit_id = session.state.get("visit_id")
        activity_key = session.state.get("game_activity_key")
        conversations_scope = (
            conversations.scope_at(session) if conversations is not None else None
        )
        async with read_frames(websocket) as router:
            # Both panes claim their frame types before either of them reads one, so
            # a message typed while the room is still forming is held for the
            # conversation rather than swallowed by the game's reader.
            game_frames = router.subscribe("input", "interval_done")
            chat_frames = router.subscribe("chat", "chat_end")
            seat = await talk.join(
                visit_id=visit_id if isinstance(visit_id, str) else "",
                activity_key=activity_key if isinstance(activity_key, str) else None,
            )
            tape = _AnchorTape()
            seat.room.watch(tape.note)
            conversation = asyncio.create_task(
                run_chat_activity(
                    websocket,
                    session,
                    talk.spec,
                    store=store,
                    new_context=lambda aggregate_id: _agent_context(
                        gateway, session, aggregate_id
                    ),
                    new_id=gateway.new_id,
                    now=gateway.clock,
                    durable=_chat_durability(
                        gateway, store, session, conversations_scope
                    ),
                    rendezvous=_Seated(seat),
                    frames=chat_frames,
                    gateway=gateway,
                )
            )
            reason = "completed"
            try:
                captured, reason = await _rounds(
                    websocket,
                    session,
                    spec,
                    seat.room.interaction_id,
                    frames=game_frames,
                    tape=tape,
                )
            finally:
                # The rounds are what end a composed activity, so closing the reader
                # is what tells the conversation the activity is over. The
                # conversation is awaited rather than cancelled, because the streams
                # it committed are part of what this activity recorded.
                router.close()
                try:
                    streams = await conversation
                except WebSocketDisconnect:
                    streams = []
            if isinstance(visit_id, str):
                await talk.leave(visit_id, reason)
            return [*captured, *streams]

    async def _rounds(
        websocket: WebSocket,
        session: Session,
        spec: GameSpec,
        interaction_id: str,
        *,
        frames: FrameChannel | None = None,
        tape: _AnchorTape | None = None,
    ) -> tuple[list[str], str]:
        """Play every round of one activity, and say how the activity ended."""
        rounds = _rounds_at(session)
        captured: list[str] = []
        reason = "completed"
        for index in range(rounds.count):
            if index > 0 and not await _interval(websocket, rounds, index, frames):
                # The participant left during the interval. What they played is
                # already recorded; the flow advances with those rounds, and the
                # interaction says they went away rather than finished.
                reason = "abandoned"
                break
            summary = await _play(
                websocket, session, spec, interaction_id, frames, tape
            )
            captured.append(await _capture(session, summary, tape))
        return captured, reason

    async def _capture(
        session: Session, summary: EpisodeSummary, tape: _AnchorTape | None
    ) -> str:
        """Commit the played episode to its stream and return the stream id."""
        episode_id = summary.boundary.episode_id
        visit_id = cast("str", session.state["visit_id"])
        envelope = _envelope(
            "episode.capture",
            episode_id,
            {"episode_id": episode_id},
            _fresh_idem(gateway),
        )
        context = gateway.mint(
            envelope, principal=session.principal, data_handling=_RESEARCH
        )
        await capture_episode(
            summary,
            visit_id=visit_id,
            context=context,
            store=store,
            anchors=await _stage_anchor_tape(gateway, store, summary, tape),
            **_recorder(gateway, store, _activity_key(session)),
        )
        return context.stream_id

    async def _play(
        websocket: WebSocket,
        session: Session,
        spec: GameSpec,
        interaction_id: str,
        frames: FrameChannel | None,
        tape: _AnchorTape | None,
    ) -> EpisodeSummary:
        # A fresh environment per round is the reset protocol: the round starts from
        # the environment's own initial state rather than from wherever the last one
        # stopped. The interaction is the same across rounds, because the
        # participant is in one sitting at one activity.
        env = GymEnv(spec.make_env)
        episode_id = gateway.new_id("episode")
        inputs = InputState(
            spec.action_bindings,
            spec.default_action,
            mode=getattr(spec, "input_mode", "pressed_keys"),
        )
        if tape is not None:
            tape.begin(episode_id)

        async def sink(packet: RenderPacket) -> None:
            if tape is not None:
                tape.saw(packet)
            await websocket.send_json(
                {
                    "type": "render",
                    "packet": packet.model_dump(mode="json", exclude_none=True),
                }
            )

        async def read_inputs() -> None:
            while True:
                message = await _next(websocket, frames)
                if message is None:
                    return
                if message.get("type") == "input":
                    keys = message.get("keys", [])
                    if isinstance(keys, list):
                        pressed = cast("list[Any]", keys)
                        inputs.press([str(key) for key in pressed])

        reader = asyncio.create_task(read_inputs())
        try:
            return await run_episode(
                env,
                render=spec.render,
                channel_key=spec.channel_key,
                episode_id=episode_id,
                interaction_id=interaction_id,
                seat_key=_SEAT_KEY,
                input_state=inputs,
                sink=sink,
                now=_instant,
                fps=spec.fps,
                max_steps=spec.max_steps,
                countdown_seconds=spec.countdown_seconds,
                hud=spec.hud,
            )
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader

    return on_game


async def _next(
    websocket: WebSocket, frames: FrameChannel | None
) -> dict[str, Any] | None:
    """Read the game's next frame, from its own socket or from the shared reader.

    An activity that owns the socket reads it. A composed activity reads the
    channel the router fills, because a game and a conversation must not both call
    ``receive_text``: two readers race, and whichever wins keeps the frame.

    A frame that is not a json object is skipped rather than ending the reading: one
    malformed frame must not cost a participant their controls for the rest of the
    round. None means the connection itself went away.
    """
    if frames is not None:
        return await frames.get()
    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return None
        try:
            loaded: Any = json.loads(raw)
        except ValueError:
            continue
        if isinstance(loaded, dict):
            return cast("dict[str, Any]", loaded)


# -- the multiplayer peer-to-peer mesh -----------------------------------------

_MESH_STUDY = StudyVersionRef(
    study_id="study_019b6000-0000-7000-8000-0000000000c0",
    study_version_id="studyver_019b6000-0000-7000-8000-0000000000c1",
    version_number=1,
    manifest_digest=Digest(algorithm="sha-256", hex="0" * 64),
)


@dataclass
class _MeshJoin:
    """One connection waiting at the game activity to join a peer mesh.

    ``action`` returns the seat's currently held action, which the mesh reads each
    tick; ``send`` pushes one frame to the seat. ``future`` resolves with this
    seat's outcome once the mesh has formed, run, and been captured.
    """

    enrollment_id: str
    visit_id: str
    activity_key: str | None
    principal: PrincipalRef
    action: Callable[[], int]
    send: Callable[[dict[str, Any]], Awaitable[None]]
    future: asyncio.Future[_SeatOutcome]


@dataclass(frozen=True)
class _SeatOutcome:
    """The outcome one seat reads once its mesh episode has been captured.

    ``stream_id`` is the shared episode stream every seat records on its own flow,
    so each visit's lineage names where the mesh episode lives. ``verified`` is the
    cross-peer parity verdict for the run.
    """

    stream_id: str
    verified: bool


class MeshMatchmaker:
    """Rendezvous the connections at the game activity into one peer mesh.

    Each connection at the game activity submits a matchmaking ticket and waits.
    When enough connections wait, the FIFO formation forms the group, the
    coordinator hosts one peer engine per seat and runs the episode, the run is
    captured once for the whole mesh, and every seat's wait resolves. The service
    lives behind the interactions layer; the matchmaker is the app-layer glue that
    calls ``poll`` and drives the ``MeshSession`` the formation implies.

    One matchmaker forms one mesh at a time: the connection that completes the
    group runs the episode while it holds the lock, so a second group forms only
    after the first has finished. Concurrent groups stay out of this slice.
    """

    def __init__(
        self,
        gateway: Gateway,
        store: Store,
        spec: MeshGameSpec,
        *,
        study_version: StudyVersionRef | None = None,
    ) -> None:
        self._gateway = gateway
        self._store = store
        self._spec = spec
        self._service = MeshFormationService(
            new_id=gateway.new_id,
            now=_instant,
            study_version=study_version or _MESH_STUDY,
            group_key=spec.channel_key,
            channel_key=spec.channel_key,
            size=spec.size,
            strategy=FifoMatch(kind="fifo"),
        )
        self._joins: dict[str, _MeshJoin] = {}
        self._lock = asyncio.Lock()

    @property
    def spec(self) -> MeshGameSpec:
        """Return the game spec this matchmaker forms a mesh for."""
        return self._spec

    async def play(
        self,
        *,
        visit_id: str,
        activity_key: str | None,
        principal: PrincipalRef,
        action: Callable[[], int],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> _SeatOutcome:
        """Submit this connection's ticket, then wait for the mesh to run.

        The connection that completes the group forms the mesh, runs the episode,
        captures it, and resolves every waiting seat; the earlier connections wait
        on their own outcome. A fresh, well-formed enrollment id identifies the
        seat, so the group members and the ticket carry a valid identity even in the
        open demo, where no durable enrollment record exists.
        """
        enrollment_id = self._gateway.new_id("enrollment")
        future: asyncio.Future[_SeatOutcome] = (
            asyncio.get_running_loop().create_future()
        )
        join = _MeshJoin(
            enrollment_id=enrollment_id,
            visit_id=visit_id,
            activity_key=activity_key,
            principal=principal,
            action=action,
            send=send,
            future=future,
        )
        async with self._lock:
            self._service.submit(enrollment_id=enrollment_id, visit_id=visit_id)
            self._joins[enrollment_id] = join
            result = self._service.poll()
            if result.status == "formed":
                await self._run(result)
        return await future

    async def _run(self, result: FormationResult) -> None:
        """Host the peer engines, run the episode, capture it, resolve every seat."""
        assert result.group is not None
        members = [
            self._joins.pop(enrollment_id)
            for enrollment_id in result.group.members
            if enrollment_id in self._joins
        ]
        await _run_mesh_group(self._gateway, self._store, self._spec, result, members)


async def _run_mesh_group(
    gateway: Gateway,
    store: Store,
    spec: MeshGameSpec,
    result: FormationResult,
    members: list[_MeshJoin],
) -> None:
    """Host one formed group's engines, run the episode, and resolve every seat.

    The formed ``result`` names the frozen mesh (its cast, interaction, and content
    digest); ``members`` are this group's joins, already claimed from the waiting
    map. The coordinator runs the shared episode, the run is captured once from the
    reference seat, and every seat's wait resolves with the shared outcome. Both the
    single-mesh matchmaker and the concurrent pool call it, so one code path hosts a
    group however it formed.
    """
    assert result.interaction is not None
    assert result.mesh_membership_digest is not None
    cast_items = sorted(result.cast.items())
    seats = [
        SeatWiring(
            seat_key=seat_key,
            actor_id=actor_id,
            action=join.action,
            send=join.send,
        )
        for (seat_key, actor_id), join in zip(cast_items, members, strict=True)
    ]
    episode_id = gateway.new_id("episode")
    session = MeshSession(
        seats=seats,
        spec=spec,
        interaction_id=result.interaction.interaction_id,
        episode_id=episode_id,
        mesh_membership_digest=result.mesh_membership_digest,
        membership_generation=result.membership_generation,
        recorded_at=_instant(),
    )
    interaction = result.interaction
    await _open_mesh_lifecycle(gateway, store, interaction, members)
    try:
        episode = await session.run()
    except Exception:
        # A seat that went away takes the mesh with it: the peers cross a start
        # barrier together, so one lost connection ends the round for everyone. The
        # interaction says so, and names the visits that were still there.
        await _close_mesh_lifecycle(
            gateway, store, interaction.interaction_id, members, "partner_lost"
        )
        raise
    stream_id = await _capture_mesh_episode(gateway, store, episode, members[0])
    await _close_mesh_lifecycle(
        gateway, store, interaction.interaction_id, members, "completed"
    )
    outcome = _SeatOutcome(stream_id=stream_id, verified=episode.verified)
    for join in members:
        if not join.future.done():
            join.future.set_result(outcome)


async def _open_mesh_lifecycle(
    gateway: Gateway, store: Store, interaction: Interaction, members: list[_MeshJoin]
) -> None:
    """Record that one formed mesh opened, under the activity its seats are at."""
    context = gateway.mint(
        _envelope(
            "interaction.open",
            interaction.interaction_id,
            {"interaction_id": interaction.interaction_id},
            _fresh_idem(gateway),
        ),
        principal=members[0].principal,
        data_handling=_RESEARCH,
    )
    await open_interaction(
        interaction,
        activity_key=members[0].activity_key,
        opened_at=_instant(),
        context=context,
        store=store,
    )


async def _close_mesh_lifecycle(
    gateway: Gateway,
    store: Store,
    interaction_id: str,
    members: list[_MeshJoin],
    reason: str,
) -> None:
    """Record why one mesh ended. Partner loss names every seat that was in it."""
    context = gateway.mint(
        _envelope(
            "interaction.finalize",
            interaction_id,
            {"interaction_id": interaction_id},
            _fresh_idem(gateway),
        ),
        principal=members[0].principal,
        data_handling=_RESEARCH,
    )
    await finalize_interaction(
        interaction_id=interaction_id,
        reason=reason,
        closed_at=_instant(),
        context=context,
        store=store,
        left=[join.visit_id for join in members] if reason != "completed" else [],
    )


async def _capture_mesh_episode(
    gateway: Gateway, store: Store, episode: MeshEpisode, reference: _MeshJoin
) -> str:
    """Commit the mesh's reference run once, and return its episode stream id."""
    summary = episode.reference_summary()
    episode_id = summary.boundary.episode_id
    envelope = _envelope(
        "episode.capture",
        episode_id,
        {"episode_id": episode_id},
        _fresh_idem(gateway),
    )
    context = gateway.mint(
        envelope, principal=reference.principal, data_handling=_RESEARCH
    )
    await capture_episode(
        summary,
        visit_id=reference.visit_id,
        context=context,
        store=store,
        **_recorder(gateway, store, reference.activity_key),
    )
    return context.stream_id


class MeshRendezvous(Protocol):
    """What the mesh game hook drives: a spec to read and a seat wait to join.

    Both ``MeshMatchmaker`` (one mesh at a time) and ``PooledMeshMatchmaker``
    (concurrent rooms) satisfy it, so the game hook joins either the same way.
    """

    @property
    def spec(self) -> MeshGameSpec: ...

    async def play(
        self,
        *,
        visit_id: str,
        activity_key: str | None,
        principal: PrincipalRef,
        action: Callable[[], int],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> _SeatOutcome: ...


class PooledMeshMatchmaker:
    """Rendezvous connections into concurrent peer meshes through the pool.

    The single ``MeshMatchmaker`` forms one mesh at a time: the connection that
    completes a group runs its episode while it holds the lock, so a second group
    waits for the first to finish. This matchmaker mounts ``MeshFormationPool``
    instead. Each connection submits its ticket under a short lock, then ``poll_all``
    forms every group that can form this sweep and claims each group's joins; the
    forming connection then runs the formed rooms *outside* the lock, so independent
    rooms play concurrently rather than one after another.

    The pool holds one waiting room per group key. This mount registers the study's
    one game, so many rooms of that game form and run at once; a many-game mount
    registers one config per game and routes each connection to its group key. The
    engine work and the capture are the shared ``_run_mesh_group``, so a pooled room
    is hosted and captured exactly as a single-matchmaker room.
    """

    def __init__(
        self,
        gateway: Gateway,
        store: Store,
        spec: MeshGameSpec,
        *,
        study_version: StudyVersionRef | None = None,
    ) -> None:
        self._gateway = gateway
        self._store = store
        self._spec = spec
        self._pool = MeshFormationPool(
            new_id=gateway.new_id,
            now=_instant,
            study_version=study_version or _MESH_STUDY,
        )
        self._pool.register(
            GroupConfig(
                group_key=spec.channel_key,
                channel_key=spec.channel_key,
                size=spec.size,
                strategy=FifoMatch(kind="fifo"),
            )
        )
        self._joins: dict[str, _MeshJoin] = {}
        self._lock = asyncio.Lock()

    @property
    def spec(self) -> MeshGameSpec:
        """Return the game spec this matchmaker forms meshes for."""
        return self._spec

    async def play(
        self,
        *,
        visit_id: str,
        activity_key: str | None,
        principal: PrincipalRef,
        action: Callable[[], int],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> _SeatOutcome:
        """Submit this connection's ticket, then wait for its mesh to run.

        The submit and the ``poll_all`` sweep run under a short lock, so the waiting
        map stays consistent; each formed group's joins are claimed there. The
        forming connection then runs every formed room concurrently outside the lock,
        so independent rooms do not serialize, and every seat waits on its outcome.
        """
        enrollment_id = self._gateway.new_id("enrollment")
        future: asyncio.Future[_SeatOutcome] = (
            asyncio.get_running_loop().create_future()
        )
        join = _MeshJoin(
            enrollment_id=enrollment_id,
            visit_id=visit_id,
            activity_key=activity_key,
            principal=principal,
            action=action,
            send=send,
            future=future,
        )
        async with self._lock:
            self._pool.submit(
                group_key=self._spec.channel_key,
                enrollment_id=enrollment_id,
                visit_id=visit_id,
            )
            self._joins[enrollment_id] = join
            formed = self._claim(self._pool.poll_all())
        if formed:
            await asyncio.gather(
                *(
                    _run_mesh_group(
                        self._gateway, self._store, self._spec, result, members
                    )
                    for result, members in formed
                )
            )
        return await future

    def _claim(
        self, results: list[FormationResult]
    ) -> list[tuple[FormationResult, list[_MeshJoin]]]:
        """Claim each formed group's joins from the waiting map, under the lock."""
        claimed: list[tuple[FormationResult, list[_MeshJoin]]] = []
        for result in results:
            assert result.group is not None
            members = [
                self._joins.pop(enrollment_id)
                for enrollment_id in result.group.members
                if enrollment_id in self._joins
            ]
            claimed.append((result, members))
        return claimed


@dataclass
class _NodeSeat:
    """One socket this process holds, waiting for or playing in a shared mesh."""

    enrollment_id: str
    connection_id: str
    visit_id: str
    activity_key: str | None
    principal: PrincipalRef
    action: Callable[[], int]
    send: Callable[[dict[str, Any]], Awaitable[None]]
    future: asyncio.Future[_SeatOutcome]
    relay: SeatRelay | None = None


class NodeMeshMatchmaker:
    """Rendezvous connections into one peer mesh however many processes hold them.

    ``MeshMatchmaker`` and ``PooledMeshMatchmaker`` match the connections this
    process holds, so a deployment of two replicas has two waiting rooms and two
    participants who never meet. This one puts the waiting list in the shared store
    (``DurableRendezvous``), so the match is made from everyone who is waiting.

    **The process that claims a group runs it.** It hosts every engine, and it
    stands in for the seats it does not hold: it reads a remote seat's action from
    what that seat's node last published, and it puts that seat's frames on the bus
    addressed to the node that can write them. The other node keeps no state about
    the run -- it samples its participant's input and writes the frames it is given,
    which is the same thing it does for a mesh in its own process.

    The formation, the hosting, the capture, and the lifecycle records are the same
    code a single-process mesh runs (``_run_mesh_group``). What is new is only where
    the members come from and how two of them reach each other.
    """

    def __init__(
        self,
        gateway: Gateway,
        store: Store,
        spec: MeshGameSpec,
        node: Node,
        *,
        study_version: StudyVersionRef | None = None,
    ) -> None:
        self._gateway = gateway
        self._store = store
        self._spec = spec
        self._node = node
        self._study_version = study_version or _MESH_STUDY
        self._seats: dict[str, _NodeSeat] = {}
        self._remote: dict[str, dict[str, RemoteSeat]] = {}
        # A task with no reference can be collected part way through the run it
        # is hosting, so the hosting tasks are held until they finish.
        self._running: set[asyncio.Task[None]] = set()
        node.link.on(SEATED, self._on_seated)
        node.link.on(INPUT, self._on_input)
        node.link.on(FRAME, self._on_frame)
        node.link.on(ENDED, self._on_ended)

    @property
    def spec(self) -> MeshGameSpec:
        """Return the game spec this matchmaker forms a mesh for."""
        return self._spec

    async def play(
        self,
        *,
        visit_id: str,
        activity_key: str | None,
        principal: PrincipalRef,
        action: Callable[[], int],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> _SeatOutcome:
        """Put this connection in the shared waiting room, then wait for its mesh.

        The claim is what decides who runs the group: whichever process takes the
        tickets hosts the mesh, and every other process waits to be told. A process
        that claims nothing waits exactly as it does today.
        """
        enrollment_id = self._gateway.new_id("enrollment")
        connection_id = self._gateway.new_handle()
        seat = _NodeSeat(
            enrollment_id=enrollment_id,
            connection_id=connection_id,
            visit_id=visit_id,
            activity_key=activity_key,
            principal=principal,
            action=action,
            send=send,
            future=asyncio.get_running_loop().create_future(),
        )
        self._seats[connection_id] = seat
        await self._node.rendezvous.submit(
            self._spec.channel_key,
            Ticket(
                enrollment_id=enrollment_id,
                visit_id=visit_id,
                node_id=self._node.node_id,
                connection_id=connection_id,
                enqueued_at=_instant(),
                details={
                    "activity_key": activity_key,
                    "principal": principal.model_dump(mode="json"),
                },
            ),
        )
        claimed = await self._node.rendezvous.claim(
            self._spec.channel_key, self._spec.size
        )
        if claimed:
            self._spawn(self._own(claimed))
        try:
            return await asyncio.shield(seat.future)
        finally:
            await self._forget(seat)

    def _spawn(self, work: Coroutine[Any, Any, None]) -> None:
        """Run one piece of hosting work, holding it until it is finished."""
        task = asyncio.ensure_future(work)
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def _forget(self, seat: _NodeSeat) -> None:
        """Drop one local seat, and take it out of the waiting room if it is in."""
        self._seats.pop(seat.connection_id, None)
        if seat.relay is not None:
            await seat.relay.stop()
        if not seat.future.done():
            await self._node.rendezvous.release(
                self._spec.channel_key, seat.enrollment_id
            )

    async def _own(self, claimed: Sequence[Ticket]) -> None:
        """Host one claimed group: seat it, run it, and tell every node how it went."""
        room_handle = self._gateway.new_handle()
        await self._node.rendezvous.open_room(
            room_handle=room_handle,
            group_key=self._spec.channel_key,
            owner_node=self._node.node_id,
            members=claimed,
        )
        proxies: dict[str, RemoteSeat] = {}
        self._remote[room_handle] = proxies
        joins = [await self._join(ticket, room_handle, proxies) for ticket in claimed]
        try:
            await _run_mesh_group(
                self._gateway, self._store, self._spec, self._form(claimed), joins
            )
        except Exception as error:
            # A mesh that could not run must not leave every seat waiting for a
            # frame that is never coming. Each one learns, wherever it is held.
            for join in joins:
                if not join.future.done():
                    join.future.set_exception(error)
        finally:
            self._remote.pop(room_handle, None)
            await self._node.rendezvous.close_room(room_handle)

    async def _join(
        self,
        ticket: Ticket,
        room_handle: str,
        proxies: dict[str, RemoteSeat],
    ) -> _MeshJoin:
        """Build one member's join, from a local socket or from another node."""
        principal = PrincipalRef.model_validate(ticket.details["principal"])
        activity_key = cast("str | None", ticket.details.get("activity_key"))
        local = self._seats.get(ticket.connection_id)
        if local is not None and ticket.node_id == self._node.node_id:
            return _MeshJoin(
                enrollment_id=ticket.enrollment_id,
                visit_id=ticket.visit_id,
                activity_key=activity_key,
                principal=principal,
                action=local.action,
                send=local.send,
                future=local.future,
            )
        proxy = RemoteSeat(
            self._node.link,
            node_id=ticket.node_id,
            room_handle=room_handle,
            connection_id=ticket.connection_id,
            default_action=self._spec.default_action,
        )
        proxies[ticket.connection_id] = proxy
        future: asyncio.Future[_SeatOutcome] = (
            asyncio.get_running_loop().create_future()
        )
        future.add_done_callback(
            lambda done, member=ticket: self._spawn(self._tell_ended(member, done))
        )
        # The seat is asked, not told. A mesh that started before the other node
        # was relaying would read this seat's default for its first ticks, and a
        # participant already holding a key would have that first input dropped.
        # The answer is that seat's held action, and waiting for it is the barrier.
        answer = await self._node.link.ask(
            ticket.node_id,
            SEATED,
            {
                "room_handle": room_handle,
                "connection_id": ticket.connection_id,
                "owner_node": self._node.node_id,
                "fps": self._spec.fps,
            },
        )
        proxy.apply(int(cast("int", answer.get("action", self._spec.default_action))))
        return _MeshJoin(
            enrollment_id=ticket.enrollment_id,
            visit_id=ticket.visit_id,
            activity_key=activity_key,
            principal=principal,
            action=proxy.action,
            send=proxy.send,
            future=future,
        )

    def _form(self, claimed: Sequence[Ticket]) -> FormationResult:
        """Cast one already-claimed group through the ordinary formation service.

        The waiting room decided *who*; this decides what they are -- the seats, the
        actors, the frozen mesh, and the leases. It is a fresh service holding
        exactly this group, so what it forms is this group and nothing else.
        """
        service = MeshFormationService(
            new_id=self._gateway.new_id,
            now=_instant,
            study_version=self._study_version,
            group_key=self._spec.channel_key,
            channel_key=self._spec.channel_key,
            size=self._spec.size,
            strategy=FifoMatch(kind="fifo"),
        )
        for ticket in claimed:
            service.submit(enrollment_id=ticket.enrollment_id, visit_id=ticket.visit_id)
        return service.poll()

    async def _tell_ended(
        self, ticket: Ticket, done: asyncio.Future[_SeatOutcome]
    ) -> None:
        """Tell the node that holds one seat how its mesh ended."""
        error = None if done.cancelled() else done.exception()
        body: dict[str, Any] = {"connection_id": ticket.connection_id}
        if error is not None or done.cancelled():
            body["error"] = str(error) if error is not None else "the mesh was lost"
        else:
            outcome = done.result()
            body["stream_id"] = outcome.stream_id
            body["verified"] = outcome.verified
        await self._node.link.tell(ticket.node_id, ENDED, body)

    async def _on_seated(self, message: NodeMessage) -> NodeMessage | None:
        """Start relaying one of this node's sockets to the process that runs it."""
        seat = self._seats.get(cast("str", message.get("connection_id")))
        if seat is None:
            return None
        relay = SeatRelay(
            self._node.link,
            owner_node=cast("str", message.get("owner_node")),
            room_handle=cast("str", message.get("room_handle")),
            connection_id=seat.connection_id,
            action=seat.action,
            send=seat.send,
            fps=int(cast("int", message.get("fps", self._spec.fps))),
        )
        seat.relay = relay
        relay.start()
        # The held action is the answer, so the owner has it before the first tick
        # rather than after the first sample.
        return {"action": seat.action()}

    async def _on_input(self, message: NodeMessage) -> NodeMessage | None:
        """Record what one remote seat is now holding, for the next tick to read."""
        proxies = self._remote.get(cast("str", message.get("room_handle")), {})
        proxy = proxies.get(cast("str", message.get("connection_id")))
        if proxy is not None:
            proxy.apply(int(cast("int", message.get("action", 0))))
        return None

    async def _on_frame(self, message: NodeMessage) -> NodeMessage | None:
        """Write one frame the process that runs the mesh produced for our socket."""
        seat = self._seats.get(cast("str", message.get("connection_id")))
        if seat is not None:
            await seat.send(cast("dict[str, Any]", message.get("frame", {})))
        return None

    async def _on_ended(self, message: NodeMessage) -> NodeMessage | None:
        """Resolve one of this node's seats with how its mesh ended elsewhere."""
        seat = self._seats.get(cast("str", message.get("connection_id")))
        if seat is None or seat.future.done():
            return None
        error = message.get("error")
        if error is not None:
            seat.future.set_exception(RuntimeError(str(error)))
            return None
        seat.future.set_result(
            _SeatOutcome(
                stream_id=cast("str", message.get("stream_id")),
                verified=bool(message.get("verified", False)),
            )
        )
        return None


def build_mesh_on_game(
    gateway: Gateway, store: Store, matchmaker: MeshRendezvous
) -> OnGame:
    """Build the game hook that joins a peer mesh, then advances past the game.

    At the game activity the connection reads its own input frames, joins the
    mesh, and waits for the episode. When the mesh has run and been captured, the
    flow advances past the game recording the shared episode stream, so every
    participating visit's lineage names the one mesh episode.
    """

    async def on_game(websocket: WebSocket, session: Session) -> None:
        outcome = await _play_mesh(websocket, session, matchmaker)
        captured = [outcome.stream_id] if outcome is not None else []
        _, delivery = await _advance(
            gateway, store, session, {}, _fresh_idem(gateway), captured
        )
        if delivery is not None:
            _queue(session, delivery)

    return on_game


async def _play_mesh(
    websocket: WebSocket, session: Session, matchmaker: MeshRendezvous
) -> _SeatOutcome | None:
    """Own the socket for the game activity: read input and join the peer mesh.

    A reader task updates the seat input from the participant's input frames while
    the mesh reads the held action each tick, the same seam the single-seat loop
    uses. The mesh pushes its frames straight to the socket. Returns the seat's
    outcome, or None when the connection carries no visit to seat.
    """
    visit_id = session.state.get("visit_id")
    if not isinstance(visit_id, str):
        return None
    spec = matchmaker.spec
    inputs = InputState(
        spec.action_bindings,
        spec.default_action,
        mode=getattr(spec, "input_mode", "pressed_keys"),
    )

    async def send(frame: dict[str, Any]) -> None:
        await websocket.send_json(frame)

    async def read_inputs() -> None:
        try:
            while True:
                raw = await websocket.receive_text()
                loaded: Any = json.loads(raw)
                if not isinstance(loaded, dict):
                    continue
                message = cast("dict[str, Any]", loaded)
                if message.get("type") == "input":
                    keys = message.get("keys", [])
                    if isinstance(keys, list):
                        pressed = cast("list[Any]", keys)
                        inputs.press([str(key) for key in pressed])
        except WebSocketDisconnect:
            return

    reader = asyncio.create_task(read_inputs())
    try:
        return await matchmaker.play(
            visit_id=visit_id,
            activity_key=_activity_key(session),
            principal=session.principal,
            action=inputs.action,
            send=send,
        )
    finally:
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader


# -- the server-authoritative multi-seat game ----------------------------------


def _no_bindings() -> dict[str, int]:
    """Return an empty, typed key-to-action binding map for a spec default."""
    return {}


@dataclass(frozen=True)
class ServerBotSeat:
    """One bot seat a server-authoritative game seats beside the participant.

    ``agent_id`` is the environment agent the seat plays, ``seat_key`` and
    ``actor_id`` its recorded identity, and ``controller`` the local seat source that
    decides the bot's action each frame (a heuristic or an ONNX policy), the one seam
    a human input also satisfies.
    """

    agent_id: str
    seat_key: str
    actor_id: str
    controller: SeatActionSource


@dataclass(frozen=True)
class ServerGameSpec:
    """One server-authoritative game a study supplies: one env, human plus bots.

    ``make_env`` builds the one authoritative multi-seat environment the server
    steps. ``human_agent_id`` and ``human_seat_key`` place the participant's seat;
    ``bots`` seat the local controllers beside them. ``render`` draws each stepped
    frame for the person watching; a game with none draws nothing.
    ``action_bindings`` and ``default_action`` map the human seat's held keys, the
    same seam the single-seat loop uses. ``fps`` and ``max_steps`` shape the loop.
    ``hud`` is the status line drawn over the frame for the person watching.
    """

    channel_key: str
    make_env: Callable[[], MultiSeatEnv]
    human_agent_id: str
    human_seat_key: str
    bots: tuple[ServerBotSeat, ...]
    render: RenderFn | None = None
    hud: HudFn | None = None
    input_mode: str = "pressed_keys"
    action_bindings: Bindings = field(default_factory=_no_bindings)
    default_action: int = 0
    fps: int = 30
    max_steps: int = 200


def build_server_on_game(
    gateway: Gateway, store: Store, spec: ServerGameSpec
) -> OnGame:
    """Build the game hook that runs a server-authoritative episode, then advances.

    The server counterpart of ``build_mesh_on_game``: one authoritative environment
    steps on the server, the participant plays one seat, and the study's bots play
    the rest over the one seat seam. The run is captured once from the reference seat
    and the flow advances past the game recording the episode stream, so a
    server-hosted bot-beside-human interaction is captured exactly as a mesh one.
    """

    async def on_game(websocket: WebSocket, session: Session) -> None:
        stream_id = await _play_server(websocket, session, spec, gateway, store)
        captured = [stream_id] if stream_id is not None else []
        _, delivery = await _advance(
            gateway, store, session, {}, _fresh_idem(gateway), captured
        )
        if delivery is not None:
            _queue(session, delivery)

    return on_game


async def _play_server(
    websocket: WebSocket,
    session: Session,
    spec: ServerGameSpec,
    gateway: Gateway,
    store: Store,
) -> str | None:
    """Own the socket for one server-authoritative episode, then capture it.

    A reader task feeds the human seat's input from the participant's frames while
    the loop reads the held action each frame -- the same seam a bot's controller
    satisfies. The stepped frame is pushed to the socket so the participant watches
    the shared timeline. Returns the captured episode stream id, or None when the
    connection carries no visit to seat.
    """
    visit_id = session.state.get("visit_id")
    if not isinstance(visit_id, str):
        return None
    interaction_id = gateway.new_id("interaction")
    episode_id = gateway.new_id("episode")
    human_input = InputState(
        spec.action_bindings,
        spec.default_action,
        mode=getattr(spec, "input_mode", "pressed_keys"),
    )
    reader = asyncio.create_task(_read_inputs_into(websocket, human_input))

    seats = [
        ServerSeat(
            seat_key=spec.human_seat_key,
            actor_id=session.principal.id,
            agent_id=spec.human_agent_id,
            source=human_input,
            kind="human",
        ),
        *[
            ServerSeat(
                seat_key=bot.seat_key,
                actor_id=bot.actor_id,
                agent_id=bot.agent_id,
                source=bot.controller,
                kind="bot",
            )
            for bot in spec.bots
        ],
    ]

    surface = Surface()

    async def frame_sink(info: MultiSeatStepInfo) -> None:
        await websocket.send_json(
            {"type": "frame", "frame_number": info.frame, "actions": info.actions}
        )
        if spec.render is None:
            return
        packet = render_packet(
            surface,
            spec.render,
            watched_state(info.result, spec.human_agent_id),
            episode_id,
            spec.human_seat_key,
            info.frame,
            spec.hud,
        )
        await websocket.send_json(
            {
                "type": "render",
                "packet": packet.model_dump(mode="json", exclude_none=True),
            }
        )

    server = ServerSeatSession(
        seats=seats,
        env=spec.make_env(),
        channel_key=spec.channel_key,
        interaction_id=interaction_id,
        episode_id=episode_id,
        now=_instant,
        fps=spec.fps,
        max_steps=spec.max_steps,
    )
    try:
        episode = await server.run(on_step=frame_sink)
    finally:
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader

    return await _capture_server_episode(gateway, store, session, episode)


async def _capture_server_episode(
    gateway: Gateway, store: Store, session: Session, episode: ServerEpisode
) -> str:
    """Commit the server episode's reference run once, and return its stream id."""
    summary = episode.reference_summary()
    episode_id = summary.boundary.episode_id
    visit_id = cast("str", session.state["visit_id"])
    envelope = _envelope(
        "episode.capture",
        episode_id,
        {"episode_id": episode_id},
        _fresh_idem(gateway),
    )
    context = gateway.mint(
        envelope, principal=session.principal, data_handling=_RESEARCH
    )
    await capture_episode(
        summary,
        visit_id=visit_id,
        context=context,
        store=store,
        **_recorder(gateway, store, _activity_key(session)),
    )
    return context.stream_id


# -- the multi-seat agent game -------------------------------------------------

# A caller that wants the assembled replay bundle (its manifest and validation)
# passes this sink; the agent game hands it every episode's bundle at capture time.
BundleSink = Callable[[ReplayBundle], Awaitable[None]]


def warming(
    gateway: Gateway,
    store: Store,
    specs: Sequence[AgentGameSpec],
    diagnostics: Diagnostics | None = None,
) -> Callable[[Session], None]:
    """Return the hook that reaches this process's model seats, once, in the.

    **When** it runs is the whole of what makes it worth running. Everything a
    warm-up buys -- a model in the runner's memory, the fixed part of the study's
    prompt already read, and the answer to "does this provider answer" -- is paid on
    the first call somebody makes. Paid inside the round it is a partner frozen in a
    running kitchen; paid when the participant arrives, minutes of consent form and
    instructions before they reach a game, it is paid by nobody.

    Measured on a local llama3.2: a warm-up in front of the round took the wait from
    the round starting to the chef's first move from 3.1 s to 5.1 s, because it is
    the same wait with another wait in front of it. Moved here it costs the
    participant nothing and takes the first decision under 2 s.

    It runs **once for the process**, because what it buys is the runner's and not a
    participant's, and it is never awaited: a session must not wait on a model, and
    a study whose provider is unreachable must still serve the participant the rest
    of itself.
    """
    done = False

    async def warm() -> None:
        for spec in specs:
            unreachable = await warm_up_seats(
                spec,
                store=store,
                new_context=lambda aggregate_id: _service_context(
                    gateway, str(aggregate_id)
                ),
                new_modelcall_id=lambda: gateway.new_id("modelcall"),
                new_generation_id=lambda: gateway.new_id("generation"),
                now=gateway.clock,
                diagnostics=diagnostics,
            )
            if unreachable:
                # It does not stop the study. A seat nobody can reach falls back
                # exactly as it always did, and the participant plays a study with a
                # quiet partner rather than no study at all -- but nothing is silent
                # about it now, which is the whole difference.
                log_line(
                    "agents.unreachable",
                    level=logging.WARNING,
                    channel_key=spec.channel_key,
                    seats=unreachable,
                )

    def on_session(_session: Session) -> None:
        nonlocal done
        if done or not specs:
            return
        done = True
        # Detached on purpose, and the reference is dropped: a warm-up that fails
        # must not reach a participant, and one that is waited for is a participant
        # waiting on a model before they have seen the study at all.
        task = asyncio.ensure_future(warm())
        _warming.add(task)
        task.add_done_callback(_warming.discard)

    return on_session


# The warm-ups in flight, held so nothing collects one mid-call.
_warming: set[asyncio.Task[None]] = set()


def build_agent_on_game(
    gateway: Gateway,
    store: Store,
    spec: AgentGameSpec,
    *,
    on_bundle: BundleSink | None = None,
    conversations: Conversations | None = None,
    specs: Mapping[str, AgentGameSpec] | None = None,
    diagnostics: Diagnostics | None = None,
) -> OnGame:
    """Build the game hook that runs a multi-seat episode over the socket.

    The study supplies the ``spec``: its multi-agent environment and who is in it --
    the model seats, the seats people play, and the seats the study's own policies
    play. The hook seats this connection, runs one episode for the whole table --
    the models decide off the frame clock, the loop steps every seat, and each
    stepped frame is pushed to everybody watching -- then captures the run to the
    ledger, assembles the replay bundle from the run's model calls, and advances the
    flow past the game.

    **Several people are one table, not several runs.** A game with more than one
    human seat waits for them all, casts one interaction, steps one environment, and
    captures one run every seat records on its own flow. So two participants, a
    model partner, and a coach are one interaction rather than a shape the mount had
    to be told about.

    A model call's decision tape and the canonical stream fold into one replay
    bundle here, so a real agent run produces the same durable, replayable artifact a
    human run does. When no model produced an output the bundle carries no tape.

    ``conversations`` carries the conversation the study wrote on this activity.
    With one, the playing seats read the channel and say what their replies say, so
    a model partner plays **and** comments -- on the cadence it decides at, which is
    what keeps it from being asked to speak once per frame (NS-07).

    ``specs`` is the game each activity runs when the study wrote its seats on the
    activity itself (``Game("play", kitchen, seats={...})``). Each activity then has
    its own environment, its own seats, and its own rendezvous, because a practice
    round with one person and a real round with two are two seatings.

    ``diagnostics`` is where a run says what it asked its model seats and what came
    back, for a process started in debug mode. With none, nothing is written down and
    nothing is served.
    """
    # The tables in play, one per interaction, so every connection at one game finds
    # the seats the others are already in.
    tables: dict[str, _Table] = {}
    # Where several people with no conversation between them rendezvous, one per
    # activity. A game with a conversation seats them in the room the conversation
    # forms instead, because one activity is one interaction.
    seatings: dict[str, SeatMatchmaker] = {}
    by_activity = dict(specs or {})

    def _spec_at(session: Session) -> AgentGameSpec:
        """Return the game the activity this session is at runs."""
        key = _activity_key(session)
        return by_activity.get(key, spec) if key is not None else spec

    def _seating(session: Session, at: AgentGameSpec) -> SeatMatchmaker | None:
        """Return where this activity's people rendezvous, when it has several."""
        if len(at.human_seats) <= 1:
            return None
        key = _activity_key(session) or at.channel_key
        found = seatings.get(key)
        if found is None:
            found = SeatMatchmaker(
                gateway,
                store,
                channel_key=at.channel_key,
                size=len(at.human_seats),
            )
            seatings[key] = found
        return found

    def _table(interaction_id: str, at: AgentGameSpec) -> _Table:
        """Return the table for one interaction, seating it the first time."""
        table = tables.get(interaction_id)
        if table is None:
            table = _Table(
                interaction_id=interaction_id,
                size=len(at.human_seats),
                render=at.render,
                hud=at.hud,
                diagnostics=diagnostics,
            )
            tables[interaction_id] = table
        return table

    def _seat_of(at: AgentGameSpec, index: int) -> HumanSeatSpec | None:
        """Return the human seat one person plays, by their place in the cast."""
        seats = at.human_seats
        return seats[index] if index < len(seats) else None

    async def on_game(websocket: WebSocket, session: Session) -> None:
        chat = conversations.spec_at(session) if conversations is not None else None
        try:
            if chat is None:
                captured = await _watch_agents(websocket, session)
            else:
                captured = await _watch_and_talk(websocket, session, chat)
        except _Gone:
            # This connection is no longer here. It moves nothing forward, so the
            # visit is left where the participant left it, for the connection that
            # comes back to read.
            return
        _, delivery = await _advance(
            gateway, store, session, {}, _fresh_idem(gateway), captured
        )
        if delivery is not None:
            _queue(session, delivery)

    async def _watch_agents(websocket: WebSocket, session: Session) -> list[str]:
        """Run the episode with no conversation beside it, alone or with others."""
        visit_id = session.state.get("visit_id")
        at = _spec_at(session)
        seating = _seating(session, at)
        if seating is None:
            table = _table(gateway.new_id("interaction"), at)
            seat = _seat_of(at, 0)
        else:
            place = await seating.join(
                visit_id=visit_id if isinstance(visit_id, str) else "",
                activity_key=_activity_key(session),
                principal=session.principal,
            )
            table = _table(place.interaction_id, at)
            seat = _seat_of(at, place.index)
        captured = await _play_agents(
            websocket, session, at, gateway, store, on_bundle, table, seat
        )
        # The seat is given up only by a connection that finished the run. One that
        # went away leaves its seat held, so the participant who comes back is given
        # the seat they already had rather than made to wait for a new group.
        if seating is not None and isinstance(visit_id, str):
            await seating.leave(visit_id, "completed")
        return captured

    async def _watch_and_talk(
        websocket: WebSocket, session: Session, chat: ChatSpec
    ) -> list[str]:
        """Run the episode and the conversation over one socket, in one interaction.

        The participant writes to the same channel the playing seats read, so an
        instruction reaches them next decision; what the seats say comes back the
        same way. One reader hands each frame to the activity that owns it.
        """
        visit_id = session.state.get("visit_id")
        at = _spec_at(session)
        async with read_frames(websocket) as router:
            game_frames = router.subscribe("input", "interval_done")
            chat_frames = router.subscribe("chat", "chat_end")
            talk = await _seat_playing_room(gateway, store, session, at, conversations)
            conversation = asyncio.create_task(
                run_chat_activity(
                    websocket,
                    session,
                    chat,
                    store=store,
                    new_context=lambda aggregate_id: _agent_context(
                        gateway, session, aggregate_id
                    ),
                    new_id=gateway.new_id,
                    now=gateway.clock,
                    durable=_chat_durability(
                        gateway,
                        store,
                        session,
                        conversations.scope_at(session)
                        if conversations is not None
                        else None,
                    ),
                    rendezvous=_Seated(talk.seat) if talk is not None else None,
                    frames=chat_frames,
                    gateway=gateway,
                )
            )
            table = _table(
                talk.interaction_id
                if talk is not None
                else gateway.new_id("interaction"),
                at,
            )
            seat = _seat_of(at, talk.seat_index if talk is not None else 0)
            try:
                played = await _play_agents(
                    websocket,
                    session,
                    at,
                    gateway,
                    store,
                    on_bundle,
                    table,
                    seat,
                    talk,
                    game_frames,
                )
            finally:
                # The run is what ends the activity, so closing the reader is what
                # tells the conversation it is over.
                router.close()
                try:
                    streams = await conversation
                except WebSocketDisconnect:
                    streams = []
            if talk is not None and isinstance(visit_id, str):
                await talk.leave(visit_id)
            captured = list(played)
            if talk is not None:
                captured.extend(talk.streams)
            return [*captured, *streams]

    return on_game


async def _seat_playing_room(
    gateway: Gateway,
    store: Store,
    session: Session,
    spec: AgentGameSpec,
    conversations: Conversations | None,
) -> _PlayingRoom | None:
    """Form the room an agent activity's conversation runs in, when it has one.

    The playing seats are put in the conversation as model members, so the room
    records who was in it: a seat that plays and talks is a member of both channels
    of the one interaction, and the membership says so rather than the runtime
    remembering it.
    """
    if conversations is None:
        return None
    chat = conversations.spec_at(session)
    if chat is None:
        return None
    playing = [one.actor_id for one in spec.seats]
    matchmaker = conversations.at(
        session, spec.channel_key, playing, people=len(spec.human_seats) or None
    )
    if matchmaker is None:
        return None
    visit_id = session.state.get("visit_id")
    seat = await matchmaker.join(
        visit_id=visit_id if isinstance(visit_id, str) else "",
        activity_key=_activity_key(session),
    )
    return _PlayingRoom(
        seat.room,
        seat=seat,
        matchmaker=matchmaker,
        channel_key=chat.channel_key,
        seat_actor_ids=playing,
        new_context=lambda aggregate_id: _agent_context(gateway, session, aggregate_id),
        new_id=gateway.new_id,
    )


class _PlayingRoom:
    """The conversation an agent episode plays inside: what it reads and says.

    It is the whole of what a playing seat needs of a room, which is deliberately
    small: which channel its seats are in, what has been said there, and a way to
    say something back. The episode runner never touches the room, and the room
    never learns that a game is running.

    **Publishing is its own task.** Committing a message is a store write, and the
    stepping loop must never wait on one (NS-06): the loop collects what its seats
    said and this drains and publishes between steps. So a slow commit costs the
    conversation latency and never costs the game a frame.
    """

    def __init__(
        self,
        room: ChatRoom,
        *,
        seat: RoomSeat,
        matchmaker: ChatMatchmaker,
        channel_key: str,
        seat_actor_ids: Sequence[str],
        new_context: Callable[[str], CommandContext],
        new_id: Callable[[str], str],
    ) -> None:
        self.seat = seat
        self._matchmaker = matchmaker
        self._room = room
        self._channel = channel_key
        self._seats = tuple(seat_actor_ids)
        self._new_context = new_context
        self._new_id = new_id
        self.streams: list[str] = []

    @property
    def interaction_id(self) -> str:
        """Return the interaction the game and the conversation share."""
        return self._room.interaction_id

    @property
    def seat_index(self) -> int:
        """Return this connection's place in the cast's order of people.

        The room casts the seats, so the room decides which of the game's human
        seats each person plays. A room that cast nobody (a conversation of one)
        answers zero, which is the only seat there is.
        """
        order = self._matchmaker.seat_order(self.interaction_id)
        seat_key = self.seat.seat_key
        return order.index(seat_key) if seat_key in order else 0

    async def leave(self, visit_id: str) -> None:
        """Record that the interaction the game and conversation shared is over."""
        await self._matchmaker.leave(visit_id, "completed")

    @contextlib.contextmanager
    def anchored(self, tape: _AnchorTape) -> Generator[None]:
        """Have the tape note every message of this room, for one round only.

        A playing seat's words are placed in the run the same way a participant's
        are. Nothing about the anchor cares which of them said it, which is the
        point: the two are one conversation.

        The tape names **this round's** episode while the room belongs to the whole
        activity and outlives it, so the tape stops watching when the round ends. A
        tape left behind would go on anchoring a later round's messages to a run
        that had already been captured.
        """
        self._room.watch(tape.note)
        try:
            yield
        finally:
            self._room.unwatch(tape.note)

    def feed(self, spec: AgentGameSpec, table: _Table) -> None:
        """Give the playing seats every message they may see, for the whole activity.

        It is registered **once per table**, not once per round and not once per
        connection, because those are the two ways of getting it wrong:

        - once per round leaves the rest between rounds unheard. A participant who
          types "you fetch the plates next time" while they are reading the
          interval is saying the one thing the next round is about.
        - once per round without ever stopping, or once per connection at a table
          two people share, delivers each message as many times as there are
          watchers -- and with the seats' transcript carried across rounds that is
          not waste but corruption: the model reads a partner who says everything
          twice, and no record anywhere contradicts it.

        While a round is running the message goes to the episode, which records it
        on every seat and wakes each one so it answers rather than waiting out its
        cadence.

        Between rounds there is no round to wake, and a partner that goes silent for
        the whole rest is the one the participant most wants to talk to: the rest is
        where "you fetch the plates next time" gets agreed. So the round that just
        ended answers it. Its seats are the same seats, standing in the kitchen the
        round left, and they take one turn each with nothing stepping.

        Before the first round there is no such thing to answer with, so the message
        goes straight into what the seats carry and the first prompt of the first
        round reads it. Either way it lands in the same lists, which is why the seat
        reads one conversation and not two.

        The room decides who may see what, so a private channel stays private: a
        seat is fed a message only when its own membership admits the channel it
        was said on. Reading is synchronous and touches no store, so it is safe on
        the room's own watcher.
        """
        if table.listening:
            return
        table.listening = True

        def watch(message: ChatMessage) -> None:
            if message.channel_key != self._channel:
                return
            if message.author_actor_id in self._seats:
                return  # a seat is not told its own words
            said = Message(
                sender=message.author_actor_id,
                text=self._room.text_of(message.message_id),
            )
            running = table.episode
            if running is not None:
                table.diagnostics.note(
                    "chat.to_seats", subject=self._channel, where="round"
                )
                running.post_message(sender=said.sender, text=said.text)
                return
            resting = table.rested
            if resting is None:
                # Nothing has run yet, so there is nothing to answer with. Which of
                # the three ways a message reaches the seats it took is the whole
                # question behind "I typed and nobody replied", and only this knows.
                table.diagnostics.note(
                    "chat.to_seats", subject=self._channel, where="before-the-first"
                )
                for seat in spec.seats:
                    table.memory.chat_of(seat.agent_id).append(said)
                return
            table.diagnostics.note(
                "chat.to_seats",
                subject=self._channel,
                where="rest",
                already_answering=table.busy,
            )
            resting.post_message(sender=said.sender, text=said.text)
            table.answering(lambda: self.answered(resting))

        self._room.watch(watch)

    async def answered(self, resting: MultiAgentEpisode) -> None:
        """Take one turn on a resting round's seats and publish what they say.

        A model call is slow and a room watcher is not a place to wait, so this runs
        as its own task. What it writes is what any turn writes -- a model call, and
        a message for each seat that said something.
        """
        await resting.answer(lambda: self._new_id("modelcall"))
        await self.publish(resting)

    def remember_into(self, spec: AgentGameSpec, memory: SeatMemory) -> None:
        """Fill a seat's carried transcript from what the room already holds.

        A seat that has played no round of this activity has an empty transcript,
        and the room may not be empty: an opening greeting is said before the first
        frame, and one conversation placed on two activities carries the earlier
        one's messages in. Without this the model would answer a greeting it had
        never been told about.

        It reads each seat's **own** view of the room, so a seat is primed with what
        it was entitled to see and never with another channel's words.
        """
        for seat in spec.seats:
            if memory.knows(seat.agent_id):
                continue
            carried = memory.chat_of(seat.agent_id)
            for message in self._room.context_for(seat.actor_id, limit=_PRIMED):
                if message.author_actor_id in self._seats:
                    continue  # a seat is not reminded of its own words
                carried.append(
                    Message(
                        sender=message.author_actor_id,
                        text=self._room.text_of(message.message_id),
                    )
                )

    async def publish(self, episode: MultiAgentEpisode) -> None:
        """Say everything the seats have said, and record where each stream went."""
        for actor_id, text, _frame in episode.take_said():
            said = await self._room.post(
                actor_id=actor_id,
                channel_key=self._channel,
                text=text,
                message_id=self._new_id("message"),
                new_context=self._new_context,
            )
            if said is None:
                continue
            if said.stream_id is not None:
                self.streams.append(said.stream_id)
            await self._room.deliver(
                said.message, new_context=self._new_context, new_id=self._new_id
            )

    async def pump(self, episode: MultiAgentEpisode) -> None:
        """Publish what the seats say for as long as the episode is running."""
        while True:
            await self.publish(episode)
            await asyncio.sleep(_SAY_INTERVAL)


# How often the publisher drains what the playing seats said. It is a latency, not
# a cadence: the seats speak when they decide, and this only bounds how long a
# message waits for its commit. Short enough to feel immediate, long enough that an
# episode with a silent seat is not a spin loop.
_SAY_INTERVAL = 0.02

# How much of a room a seat is reminded of when it joins an activity that is already
# under way. It matches the context a model is given for one decision, because that
# is what the reminder is for.
_PRIMED = 20


# Push one stepped frame to one connection.
_Sink = Callable[[dict[str, Any]], Awaitable[None]]


class _Watcher:
    """One connection watching a shared run, and the scene it already holds.

    The surface is *per connection and per episode*, and it has to be both.

    Per connection, because every watcher sees the same board but each is told what
    changed **since its own last frame**: a person who joined late or reconnected is
    sent the whole scene and the others are not sent it again.

    Per episode, because a surface is the memory of what the far end already holds,
    and at the rest between two rounds the far end throws its drawing away and
    builds a new one. A surface carried across that remembers a canvas that no
    longer exists: it holds back every persistent object -- the whole room, in a
    game whose room is drawn once -- and the next round opens with nothing on the
    floor but the things that move. So the episode is held beside the surface, and
    a frame of a new one is drawn on a surface that remembers nothing.
    """

    def __init__(self, send: _Sink, seat_key: str, agent_id: str) -> None:
        self.send = send
        self.seat_key = seat_key
        self.agent_id = agent_id
        self.surface = Surface()
        # The episode this surface is the memory of. Nothing has been drawn on it
        # yet, so the first frame of any episode is a keyframe.
        self.drawing: str | None = None

    def drawn_on(self, episode_id: str) -> Surface:
        """Return the surface to draw one episode's frame on, forgetting an older."""
        if self.drawing != episode_id:
            self.surface.reset()
            self.drawing = episode_id
        return self.surface


class _Table:
    """One group seated at one multi-seat game, and the one run they share.

    Each person's connection contributes two things: the input their seat holds
    each frame, and somewhere to push the stepped frames. The table gathers them,
    and the run steps one environment for everybody.

    **The run belongs to the table, not to the connection that started it.** With
    several people seated, the episode is the table's own task: a participant who
    reloads mid-game must not take the game away from the person still playing, and
    the one who comes back sits down at the seat they left. With one person seated
    there is nobody to keep playing for, so the run stays on their connection and
    ends when they go -- a model left stepping for an empty room is a cost with no
    reader.

    A connection that has gone stops being pushed to; its seat keeps its input,
    which now holds no key. That is the true statement about somebody who walked
    away from the keyboard: the seat is still in the environment and does nothing.
    """

    def __init__(
        self,
        *,
        interaction_id: str,
        size: int,
        render: RenderFn | None = None,
        hud: HudFn | None = None,
        diagnostics: Diagnostics | None = None,
    ) -> None:
        self.interaction_id = interaction_id
        self.size = size
        self.render = render
        self.hud = hud
        # Where this table's seats say what they were asked and what came back. It
        # belongs to the table for the same reason the run does: the rounds of one
        # activity are one table's rounds, whichever connection claims each.
        self.diagnostics: Diagnostics = diagnostics or NullDiagnostics()
        self.inputs: dict[str, InputState] = {}
        self._watchers: list[_Watcher] = []
        self._sinks: list[_Sink] = []
        # One barrier, one claim, and one outcome **per round**. A study that plays
        # a practice round and then the real one plays them at one table, and each
        # round is its own run: its own environment, its own episode, and its own
        # start once everybody is back from the rest between them.
        self._full: dict[int, asyncio.Event] = {}
        self._ready: dict[int, set[str]] = {}
        self._outcomes: dict[int, asyncio.Future[str | None]] = {}
        self._claimed: set[int] = set()
        # The detached run, held so nothing collects it while it is stepping.
        self.running: asyncio.Task[None] | None = None
        # What the model seats carry from one round into the next. It belongs to
        # the table rather than to a connection, because the run does: the rounds
        # of one activity are one table's rounds whichever connection claims each.
        self.memory = SeatMemory()
        # The round now running, so a message said while one is on reaches its
        # seats and wakes them.
        self.episode: MultiAgentEpisode | None = None
        # The last round to have run, running or ended. Between rounds it is what
        # answers: its seats are the same seats, standing where the round left them.
        self.rested: MultiAgentEpisode | None = None
        # Whether somebody is already feeding this table's seats. The feed belongs
        # to the table, so the second connection to sit down does not add a second.
        self.listening = False
        # The turn the resting seats are taking now, held so nothing collects it,
        # and whether somebody has said something since it started.
        self._answering: asyncio.Task[None] | None = None
        self._asked = False

    @property
    def shared(self) -> bool:
        """Return whether more than one person is seated at this table."""
        return self.size > 1

    def answering(self, turn: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Have the resting seats answer, one turn at a time.

        A turn is asked for from the room's own watcher, which is neither a place to
        wait nor a place to raise: a model that fails to answer must not take the
        conversation down with it. So it runs detached, and it is held until it is
        done -- an unheld task is collected mid-call and the answer disappears.

        **One at a time, and once more if anybody spoke.** Two turns over one seat
        share its transcript and the words it is holding to say, so the second would
        take the first one's message and publish it as its own answer. Somebody who
        writes three lines quickly gets one answer to all three, then another turn
        if they wrote again while it was thinking -- which is what a partner does.
        """
        self._asked = True
        if self._answering is not None:
            return
        self._answering = asyncio.ensure_future(self._answer_while_asked(turn))

    async def _answer_while_asked(
        self, turn: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Take turns until nobody has said anything new since the last one."""
        try:
            while self._asked:
                self._asked = False
                # A turn that failed is silence, and silence is an answer a seat is
                # allowed to give. Nothing is put on the participant's screen for it.
                with contextlib.suppress(Exception):
                    await turn()
        finally:
            self._answering = None

    @property
    def busy(self) -> bool:
        """Say whether a between-rounds turn is still running.

        **The next round does not wait on it.** A participant who writes something
        and presses continue must not hold a blank screen while a model finishes,
        and a local model takes seconds. The round starts, and a turn still running
        publishes when it is done: publishing goes to the **room**, which belongs to
        the whole activity and outlives any round, so a late answer is a late
        message and not a message in the wrong place.
        """
        return self._answering is not None

    def _barrier(self, round_index: int) -> asyncio.Event:
        """Return the event that says every seat is ready for one round."""
        found = self._full.get(round_index)
        if found is None:
            found = asyncio.Event()
            self._full[round_index] = found
            self._ready.setdefault(round_index, set())
            if self.size <= 0:
                found.set()
        return found

    def sit(self, seat_key: str, inputs: InputState, round_index: int = 0) -> None:
        """Seat one person for one round: the input that seat holds each frame."""
        self.inputs[seat_key] = inputs
        barrier = self._barrier(round_index)
        self._ready[round_index].add(seat_key)
        if len(self._ready[round_index]) >= self.size:
            barrier.set()

    def watch(self, send: _Sink, seat_key: str = "", agent_id: str = "") -> None:
        """Push the stepped frames to one more connection.

        Watching and playing are separate: a participant with no seat still sees
        the run, which is what an activity where the models play and a person reads
        along is.

        ``seat_key`` is what the records call this seat and ``agent_id`` is the agent
        the environment acts. The two differ where an environment numbers its agents,
        so the observation is read by the second and the frame is named by the first.

        The connection gets a surface of its own, so it is told what changed since
        **its** last frame rather than since somebody else's.
        """
        self._sinks.append(send)
        self._watchers.append(_Watcher(send, seat_key, agent_id))

    def stop(self, send: _Sink) -> None:
        """Stop pushing frames to a connection that has gone.

        A seat's input stays behind, so the loop keeps stepping a seat that now
        holds no key. That is the true statement about somebody who left: the seat
        is still in the environment and does nothing.
        """
        if send in self._sinks:
            self._sinks.remove(send)
        self._watchers = [one for one in self._watchers if one.send is not send]

    async def seated(self, round_index: int = 0) -> None:
        """Wait until every seat has somebody at it, ready for that round."""
        await self._barrier(round_index).wait()

    def claim(self, round_index: int = 0) -> bool:
        """Return whether this connection is the one that runs that round."""
        if round_index in self._claimed:
            return False
        self._claimed.add(round_index)
        return True

    async def push(self, frame: dict[str, Any]) -> None:
        """Push one stepped frame to everybody still connected."""
        for send in list(self._sinks):
            try:
                await send(frame)
            except (WebSocketDisconnect, RuntimeError):
                self.stop(send)

    async def draw(self, episode_id: str, frame: int, result: MultiStepResult) -> None:
        """Draw one stepped frame for everybody still watching this run.

        Each watcher is drawn on its own surface, so what it is sent is what changed
        for it. A game the study gave no drawing draws nothing and pushes nothing;
        the stepped frame itself still goes out.

        The surface is asked for **by episode**, so the first frame of each round is
        a keyframe: the client mounts a new drawing for every round and a surface
        that remembered the last one would hold back everything drawn once.
        """
        if self.render is None:
            return
        for watcher in list(self._watchers):
            packet = render_packet(
                watcher.drawn_on(episode_id),
                self.render,
                watched_state(result, watcher.agent_id),
                episode_id,
                watcher.seat_key or _SEAT_KEY,
                frame,
                self.hud,
            )
            try:
                await watcher.send(
                    {
                        "type": "render",
                        "packet": packet.model_dump(mode="json", exclude_none=True),
                    }
                )
            except (WebSocketDisconnect, RuntimeError):
                self.stop(watcher.send)

    def _future(self, round_index: int) -> asyncio.Future[str | None]:
        """Return the outcome every seat waits on for one round."""
        found = self._outcomes.get(round_index)
        if found is None:
            found = asyncio.get_running_loop().create_future()
            self._outcomes[round_index] = found
        return found

    def settle(self, stream_id: str | None, round_index: int = 0) -> None:
        """Give every seat the captured run they share for that round."""
        future = self._future(round_index)
        if not future.done():
            future.set_result(stream_id)

    def fail(self, error: BaseException, round_index: int = 0) -> None:
        """Give every seat the failure that ended the round they shared."""
        future = self._future(round_index)
        if not future.done():
            future.set_exception(error)

    async def outcome(self, round_index: int = 0) -> str | None:
        """Wait for the run everybody at this table shares for that round.

        The wait is shielded, so one connection giving up does not cancel the run
        the others are still in.
        """
        return await asyncio.shield(self._future(round_index))


async def _play_agents(
    websocket: WebSocket,
    session: Session,
    spec: AgentGameSpec,
    gateway: Gateway,
    store: Store,
    on_bundle: BundleSink | None,
    table: _Table,
    seat: HumanSeatSpec | None,
    talk: _PlayingRoom | None = None,
    game_frames: FrameChannel | None = None,
) -> list[str]:
    """Sit this connection at its seat, play every round, and report what it captured.

    ``seat`` is the human seat this person plays, when the game has one for them. A
    reader task feeds that seat's held keys from the connection's input frames while
    the loop reads the held action each frame -- the same seam a bot's controller
    and a model's held action satisfy.

    **The run is the table's, not this connection's.** Every seated connection waits
    for the same episode; exactly one of them starts it. So the several-people case
    and the one-person case are the same path, and neither has to know which it is.
    Returns one captured episode stream id per round this connection played, and
    nothing at all when the connection carries no visit to seat.

    ``talk`` is the conversation this activity also carries. With one, the playing
    seats read what is said on the channels they are in and publish what they say
    back onto it, on the cadence they decide at rather than once per frame (NS-07).
    """
    visit_id = session.state.get("visit_id")
    if not isinstance(visit_id, str):
        return []

    async def send(frame: dict[str, Any]) -> None:
        await websocket.send_json(frame)

    table.watch(
        send,
        seat.seat_key if seat is not None else "",
        seat.agent_id if seat is not None else "",
    )
    rounds = _rounds_at(session)
    captured: list[str] = []
    try:
        for index in range(rounds.count):
            if index > 0 and not await _interval(websocket, rounds, index, game_frames):
                # This participant left during the rest between rounds. What they
                # played is already recorded, and the flow advances with it.
                break
            captured.extend(
                await _one_round(
                    websocket,
                    session,
                    spec,
                    gateway,
                    store,
                    on_bundle,
                    table,
                    seat,
                    talk,
                    game_frames,
                    index,
                )
            )
        return captured
    finally:
        table.stop(send)


async def _one_round(
    websocket: WebSocket,
    session: Session,
    spec: AgentGameSpec,
    gateway: Gateway,
    store: Store,
    on_bundle: BundleSink | None,
    table: _Table,
    seat: HumanSeatSpec | None,
    talk: _PlayingRoom | None,
    game_frames: FrameChannel | None,
    index: int,
) -> list[str]:
    """Play one round at the table, and read this connection's input while it runs.

    The input reader lives for the round rather than for the activity. Two readers
    on one socket would race, and the frame that says the participant is ready for
    the next round is the one that would be lost: the rest between two rounds is
    read by the loop above, and nothing else may be reading while it is.
    """
    reader: asyncio.Task[None] | None = None
    if seat is not None:
        # A key held when the last round ended is not held in the next one, so each
        # round starts from an empty hand.
        inputs = InputState(
            spec.action_bindings,
            spec.default_action,
            mode=getattr(spec, "input_mode", "pressed_keys"),
        )
        reader = asyncio.create_task(_read_inputs_into(websocket, inputs, game_frames))
        table.sit(seat.seat_key, inputs, index)
    try:
        await table.seated(index)
        if table.claim(index):
            running = _run_table(
                table, session, spec, gateway, store, on_bundle, talk, index
            )
            if table.shared:
                # Several people are in it, so the run outlives whichever of them
                # started it. The table holds the task, so nothing collects it.
                table.running = asyncio.create_task(running)
            else:
                await running
        stream_id = await _watched(table, reader, index)
        return [stream_id] if stream_id is not None else []
    finally:
        if reader is not None:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader


class _Gone(Exception):
    """This connection went away while the run it was in went on.

    It is not an error and it does not end the run. It is how a connection says it
    has nothing more to do: it advances no flow and finalizes no interaction,
    because the connection that comes back in its place will.
    """


async def _watched(
    table: _Table, reader: asyncio.Task[None] | None, round_index: int = 0
) -> str | None:
    """Wait for the shared run, unless this connection goes away first.

    A connection that has gone stops waiting at once: it holds no task for the rest
    of a run nobody is reading, and it advances nothing. The flow is moved forward
    by the connection that came back in its place, which is what keeps a
    reconnection from walking a visit past the screen it came back to. The run
    itself is untouched -- the wait is shielded, so giving up on it is not ending
    it.
    """
    waiting = asyncio.ensure_future(table.outcome(round_index))
    if reader is None:
        return await waiting
    done, _pending = await asyncio.wait(
        {waiting, reader}, return_when=asyncio.FIRST_COMPLETED
    )
    if waiting in done:
        return waiting.result()
    waiting.cancel()
    raise _Gone


async def _run_table(
    table: _Table,
    session: Session,
    spec: AgentGameSpec,
    gateway: Gateway,
    store: Store,
    on_bundle: BundleSink | None,
    talk: _PlayingRoom | None,
    round_index: int = 0,
) -> None:
    """Step one table's environment to its end, capture the run, settle every seat.

    It never raises. Whatever happened is handed to the seats through the outcome
    they all wait on, because a detached run has nobody to raise to and a seat that
    waits forever is worse than a seat that is told.
    """
    episode_id = gateway.new_id("episode")
    tape: _AnchorTape | None = None
    if talk is not None:
        tape = _AnchorTape()
        tape.begin(episode_id)
        talk.remember_into(spec, table.memory)
        talk.feed(spec, table)

    async def frame_sink(info: MultiSeatStepInfo) -> None:
        if tape is not None:
            tape.reached(info.frame)
        await table.push(
            {"type": "frame", "frame_number": info.frame, "actions": info.actions}
        )
        await table.draw(episode_id, info.frame, info.result)

    episode = build_agent_episode(
        spec,
        store=store,
        new_context=lambda aggregate_id: _agent_context(gateway, session, aggregate_id),
        new_decision_id=lambda: gateway.new_id("decision"),
        new_generation_id=lambda: gateway.new_id("generation"),
        now=gateway.clock,
        interaction_id=table.interaction_id,
        episode_id=episode_id,
        human_sources=table.inputs,
        frame_sink=frame_sink,
        memory=table.memory,
        diagnostics=table.diagnostics,
    )
    table.diagnostics.note(
        "round.start",
        subject=table.interaction_id,
        round=round_index + 1,
        episode_id=episode_id,
        model_seats=[one.seat_key for one in spec.seats],
        human_seats=[one.seat_key for one in spec.human_seats],
        bot_seats=[one.seat_key for one in spec.bots],
        max_steps=spec.max_steps,
        fps=spec.fps,
        talking=talk is not None,
    )
    publisher: asyncio.Task[None] | None = None
    watching = (
        talk.anchored(tape)
        if talk is not None and tape is not None
        else contextlib.nullcontext()
    )
    table.episode = episode
    # And it is what answers once the round has ended: a round that has stopped
    # stepping still holds the seats, their conversation, and the environment as
    # they left it, which is everything a rest between rounds is talked about with.
    table.rested = episode
    try:
        with watching:
            if talk is not None:
                publisher = asyncio.create_task(talk.pump(episode))
            try:
                result = await episode.run()
            finally:
                table.episode = None
                if publisher is not None and talk is not None:
                    publisher.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await publisher
                    # Whatever the last decisions said is published before the run
                    # is captured, so a message the model really produced is not
                    # lost to the end of the episode.
                    await talk.publish(episode)
        stream_id = await _capture_multiseat(
            gateway, store, session, result.summary, tape
        )
        await _bundle_agent_run(
            gateway,
            store,
            table.interaction_id,
            result.summary.boundary.episode_id,
            stream_id,
            result.model_calls(),
            on_bundle,
        )
    except (Exception, asyncio.CancelledError) as error:
        # A round that ended in a failure is the one a person most needs told. It
        # reaches the seats through the outcome they wait on and nothing else says
        # it out loud, so it is written down before it is handed over.
        table.diagnostics.note(
            "round.failed",
            subject=table.interaction_id,
            round=round_index + 1,
            episode_id=episode_id,
            error=type(error).__name__,
            message=str(error),
        )
        table.fail(error, round_index)
    else:
        table.diagnostics.note(
            "round.end",
            subject=table.interaction_id,
            round=round_index + 1,
            episode_id=episode_id,
            frames=result.summary.frames,
            stream_id=stream_id,
        )
        table.settle(stream_id, round_index)


async def _read_inputs_into(
    websocket: WebSocket,
    inputs: InputState,
    frames: FrameChannel | None = None,
) -> None:
    """Feed a human seat's input state from the connection's input frames.

    With ``frames`` set the connection is shared with a conversation, so the input
    comes from the router's channel rather than from a second reader on the socket.
    """
    while True:
        message = await _next(websocket, frames)
        if message is None:
            return
        if message.get("type") == "input":
            keys = message.get("keys", [])
            if isinstance(keys, list):
                pressed = cast("list[Any]", keys)
                inputs.press([str(key) for key in pressed])


def _agent_context(
    gateway: Gateway, session: Session, aggregate_id: str
) -> CommandContext:
    """Mint a fresh command context on one agent aggregate's stream.

    A model call, a decision, and every other agent aggregate each commit on their
    own stream, so the runtime asks for a context per aggregate id. The gateway is
    the one entropy-and-clock boundary; a fresh idempotency key makes each context
    distinct, and the store's revision guard carries idempotency for a retry.
    """
    envelope = _envelope(
        "agent.step",
        aggregate_id,
        {"aggregate_id": aggregate_id},
        _fresh_idem(gateway),
    )
    return gateway.mint(envelope, principal=session.principal, data_handling=_RESEARCH)


def _service_context(gateway: Gateway, aggregate_id: str) -> CommandContext:
    """Mint a command context for work the **process** does, not a participant.

    A warm-up is the deployment checking its own provider, so it is recorded under
    the service principal rather than under whoever happened to connect first. A
    participant did not ask for it and must not be named as having made it.
    """
    envelope = _envelope(
        "agent.step",
        aggregate_id,
        {"aggregate_id": aggregate_id},
        _fresh_idem(gateway),
    )
    return gateway.mint(
        envelope, principal=_service_principal(gateway), data_handling=_RESEARCH
    )


async def _capture_multiseat(
    gateway: Gateway,
    store: Store,
    session: Session,
    summary: MultiSeatSummary | TurnBasedSummary,
    tape: _AnchorTape | None = None,
) -> str:
    """Capture a multi-seat or turn-based episode and return the stream id.

    Both summaries name every seat, so the episode summary joins the seat keys; the
    capture aggregate then records the run under one seat-key field.

    ``tape`` is what was said while the run played, when the activity carried a
    conversation. A playing seat's own words are in it beside a participant's,
    because the two are one conversation (W7).
    """
    episode = EpisodeSummary(
        channel_key=summary.channel_key,
        seat_key="+".join(summary.seat_keys),
        frames=summary.frames,
        transitions=summary.transitions,
        boundary=summary.boundary,
        solved=summary.solved,
        trajectory=summary.trajectory,
    )
    episode_id = summary.boundary.episode_id
    visit_id = cast("str", session.state["visit_id"])
    envelope = _envelope(
        "episode.capture",
        episode_id,
        {"episode_id": episode_id},
        _fresh_idem(gateway),
    )
    context = gateway.mint(
        envelope, principal=session.principal, data_handling=_RESEARCH
    )
    await capture_episode(
        episode,
        visit_id=visit_id,
        context=context,
        store=store,
        anchors=await _stage_anchor_tape(gateway, store, episode, tape),
        **_recorder(gateway, store, _activity_key(session)),
    )
    return context.stream_id


async def _stage_anchor_tape(
    gateway: Gateway,
    store: Store,
    summary: EpisodeSummary,
    tape: _AnchorTape | None,
) -> ArtifactRef | None:
    """Stage what was said while one run played, checked against the run.

    The check is the point: an anchor naming a frame the run never reached is not
    weak evidence, it is a false statement about what the participant was looking
    at. A tape that does not verify is not recorded at all.
    """
    if tape is None:
        return None
    anchors = tape.take()
    if not anchors:
        return None
    verify_anchors(
        anchors,
        episode_id=summary.boundary.episode_id,
        frames=summary.frames,
        message_ids=[anchor.message_id for anchor in anchors],
    )
    return await stage_artifact(
        cast("ArtifactStore", store),
        data=anchor_bytes(anchors),
        media_type=MESSAGE_ANCHOR_MEDIA_TYPE,
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=_instant,
        data_handling=_RESEARCH,
    )


async def _bundle_agent_run(
    gateway: Gateway,
    store: Store,
    interaction_id: str,
    episode_id: str,
    stream_id: str,
    model_calls: list[ModelCallResult],
    on_bundle: BundleSink | None,
) -> None:
    """Assemble the replay bundle for one agent run and hand it to the sink.

    The decision tape folds the run's model calls into the API-16 tape, and the
    bundle assembler persists it beside the canonical stream as one replay bundle.
    The bundle carries no tape when no model produced an output.
    """
    tape = build_decision_tape(interaction_id=interaction_id, results=model_calls)
    # The bundle names the run's recorded values, so its capability levels come from
    # what the episode actually kept rather than from a claim.
    recorded = recorded_trajectory(store, episode_id)
    bundle = await build_replay_bundle(
        store=store,
        artifacts=cast("ArtifactStore", store),
        interaction_id=interaction_id,
        stream_ids=[stream_id],
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=_instant,
        data_handling=_RESEARCH,
        decision_tape=tape if tape.entries else None,
        trajectory=recorded,
    )
    if on_bundle is not None:
        await on_bundle(bundle)


# -- the turn-based (AEC) agent game -------------------------------------------


def build_turnbased_on_game(
    gateway: Gateway,
    store: Store,
    spec: TurnBasedGameSpec,
    *,
    on_bundle: BundleSink | None = None,
) -> OnGame:
    """Build the game hook that runs a turn-based agent episode over the socket.

    The turn-based sibling of ``build_agent_on_game``: the seats act one at a time
    over the study's AEC environment, each played turn is pushed to the socket, and
    the run is captured and bundled the same way. So an AEC episode is reachable by a
    real participant, not only a test.
    """

    async def on_game(websocket: WebSocket, session: Session) -> None:
        stream_id = await _play_turnbased(
            websocket, session, spec, gateway, store, on_bundle
        )
        captured = [stream_id] if stream_id is not None else []
        _, delivery = await _advance(
            gateway, store, session, {}, _fresh_idem(gateway), captured
        )
        if delivery is not None:
            _queue(session, delivery)

    return on_game


async def _play_turnbased(
    websocket: WebSocket,
    session: Session,
    spec: TurnBasedGameSpec,
    gateway: Gateway,
    store: Store,
    on_bundle: BundleSink | None,
) -> str | None:
    """Own the socket for one turn-based episode: run it, capture it, bundle it."""
    visit_id = session.state.get("visit_id")
    if not isinstance(visit_id, str):
        return None
    interaction_id = gateway.new_id("interaction")
    episode_id = gateway.new_id("episode")

    human_source: InputState | None = None
    reader: asyncio.Task[None] | None = None
    if spec.human is not None:
        human_source = InputState(
            spec.action_bindings,
            spec.default_action,
            mode=getattr(spec, "input_mode", "pressed_keys"),
        )
        reader = asyncio.create_task(_read_inputs_into(websocket, human_source))

    async def frame_sink(info: TurnStepInfo) -> None:
        await websocket.send_json(
            {"type": "frame", "frame_number": info.frame, "mover": info.agent}
        )

    episode = build_turnbased_episode(
        spec,
        store=store,
        new_context=lambda aggregate_id: _agent_context(gateway, session, aggregate_id),
        new_decision_id=lambda: gateway.new_id("decision"),
        new_generation_id=lambda: gateway.new_id("generation"),
        now=gateway.clock,
        interaction_id=interaction_id,
        episode_id=episode_id,
        human_source=human_source,
        frame_sink=frame_sink,
    )
    try:
        result = await episode.run()
    finally:
        if reader is not None:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader

    stream_id = await _capture_multiseat(gateway, store, session, result.summary)
    await _bundle_agent_run(
        gateway,
        store,
        interaction_id,
        result.summary.boundary.episode_id,
        stream_id,
        result.model_calls(),
        on_bundle,
    )
    return stream_id


# -- the comparison activity -----------------------------------------------------


def build_comparison_on_game(
    gateway: Gateway,
    store: Store,
    generations: Mapping[str, RecordedGeneration] | None = None,
) -> OnGame:
    """Build the activity hook that asks one comparison over recorded candidates.

    At a comparison activity the hook takes the socket over, resolves what the
    comparison is about, presents the options blinded in the order the assignment
    committed to, records the one answer, and then advances the flow past the
    activity with the stream it wrote.

    A comparison of runs needs nothing from the application: what it compares is what
    the participant recorded, and the question is the study's own. A comparison of
    model outputs compares generations the study recorded before its participants
    arrived, so ``generations`` maps each option key to the generation behind it and
    the hook contacts no provider.
    """

    async def on_game(websocket: WebSocket, session: Session) -> None:
        key = session.state.get("comparison_activity_key")
        study = _study_of(session)
        outcome = ComparisonOutcome(reason="the study has no such comparison")
        if isinstance(key, str) and key in study.comparisons:
            outcome = await run_comparison_activity(
                websocket,
                session,
                study.comparison(key),
                store=store,
                gateway=gateway,
                now=_instant,
                generations=generations,
            )
        if not outcome.finished:
            # The participant has not answered and still could. The flow stays at
            # the comparison, so their next connection asks the same question.
            return
        _, delivery = await _advance(
            gateway, store, session, {}, _fresh_idem(gateway), outcome.streams
        )
        if delivery is not None:
            _queue(session, delivery)

    return on_game


def build_routed_on_game(
    by_activity: Mapping[str, OnGame], fallback: OnGame | None = None
) -> OnGame:
    """Route each game activity to the runtime that plays it.

    One study may hold a practice round on the server and a real round with a model
    partner, and those are two different runtimes. Until this existed the application
    chose **one** runtime for the whole study from a chain of mutually exclusive
    keywords, so a study with two environments could run only one of them and nothing
    said which.

    ``fallback`` is what an activity nobody resolved runs, which is how a study that
    still mounts its game through a keyword keeps working beside one that names its
    environments.
    """

    async def on_game(websocket: WebSocket, session: Session) -> None:
        key = _activity_key(session)
        found = by_activity.get(key) if key is not None else None
        if found is None:
            found = fallback
        if found is not None:
            await found(websocket, session)

    return on_game


def build_activity_on_game(comparison: OnGame, game: OnGame | None) -> OnGame:
    """Route each activity that owns the socket to the hook that runs it.

    A study puts a comparison after the rounds it asks about, so both hooks are
    live in one deployment and the activity the session is at decides which one
    runs. A study with no game mounted still reaches its comparison, and a study
    with no comparison never meets this router's other arm.
    """

    async def on_game(websocket: WebSocket, session: Session) -> None:
        if session.state.get("activity_kind") == "comparison":
            await comparison(websocket, session)
            return
        if game is not None:
            await game(websocket, session)

    return on_game


# -- the chat activity ----------------------------------------------------------


def _chat_durability(
    gateway: Gateway, store: Store, session: Session, scope: str | None = None
) -> ChatDurability | None:
    """Build what the chat mount needs to keep a conversation across connections.

    The transcript is kept per conversation, and what a conversation *is* comes
    from the author. By default it is the step the participant is on, so a study
    that holds two conversations keeps two transcripts and a within-subject repeat
    keeps one per pass. ``scope`` overrides that with the conversation the author
    wrote: one written conversation placed on two game activities keeps one
    transcript, so a pair who talked in the practice round carry that into the real
    one. A session that carries neither keeps nothing, and the conversation then
    lives and dies with the connection.
    """
    occurrence = scope or session.state.get("occurrence_key")
    if not isinstance(occurrence, str):
        return None
    return ChatDurability(
        derive=gateway.derived_id,
        artifacts=cast("ArtifactStore", store),
        new_artifact_id=lambda seed: gateway.derived_id("artifact", seed),
        new_upload_id=lambda: gateway.new_id("upload"),
        occurrence_key=occurrence,
    )


_CHAT_STUDY = StudyVersionRef(
    study_id="study_019b6000-0000-7000-8000-0000000000d0",
    study_version_id="studyver_019b6000-0000-7000-8000-0000000000d1",
    version_number=1,
    manifest_digest=Digest(algorithm="sha-256", hex="0" * 64),
)


@dataclass
class _ChatWait:
    """One connection waiting at the chat activity for its room to form."""

    visit_id: str
    activity_key: str | None
    principal: PrincipalRef
    future: asyncio.Future[RoomSeat]


class ChatMatchmaker:
    """Rendezvous the connections at the chat activity into one shared room.

    This is the chat counterpart of ``MeshMatchmaker``: each connection submits a
    ticket and waits, and when enough wait the ``RoomFormation`` casts them into one
    interaction with one lease each. The connection that completes the group builds
    the live ``ChatRoom``, places every participant in it, records that the
    interaction opened, and resolves every waiting seat with the same room.

    **A refresh does not cost a seat.** A visit that comes back is given its own
    seat again with its lease re-acquired at the next fencing generation, which
    fences whatever the previous connection still holds. So a participant who
    reloads rejoins the conversation they were in, and the connection they replaced
    can no longer speak for them.
    """

    def __init__(
        self,
        gateway: Gateway,
        store: Store,
        spec: ChatSpec,
        *,
        study_version: StudyVersionRef | None = None,
        game_channel: str | None = None,
        conversation_key: str | None = None,
        players: Sequence[str] = (),
        participants: int | None = None,
    ) -> None:
        self._gateway = gateway
        self._store = store
        self._spec = spec
        self._game_channel = game_channel
        # The actors that play this activity's game. They are members of the
        # conversation too, so a seat that plays and talks is one member of one
        # interaction rather than two things that happen to share an id.
        self._players = tuple(players)
        # The channels of one composed activity: the game beside the conversation,
        # in one interaction. They are not ordered the same way, so each says which
        # it is. A conversation the author placed on several activities names one
        # definition per channel, derived from the conversation rather than minted
        # here, so each activity's instance is one run of the same channel.
        channels: list[ChannelSpec] = [
            ChannelSpec(
                key=channel.key,
                type="chat",
                definition_id=self._definition_of(conversation_key, channel.key),
            )
            for channel in spec.room_channels
        ]
        if game_channel is not None:
            channels.append(
                ChannelSpec(
                    key=game_channel,
                    type="game",
                    definition_id=self._definition_of(conversation_key, game_channel),
                )
            )
        self._formation = RoomFormation(
            new_id=gateway.new_id,
            now=_instant,
            study_version=study_version or _CHAT_STUDY,
            group_key=spec.channel_key,
            channels=channels,
            # A composed activity's seating is the **game's**: the number of people
            # in the room is how many human seats the environment has, so a study
            # cannot state it twice and state it differently.
            size=participants or spec.participants,
        )
        self._waiting: dict[str, _ChatWait] = {}
        self._seats: dict[str, RoomSeat] = {}
        # The participant seat keys of each formed room, in the cast's own order.
        # A composed activity binds each person to one of the game's declared human
        # seats by this order, so the seat somebody plays is the seat the
        # interaction cast them into rather than the order their socket opened in.
        self._orders: dict[str, tuple[str, ...]] = {}
        self._lock = asyncio.Lock()

    def _definition_of(self, conversation_key: str | None, channel_key: str) -> str:
        """Derive the authored channel one key's instances are all runs of.

        It derives from the conversation the author wrote rather than from the
        activity, which is what makes one conversation placed on two activities one
        channel with two runs. A conversation named nowhere gets a definition of the
        formation's own, which is what a study with one chat activity always had.
        """
        if conversation_key is None:
            return self._gateway.new_id("channeldef")
        return self._gateway.derived_id(
            "channeldef", f"conversation:{conversation_key}:{channel_key}"
        )

    @property
    def spec(self) -> ChatSpec:
        """Return the conversation this matchmaker rendezvouses connections into."""
        return self._spec

    @property
    def formation(self) -> RoomFormation:
        """Return the formation that fences this matchmaker's leases."""
        return self._formation

    def seat_order(self, interaction_id: str) -> tuple[str, ...]:
        """Return one room's participant seat keys, in the cast's own order."""
        return self._orders.get(interaction_id, ())

    async def join(self, *, visit_id: str, activity_key: str | None) -> RoomSeat:
        """Wait for a room and return this connection's seat in it."""
        async with self._lock:
            seated = self._seats.get(visit_id)
            if seated is not None:
                return self._rejoin(visit_id, seated)
            enrollment_id = self._gateway.new_id("enrollment")
            future: asyncio.Future[RoomSeat] = (
                asyncio.get_running_loop().create_future()
            )
            self._formation.submit(enrollment_id=enrollment_id, visit_id=visit_id)
            self._waiting[enrollment_id] = _ChatWait(
                visit_id=visit_id,
                activity_key=activity_key,
                principal=_service_principal(self._gateway),
                future=future,
            )
            result = self._formation.poll()
            if result.status == "formed":
                await self._open(result)
        return await future

    def _rejoin(self, visit_id: str, seat: RoomSeat) -> RoomSeat:
        """Return a returning visit's own seat, its lease fenced one further on."""
        if seat.lease is None:
            return seat
        fenced = self._formation.reacquire_lease(seat.room.interaction_id, seat.lease)
        member = seat.room.member(seat.actor_id)
        if member is not None:
            member.lease = fenced
        renewed = RoomSeat(
            room=seat.room,
            actor_id=seat.actor_id,
            seat_key=seat.seat_key,
            lease=fenced,
        )
        self._seats[visit_id] = renewed
        return renewed

    async def _open(self, result: RoomResult) -> None:
        """Build the live room for one formed group and resolve every waiter."""
        assert result.group is not None and result.interaction is not None
        members = [
            self._waiting.pop(enrollment_id)
            for enrollment_id in result.group.members
            if enrollment_id in self._waiting
        ]
        room = ChatRoom(
            store=self._store,
            interaction_id=result.interaction.interaction_id,
            channels=[
                RoomChannel(key=channel.key, visibility=channel.visibility)
                for channel in self._spec.room_channels
            ],
            now=self._gateway.clock,
            leases=self._formation,
        )
        seat_keys = sorted(result.cast)
        self._orders[result.interaction.interaction_id] = tuple(seat_keys)
        leases = {lease.actor_id: lease for lease in result.leases}
        for seat_key, wait in zip(seat_keys, members, strict=True):
            actor_id = result.cast[seat_key]
            room.add_member(
                RoomMember(
                    actor_id=actor_id,
                    channels=_seat_channels(self._spec, seat_key),
                    kind="participant",
                    lease=leases.get(actor_id),
                )
            )
            self._seats[wait.visit_id] = RoomSeat(
                room=room,
                actor_id=actor_id,
                seat_key=seat_key,
                lease=leases.get(actor_id),
            )
        # The model seats join before the membership is recorded, so what is
        # written down is the whole room rather than only the people in it. A
        # playing seat joins here too, for the same reason.
        for seat in self._spec.model_seats:
            room.add_member(
                RoomMember(
                    actor_id=seat.actor_id,
                    channels=self._spec.channels_of(seat),
                    kind="model",
                )
            )
        for actor_id in self._players:
            if room.member(actor_id) is None:
                room.add_member(
                    RoomMember(
                        actor_id=actor_id,
                        channels=(self._spec.channel_key,),
                        kind="model",
                    )
                )
        await self._record_open(result, room, members)
        for wait in members:
            if not wait.future.done():
                wait.future.set_result(self._seats[wait.visit_id])

    async def _record_open(
        self, result: RoomResult, room: ChatRoom, members: list[_ChatWait]
    ) -> None:
        """Record that one formed conversation opened, and who was in each channel."""
        assert result.interaction is not None
        interaction = result.interaction
        principal = members[0].principal
        context = self._gateway.mint(
            _envelope(
                "interaction.open",
                interaction.interaction_id,
                {"interaction_id": interaction.interaction_id},
                _fresh_idem(self._gateway),
            ),
            principal=principal,
            data_handling=_RESEARCH,
        )
        await open_interaction(
            interaction,
            activity_key=members[0].activity_key,
            opened_at=_instant(),
            context=context,
            store=self._store,
        )
        for instance in result.instances:
            await record_channel(
                instance,
                context=self._gateway.mint(
                    _envelope(
                        "interaction.channel",
                        instance.channel_instance_id,
                        {"channel_instance_id": instance.channel_instance_id},
                        _fresh_idem(self._gateway),
                    ),
                    principal=principal,
                    data_handling=_RESEARCH,
                ),
                store=self._store,
            )
        await self._record_memberships(interaction.interaction_id, room, principal)

    async def _record_memberships(
        self, interaction_id: str, room: ChatRoom, principal: PrincipalRef
    ) -> None:
        """Record what every member of the room may do on every channel of it.

        Access ``none`` is recorded too. A study that gives one participant a
        coaching channel has to be able to show that the other participant did not
        have it, and the room's own membership map is memory, not evidence.

        A composed activity's game channel is written down the same way. The room
        does not hold it -- a game channel is not a conversation -- so who plays is
        decided here: the people do, and a model seat of the conversation does not.
        (A model that plays as well as talks arrives with W7.)
        """
        for member in room.members():
            for channel_key in self._channel_keys(room):
                if channel_key == self._game_channel:
                    plays = (
                        member.kind == "participant" or member.actor_id in self._players
                    )
                else:
                    plays = member.may_see(channel_key)
                membership = Membership(
                    interaction_id=interaction_id,
                    actor_id=member.actor_id,
                    channel_key=channel_key,
                    access="read_write" if plays else "none",
                )
                aggregate_id = membership_id_for(
                    self._gateway.derived_id,
                    interaction_id,
                    member.actor_id,
                    channel_key,
                )
                await record_membership(
                    membership,
                    context=self._gateway.mint(
                        _envelope(
                            "interaction.membership",
                            aggregate_id,
                            {"interaction_id": interaction_id},
                            _fresh_idem(self._gateway),
                        ),
                        principal=principal,
                        data_handling=_RESEARCH,
                    ),
                    store=self._store,
                )

    def _channel_keys(self, room: ChatRoom) -> tuple[str, ...]:
        """Return every channel of the interaction, the game one included."""
        if self._game_channel is None:
            return room.channel_keys
        return (*room.channel_keys, self._game_channel)

    async def leave(self, visit_id: str, reason: str) -> None:
        """Record why one conversation ended, once, when its first seat leaves."""
        seat = self._seats.pop(visit_id, None)
        if seat is None:
            return
        left = [visit_id] if reason != "completed" else []
        context = self._gateway.mint(
            _envelope(
                "interaction.finalize",
                seat.room.interaction_id,
                {"interaction_id": seat.room.interaction_id},
                _fresh_idem(self._gateway),
            ),
            principal=_service_principal(self._gateway),
            data_handling=_RESEARCH,
        )
        await finalize_interaction(
            interaction_id=seat.room.interaction_id,
            reason=reason,
            closed_at=_instant(),
            context=context,
            store=self._store,
            left=left,
        )


# -- several people in one environment ------------------------------------------


@dataclass(frozen=True)
class PlaySeat:
    """One connection's place in a multi-seat game: which seat, in which interaction.

    ``index`` is the seat's position in the cast's own order, which is what binds a
    person to one of the game's declared human seats. The order is the interaction's
    and is recorded, so the same person plays the same seat on a reconnection and a
    replay names the same seat the run did.
    """

    interaction_id: str
    seat_key: str
    actor_id: str
    index: int


@dataclass
class _SeatWait:
    """One connection waiting at a multi-seat game for the seats to fill."""

    visit_id: str
    activity_key: str | None
    principal: PrincipalRef
    future: asyncio.Future[PlaySeat]


class SeatMatchmaker:
    """Rendezvous the connections at a multi-human game into one cast interaction.

    It is what a conversation's ``ChatMatchmaker`` is, for a game with no
    conversation beside it: several people need the same thing several talkers need
    -- wait until the seats are full, cast one interaction, and give each connection
    its own seat in it. The difference is what the interaction carries. This one
    declares the game channel and nothing else, so there is no room, no transcript,
    and no message order to keep.

    An activity that **does** have a conversation does not use this. It takes its
    seats from the room the conversation formed, because one activity is one
    interaction and casting it twice would make two.
    """

    def __init__(
        self,
        gateway: Gateway,
        store: Store,
        *,
        channel_key: str,
        size: int,
        study_version: StudyVersionRef | None = None,
    ) -> None:
        self._gateway = gateway
        self._store = store
        self._channel_key = channel_key
        self._formation = RoomFormation(
            new_id=gateway.new_id,
            now=_instant,
            study_version=study_version or _CHAT_STUDY,
            group_key=channel_key,
            channels=[ChannelSpec(key=channel_key, type="game")],
            size=size,
        )
        self._waiting: dict[str, _SeatWait] = {}
        self._seats: dict[str, PlaySeat] = {}
        self._lock = asyncio.Lock()

    async def join(
        self, *, visit_id: str, activity_key: str | None, principal: PrincipalRef
    ) -> PlaySeat:
        """Wait for the seats to fill and return this connection's seat.

        A visit that comes back is given the seat it already holds rather than a
        new one, so a participant who reloads mid-game sits back down where they
        were instead of waiting for a group that has already formed.
        """
        async with self._lock:
            seated = self._seats.get(visit_id)
            if seated is not None:
                return seated
            enrollment_id = self._gateway.new_id("enrollment")
            future: asyncio.Future[PlaySeat] = (
                asyncio.get_running_loop().create_future()
            )
            self._formation.submit(enrollment_id=enrollment_id, visit_id=visit_id)
            self._waiting[enrollment_id] = _SeatWait(
                visit_id=visit_id,
                activity_key=activity_key,
                principal=principal,
                future=future,
            )
            result = self._formation.poll()
            if result.status == "formed":
                await self._open(result)
        return await future

    async def _open(self, result: RoomResult) -> None:
        """Cast one formed group into seats, record it, and resolve every waiter."""
        assert result.group is not None and result.interaction is not None
        members = [
            self._waiting.pop(enrollment_id)
            for enrollment_id in result.group.members
            if enrollment_id in self._waiting
        ]
        seat_keys = sorted(result.cast)
        for index, (seat_key, wait) in enumerate(zip(seat_keys, members, strict=True)):
            self._seats[wait.visit_id] = PlaySeat(
                interaction_id=result.interaction.interaction_id,
                seat_key=seat_key,
                actor_id=result.cast[seat_key],
                index=index,
            )
        await self._record_open(result, members)
        for wait in members:
            if not wait.future.done():
                wait.future.set_result(self._seats[wait.visit_id])

    async def _record_open(self, result: RoomResult, members: list[_SeatWait]) -> None:
        """Record that the interaction opened, its channel, and who plays in it."""
        assert result.interaction is not None
        interaction = result.interaction
        principal = members[0].principal
        await open_interaction(
            interaction,
            activity_key=members[0].activity_key,
            opened_at=_instant(),
            context=self._context(
                "interaction.open", interaction.interaction_id, principal
            ),
            store=self._store,
        )
        for instance in result.instances:
            await record_channel(
                instance,
                context=self._context(
                    "interaction.channel", instance.channel_instance_id, principal
                ),
                store=self._store,
            )
        for actor_id in sorted(result.cast.values()):
            membership = Membership(
                interaction_id=interaction.interaction_id,
                actor_id=actor_id,
                channel_key=self._channel_key,
                access="read_write",
            )
            aggregate_id = membership_id_for(
                self._gateway.derived_id,
                interaction.interaction_id,
                actor_id,
                self._channel_key,
            )
            await record_membership(
                membership,
                context=self._context(
                    "interaction.membership", aggregate_id, principal
                ),
                store=self._store,
            )

    def _context(
        self, name: str, aggregate_id: str, principal: PrincipalRef | None = None
    ) -> CommandContext:
        """Mint one command context on the given aggregate's stream.

        The records of a group forming are attributed to a participant who was
        there, the way a conversation's are. Closing it is the platform's own,
        because the participant it would be attributed to may be the one who left.
        """
        return self._gateway.mint(
            _envelope(
                name,
                aggregate_id,
                {"aggregate_id": aggregate_id},
                _fresh_idem(self._gateway),
            ),
            principal=principal or _service_principal(self._gateway),
            data_handling=_RESEARCH,
        )

    async def leave(self, visit_id: str, reason: str) -> None:
        """Record why one seated game ended, once, when its first seat leaves."""
        seat = self._seats.pop(visit_id, None)
        if seat is None:
            return
        await finalize_interaction(
            interaction_id=seat.interaction_id,
            reason=reason,
            closed_at=_instant(),
            context=self._context("interaction.finalize", seat.interaction_id),
            store=self._store,
            left=[visit_id] if reason != "completed" else [],
        )


class Conversations:
    """The conversations a study wrote on its game activities, and their rooms.

    A conversation is written on the activity it happens in, so the rendezvous is
    **per activity**: each activity forms its own room, because each activity is
    its own interaction with its own lifecycle.

    What the author's own value decides is something else -- whether two activities
    are one conversation or two. The same written conversation placed on two
    activities names one channel definition, so each activity's channel instance is
    one run of the same channel and the transcript carries from the first to the
    second. Two written conversations name two definitions and start fresh.
    """

    def __init__(
        self,
        gateway: Gateway,
        store: Store,
        study: Study,
        *,
        specs: Mapping[str, ChatSpec],
        study_version: StudyVersionRef | None = None,
    ) -> None:
        self._gateway = gateway
        self._store = store
        self._study = study
        self._study_version = study_version
        self._matchmakers: dict[str, ChatMatchmaker] = {}
        # What the author wrote, already compiled, by activity key. It is compiled
        # by the caller because compiling it is what ``mug.mounts`` does for every
        # authored conversation, and that module is above this one.
        self._specs = dict(specs)

    def spec_at(self, session: Session) -> ChatSpec | None:
        """Return the conversation the activity this session is at carries."""
        key = _activity_key(session)
        return None if key is None else self._specs.get(key)

    def scope_at(self, session: Session) -> str | None:
        """Return the conversation this activity is part of, by the author's value."""
        key = _activity_key(session)
        return None if key is None else self._study.conversations.get(key)

    def at(
        self,
        session: Session,
        game_channel: str,
        players: Sequence[str] = (),
        people: int | None = None,
    ) -> ChatMatchmaker | None:
        """Return where this activity's room forms, or None when it has no chat.

        ``players`` are the actors that play this activity's game. They join the
        conversation as model members **before** the room records who was in it, so
        a seat that plays and talks is written down as a member of both channels
        rather than added afterwards and never recorded.

        ``people`` is how many human seats the game has. It decides the size of the
        room, because the room and the environment seat the same people and two
        statements of that number is one too many (R-15).
        """
        key = _activity_key(session)
        spec = self.spec_at(session)
        if key is None or spec is None:
            return None
        matchmaker = self._matchmakers.get(key)
        if matchmaker is None:
            matchmaker = ChatMatchmaker(
                self._gateway,
                self._store,
                spec,
                study_version=self._study_version,
                game_channel=game_channel,
                conversation_key=self.scope_at(session),
                players=players,
                participants=people,
            )
            self._matchmakers[key] = matchmaker
        return matchmaker


def _seat_channels(spec: ChatSpec, seat_key: str) -> tuple[str, ...]:
    """Return the channels one participant seat may see in the authored room."""
    return tuple(
        channel.key
        for channel in spec.room_channels
        if channel.seats is None or seat_key in channel.seats
    )


def _service_principal(gateway: Gateway) -> PrincipalRef:
    """Return the service principal a room's own records are written under."""
    return PrincipalRef(kind="service", id=gateway.new_id("service"))


def build_chat_on_game(
    gateway: Gateway,
    store: Store,
    spec: ChatSpec,
    *,
    rendezvous: ChatMatchmaker | None = None,
    diagnostics: Diagnostics | None = None,
) -> OnGame:
    """Build the activity hook that runs one chat conversation over the socket.

    This is the chat channel's counterpart to the game mounts: at the study's
    interactive activity the hook takes the socket over, carries the conversation
    between the participant and the study's model seats, records every message,
    delivery, and context snapshot as canonical API-08 evidence, and then advances
    the flow past the activity with the streams it wrote.

    A study whose conversation holds more than one participant gets a
    ``rendezvous``, and the connection waits at the activity until its room forms.
    A study with one participant per conversation gets none, and the mount forms its
    own room of one.

    The mount is the one impure boundary, exactly as it is for a game: it injects
    the store, the gateway's id minter and clock, and the per-aggregate command
    context factory, so the conversation runtime below holds none of them.
    """

    async def on_game(websocket: WebSocket, session: Session) -> None:
        visit_id = session.state.get("visit_id")
        reason = "completed"
        try:
            streams = await run_chat_activity(
                websocket,
                session,
                spec,
                store=store,
                new_context=lambda aggregate_id: _agent_context(
                    gateway, session, aggregate_id
                ),
                new_id=gateway.new_id,
                now=gateway.clock,
                durable=_chat_durability(gateway, store, session),
                rendezvous=rendezvous,
                gateway=gateway,
                diagnostics=diagnostics,
            )
        except WebSocketDisconnect:
            reason = "abandoned"
            raise
        finally:
            if rendezvous is not None and isinstance(visit_id, str):
                await rendezvous.leave(visit_id, reason)
        _, delivery = await _advance(
            gateway, store, session, {}, _fresh_idem(gateway), streams
        )
        if delivery is not None:
            _queue(session, delivery)

    return on_game


# -- the authenticated browser peer-to-peer game --------------------------------


def build_browser_p2p_on_game(
    gateway: Gateway, store: Store, coordinator: P2PCoordinator
) -> OnGame:
    """Build the game hook that runs one authenticated browser P2P room.

    At the game activity the connection joins the browser P2P waiting room. The
    hook owns the socket for that activity: one reader task decodes the browser's
    API-09 frames and applies them, and the coordinator pushes every room effect
    back through the one writer. The hook returns when the room finishes or
    aborts, and the flow then advances past the game.

    The browser holds only public handles. The hook binds each socket to its own
    enrollment, visit, and principal before the coordinator sees it, so a frame
    can never name its own identity.

    The mount needs a durable enrollment, so it needs the launch gate. A
    connection with no enrollment is not admitted to the waiting room, and its
    flow advances past the game with nothing captured.
    """

    async def on_game(websocket: WebSocket, session: Session) -> None:
        await _play_browser_p2p(websocket, session, coordinator)
        _, delivery = await _advance(
            gateway, store, session, {}, _fresh_idem(gateway), []
        )
        if delivery is not None:
            _queue(session, delivery)

    return on_game


async def _play_browser_p2p(
    websocket: WebSocket, session: Session, coordinator: P2PCoordinator
) -> RoomEnd | None:
    """Own the socket for one browser P2P room and return how the room ended.

    The socket is read from the moment the connection joins the waiting room, not
    from the moment a room forms. A browser can leave while it waits -- a closed
    tab is the common case -- and nothing else would notice: the coordinator only
    learns of a departure when this hook stops. So the waiting participant would
    hold a seat no one is in, and the browsers behind it would wait for a room
    that can never fill.

    Returns None when the connection carries no visit to seat, when the browser
    left the waiting room, or when the socket closed before the room reached a
    terminal effect.
    """
    visit_id = session.state.get("visit_id")
    enrollment_id = session.state.get("enrollment_id")
    if not isinstance(visit_id, str) or not isinstance(enrollment_id, str):
        return None

    async def send(effect: RoomEffect) -> None:
        await websocket.send_json(effect_frame(effect))

    identity = P2PConnectionIdentity(
        browser_session_handle=browser_session_handle(visit_id),
        enrollment_id=enrollment_id,
        visit_id=visit_id,
        principal=session.principal,
    )
    connection = await coordinator.connect(identity, send)
    try:
        room = await coordinator.enqueue(connection)
        reader = asyncio.create_task(
            _read_browser_p2p(websocket, coordinator, connection)
        )
        try:
            # Either a room forms or the browser goes away. Waiting on the reader
            # too is what turns a closed socket into a released seat, and later
            # into an abort for the other peers: a connection that only waited on
            # a future would never notice.
            await asyncio.wait((reader, room), return_when=asyncio.FIRST_COMPLETED)
            if not room.done():
                return None
            assignment = room.result()
            await websocket.send_json(bootstrap_frame(assignment))
            await asyncio.wait(
                (reader, assignment.ended), return_when=asyncio.FIRST_COMPLETED
            )
            return assignment.ended.result() if assignment.ended.done() else None
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
    finally:
        await coordinator.disconnect(connection)


async def _read_browser_p2p(
    websocket: WebSocket, coordinator: P2PCoordinator, connection: P2PConnection
) -> None:
    """Decode and apply the browser's P2P frames until the socket closes.

    A frame the edge refuses does not close the socket: a signal is answered with
    a rejected acknowledgement, and any other refusal is dropped. Only a
    disconnect ends the loop, so one bad frame cannot end a live room.
    """
    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return
        try:
            loaded: Any = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(loaded, dict):
            continue
        message = cast("dict[str, Any]", loaded)
        if not is_p2p_frame(message):
            continue
        try:
            reply = await apply_frame(coordinator, connection, message)
        except (P2PFrameError, P2PRoomError, P2PEdgeError, ValueError):
            continue
        if reply is not None:
            await websocket.send_json(reply)
