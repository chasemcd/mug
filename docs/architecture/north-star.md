# North-Star Architecture

| Field | Value |
| --- | --- |
| Status | Accepted (Phase 0 closed as-is, 2026-07-20) |
| Last updated | 2026-07-20 |
| Depends on | [Glossary](glossary.md), [ADR 0001](decisions/0001-functional-parity-not-backward-compatibility.md), [ADR 0014](decisions/0014-mug-scope-identity-not-recruitment.md), [ADR 0015](decisions/0015-governance-out-of-scope.md) |

## Product statement

MUG is a self-hosted, code-first platform for running durable, replayable
experiments among arbitrary combinations of humans, conventional policies,
and LLM agents. Actors interact through game, conversation, and annotation
channels with explicit scheduling, visibility, treatment, provenance, privacy,
and storage semantics.

MUG owns the experimental runtime, pseudonymous study-scoped enrollment, and
evidence record. Recruitment and participant contact remain in the
researcher's own tools; MUG accepts an opaque launch and, when supplied, keeps
an external-identity link apart from research data. Model, tool, storage, and
annotation systems integrate through MUG-owned contracts rather than being
recreated inside MUG.

## Required north-star capabilities

The platform must support all of the following as first-class configurations,
not experiment-specific JavaScript or socket-handler customizations:

| Capability | Required representation |
| --- | --- |
| Preference over trajectories | Preference candidates reference immutable canonical or participant-experienced trajectory slices. |
| Preference over LLM outputs | Candidates reference normalized model generations, published chat messages, or conversation segments. |
| One human chats with one LLM | Human and LLM actor instances share a chat channel with an explicit activation policy. |
| Multiple humans chat with one LLM | Channel membership, ordering, floor control, delivery evidence, and group context are explicit. |
| Multiple humans chat with multiple LLMs | Each LLM has independent role, visibility, routing, model, tools, memory, and activation rules. |
| Humans play games while chatting | A single interaction contains game and chat channels with causally linked, independently ordered evidence streams. |
| LLMs play games and optionally chat | An LLM actor may observe game and chat channels and emit validated actions, action plans, and messages on independent cadences. |

The replacement must also satisfy the [functional-parity contract](functional-parity.md)
for current MUG platform capabilities.

## Conceptual model

Identity, experimental role, and control are separate concepts:

```text
LaunchTicket ──┐
               ├──► Enrollment
ReturnLink ────┘
                        ├── ParticipantPrincipal
                        ├─ ─ ExternalIdentityLink (stored apart)
                        └──< Visit ──► VisitPlan ──< ActivityOccurrence
                                                               │
                                                               ▼
                                                        Interaction
                                                        ├── Seats
                                                        ├── ActorInstances
                                                        ├── ControllerBindings
                                                        ├── Channels
                                                        └── Causally linked evidence streams

AgentDefinition ──< AgentVersion ──► ActorInstance
```

- A participant principal is opaque, server-derived runtime identity; it is
  not a game player or external panel ID.
- An enrollment is the study-scoped pseudonymous unit of longitudinal analysis.
  The launch ticket reveals no identity, and a stable return link resolves the
  same enrollment for later parts or resumption.
- Any blinded external identity link is stored apart from research data. MUG
  provides no participant account or recruitment system.
- A seat is a role in an authored interaction.
- An actor instance fills a seat for one interaction.
- A controller binding says how that actor exercises a capability in a
  channel. The same actor can use an RL controller for game actions and an LLM
  controller for chat, or one LLM controller for both.
- An interaction is the shared coordination and evidence boundary.

This separation is required for replacement agents, role changes, team chat,
human takeover, multiple LLMs, and longitudinal identity without conflating
participant entry identity with environment agent IDs.

## System shape

```text
Researcher Python API
        │
        ▼
Study compiler and validator ──► immutable StudyVersion
        │                         ├── client manifest
        │                         ├── private server manifest
        │                         └── provenance manifest
        ▼
Visit-plan materializer and treatment service
        │
        ▼
Real-time interaction coordinator
  ├── game runtime: browser, P2P, or server authoritative
  ├── conversation runtime
  ├── actor/channel membership, write validity, and ordering
  └── client delivery and experienced-stream capture
        │
        ├────────► agent scheduler/executor
        │           ├── model providers
        │           ├── tools and optional MCP clients
        │           └── scoped memory
        │
        └────────► canonical event ingestor
                    ├── PostgreSQL metadata and current state
                    ├── content-addressed artifact storage
                    └── transaction outbox/workers
                              │
                ┌─────────────┼─────────────┐
                ▼             ▼             ▼
             Replay      Preferences      Exports
```

## Architectural layers

### Authoring and publication

Researchers author typed study, flow, activity, interaction, actor, channel,
treatment, capture, and preference specifications. A compiler validates the
entire protocol, resolves assets and code, checks provider and execution-mode
capabilities, and produces an immutable study version.

Compilation produces three deliberately different views:

- The client manifest contains only browser-visible, condition-safe
  configuration.
- The private server manifest contains prompts, tool policies, provider
  settings, and treatment-private data.
- The provenance manifest contains stable hashes, versions, and content that
  the capture policy explicitly permits retaining.

### Durable study control plane

The control plane owns studies, deployments, enrollments, launch and return-link
resolution, eligibility, visits, treatment assignment, materialized visit
plans, activity advancement, completion, and recovery. Longitudinal designs
are multi-part flows; consent, when needed, is an ordinary versioned flow
activity and response rather than a separate subsystem.

A visit plan is materialized and committed before a visit begins. Recovery
loads that plan; it never rebuilds and reshuffles authoring objects.

### Interaction runtime

The interaction runtime owns seats, actor instances, controller bindings,
channel membership, routing, ordering, matchmaking, connection leases,
participant input, and lifecycle transitions.

In server and browser-local execution, one runtime owns each environment
instance. In rollback P2P, each peer owns its local deterministic replica under
one accepted-input/finality protocol; reconciliation determines evidence status
after the finalization barrier. Browser and worker callbacks cannot bypass the
owning runtime to mutate an environment. Research-significant progression is
acknowledged only after its declared durable acceptance boundary.

### Agent runtime

Potentially slow or nondeterministic agents run outside the synchronous game
step. An asynchronous scheduler submits immutable requests and accepts results
only when their interaction, episode generation, source observation, deadline,
and validity window still match.

Agent outputs may contain game actions or action plans, chat messages, tool
interactions, and proposed memory updates. Each output type has an independent
cadence and effect-time validity check. Initial live external agents are
server-authoritative.

### Evidence and storage

MUG uses a hybrid evidence model:

- Relational records hold transactional current state and searchable metadata.
- An append-only event ledger records research-significant facts and their
  scientific history.
- Immutable artifact storage holds high-volume trajectories, render streams,
  snapshots, model and tool records, media, and export bundles.
- Ephemeral presence and leases may use Redis, but Redis is never authoritative
  research state.

Every event and artifact has stable occurrence identity, schema version,
lineage, integrity information, and privacy classification.

### Replay and preference collection

Replay supports declared capability levels:

1. Visual replay from render packets and keyframes
2. Deterministic replay from environment artifacts, state, and executed actions
3. Outcome replay from recorded model decisions and tool results

Preferences operate over generic immutable candidate references, including
trajectory slices, model outputs, chat messages, conversation segments, and
derived media. Assignment, presentation order, exposure, response, and quality
events are durable records.

## Non-negotiable invariants

1. Published study, agent, prompt, tool, and preference-protocol versions are
   immutable.
2. A visit uses a persisted materialized plan; restoration never reruns
   randomization implicitly.
3. Assignment and actual exposure are separate records.
4. Direct identity is separated from study-scoped research identity.
5. Secrets and private treatment information never enter client manifests,
   browser events, object keys, or ordinary logs.
6. The server derives participant and run context from verified launch or
   return-link state; it does not trust client-supplied identity or ownership
   fields.
7. Server/browser environments have one writer per instance. P2P has one writer
   per deterministic replica plus explicit input, finality, and evidence-
   reconciliation authority; it does not pretend there is one global mutable
   environment object.
8. Provider latency, tools, and storage I/O never block a real-time environment
   lock.
9. Stale, cancelled, replayed, or rejected agent decisions cannot mutate the
   environment or longitudinal memory.
10. Exact replay makes no provider calls and repeats no external tool side
    effects.
11. Canonical and participant-experienced streams are distinct when delivery,
    speculation, rollback, or streaming can differ.
12. Commands use explicit idempotency/retry policy. A possibly executed external
    effect becomes a durable indeterminate outcome and is never retried
    automatically; the platform does not claim an unprovable network
    “at-most-once” guarantee.
13. Activity advancement, response submission, committed chat messages, and
    completion receive a durable commit receipt only after aggregate state,
    idempotency record, canonical research event, and outbox commit in one
    relational transaction. High-rate ingress receipts declare weaker durability.
14. P2P evidence declares whether it is peer-reconciled, unverified, partial,
    or quarantined.
15. Recovery promises are capability-based. Exact mid-episode resume is offered
    only when the environment and every controller provide compatible snapshot
    contracts.

## Product boundaries

The initial platform does not attempt to become:

- A participant marketplace or payment processor
- A general-purpose survey builder
- An RL training framework
- A model gateway that replaces provider-specific systems
- A general agent orchestration product unrelated to experiments
- A warehouse or full statistical analysis platform
- A browser-side secret manager

Recruitment systems, model gateways, MCP servers, annotation platforms, and
analysis tools remain outside MUG. Recruitment tools hand participants an
opaque MUG launch URL and may receive a completion redirect; model, tool,
annotation, and analysis systems integrate through MUG-owned contracts.

## North-star acceptance story

Two participants enter a versioned study through opaque signed launch links.
They complete an ordinary content-and-form consent activity, are assigned
durable roles and treatment, play a multiplayer environment, and use public
and team chat. One LLM actor plays and chats as a partner; a second LLM is a
chat-only coach with different visibility, tools, memory, and activation rules.
After completing the first part, both participants later follow their stable
return links into the next part of the same multi-part flow. The server restarts
between parts without changing either participant's enrollment, materialized
plan, or treatment. Participants compare both trajectory segments and blinded
model messages. MUG exports normalized data and a verified replay bundle.
Replaying the interaction offline makes no model or external-tool calls.

Each visit pins both a scientific `StudyVersion` and an immutable
`DeploymentRevision`. For hosted models, the study pins the requested provider,
model selector, parameters, adapter, prompt, and fallback policy; provenance and
exposure record the provider-resolved model and response. MUG does not claim to
content-address or exactly pin a vendor's hidden serving backend.
