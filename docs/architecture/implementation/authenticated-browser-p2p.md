# Authenticated browser P2P vertical

| Field | Value |
| --- | --- |
| Status | Transport vertical implemented and mounted; browser game executor integration pending |
| Last updated | 2026-07-25 |
| Scope | Authentication, signalling, ICE access, mesh readiness, and capture reconciliation |
| Contract | [API-09 revision 0.4](../phase-0/api-09/index.md) |
| Style | This document uses ASD-STE100 Simplified Technical English |

This vertical builds the secure control path for a browser peer-to-peer room. It
does not complete browser P2P gameplay.

The vertical forms an authenticated room. It gives each browser opaque handles.
It relays bounded WebRTC signals. It waits for every pair to validate. It then
hands the open data channels to a consumer. It also reconciles the final capture
from every peer.

The later Pyodide rollback executor must consume the data-channel handoff. That
executor must load the environment, exchange frame inputs, run rollback, render
the game, and produce the final trajectory. Until that integration passes its
browser tests, MUG must not claim that the new browser P2P gameplay path is
complete.

## Scope boundary

This vertical owns the P2P control plane:

- the authenticated connection-to-peer binding;
- scoped room, peer, capture-owner, and ICE grant handles;
- offer, answer, candidate, and end-of-candidates relay;
- WebRTC data-channel setup and all-pair validation;
- the server start barrier;
- peer completion claims and capture-owner submission;
- final digest reconciliation or an explicit abort.

The later rollback executor owns the P2P game data plane:

- the accepted browser environment package and Pyodide lifecycle;
- input packets, redundancy, frame delay, and congestion behavior;
- deterministic stepping, rollback, and resimulation;
- state hashes, episode boundaries, and frame finality;
- render output and optional in-game chat behavior;
- the trajectory that the capture records summarize.

The existing rollback and wire cores can support that executor. They do not
remove the need for the browser integration. An open `DataChannelLink` is a
handoff, not proof that a game ran.

## Trust boundary

The server authenticates the WebSocket before it admits the connection to a
room. It binds the connection to the enrollment, visit, seat, actor, current
connection lease, and frozen API-06 mesh membership.

The browser receives only `PublicHandle` values. It does not receive or submit:

- a principal ID, enrollment ID, visit ID, seat ID, or actor ID;
- an API-06 membership digest or membership generation;
- a lease ID, namespace epoch, lease generation, or lease token;
- a deployment secret or long-lived TURN credential.

The server keeps a private map from each public handle to its trusted binding.
The browser cannot choose its source identity. `P2PSignal` has no source field.
The server adds `source_peer_handle` when it creates
`P2PSignalDelivery`.

A public handle is not authority by itself. The server accepts it only with the
authenticated connection and the current room binding.

## How the vertical is mounted

A study mounts the vertical with one configuration value:

```python
build_demo_app(browser_p2p=BrowserP2PConfig(
    channel_key="p2p-browser", size=2, verify_capture=my_verifier,
))
```

The mount needs a durable enrollment, so it needs the launch gate: a connection
with no enrollment is not admitted to the waiting room. The pieces are:

- `mug/participant_p2p.py` `P2PCoordinator` owns matchmaking, room lifetime, ICE
  grant scope, capture persistence, and re-pooling. It parses no frame.
- `mug/participant_p2p_edge.py` is the wire boundary, and only that: it turns one
  decoded browser frame into a coordinator call, and one room effect into the
  API-09 frame the browser reads.
- `mug/participant.py` `build_browser_p2p_on_game` owns the socket for the game
  activity, and `mug/app.py` mounts it on `/ws` beside the other game modes.
- `_add_ice_endpoint` serves the `no-store` redemption at the configured
  same-origin path.

A terminal effect reaches every socket before the members' flows continue, and a
member that has already gone away is skipped rather than written to. Both matter:
a terminal effect is usually produced inside a member's own reader task, and that
task ends as soon as its room does.

## Socket ownership

One connection task owns the WebSocket reader. One serialized writer owns all
WebSocket writes. No game, chat, signalling, or capture component calls
`receive_text`, `receive_json`, `send_text`, or `send_json` on that socket.

The reader parses the closed frame union and routes typed values to bounded
queues. The writer serializes typed outbound records in order. A component
returns an outbound effect to the writer; it does not write to the socket.

This rule lets signalling, game input, and chat share one connection. It also
prevents concurrent reads and interleaved writes. The server must not hold a
room, matchmaking, or interaction lock while it waits for a socket write.

The WebRTC data channels are separate after handoff. The single-reader and
single-writer rule applies to the server WebSocket control path.

## Exact API-09 sequence

The following sequence is the only successful control sequence. Signalling
frames can repeat within step 3.

| Step | Direction | Record | Required effect |
| --- | --- | --- | --- |
| 0 | Browser ↔ server | Authenticated session setup | Bind the connection to its current actor, membership, and lease. |
| 1 | Server → browser | `P2PMeshBootstrap` | Give the browser its room handle, local handle, remote handles and roles, capture owner, data-channel constants, validation timeout, and ICE grant. |
| 2 | Browser → HTTPS edge | `P2PIceGrantRequest` | Redeem the one-use ICE capability. Return only transient `no-store` WebRTC configuration. |
| 3a | Browser → server | `P2PSignal` | Check authority and bounds. Queue or reject the opaque signal. |
| 3b | Server → browser | `P2PSignalAck` | Report `queued` or `rejected`. This frame is not a durable receipt. |
| 3c | Server → target browser | `P2PSignalDelivery` | Stamp the source handle and deliver the signal to the bound target. |
| 4 | Browser → server | `P2PPeerReady` | Name every remote handle whose channel passed bidirectional application validation. |
| 5 | Server → all browsers | `P2PMeshStart` | Release one start barrier after every current peer reports the complete mesh. |
| 6 | Server → executor | Data-channel handoff | Give all open pair links and the start values to the later rollback executor. |
| 7 | Every browser → server | `P2PPeerComplete` | Report the final trajectory digest and frame count for each replica. |
| 8 | Capture owner → server | `P2PCaptureSubmission` | Submit the bounded trajectory payload and its exact UTF-8 payload digest. |
| 9 | Server → all browsers | `P2PMeshFinish` | Confirm one reconciled result after persistence returns an opaque capture receipt. |

`P2PSignal.signal_kind` is `offer`, `answer`, `candidate`, or
`end_of_candidates`. Offer, answer, and candidate frames contain bounded
`payload_json`. An end-of-candidates frame omits that field. `null` is not an
alternate spelling.

`P2PMeshAbort` can replace any later step. An abort is not a successful episode
or a `GAME_ENDED` event.

## Authority and effect-time checks

Parsing a valid frame does not authorize an effect. The room checks authority
when it relays a signal, accepts readiness, accepts a completion claim, or
accepts a capture.

For each effect, the server checks:

1. The room is open for that operation.
2. The supplied `negotiation_generation` equals the current room generation.
3. The authenticated connection maps to one room peer.
4. The peer actor belongs to the frozen API-06 membership.
5. The lease binds the same interaction and actor.
6. The lease namespace epoch and generation are current.
7. The lease has not expired.
8. The target handle belongs to the room and is not the source.

The server repeats the current-binding check before it routes, starts, or
persists an effect. A queued frame does not keep authority after its lease or
generation becomes stale. A stale or unknown binding fails closed with a safe
error.

A finish or abort fences the room leases. A late frame cannot reopen the room.

## Bounded signalling and mesh validation

API-09 permits 2 through 16 peers in one mesh. Each browser bootstrap contains
1 through 15 remote peers. The server assigns one offerer and one answerer for
each pair. Peers open all required pairs concurrently.

The first vertical uses these upper bounds:

| Resource | Bound |
| --- | --- |
| Offer or answer payload | 65,536 characters and no more than 65,536 UTF-8 bytes at runtime |
| Candidate payload | 4,096 characters |
| Signals from one peer in one room | 256 |
| Signals from one peer in one rolling window | 32 per second |
| Pending relay messages for one directed pair | 64 |
| Initial validation deadline | 15 seconds |
| Capture payload | 1,048,576 UTF-8 bytes |

An implementation can use a lower deployment limit. It cannot exceed the
contract limit.

The signal adapter buffers remote ICE candidates until it sets the remote
description. It also relays an explicit end-of-candidates marker. The fixed
data channel has:

```text
label = "mug-mesh-data"
ordered = false
max_retransmits = 0
```

An open channel is not sufficient. Each pair must pass application-level
validation in both directions. For a room with `N` peers, each readiness report
must name exactly `N - 1` remote handles. The server starts only after all `N`
reports match the current generation.

## ICE capability and secret boundary

The deployment stores the long-lived TURN value behind an API-02 `SecretRef`.
The browser never receives that reference or value. Runtime code resolves it
only inside the server process.

The server issues one ICE grant for one room and one peer. The grant has an
opaque handle, a short expiry, and one allowed redemption. The authenticated
peer posts `P2PIceGrantRequest` to the same-origin endpoint. The server rejects:

- an unknown grant;
- an expired or already redeemed grant;
- a grant for a different room;
- a grant for a different peer.

The direct response can contain STUN URLs and a short-lived TURN username and
credential. It is transient WebRTC configuration. The response must set
`Cache-Control: no-store`. MUG does not put this response in a Pydantic contract
model. It also does not put it in an event, artifact, log, replay, or export.

The server derives the short-lived TURN credential only during redemption. The
grant registry stores no TURN credential.

## Start, capture, and finality

The server chooses one capture owner deterministically from the frozen actor
set. It exposes only that actor's public peer handle.

Every peer submits one `P2PPeerComplete` claim. All claims must contain the same
trajectory digest and frame count. The capture owner also submits one
`P2PCaptureSubmission`. The server:

1. checks that the sender is the capture owner;
2. checks the payload and frame-count bounds;
3. parses the payload as JSON;
4. recomputes SHA-256 over the exact UTF-8 `payload_json` bytes;
5. compares the recomputed value with `payload_digest`;
6. compares the trajectory digest and frame count with every peer claim;
7. persists the accepted payload through the imperative shell;
8. emits `P2PMeshFinish` only after persistence returns a public receipt handle.

A repeated identical claim is safe. A changed claim or a conflicting peer
claim aborts the room. The server never selects a winner from conflicting
replicas.

## Abort and recovery

This vertical does not support mid-episode reconnect. A bound peer disconnect
aborts the whole room. The server does not shrink the mesh.

`P2PMeshAbort.reason` uses this closed vocabulary:

```text
peer_disconnected     negotiation_timeout
validation_failed     stale_connection
room_replaced         capture_timeout
capture_conflict      server_unavailable
```

The disposition is `repool`, `resume_flow`, or `terminal`. A negotiation
failure normally re-pools eligible participants. A scientific conflict is
terminal for that room. The caller applies the authored flow policy.

The room emits at most one start, finish, or abort effect. Abort and finish
fence all connection leases for that room.

## Process restart behavior

The signalling room, relay queues, readiness reports, and ICE grant registry
are volatile process state. This vertical does not restore them after a process
restart.

A restart closes the WebSocket and WebRTC control path. The new process rejects
the old room, peer, and ICE grant handles. It does not infer readiness,
completion, or a winner from partial memory.

The participant can return through the durable visit flow when that flow allows
it. The server must form a new room with new public handles, current leases, and
a new negotiation generation. It must not append new evidence to the old room
generation. A capture that did not reach a durable receipt and
`P2PMeshFinish` remains incomplete.

Durable restoration of an in-progress P2P episode is a later feature. It
requires a compatible executor snapshot and an explicit recovery contract.

## Tests and acceptance gates

The current vertical has executable evidence at these boundaries:

- `tests/architecture/test_api09_contract_fixtures.py` checks schema fixtures,
  semantic rules, bundle binding, and Python-model conformance.
- `tests/unit/client/test_client_conformance.py` binds the client models to the
  frozen API-09 bytes.
- `tests/unit/game/test_signalling.py` checks pair isolation, source stamping,
  bounds, offer/answer flow, early ICE, explicit end-of-candidates, timeouts,
  closure, and a three-peer all-pair mesh.
- `tests/unit/game/test_p2p_datachannel.py` checks the bounded data-channel
  adapter and fail-closed decoding.
- `tests/unit/game/test_signalling_mesh.py` completes the negotiated path: a fake
  RTC pair opens real `DataChannelLink` links through the relay, real peer nodes
  play one episode over them to byte-identical trajectories, and the relay
  carries no game packet.
- `tests/unit/game/test_p2p_room.py` checks the room core: effect-time authority,
  stale generation, fenced and expired leases, signal bounds and idempotency, the
  readiness barrier, capture reconciliation, and single-abort termination.
- `tests/unit/game/test_p2p_room_pool.py` checks formation, placement, and the
  deterministic offer roles.
- `tests/unit/client/test_ice_grants.py` checks room and peer scope, one-use
  redemption, expiry, and that no representation carries the TURN secret.
- `tests/unit/app/test_browser_p2p_coordinator.py` checks the live coordinator:
  formation, relay, start, reconciled finish, disconnect, replacement fencing,
  the negotiation deadline, and ICE scope.
- `tests/unit/app/test_browser_p2p_flow.py` drives the mounted vertical over the
  application websocket: two launch-gated browsers form a room, signal, start,
  reconcile, and finish, and the ICE endpoint answers once with `no-store`.
- `tests/conformance/test_ts_p2p_conformance.py` runs the TypeScript edge's own
  scenarios, so the browser half fails the maintained gate when it breaks.

The transport vertical is acceptable only while the following gates pass:

1. Python and TypeScript accept and reject the same API-09 fixtures.
2. No client frame can supply its source actor, membership, lease, or secret.
3. A stale lease or generation cannot route a signal or produce an effect.
4. One connection has one WebSocket reader and one serialized writer.
5. A three-peer room opens and validates all three pair links.
6. One missing or failed pair prevents `P2PMeshStart`.
7. An ICE grant is room-scoped, peer-scoped, expiring, and one-use.
8. Logs, errors, events, artifacts, replays, and exports contain no ICE
   credential.
9. All peer claims and the persisted owner capture must agree before finish.
10. Disconnect and process-restart tests produce an explicit abort or a new
    room. They never continue an old generation.

Browser P2P gameplay has one additional gate: the Pyodide rollback executor
must consume the channel handoff and complete a deterministic multi-browser
episode, including TURN fallback. Until that gate passes, this page describes a
complete transport vertical and an incomplete browser gameplay vertical.
