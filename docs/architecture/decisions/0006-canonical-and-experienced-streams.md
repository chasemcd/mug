# ADR 0006: Canonical and Participant-Experienced Streams

| Field | Value |
| --- | --- |
| Status | Accepted |
| Accepted | 2026-07-20 (ratification; canonical + participant-experienced streams folded in API-10/API-16; per-family freeze separate) |
| Date | 2026-07-16 |
| Owners | Unassigned |
| Affects | API-07 through API-10, API-16, API-18, API-19 |

## Context

In P2P games, chat streaming, rendering, reconnect, and client catch-up, the
final accepted state can differ from what a participant saw and when they saw
it. Both are scientifically relevant, but they answer different questions.

## Decision

MUG records distinct evidence when necessary:

- A canonical stream for finalized accepted environment transitions, messages,
  workflow decisions, and responses
- A participant-experienced stream for delivered/speculative render frames,
  streaming deltas, corrections, skipped updates, focus loss, and display
  acknowledgments

Cross-modal relationships use causation and explicit anchors such as environment
step, render frame, chat sequence, and monotonic timing. Server ingest order is
not mislabeled as participant experience.

Each authoritative stream has its own monotonic sequence. A coordinator may
also assign an interaction-wide acceptance sequence for operational correlation,
but it means only "order accepted by this coordinator." It is not physical event
order or participant-experienced order.

## Invariants

- Speculative P2P transitions are not canonical before the finalization barrier.
- P2P confirmation (complete authoritative actions from the frozen mesh) and
  verification (mesh-wide equal state hashes) are distinct. Missing or
  conflicting peer evidence never advances the verified high-water mark.
- Chat acceptance, publication, delivery, and display are separate facts.
- Missing experienced evidence does not invalidate canonical evidence but
  changes completeness claims.
- Replay and preference candidates declare which stream/perspective they use.

## Alternatives considered

### Keep only the final canonical trajectory

Rejected because human judgments may depend on latency, rollback, display, or
streaming behavior that the final trajectory omits.

### Treat client display logs as canonical truth

Rejected because clients and peers are untrusted and may disagree.

## Validation

NS-06 and NS-09 verify distinct but causally related canonical and experienced
streams, explicit completeness, peer reconciliation, and replay perspective.
