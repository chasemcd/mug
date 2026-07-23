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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from mug.agents import (
    AgentGameSpec,
    TurnBasedGameSpec,
    build_agent_episode,
    build_turnbased_episode,
)
from mug.client import RealtimeCommand
from mug.content import (
    AdvanceFlowCommand,
    FlowState,
    MaterializeFlowCommand,
    advance_flow,
    materialize_flow,
    present,
)
from mug.game import RenderPacket
from mug.game.aec import TurnBasedSummary, TurnStepInfo
from mug.game.browser import (
    BrowserGameSpec,
    ClientEpisodeError,
    capture_browser_episode,
    client_manifest,
    parse_client_episode,
)
from mug.game.capture import capture_episode
from mug.game.env import GymEnv
from mug.game.mesh_session import (
    MeshEpisode,
    MeshGameSpec,
    MeshSession,
    SeatWiring,
)
from mug.game.multiseat import MultiSeatStepInfo, MultiSeatSummary
from mug.game.runtime import EpisodeSummary, InputState, run_episode
from mug.game.spec import GameSpec
from mug.gateway import Gateway
from mug.identity import EnrollCommand, LaunchTicket, enroll
from mug.interactions import FormationResult, MeshFormationService
from mug.interactions.types import FifoMatch
from mug.kernel import (
    CommandReceipt,
    CommandTypeRef,
    DataHandlingRef,
    Digest,
    PrincipalRef,
    WireCommandEnvelope,
)
from mug.kernel.refs import StudyVersionRef
from mug.providers import ModelCallResult
from mug.realtime import (
    Establish,
    OnGame,
    OnOpen,
    RealtimeDispatch,
    Session,
    SessionRejected,
)
from mug.replay import ReplayBundle, build_decision_tape, build_replay_bundle
from mug.replay.verify import verify_browser_episode
from mug.returns import ReturnClaims, sign_return_link, verify_return_link
from mug.runtime import CommandContext, reject_command
from mug.storage import ArtifactStore, Store
from mug.visits import StartVisitCommand, start_visit

_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_ENVELOPE_DIGEST = Digest(algorithm="sha-256", hex="0" * 64)
_ADVANCE_CHANNEL = "flow.advance"
_CAPTURE_CHANNEL = "game.capture"
_CAPTURE_COMMAND = CommandTypeRef(name="game.capture", version=0)
_SEAT_KEY = "player"
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
    """Queue one activity delivery, and route the game by its execution mode.

    A server-mode game marks the session ready, so the transport runs the server
    stepping loop. A browser-mode game ships the public client manifest instead
    and waits for the client to report its run, so no server loop runs.
    """
    kind = delivery.get("kind")
    if kind == "complete":
        return_url = session.state.get("return_url")
        if isinstance(return_url, str):
            delivery = {**delivery, "return_url": return_url}
    if kind == "game":
        countdown = session.state.get("countdown_seconds", 0)
        manifest = session.state.get("browser_manifest")
        if isinstance(manifest, dict):
            delivery = {**delivery, "mode": "browser", "manifest": manifest}
        else:
            delivery = {**delivery, "mode": "server"}
        delivery = {**delivery, "countdown": countdown}
    session.deliver(delivery)
    if kind == "game" and not session.state.get("browser_manifest"):
        session.state["run_game"] = True


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
    receipt = await advance_flow(
        AdvanceFlowCommand(
            answers=answers, expected_revision=revision, captured_streams=streams
        ),
        context=context,
        store=store,
    )
    if receipt.outcome != "accepted":
        return receipt, None
    session.state["flow_revision"] = revision + 1
    state = FlowState.model_validate(store.load_aggregate(flow_id))
    return receipt, present(state)


async def _materialize(
    gateway: Gateway, store: Store, session: Session, visit_id: str
) -> str | None:
    """Materialize one flow for a visit and seed the session pointers.

    Returns the flow id, or None when the materialize command does not commit.
    """
    flow_id = gateway.new_id("visitplan")
    envelope = _envelope(
        "flow.materialize", flow_id, {"visit_id": visit_id}, _fresh_idem(gateway)
    )
    context = gateway.mint(
        envelope, principal=session.principal, data_handling=_RESEARCH
    )
    receipt = await materialize_flow(
        MaterializeFlowCommand(visit_id=visit_id), context=context, store=store
    )
    if receipt.outcome != "accepted":
        return None
    session.state["flow_id"] = flow_id
    session.state["visit_id"] = visit_id
    session.state["flow_revision"] = 1
    return flow_id


async def _resume(store: Store, session: Session, flow_id: str) -> bool:
    """Rehydrate the flow pointer, and restore the enrollment identity if present.

    A launch-gated flow was started for a durable enrollment: the resume walks the
    flow to its visit to its enrollment and rebinds the session principal, so a
    reconnection continues the same pseudonymous participant rather than minting a
    second research identity. A non-gated flow has no visit or enrollment record,
    so the walk finds none and the provisional principal stands.
    """
    raw = store.load_aggregate(flow_id)
    if raw is None:
        return False
    state = FlowState.model_validate(raw)
    visit = store.load_aggregate(state.visit_id)
    if isinstance(visit, dict):
        enrollment_id = cast("dict[str, Any]", visit).get("enrollment_id")
        enrollment = (
            store.load_aggregate(enrollment_id)
            if isinstance(enrollment_id, str)
            else None
        )
        if isinstance(enrollment, dict):
            principal = cast("dict[str, Any]", enrollment).get("principal")
            if isinstance(principal, dict):
                session.principal = PrincipalRef.model_validate(principal)
    session.state["flow_id"] = flow_id
    session.state["visit_id"] = state.visit_id
    session.state["flow_revision"] = state.version.revision
    return True


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
        "enrollment.enroll", enrollment_id, {"study_id": ticket.study_id},
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

    return await _materialize(gateway, store, session, visit_id)


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


def build_establish(
    gateway: Gateway,
    store: Store,
    return_url: str | None = None,
    browser: BrowserGameSpec | None = None,
    countdown_seconds: int = 0,
    launch: bool = False,
    *,
    signing_key: bytes,
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
    so the client runs the environment and reports its run under those ids.
    """

    async def establish(session: Session) -> dict[str, Any]:
        if return_url is not None:
            session.state["return_url"] = return_url
        session.state["countdown_seconds"] = countdown_seconds
        if browser is not None:
            episode_id = gateway.new_id("episode")
            interaction_id = gateway.new_id("interaction")
            session.state["episode_id"] = episode_id
            session.state["interaction_id"] = interaction_id
            session.state["browser_manifest"] = client_manifest(
                browser,
                episode_id=episode_id,
                interaction_id=interaction_id,
                seat_key=_SEAT_KEY,
            )
        token = session.state.get("resume_token")
        if isinstance(token, str):
            resumed_id, status = _resume_flow_id(signing_key, token)
            if resumed_id is not None and await _resume(store, session, resumed_id):
                return {"resume_token": token}
            if launch:
                _refuse_return(status)
        if launch:
            flow_id = await _enter_with_ticket(gateway, store, session)
        else:
            flow_id = await _materialize(
                gateway, store, session, gateway.new_id("visit")
            )
        if flow_id is None:
            return {}
        return {"resume_token": _return_token(signing_key, flow_id)}

    return establish


def build_open(store: Store) -> OnOpen:
    """Build the open hook that presents the flow's current activity.

    The flow is already established (fresh or resumed). A browser game announces
    its bundle first, so the client boots Pyodide and installs the packages during
    the forms and the game never waits on a blank canvas. Then the current
    activity is presented, so a reconnection resumes where the participant stopped.
    """

    async def on_open(session: Session) -> None:
        flow_id = session.state.get("flow_id")
        if not isinstance(flow_id, str):
            return
        manifest = session.state.get("browser_manifest")
        if isinstance(manifest, dict):
            session.deliver({"kind": "preload", "manifest": manifest})
        state = FlowState.model_validate(store.load_aggregate(flow_id))
        _queue(session, present(state))

    return on_open


def build_dispatch(
    gateway: Gateway, store: Store, browser: BrowserGameSpec | None = None
) -> RealtimeDispatch:
    """Build the dispatch that advances the flow on a participant command.

    ``flow.advance`` steps the flow forward as the participant answers a form. A
    browser game also routes ``game.capture``: the client reports its finished
    run, the server validates it into the transition contract, commits it under
    browser authority and a producer generation, and advances past the game.
    """

    async def dispatch(
        command: RealtimeCommand, payload: Any, session: Session
    ) -> CommandReceipt | None:
        if not isinstance(session.state.get("flow_id"), str):
            return None
        data = cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}
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


async def _capture_client_episode(
    gateway: Gateway,
    store: Store,
    session: Session,
    browser: BrowserGameSpec,
    data: dict[str, Any],
    idem: str,
) -> CommandReceipt:
    """Validate and commit one client-reported episode, then advance the flow."""
    episode_id = cast("str", session.state["episode_id"])
    visit_id = cast("str", session.state["visit_id"])
    generation = _generation_of(data)
    envelope = _envelope(
        "game.capture", episode_id, {"episode_id": episode_id}, idem
    )
    context = gateway.mint(
        envelope, principal=session.principal, data_handling=_RESEARCH
    )
    try:
        summary = parse_client_episode(
            data.get("episode"),
            expected_channel_key=browser.channel_key,
            expected_episode_id=episode_id,
            seat_key=_SEAT_KEY,
        )
    except ClientEpisodeError:
        return reject_command(
            context,
            command=_CAPTURE_COMMAND,
            code="schema.validation_failed",
            category="validation",
            message="the reported episode did not validate",
            retry="never",
        )
    report = verify_browser_episode(
        browser, actions=_actions_of(data), summary=summary
    )
    if report.verification == "deterministic" and not report.verified:
        return reject_command(
            context,
            command=_CAPTURE_COMMAND,
            code="game.verification_failed",
            category="validation",
            message="the reported episode did not match the re-execution",
            retry="never",
        )
    receipt = await capture_browser_episode(
        summary,
        visit_id=visit_id,
        context=context,
        epoch_id=gateway.new_id("prodepoch"),
        generation=generation,
        store=store,
        verification=report.verification,
        state_hash_chain_digest=report.state_hash_chain_digest,
    )
    if receipt.outcome != "accepted":
        return receipt
    _, delivery = await _advance(
        gateway, store, session, {}, _fresh_idem(gateway), [context.stream_id]
    )
    if delivery is not None:
        _queue(session, delivery)
    return receipt


def _generation_of(data: dict[str, Any]) -> int:
    """Read the client writer generation, clamped to a positive integer."""
    raw = data.get("generation", 1)
    return raw if isinstance(raw, int) and raw >= 1 else 1


def _actions_of(data: dict[str, Any]) -> list[int]:
    """Read the client action sequence the server re-executes to verify the run.

    Only whole-number actions pass through; a bool is not an action. A missing or
    malformed sequence yields no actions, so the verifier finds an action-count
    mismatch and the run does not verify.
    """
    raw = data.get("actions")
    if not isinstance(raw, list):
        return []
    actions = cast("list[Any]", raw)
    return [
        item
        for item in actions
        if isinstance(item, int) and not isinstance(item, bool)
    ]


def build_on_game(gateway: Gateway, store: Store, game: GameSpec | None) -> OnGame:
    """Build the hook that runs the study game over the socket, then advances.

    The study supplies the ``game`` specification: its environment, its key
    bindings, and its drawing. The loop owns the socket while it runs -- one task
    reads input frames into the seat input state, and the loop pushes a render
    packet per frame. When the episode ends the run is captured to the ledger and
    the flow advances past the game, recording the episode stream on the visit. If
    no game is configured the flow advances straight past the game activity.
    """

    async def on_game(websocket: WebSocket, session: Session) -> None:
        captured: list[str] = []
        if game is not None:
            summary = await _play(websocket, session, game)
            captured = [await _capture(session, summary)]
        _, delivery = await _advance(
            gateway, store, session, {}, _fresh_idem(gateway), captured
        )
        if delivery is not None:
            _queue(session, delivery)

    async def _capture(session: Session, summary: EpisodeSummary) -> str:
        """Commit the played episode to its stream and return the stream id."""
        episode_id = summary.boundary.episode_id
        visit_id = cast("str", session.state["visit_id"])
        envelope = _envelope(
            "episode.capture", episode_id, {"episode_id": episode_id},
            _fresh_idem(gateway),
        )
        context = gateway.mint(
            envelope, principal=session.principal, data_handling=_RESEARCH
        )
        await capture_episode(
            summary, visit_id=visit_id, context=context, store=store
        )
        return context.stream_id

    async def _play(
        websocket: WebSocket, session: Session, spec: GameSpec
    ) -> EpisodeSummary:
        env = GymEnv(spec.make_env)
        episode_id = gateway.new_id("episode")
        interaction_id = gateway.new_id("interaction")
        inputs = InputState(spec.action_bindings, spec.default_action)

        async def sink(packet: RenderPacket) -> None:
            await websocket.send_json(
                {"type": "render", "packet": packet.model_dump(
                    mode="json", exclude_none=True
                )}
            )

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
            )
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader

    return on_game


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
        assert result.interaction is not None
        assert result.mesh_membership_digest is not None
        members = [
            self._joins[enrollment_id]
            for enrollment_id in result.group.members
            if enrollment_id in self._joins
        ]
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
        episode_id = self._gateway.new_id("episode")
        session = MeshSession(
            seats=seats,
            spec=self._spec,
            interaction_id=result.interaction.interaction_id,
            episode_id=episode_id,
            mesh_membership_digest=result.mesh_membership_digest,
            membership_generation=result.membership_generation,
            recorded_at=_instant(),
        )
        episode = await session.run()
        stream_id = await self._capture(episode, members[0])
        outcome = _SeatOutcome(stream_id=stream_id, verified=episode.verified)
        for join in members:
            self._joins.pop(join.enrollment_id, None)
            if not join.future.done():
                join.future.set_result(outcome)

    async def _capture(self, episode: MeshEpisode, reference: _MeshJoin) -> str:
        """Commit the mesh's reference run once, and return its episode stream id."""
        summary = episode.reference_summary()
        episode_id = summary.boundary.episode_id
        envelope = _envelope(
            "episode.capture", episode_id, {"episode_id": episode_id},
            _fresh_idem(self._gateway),
        )
        context = self._gateway.mint(
            envelope, principal=reference.principal, data_handling=_RESEARCH
        )
        await capture_episode(
            summary, visit_id=reference.visit_id, context=context, store=self._store
        )
        return context.stream_id


def build_mesh_on_game(
    gateway: Gateway, store: Store, matchmaker: MeshMatchmaker
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
    websocket: WebSocket, session: Session, matchmaker: MeshMatchmaker
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
    inputs = InputState(spec.action_bindings, spec.default_action)

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
            principal=session.principal,
            action=inputs.action,
            send=send,
        )
    finally:
        reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reader


# -- the multi-seat agent game -------------------------------------------------

# A caller that wants the assembled replay bundle (its manifest and validation)
# passes this sink; the agent game hands it every episode's bundle at capture time.
BundleSink = Callable[[ReplayBundle], Awaitable[None]]


def build_agent_on_game(
    gateway: Gateway,
    store: Store,
    spec: AgentGameSpec,
    *,
    on_bundle: BundleSink | None = None,
) -> OnGame:
    """Build the game hook that runs a multi-seat agent episode over the socket.

    The study supplies the ``spec``: its multi-agent environment, its model seats,
    and an optional human seat the participant plays beside them. The hook runs one
    episode -- the models decide off the frame clock, the loop steps every seat, and
    each stepped frame is pushed to the socket so a participant watches -- then
    captures the run to the ledger, assembles the replay bundle from the run's model
    calls, and advances the flow past the game.

    A model call's decision tape and the canonical stream fold into one replay
    bundle here, so a real agent run produces the same durable, replayable artifact a
    human run does. When no model produced an output the bundle carries no tape.
    """

    async def on_game(websocket: WebSocket, session: Session) -> None:
        stream_id = await _play_agents(
            websocket, session, spec, gateway, store, on_bundle
        )
        captured = [stream_id] if stream_id is not None else []
        _, delivery = await _advance(
            gateway, store, session, {}, _fresh_idem(gateway), captured
        )
        if delivery is not None:
            _queue(session, delivery)

    return on_game


async def _play_agents(
    websocket: WebSocket,
    session: Session,
    spec: AgentGameSpec,
    gateway: Gateway,
    store: Store,
    on_bundle: BundleSink | None,
) -> str | None:
    """Own the socket for one agent episode: run it, capture it, and bundle it.

    A human seat, when the spec names one, is fed by a reader task from the
    participant's input frames while the loop reads the held action each frame -- the
    same seam the single-seat loop uses. Returns the captured episode stream id, or
    None when the connection carries no visit to seat.
    """
    visit_id = session.state.get("visit_id")
    if not isinstance(visit_id, str):
        return None
    interaction_id = gateway.new_id("interaction")
    episode_id = gateway.new_id("episode")

    human_source: InputState | None = None
    reader: asyncio.Task[None] | None = None
    if spec.human is not None:
        human_source = InputState(spec.action_bindings, spec.default_action)
        reader = asyncio.create_task(_read_inputs_into(websocket, human_source))

    async def frame_sink(info: MultiSeatStepInfo) -> None:
        await websocket.send_json(
            {"type": "frame", "frame_number": info.frame, "actions": info.actions}
        )

    episode = build_agent_episode(
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
        gateway, store, interaction_id, stream_id, result.model_calls(), on_bundle
    )
    return stream_id


async def _read_inputs_into(websocket: WebSocket, inputs: InputState) -> None:
    """Feed a human seat's input state from the connection's input frames."""
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
        "agent.step", aggregate_id, {"aggregate_id": aggregate_id},
        _fresh_idem(gateway),
    )
    return gateway.mint(
        envelope, principal=session.principal, data_handling=_RESEARCH
    )


async def _capture_multiseat(
    gateway: Gateway,
    store: Store,
    session: Session,
    summary: MultiSeatSummary | TurnBasedSummary,
) -> str:
    """Capture a multi-seat or turn-based episode and return the stream id.

    Both summaries name every seat, so the episode summary joins the seat keys; the
    capture aggregate then records the run under one seat-key field.
    """
    episode = EpisodeSummary(
        channel_key=summary.channel_key,
        seat_key="+".join(summary.seat_keys),
        frames=summary.frames,
        transitions=summary.transitions,
        boundary=summary.boundary,
        solved=summary.solved,
    )
    episode_id = summary.boundary.episode_id
    visit_id = cast("str", session.state["visit_id"])
    envelope = _envelope(
        "episode.capture", episode_id, {"episode_id": episode_id},
        _fresh_idem(gateway),
    )
    context = gateway.mint(
        envelope, principal=session.principal, data_handling=_RESEARCH
    )
    await capture_episode(episode, visit_id=visit_id, context=context, store=store)
    return context.stream_id


async def _bundle_agent_run(
    gateway: Gateway,
    store: Store,
    interaction_id: str,
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
        human_source = InputState(spec.action_bindings, spec.default_action)
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
        gateway, store, interaction_id, stream_id, result.model_calls(), on_bundle
    )
    return stream_id
