# Identifiers and Resource Hierarchy

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Owner | Shared kernel; issuance and lifecycle remain domain-owned |
| Last updated | 2026-07-20 |
| Decision | Proposed ADR 0008 |

## Identity classes

MUG uses different types even where two values share the same physical wire
encoding.

| Class | Meaning | Examples |
| --- | --- | --- |
| Definition | Stable scientific or operational concept across edits and publications | `StudyId`, `ActivityDefinitionId`, `AgentDefinitionId` |
| Immutable version | One published, immutable realization | `StudyVersionId`, `AgentVersionId`, `DeploymentRevisionId` |
| Runtime occurrence | One materialization, execution, or accepted record | `VisitId`, `InteractionId`, `EpisodeId`, `EventId` |
| Principal/security | Identity to which authentication may resolve | `ParticipantPrincipalId`, `ResearcherPrincipalId`, `ServicePrincipalId` |
| Mutable resource | Stable logical object with an optimistic-concurrency revision | `DeploymentId`, `EnrollmentId` |
| Authoring key | Human-readable, namespace-scoped source key | `activity_key="practice"` |
| Content digest | Equality/integrity of bytes under a declared digest domain | SHA-256 digest of an artifact or canonical manifest |
| Credential/token | Proof presented to an authority | session token, lease token, resume token |
| Position/version | State or order within another identity | aggregate revision, stream sequence, study display ordinal |

These classes are not interchangeable. In particular, a digest does not
replace an occurrence ID, a UUID timestamp is not event time, and a readable
key is not a database or security identity.

## MUG-issued identifier encoding

Every MUG-issued entity ID is a registered lowercase kind prefix, an
underscore, and a canonical lowercase UUIDv7:

```text
<kind>_<xxxxxxxx-xxxx-7xxx-[89ab]xxx-xxxxxxxxxxxx>
```

Example:

```json
"study_01981c4e-7b64-7e81-8a72-a2537d5f6c91"
```

Generic syntax:

```regex
^[a-z][a-z0-9]{1,23}_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$
```

The prefix is validated against the type registry. Code must not strip or
branch on the prefix as a substitute for a typed parser. UUIDv7 time bits are a
database-locality convenience only. They are not trusted event time, security
entropy, or canonical order.

MUG IDs are:

- Immutable after issuance
- Case-sensitive and lowercase on the wire
- Opaque outside their owning API
- Never reused, including after deletion
- Never bearer credentials
- Potentially personal or blinded data when linkable, despite being opaque

Security tokens use independently generated CSPRNG material and a separate
type. An API must use scoped presentation handles instead of raw entity IDs
when UUID timing, cross-context linkage, or the type prefix could unblind a
condition.

## Public handles

`PublicHandle` is the mandatory browser-safe alias for an internal resource
whenever exposing its typed ID, UUIDv7 issuance time, digest, definition kind,
or stable cross-context identity could reveal linkage or unblind a study. It is
not a MUG entity ID and does not appear in the registered-kind table.

Its portable wire form is a string:

```text
handle_<canonical unpadded base64url encoding of exactly 16 CSPRNG bytes>
```

```regex
^handle_[A-Za-z0-9_-]{21}[AQgw]$
```

A handle binding records, in protected server state, the internal typed
resource, issuing deployment/visit/presentation context, audience or principal
scope, purpose, and lifetime. The following rules are mandatory:

- A handle is opaque and carries no type, timestamp, digest, display order, or
  scientific identifier.
- Decoders require exactly 22 canonical base64url characters (128 bits); the
  final character restriction prevents alternate encodings of the same bytes.
- A handle is an untrusted routing claim, not a bearer credential or grant.
  The server still verifies launch/runtime identity, audience, membership, and
  current binding state when resolving it.
- Equality is meaningful only inside the issuing scope. APIs issue a new handle
  across scopes unless the published protocol explicitly requires stable
  pseudonymity and privacy review permits it.
- Client events may retain the handle needed to describe participant experience;
  protected canonical evidence separately records the resolved binding to the
  internal resource.
- A missing, expired, unavailable-to-this-audience, and nonexistent protected binding follows
  the owning API's concealment-safe error policy.

The shared kernel owns this encoding and non-authorizing semantics. API-03 owns
participant pseudonym bindings, API-09 owns transport presentation, and
API-18 owns blinded candidate/presentation bindings. Their detailed issuance,
expiry, resolution, and persistence services are specified by those APIs.

## Registered kinds

This is the initial registry. Renaming a Python class does not change an
accepted wire prefix. New entries require shared-kernel review; deleted entries
remain reserved.

| Prefix | Type | Class | Owning API |
| --- | --- | --- | --- |
| `study` | `StudyId` | Definition | API-01 |
| `studyver` | `StudyVersionId` | Immutable version | API-01 |
| `flownode` | `FlowNodeDefinitionId` | Definition | API-01/API-04 |
| `deploy` | `DeploymentId` | Mutable resource | API-02 |
| `deployrev` | `DeploymentRevisionId` | Immutable version | API-02 |
| `participant` | `ParticipantPrincipalId` | Principal/security | API-03 |
| `service` | `ServicePrincipalId` | Principal/security | Shared kernel/runtime |
| `system` | `SystemPrincipalId` | Principal/security | Shared kernel/runtime |
| `researcher` | `ResearcherPrincipalId` | Principal/security | API-03 |
| `enrollment` | `EnrollmentId` | Mutable resource | API-03 |
| `visit` | `VisitId` | Runtime occurrence | API-04 |
| `visitplan` | `VisitPlanId` | Immutable materialization | API-04 |
| `activitydef` | `ActivityDefinitionId` | Definition | API-01/API-04 |
| `activity` | `ActivityOccurrenceId` | Runtime occurrence | API-04 |
| `seatdef` | `SeatDefinitionId` | Definition | API-05 |
| `actor` | `ActorInstanceId` | Runtime occurrence | API-05 |
| `controller` | `ControllerBindingId` | Runtime occurrence | API-05 |
| `interaction` | `InteractionId` | Runtime occurrence | API-06 |
| `group` | `GroupId` | Runtime occurrence | API-06 |
| `channeldef` | `ChannelDefinitionId` | Definition | API-06 |
| `channel` | `ChannelInstanceId` | Runtime occurrence | API-06 |
| `lease` | `LeaseId` | Runtime occurrence | API-06 |
| `leaseepoch` | `LeaseNamespaceEpochId` | Runtime occurrence | API-06 |
| `prodepoch` | `ProducerEpochId` | Runtime occurrence | API-09/API-10 |
| `clockepoch` | `ClockEpochId` | Runtime occurrence | Shared kernel/runtime |
| `correlation` | `CorrelationId` | Runtime occurrence | Shared kernel |
| `episode` | `EpisodeId` | Runtime occurrence | API-07 |
| `message` | `MessageId` | Runtime occurrence | API-08 |
| `stream` | `StreamId` | Mutable append resource | API-10 |
| `event` | `EventId` | Runtime occurrence | API-10 |
| `artifact` | `ArtifactId` | Runtime occurrence | API-11 |
| `upload` | `UploadId` | Runtime occurrence | API-11 |
| `agentdef` | `AgentDefinitionId` | Definition | API-12 |
| `agentver` | `AgentVersionId` | Immutable version | API-12 |
| `agentrun` | `AgentRunId` | Runtime occurrence | API-12 |
| `promptdef` | `PromptTemplateDefinitionId` | Definition | API-12 |
| `promptver` | `PromptTemplateVersionId` | Immutable version | API-12 |
| `decision` | `DecisionId` | Runtime occurrence | API-12 |
| `modelcall` | `ModelInvocationId` | Runtime occurrence | API-13 |
| `generation` | `ModelGenerationId` | Runtime occurrence | API-13 |
| `tooldef` | `ToolDefinitionId` | Definition | API-14 |
| `toolver` | `ToolVersionId` | Immutable version | API-14 |
| `toolcall` | `ToolCallId` | Runtime occurrence | API-14 |
| `memory` | `MemorySnapshotId` | Immutable materialization | API-15 |
| `prefdef` | `PreferenceProtocolDefinitionId` | Definition | API-18 |
| `prefver` | `PreferenceProtocolVersionId` | Immutable version | API-18 |
| `prefquery` | `PreferenceQueryId` | Runtime occurrence | API-18 |
| `prefassign` | `PreferenceAssignmentId` | Runtime occurrence | API-18 |
| `prefresponse` | `PreferenceResponseId` | Runtime occurrence | API-18 |
| `secret` | `SecretBindingId` | Mutable resource | API-02 |
| `job` | `JobId` | Runtime occurrence | API-22 |
| `command` | `CommandId` | Runtime occurrence | Shared kernel |
| `request` | `RequestId` | Runtime occurrence | Shared kernel |
| `receipt` | `ReceiptId` | Runtime occurrence | Shared kernel |
| `error` | `ErrorId` | Runtime occurrence | Shared kernel |

The ambiguous legacy names `SeatId` and `ChannelId` must not appear in vNext
contracts. They become `SeatDefinitionId` and either `ChannelDefinitionId` or
`ChannelInstanceId`.

### Reserved (retired) prefixes

The 0.2 re-draft removed these prefixes from the active registry and from the
version-0 schema pattern. Per the deleted-entries rule above, each remains
permanently *reserved*: it may never be reused for any other kind, and no new
records may be issued under it.

- `studydraft`, `draftrev` — retired by ADR-0013; git-native study versioning
  removed the draft/revision resources.
- `account`, `authsession`, `wavedef` — retired by ADR-0014; API-03 was reduced
  to identity-not-recruitment and no longer owns accounts, auth sessions, or
  wave definitions.
- `retpolicy`, `retpolicyver` — retired by ADR-0015; governance (API-20) was
  removed, so there is no retention-policy subsystem. Retention is owned by the
  self-hosting institution against its own store.

## Definition identity and authoring keys

Readable authoring keys use this syntax:

```regex
^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$
```

They are at most 64 ASCII characters and are unique only in the declaring
namespace. MUG has no checked-in or mutable definition registry (ADR 0013).
The draft default tracked by SK-O01 is to resolve continuity against immutable
published history: an existing key retains its definition ID, a new key gets a
new ID, and rename or fork continuity is explicit and lineage-bearing. The
compiler rejects ambiguous key reuse. Forking a study creates a new `StudyId`
and new definition IDs while recording lineage. The exact rename declaration
remains open until SK-O01 is accepted.

Definition IDs are not content hashes. Ordinary edits change content without
changing the definition identity. Nested definitions can be versioned by the
pair `(definition_id, study_version_id)`; independently publishable agents,
prompts, tools, environments, forms, and preference protocols have their own
version types.

## Version and occurrence issuance

- Publishing a novel manifest digest within a study creates a new immutable
  version ID, catalog ordinal, and manifest digest. Repeating publication of the
  same manifest under the same study is idempotent and returns the existing
  version; it does not manufacture a second scientific version with identical
  content. The ordinal is display metadata, not identity.
- Materialization creates a new occurrence ID. Idempotency prevents duplicate
  occurrences; deterministic UUID derivation must not substitute for an
  idempotency record.
- The authoritative service issues canonical IDs. Offline or P2P producers may
  issue typed source-assertion IDs only under an explicit producer scope; the
  acceptance authority may issue a distinct canonical event ID.
- IDs never encode parentage. Parent links are explicit fields; runtime
  identity, membership, and effect validity are resolved from canonical state.

## Resource hierarchy

The target logical hierarchy is:

```text
Study
├── StudyVersion
│   └── definition versions (activity, seat, channel, agent, prompt, tool, ...)
├── Deployment
│   └── DeploymentRevision ── pins exactly one StudyVersion
└── Enrollment
    └── Visit
        ├── pins exactly one StudyVersion and DeploymentRevision
        └── VisitPlan
            └── ActivityOccurrence
                └── Interaction
                    ├── SeatDefinition → ActorInstance → ControllerBinding
                    ├── ChannelInstance → Message / delivery evidence
                    └── Episode → trajectory/replay evidence

Every durable resource may reference EventStream(s) and Artifact(s).
ModelInvocation, ToolCall, AgentRun, PreferenceAssignment, PreferenceResponse,
and Job reference their causal activity/interaction but retain independent IDs.
```

This is a relationship model, not a URL or runtime-authority hierarchy. An object
can have additional lineage and causation links, but exactly one owning API and
aggregate boundary.

## Public and typed references

`ResourceRef {id}` exists for lineage, evidence correlation, and generic
envelopes. Its kind is
derived from the registered ID prefix rather than repeated as caller-controlled
data. Domain APIs should expose typed references that make invalid combinations
unrepresentable.

External-provider identifiers are encrypted/protected mappings owned by API-03.
They never become MUG IDs, research object keys, idempotency keys, trace values,
or ordinary export columns.

## Rejected alternatives

- **Labels or source paths as IDs:** renames and refactors would change identity.
- **Content hashes as all IDs:** equal bytes can be different occurrences with
  different provenance, privacy classification, and institutional handling.
- **One unprefixed UUID type:** it makes accidental cross-type substitution easy
  in JSON, logs, fixtures, and dynamically typed clients.
- **Auto-increment integers:** they leak cardinality, complicate offline issuance,
  and are unsafe across tenancy boundaries.
- **Deterministic occurrence UUIDs:** they hide duplicate-command semantics and
  make namespace mistakes scientifically dangerous.
