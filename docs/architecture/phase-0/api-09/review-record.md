# API-09 Review Record

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.3` |
| Review opened | 2026-07-17 |
| Accountable owner | Unassigned |
| Target accepted version | `1` |

## Deliverable status

| Deliverable | Status | Evidence |
| --- | --- | --- |
| Ownership, lifecycles, and boundary | Drafted | [Index](index.md) |
| Version-0 schemas | Drafted | `client.schema.json` |
| Golden fixtures and harness | Drafted | 25 fixtures, 28 tests |
| Scenario/parity trace | Partial | Obligations mapped; concrete walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions, reviews, and cross-API ports |

## Checklist

- [x] Server derives identity from authenticated launch, not client fields
- [x] Transport acknowledgment is distinct from a command receipt
- [x] Realtime commands carry an idempotency key
- [x] Upload tickets use opaque grants and hide storage identity
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [x] `0.2` schema/fixture re-draft encoding the folded decisions: typed
      `InputScheme` over the env's own action space (`pressed_keys` /
      `single_keystroke`, typed no-input fill, `input_delay`; `decides_every`
      structurally excluded), per-seat `SeatDelivery` (no broadcast of
      seat-scoped views), and the typed `window.mug` `BridgeMessage` surface
      (`mugGlobals` retired; bridge keys never trusted for identity, condition,
      or seat)
- [x] RP-6/RP-8 decisions recorded: typed client quality measurements feed
      server-authoritative monitoring, and trusted page JavaScript gains a typed
      `mug.gate` readiness operation
- [x] Fold RP-6/RP-8 into the 0.3 contract, exact wire schemas, semantic rules,
      and fixtures: typed `MonitoringMeasurement` client event (ping/latency
      `rtt` + tab focus/blur `hidden` samples) that pins API-06's
      server-authoritative `MonitoringPolicy`, and the typed `mug.gate` `GateOp`
      readiness op (block/unblock advance or join over an interaction/flow
      anchor). RP-8's state→env-args path and read-only participant handle stay
      out of scope (open sub-items below)
- [ ] Exact command payload/result/view schemas for every command and query
- [ ] Accountable owner and four reviewers assigned
- [ ] Reconnect, resume, and connection-lease handshake defined with API-06
- [ ] HTTP resource surface and pagination defined
- [ ] Upload finalize/verify handoff to API-11 defined
- [ ] NS-03 through NS-10 walkthroughs pass
- [ ] Dependent ADRs accepted; four sign-offs recorded; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A09-O01 | Reconnect and resume protocol | Handshake replays the accepted deployment and resumes from a durable cursor | ['API-06'] |
| A09-O02 | Upload grant scope and expiry | Short-lived opaque grant bound to one upload; finalize verifies digest via API-11 | ['API-11'] |
| A09-O03 | Client backpressure and rate limits | Per-connection command budget with transport-level backpressure | ['API-06'] |

## Settled runtime-parity input for revision 0.3

Both are now **folded into the 0.3 schema bundle** (see the folded table below).

- **RP-6 (folded):** API-09 carries typed ping/visibility measurements to
  API-06's server-authoritative `MonitoringPolicy`; the client does not decide
  exclusion. Encoded as `MonitoringMeasurement` (`rtt`/`hidden`
  `QualityMeasurement` samples) which pins the API-06 interaction bundle
  (`mug.api-06.interaction` v0, digest `538a17e3…`) as an inert foreign ref.
- **RP-8 (folded):** the typed `window.mug` bridge adds `mug.gate` so trusted
  page code can block/unblock advance or interaction join without polling hacks.
  Encoded as `GateOp` (owned by API-09; bundle name `mug.api-09.gate-op`).

The general state→env-args resolution path and a read-only participant handle
remain **explicit RP-8 open sub-items** — deliberately NOT schemed in 0.3, not
silently adopted. Only the readiness-gating op was adopted.

## Folded runtime-parity decisions in revision 0.3

| Decision | Settled input |
| --- | --- |
| RP-6 | API-09 supplies typed client MEASUREMENTS only; enforcement is server-side. `MonitoringMeasurement` carries per-seat `rtt` (ping/latency) and `hidden` (tab focus/blur) `QualityMeasurement` samples as `Duration`s, and pins API-06's server-authoritative `MonitoringPolicy` (`mug.api-06.interaction` v0, digest `538a17e390be96543227d1cdef37274dbf0e59d1c10c457f3c3f428be182dc02`, at `#/$defs/MonitoringPolicy`) as an inert foreign ref never recomputed against this bundle. The server evaluates the measurements against `max_rtt`/`max_hidden` and alone decides warn/exclude. |
| RP-8 | API-09 owns a typed `mug.gate` readiness op (`GateOp`, bundle `mug.api-09.gate-op`): a closed `block`/`unblock` `GateAction` over a `GateTarget` of `advance` vs `join`, anchored to an interaction/flow node (`GateAnchor`), formalizing the legacy startButton/advanceButton interval hacks. RP-8 adopts ONLY this readiness op; the state→env-args resolution path and the read-only participant handle were NOT adopted and remain open sub-items. |

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Client protocol and identity derivation |
| Runtime/distributed systems | Unassigned | Pending | — | Idempotency, reconnect, backpressure |
| Data/replay | Unassigned | Pending | — | Ack/receipt distinction, upload integrity |
| Security/privacy | Unassigned | Pending | — | Client disclosure, upload authority, abuse limits |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-09: handshake, realtime-command, transport-ack, upload-ticket schemas, ack-vs-receipt distinction, upload disclosure, idempotency, 9 fixtures, 13 tests |
| 2026-07-18 | `0.2 (docs)` | Folded user-surface-review decisions (docs only; schema bundle stays `0.1`): typed input scheme over the env's own action space, per-seat routing/delivery, ungated surface (ADR-0015) |
| 2026-07-19 | `0.2` | Re-drafted the schema bundle to the `0.2` docs: added `InputScheme` (typed input over the env's own action space — integer or numeric-vector action values only, `pressed_keys`/`single_keystroke`, typed `on_no_input` fill incl. `repeat_last`, optional `input_delay`, per-seat `seat_key`; `decides_every` structurally excluded per D10-3), `SeatDelivery` (every render-packet/message delivery addressed to exactly one seat; no broadcast field), and `BridgeMessage` (R-13 typed `window.mug` surface: `response.set/get`, `state.set/get`, `advance`; closed shape rejects identity fields; reserved identity/condition/seat keys rejected semantically; `mugGlobals` retired); handshake capability set advertises `mug.client.bridge.v1`; 19 fixtures (8 valid, 11 invalid), 22 tests; bundle digests restamped |
| 2026-07-20 | `0.3 input (docs)` | Recorded settled RP-6 typed monitoring measurements and RP-8 `mug.gate`; exact wire/schema/fixture fold remains pending |
| 2026-07-20 | `0.3` | Folded RP-6 and RP-8 into exact bytes: `MonitoringMeasurement` client event (per-seat `rtt`/`hidden` `QualityMeasurement` Duration samples) pinning API-06's server-authoritative `MonitoringPolicy` (`mug.api-06.interaction` `538a17e3…`) as an inert foreign ref, enforcement left to the server; and API-09-owned `mug.gate` `GateOp` (closed `block`/`unblock` action, `advance`/`join` target, interaction/flow `GateAnchor`) formalizing the startButton/advanceButton hacks, with `uniqueMeasurementMetric` and `gateAnchorTarget` semantic rules. RP-8 state→env-args path and read-only participant handle deliberately unscoped. Bundle digest `a687a135…`; 25 fixtures (11 valid, 14 invalid), 28 tests. |

## Folded decisions (2026-07-18/19)

Approved user-surface-review decisions applied to this family's docs
(schema/fixture re-draft landed at `0.2` on 2026-07-19):

| ID | Applied as |
| --- | --- |
| D10-1 | Input bindings map keys to the environment's actual action space (env `IntEnum` or raw `Discrete`/`MultiDiscrete`/`Box` values); no platform-invented action vocabulary |
| D10-2 | Both input modes first-class: `InputMode.PRESSED_KEYS` and `InputMode.SINGLE_KEYSTROKE`, with typed `on_no_input` fill |
| D10-3 | `input_delay` (human netcode pacing) lives on `Input`; agent decision cadence (`decides_every`) is a policy/agent property in API-12/13, not input config |
| D10-4 | Input routed per-seat: a participant controls only their bound seat/env agent id; per-seat delivery of render packets and messages (with D09-4) |
| D10-6 | Realtime honesty retained: local prediction for feel; transport ack is never a durable receipt; canonical vs experienced capture |
| F-3 | Illustrative Python uses typed constants (`InputMode.*`, `Key.*`, env enums), never magic strings |
| F-4 / ADR-0015 | Surface is ungated (self-hosted); no grant/authority layer above launch-derived identity |
| R-13 | Custom-page JS speaks only the typed `window.mug` bridge (`mug.response.*`, `mug.state.*`, `mug.advance`); `mugGlobals` retired; nothing the bridge sends is trusted for identity, condition, or seat |
