"""The composition root: wire the store, gateway, edge, web shell, and realtime.

This module is the one place that builds a running application from the parts. It
replaces the module-global pattern of the legacy server. It reuses the edge for
the command surface, serves a static client shell, and runs the realtime session
loop for each websocket connection.

The application is the outermost layer. It may import any inner layer to wire it,
but no inner layer imports the application, and the import-linter forbids it from
importing the legacy runtime.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Coroutine, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone
from pathlib import Path
from typing import Any, TypeVar, cast

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from mug.admission import Admission, AdmissionPolicy
from mug.agents import AgentGameSpec, TurnBasedGameSpec
from mug.agents.generation import (
    GenerationSet,
    RecordedGeneration,
    record_generations,
)
from mug.authoring import GitProvenance
from mug.client.ice import IceGrantError
from mug.client.p2p import P2PIceGrantRequest
from mug.content import Conversation, Step, Study, demo_study
from mug.content.assets import StagedAsset, asset_manifest, by_digest, stage_assets
from mug.content.publish import PublishedStudy, compile_and_publish
from mug.content.seats import MultiSeatGame, Seating, seat_game
from mug.diagnostics import (
    Diagnostics,
    NullDiagnostics,
    RecordingDiagnostics,
)
from mug.edge import build_app
from mug.export import export_visit
from mug.game.browser import BrowserGameSpec
from mug.game.browser_mesh import browser_mesh_manifest
from mug.game.mesh_session import MeshGameSpec
from mug.game.spec import GameSpec
from mug.gateway import Gateway
from mug.interactions.bus import NodeBus, NodeLink, StoreBus
from mug.interactions.lifecycle import operator_view
from mug.interactions.rendezvous import DurableRendezvous
from mug.kernel import (
    DataHandlingRef,
    Digest,
    PrincipalRef,
    WireCommandEnvelope,
)
from mug.kernel.refs import DeploymentRevisionRef, StudyVersionRef
from mug.launch import provision_launch_ticket
from mug.mounts import (
    Mount,
    chat_for,
    chats_beside_games,
    chats_for,
    mounts_for,
)
from mug.nodes import Node
from mug.observability import InMemoryTelemetry, Telemetry
from mug.participant import (
    ChatMatchmaker,
    Conversations,
    MeshMatchmaker,
    MeshRendezvous,
    NodeMeshMatchmaker,
    PooledMeshMatchmaker,
    ServerGameSpec,
    build_activity_on_game,
    build_agent_on_game,
    build_browser_p2p_on_game,
    build_chat_on_game,
    build_close,
    build_comparison_on_game,
    build_dispatch,
    build_establish,
    build_measure,
    build_mesh_on_game,
    build_on_game,
    build_open,
    build_routed_on_game,
    build_server_on_game,
    build_turnbased_on_game,
    warming,
)
from mug.participant_chat import ChatSpec
from mug.participant_p2p import P2PCoordinator
from mug.participant_p2p_types import (
    BrowserP2PConfig,
    P2PEdgeError,
    browser_session_handle,
)
from mug.platform.deployment import Deployment, open_deployment
from mug.realtime import Establish, OnGame, ResolvePrincipal, Session, serve_session
from mug.replay import ReplayBundle
from mug.runtime import CommandContext
from mug.storage import ArtifactStore, InMemoryStore, Store

_T = TypeVar("_T")

_WEB = Path(__file__).resolve().parent / "webclient"
_PROTOCOL_VERSION = "0.1.0"

# A placeholder pseudonymous participant for the HTTP setup commands. The realtime
# transport mints a fresh per-connection subject instead (see ``_resolve_subject``).
_DEMO_PARTICIPANT = PrincipalRef(
    kind="participant", id="participant_019b6000-0000-7000-8000-0000000000aa"
)

# The researcher principal that provisions the demo's launch ticket.
_DEMO_RESEARCHER = PrincipalRef(
    kind="researcher", id="researcher_019b6000-0000-7000-8000-0000000000ab"
)


def _pseudonymous_participant(_request: Request) -> PrincipalRef:
    """Resolve the acting principal for the demo (a fixed pseudonymous subject)."""
    return _DEMO_PARTICIPANT


def _resolve_subject(gateway: Gateway) -> ResolvePrincipal:
    """Build a resolver that mints a fresh pseudonymous participant per connection.

    The gateway is the one entropy boundary, so it mints the subject identifier.
    A restart draws new subjects; a durable identity is out of the demo slice.
    """

    def resolve(_websocket: WebSocket) -> PrincipalRef:
        return PrincipalRef(kind="participant", id=gateway.new_id("participant"))

    return resolve


# The client shell must always be revalidated.
#
# A study's declared pictures are served at the address of their own bytes, so a
# browser may hold them for ever. The shell can not be: it keeps one address and
# its bytes change when the client is rebuilt. With no ``cache-control`` a
# browser applies its own heuristic from ``last-modified`` and can serve a shell
# it fetched days ago -- so a deployment reaches a new participant and not a
# returning one, and the two are then running different clients against the same
# study. ``no-cache`` does not stop the browser storing it; it stops the browser
# using it without asking, which is a conditional request and one 304.
_REVALIDATE = "no-cache"


class _ShellFiles(StaticFiles):
    """The client's own files, served so a browser always asks if they changed."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["cache-control"] = _REVALIDATE
        return response


def _add_web_shell(app: FastAPI, web_root: Path) -> None:
    """Serve the static client shell and its assets from ``web_root``.

    The default root is the bundled JavaScript client. A deployment or a test may
    point ``web_root`` at another built client (for example the TypeScript client
    under ``ts/dist-web``); the directory must hold an ``index.html`` shell and the
    assets it loads under ``/static``.
    """
    app.mount("/static", _ShellFiles(directory=web_root), name="static")

    @app.get("/")
    async def index() -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        return FileResponse(
            web_root / "index.html", headers={"cache-control": _REVALIDATE}
        )


def _add_assets(app: FastAPI, store: Store, staged: Mapping[str, StagedAsset]) -> None:
    """Serve the study's declared pictures, each at the address of its own bytes.

    The digest is the whole address, so the response is immutable: a browser may
    cache it forever, and no request can reach bytes the study did not declare. A
    digest nobody declared is a not-found rather than a lookup in the object store,
    because the artifact layer holds far more than the pictures.
    """
    if not staged:
        return
    index = by_digest(staged)

    @app.get("/assets/{digest_hex}")
    async def asset(digest_hex: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        found = index.get(digest_hex)
        if found is None:
            raise HTTPException(status_code=404, detail="no such asset")
        data = await cast("ArtifactStore", store).read_artifact(found.artifact_id)
        return Response(
            content=data,
            media_type=found.media_type,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )


def _add_export(app: FastAPI, store: Store) -> None:
    """Serve one visit's canonical lineage as a JSONL download.

    A researcher exports a finished visit by its flow id. An unknown flow answers
    a not-found. The demo leaves this open; a real deployment gates it behind
    researcher authentication.
    """

    @app.get("/export/{flow_id}")
    async def export(flow_id: str) -> PlainTextResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            result = export_visit(store, flow_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail="no such visit") from error
        return PlainTextResponse(result.jsonl, media_type="application/x-ndjson")


def _add_operator_view(app: FastAPI, store: Store) -> None:
    """Serve the read-only operator view of the live and completed interactions.

    An operator's first question is what is happening right now, and it is only
    useful beside what happened. The projection carries interaction ids, activity
    keys, participant counts, and terminal reasons -- every field internal and
    pseudonymous. **No external identity and no secret material reaches it**, which
    is what parity fixture 10 asks for and what keeps this from becoming a second
    way to reach the study's data.

    It is not authenticated and must not be reachable from outside the deployment,
    for the same reason the readiness numbers are not: how many people are in a
    study is not a public fact.
    """

    @app.get("/operator/interactions")
    async def interactions() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        rows = [
            view.model_dump(mode="json", exclude_none=True)
            for view in operator_view(store)
        ]
        live = sum(1 for view in operator_view(store) if view.closed_at is None)
        return JSONResponse(
            {"live": live, "total": len(rows), "interactions": rows},
            headers={"Cache-Control": "no-store"},
        )


def _add_operations(
    app: FastAPI, admission: Admission, telemetry: InMemoryTelemetry
) -> None:
    """Serve the three things an operator asks a running process.

    ``/healthz`` answers whether the process is alive. It says nothing about load, so
    a supervisor that reads it restarts a process that has stopped serving and leaves
    a busy one alone.

    ``/readyz`` answers whether the process should be sent more participants. A
    process at its session bound is alive but not ready: a load balancer that reads
    this stops adding to it, which is the difference between a queue in front of one
    process and a refusal at its door.

    ``/metrics`` renders the process's counters in the Prometheus text format. It
    names no participant and no principal -- the series are labelled by command,
    outcome, and error category only.

    None of the three is authenticated, and none should be reachable from outside the
    deployment: the readiness numbers say how loaded a study is.
    """

    @app.get("/healthz")
    async def healthz() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})

    @app.get("/readyz")
    async def readyz() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        limit = admission.policy.max_sessions
        open_sessions = admission.open_sessions
        ready = open_sessions < limit
        return JSONResponse(
            {
                "ready": ready,
                "open_sessions": open_sessions,
                "max_sessions": limit,
            },
            status_code=200 if ready else 503,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/metrics")
    async def metrics() -> PlainTextResponse:  # pyright: ignore[reportUnusedFunction]
        telemetry.gauge("mug_realtime_open_sessions", admission.open_sessions)
        return PlainTextResponse(
            telemetry.render_prometheus(),
            media_type="text/plain; version=0.0.4",
            headers={"Cache-Control": "no-store"},
        )


def _add_debug(
    app: FastAPI,
    diagnostics: Diagnostics,
    telemetry: InMemoryTelemetry,
    admission: Admission,
) -> None:
    """Serve what the run said about itself, to the person who is running it.

    Two paths, and both exist only in debug mode. A process that is not in debug mode
    mounts neither, so the answer to a request for them is the same 404 a study that
    has never heard of debugging gives -- which is the point. A note holds prompts,
    replies, and what a participant said; nothing about a live study should be able to
    ask for those and be answered.

    ``/_debug`` says the process is watching, and carries the counters beside the
    notes so one read answers "what is this process doing" as well as "what did the
    model say".

    ``/_debug/notes?since=N`` is the tail. A reader keeps the highest sequence it has
    seen and asks for what came after it, so a panel that polls twice a second is
    given what happened between the polls and nothing twice. The answer says which
    sequence is the oldest still held, so a reader that has fallen behind reads that
    it missed notes instead of rendering the gap as quiet.

    **This is the debug channel, and it is deliberately not the participant's.** A
    debugging aid that can break a run is worse than none: nothing here touches the
    websocket, the frame protocol, or anything a study records.
    """
    if not isinstance(diagnostics, RecordingDiagnostics):
        return
    watching = diagnostics

    def _status() -> dict[str, Any]:
        return {
            "debug": True,
            "open_sessions": admission.open_sessions,
            "max_sessions": admission.policy.max_sessions,
            "telemetry": telemetry.snapshot(),
        }

    @app.get("/_debug")
    async def debug_status() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse(
            {**_status(), **watching.since(0)}, headers={"Cache-Control": "no-store"}
        )

    @app.get("/_debug/notes")
    async def debug_notes(  # pyright: ignore[reportUnusedFunction]
        since: int = 0,
    ) -> JSONResponse:
        return JSONResponse(
            {**_status(), **watching.since(since)},
            headers={"Cache-Control": "no-store"},
        )


def _add_ice_endpoint(app: FastAPI, coordinator: P2PCoordinator) -> None:
    """Serve the same-origin, one-use ICE redemption for the browser P2P mount.

    The browser posts the grant handle it received in its bootstrap. The server
    answers with transient WebRTC configuration and nothing else: the response is
    ``no-store``, it is not a contract model, and it never enters an event, an
    artifact, a replay, or an export. The long-lived TURN secret stays in this
    process; the server derives a short-lived credential during redemption.

    The grant itself is the capability: it is unguessable, one-use, short-lived,
    and bound to one room and one peer, and it is only redeemable while the
    browser it was issued to holds a live connection seated in that live room.
    The visit binds it to a browser as a second factor, and this demo reads that
    visit from a request header when one is present. **A header is not
    authentication.** A deployment must carry the visit in its own authenticated
    same-origin session and pass that value here instead; a browser cannot supply
    it, because the client is never told its own visit. With no header the
    endpoint rests on the grant handle alone, which is the documented floor.
    """

    @app.post(coordinator.config.ice_endpoint)
    async def redeem_ice(  # pyright: ignore[reportUnusedFunction]
        request: Request,
    ) -> JSONResponse:
        visit = request.headers.get("x-mug-visit")
        session_handle = None if visit is None else browser_session_handle(visit)
        try:
            body = P2PIceGrantRequest.model_validate(await request.json())
        except ValueError as error:
            raise HTTPException(status_code=400, detail="invalid request") from error
        try:
            credentials = await coordinator.redeem_ice(
                session_handle, body.ice_grant_handle
            )
        except (IceGrantError, P2PEdgeError) as refusal:
            raise HTTPException(
                status_code=403, detail=refusal.safe_message
            ) from refusal
        return JSONResponse(
            credentials.as_json(), headers={"Cache-Control": "no-store"}
        )


def _seated_games(study: Study, gateway: Gateway) -> dict[str, AgentGameSpec]:
    """Compile the seat list each game activity wrote into the game it runs.

    A study that wrote no seats compiles nothing, and every mount runs exactly as
    it did before a seat list could be written. The identifiers a seat carries are
    derived through the gateway, so two processes over one ledger compile the same
    seats and a replay names what the run named.
    """
    compiled: dict[str, AgentGameSpec] = {}
    for activity_key, seats in study.seats.items():
        if activity_key in study.game_activities:
            # The activity named its own environment, so its seating is compiled where
            # the mount is resolved (``mug.mounts``) and there is nothing to do here.
            continue
        game = study.games.get(activity_key)
        if not isinstance(game, MultiSeatGame):
            raise ValueError(
                f"the activity {activity_key!r} names seats, so it must name the "
                "environment they sit in: Game(key, MultiSeatGame(...), seats={...})"
            )
        compiled[activity_key] = seat_game(
            game,
            cast("Seating", seats),
            activity_key=activity_key,
            derived_id=gateway.derived_id,
        )
    return compiled


def _written_chat(chat: Step) -> Conversation:
    """Return the conversation a mounted ``chat=`` names, refusing anything else.

    It takes the author's own ``Chat(...)`` and nothing else. It used to take the
    runtime's ``ChatSpec`` -- twenty fields, none of them a decision an author
    should be making -- which meant the one way to mount a conversation was to
    write the thing the platform compiles to.
    """
    talk = getattr(chat, "talk", None)
    if not isinstance(talk, Conversation):
        raise ValueError(
            "mount a conversation as the author's own: "
            'build_study_app(chat=Chat("talk", Model(agent))). It was given a '
            f"{type(chat).__name__}."
        )
    return talk


def _conversations(
    gateway: Gateway,
    store: Store,
    study: Study | None,
    study_version: StudyVersionRef | None,
) -> Conversations | None:
    """Return the conversations the study wrote on its activities, if it wrote any.

    A study that writes none gets none, and every game mount runs exactly as it did
    before a conversation could be written beside one.
    """
    if study is None or not study.chats:
        return None
    return Conversations(
        gateway,
        store,
        study,
        specs=chats_beside_games(study, derived_id=gateway.derived_id),
        study_version=study_version,
    )


def _add_realtime(
    app: FastAPI,
    gateway: Gateway,
    store: Store,
    study: Study | None,
    game: GameSpec | None,
    browser_game: BrowserGameSpec | None,
    mesh_game: MeshGameSpec | None,
    concurrent_mesh: bool,
    server_game: ServerGameSpec | None,
    browser_p2p: BrowserP2PConfig | None,
    agent_game: AgentGameSpec | None,
    seated: Mapping[str, AgentGameSpec],
    turnbased_game: TurnBasedGameSpec | None,
    chat: ChatSpec | None,
    resolved: Mapping[str, Mount],
    talks: Mapping[str, ChatSpec],
    generations: Mapping[str, RecordedGeneration],
    assets: Mapping[str, StagedAsset],
    deployment: DeploymentRevisionRef | None,
    study_version: StudyVersionRef | None,
    return_url: str | None,
    require_launch: bool,
    signing_key: bytes,
    admission: Admission,
    telemetry: Telemetry,
    node: Node | None,
    diagnostics: Diagnostics,
) -> None:
    """Run the realtime session loop for each websocket connection.

    With ``require_launch`` set, a fresh connection must present a valid launch
    ticket, which enrolls the participant and starts the visit; without it a fresh
    connection opens the flow for an anonymous per-connection subject. Either way
    the session serves ``flow.advance`` commands that step the flow forward. A
    server ``game`` runs over the stepping loop when the flow reaches the game
    activity; a ``browser_game`` ships the client manifest and captures the run
    the client reports; a ``mesh_game`` rendezvouses the connections at the game
    activity into a peer-to-peer mesh and runs one shared episode; a ``server_game``
    runs one server-authoritative multi-seat episode where the participant plays one
    seat and the study's bots play the rest; an ``agent_game`` runs a multi-seat
    model episode the participant watches or plays a seat in, captures it, and
    assembles its replay bundle; a ``chat`` runs a conversation between the
    participant and the study's model seat over the chat channel instead of a game.
    With none configured the game activity is skipped.
    """
    mesh_manifest = (
        browser_mesh_manifest(browser_p2p.game)
        if browser_p2p is not None and browser_p2p.game is not None
        else None
    )
    if game is not None:
        countdown_seconds = game.countdown_seconds
    elif browser_game is not None:
        countdown_seconds = browser_game.countdown_seconds
    elif mesh_manifest is not None:
        countdown_seconds = mesh_manifest["countdown_seconds"]
    else:
        countdown_seconds = 0
    resolve = _resolve_subject(gateway)
    dispatch = build_dispatch(gateway, store, browser_game)
    on_establish = build_establish(
        gateway,
        store,
        return_url,
        browser_game,
        countdown_seconds,
        require_launch,
        signing_key=signing_key,
        chat=chat is not None,
        mesh_manifest=mesh_manifest,
        study=study,
        deployment=deployment,
        study_version=study_version,
        assets=asset_manifest(assets),
    )
    on_open = build_open(gateway, store)
    # Reach this process's model seats once, when the first participant arrives and
    # long before they reach a game. What a warm-up buys is paid on the first call
    # somebody makes, and paid inside the round it is a partner frozen in a running
    # kitchen. Here it is paid while they are reading a consent form.
    warm = warming(
        gateway, store, _model_games(resolved, seated, agent_game), diagnostics
    )
    on_measure = build_measure(gateway, store)
    # A participant who leaves mid-round leaves a run nobody closed.
    on_close = build_close(gateway, store, browser_game)
    if chat is not None:
        # Every conversation is a room, including a room of one: that is what
        # commits the interaction, its channels, and who was in each of them.
        rendezvous = ChatMatchmaker(gateway, store, chat, study_version=study_version)
        on_game = build_chat_on_game(
            gateway, store, chat, rendezvous=rendezvous, diagnostics=diagnostics
        )
    elif agent_game is not None or turnbased_game is not None:
        # A watcher can read the assembled replay bundles off the app state.
        bundles: list[ReplayBundle] = []
        app.state.replay_bundles = bundles

        async def collect(bundle: ReplayBundle) -> None:
            bundles.append(bundle)

        if agent_game is not None:
            on_game = build_agent_on_game(
                gateway,
                store,
                agent_game,
                on_bundle=collect,
                conversations=_conversations(gateway, store, study, study_version),
                specs=seated,
                diagnostics=diagnostics,
            )
        else:
            assert turnbased_game is not None
            on_game = build_turnbased_on_game(
                gateway, store, turnbased_game, on_bundle=collect
            )
    elif mesh_game is not None:
        matchmaker: MeshRendezvous
        if node is not None:
            # The waiting room is shared, so the two participants a deployment put
            # on two processes are matched with each other rather than each waiting
            # alone. One process then hosts the mesh for both.
            matchmaker = NodeMeshMatchmaker(gateway, store, mesh_game, node)
        elif concurrent_mesh:
            matchmaker = PooledMeshMatchmaker(gateway, store, mesh_game)
        else:
            matchmaker = MeshMatchmaker(gateway, store, mesh_game)
        on_game = build_mesh_on_game(gateway, store, matchmaker)
    elif server_game is not None:
        on_game = build_server_on_game(gateway, store, server_game)
    elif browser_p2p is not None:
        coordinator = P2PCoordinator(gateway, store, browser_p2p, node=node)
        app.state.p2p_coordinator = coordinator
        _add_ice_endpoint(app, coordinator)
        on_game = build_browser_p2p_on_game(gateway, store, coordinator)
    else:
        # A study writes a conversation on the activity it happens in, so what a
        # composed activity is comes from the study rather than from a mount: the
        # same hook plays a game alone or plays and talks at once.
        on_game = build_on_game(
            gateway,
            store,
            game,
            conversations=_conversations(gateway, store, study, study_version),
        )
    # A study that named its own environments resolves one runtime per game activity,
    # so a practice round on the server and a real round with a model partner are two
    # runtimes in one study. What is mounted through a keyword stays the fallback, so a
    # study is ported when its author ports it.
    if resolved or talks:
        on_game = build_routed_on_game(
            _activity_hooks(
                app, gateway, store, resolved, talks, study, study_version, diagnostics
            ),
            on_game,
        )
    # A comparison activity owns the socket the way a game does, and a study puts
    # it after the rounds it asks about, so the router keeps both live and the
    # activity the session is at decides which one runs.
    on_game = build_activity_on_game(
        build_comparison_on_game(gateway, store, generations), on_game
    )

    @app.websocket("/ws")
    async def realtime(  # pyright: ignore[reportUnusedFunction]
        websocket: WebSocket,
    ) -> None:
        await serve_session(
            websocket,
            resolve_principal=resolve,
            dispatch=dispatch,
            protocol_version=_PROTOCOL_VERSION,
            on_establish=_also_warming(on_establish, warm),
            on_open=on_open,
            on_game=on_game,
            on_measure=on_measure,
            on_close=on_close,
            admission=admission,
            telemetry=telemetry,
        )


def _model_games(
    resolved: Mapping[str, Mount],
    seated: Mapping[str, AgentGameSpec],
    mounted: AgentGameSpec | None,
) -> list[AgentGameSpec]:
    """Return every game in this study that has a model seat in it, once each.

    A study may reach its games three ways -- an activity that named its own
    environment, a seating compiled onto an activity, or the older keyword -- and a
    warm-up wants each game once whichever way it arrived. A game with no model seat
    is not one of them: there is nothing to reach.
    """
    found: list[AgentGameSpec] = []
    seen: set[int] = set()
    for spec in (
        [mount.agent_game for mount in resolved.values()]
        + list(seated.values())
        + [mounted]
    ):
        if spec is None or not spec.seats or id(spec) in seen:
            continue
        seen.add(id(spec))
        found.append(spec)
    return found


def _also_warming(establish: Establish, warm: Callable[[Session], None]) -> Establish:
    """Wrap the establish hook so the first session starts the warm-up.

    It wraps rather than replaces, and it starts rather than waits: a participant
    must never be held at the door by a model, and a provider that cannot be reached
    must still let them walk the rest of the study.
    """

    async def establishing(session: Session) -> dict[str, Any]:
        answer = await establish(session)
        warm(session)
        return answer

    return establishing


def _activity_hooks(
    app: FastAPI,
    gateway: Gateway,
    store: Store,
    resolved: Mapping[str, Mount],
    talks: Mapping[str, ChatSpec],
    study: Study | None,
    study_version: StudyVersionRef | None,
    diagnostics: Diagnostics,
) -> dict[str, OnGame]:
    """Build one hook per resolved activity, keyed by the activity it runs.

    Each activity gets the runtime its own environment and seating resolved to, so a
    study is no longer one mount however many games it holds. The conversation a study
    wrote on an activity reaches the hook that plays it, because a game and the talk
    beside it are one interaction. A conversation that **is** the activity gets its own
    room, so one study may hold a game and a conversation -- which the nine mutually
    exclusive keywords could not express at all.

    A watcher can read the assembled replay bundles off the application state, the same
    as it could when one keyword chose the mount for the whole study.
    """
    bundles: list[ReplayBundle] = list(getattr(app.state, "replay_bundles", []))
    app.state.replay_bundles = bundles

    async def collect(bundle: ReplayBundle) -> None:
        bundles.append(bundle)

    conversations = _conversations(gateway, store, study, study_version)
    hooks: dict[str, OnGame] = {}
    for key, mount in resolved.items():
        if mount.agent_game is not None:
            hooks[key] = build_agent_on_game(
                gateway,
                store,
                mount.agent_game,
                on_bundle=collect,
                conversations=conversations,
                specs={key: mount.agent_game},
                diagnostics=diagnostics,
            )
        elif mount.turnbased_game is not None:
            hooks[key] = build_turnbased_on_game(
                gateway, store, mount.turnbased_game, on_bundle=collect
            )
        elif mount.server_game is not None:
            hooks[key] = build_server_on_game(gateway, store, mount.server_game)
        elif mount.game is not None:
            hooks[key] = build_on_game(
                gateway, store, mount.game, conversations=conversations
            )
    for key, spec in talks.items():
        # Every conversation is a room, including a room of one: that is what commits
        # the interaction, its channels, and who was in each of them.
        hooks[key] = build_chat_on_game(
            gateway,
            store,
            spec,
            rendezvous=ChatMatchmaker(
                gateway, store, spec, study_version=study_version
            ),
            diagnostics=diagnostics,
        )
    return hooks


def _refuse_unplayable_rounds(study: Study | None, **mounted: object) -> None:
    """Refuse a study that asks for rounds the mounted execution cannot play.

    Only the two server-stepped modes loop rounds. A browser-executed game is
    written by the client and captured once, and a peer-to-peer mesh runs one room
    to its end, so ``Game("play", episodes=5)`` on either would play **one** round
    and move on.

    That is the worst kind of fault: the author said what they wanted, the platform
    read it, and nothing in the records would say it had been dropped. So it is
    refused here, where the author is reading their own code, rather than a
    participant's run later. A study that wants five rounds of a browser game
    writes five game activities.
    """
    if study is None:
        return
    one_round_only = sorted(
        name for name, value in mounted.items() if value is not None
    )
    if not one_round_only:
        return
    asked = {
        key: rounds.count for key, rounds in study.rounds.items() if rounds.count > 1
    }
    if not asked:
        return
    named = ", ".join(f"{key} ({count} rounds)" for key, count in asked.items())
    raise ValueError(
        f"{' and '.join(one_round_only)} plays one round per activity, and {named} "
        "asks for more; write one game activity per round, or run the game on the "
        "server"
    )


def build_study_app(
    *,
    study: Study | None = None,
    store: Store | None = None,
    gateway: Gateway | None = None,
    game: GameSpec | None = None,
    browser_game: BrowserGameSpec | None = None,
    mesh_game: MeshGameSpec | None = None,
    concurrent_mesh: bool = False,
    server_game: ServerGameSpec | None = None,
    browser_p2p: BrowserP2PConfig | None = None,
    agent_game: AgentGameSpec | None = None,
    turnbased_game: TurnBasedGameSpec | None = None,
    chat: Step | None = None,
    generate: GenerationSet | None = None,
    return_url: str | None = None,
    require_launch: bool = False,
    signing_key: bytes | None = None,
    web_root: Path | None = None,
    admission: AdmissionPolicy | None = None,
    gateway_secret: bytes | None = None,
    node_id: str | None = None,
    bus: NodeBus | None = None,
    debug: bool = False,
) -> FastAPI:
    """Build one running application for a study: edge, web shell, and realtime.

    ``study`` is the ordered activities one participant walks through -- the
    author's own consent, surveys, game, and debrief (see ``mug.content.study``).
    With none, the demo study runs, which is what a local try wants and what the
    tests use.

    The parts are injected for a test, or defaulted for a real run. The default
    store is in-memory, so a plain run keeps no state between restarts. A study
    supplies one of ``game`` (the environment steps on the server), ``browser_game``
    (the environment steps in the browser through Pyodide and the client reports its
    run), ``mesh_game`` (the connections rendezvous at the game activity into a
    peer-to-peer mesh and run one shared episode), ``server_game`` (one
    server-authoritative multi-seat episode, the participant on one seat and the
    study's bots on the rest), or ``agent_game`` (a multi-seat
    model episode the participant watches or plays a seat in); a study entrypoint
    supplies one (for example ``examples/mountain_car/native_demo.py``). A study
    whose activity is a conversation rather than a game supplies ``chat`` instead:
    the participant talks to the study's model seat over the chat channel, and every
    message, delivery, and context snapshot is recorded as canonical evidence. With
    none the flow runs
    the forms and skips the game activity. ``return_url`` is the deployment return
    link the completed flow presents with the completion code.

    ``require_launch`` gates realtime entry on an opaque launch ticket (API-03): it
    provisions one genuine ticket at build time, exposes its handle as
    ``app.state.launch_ticket``, and refuses a connection that presents no valid
    ticket. A returning participant resumes through the stored return token, so the
    ticket is not required again. With the default unset, entry is open (the demo
    mode a local try or an all-agent run uses).

    ``signing_key`` signs the return token the handshake issues, so only a token
    the server minted resumes a visit. It defaults to a fresh per-process key, so
    the return links of one run do not verify against another. A deployment that
    must keep return links valid across a restart sets a stable key (see
    ``build_app_from_env``).

    ``concurrent_mesh`` mounts the formation pool for a ``mesh_game``: many rooms of
    that game form and run at once, rather than one mesh at a time. With it unset the
    single matchmaker runs one mesh at a time (the default).

    ``web_root`` selects the static client directory. It defaults to the bundled
    JavaScript client; a deployment or a test may point it at another built client
    (for example the TypeScript client under ``ts/dist-web``).

    ``admission`` bounds what one process accepts: how many sessions at once, how
    fast one connection may send commands, and how large a frame may be. It defaults
    to the working bounds in ``mug.admission``, so a deployment is bounded without
    saying anything; a deployment that knows its own numbers passes its own policy,
    and the live session count is on ``app.state.admission``.

    ``gateway_secret`` seeds the content-addressed command identifiers. It defaults
    to a fresh per-process secret, which is right for one process; a deployment that
    runs several passes the same secret to each, so a client retry is idempotent
    whichever process it lands on (see ``build_app_from_env`` and the deployment
    topology note).

    ``node_id`` names this process, and naming it is what makes a multi-participant
    activity work across processes: the waiting room moves into the shared store, so
    two participants the load balancer sent to two replicas are matched with each
    other. With it unset a process matches only its own connections, which is right
    for one process and is what a study running locally gets. ``bus`` is how the
    processes reach each other; it defaults to the shared store, and a deployment
    with a message broker passes its own.

    ``debug`` has the run write down what it is doing -- what each model seat was
    asked, what came back, how long it took, whether an action could be read out of
    it, and what the seat said -- and serves it at ``/_debug``, where the study's own
    screen shows it in a panel. It is **off** unless it is asked for, because those
    notes hold prompts and what a participant wrote: they belong to the person
    running the study and not to the person in it. ``MUG_DEBUG=1`` is the same switch
    for a study started through ``build_app_from_env``.
    """
    _refuse_unplayable_rounds(
        study,
        browser_game=browser_game,
        mesh_game=mesh_game,
        browser_p2p=browser_p2p,
    )
    gateway = gateway or Gateway(secret=gateway_secret)
    store = store or InMemoryStore()
    signing_key = signing_key or os.urandom(32)
    gate = Admission(admission)
    sink = InMemoryTelemetry()
    # What the run says about itself while it runs. It is off unless a process is
    # started in debug mode, because a note holds prompts, replies, and what a
    # participant said: the notes of a running study are not a participant's to read.
    watch: Diagnostics = RecordingDiagnostics() if debug else NullDiagnostics()
    node = _node(node_id, gateway, store, bus)
    app = build_app(
        store,
        gateway=gateway,
        authenticate=_pseudonymous_participant,
        telemetry=sink,
    )
    if node is not None:
        # The pump needs a running loop, which a builder does not have. It starts
        # with the application and stops with it, so a process that is never served
        # never polls.
        app.router.add_event_handler("startup", node.link.start)
        app.router.add_event_handler("shutdown", node.link.stop)
    published = _run_once(_publish(study or demo_study(), gateway, store))
    app.state.study = published
    app.state.study_version = published.study_version
    launch_ticket: str | None = None
    if require_launch:
        provision = _run_once(
            provision_launch_ticket(
                gateway,
                store,
                researcher=_DEMO_RESEARCHER,
                study_version=published.study_version if published.published else None,
            )
        )
        launch_ticket = provision.ticket_handle
        app.state.deployment = provision.deployment
        deployment = _run_once(
            _open_deployment(gateway, store, published, provision.deployment)
        )
        app.state.deployment_record = deployment
    running = study or demo_study()
    # What each game activity runs, resolved from the environment it named and who it
    # seated in it. A study that named none resolves nothing and every mount runs
    # exactly as it did before an environment could be named.
    resolved = mounts_for(running, derived_id=gateway.derived_id)
    # The conversations the study wrote as activities of their own. A conversation
    # beside a game stays on the game, because it happens there.
    talks = chats_for(running, derived_id=gateway.derived_id)
    seated = _seated_games(running, gateway)
    # A conversation mounted beside the study rather than written into it. It is the
    # author's own ``Chat(...)``, compiled here where the gateway is, because a model
    # speaker's pinned build and recorded actor are derived and never written.
    mounted_chat = (
        chat_for(_written_chat(chat), derived_id=gateway.derived_id)
        if chat is not None
        else None
    )
    if agent_game is None and seated:
        # A study that wrote its seats on an activity has said what the mount runs,
        # so nothing else has to be passed to say it again.
        agent_game = next(iter(seated.values()))
    staged_assets = _run_once(_stage_study_assets(running, gateway, store))
    app.state.assets = staged_assets
    generations: Mapping[str, RecordedGeneration] = (
        {}
        if generate is None
        else _run_once(_record_generations(generate, gateway, store))
    )
    app.state.generations = generations
    app.state.launch_ticket = launch_ticket
    app.state.admission = gate
    app.state.telemetry = sink
    app.state.diagnostics = watch
    _add_operations(app, gate, sink)
    _add_debug(app, watch, sink, gate)
    _add_operator_view(app, store)
    _add_web_shell(app, web_root or _WEB)
    _add_assets(app, store, staged_assets)
    _add_export(app, store)
    _add_realtime(
        app,
        gateway,
        store,
        study,
        game,
        browser_game,
        mesh_game,
        concurrent_mesh,
        server_game,
        browser_p2p,
        agent_game,
        seated,
        turnbased_game,
        mounted_chat,
        resolved,
        talks,
        generations,
        staged_assets,
        getattr(app.state, "deployment", None),
        published.study_version,
        return_url,
        require_launch,
        signing_key,
        gate,
        sink,
        node,
        watch,
    )
    return app


# The service principal that runs a study's candidate-generation job. It is derived,
# so the same deployment always records its generations under the same actor.
_GENERATION_JOB = "generation-job"

# The researcher principal a study publishes under. It is derived, so one deployment
# always publishes as the same actor.
_PUBLISHER = "study-publisher"

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"

_ENVELOPE_DIGEST = Digest(algorithm="sha-256", hex="0" * 64)
_RESEARCH = DataHandlingRef(privacy_labels=["research"])


def _run_once(work: Coroutine[Any, Any, _T]) -> _T:
    """Run one coroutine to completion from this synchronous builder.

    ``build_study_app`` is called both from a plain script and from inside a running
    event loop (an async test, an async entrypoint). ``asyncio.run`` refuses the
    second, so a loop that is already running is served by a fresh loop on a worker
    thread. The work is the same either way: it finishes before the builder returns.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(work)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, work).result()


def _generation_context(gateway: Gateway, aggregate_id: str) -> CommandContext:
    """Mint a fresh command context on one generation aggregate's stream.

    The generation job is server-side work with no participant behind it, so it acts
    as a derived service principal rather than as anyone. Each generation writes its
    own aggregate, so the runtime asks for a context per aggregate id.
    """
    return _server_context(
        gateway,
        aggregate_id,
        command="generation.record",
        principal=PrincipalRef(
            kind="service", id=gateway.derived_id("service", _GENERATION_JOB)
        ),
    )


def _server_context(
    gateway: Gateway,
    aggregate_id: str,
    *,
    command: str,
    principal: PrincipalRef,
    idempotency_key: str | None = None,
) -> CommandContext:
    """Mint one command context for server-side work with no participant behind it."""
    schema = {
        "name": "mug.command-envelope",
        "version": 0,
        "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
    }
    envelope = WireCommandEnvelope.model_validate(
        {
            "schema": schema,
            "protocol_version": _PROTOCOL_VERSION,
            "command": {"name": command, "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-000000000001",
            "idempotency_key": idempotency_key or _job_idempotency_key(gateway),
            "target": {"id": aggregate_id},
            "payload": {
                "schema": {
                    "name": "mug.edge.payload",
                    "version": 0,
                    "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
                },
                "data": {"aggregate_id": aggregate_id},
            },
        }
    )
    return gateway.mint(envelope, principal=principal, data_handling=_RESEARCH)


def _job_idempotency_key(gateway: Gateway) -> str:
    """Mint one well-formed idempotency key for a server-side generation command."""
    body = gateway.new_id("request").split("_", 1)[1].replace("-", "")
    return "idem_" + body[:21] + "A"


def derived_idempotency_key(gateway: Gateway, seed: str) -> str:
    """Return the one well-formed idempotency key this seed always gives.

    A command that must replay rather than collide -- publishing a study version that
    is already published -- derives its key, so the store coalesces the retry to the
    first receipt.
    """
    body = gateway.derived_id("request", seed).split("_", 1)[1].replace("-", "")
    return "idem_" + body[:21] + "A"


async def _publish(study: Study, gateway: Gateway, store: Store) -> PublishedStudy:
    """Compile the study and publish it, before the first participant connects.

    Publishing is idempotent by derivation, so a restart republishes to the same
    version and an edited study publishes a new one; a deployment that shares its
    store and its gateway secret publishes once however many processes it runs. A
    study whose validation found an error is **not** published, and the application
    still serves it: refusing to start would take a live study down over a
    compile-time complaint, so the failure surfaces as an unpublished version and the
    report on ``app.state.study`` rather than as an outage.
    """
    git, limitations = _git_provenance()
    return await compile_and_publish(
        study,
        store=store,
        artifacts=cast("ArtifactStore", store),
        derive=gateway.derived_id,
        new_context=lambda aggregate_id: _publication_context(gateway, aggregate_id),
        new_artifact_id=lambda seed: gateway.derived_id("artifact", seed),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=lambda: gateway.clock().astimezone(timezone.utc).strftime(_INSTANT),
        git=git,
        limitations=limitations,
    )


def _git_provenance() -> tuple[GitProvenance, list[str]]:
    """Return the source provenance of the published study, and what it cannot say.

    A build sets ``MUG_GIT_COMMIT`` and ``MUG_GIT_BRANCH``, and the provenance then
    names the commit the study was built from. With neither set the commit is
    unknown, and the record cannot say so: ``GitProvenance`` marks a dirty tree only
    with the patch that made it dirty, and there is no patch to name. So an unknown
    build records the zero commit -- which no real commit ever is -- and declares the
    limitation, which is what the provenance manifest's ``limitations`` field is for.
    A reader is told the provenance is missing rather than shown a clean one.
    """
    commit = os.environ.get("MUG_GIT_COMMIT", "")
    known = len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
    provenance = GitProvenance(
        commit=commit if known else "0" * 40,
        branch=os.environ.get("MUG_GIT_BRANCH") or None,
        dirty=False,
    )
    return provenance, [] if known else ["provenance.git.unknown"]


def _publication_context(gateway: Gateway, aggregate_id: str) -> CommandContext:
    """Mint the context that publishes one study version, as a researcher.

    The idempotency key derives from the version being published, so republishing an
    identical study **replays** the first publication instead of colliding with it.
    A fresh key would make every restart a rejected create against an aggregate that
    already exists, and the application would come up believing it had not published.
    """
    return _server_context(
        gateway,
        aggregate_id,
        command="study.publish",
        principal=PrincipalRef(
            kind="researcher", id=gateway.derived_id("researcher", _PUBLISHER)
        ),
        idempotency_key=derived_idempotency_key(gateway, f"publish:{aggregate_id}"),
    )


async def _open_deployment(
    gateway: Gateway,
    store: Store,
    published: PublishedStudy,
    revision: DeploymentRevisionRef,
) -> Deployment | None:
    """Record the deployment this process serves, at the revision it is serving.

    A deployment already recorded is left as it stands, so a restart never quietly
    starts a deployment an operator stopped: the disposition is durable and it
    outlives the process that set it.
    """
    _, deployment = await open_deployment(
        study_id=published.study_version.study_id,
        revision=revision,
        context=_server_context(
            gateway,
            revision.deployment_id,
            command="deployment.open",
            principal=PrincipalRef(
                kind="researcher", id=gateway.derived_id("researcher", _PUBLISHER)
            ),
            idempotency_key=derived_idempotency_key(
                gateway, f"deployment:{revision.deployment_revision_id}"
            ),
        ),
        store=store,
    )
    return deployment


async def _stage_study_assets(
    study: Study, gateway: Gateway, store: Store
) -> dict[str, StagedAsset]:
    """Read and store the study's declared pictures, before anyone connects.

    Staging is idempotent by content: the artifact address is the digest of the
    bytes, so a restart re-reads the files and reaches the same addresses, and a
    deployment that shares its object store stores each picture once however many
    processes it runs.
    """
    if not study.assets:
        return {}
    return await stage_assets(
        study.assets,
        root=Path(study.asset_root) if study.asset_root else Path.cwd(),
        artifacts=cast("ArtifactStore", store),
        new_artifact_id=lambda digest_hex: gateway.derived_id(
            "artifact", f"asset:{digest_hex}"
        ),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=lambda: gateway.clock().astimezone(timezone.utc).strftime(_INSTANT),
    )


async def _record_generations(
    generate: GenerationSet, gateway: Gateway, store: Store
) -> dict[str, RecordedGeneration]:
    """Record the study's candidate generations once, before anyone connects.

    A generation already in the store is returned as it stands, so a restart calls no
    provider and a deployment that shares its store calls each model once however many
    processes it runs. That is what lets an annotator answer with every provider
    offline (NS-02).
    """
    return await record_generations(
        generate,
        store=store,
        artifacts=cast("ArtifactStore", store),
        derive=gateway.derived_id,
        new_context=lambda aggregate_id: _generation_context(gateway, aggregate_id),
        new_id=gateway.new_id,
        now=gateway.clock,
    )


def store_from_env() -> Store:
    """Return the durable store when ``MUG_PG_DSN`` is set, else the in-memory one.

    A deployment sets ``MUG_PG_DSN`` and gets the Postgres backend, opened
    non-destructively so a restart resumes the stored visits. With the variable
    unset the in-memory store runs, which keeps no state between restarts.
    """
    dsn = os.environ.get("MUG_PG_DSN")
    if not dsn:
        return InMemoryStore()
    from mug.storage.pg_store import PgStore

    return asyncio.run(PgStore.open(dsn))


def _node(
    node_id: str | None, gateway: Gateway, store: Store, bus: NodeBus | None
) -> Node | None:
    """Build this process's identity on the bus, or None for a single process.

    A process with no name matches only the connections it holds, which is exactly
    what it did before and exactly right when there is only one. A process that is
    named joins the shared waiting room, and the bus it reaches the others through
    defaults to the store they already share, so a two-replica deployment needs no
    broker to work -- only to be fast.
    """
    if node_id is None:
        return None
    link = NodeLink(
        bus or StoreBus(store, new_id=gateway.new_id), node_id, new_id=gateway.new_id
    )
    return Node(
        node_id=node_id,
        link=link,
        rendezvous=DurableRendezvous(
            store,
            new_id=gateway.new_id,
            now=lambda: gateway.clock().astimezone(timezone.utc).strftime(_INSTANT),
        ),
    )


def node_id_from_env() -> str | None:
    """Return this process's name from ``MUG_NODE_ID``, or None.

    A deployment that runs more than one process gives each a distinct name -- the
    pod name serves -- so two participants on two replicas are matched with each
    other rather than each waiting alone. With the variable unset a process matches
    only the connections it holds, which is right for one process.
    """
    return os.environ.get("MUG_NODE_ID") or None


def debug_from_env() -> bool:
    """Return whether ``MUG_DEBUG`` asks this process to write down what it does.

    Anything but an off word turns it on, because somebody who wrote ``MUG_DEBUG=yes``
    meant yes. A deployment that serves participants leaves it unset: the notes hold
    prompts and what a participant wrote.
    """
    said = os.environ.get("MUG_DEBUG", "").strip().lower()
    return said not in ("", "0", "no", "off", "false")


def gateway_secret_from_env() -> bytes | None:
    """Return the gateway identifier secret from ``MUG_GATEWAY_SECRET``, or None.

    A deployment that runs more than one process sets this to one long random secret
    shared by all of them, so a client retry that lands on a second process derives
    the identical command identifiers and the store replays it. With the variable
    unset each process draws its own secret, which is correct for a single process
    and unsafe for several -- see the deployment topology note.
    """
    secret = os.environ.get("MUG_GATEWAY_SECRET")
    return secret.encode("utf-8") if secret else None


def signing_key_from_env() -> bytes | None:
    """Return the return-link signing key from ``MUG_RETURN_LINK_KEY``, or None.

    A deployment sets ``MUG_RETURN_LINK_KEY`` to a long random secret, so return
    links stay valid across a restart -- a returning participant resumes even
    after the server has restarted. With the variable unset a fresh per-process
    key is used, so a restart invalidates the outstanding return links.
    """
    secret = os.environ.get("MUG_RETURN_LINK_KEY")
    return secret.encode("utf-8") if secret else None


def build_demo_app(**config: Any) -> FastAPI:
    """Build the application over the demo study: consent, survey, game, debrief.

    It is a shortcut for a local try and for the tests, not the way a study is
    written. A real study writes its own activities and passes them as ``study``
    to ``build_study_app`` (or ``build_app_from_env``), so its own consent, its
    own surveys, and its own debrief sit around the game rather than a demo's.
    """
    return build_study_app(**config)


def build_app_from_env(
    *,
    study: Study | None = None,
    game: GameSpec | None = None,
    browser_game: BrowserGameSpec | None = None,
    mesh_game: MeshGameSpec | None = None,
    concurrent_mesh: bool = False,
    server_game: ServerGameSpec | None = None,
    browser_p2p: BrowserP2PConfig | None = None,
    agent_game: AgentGameSpec | None = None,
    turnbased_game: TurnBasedGameSpec | None = None,
    chat: Step | None = None,
    generate: GenerationSet | None = None,
    return_url: str | None = None,
    require_launch: bool = False,
    admission: AdmissionPolicy | None = None,
    debug: bool | None = None,
) -> FastAPI:
    """Build the application with the store resolved from the environment.

    A study entrypoint uses this, so the same study runs on the in-memory store
    for a quick try and on Postgres for a real deployment, with no code change --
    only ``MUG_PG_DSN``. ``study`` is the ordered activities the participant walks
    through; with none, the demo study runs. ``require_launch`` gates entry on a
    launch ticket, and ``MUG_RETURN_LINK_KEY`` keeps the return links valid across
    a restart.

    Four environment variables are what a deployment sets, and all four are what
    running more than one process needs: ``MUG_PG_DSN`` shares the ledger,
    ``MUG_RETURN_LINK_KEY`` makes a return link verify on any process,
    ``MUG_GATEWAY_SECRET`` makes a client retry idempotent on any process, and
    ``MUG_NODE_ID`` names this process, so two participants on two replicas meet.
    See
    ``docs/architecture/implementation/deployment-topology.md`` for what is safe to
    replicate and what is not.

    ``MUG_DEBUG=1`` has the run write down what it asked its models and what came
    back, and puts a panel on the study's own screen that reads it. It is off unless
    it is set. An entrypoint that passes ``debug`` says so itself and the environment
    is not read.
    """
    return build_study_app(
        study=study,
        store=store_from_env(),
        game=game,
        browser_game=browser_game,
        mesh_game=mesh_game,
        concurrent_mesh=concurrent_mesh,
        server_game=server_game,
        browser_p2p=browser_p2p,
        agent_game=agent_game,
        turnbased_game=turnbased_game,
        chat=chat,
        generate=generate,
        return_url=return_url,
        require_launch=require_launch,
        signing_key=signing_key_from_env(),
        admission=admission,
        gateway_secret=gateway_secret_from_env(),
        node_id=node_id_from_env(),
        debug=debug_from_env() if debug is None else debug,
    )


# The module-level application a server runs: ``uvicorn mug.app:app``. It always
# uses the in-memory store, so importing this module never opens a database; a
# deployment runs a study entrypoint that calls ``build_app_from_env`` instead.
app = build_demo_app()
