# Quality Attributes

| Field | Value |
| --- | --- |
| Status | Accepted (Phase 0 closed as-is, 2026-07-20) |
| Last updated | 2026-07-20 |
| Phase 0 owner | Work package 0A |
| Scope alignment | ADR-0014 (identity, not recruitment), ADR-0015 (governance out of scope), API-21 retracted for v0 |

Feature lists do not make the target architecture testable. Phase 0 must accept
measurable quality attributes and representative workload profiles before API
contracts are frozen.

## Priority order

When qualities conflict, use this default ordering unless a study version
declares a stricter policy:

1. Participant safety, runtime/channel isolation, and secret protection
2. Scientific integrity and explicit evidence completeness
3. Correct treatment, identity, and interaction isolation
4. Real-time participant experience
5. Availability and graceful degradation
6. Cost and throughput efficiency
7. Operator and developer convenience

The system must not silently trade a higher-priority property for a lower one.
For example, it may pause or mark a run partial instead of claiming complete
capture when durable storage is unavailable.

## Scientific integrity

- Assignment, plan, progression, committed message, form/preference response,
  completion, and artifact-finalization commands that return a `CommitReceipt`
  have zero acknowledged-data loss under the declared storage failure model.
  High-rate `IngressReceipt`s make no such durability claim.
- Published scientific versions and their artifact digests are immutable.
- Missing, partial, disputed, degraded, invalidated, and quarantined evidence is
  never exported as complete without an explicit override recorded in lineage.
- Assignment and exposure can be reconstructed for every valid interaction.
- All provider/tool/controller effects can be traced to exact inputs, versions,
  and acceptance/discard outcomes.
- Canonical and experienced evidence are distinguishable whenever they may
  differ.

## Real-time responsiveness

- Provider, tool, database, object-store, export, and background-job I/O never
  executes while an environment mutation lock is held.
- A provider delayed for 30 seconds must not stall human input ingestion,
  connection heartbeats, unrelated chat, or the configured environment loop.
- Each game execution profile declares a frame budget and measures scheduling,
  action-ingest, step, render, serialization, and delivery time separately.
- Durable chat/form/preference acknowledgment latency is measured separately
  from model generation or artifact processing latency.
- Backpressure has a declared bounded-buffer, pause, degrade, or fail-closed
  policy. Unbounded queues are prohibited.

Phase 0 must select concrete percentile thresholds after benchmarking the
reference environments rather than inventing one number for every game.

## Durability and recovery

- The recovery point objective for mutations with a `CommitReceipt` is zero
  within the supported database profile.
- Every mutable aggregate has a revision, state machine, and idempotent recovery
  path.
- Every live owner has a fencing generation; a stale browser or worker cannot
  apply effects after ownership changes.
- Exact mid-episode recovery is advertised only for environments and controllers
  that pass snapshot conformance.
- Otherwise, interruption closes a partial attempt and starts a separately
  identified attempt; trajectories are never silently spliced.
- Backup and restore objectives are deployment-profile settings tested by drills.

## Isolation and security

These attributes govern the experimental runtime and its external boundaries.
They do not create operator roles, grants, or an administrative authorization
layer. A self-hosted deployment trusts whoever can operate it; the institution
must secure that perimeter and the researcher-owned store.

- One study, enrollment, visit, interaction, actor, channel, treatment, model,
  tool, or memory scope cannot affect another without an explicit compiled
  binding, runtime membership, or ownership relation.
- Secret values do not occur in client manifests, event/artifact payloads,
  replay bundles, researcher exports, or ordinary logs.
- Client, peer, webhook, provider, and tool inputs are treated as untrusted at
  their boundary. Researcher-authored study code is trusted code at the
  self-hosted perimeter, but the published version pins exactly which code ran.
- Model or tool output is data, never executable HTML or code by default.
- Tool/model spending and activation recursion have per-study and per-interaction
  budgets and emergency stops.
- Operator access is not gated or audited by MUG. Deployment credentials,
  network access, and direct store access are controlled by the self-hosting
  institution.

## Privacy and researcher-owned data

- External identity and contact information are separable from pseudonymous
  research evidence, and external identity is stored apart by default.
- Data classification may be applied at field/artifact granularity when one
  event contains mixed content.
- Consent text is ordinary versioned study content and its response is ordinary
  research evidence; MUG does not implement a consent-policy or withdrawal
  subsystem.
- Provider-processing and export transformations are explicit and
  lineage-bearing. Export is ungated within the trusted self-hosted deployment.
- MUG does not schedule or enforce retention, withdrawal, unlinking, erasure,
  legal hold, or data-rights workflows. The researcher and institution perform
  those operations against their own store and own any resulting consistency,
  backup, or released-export obligations.
- Redacted/shareable replay and export profiles are distinct from internal
  research profiles; redaction creates a new lineage-bearing object rather than
  rewriting source evidence.

## Replay and reproducibility

- Every replay advertises only capabilities it can verify: visual, seekable,
  deterministic, forkable, or combinations thereof.
- Exact replay is offline with respect to model providers and external tools and
  never commits memory.
- Integrity validation covers every referenced chunk and embedded artifact.
- Deterministic verification reports the first divergent state/observation
  coordinate and never silently continues as exact.
- Published studies pin platform/client, environment, controller, prompt, tool,
  asset, schema, and capture versions sufficient for their declared claims.

## Accessibility and participant experience

- Core study navigation, forms, preference controls, replay controls, and chat
  support keyboard-only and screen-reader use.
- Color, animation, timing, and focus requirements have configurable accessible
  alternatives.
- Technical-problem, cannot-judge, disconnect, waiting, and partial-completion
  paths are first-class participant experiences.
- Preference presentation records exposure as quality evidence without treating
  one heuristic as an automatic exclusion rule.

## Scalability and workload profiles

Phase 0 defines at least four benchmark profiles:

1. Browser-local single-player studies with server-side evidence ingestion
2. P2P rollback games with matchmaking and peer reconciliation
3. Server-authoritative games with multiple concurrent interactions
4. Chat/LLM studies with streaming, tools, memory, and large content artifacts

Each profile specifies concurrent participants/interactions, environment FPS,
event and artifact rates, episode length, chat/model traffic, evidence volume,
operator-selected preservation horizon, and expected provider latency. Phase
1–6 gates set throughput targets from these profiles.

## Operability

- Every command, event, provider/tool call, job, and artifact can be correlated
  without exposing direct identity or secrets.
- Operators can distinguish participant state, durable research state, live
  connection state, worker ownership, provider health, and evidence completeness.
- Runtime and scientific corrections append new evidence rather than rewriting
  accepted evidence. Direct operator changes to the researcher-owned store are
  outside MUG's consistency and audit guarantees.
- Provider, worker, database, object-store, transport, and trusted author-code
  failures have runbooks and fault-injection tests.

## Closed v0 surface and post-v0 extensibility

- Version 0 has no plugin framework, discovery/negotiation layer, trust-class
  hierarchy, or sharing/distribution mechanism. MUG-defined vocabularies are
  closed and unsupported kinds fail during authoring or compilation.
- Researcher-authored environments, policies, renderers, and native tools are
  core study code rather than plugins; publication pins them with the study.
- Unsupported capability combinations fail during compilation or deployment,
  not after participants arrive.
- Provider SDK types do not leak into canonical evidence or unrelated domain
  APIs.
- If extension points are introduced after v0, they use typed Python protocols
  pinned with the study. They do not silently change a published version through
  discovery drift and do not create a plugin framework or distribution channel.

## Phase 0 quality gate

Phase 0 does not pass until each attribute has:

- An accountable owner
- At least one measurable acceptance scenario
- A named implementation phase
- A representative workload or fault fixture
- A documented degradation/failure policy
- An explicit decision where the proposed text still leaves a threshold open
