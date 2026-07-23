# API-03 Review Record

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Review opened | 2026-07-17 |
| Accountable owner | Unassigned |
| Target accepted version | `1` |

## Scope reduction folded at `0.2`

Foundational decision **F-2** (MUG owns identity, not recruitment; source:
`scratch/phase0-review/DECISIONS.md`, F-2 and D04-1..D04-4; recorded as
ADR-0014) was folded into this contract:

- **Removed `ConsentRecord`.** Consent is an ordinary flow activity — presented
  as content, its response recorded like any other activity response
  (API-17/API-04). No consent-scope gating machinery remains in API-03 (D04-3).
- **Removed `WaveSpec` and all wave concepts.** Longitudinal designs are
  multi-part flows plus a stable return link; no availability windows, no wave
  gating. `LaunchTicket` no longer binds a wave; `Enrollment` no longer tracks
  a current wave (D04-4).
- **Removed invitation/targeting/scheduling concepts.** Recruitment platforms
  own contact; the deploy URL is the whole surface (D04-2).
- **Kept** `Enrollment` (pseudonymous, study-scoped, participant principal
  only), `LaunchTicket` (opaque, expiring, binds study + deployment revision),
  and `ExternalIdentityLink` (blinded handle, classified `pii`, kept apart in
  the researcher-controlled store) (D04-1), plus stable-return-link re-entry.

## Deliverable status

| Deliverable | Status | Evidence |
| --- | --- | --- |
| Ownership, identity separation, lifecycles | Drafted | [Index](index.md) |
| Version-0 schemas | Drafted | `identity-enrollment.schema.json` |
| Golden fixtures and harness | Drafted | 7 fixtures, 10 tests |
| Scenario/parity trace | Partial | NS-08/NS-12 obligations mapped; walkthroughs open |
| Version-1 immutable contract | Not started | Blocked by decisions and reviews |

## Checklist

- [x] Enrollment is pseudonymous and structurally excludes account/external/PII
- [x] Launch ticket is opaque, principal-free, and wave-free (binds study + deployment revision only)
- [x] External identity is a blinded, `pii`-classified, separately stored handle
- [x] Consent machinery removed; consent handled as an ordinary flow activity (F-2/D04-3)
- [x] Wave machinery removed; longitudinal return is a stable per-participant link (F-2/D04-4)
- [x] Version-0 schemas, fixtures, and semantic harness pass
- [ ] Exact command payload/result schemas for enroll/launch
- [ ] Stable-return-link issuance, recognition, and re-entry semantics specified
- [ ] API-04 eligibility and re-entry compatibility reviewed
- [ ] Signed-launch cryptography, expiry, and replay defense accepted
- [ ] NS-08 and NS-12 walkthroughs pass
- [ ] Dependent ADRs (0003, 0011, 0014) accepted; four sign-offs; version-1 bytes frozen

## Open decision log

| ID | Decision needed | Proposed default | Blocks |
| --- | --- | --- | --- |
| A03-O02 | Signed launch token format and re-entry | Short-lived signed ticket bound to study/deployment; re-entry via the stable return link mints a new ticket for the same enrollment | API-09 review |
| A03-O04 | External-identity linkage and unlink | Blinded handle kept apart in the researcher-controlled store; unlink/deletion handled by the researcher against their own store | Security/privacy review |
| A03-O05 | Eligibility predicate ownership | API-03 declares eligibility inputs; API-04 evaluates them at visit materialization | API-04 review |

Closed at `0.2`: A03-O01 (account/auth-session model — no accounts; the link is
the entire entry) and A03-O03 (consent evolution across waves — consent is a
flow activity in the immutable study version; waves removed).

## Required sign-off

| Review | Reviewer | Decision | Date | Focus |
| --- | --- | --- | --- | --- |
| Domain/scientific validity | Unassigned | Pending | — | Identity separation, longitudinal return semantics |
| Runtime/distributed systems | Unassigned | Pending | — | Enrollment concurrency, launch re-entry, idempotency |
| Data/replay | Unassigned | Pending | — | Schemas, pseudonymity, archival readability |
| Security/privacy | Unassigned | Pending | — | PII isolation, launch opacity, return-link safety |

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-03: identity separation, enrollment/consent/wave/launch/external-link schemas, 11 fixtures, 15 tests |
| 2026-07-18 | `0.2` | Folded F-2 (DECISIONS.md F-2, D04-1..D04-4; ADR-0014): removed `ConsentRecord`, `WaveSpec`, and all wave/invitation concepts; removed wave binding from `LaunchTicket` and `Enrollment`; dropped `invited`/`consented` enrollment statuses (enrollment is automatic on arrival; consent state lives in activity responses); removed API-20 coupling (governance retracted by F-4); 7 fixtures, 10 tests; digests restamped |
| 2026-07-19 | `0.2` | Shared-kernel 0.2 conformance: removed `retention_policy` from the `ExternalIdentityLink` fixtures' `data_handling` blocks (kernel `DataHandlingRef` now carries `privacy_labels` only; `RetentionPolicyRef` retired); replaced the retired `account`-principal invalid fixture with a `researcher` (non-participant) principal defect; schema bytes and family digest unchanged; 7 fixtures, 10 tests |
