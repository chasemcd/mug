# API-05: Seats, Actor Instances, Capabilities, and Controller Bindings

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-19 |
| Consumers | API-06 (interaction assembly, matchmaking), API-07/API-08 (channel execution), API-12 (controller scheduling), API-10 (evidence), API-22 (`mug simulate` all-agent runs) |
| Depends on | [Shared kernel 0.1](../shared-kernel/index.md), [API-01 0.1](../api-01/index.md), proposed ADRs 0002, 0013 |
| Implementation phase | Phase 1 |
| Stability tiers | Application command/query, archival |

## Outcome

API-05 realizes the north-star separation of **seat** (an authored role),
**actor instance** (who or what fills it for one interaction), and **controller
binding** (how that actor exercises one capability in one channel) — D07-1.
This is what lets a single actor drive game actions with one controller and
chat with another (D07-5), and lets the same seat be a human or an AI partner
as a casting change, not a rewrite (D07-3).

```text
SEAT            authored role                      ("forager-1", "forager-2")
  ⟵ filled by
ACTOR           per-run casting                    human (enrollment)  XOR  agent@version
  ⟵ acts through
CONTROLLER      per-channel behavior               human input · scripted · RL policy · LLM
  ⟵ bound to
ENV AGENT ID    the environment's own name for the slot (explicit, recorded binding)
```

## Casting model

- **Casting is all-or-nothing** (R-16, 2026-07-19): with no `cast` declared,
  every seat is a human participant; once a `cast` is declared it must name
  every seat — a partial cast is a compile error (no implicit occupant next to
  explicit ones).
- A seat is filled by a **human XOR an agent@version** — never both (D07-2). A
  human `ActorInstance` references an enrollment; a software `ActorInstance`
  references an immutable agent version. Agents live in the study repo and are
  versioned with the study (`agent@version`; git-native, ADR-0013, D07-4).
- Casting is **swappable and treatment-driven** (D07-3): a `Scope.GROUP`
  treatment (API-04, D06-7) can decide per group whether a seat is human or
  agent, resolved when the group forms and recorded. The rule is written
  **inline in the cast slot** (R-15, 2026-07-19): `cast={"seat":
  Treatment(levels={"human": Actor.human(), "ai": Actor.agent(...)}, ...)}` —
  an `Actor` in the slot is fixed structure, a `Treatment` in the slot is the
  manipulation; group scope is inferred from casting a shared seat.
- **Every seat may be an agent** (D07-8): all-agent interactions are allowed —
  multi-agent simulations, baselines, pilot data — launched headless by
  `mug simulate` (researcher/scheduler path, API-22), not by a participant
  link. Agent-backfill of a seat that *was* human is **not** in v0.
- LLM/agent casting declares provider needs and a secret **key**, never a
  credential (D07-6); binding happens at deploy (API-02).

## Seat ↔ environment agent id binding

A seat is an authored role; the **env agent id** is the environment's internal
name for a controllable slot (Gym/PettingZoo agent id). The two are **never
conflated** (D09-7): at casting time each seat is **explicitly bound** to one
env agent id, and the binding is recorded with the interaction's evidence. The
environment keeps using agent ids internally; role, occupant, and env slot stay
separately queryable, which is what makes human↔AI swapping and per-seat
routing/rendering robust.

## Grouping and matchmaking

When human seats must be filled, grouping is author-declared and typed (D07-7,
F-3; generalized 2026-07-19, R-18), never opaque queue behavior:

```python
team = Group(
    size=4,                                  # N participants, not just pairs
    match=Match.latency(max_p2p_rtt=150),    # Match.FIFO default; custom Matchmaker allowed
    wait=Duration(seconds=90),
    on_timeout=OnTimeout.RELEASE,
)
game1 = activities.Interaction(key="round-1", group=team, ...)
game2 = activities.Interaction(key="round-2", group=team,   # same object ⇒ group
    on_missing_member=OnMissing.WAIT)                       # persists across activities
```

`size` defaults to the number of human seats. In v0 the only timeout policy is
`OnTimeout.RELEASE` (return the waiting participant, mark ungrouped) —
agent-backfill on timeout is deferred with D07-8. Strategy is typed:
`Match.FIFO` (arrival order), `Match.latency(max_estimated_rtt=, max_p2p_rtt=)`
(current MUG's two-stage behavior: cheap server-RTT pre-filter, then P2P probe
of the proposed match with rejection/re-pooling over ranked candidates), or a
custom `mug.Matchmaker` subclass in the study repo (`find_match(arriving,
waiting, size)` / `rank_candidates(...)` — today's ABC, core authoring per
D15-2, versioned via ADR-0013). **Group persistence is the shared object**:
placing the same `Group` on several interactions reunites the same
participants (durable group identity, recorded), with `OnMissing.WAIT` or
`OnMissing.REGROUP` declaring later-activity behavior; a `Scope.GROUP`
treatment is assigned per `Group` and rides with it across activities.
Matchmaking ticket/group state lives in API-06; API-05 owns the authored
`Group` declaration and the resulting seat castings.

## Ownership boundary

API-05 owns `SeatDefinition`, `ActorInstance`, `ControllerBinding`, the
seat↔env-agent-id binding record, and the authored `Group` declaration. It
composes API-01 seat/channel definitions, API-03 enrollment identity, and
API-13 agent versions by reference; it does not own interaction lifecycle or
matchmaking execution (API-06), channel execution (API-07/08), or scheduler
mechanics (API-12).

## Non-negotiable actor boundary

1. A `SeatDefinition` is an authored role that exists before any actor fills it.
   Single-participant studies declare no seats; the participant is the implicit
   actor (D07-1).
2. An `ActorInstance` is human or software: a human references an enrollment, a
   software actor references an immutable agent version; never both (D07-2).
3. Every cast seat carries an explicit, recorded binding to exactly one env
   agent id (D09-7); the binding is data, never inferred from naming.
4. A `ControllerBinding` maps one actor capability in one channel to one
   controller kind. Human input carries no controller reference; scripted/RL/LLM
   controllers must reference one (D07-5).
5. Capability and controller kind must be compatible (e.g. a scripted policy
   cannot drive a chat-message capability).
6. All-agent castings are valid interactions (D07-8); a human seat is never
   silently rebound to an agent in v0.

## Current executable evidence

- 11 valid examples and 10 one-defect invalid examples covering subject
  exclusivity, controller-reference rules, capability/controller compatibility,
  cast totality (R-16), inline treatment cast slots (R-15), the explicit
  seat↔env-agent-id binding record (D09-7), all-agent castings (D07-8), and
  `Group`/`Match`/`OnMissing` declarations (R-18).
- 26 API-05 tests. The focused architecture suite passes.

## Acceptance status

`Drafted`, not `Accepted`. See the [review record](review-record.md).
