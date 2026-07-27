# API-09: Participant Client, Realtime, Browser P2P, HTTP, and Uploads

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.4` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-23 |
| Consumers | Browser client, API-06 (channels and P2P membership), API-07 (execution/render packets), API-10/11 (evidence/uploads), API-02/03 (deployment/launch) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), [API-02 0.1](../api-02/index.md), [API-06 0.1](../api-06/index.md), proposed ADRs 0007, 0009 |
| Implementation phase | Phase 1 onward |
| Stability tiers | Wire (public), application command/query |

## Outcome

API-09 is the browser-facing wire contract: an opaque handshake, idempotent
realtime commands, transport acknowledgments distinct from command receipts, and
upload tickets that grant scoped write access without exposing storage identity.
The surface is ungated (self-hosted; ADR-0015): there is no authorization or
grant layer above the launch-derived identity.

Revision 0.4 also owns the authenticated browser P2P edge. It gives each browser
only scoped `PublicHandle` values, bounded opaque SDP/ICE payloads, an explicit
full-mesh validation barrier, and capture reconciliation records. The server
derives the principal, actor, membership, connection lease, source peer, and
capture authority. None of those trusted bindings enters a client-supplied
record.

The input scheme is **typed and authored** (D10-1/2/3): key bindings map to the
**environment's own action space** — an env-provided `IntEnum` for readability,
or raw `Discrete`/`MultiDiscrete`/`Box` values when the env defines none. The
platform never invents a parallel action vocabulary; the action a key produces
is exactly what the env's `step()` receives. Both input modes are first-class:
`InputMode.PRESSED_KEYS` (held keys drive every frame) and
`InputMode.SINGLE_KEYSTROKE` (one action per press), with a typed no-input fill.
`input_delay` (human-input netcode pacing) lives on `Input`; an agent's decision
cadence (`decides_every`) does not — it is a policy/agent property (API-12/13).

Delivery is **per-seat** (D10-4, D09-4): input is routed only to the
participant's bound seat/env agent id, and each seat receives its own
`RenderPacket` and message deliveries — a seat's private view is never sent to
another client.

## Ownership boundary

API-09 owns `ClientHandshake`, `RealtimeCommand`, `TransportAck`,
`UploadTicket`, the typed `Input` scheme (`InputScheme`: mode, bindings over the
env's own action space, no-input fill, `input_delay`, seat binding), the
per-seat delivery envelope (`SeatDelivery`), the typed `window.mug` bridge
message surface (`BridgeMessage`: `response.*`, `state.*`, `advance`), the typed
client `MonitoringMeasurement` event (RP-6), and the typed `mug.gate` `GateOp`
readiness op (RP-8).

API-09 also owns `P2PMeshBootstrap`, `P2PIceGrantRequest`, `P2PSignal`,
`P2PSignalDelivery`, `P2PSignalAck`, `P2PPeerReady`, `P2PMeshStart`,
`P2PMeshAbort`, `P2PPeerComplete`, `P2PCaptureSubmission`, and
`P2PMeshFinish`. `P2PPeer` and `P2PDataChannel` are nested exact records.
Channel semantics and the server-authoritative
`MonitoringPolicy` that evaluates measurements are API-06; render-packet content
is API-07; durable receipts and events are API-10/11; deployment endpoints are
API-02.

Client MONITORING is report-only (RP-6): `MonitoringMeasurement` carries per-seat
ping/latency (`rtt`) and tab focus/blur (`hidden`) samples and pins API-06's
server-authoritative `MonitoringPolicy`; the client never decides warn/exclude —
the server evaluates the measurements. Readiness GATING (RP-8) is a typed
`mug.gate` `GateOp`: trusted page JavaScript blocks/unblocks `advance` or `join`
over an interaction/flow anchor, replacing the legacy startButton/advanceButton
interval hacks. RP-8's state->env-args resolution path and read-only participant
handle are deliberately out of scope for revision 0.3 and remain open sub-items.

## Authoring surface (illustrative)

```python
from mug import Input, InputMode, Key
from .envs.foraging import ForagingAction        # the env's own action enum

controls = Input(
    mode=InputMode.PRESSED_KEYS,                 # continuous: held keys drive every frame
    bindings={
        Key.UP: ForagingAction.MOVE_UP,          # keys map to ACTUAL env action-space values
        Key.DOWN: ForagingAction.MOVE_DOWN,
        Key.SPACE: ForagingAction.GRAB,
    },
    on_no_input=ForagingAction.NOOP,             # the env's no-op (or NoInput.REPEAT_LAST)
    input_delay=2,                               # human-input netcode feel; NOT agent cadence
)
```

## Non-negotiable client boundary

1. The server derives identity from authenticated launch state, never from
   client-supplied identity or ownership fields.
2. A transport acknowledgment (parsed/queued/accepted) is not a command receipt;
   an accepted ack names a stream position.
3. Realtime commands carry an idempotency key for safe retry.
4. Upload tickets grant scoped writes via an opaque handle and never expose a
   bucket, storage URI, or signed URL to the browser.
5. Input bindings resolve to values in the environment's own action space; no
   platform-invented action names exist on the wire.
6. Input and delivery are per-seat: a participant's keys drive only their bound
   seat, and a seat's render packets and messages are delivered only to the
   client(s) entitled to that seat's view.
7. Custom-page JS speaks only the typed `window.mug` bridge (settled
   2026-07-19): `mug.response.*` submissions ride the same idempotent,
   receipt-bearing response command path as `Form` responses, and
   `mug.state.*` targets the visit's client-writable `StateDocument` namespace
   (API-04). There is no shared mutable global synced out-of-band
   (`mugGlobals` retired); nothing the bridge sends is trusted for identity,
   condition, or seat.
8. Browser P2P records carry only scoped `PublicHandle` values. Actor IDs,
   membership digests, lease claims/tokens, and secret values are forbidden.
9. A `P2PSignalAck` means only `queued` or `rejected`. It is not a command
   receipt and never claims a durable scientific effect.
10. `P2PSignalDelivery.source_peer_handle` is server-stamped. The inbound
    `P2PSignal` has no source, principal, actor, membership, or lease field.
11. Offer, answer, and candidate payloads are opaque bounded JSON strings.
    `end_of_candidates` omits `payload_json`; `null` is not an alternate wire
    spelling.
12. The fixed DataChannel has label `mug-mesh-data`, `ordered=false`, and
    `max_retransmits=0`.

## Browser P2P lifecycle and capture

The edge progresses through `formed → signalling → validating → running →
capture → finished`, or emits `P2PMeshAbort`. `negotiation_generation` fences
every frame in one attempt. The server validates the current authenticated
connection, lease, room, and frozen API-06 membership both when it accepts a
frame and when it routes or applies that frame.

Each bootstrap lists every remote peer and assigns the local browser exactly one
offerer/answerer role per pair. The client establishes all links and performs
bidirectional application-level validation. `P2PPeerReady` names the complete
validated remote-handle set. The server emits `P2PMeshStart` only after every
current member reports the same complete generation.

This first edge does not support mid-episode reconnect. A stale connection,
peer disconnect, negotiation timeout, or validation failure closes the attempt
with the authored `repool`, `resume_flow`, or `terminal` disposition. It never
silently shrinks the mesh.

At completion, every peer submits `P2PPeerComplete`. The designated capture
owner also sends `P2PCaptureSubmission`. The server recomputes
`payload_digest`, reconciles the trajectory digest and frame count across every
current peer, and emits `P2PMeshFinish` with an opaque public capture-receipt
handle. Conflicting or missing evidence aborts with an explicit capture reason;
the transport never invents a canonical winner.

## Transient ICE grant redemption

`P2PMeshBootstrap` carries an opaque, expiring `ice_grant_handle` and a
same-origin `ice_endpoint`. The authenticated client posts a typed
`P2PIceGrantRequest`. The response is transient WebRTC configuration and must
set `Cache-Control: no-store`. It is deliberately not a Pydantic contract
object and must never be persisted, logged, captured, replayed, or exported.
Long-lived TURN or provider credentials remain server-side API-02 `SecretRef`
bindings; the deployment secret never reaches the browser.

## Current executable evidence

- 23 valid and 29 one-defect invalid examples; 82 API-09 tests including
  upload-ticket disclosure, accepted-ack evidence, invented-action-name and
  `decides_every` rejection on `InputScheme`, broadcast rejection on
  `SeatDelivery`, identity/reserved-key rejection on `BridgeMessage`, the RP-6
  `MonitoringMeasurement` event (ping/visibility, API-06 `MonitoringPolicy` pin,
  bad-metric rejection), and the RP-8 `mug.gate` `GateOp` (block/unblock over
  advance/join anchors, bad-target and missing-anchor rejection), plus full
  P2P bootstrap/signaling/readiness/start/abort/capture/finish coverage,
  server-derived-source rejection, end-of-candidates omission, fixed
  DataChannel settings, and Python-model conformance.

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
