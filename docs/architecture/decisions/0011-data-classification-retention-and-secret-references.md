# ADR 0011: Data Classification, Retention, and Secret References

| Field | Value |
| --- | --- |
| Status | Accepted |
| Date | 2026-07-17 |
| Accepted | 2026-07-20 (shared-kernel **core-layer** freeze; accountable-owner human sign-off; data-classification lattice + `SecretRef` boundary held under adversarial security review) |
| Owners | Unassigned |
| Supersedes | None |
| Superseded by | [ADR 0015](0015-governance-out-of-scope.md) in part (2026-07-18): the API-20 governance layer (policy engine, retention/deletion workflows, grants) is removed; the data-classification and secret-reference mechanisms stand as security controls |
| Affects | Shared kernel and all data-bearing API families; especially API-01, API-03, API-10 through API-20 |

## Context

The north-star platform sends participant, game, chat, prompt, model, tool,
preference, replay, identity, and operational data across browsers, servers,
workers, stores, providers, researchers, and exports. The current broad
serialization of public Python attributes cannot safely carry blinded treatment
or private provider configuration. Treating provider credentials as ordinary
configuration would also leak them into manifests, logs, evidence, or bundles.

## Decision

Adopt the [privacy, retention, and secrets contract](../phase-0/shared-kernel/privacy-retention-and-secrets.md):

- Every persisted data-bearing field/document/artifact declares or inherits an
  immutable `DataHandlingRef` with canonical privacy labels and a
  `RetentionPolicyRef`.
- Privacy labels form a joinable lattice: exactly one base label (`public` or
  `research`) plus independent additive `sensitive` and `pii` restrictions.
  Effective handling is the join of inherited, declared, and policy-overlay
  labels. Lowering it requires an explicit provenance-bearing transformation
  that creates a new data object.
- `secret` is not a research privacy label. Secret material is forbidden from
  ordinary JSON/evidence and appears only as `SecretRef` in authorized private
  server/deployment configuration.
- Compile explicit client, private server, and provenance manifests. Never infer
  browser-safe metadata from arbitrary public attributes.
- Separate participant chat, model generation, raw provider body, visible
  presentation, conversation history, decision context, and experimental memory.
- Require a declared policy/data-flow for model providers, tools, exports, replay
  bundles, and other processors; record actual fallback/exposure.
- Treat withdrawal, exclusion, unlinking, revocation, erasure/anonymization,
  derivative deletion, legal hold, and backup expiry as separate audited states.

## Scope and non-goals

This ADR defines the portable classification/reference and baseline flow rules.
API-20 still owns consent/legal-purpose policy, RBAC/ABAC, retention engine,
secret provider, data-rights workflow, deletion implementation, residency, and
processor governance. It does not promise that all retained scientific evidence
is legally erasable or that independently released exports can be recalled.

## Invariants

- Secret material never enters client/provenance manifests, ordinary events or
  artifacts, replay bundles, exports, traces/logs, receipts/errors, IDs, or
  idempotency keys.
- A `SecretRef`, artifact reference, digest, or opaque ID grants no access.
- Client data cannot reveal blinded/private condition, partner, model, prompt,
  candidate, or treatment through metadata or error behavior.
- Persisted data has a retention/purpose policy and traceable derivatives.
- Effective handling is the lattice join of its immutable creation labels and
  every inherited or policy-added restriction; ordinary policy evaluation can
  never lower it.
- Provider/tool content is limited to the compiled declared flow and actual
  processing is recorded in protected provenance.
- Administrative privacy actions append audit/evidence; they do not silently
  rewrite historical facts.

## Consequences

### Positive

- Privacy/security requirements become part of every feature contract rather
  than a late governance retrofit.
- Client manifests and replay/export variants can be reviewed mechanically for
  secret/blinding leakage.
- Longitudinal identity can remain durable without using external identity as a
  research key.
- Model/tool/provider processing and fallback become inspectable exposures.

### Costs and constraints

- API-20 policy evaluation and lineage participate in storage, export, replay,
  provider, tool, and deletion paths.
- Multiple protected content representations and redacted bundle/export
  variants require storage and provenance.
- Physical deduplication cannot cross policy/tenancy boundaries merely because
  digests match.
- Some data rights require asynchronous derivative/backups processing and honest
  limitation reporting.

### Failure consequences

- Policy/secret resolution failure is fail-closed for the affected external
  request; it cannot fall back to a broader data flow.
- Candidate/presentation content unavailability pauses/reassigns/invalidates
  under explicit policy rather than substituting silently.
- Deletion failure remains a visible audited state requiring retry/escalation.
- A later stricter classification withdraws access/export capabilities without
  mutating original evidence bytes.

## Security and privacy

This ADR is itself a baseline security/privacy control. Secret resolution is
purpose-, deployment-, consumer-, and service-principal-scoped, returns a
short-lived nonserializable lease, and audits only binding/revision. Public
errors use allowlisted details; forbidden/nonexistent protected resources may be
observationally identical. Trace baggage and raw validation inputs are excluded.

## API and schema impact

Shared `DataHandlingRef`, privacy-label set, `RetentionPolicyRef`, `ArtifactRef`,
and `SecretRef` shapes appear throughout schemas. API-01 produces three explicit manifests;
API-03 isolates identity; API-10/11 classify evidence/artifacts; API-12–15
declare provider/tool/memory flows; API-16/19 build audience-scoped bundles and
exports; API-18 protects blinding; API-20 owns policy/resolution/actions.

## Alternatives considered

### Add privacy and secrets in a late hardening phase

Rejected because client schemas, evidence, providers, storage, and replay would
already have irreversible unsafe boundaries.

### Put credentials directly in study/provider configuration

Rejected because compilation, logging, browser serialization, provenance, and
bundling would copy material broadly and make rotation unsafe.

### One generic “private” boolean

Rejected because identity, sensitive content, pseudonymous research, processing
purpose, retention, export, and secret handling have different controls.

### Delete rows in place and promise immediate global erasure

Rejected because immutable evidence, artifacts, exports, derivatives, shared
blobs, audits, and backups require explicit, truthful state transitions.

## Validation

- Static/fixture scans for forbidden secret/token/path/URI fields
- Client-manifest and blinded-candidate leakage review
- Authorization existence-concealment and public-error injection tests
- Policy tightening, scoped artifact access, derivative lineage, shared-blob,
  deletion retry, backup expiry, and restore/redeletion tests
- NS-01/02 blinding, NS-05 private channel isolation, NS-08 external identity,
  and full NS-12 walkthrough

## Follow-up decisions

- Consent, purposes, policy language, retention/deletion state machines — API-20
- Account/external identity vault and longitudinal linkage — API-03
- Artifact encryption/dedup/access grant — API-11/API-20
- Provider privacy/residency and tool egress/sandbox policy — API-13/API-14/API-20
- Bundle/export audience, redaction, and released-copy limitations — API-16/API-19/API-20
