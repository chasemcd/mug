# Architecture Glossary

| Field | Value |
| --- | --- |
| Status | Proposed |
| Last updated | 2026-07-20 |

These terms are intentionally more precise than the vocabulary in the current
implementation. In new design documents, avoid the unqualified words
"session," "run," "user," and "agent" when one of the terms below is meant.

## Study and longitudinal terms

**Study**
: A stable research program boundary. A study can have multiple immutable
  versions and a multi-part longitudinal flow.

**Study definition**
: The author-written, pre-publication specification supplied to the compiler.
  Its source of truth is the researcher's git repository, not a platform
  draft (ADR-0013).

**Git provenance**
: The record of exactly which source state was published: the git commit SHA
  plus stored patch bytes when the working tree was dirty. Reproducible as
  *commit + patch*; stored with every study version.

**Version string**
: The hand-typed, author-chosen handle of one study version. Free-form,
  non-empty, unique and immutable within its study; the citable identifier
  used in `mug deploy study@version`. Distinct from the resolved-content
  digest (dedup identity) and the git SHA (provenance).

**Scientific manifest**
: The canonical immutable root of a study version's scientific meaning. It
  binds the normalized study, definitions, flow/rules, packages, schemas,
  capability/deployment requirements, and client/server/provenance projection
  digests while excluding publication occurrence metadata and secret bindings.

**Study version**
: An immutable published scientific protocol, stored as a compiled artifact.
  It carries a hand-typed version string, a resolved-content digest, and git
  provenance, and includes the compiled flow, conditions, actor and channel
  definitions, prompts, tools, capture policy, schemas, and artifact digests,
  but excludes secrets and mutable deployment settings. A hosted provider's
  hidden backend is recorded as actual exposure; it is not claimed to be
  content-addressed. Amendments are always new versions; deprecate/withdraw
  changes availability only.

**Deployment**
: A stable operational launch identity for one study. Each immutable deployment
  revision binds one study version to exact server/client builds, execution
  artifacts, adapters, region, endpoints, and secret references.

**Deployment revision**
: An immutable *internal* operational binding pinned by each visit; the
  operator surface is only `deploy` and `stop`. A scientifically
  equivalent infrastructure or secret-binding change may create a new
  deployment revision without changing the study version. If a change can
  affect study semantics or participant experience, it requires a new study
  version as well.

**Participant principal**
: An opaque server-issued identity used to derive participant runtime authority.
  It carries no external identity or PII and is not the default analysis
  identifier.

**External identity link**
: A blinded reference to a recruitment provider's or panel's subject ID,
  captured opaquely at launch and stored apart from research data. It never
  becomes a research object key.

**Enrollment**
: A participant's study-scoped pseudonymous identity and longitudinal record.

**Return link**
: The stable per-participant link that lets an enrolled participant re-enter a
  study (for a later part of a multi-part flow, or to resume). MUG recognizes
  returners; re-contact logistics belong to the researcher's own tools.

**Visit**
: One attempt by one enrollment to participate in one part of the study flow.
  A visit is not a browser connection or multiplayer match. It pins one study
  version and one immutable deployment revision.

**Visit plan**
: The fully materialized, persisted activities, randomization outcomes,
  branches, parameters, roles, and stable occurrence identifiers for a visit.

**Activity occurrence**
: One materialized occurrence of an authored activity in a visit plan. It may
  present content, collect a form, run an interaction, elicit a preference, or
  complete the visit.

## Interaction terms

**Interaction**
: One coordinated activity involving one or more actor instances and one or
  more channels. A multiplayer game with chat is one interaction, not two
  unrelated sessions. Its channel streams form a causally linked evidence graph;
  they do not imply one physically meaningful global order.

**Seat**
: A role or slot declared by an interaction specification, such as
  `player_left`, `human_annotator`, or `coach`. A seat exists before a concrete
  actor fills it. Its ID type is `SeatDefinitionId`, never an occurrence ID.

**Actor instance**
: A human or software participant in one interaction. A human actor may refer
  to an enrollment; a software actor refers to an immutable controller or
  agent version. An actor is human XOR software agent, never both.

**Seat ↔ agent-id binding**
: The explicit mapping between an authored seat and the environment's own
  internal agent identifier. The environment keeps its native agent ids; the
  binding separates role (seat), occupant (actor), and env slot so casting a
  human or an `agent@version` into a seat never rewrites the environment.

**Controller binding**
: The mechanism controlling one actor capability in one channel. Human input,
  a deterministic policy, an RL model, and an LLM can each be controller
  bindings. One actor may use different bindings for game actions and chat.

**Channel**
: A typed interaction medium with membership, visibility, ordering, and
  access rules. Initial channel types are game, chat, and annotation.
  `ChannelDefinitionId` identifies the authored declaration;
  `ChannelInstanceId` identifies one runtime channel.

**Episode**
: One environment reset-to-terminal interval inside a game channel.

**P2P mesh membership**
: The canonical, generation-fenced set of human actor instances hosting the
  deterministic replicas for one P2P game channel. A full mesh is logical:
  every replica must receive every required action and participate in frame
  confirmation and state-hash verification, even when a relay transports a
  particular edge. Changing the set creates a new membership generation; it
  never silently changes an episode already in progress.

**Confirmed frame**
: A P2P frame whose complete authoritative action vector is known and whose
  entire frozen mesh membership has participated. Predicted actions do not
  confirm a frame. `confirmedFrame` is the highest contiguous confirmed frame.

**Verified frame**
: A confirmed P2P frame for which every replica in the frozen mesh membership
  attests the same post-step state hash. `verifiedFrame` is the highest
  contiguous verified frame and never advances across missing or conflicting
  evidence. Live resynchronization does not turn a disagreement into
  verification.

**Connection lease**
: Ephemeral ownership of a browser or worker connection. It is not research
  status and is never the sole evidence that a visit or interaction exists.

**Ownership lease**
: Fenced authority held by a worker/coordinator for one runtime resource. Its
  namespace epoch and generation are checked when an effect is applied.

## Shared contract terms

**Wire command**
: An untrusted, schema-versioned request to perform one logical mutation. It
  carries routing claims and retry/precondition material, never trusted
  principal, actor, treatment, membership, or effect-validity state.

**Command context**
: Trusted server-derived authority, scope, fingerprint, deadline, causation,
  and verified fencing information used to execute a wire or internal command.

**Command status**
: A mutable projection for queued/running/cancelling work. It is not proof of a
  terminal accepted or rejected domain result.

**Command receipt**
: An immutable terminal accepted, rejected, or indeterminate result that names
  the receipt and effect durability boundary. A repeated idempotent command
  returns the same receipt.

**Transport acknowledgment**
: Confirmation that bytes were parsed, framed, or queued. It is not a command
  receipt or scientific acceptance.

**Aggregate revision**
: A monotonic optimistic-concurrency value for one mutable aggregate. It is not
  an immutable version, event sequence, or timestamp.

**Fencing generation**
: A monotonic ownership epoch within one lease namespace. Effects from an older
  generation are rejected even when their original holder is otherwise known.

## Evidence terms

**Research event**
: An immutable, schema-versioned fact accepted into the canonical event ledger.

**Artifact**
: Immutable content stored outside or alongside the relational record, with a
  digest, media type, size, privacy classification, and lineage. It lives in
  the researcher-owned store; MUG attaches no retention policy of its own.

**Privacy classification**
: A canonical set of handling labels with exactly one base disclosure label,
  `public` or `research`, plus optional independent `sensitive` and `pii`
  restrictions on research data. Joining classifications selects the stricter
  base and unions restrictions. `secret` is deliberately outside this
  research-data classification.

**Canonical stream**
: The finalized authoritative sequence used to describe what the environment,
  conversation, or workflow accepted.

**Experienced stream**
: What a particular participant was delivered or shown, including latency,
  speculative frames, corrections, skipped render packets, and streaming
  message timing.

**Assignment**
: The treatment or condition the protocol intended to deliver.

**Exposure**
: The exact treatment, model, prompt, toolset, interface, or content actually
  delivered.

**Replay**
: Reproduction from recorded actions, messages, render data, model decisions,
  and tool results. Exact replay never calls a live model provider or repeats an
  external side effect.

**Counterfactual run**
: A new, branched execution against prior evidence. It is not replay.

## Retired terms

These terms appeared in earlier revisions and were retired by the Phase 0
user-surface review. Do not use them in new design documents.

**Study draft / draft revision / definition registry** *(retired, ADR-0013)*
: Git is the source of truth for study source; the platform stores no drafts
  or mutable registries. See *git provenance* and *version string*.

**Account / auth session** *(retired, ADR-0014)*
: No accounts, magic links, OIDC, or WebAuthn. The launch link and the stable
  return link are the entire participant entry surface.

**Wave / invitation / consent record** *(retired, ADR-0014)*
: Longitudinal rounds are multi-part flows plus the return link; consent is an
  ordinary flow activity recorded like any response; recruitment and outreach
  stay in the researcher's own tools.

**Governance grant / audit trail / retention schedule / deletion workflow**
*(retired, ADR-0015)*
: MUG is self-hosted and ungated; the researcher-owned store and institution
  handle access control, compliance, retention, and deletion. Immutable event
  capture (API-10) is scientific evidence, not an audit trail.

**Plugin / extension point** *(retired for v0, D15-1..3)*
: No plugin framework in v0; closed vocabularies stay closed. Core authoring
  in plain Python (environments, policies, renderers, tools) is unaffected.
  The recorded post-v0 direction is typed `ExtensionPoint` protocols.
