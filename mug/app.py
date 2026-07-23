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
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from mug.agents import AgentGameSpec, TurnBasedGameSpec
from mug.edge import build_app
from mug.export import export_visit
from mug.game.browser import BrowserGameSpec
from mug.game.mesh_session import MeshGameSpec
from mug.game.spec import GameSpec
from mug.gateway import Gateway
from mug.kernel import PrincipalRef
from mug.launch import provision_launch_ticket
from mug.participant import (
    MeshMatchmaker,
    build_agent_on_game,
    build_dispatch,
    build_establish,
    build_mesh_on_game,
    build_on_game,
    build_open,
    build_turnbased_on_game,
)
from mug.realtime import ResolvePrincipal, serve_session
from mug.replay import ReplayBundle
from mug.storage import InMemoryStore, Store

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


def _add_web_shell(app: FastAPI, web_root: Path) -> None:
    """Serve the static client shell and its assets from ``web_root``.

    The default root is the bundled JavaScript client. A deployment or a test may
    point ``web_root`` at another built client (for example the TypeScript client
    under ``ts/dist-web``); the directory must hold an ``index.html`` shell and the
    assets it loads under ``/static``.
    """
    app.mount("/static", StaticFiles(directory=web_root), name="static")

    @app.get("/")
    async def index() -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        return FileResponse(web_root / "index.html")


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


def _add_realtime(
    app: FastAPI,
    gateway: Gateway,
    store: Store,
    game: GameSpec | None,
    browser_game: BrowserGameSpec | None,
    mesh_game: MeshGameSpec | None,
    agent_game: AgentGameSpec | None,
    turnbased_game: TurnBasedGameSpec | None,
    return_url: str | None,
    require_launch: bool,
    signing_key: bytes,
) -> None:
    """Run the realtime session loop for each websocket connection.

    With ``require_launch`` set, a fresh connection must present a valid launch
    ticket, which enrolls the participant and starts the visit; without it a fresh
    connection opens the flow for an anonymous per-connection subject. Either way
    the session serves ``flow.advance`` commands that step the flow forward. A
    server ``game`` runs over the stepping loop when the flow reaches the game
    activity; a ``browser_game`` ships the client manifest and captures the run
    the client reports; a ``mesh_game`` rendezvouses the connections at the game
    activity into a peer-to-peer mesh and runs one shared episode; an ``agent_game``
    runs a multi-seat model episode the participant watches or plays a seat in,
    captures it, and assembles its replay bundle. With none configured the game
    activity is skipped.
    """
    if game is not None:
        countdown_seconds = game.countdown_seconds
    elif browser_game is not None:
        countdown_seconds = browser_game.countdown_seconds
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
    )
    on_open = build_open(store)
    if agent_game is not None or turnbased_game is not None:
        # A watcher can read the assembled replay bundles off the app state.
        bundles: list[ReplayBundle] = []
        app.state.replay_bundles = bundles

        async def collect(bundle: ReplayBundle) -> None:
            bundles.append(bundle)

        if agent_game is not None:
            on_game = build_agent_on_game(gateway, store, agent_game, on_bundle=collect)
        else:
            assert turnbased_game is not None
            on_game = build_turnbased_on_game(
                gateway, store, turnbased_game, on_bundle=collect
            )
    elif mesh_game is not None:
        matchmaker = MeshMatchmaker(gateway, store, mesh_game)
        on_game = build_mesh_on_game(gateway, store, matchmaker)
    else:
        on_game = build_on_game(gateway, store, game)

    @app.websocket("/ws")
    async def realtime(  # pyright: ignore[reportUnusedFunction]
        websocket: WebSocket,
    ) -> None:
        await serve_session(
            websocket,
            resolve_principal=resolve,
            dispatch=dispatch,
            protocol_version=_PROTOCOL_VERSION,
            on_establish=on_establish,
            on_open=on_open,
            on_game=on_game,
        )


def build_demo_app(
    *,
    store: Store | None = None,
    gateway: Gateway | None = None,
    game: GameSpec | None = None,
    browser_game: BrowserGameSpec | None = None,
    mesh_game: MeshGameSpec | None = None,
    agent_game: AgentGameSpec | None = None,
    turnbased_game: TurnBasedGameSpec | None = None,
    return_url: str | None = None,
    require_launch: bool = False,
    signing_key: bytes | None = None,
    web_root: Path | None = None,
) -> FastAPI:
    """Build one running application: the edge, the web shell, and realtime.

    The parts are injected for a test, or defaulted for a real run. The default
    store is in-memory, so a plain run keeps no state between restarts. A study
    supplies one of ``game`` (the environment steps on the server), ``browser_game``
    (the environment steps in the browser through Pyodide and the client reports its
    run), ``mesh_game`` (the connections rendezvous at the game activity into a
    peer-to-peer mesh and run one shared episode), or ``agent_game`` (a multi-seat
    model episode the participant watches or plays a seat in); a study entrypoint
    supplies one (for example ``examples/mountain_car/native_demo.py``). With none
    the flow runs
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

    ``web_root`` selects the static client directory. It defaults to the bundled
    JavaScript client; a deployment or a test may point it at another built client
    (for example the TypeScript client under ``ts/dist-web``).
    """
    gateway = gateway or Gateway()
    store = store or InMemoryStore()
    signing_key = signing_key or os.urandom(32)
    app = build_app(
        store,
        gateway=gateway,
        authenticate=_pseudonymous_participant,
    )
    launch_ticket: str | None = None
    if require_launch:
        provision = asyncio.run(
            provision_launch_ticket(gateway, store, researcher=_DEMO_RESEARCHER)
        )
        launch_ticket = provision.ticket_handle
    app.state.launch_ticket = launch_ticket
    _add_web_shell(app, web_root or _WEB)
    _add_export(app, store)
    _add_realtime(
        app,
        gateway,
        store,
        game,
        browser_game,
        mesh_game,
        agent_game,
        turnbased_game,
        return_url,
        require_launch,
        signing_key,
    )
    return app


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


def signing_key_from_env() -> bytes | None:
    """Return the return-link signing key from ``MUG_RETURN_LINK_KEY``, or None.

    A deployment sets ``MUG_RETURN_LINK_KEY`` to a long random secret, so return
    links stay valid across a restart -- a returning participant resumes even
    after the server has restarted. With the variable unset a fresh per-process
    key is used, so a restart invalidates the outstanding return links.
    """
    secret = os.environ.get("MUG_RETURN_LINK_KEY")
    return secret.encode("utf-8") if secret else None


def build_app_from_env(
    *,
    game: GameSpec | None = None,
    browser_game: BrowserGameSpec | None = None,
    mesh_game: MeshGameSpec | None = None,
    agent_game: AgentGameSpec | None = None,
    turnbased_game: TurnBasedGameSpec | None = None,
    return_url: str | None = None,
    require_launch: bool = False,
) -> FastAPI:
    """Build the application with the store resolved from the environment.

    A study entrypoint uses this, so the same demo runs on the in-memory store
    for a quick try and on Postgres for a real deployment, with no code change --
    only ``MUG_PG_DSN``. ``require_launch`` gates entry on a launch ticket, and
    ``MUG_RETURN_LINK_KEY`` keeps the return links valid across a restart.
    """
    return build_demo_app(
        store=store_from_env(),
        game=game,
        browser_game=browser_game,
        mesh_game=mesh_game,
        agent_game=agent_game,
        turnbased_game=turnbased_game,
        return_url=return_url,
        require_launch=require_launch,
        signing_key=signing_key_from_env(),
    )


# The module-level application a server runs: ``uvicorn mug.app:app``. It always
# uses the in-memory store, so importing this module never opens a database; a
# deployment runs a study entrypoint that calls ``build_app_from_env`` instead.
app = build_demo_app()
