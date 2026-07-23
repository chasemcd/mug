# Target API Catalog

| Field | Value |
| --- | --- |
| Status | Proposed |
| Note | Inventory is complete in scope; individual contracts are not yet frozen |
| Last updated | 2026-07-20 |
| Governing standard | [API design standard](api-design-standard.md) |

## Purpose

This catalog is the Phase 0 queue for all target-platform APIs. Its purpose is
to prevent teams from independently inventing incompatible concepts while
building storage, games, chat, LLM agents, replay, or preferences.

Every family below receives a dedicated specification, JSON fixtures, contract
tests, and the four required reviews before implementation. Names and method
shapes in this document are candidates; semantics are more important than the
particular Python spelling.

No compatibility with the existing API is required. All retained platform
capabilities must nevertheless map to at least one family below.

The author-facing surface over these families — the public Python authoring
API (`Study`, flow algebra, activities, treatment, seats/casting, rendering,
agents, forms/preferences, export) — is specified separately in
[the public Python authoring API](python-authoring-api.md). Per the
cross-cutting no-magic-strings rule (F-3), every closed vocabulary MUG defines
is exposed as a typed constant or enum (for example `ExecutionMode.SERVER`,
`Assign.balanced()`, `Dataset.TRAJECTORIES`), never a bare literal;
author-defined identifiers (study keys, condition labels, form-field names)
remain plain strings.

## API layers

| Layer | Audience | Stability expectation |
| --- | --- | --- |
| Authoring API | Researchers writing studies | Public, documented, validated at compile time |
| Extension SPI | Post-v0 (retracted for v0; closed vocabularies stay closed, core authoring is plain Python) | Post-v0: typed `ExtensionPoint` protocols, no plugin framework |
| Application API | MUG runtime and worker components | Explicit ownership, transactions, and errors |
| Wire API | Browser, admin client, external webhook, upload client | Language-neutral versioned schemas and capability negotiation |
| Evidence API | Researchers, replay, preferences, exporters, archives | Durable, schema-versioned, readable for the life of the researcher-owned store |

## Shared kernel

All APIs depend on a small language-neutral contract package.

### Identifier families

```text
StudyId                 StudyVersionId          DeploymentId
DeploymentRevisionId    ParticipantPrincipalId  ServicePrincipalId
SystemPrincipalId       ResearcherPrincipalId   EnrollmentId
VisitId                 VisitPlanId             ActivityDefinitionId
ActivityOccurrenceId    SeatDefinitionId        ActorInstanceId
ControllerBindingId     InteractionId           ChannelDefinitionId
ChannelInstanceId       LeaseId                 LeaseNamespaceEpochId
ProducerEpochId         ClockEpochId            CorrelationId
EpisodeId               MessageId               StreamId
EventId                 ArtifactId              UploadId
AgentDefinitionId       AgentVersionId          AgentRunId
PromptTemplateDefinitionId PromptTemplateVersionId DecisionId
ModelInvocationId       ModelGenerationId       ToolDefinitionId
ToolVersionId           ToolCallId              MemorySnapshotId
PreferenceProtocolDefinitionId PreferenceProtocolVersionId PreferenceQueryId
PreferenceAssignmentId  PreferenceResponseId    SecretBindingId
JobId                   CommandId               RequestId
ReceiptId               ErrorId
```

Account, auth-session, wave, and retention-policy identifier families were
retired by ADR-0014 (identity, not recruitment) and ADR-0015 (governance out
of scope). The hand-typed study version string is an author-chosen handle, not
an opaque ID; it is unique and immutable within a study.

IDs are opaque and typed. Runtime occurrence IDs are distinct from definition,
version, display, environment-agent, and content-digest identifiers. The
[registered-kind table](shared-kernel/identifiers-and-resource-hierarchy.md#registered-kinds)
is normative; the conformance suite verifies that its prefixes and the schema
registry remain identical.

### Shared values

```python
ArtifactRef
SchemaRef
SecretRef
Digest
ResourceRef
PrincipalRef
PublicHandle
StudyVersionRef
DeploymentRevisionRef
WireCommandEnvelope
CommandContext
TypedObject
IngressReceipt
CommitReceipt
ArtifactCommitReceipt
VersionStamp
EventCursor
StreamPosition
LeaseToken
LeaseRef
CapabilitySet
PrivacyClassification
DataHandlingRef
GitProvenance
DomainError
TraceContext
```

The first concrete [shared-kernel review](shared-kernel/index.md) now proposes
the ID format, canonical JSON, timestamps/numbers, schema language/evolution,
wire/trusted command split, receipt and error shapes, idempotency/concurrency,
ordering/fencing, privacy/secrets, and golden fixtures. Binary replay codecs
and the runtime Python/TypeScript generation libraries remain open decisions.

## Catalog summary

| ID | API family | Contract phase | First implementation |
| --- | --- | --- | --- |
| API-01 | Study authoring, compiler, manifests, and publication | 0 | 1 |
| API-02 | Platform composition and deployment | 0 | 1–2 |
| API-03 | Identity, enrollment, launch tickets, and return links | 0 | 2 and 5 |
| API-04 | Visit plans, flow, treatment, exposure, and state | 0 | 2 |
| API-05 | Seats, actor instances, capabilities, and controller bindings | 0 | 1 |
| API-06 | Interactions, channels, membership, matchmaking, and leases | 0 | 1–2 |
| API-07 | Environment, game, input, rendering, and execution modes | 0 | 1 |
| API-08 | Conversation, routing, history, streaming, and delivery | 0 | 3D |
| API-09 | Participant client, realtime commands, HTTP, and uploads | 0 | 1 onward |
| API-10 | Events, capture, provenance, metrics, and projections | 0 | 1 |
| API-11 | Storage, artifacts, repositories, transactions, and outbox | 0 | 1–2 |
| API-12 | Automated controllers, scheduling, and execution | 0 | 3B |
| API-13 | Model providers, content, usage, and errors | 0 | 3B |
| API-14 | Tools, authorization, approval, and environment commands | 0 | 4 |
| API-15 | Experimental agent memory | 0 | 4 |
| API-16 | Replay capture, bundles, validation, reading, and branching | 0 | 3A |
| API-17 | Content, forms, presentation, and accessible UI components | 0 | 1 onward |
| API-18 | Preferences, annotation, quality, and adjudication | 0 | 3C |
| API-19 | Dataset query, export, lineage, and external annotation | 0 | 1 onward |
| API-20 | REMOVED — governance out of scope (tombstone retained) | — | — |
| API-21 | RETRACTED for v0 — no plugin framework (tombstone retained) | — | Post-v0 |
| API-22 | Durable background jobs and workers | 0 | 1 onward; durable scaling in 6 |

## Contract ownership rule

Every type and protocol has exactly one owning API family. Other families may
compose or reference it but may not redefine its semantics. The first detailed
API review must complete the ownership map; these cross-cutting assignments are
already proposed:

| Contract | Owning family | Referenced by |
| --- | --- | --- |
| IDs, schema refs, command context, receipts, errors, privacy refs | Shared kernel | All APIs |
| `StudySpec`, `FlowSpec`, `GitProvenance`, compiler, manifests, `StudyVersion` | API-01 | All authored domains |
| `DeploymentSpec`, `DeploymentRequirements`, `DeploymentRevision`, secret storage/reference | API-02 (with shared kernel) | API-01, API-03, API-09, API-13 |
| `Enrollment`, `LaunchTicket`, `ExternalIdentityLink`, return links | API-03 | API-01, API-04 |
| Treatment, assignment, exposure, visit plan, activity occurrence | API-04 | API-01, API-06, API-18 |
| Seat, actor instance, controller base, controller binding | API-05 | API-06 through API-08, API-12 |
| Interaction, generic channel membership, matchmaking, leases | API-06 | API-07 through API-09 |
| Environment, game channel, action, rendering, execution mode | API-07 | API-12, API-16 |
| Chat content, message, visible history, delivery | API-08 | API-12, API-16, API-18 |
| Client protocol envelope and transport commands | API-09 | Domain services |
| Event envelope, event store semantics, capture policy, immutable event capture | API-10 | API-11, API-16 through API-19 |
| Artifact store, repositories, unit of work, outbox | API-11 | All durable domains |
| Agent/prompt version, automated controller, scheduler, decision context | API-12 | API-13 through API-16, API-18 |
| Model request/response/invocation/provider SPI | API-13 | API-12, API-18 |
| Tool definition/execution/authority | API-14 | API-12, API-15, API-16 |
| Experimental memory retrieval and commit | API-15 | API-12 |
| Replay manifest/bundle/reader | API-16 | API-18, API-19 |
| Content/form/presentation artifacts and components | API-17 | API-01, API-18 |
| Preference protocol/query/assignment/response | API-18 | API-19 |
| Dataset snapshot/export/lineage (JSONL) | API-19 | Researcher-owned analysis tooling |
| Job lifecycle, worker lease, progress, cancellation | API-22 | API-11 through API-19 |

The former API-20 (governance) and API-21 (plugin) ownership rows are retired:
API-20 is removed (F-4, ADR-0015) with immutable event capture re-homed to
API-10 and minimal secret storage to API-02/shared kernel, and API-21 is
retracted for v0 with no extension SPI rows to own.

## API-01 — Study authoring, compiler, manifests, and publication

**Authoring types**

```python
StudySpec
FlowSpec
ActivityNodeSpec
CompilationPolicy
GitProvenance            # commit SHA + stored patch bytes when the tree is dirty
CompiledStudyCandidate
StudyVersion             # immutable stored compiled artifact
ScientificManifest
ClientManifest
StudyServerManifest
ProvenanceManifest
```

**Primary operations**

```python
StudyValidator.check(spec, build_context) -> ValidationReport
StudyCompiler.compile(spec, git_provenance, build_context) -> CompiledStudyCandidate
StudyPublicationService.publish(command, command_context) -> CommitReceipt[StudyVersionPublished]
StudyCatalog.get_version(study_id, version_string) -> StudyVersion
StudyCompiler.diff(left_version, right_version) -> StudyVersionDiff
```

Versioning is git-native ([ADR-0013](../decisions/0013-git-native-study-versioning.md)).
Git owns study source: branches, diffs, pull requests, and collaboration happen
in the researcher's repository, and the platform implements no drafts, draft
revisions, or mutable definition registry. `publish` compiles a named git state
— the current commit plus a stored patch of any uncommitted changes — into an
immutable, fully resolved `StudyVersion` and **stores that compiled artifact**,
so reproducibility survives toolchain rot. Each version carries a hand-typed
**version string** (free-form, unique and immutable within the study, the
citable handle), a **resolved-content digest** (dedup identity), and
`GitProvenance` (commit + patch). Identical content republished under the same
string is idempotent; identical content under a new string and new content
under a reused string are both rejected. Compilation produces one complete
scientific root plus explicit client, private-server, and provenance
projections; it resolves every default, pins
source/environment/model/prompt/tool/asset requirements, and fails on silently
unserializable content. Definition-key identity is derived from published
history, not a stateful registry aggregate. `diff` compares **resolved**
versions, catching behavior changes with zero source diff; source diff is git's
job. Authors declare secret *requirements*, never values; binding happens at
deploy. Amendments are always new immutable versions; deprecate/withdraw
changes availability only and never deletes. Compilation uses API-22 for
durable work, and publication is atomic.

The concrete revision-0.2 contract, schemas, fixtures, decisions, and remaining
review blockers are in [API-01](api-01/index.md).

## API-02 — Platform composition and deployment

**Types and services**

```python
PlatformConfig
DeploymentSpec
Deployment
DeploymentRevision       # internal pinning record, not an operator surface
DeploymentRequirements
RuntimeServices
ApplicationFactory
DeploymentService.deploy(study_version, secrets, ...) -> DeploymentReceipt
DeploymentService.stop(deployment_id, ...) -> CommitReceipt
```

The operator surface is **two verbs**: `deploy` and `stop` (`mug deploy
study@version --at … --secret …`). "Stopped" means not live; `deploy` brings it
back; neither deletes data. Secrets are passed at deploy time (value or
environment reference); the platform stores them and everything else holds only
a reference — the value never enters science, artifacts, events, or the client.
Immutable `DeploymentRevision` records remain as internal pinning for history,
rollback, and in-flight visit pinning; a visit pins one revision. Requirement
satisfaction, secret isolation, and pinning are always-on invisible guarantees
that surface only as plain deploy errors. Deployment is ungated: MUG is
self-hosted, and whoever operates the installation can deploy and stop — there
is no grant system (F-4, ADR-0015). This API is also the composition root for
repositories, event/artifact stores, realtime transport, workers, and execution
backends. Scientific configuration may not leak into mutable deployment
settings; an operational change that can affect study semantics requires a new
study version as well as a new deployment revision.

**Process model (settled 2026-07-19, R-20):** one typical run path — `mug
deploy` runs **on the hosting machine** itself (laptop for dev, lab box/VM for
collection; identical commands), starting the local server process (web +
durable store + workers) if needed, recording the revision locally, and
serving. Study code reaches the host via git; `--at` declares the presented
public URL (participant links), not a remote target. There is no remote
deployment protocol, operator API, or artifact push, and MUG provisions no
machines, DNS, or TLS.

**Publish/deploy bundling (settled 2026-07-19, R-21):** `mug deploy
study@version` publishes implicitly when the string is unused (D02-3 collision
rules keep used strings immutable); bare `mug deploy study` is a
localhost-only working-tree **dev preview** with no version minted and
preview-marked data. `mug run` is retired; `mug simulate` auto-publishes the
same way; `mug export` never publishes.

**Open decisions:** dependency injection style, health/readiness contract,
client-build pinning, external secret-manager references (post-v0), and a
`deploy.toml` for repeatable deploys.

## API-03 — Identity, enrollment, launch tickets, and return links

**Types**

```python
Enrollment               # pseudonymous, study-scoped
LaunchTicket             # opaque; the deploy URL is the whole entry surface
ExternalIdentityLink     # blinded panel/provider ref, stored apart
ReturnLink               # stable per-participant re-entry link
```

**Services**

```python
LaunchService.exchange(launch_ticket, deployment_revision_id) -> LaunchSession
EnrollmentService.enroll_or_resolve(launch_ticket, study_id, ctx) -> Enrollment
ReturnLinkService.issue(enrollment_id, ctx) -> ReturnLink
ReturnLinkService.resolve(return_link) -> Enrollment
ExternalIdentityVault.record(external_ref, enrollment_id, ctx) -> ExternalIdentityLink
```

MUG owns identity, not recruitment
([ADR-0014](../decisions/0014-mug-scope-identity-not-recruitment.md)). It does
exactly three things at this boundary: assigns pseudonymous study-scoped
enrollments automatically, captures external references (for example a panel ID
in the launch URL) opaquely and stores them **apart** from research data, and
lets a participant return via a stable link. There are no accounts, magic
links, OIDC, WebAuthn, invitations, targeting, scheduling, or reminder
machinery — recruitment, re-contact logistics, and payment stay in the
researcher's existing tools. Consent is an ordinary flow activity (a
`Content`/`Form` step recorded like any response, versioned with the study),
not a `ConsentRecord` subsystem. Longitudinal designs are multi-part flows plus
the stable return link; there is no `WaveSpec`. Identity and condition are
server-derived; the browser receives only scoped pseudonymous references, and
the external identity link never becomes a research object key.

**Open decisions:** launch-ticket cryptographic format and replay defense,
completion redirect/code for panel round-trips, and cross-study linkage.

## API-04 — Visit plans, flow, treatment, exposure, and state

**Types**

```python
Visit
VisitPlan
ActivityOccurrence
PlanDecision
ActivityOutcome
TreatmentSpec
FactorSpec
ConditionSpec
AssignmentPolicySpec     # closed typed set: Assign.random/balanced/blocked/stratified
AssignmentScope          # typed: Scope.PARTICIPANT (default) | Scope.GROUP
TreatmentAssignment
TreatmentExposure
RandomnessRecord
StateDocument
CompletionClaim
```

**Services**

```python
VisitService.begin_or_resume(...) -> VisitBootstrap
VisitService.complete(...) -> CompletionReceipt
VisitPlanMaterializer.materialize(...) -> VisitPlan
VisitPlanService.advance(expected_occurrence, outcome, ctx) -> AdvanceReceipt
AssignmentService.assign_once(...) -> TreatmentAssignment
ExposureService.record(...) -> ExposureReceipt
StateDocumentService.read(...) -> StateDocument
StateDocumentService.compare_and_set(...) -> StateWriteReceipt
```

Assignment, initial plan, and visit start commit atomically. Known randomization,
repetition, parameters, and treatment are persisted before exposure. Dynamic
branches become durable `PlanDecision` records and are never recomputed during
recovery.

Authors declare the design; MUG samples, balances, and records — no hand-coded
`random.choice()`. Assignment policies are a closed typed set
(`Assign.random()`, `Assign.balanced()`, `Assign.blocked()`,
`Assign.stratified()`; within-subject order via `Order.*`) with no magic
strings (F-3) and no plugin allocator in v0. A treatment is declared **inline
at its point of effect** (settled 2026-07-19, R-15): a `Treatment` object sits
directly in the cast slot or spec field it manipulates
(`levels={label: value}`); multi-effect designs reuse the same object
(`t.map({...})` per site); joint factorial balance is an optional study-level
`Design(cross=[...])`, otherwise treatments assign independently. The full
design space is known at compile time and `check()` prints the effect map.
Assignment
scope is typed: `Scope.PARTICIPANT` (default) or `Scope.GROUP`, where a whole
session shares one condition assigned when the group forms (balancing unit is
the typed `unit=` knob, default `Unit.GROUPS`). Balancing operates
across the **study-version lifetime** through durable per-cell allocation
state that survives restarts — fixed behavior, not a knob. Assignment (intent)
and exposure (delivery) both reach the author's data.

**Open decisions:** branch materialization boundary, revision semantics,
mid-activity recovery, visit amendment, completion issuance/redemption, which
state namespaces may be client writable, and whether `Scope.GROUP` balance
cells count groups or participants when group sizes vary.

## API-05 — Seats, actor instances, capabilities, and controllers

**Design-time types**

```python
SeatSpec
CastingSpec              # fills a seat: human XOR agent@version, never both
GroupSpec                # grouping: N-size, Match strategy, wait, on_timeout, persistence identity
SeatAgentIdBinding       # explicit seat <-> environment agent-id binding
ActorTemplate
ControllerSpec
HumanControllerSpec
RandomControllerSpec
HeuristicControllerSpec
RLControllerSpec
LLMControllerSpec
CompositeControllerSpec
ControllerBindingRule
```

**Runtime types and SPI**

```python
ActorInstance
ControllerBinding
ControllerCapabilitySet
EffectiveAuthority
Intent
GameActionIntent
ChatMessageIntent
ReadyIntent

Controller.start(context) -> ControllerHandle
Controller.propose(request) -> ControllerDecision
Controller.snapshot() -> ControllerSnapshot
Controller.close(reason) -> None
```

`Intent` is limited to interaction effects such as game action, chat message,
and readiness. Preference submission is owned solely by API-18 and does not use
the generic interaction-intent path.

A controller proposes intents. It cannot directly change an environment,
conversation, preference response, or memory. Effective runtime authority is
the intersection of technical controller capability, channel `Membership`
access, current context/lifecycle state, treatment, and validation at
effect-application time.

The model is seat (authored role) ⟵ actor (human XOR software agent, never
both) ⟵ controller (how it acts per channel). Casting is swappable and may be
treatment-driven (human vs. AI partner via `Scope.GROUP`); the game is written
against roles, so a human↔AI swap is a casting change, not a rewrite. Agents
live in the study repo and are versioned with the study (`agent@version`,
riding git-native versioning); LLM/agent casting declares provider needs and a
secret key, never credentials. The seat↔environment-agent-id binding is
explicit (`SeatAgentIdBinding`): the environment keeps its own agent ids
internally, and role/actor/slot are cleanly separated. Grouping is an
author-declared, typed **shared `Group` object** (R-18, 2026-07-19): N-size,
`Match.FIFO` / `Match.latency` (two-stage RTT: server-RTT pre-filter, then P2P
probe with re-pooling over ranked candidates) / custom `Matchmaker` subclass
(core authoring), `wait`, `on_timeout=OnTimeout.RELEASE` in v0. Placing the
same `Group` on several interactions persists the group across them (durable
recorded identity, `OnMissing.WAIT/REGROUP`), and `Scope.GROUP` treatments
ride with the group. All-agent interactions are allowed via a non-participant
launch path (researcher/scheduler, `mug simulate`); agent backfill of a human
seat is not in v0.

**Open decisions:** one actor controlling multiple environment agents,
compound controllers, snapshot requirements, and independent versus atomic
multi-modality effects.

## API-06 — Interactions, channels, membership, matchmaking, and leases

**Types**

```python
InteractionSpec
InteractionActivitySpec
Interaction
ChannelSpec
ChannelMembership
InteractionSnapshot
InteractionResult
P2PMeshMembership       # frozen, generation-fenced replica actor set
MatchmakingPolicySpec
MatchCandidate
MatchProposal
ConnectionLease
FencingGeneration
```

**Services and SPI**

```python
InteractionService.open(occurrences, bindings, ctx) -> InteractionSnapshot
InteractionService.join(interaction_id, actor_id, lease) -> JoinSnapshot
InteractionService.submit_intent(interaction_id, intent, ctx) -> IntentReceipt
InteractionService.pause(...) -> CommitReceipt
InteractionService.close(...) -> InteractionResult
ChannelRuntime.validate_intent(state, actor, intent) -> ValidationResult
ChannelRuntime.reduce(state, accepted_event) -> ChannelState
MatchmakingService.enqueue(...) -> QueueReceipt
MatchmakingService.accept(match_proposal, ctx) -> InteractionRef
LeaseService.acquire_or_fence(...) -> ConnectionLease
```

Channels share membership and effect-validity concepts but retain typed game,
chat, and annotation protocols. Preferences need not masquerade as a live
channel.

For a P2P game, API-06 records one canonical `P2PMeshMembership` for the
interaction/game channel and membership generation. Its sorted human
`ActorInstanceId` set resolves from the formed group through the interaction
cast; it is not inferred from seat count. API-07 binds this record by digest and
generation. A changed peer set is a new fenced generation, never a silent
mid-episode edit.

**Open decisions:** interaction ownership lease, cross-visit group interaction,
match proposal expiry, disconnect grace/substitution, and pause/partial/abort
compensation. Version 0's channel-kind vocabulary is closed.

## API-07 — Environment, game, input, rendering, and execution modes

**Authoring types**

```python
EnvironmentSpec
EnvironmentArtifactRef
GameChannelSpec
AgentSlotMapping
ObservationSchema
ActionSchema
InputMapSpec             # keys bound to the env's native action space
StepPolicySpec
RenderSpec
CaptureProfileRef
ExecutionMode            # typed: ExecutionMode.SERVER | ExecutionMode.BROWSER | ExecutionMode.P2P
P2PExecutionContract     # full mesh, finality, delay, snapshot, bot-publication rules
P2PFrameFinality         # speculative/confirmed/verified/disputed evidence
EpisodeBoundary          # explicit end_frame_exclusive; mesh minimum in P2P
AppliedDecision          # action linked to API-12 DecisionResult evidence
```

**Runtime SPI**

```python
EnvironmentDriver.reset(seed, options) -> ResetResult
EnvironmentDriver.step(actions) -> StepResult
EnvironmentDriver.snapshot() -> EnvironmentSnapshot
EnvironmentDriver.restore(snapshot) -> None
EnvironmentDriver.state_hash() -> StateHash
EnvironmentDriver.render() -> RenderPacket

ActionValidator.validate(...)
GameCoordinator.accept_action(...)
TrajectoryRecorder.record_transition(...)
PeerReconciliationService.finalize(...)
BrowserEnvironmentBridge.negotiate(...)
```

All three execution modes — `ExecutionMode.SERVER`, `ExecutionMode.BROWSER`
(Pyodide, first-class), and `ExecutionMode.P2P` — are in v0 with an identical
data shape across modes; P2P is flagged as the riskiest build. Server and
browser-local execution have one writer per environment instance. Rollback P2P
has one writer per deterministic replica plus a shared accepted-input/finality
protocol over API-06's frozen mesh membership; `PeerReconciliationService` owns
the resulting evidence status rather than pretending there is one global
mutable instance. Confirmation means a complete authoritative action set with
every frozen peer participating; verification is a later unanimous state-hash
claim. The episode boundary is the minimum `end_frame_exclusive` claimed by the
complete peer set. Lower-ID-defers controls live repair direction only and
never resolves scientific disagreement. Snapshot support is declared, not
assumed; deterministic P2P coverage includes environment/platform state and
Python, NumPy, and MUG-managed JavaScript RNG state. The portable bytes/codec
remain open, and durable data may not rely on unsafe pickle.

The environment is a Gym-style env class in the study repo, versioned with the
study; **instantiation is by factory** (R-17, 2026-07-19): the game names a
module-level callable recorded by qualified name, and every runtime — server,
each Pyodide client, each P2P peer, each simulate worker — imports the study
source and constructs its own instance (no shipped instances, no exec-strings,
no magic `env` variable; browser packages pinned at publish via `requires`).
Input maps bind keys to the env's **native** action space (its own
`IntEnum` or raw `Discrete`/`Box` values); MUG never invents a parallel action
vocabulary. Rendering keeps the imperative per-frame `Surface` renderer —
`render(state, surface, seat)` in Python (Pyodide default, optional JS/HTML
custom renderer) — with the full primitive set and semantics preserved (delta
compression, object identity/tween, depth, alpha, coords, resolution
independence; typed known params plus an explicit `extras=` escape). Per-seat
rendering is a v0 goal: platform-enforced per-seat `RenderPacket`s so
hidden-information secrets are never sent, not just client-hidden. Integrity is
mode-specific and stated honestly (server-auth = thin client; Pyodide/P2P =
client runs the env, reconciled). This family also owns assets (bundled,
versioned, content-addressed), HUD/DOM overlays, keyframes, animation
semantics, the external/Unity (WebGL) activity bridge, and the
execution-package loader.

**Open decisions:** Gym/PettingZoo normalization, dtype/shape codecs, browser
package format, deterministic hashing tolerance, renderer protocol, P2P
finalization barrier, buffering policy, and mid-episode recovery claims.

## API-08 — Conversation, routing, history, streaming, and delivery

**Types**

```python
ChatChannelSpec
ChatMessage
ChatContentPart
MessageDraft
MessageReceipt
MessageDelivery
ConversationTurn
RoutingPolicySpec
ActivationPolicySpec
ModerationPolicySpec
```

**Services and SPI**

```python
ConversationService.submit(intent, ctx) -> MessageReceipt
ConversationService.history(channel_id, cursor) -> MessagePage
ConversationService.acknowledge_delivery(...) -> DeliveryReceipt
ActivationPolicy.plan(event, state) -> ActivationPlan
```

Lifecycle evidence distinguishes:

```text
message.submitted -> accepted -> started -> delta* -> committed
                  -> published -> delivered -> display_acknowledged
                  \-> rejected | cancelled | failed
```

The final participant-visible message is distinct from raw provider output.
Streaming deltas are normally experienced delivery evidence, not independent
canonical messages.
API-08 owns visible ordered history. API-12 owns assembly of a model decision
context from authorized conversation, game, artifact, and memory snapshots.

**Open decisions:** publication order for concurrent agents, context boundary,
message revision/redaction, activation-loop prevention, moderation timing,
history visibility, streaming reconnect, and delivery-versus-exposure rules.

## API-09 — Participant client, realtime commands, HTTP, and uploads

**Likely HTTP use cases**

```text
Exchange launch credential
Fetch visit bootstrap and client manifest
Create, upload, and finalize an artifact
Fetch authorized artifact/replay content
Resume and complete a visit
```

**Realtime command vocabulary**

```text
interaction.join
intent.submit
preference.response.submit
delivery.ack
state.resync
heartbeat
```

**Realtime server vocabulary**

```text
interaction.snapshot
event.batch
intent.receipt
lease.revoked
resync.required
protocol.error
```

Caller command envelopes carry protocol/schema version, per-attempt request ID,
logical-command idempotency key, routing target, a payload bound to an exact
`SchemaRef`, and any declared preconditions/producer position/lease token. The
gateway resolves and validates that schema from the offline allowlist before
fingerprinting or effects. Envelopes never carry trusted authenticated scope or
verified lease generation; the server derives both.
Server event/delivery envelopes carry their own event/message identity and
cursor/sequence. The server acknowledges after the named durability boundary,
not socket receipt.

Wire receipts declare a durability class. `IngressReceipt` means a high-rate
intent reached the current authoritative runtime but is not yet durable research
evidence. `CommitReceipt` means the domain revision, idempotency result,
canonical event record, and outbox were committed atomically.
`ArtifactCommitReceipt` additionally means staged bytes were verified and their
metadata/reference committed. Terminal receipts also state accepted, rejected,
or indeterminate outcome, receipt/effect durability, and a deployment-pinned
failure profile. Preference response submission is routed directly to API-18
rather than `InteractionService.submit_intent`.

**Open decisions:** HTTP framework-neutral description, WebSocket/SSE choice,
protocol negotiation, IndexedDB buffering, message limits, resumption window,
backpressure, asset authorization, and client build compatibility.

## API-10 — Events, capture, provenance, metrics, and projections

**Core types**

```python
EventEnvelope
EventSource
InteractionCoordinates
AppendRequest
AppendReceipt
EventCursor
EventPage
CapturePolicy
CaptureDecision
Projection
MetricDefinition
```

**Services**

```python
EventStore.append(request) -> AppendReceipt
EventStore.read(stream_id, cursor, limit) -> EventPage
EventStore.tail(stream_id, cursor) -> AsyncIterator[EventEnvelope]
CapturePolicyEvaluator.evaluate(field, context) -> CaptureDecision
EventBatchIngestService.accept(batch, ctx) -> BatchReceipt
Projector.apply(event) -> ProjectionUpdate
```

Events include schema, globally unique ID, stream and sequence, occurred and
recorded times, source, study/visit/interaction/actor context, causation,
correlation, typed payload, artifact references, privacy, and checksum.

Each authoritative stream has its own monotonic sequence. Any optional
interaction-wide coordinator sequence is explicitly labeled server acceptance
order and is not treated as physical or participant-experienced order.

Operational traces and logs are not canonical scientific evidence.

**Open decisions:** event catalog granularity, stream boundaries, event
upcasting, unknown critical events, metric schema, speculative P2P evidence,
field-level privacy, and operational/canonical correlation.

## API-11 — Storage, artifacts, repositories, transactions, and outbox

**Ports**

```python
UnitOfWork
StudyRepository
DeploymentRepository
EnrollmentRepository
VisitRepository
InteractionRepository
PreferenceRepository
ArtifactStore
LeaseStore
OutboxRepository
IdempotencyRepository
ArtifactMetadataRepository
```

**Artifact lifecycle**

```python
ArtifactStore.create_upload(metadata) -> UploadGrant
ArtifactStore.accept_chunk(grant, chunk) -> ChunkReceipt
ArtifactStore.finalize(grant, expected_hash, expected_size) -> ArtifactRef
ArtifactStore.open(ref) -> AsyncByteStream
ArtifactStore.verify(ref) -> VerificationResult
```

Object data moves through staging and finalized states because the object store
cannot share the relational transaction. Bytes are staged and verified before a
relational transaction can finalize their reference. A committed reference
never points to an object that was uncommitted at acceptance time; orphan
staging objects are safe to collect. Later outage, deletion, or bit rot changes
the artifact's availability/integrity status and retracts dependent replay or
presentation capabilities rather than pretending committed bytes are infallible.
High-frequency streams are chunked rather than stored one database row per
frame.

The Unit of Work atomically commits aggregate revisions, idempotency receipt,
canonical event records, and outbox entries. API-10 owns logical `EventStore`
semantics and API-02/shared kernel own the minimal secret store; API-11
supplies their storage/composition implementations without redefining the
contracts. The stores live in a researcher-owned database and object store:
MUG is self-hosted and imposes no access-control, retention, or deletion layer
of its own (F-4).

**Open decisions:** PostgreSQL/SQLite model, transaction isolation, outbox
delivery, artifact encryption and digest semantics, deduplication/privacy,
lease backend, garbage collection, backup consistency, and repository
granularity.

## API-12 — Automated controllers, scheduling, and execution

**Types**

```python
AgentSpec
AgentVersion
PromptTemplateVersion
DecisionRequest
DecisionContextPolicySpec
DecisionContextSnapshot
ControllerDecision
AgentEmission
DecisionValidity
DecisionProvenance
SchedulerMode
DecisionCadence          # decides_every — a property of the policy, not the input layer
ExecutionHandle
CompletionDisposition
FallbackPolicySpec       # mandatory: every automated controller declares a fallback
P2PBotAuthority          # fenced exclusive P2P action publisher for one bot seat
```

**Protocols**

```python
AgentCatalog.publish(spec, ctx) -> AgentVersion
AgentCatalog.get(agent_version_id) -> AgentVersion
PromptCatalog.publish(template, ctx) -> PromptTemplateVersion
DecisionContextAssembler.assemble(inputs, policy, memory_view) -> DecisionContextSnapshot
AutomatedController.decide(request) -> ControllerDecision
PolicyScheduler.on_event(actor_runtime, event) -> tuple[DecisionRequest, ...]
PolicyScheduler.accept_completion(decision, generation) -> CompletionDisposition
AgentExecutor.submit(request) -> ExecutionHandle
AgentExecutor.cancel(handle) -> None
ObservationEncoder.encode(snapshot, policy) -> EncodedObservation
ActionDecoder.decode(response, allowed_intents) -> DecodeResult
```

Scheduler modes include blocking turn, realtime hold, action plan, and event
triggered. Slow decisions are scheduled asynchronously and never block a game
frame, human input, or heartbeat. Decision cadence (`decides_every`) is a
property of the policy/controller, not the input layer. Provider success and
decision acceptance are separate facts: stale decisions are discarded at
effect time, and timeout or staleness invokes the mandatory declared fallback
— no acting on stale state, no hangs. Effects are reauthorized and validated
when applied.

In P2P, each bot seat has one episode-fixed action publisher: the canonical
highest eligible peer actor ID under the frozen mesh generation. The publisher
is fenced by `LeaseRef` and an authority generation; peers cannot self-elect or
overlap publishers mid-episode. Local scripted/ONNX decisions may execute
there. Provider/tool-backed inference remains server-authoritative under ADR
0005, and the selected peer only injects the already accepted recorded action.

`AutomatedController` is the asynchronous specialization of the API-05
controller contract, not a second controller root. An immutable `AgentVersion`
pins controller configuration, prompt template, context policy, provider/model
selection rule, encoders/decoders, tool catalog, memory policy, and fallback.
The exact `DecisionContextSnapshot` used for every invocation is retained or
hashed/referenced according to capture policy.

**Open decisions:** scheduler ownership, deadlines/clocks, generation fencing,
compound action/chat commit policy, repair attempts, fallback exposure,
executor topology, queue backpressure, and cost budgets.

## API-13 — Model providers, content, usage, and errors

**Normalized types**

```python
ModelSpec
ResolvedModel
ModelMessage
ModelContentPart
ModelInvocation
ModelGeneration
ModelGenerationRef
ToolDeclaration
ModelRequest
ModelResponse
ModelStreamEvent
ProviderCapabilities
Usage
ProviderError
```

**SPI**

```python
ModelProvider.capabilities() -> ProviderCapabilities
ModelProvider.resolve(model_spec) -> ResolvedModel
ModelProvider.generate(request) -> ModelResponse
ModelProvider.stream(request) -> AsyncIterator[ModelStreamEvent]
ProviderRegistry.resolve(provider_ref) -> ModelProvider
ModelInvocationService.get(invocation_id) -> ModelInvocation
ModelInvocationService.get_generation(generation_id) -> ModelGeneration
```

`ModelContentPart` is provider-normalized content and is distinct from API-08
`ChatContentPart` and API-17 presentation content. Explicit adapters transform
between them. Provider SDK objects never enter other APIs.
Requested and resolved model, parameters, retries, provider response ID, usage,
cost, timing, and safe errors enter provenance. Hidden chain-of-thought is not
requested or treated as an evidence requirement.

For hosted models, the study/agent version pins the requested provider, model
selector, parameters, adapter, and fallback policy. The invocation records the
provider-resolved model as exposure; MUG does not claim that the provider's
hidden backend is exactly pinnable.

**Open decisions:** minimum normalized capability set, structured output/tool
normalization, streaming semantics, retry/fallback authority, model alias
pinning, provider retention/residency, and adapter fixtures.

## API-14 — Tools, authorization, approval, and environment commands

**Types and protocols**

```python
ToolSpec
ToolCatalogSnapshot
ToolCallRequest
ToolCallReceipt
ToolResult
SideEffectClass
ToolAuthority
ApprovalRequest
EnvironmentCommand

ToolHandler.invoke(arguments, context) -> ToolResult
ToolRuntime.invoke(request) -> ToolCallReceipt
ToolAuthority.authorize(actor, tool, arguments) -> AuthorizationDecision
ApprovalService.decide(request) -> ApprovalDecision
EnvironmentCommandMailbox.enqueue(command) -> IngressReceipt
ToolSource.snapshot_catalog() -> ToolCatalogSnapshot
```

MUG, not the model, owns authorization. Mutating environment tools enter the
owning environment runtime's mailbox. They are initially unsupported for
replicated P2P environments unless a later authority ADR defines one externally
authorized effect path. Timeouts after an external side effect may produce
`unknown_outcome` and are not retried automatically. Exact replay substitutes
recorded results.

**Open decisions:** sandbox/trust classes, egress/SSRF controls, approval UI,
idempotency for each side-effect class, unknown-outcome reconciliation, MCP
version pinning, and catalog drift.

## API-15 — Experimental agent memory

API-08 owns durable visible conversation history. API-12 owns deterministic
decision-context assembly. This family owns only experimental memory not implied
by the visible conversation.

**Types and protocols**

```python
MemoryScopeKey
MemoryReadQuery
MemoryView
MemorySearchQuery
MemoryWriteProposal
MemoryWriteSet
MemoryCommitReceipt
MemorySnapshot
MemoryTreatmentSpec

MemoryStore.read(query) -> MemoryView
MemoryStore.search(query) -> MemorySearchResult
MemoryStore.commit(write_set, expected_revision) -> MemoryCommitReceipt
MemoryStore.snapshot(key) -> MemorySnapshot
```

Scopes are working, episodic, and longitudinal. A pinned snapshot/revision is
part of each decision request. Writes commit only at declared boundaries after
decision acceptance; stale, cancelled, fallback, and replayed work cannot
commit.

**Open decisions:** memory ownership, group scope, retrieval semantics,
summarization provenance, commit boundaries, treatment/ablation modes,
concurrent visits, and vector-backend portability. Retention and deletion are
institution-owned operations against the researcher-owned store, not API-15
commands (ADR 0015).

## API-16 — Replay capture, bundles, validation, reading, and branching

**Types and protocols**

```python
ReplayCaptureProfile
ReplayCapability
ReplayCompleteness
ReplayAuthority
ReplayManifest
ReplayBundleRef
DecisionTape
P2PReplayEvidence
P2PFinalityOutcome
StateHashCheck
ReplayCursor
ReplayFrame

ReplayBundleBuilder.build(source, profile) -> ReplayBundleRef
ReplayValidator.validate(bundle) -> ReplayValidationReport
ReplayReader.manifest() -> ReplayManifest
ReplayReader.seek(cursor) -> ReplayFrame
ReplayReader.events(start, end) -> AsyncIterator[EventEnvelope]
DeterminismVerifier.verify(bundle) -> DeterminismReport
ReplayBranchService.branch(bundle, fork_point, spec) -> BranchRunRef
```

The `.mugrun` format declares visual, seekable, deterministic, and forkable
capabilities separately, along with complete/partial/disputed/quarantined state
and authoritative/peer-reconciled/unverified evidence. Branching creates a new
counterfactual run with lineage; it is not exact replay.

P2P replay binds the exact API-06 mesh generation, API-07 frame-finality and
episode-boundary evidence, and API-12 decision results. Confirmed-only,
partial, and disputed outcomes cannot be presented as verified. Bot rollback
and exact replay apply the recorded action and make no policy, provider, or tool
call. Deterministic state-hash checks retain both expected and observed hashes;
visual fallback is a distinct declared result, not a fabricated match.

**Open decisions:** manifest schema, portable versus thin bundles, codecs,
keyframe intervals, state-hash tolerance, safe viewer, signatures, redacted
profiles, format reader lifetime, and optional archival profile.

## API-17 — Content, forms, presentation, and accessible UI

**Types**

```python
ContentActivitySpec
CompletionActivitySpec
FormActivitySpec
FormProtocolVersion
QuestionSpec
TextQuestionSpec
ChoiceQuestionSpec
ScaleQuestionSpec
FormResponse
PresentationArtifact
PresentationContentPart
ClientComponentSpec
AccessibilityRequirement
```

**Services**

```python
FormService.open(occurrence, actor, ctx) -> FormAssignment
FormService.submit(response, ctx) -> FormResponseReceipt
PresentationService.resolve(ref, viewer, ctx) -> AuthorizedPresentation
ComponentRegistry.validate(component_spec) -> ValidationReport
```

This preserves content, instructions, basic forms, completion, redirects, and
external-client activities without becoming a general survey-builder product.
Custom content and model output are rendered safely and cannot become executable
HTML implicitly.

**Open decisions:** safe rich-content format, custom-component sandbox,
accessibility baseline, response revision, content security policy, completion
semantics, and external/Unity bridge placement.

## API-18 — Preferences, annotation, quality, and adjudication

**Candidate types**

```python
TrajectorySliceRef
ModelGenerationRef
PublishedChatMessageRef
ConversationSegmentRef
ArtifactCandidateRef
CompositeCandidateRef
```

**Protocol/runtime types**

```python
PreferenceProtocolSpec
PreferenceActivitySpec
PairwiseQuestionSpec
RankingQuestionSpec
RatingQuestionSpec
BestWorstQuestionSpec
PresentationPolicySpec
QualityControlSpec
PreferenceQuery
PreferenceAssignment
CandidatePresentation
PresentationExposure
PreferenceResponse
ResponseReceipt
Adjudication
```

**Services**

```python
CandidateMaterializer.materialize(request) -> CandidateSet
PreferenceQueryGenerator.generate(...) -> PreferenceQuery
PreferenceService.next_assignment(rater, protocol, ctx) -> PreferenceAssignment
PreferenceService.acknowledge_presentation(exposure, ctx) -> PresentationReceipt
PreferenceService.submit_response(response, ctx) -> ResponseReceipt
PreferenceQualityEvaluator.evaluate(...) -> QualityAssessment
AdjudicationService.resolve(...) -> Adjudication
```

Candidates are immutable presentation artifacts before assignment. Identity is
independent of displayed position. Assignment, order, blinding, and defined
exposure commit before response acceptance.

`PreferenceService.submit_response` is the sole authority for preference
mutation. The client may carry that command over HTTP or realtime API-09, but it
does not become a generic interaction `Intent` and API-06 cannot accept it.

**Open decisions:** response revision/finalization, exposure definitions,
ranking ties, adaptive selection/propensity, assignment leases, gold/repeat
quality, adjudication, and participant versus external annotator identity.

## API-19 — Dataset query, export, lineage, and external annotation

**Types and services**

```python
Dataset                  # typed selectors: Dataset.TRAJECTORIES, Dataset.MESSAGES, ...
DatasetQuery
DatasetSnapshot
ExportSpec
ExportArtifact
LineageManifest
SplitPolicySpec

DatasetQueryService.create_snapshot(query, ctx) -> DatasetSnapshot
ExportService.start(snapshot, spec, ctx) -> JobId
ExportService.result(job_id) -> ExportArtifact
LineageService.trace(resource_ref) -> LineageGraph
Exporter.export(snapshot, spec) -> ExportArtifact
```

**JSONL is the single export format** (D13-1): familiar, greppable,
appendable, the LLM-ecosystem default; nested data stays nested JSON. There
are no Parquet, CSV, or derived-format exporters. Dataset selectors are typed
constants (`Dataset.TRAJECTORIES`), never magic strings. Every export carries
a complete lineage record so any row traces to its source evidence; redacted
or aggregated exports are new lineage-bearing objects, never silent edits.
Export is **ungated**: MUG is self-hosted and the researcher owns the store
(F-4). Transformations retain query/participant/interaction grouping so
downstream splits can avoid leakage and pseudoreplication.

**Open decisions:** query language, snapshot consistency, de-identification
profiles, split helpers, schema registry, external round-trip identity, and
live versus batch export.

## API-20 — REMOVED — governance out of scope

API-20 (authorization/RBAC, admin audit trails, retention schedules,
deletion/data-rights workflows, administration) is **removed** as a contract
family under foundational decision F-4
([ADR-0015](../decisions/0015-governance-out-of-scope.md)). MUG is
self-hosted: the researcher and their institution own the database and
infrastructure and handle access control, IRB/compliance, retention, and
deletion through their own means. Platform operations are ungated. Two
concerns were deliberately re-homed because they are not governance:
**immutable event capture** for reproducibility stays in
[API-10](api-10/index.md) (it is scientific evidence, not an audit trail), and
**minimal secret storage/reference** stays in [API-02](api-02/index.md) and
the shared kernel as a security mechanism (by-reference, never in client or
science). The heading is kept for historical numbering; see the
[tombstone](api-20/index.md).

## API-21 — RETRACTED for v0 — no plugin framework

API-21 (plugin manifests, capability negotiation, trust classes, sandboxing,
sharing/distribution) is **retracted for v0** (decisions D15-1..3). Closed
vocabularies stay closed: v0 adds no new *kinds* of activity, form field,
assignment policy, channel, or model provider beyond what ships; the generic
HTTP provider absorbs most "new provider" needs. Core authoring in plain
Python is unaffected — researchers still write their own environments,
policies, renderers, and native tools in the study repo (see API-07, API-12,
API-14). If extension points arrive post-v0, the recorded direction is plain
Python against typed `ExtensionPoint` protocols with pinned versions — no
framework, no sharing/distribution machinery. The heading is kept for
historical numbering; see the [tombstone](api-21/index.md).

## API-22 — Durable background jobs and workers

Study compile/publish jobs, replay builds, exports, provider execution,
artifact processing, headless simulation batches, and backups must not invent
independent queue semantics.

**Types and protocols**

```python
JobSpec
JobState          # typed enum: JobState.SUBMITTED ... JobState.TERMINAL
JobProgress
JobLease
JobAttempt
JobResult
JobFailure

JobService.submit(spec, ctx) -> JobId
JobService.status(job_id) -> JobSnapshot
JobService.cancel(job_id, ctx) -> CommitReceipt
WorkerQueue.claim(worker, capabilities) -> JobLease
WorkerQueue.heartbeat(lease, progress) -> LeaseReceipt
WorkerQueue.complete(lease, result) -> CommitReceipt
WorkerQueue.fail(lease, failure) -> CommitReceipt
```

Job submission is idempotent. Worker ownership is fenced by lease generation;
late workers cannot complete a reassigned job. Each job declares whether work
is retryable, cancellable, side-effecting, and resumable, plus deadline, budget,
privacy scope, result artifact schema, and attempt policy. Cancellation is a
requested transition, not a promise that an external side effect stopped.

API-22 also runs the API-01 compile/publish jobs and the headless batch runner
behind `mug simulate … --n` (all-agent runs, headless by default, `--render`
to debug; the scheduler drives).

**Open decisions:** state machine, lease duration/renewal, attempt identity,
retry classification, priority/fairness, progress durability, result retention,
provider-specific cancellation, local executor, durable queue backend, and
operator intervention.

## Dependency graph

```text
Shared IDs, schemas, errors, privacy, and command semantics
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
       Study compiler/manifests      Storage/events/artifacts
                 │                         │
                 ▼                         │
 Identity/visits/plans/treatment           │
                 │                         │
                 └────────────┬────────────┘
                              ▼
             Seats/actors/controllers/interactions
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
           Game/runtime/client       Conversation/client
                 │                         │
                 ├───────────┬─────────────┤
                 ▼           ▼             ▼
              Replay     LLM agents    Preferences/forms
                              │             │
                         Tools/memory       │
                              └──────┬──────┘
                                     ▼
                            Query/export (JSONL)
```

There is no governance layer: API-20 is removed (F-4), and the researcher-owned
store sits below everything as plain self-hosted infrastructure.

Replay and preference contracts depend only on canonical events, artifacts,
and published provenance. They never depend on a provider SDK or a live model
runtime.

## Review order and completion tracking

The recommended detailed working-session order is:

1. Shared kernel and API design decisions
2. API-01 and API-02
3. API-03 and API-04
4. API-05 and API-06
5. API-10 and API-11
6. API-22
7. API-09 and API-07
8. API-08
9. API-12 and API-13
10. API-16
11. API-17 and API-18
12. API-14 and API-15
13. API-19 (API-20 removed; API-21 retracted for v0)

For each family, the Phase 0 tracker records:

- Design owner
- Draft/proposed/accepted status
- ADR dependencies
- State-machine completion
- Python contract sketch
- JSON Schema fixtures
- Failure matrix
- Privacy review
- Contract-test plan
- Acceptance-scenario coverage
- Implementation phase and backlog links

An implementation phase may refine internal performance details, but it may not
invent a new cross-cutting identity, authority, durability, privacy, or
versioning rule without returning to architecture review.
