# API-03: Identity, Launch, and Enrollment

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Accountable owner | Unassigned |
| Last updated | 2026-07-19 |
| Consumers | Participants (via opaque launch link), API-04 (visit materialization), API-09 (launch) |
| Depends on | [Shared kernel 0.2](../shared-kernel/index.md), [API-01 0.1](../api-01/index.md), [API-02 0.1](../api-02/index.md), proposed ADRs 0003, 0011 (data classification), 0014 (scope: identity, not recruitment) |
| Implementation phase | Phase 2 |
| Stability tiers | Application command/query, wire (launch ticket), archival |

## Outcome

API-03 owns study-scoped pseudonymous identity and nothing else at this
boundary: MUG owns identity, not recruitment (ADR-0014, decision F-2). An
`Enrollment` is a pseudonymous, study-scoped record that never carries an
account, an external panel ID, or PII; a participant reaches a study through an
opaque signed `LaunchTicket` rather than a client-supplied identity; and a
returning participant resumes via their stable pseudonymous return link.

Recruitment, invitations, reminders, panel management, targeting, and
scheduling are explicitly out of scope — recruitment platforms and the
researcher's existing tools own contact. Consent is not an API-03 concept:
it is an ordinary flow activity presented as content, with its response
recorded like any other activity response (API-17/API-04). Longitudinal
("wave") designs are just multi-part flows plus the stable return link; API-03
defines no availability windows and no wave gating.

## Ownership boundary

API-03 owns `Enrollment`, `LaunchTicket`, and the separately stored
`ExternalIdentityLink`. It does not own study science (API-01), deployment
binding (API-02), visit materialization (API-04), or activity/consent
responses (API-17/API-04). External identity values are referenced only
through blinded `PublicHandle`s and are kept apart in the researcher-controlled
store.

## Contract summary

- **`Enrollment`** — study-scoped pseudonymous identity; `principal` must be a
  `participant`; the record structurally excludes account/external/PII fields.
- **`LaunchTicket`** — an opaque, expiring, participant-safe launch handle that
  binds study and deployment revision without exposing any principal.
- **`ExternalIdentityLink`** — the only external-identity reference, held as a
  blinded handle, classified `pii`, and stored apart from research data.

## Non-negotiable identity boundary

1. Direct identity is separated from study-scoped research identity; an
   `Enrollment` carries neither account nor external subject.
2. A `LaunchTicket` is opaque and reveals no principal, account, or external
   identity to a browser.
3. External identity appears only in `ExternalIdentityLink`, as a blinded
   handle classified `pii`, kept apart in the researcher-controlled store.
4. A returning participant resumes the same `Enrollment` via a stable
   pseudonymous return link; re-entry never mints a second research identity.

## Current executable evidence

- 3 valid examples (enrollment, launch ticket, external link) and 4 one-defect
  invalid examples (non-participant researcher principal, PII field on enrollment, principal
  embedded in a launch ticket, missing PII classification).
- 10 API-03 tests (7 fixture cases plus schema-validity, manifest-completeness,
  and bundle-digest-binding checks). The focused architecture suite passes.

## Acceptance status

API-03 is `Drafted`, not `Accepted`. See the [review record](review-record.md).
Highest-priority remaining work: exact command payload/result schemas for
enroll/launch; signed launch cryptography and stable-return-link re-entry; the
API-04 eligibility boundary; and NS-08/NS-12 walkthroughs.
