# Phase 1 Demo Plan: The First Working Vertical

| Field | Value |
| --- | --- |
| Status | Accepted (owner-directed, 2026-07-21) |
| Purpose | Map the work from the records-only spine to the first working demo |
| Scope | Faithful Phase 1 -- a native realtime stack, no legacy bridge |
| Target | Functional-parity fixture 1: one human, one Gymnasium environment. Server execution in M0-M7; browser (Pyodide) execution in M8 |

This plan turns the frozen Phase 0 contracts and the records-only command spine
into the first demonstrable experiment. It follows the roadmap Phase 1 "minimal
parity subset" (`roadmap.md`, `phase-0/implementation-backlog.md` items 1-11).

## What is already built

The records-only work delivered most of the durability spine (roadmap Phase 2):
three storage backends (in-memory, sqlite, Postgres), versioned aggregates, the
canonical event ledger, the outbox record, idempotency and fencing, and artifacts.
Four families have real command handlers -- authoring, platform, identity, visits.
The gateway mints content-addressed identifiers, so a client retry is idempotent
end to end. The edge dispatches six commands over HTTP.

The gap to a demo is almost entirely the realtime and participant surface, not the
durability core.

## The demo, defined

One participant completes a full single-participant visit:

1. The participant enrols and launches into a visit.
2. The visit presents a consent form; the participant submits it.
3. The visit runs one Gymnasium environment (mountain car); the participant plays
   it with the keyboard, server-authoritative, until the episode ends.
4. The visit issues a completion code.
5. Every form response and environment transition is captured to the ledger.
6. The researcher exports the visit as JSONL with complete lineage.

Chat, model providers, preferences, tools, memory, replay bundles, multiplayer,
and peer-to-peer are all out of this slice (roadmap Phases 3A-4).

### Execution modes and where Pyodide lands

API-07 fixes three execution modes: `server`, `browser`, and `p2p`. They share
everything above the environment -- the same flow, the same realtime transport, the
same `SurfaceCommand` and `RenderPacket` protocol, and the same normalized
`GameTransition` contract. They differ only in where the environment steps and who
writes the transition.

M0-M7 build the `server` mode: the environment steps on the server, and the server
writes the ledger. This is the simpler path to prove the realtime and capture spine,
so the demo uses it first.

The `browser` mode -- the environment running in the participant browser through
Pyodide (WebAssembly Python) -- is M8. It is not a nice-to-have backend. In the legacy
system the single-player environments ran in Pyodide by default, and browser execution
is a core value of MUG: it removes per-participant server compute and scales to many
concurrent participants at low cost. Fixture 1 is defined against browser execution, so
M8 is what meets it literally; M0-M7 meet its shape (one human, one Gymnasium
environment, playable in the browser) under server execution. See M8 for the sequencing
recommendation.

## Milestones

Each milestone is independently runnable. The order front-loads the participant
surface, which reuses what is built, and defers the hard realtime loop.

- **M0 -- Composition root and app skeleton.** One native entrypoint (`mug/app.py`)
  wires the store, gateway, and edge, serves a static client shell, and answers a
  websocket handshake. Replaces the module-global pattern of the legacy server.
  Gate: the app boots, the browser loads the shell, the websocket returns an ack.
- **M1 -- Native realtime transport.** An asyncio websocket endpoint, a session per
  participant, a handshake that resolves the principal, message envelopes that reuse
  the typed `RealtimeCommand` and `TransportAck`, and reconnection from a durable
  cursor. Replaces Flask-SocketIO and eventlet.
- **M2 -- Participant flow and forms (first runnable vertical, no game).** Visit-plan
  materialisation and an activity pointer on top of the current start and advance
  commands; a consent form activity presented to the client and committed as a
  durable response. Gate: enrol, launch, see the form, submit, advance -- all on the
  new stack, the response in the ledger.
- **M3 -- Environment adapter and stepping loop.** A server-authoritative game
  session that builds a Gymnasium environment, runs an asyncio tick loop, holds
  pending actions, and emits the normalized transition contract; keyboard input
  mapped to actions; the render packet pushed to the client.
- **M4 -- Native browser renderer.** A canvas renderer behind a small `Renderer`
  seam, plain ES modules. Gate: mountain car is visibly playable in the browser
  through the new stack.
- **M5 -- Canonical capture.** Every accepted transition and episode boundary
  committed as canonical events into the ledger. For single-player the accepted
  stream is the experienced stream, so there is no rollback or decision evidence yet.
- **M6 -- Completion and export (the demo).** A completion activity with an
  idempotent completion claim and a return link, and a JSONL export of the visit's
  full lineage. Gate: the full single-participant slice runs and exports.
- **M7 -- Harden as Phase 1 acceptance.** Wire the Phase 1 parity fixtures as
  automated acceptance tests and meet the Phase 1 gate (`roadmap.md`): the fixtures
  pass, the transition contract is single-sourced, and private manifest data cannot
  reach a client.
- **M8 -- Browser (Pyodide) execution mode.** The environment runs in the participant
  browser through Pyodide, not the server stepping loop. This is the API-07 `browser`
  execution mode and the primary single-player path. It reuses the M1 transport, the M2
  flow, the M4 renderer, and the M3 transition contract unchanged: the environment draws
  the same `Surface`, only in the browser. The new work is five things. (1) Ship the
  environment source bundle and its package requirements to the client
  (`EnvFactory.mode="browser"`, `source_bundle`), split from the private server manifest
  so no private manifest data reaches the browser. (2) Bootstrap Pyodide and install the
  packages once, then reset, step, and render the environment in the browser, so input
  has no server round trip. (3) Make the client the fenced writer of the `GameTransition`
  ledger, so a superseded client cannot write after a newer one takes over. (4) Add the
  API-16 determinism the browser path needs -- python, numpy, and JavaScript RNG capture
  behind the `snapshot-restore` and `state-hash` environment hooks -- so a client episode
  is reproducible and the server can verify the client-reported state. (5) Keep the
  normalized transition contract identical to the server loop, so a captured episode is
  indistinguishable by mode downstream. Gate: functional-parity fixture 1 passes
  literally -- one human runs a browser Gymnasium environment, its transitions captured
  under client authority, in the same normalized transition contract as the server loop.

  **Sequencing.** M8 is numbered last but ranks high. Because browser execution is a core
  MUG capability, the recommendation is to run M8 as soon as the demo is real (right after
  M6), before or alongside M7 hardening, rather than at the very end. M0-M6 must land first
  only because M8 reuses the transport, flow, renderer, and capture they build; it does not
  depend on M7. The design homework is already done: the Phase 0 runtime-parity audit
  `runtime-parity/03-pyodide-env-lifecycle.md` maps the legacy Pyodide lifecycle onto
  API-07, API-09, and API-16.

## Rendering decision

The choice is two layers, kept separate.

The **protocol** -- `SurfaceCommand` and `RenderPacket` in `mug/game/types.py` -- stays
the backend-neutral contract. It is already a retained-mode, animated,
sprite-capable two-dimensional scene description: it carries persistent objects,
tween durations, depth layers, atlas frames, relative coordinates, and an `extras`
escape hatch. The environments are authored against it. The protocol stays
two-dimensional. A three-dimensional protocol would break the frozen API-07 contract
and force every environment to be re-authored for a capability nothing on the roadmap
needs. The legacy system has no three-dimensional rendering through this surface; the
footsies example is a separate self-rendering Unity integration, not this protocol.

The **backend** starts as a small canvas renderer behind a `Renderer` seam for the
demo, because mountain car needs only shapes. The production two-dimensional backend
is pixi.js, adopted when a sprite or tween environment (overcooked) arrives; pixi
gives a hardware-accelerated retained scene graph and atlas support without the
physics, input, and scene-manager weight of a full game framework, which the new
stack builds itself. The backend is not a Phaser port, which would draw legacy weight
back in, and not Three.js, which needs a three-dimensional protocol it does not have.

Rendering is the most swappable layer in the system, because it is a pure downstream
view of the authoritative transition ledger. The backend can change at any time
without touching the environments, the protocol, or any durable contract. The
`extras` field and operation-set versioning keep three dimensions possible later if it
becomes a real direction, under its own decision record.

## Legacy coexistence and isolation

The legacy runtime stays in place and runnable, as a behavior reference. The new work
is additive: it adds `mug/app.py` and new modules under the new-stack families, and it
changes no file under `mug/server`, `mug/scenes`, `mug/configurations`, `mug/rendering`,
or `mug/utils`.

The two systems run as separate entry points, which the roadmap allows during the
transition:

- The **legacy app** runs through `mug/server` and the examples, under the `[server]`
  optional extra (eventlet, flask, flask-socketio, gymnasium), for example
  `python -m examples.mountain_car.mountain_car_experiment`.
- The **new app** runs through `mug.app`, under the `[serve]` optional extra (uvicorn).

The boundary is enforced, not just documented. The import-linter "forbidden" contract
blocks every new-stack module, including `mug.app`, from importing any legacy module.
So the new stack can never depend on legacy code, and the legacy app keeps working for
cross-reference.

## Defaults and deferrals

Defaults: a plain ES-module client with no framework or bundler; inline study
compilation with no background worker yet (API-22 execution is Phase 6 scale work);
and pseudonymous participant identity through the existing edge `authenticate` seam.

Deferred out of this slice: the portable binary snapshot codec (peer-to-peer and
replay only); multiplayer, peer-to-peer, and matchmaking, so seats and interactions
stay minimal; and chat, model providers, preferences, tools, memory, and replay
bundles (Phases 3A-4).
