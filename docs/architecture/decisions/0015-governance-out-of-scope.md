# ADR 0015: Governance Is Out of Scope

| Field | Value |
| --- | --- |
| Status | Accepted |
| Accepted | 2026-07-20 (ratification; governance out of scope — API-20 removed, API-21 retracted for v0; already executed across the corpus) |
| Date | 2026-07-18 |
| Owners | Unassigned |
| Supersedes | ADR 0011 in part (the API-20 governance layer); classification and secret references stand |
| Superseded by | None |
| Affects | All API families; removes API-20, retracts API-21 for v0 |

## Context

The draft contracts routed authority through an API-20 governance family:
RBAC/ABAC grants, admin audit trails, a retention engine, deletion/data-rights
workflows, and processor governance, with cross-family requirements phrased as
"authorized by an API-20 grant." MUG is a self-hosted research tool, usually
run by one lab that owns the database and infrastructure. A permission-and-
compliance platform duplicates what the institution and hosting environment
already provide and taxes every other surface with authorization ceremony
(review decision F-4).

## Decision

MUG implements no governance layer.

- No authorization, roles, permissions, or grants. Whoever operates a MUG
  deployment can do everything; any author/operator split is social convention.
- No admin audit trail.
- No retention schedules or retention engine.
- No deletion, consent-withdrawal, or data-rights workflows. "Delete my data"
  and re-identification requests are handled by the researcher directly against
  their own store, using the enrollment handle and the apart-stored external
  link (ADR 0014).
- **API-20 is removed as a family.** Every cross-family requirement previously
  phrased as "authorized by an API-20 grant" becomes "ungated in a self-hosted
  deployment." Deprecate/withdraw is author-callable; export is ungated.

Access control, IRB/compliance, retention, and deletion are owned by the
researcher's institution and infrastructure: their database, their processes.
MUG's obligation is to not get in the way — data lives in a store the
researcher controls and can query, export, or delete directly.

Two things previously bundled into API-20 are deliberately retained elsewhere
because they are not governance:

- **Immutable event capture for reproducibility** stays in API-10. It is the
  evidence substrate that makes replay and export trustworthy; it is not an
  admin audit trail.
- **Minimal secret storage and reference** stays in API-02 and the shared
  kernel. Secrets are bound by reference at deploy time and never appear in the
  client or the scientific record (ADR 0007, ADR 0011). Only the governance,
  audit, and rotation-authority machinery around secrets is cut.

Additionally, **API-21's plugin framework is retracted for v0**: no
`PluginManifest`, capability negotiation, trust classes, sandboxing, or
sharing/distribution. Closed vocabularies stay closed in v0. If extension
points arrive post-v0, the recorded direction is plain Python against typed
protocols — no framework, no distribution channel.

## Scope and non-goals

This decision removes the governance family and the plugin framework; it does
not weaken any security mechanism. Data classification, privacy labels,
manifest partitioning, and `SecretRef` handling (ADR 0007, ADR 0011) stand as
security mechanisms without a policy engine above them. This ADR does not claim
MUG satisfies any regulatory regime; compliance is explicitly the deployer's.

## Invariants

- No MUG API requires or evaluates a grant, role, or permission.
- Evidence capture (API-10) remains immutable and complete regardless of the
  absence of an audit subsystem.
- Secret material still never enters clients, manifests, evidence, exports, or
  the scientific record; `SecretRef` binding at deploy is unchanged.
- Availability transitions (deprecate/withdraw) remain append-only and never
  delete data; deletion happens outside MUG, in the researcher's store.
- v0 ships no extension points; every closed set is closed.

## Consequences

### Positive

- An entire family (API-20) and its coupling into storage, export, replay,
  provider, and deletion paths disappear.
- Every other surface loses authorization ceremony; deploy, export, and
  deprecate are single ungated calls.
- API-21 machinery (manifests, negotiation, sandboxing, distribution) is cut
  from v0 scope.

### Costs and constraints

- Multi-tenant or hosted-service deployments are out of scope; MUG assumes the
  operator is trusted with everything.
- Institutions wanting enforced separation of duties must impose it at the
  infrastructure layer (network, database credentials), not in MUG.
- Data-rights execution (erasure, export limitation reporting) has no MUG
  tooling; correctness is the researcher's responsibility.
- Extensibility beyond authored Python (envs, policies, renderers, tools) waits
  for post-v0.

### Failure consequences

- A compromised or careless operator can read or destroy anything; there is no
  MUG-level containment or audit trail to detect it. This is accepted as the
  self-hosted trust model.
- Deleting rows directly in the researcher's store can orphan derived
  artifacts; MUG makes no consistency promise about out-of-band deletion.

## Security and privacy

Security mechanisms survive; governance policy does not. The trust boundary
moves wholly to the deployment perimeter: whoever can reach the MUG deployment
and its store is trusted. Classification labels (ADR 0011) continue to drive
manifest partitioning, blinding, and export hygiene mechanically, with no
policy-evaluation layer. Secret resolution remains fail-closed and by
reference.

## API and schema impact

- API-20 schemas, commands, and identifiers are removed from the contract set
  and shared identifier registry.
- API-21 plugin schemas are removed for v0; only a recorded post-v0 direction
  (typed extension protocols) remains.
- ADR 0007's deployment-private secret overlay is owned by API-02 alone.
- All cross-family "API-20 grant" preconditions are rewritten as ungated; the
  affected contract texts are updated at fold time.
- ADR 0011's retention/deletion/consent follow-ups assigned to API-20 are
  closed as out of scope.

## Alternatives considered

### Build RBAC/ABAC, audit, and retention as drafted

Rejected because it is a large subsystem duplicating institutional and
infrastructure controls, serving no approved user journey for a self-hosted,
single-lab tool.

### Ship a minimal roles system (author versus operator only)

Rejected because even two enforced roles require grants, checks, and audit to
be meaningful; the common case is one person, and teams can split duties by
convention or infrastructure.

### Keep API-20 but mark it optional

Rejected because optional authorization still forces every family to carry
grant-aware contract text and test matrices for both modes.

### Keep the plugin framework but restrict it to trusted code

Rejected because the framework's cost is its manifests, negotiation, and
distribution machinery, not its trust policy; v0 needs none of it.

## Validation

- Contract-text sweep: no remaining "API-20", grant, role, or permission
  preconditions in any family.
- Evidence capture and export still pass NS-scenario walkthroughs with no
  authorization layer present.
- Secret-hygiene scans (ADR 0007/0011 validation) pass unchanged, proving the
  security mechanisms do not depend on the removed governance layer.
- v0 surface audit: no extension-point or plugin schema is reachable.

## Follow-up decisions

- Deployment-hardening guidance (database credentials, network perimeter) as
  documentation, not enforcement — docs owner
- Post-v0 revisit trigger for typed extension protocols — API-21 owner
- Whether any minimal operational logging (distinct from audit) ships in v0 —
  API-22 owner

### Resolved 2026-07-20 (accountable-owner)

- **Minimal operational logging ships in v0** — server health, errors, and
  request traces, explicitly distinct from participant/audit evidence; owned by
  API-22 (not a governance/audit subsystem).
- Deployment-hardening guidance (docs, not enforcement) and the post-v0
  extension-protocol revisit trigger remain routed to their gates.
