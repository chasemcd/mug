# Privacy Classification and Secrets

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Owner | Shared portable shapes; the self-hosting institution owns retention and access policy (ADR 0015) |
| Last updated | 2026-07-20 |
| Decision | Proposed ADR 0011, narrowed by ADR 0015 |
| Scenario anchors | NS-01, NS-02, NS-05, NS-08, NS-12 |

## Classification model

Every persisted data-bearing field/document/artifact declares or inherits a
`DataHandlingRef`: a canonical privacy label set. Privacy is a small label-set
lattice, not a scalar enum that pretends identity and sensitivity are one total
ordering.

Every valid label set contains exactly one base disclosure label and zero or
more independent restriction labels:

| Label | Role | Initial meaning | Typical examples |
| --- | --- | --- | --- |
| `public` | Base, least restrictive | Approved for public disclosure under the stated purpose | Public instructions, intentionally released benchmark metadata |
| `research` | Base, controlled | Controlled research data; it may be anonymous, pseudonymous, or further restricted | Actions, rewards, condition-safe event metadata |
| `sensitive` | Additive restriction | Content needing restricted access, minimization, and redaction controls | Chat text, prompts, rationales, model/tool content, fine-grained behavior |
| `pii` | Additive restriction | Direct or reasonably linkable personal identity data | Apart-stored external identity mapping; IP/device identifiers where intentionally retained |

The only canonical initial combinations are:

```json
["public"]
["research"]
["research", "sensitive"]
["research", "pii"]
["research", "sensitive", "pii"]
```

Labels use exactly that canonical order: base first, then `sensitive`, then
`pii`. `public` cannot coexist with a restriction label; adding either
restriction promotes the base to `research`.

`secret` is not a privacy label. Secret material is forbidden in ordinary
research storage and represented only by a declared `SecretRef` in private
deployment configuration.

Opaque IDs and digests are not automatically public. An enrollment ID can be
personal data when linked; a UUIDv7 may reveal creation time; a digest may reveal
equality or allow dictionary attack against low-entropy content.

Privacy labels form a partial order. `public < research`; absence of each
restriction is less restrictive than its presence. The join operation chooses
the stricter base and unions restriction labels, promoting to `research` if a
restriction is present. Effective labels are the join of inherited labels and
locally declared labels.

An owning domain API may assign stricter labels when context or linkage makes
them necessary. A child inherits its parent labels unless its schema declares
additional restrictions. Only an explicit, provenance-bearing transformation
that creates a new data object may lower labels; ordinary reassignment cannot.

## Retention is institutional, not a platform object

MUG records privacy labels on persisted data; it does not model retention as a
platform object. There is no retention-policy subsystem, no policy engine, and
no policy reference on the wire (ADR 0015 removed the API-20 governance
family). Retention, deletion, consent-withdrawal, and data-rights execution
are owned by the self-hosting institution and applied directly to its own
store — the researcher's database, artifact storage, and backups.

MUG's obligations are limited and mechanical:

- Every persisted object carries canonical `privacy_labels` so the institution
  can locate and classify what it retains.
- Evidence capture is append-only; corrections and ordinary availability-state
  changes append rather than rewrite. Out-of-band deletion removes data from
  the institution's store rather than altering retained canonical facts.
- MUG makes no consistency promise about rows the institution deletes
  directly; orphaned derivatives are the deployer's responsibility.

## Destination matrix

This matrix is a conservative default. A domain API further restricts it using
the compiled data flow, participant/channel membership, treatment blinding,
and data minimization.

| Destination | `["public"]` | `research` base | plus `sensitive` | plus `pii` | Secret material |
| --- | --- | --- | --- | --- | --- |
| Client manifest | Allowed if needed | Scoped references/condition-safe values only | Only participant-required presentation, never private treatment/config | Forbidden; external identity stays apart | Forbidden |
| Private server manifest | Allowed | Allowed when declared | Allowed when declared | Reference identity data stored apart | `SecretRef` only |
| Canonical event | Allowed | Allowed | Allowed when declared and minimized | Pseudonymous reference; direct PII normally separate | Forbidden |
| Artifact | Allowed | Allowed when declared | Encrypted/restricted | Protected identity artifact only when unavoidable | Forbidden |
| Replay bundle | Allowed | Allowed by bundle audience | Redacted/encrypted restricted variant | Excluded or separately protected | Forbidden |
| Receipt | Ingress receipt (empty `stream_positions`) to participants | `commit`/`artifact_commit` are trusted-audience (researcher/service) only | Audience-scoped projection for any wider delivery | Never participant-facing | Forbidden |
| Operational trace/log | Metadata only | IDs/metrics only | No raw content by default | No direct PII | Forbidden, including tokens |
| Researcher export | Allowed | Declared snapshot | Restricted/redacted with lineage | Identity data remains a separate institution-managed export | Forbidden |
| Model-provider request | Only declared content | Only declared fields | Only declared processor data and minimal prompt context | Forbidden | Credential resolved out of band |
| Tool invocation | Only declared input | Scoped minimal input | Only declared tool data | Forbidden | Credential resolved out of band |

“Allowed” never means automatically included. The compiler produces explicit
client, private server, and provenance manifests; broad serialization of Python
attributes is forbidden.

A `commit`/`artifact_commit` receipt is trusted-audience (researcher or service)
because its `stream_positions` leak stream identity and cardinality. Participant
delivery therefore uses an `ingress` receipt with empty `stream_positions`, or an
audience-scoped projection that omits them.

## Field and content separation

These references must remain distinct even when text happens to match:

- Canonical participant-authored chat content
- Normalized model generation content
- Raw provider request/response content
- Participant-visible presentation content after filtering/redaction
- Operational logs/traces

Conversation history, automated-controller decision context, and experimental
agent memory are different APIs and persistence scopes. A chat message does not
implicitly enter longitudinal memory; a prompt snapshot does not become visible
conversation history; a provider body does not become a participant message.

Blinded/private treatment, model, partner, prompt, and candidate metadata are
server/provenance data. Client-facing candidate handles and presentation order
must not reveal underlying identity through IDs, timestamps, filenames, digests,
URLs, or error behavior.

`ArtifactRef` is trusted/archival-only. Condition-linked content delivered to a
client MUST NOT expose the artifact digest or size: equality on either unblinds
treatment. The concrete blinding-safe client delivery reference is owned by
API-11 (SK-O08).

## Secret requirements and bindings

An authored study declares a logical secret requirement without a value:

```json
{
  "slot": "model-provider.primary",
  "purpose": "model-provider-credential"
}
```

A private deployment revision binds that slot using `SecretRef`:

```json
{
  "binding_id": "secret_01981c66-2f5c-7658-b3da-76dcdf5b0486",
  "resolution": "deployment-current"
}
```

The reference contains no secret value, environment-variable name, vault path,
provider account, endpoint credential, or browser-visible alias. Resolution is
a private, mechanical operation inside the server or worker boundary:

1. The runtime resolves only a secret slot declared by the pinned deployment
   revision for the requesting consumer and purpose.
2. The resolved binding revision is recorded as protected exposure/provenance;
   secret material is never recorded.
3. The runtime receives a nonserializable, short-lived in-process
   `SecretLease`.
4. The lease is held for the minimum time and cleared/revoked on cancellation
   or worker shutdown where the runtime permits.

Caching, rotation, renewal, revocation, and provider outage behavior are owned
by API-02. Credentials are not part of scientific model identity. The
deployment revision pins the logical binding by default; whether a specific
credential rotation requires a new deployment revision remains an ADR
follow-up. MUG does not add a credential-access authorization or operator-audit
subsystem around the institution's trusted deployment boundary.

## Forbidden secret destinations

A `SecretRef`, raw credential, auth token, lease token, signed URL, or resolved
secret value is forbidden from:

- Client and provenance manifests
- Canonical research events and artifacts
- Replay bundles and preference candidates
- Participant and researcher exports
- Telemetry attributes, trace baggage, logs, exception text, and error details
- Idempotency keys, resource identifiers, filenames, and fixture examples

Private deployment manifests may contain `SecretRef`; only the minimal secret
store used by API-02 holds material. CI/test fixtures use unmistakably
synthetic nonworking values.

## Error, receipt, and trace redaction

Public `DomainError.details` is allowlisted per code. It must not include raw
input that failed validation. Receipts contain stable resource/evidence
references, not participant text, provider bodies, or tool arguments unless a
domain result schema explicitly requires and classifies them.

Trace context permits `traceparent`/`tracestate`, not arbitrary baggage. Logs
use pseudonymous correlation IDs and safe enumerated state. Private diagnostics
can reference `error_id`, `command_id`, or invocation ID; a trusted operator
may correlate those references directly with the institution's protected store
without duplicating protected content in logs.

## External processors

Provider/tool calls require a compiled data-flow declaration naming:

- Processor/provider and region/residency constraints
- Data categories and fields sent
- Scientific purpose and provider data-use/training settings
- Model/tool version selector and fallback chain
- Redaction/transformation applied
- Failure, cancellation, and known provider-persistence limitations

Actual request content, resolved provider/model, usage, and response disposition
are recorded in protected provenance. A fallback is a separately recorded
exposure; it must not silently change treatment or broaden allowed data flow.

## Export and out-of-band data operations

1. A researcher export is an immutable dataset snapshot with schema,
   provenance, and lineage, not a database dump. MUG does not gate the trusted
   self-hosting researcher from exporting the data they operate.
2. Redaction, anonymization, filtering, and analysis exclusion create a new
   lineage-bearing object or projection; they do not rewrite captured evidence.
3. Withdrawal, consent revocation, identity unlinking, erasure, legal hold, and
   institutional access control are not MUG workflow or authorization objects.
   The institution performs them directly against its own stores and records
   them in its own systems when required.
4. Direct deletion can orphan events, artifact references, replay bundles,
   exports, or derived data. MUG exposes stable references and labels that make
   such consequences discoverable, but it does not promise a referentially
   complete deletion engine.
5. Physical deduplication, backup expiry, restored-backup cleanup, and copies
   already exported to other systems are institutional storage concerns. MUG
   must not imply that an out-of-band deletion immediately removes every copy.

## Required validation

- Static scans and negative fixtures reject `api_key`, `password`, `token`,
  `credential`, secret values, backend URIs, and signed URLs in forbidden schemas.
- Blinded client manifests contain no condition/model/provider/candidate linkage
  through metadata or identifiers.
- Unavailable and nonexistent protected objects are observationally equivalent
  at participant-facing boundaries.
- Error injection containing a credential, prompt, SQL text, and participant PII
  yields a public envelope containing none of them.
- A stricter derived object retains lineage without changing the source object's
  bytes/reference.
- NS-12 traces ungated researcher export, redacted-derivative lineage,
  apart-stored identity, and the limits of direct deletion and backup handling.
