# API-12: Automated Controllers, Scheduling, and Execution

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.3` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-20 |
| Consumers | API-05 (software actors), API-07/08 (game/chat), API-13 (providers), API-14 (tools), API-10 (evidence) |
| Depends on | [Shared kernel 0.2](../shared-kernel/index.md), [API-06 0.3](../api-06/index.md), [API-07 0.3](../api-07/index.md), proposed ADRs 0005, 0010 |
| Implementation phase | Phase 3B |
| Stability tiers | Application command/query, archival |

## Outcome

API-12 admits potentially slow, nondeterministic controllers into a synchronous
environment without blocking it. An asynchronous scheduler submits immutable
decision requests and accepts a result only while its interaction, episode
generation, source observation, deadline, and validity window still match; stale
or cancelled decisions cannot mutate anything.

The north-star guarantee (D11-2): **a slow or failed provider/tool decision
never blocks a game frame, human input, or heartbeat.** Stale decisions are
discarded, never applied (D11-3), and timeout/staleness always resolves through
an explicit, typed fallback — `Fallback.REPEAT_LAST`, a declared default
action, etc. Declaring a fallback is **mandatory for any realtime seat**: a
seat in a running game frame must always resolve to an action, so there is no
implicit "wait for the model" path.

Decision cadence is an agent property, not an input property (D10-3, D11-4):
`decides_every` (frame-skip — how often an AI controller selects an action)
lives on the policy/agent definition scheduled here, never on the human `Input`
configuration (API-09).

```python
from mug import LLMAgent, Provider, Fallback

partner = LLMAgent(
    provider=Provider.OPENAI,          # typed provider (API-13)
    model="gpt-5",
    prompt="You are a cooperative foraging partner…",
    decides_every=4,                   # agent decision cadence: a policy property
    on_timeout=Fallback.REPEAT_LAST,   # mandatory for realtime seats
)
```

## P2P bot-action authority (RP-3)

`P2PBotAuthority` assigns exactly one peer to publish and inject a bot seat's
accepted actions into a P2P game. The eligible peer actor IDs are unique and
canonical, and the selected authority is the lexicographically highest eligible
actor ID. The assignment binds the API-06 mesh record's canonical digest and
membership generation, the interaction/channel, bot actor, episode identity and
generation, and a shared-kernel `LeaseRef` fence.

This is publication authority, not permission to make arbitrary external calls.
ADR-0005 remains authoritative: provider/tool-backed inference runs through the
server scheduler, then the designated peer injects its accepted result. A local
scripted or ONNX policy may compute on that peer. `DecisionResult.decision_origin`
records which path produced the decision without changing who is the sole mesh
publisher.

The authority is fixed for the episode (`authority_scope = "episode"` and
`mid_episode_failover = false`). A peer cannot self-elect or fail over after a
disconnect. Any future assignment starts under a new episode generation and a
new, strictly higher authority-fence generation; active authority ranges never
overlap.

P2P `DecisionRequest` and `DecisionResult` records carry the same
`P2PAuthorityClaim`: the canonical assignment digest, mesh digest/generation,
bot and authority actors, episode generation, target frame, and authority
fence. A produced result also carries the authority's `ProducerPosition` and
`replay_behavior = "apply-recorded-action"`. Acceptance is unique by decision
ID and by `(bot actor, episode generation, target frame, authority fence)`;
same-position/same-digest delivery is idempotent and conflicting evidence is
rejected. Rollback reapplies the recorded action bytes selected by
`action_digest`; it never asks any controller to decide again.

## Ownership boundary

API-12 owns `DecisionRequest`, `DecisionResult`, `P2PBotAuthority`,
`SchedulerState`, `FallbackPolicy`, and the decision-cadence (`decides_every`)
semantics of scheduled controllers. Provider calls are API-13; tool calls are API-14;
game/chat application is API-07/08; memory is API-15; human input timing
(`input_delay`) is API-09.

## Non-negotiable scheduler boundary

1. Slow provider/tool work never blocks a game frame, human input, or heartbeat.
2. A decision is accepted only if its episode generation, observation, deadline,
   and validity window still match; late decisions cannot cross episode boundaries.
3. A produced decision names an action digest; a stale produced decision is
   discarded, never applied.
4. Timeout and staleness resolve through an explicit, typed fallback policy
   (e.g. `Fallback.REPEAT_LAST`); a fallback declaration is mandatory for any
   realtime seat.
5. Decision cadence (`decides_every`) is declared on the policy/agent
   definition, never on human input configuration.
6. One deterministically selected, episode-scoped authority publishes each P2P
   bot seat. It is fenced to one mesh generation, cannot fail over unilaterally,
   and rollback replays its accepted recorded action rather than re-deciding
   (RP-3).
7. P2P publication authority does not move provider/tool execution to a browser:
   external decisions remain server-scheduled under ADR-0005.

## Current executable evidence

- 9 valid and 14 one-defect invalid examples; 28 API-12 tests including
  produced-decision evidence, stale-decision rejection, retired
  `noop`/`apply-if-valid` fallback branches, and the mandatory
  realtime-seat fallback declaration on the scheduled controller policy, plus
  four-peer authority selection, mesh/fence/request/result binding, missing or
  stale authority rejection, and recorded-action replay enforcement.

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
