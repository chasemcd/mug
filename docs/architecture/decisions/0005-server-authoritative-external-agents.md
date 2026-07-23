# ADR 0005: Server-Authoritative External Agents and Async Scheduling

| Field | Value |
| --- | --- |
| Status | Accepted |
| Accepted | 2026-07-20 (ratification; server-authoritative external agents + async scheduling folded in API-12; per-family freeze separate) |
| Date | 2026-07-16 |
| Owners | Unassigned |
| Affects | API-05 through API-08, API-12 through API-16 |

## Context

Model-provider calls have variable multi-second latency, cost, nondeterministic
outputs, and possible external side effects. Calling them synchronously in a
game step blocks the environment, and independently calling them on P2P peers
causes divergence and duplicate effects.

## Decision

External agents execute asynchronously outside environment mutation locks. A
scheduler captures immutable inputs, submits work through an executor, and
accepts proposed effects only if their authority, interaction generation,
episode, source snapshot, deadline, and validity still match.

Initial live LLM-controlled game actions are server-authoritative. Browser and
P2P environments may later consume decisions from an authoritative remote-agent
bridge, but peers never independently make live provider calls for one actor.

For P2P games, the generation-fenced designated peer selected by API-07/API-12
is the sole publisher of an accepted bot action into the peer input stream. A
local scripted/ONNX controller may also execute on that peer. A provider- or
tool-backed controller remains server-scheduled: the server produces the
recorded `DecisionResult`, and the designated peer injects that already accepted
action. Publication authority is not permission to expose provider credentials
or run external side effects in a participant browser.

## Invariants

- Provider success does not imply decision acceptance.
- Workers never receive or mutate a live environment.
- Reset, ownership change, and episode transition fence outstanding requests.
- Late results remain provenance but produce no effects or memory commits.
- Provider fallback is explicit configuration and recorded exposure.
- Exact replay never invokes a provider.
- A P2P bot action has one fenced peer publisher per episode and authority
  generation; provider-backed inference remains server-authoritative.

## Alternatives considered

### Make `compute_action` perform a provider request

Rejected because it blocks real-time locks and has no cancellation or stale
result semantics.

### Let every P2P client call the provider

Rejected because responses, cost, tools, timing, and side effects diverge and
cannot be rolled back.

## Validation

NS-03, NS-05, and NS-07 use a deliberately slow provider while frames, input,
chat transport, and heartbeats continue. Late and cross-episode completions are
discarded without side effects.
