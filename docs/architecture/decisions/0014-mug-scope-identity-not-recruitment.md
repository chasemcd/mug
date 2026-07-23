# ADR 0014: MUG Owns Participant Identity, Not Recruitment

| Field | Value |
| --- | --- |
| Status | Accepted |
| Accepted | 2026-07-20 (ratification; identity-not-recruitment folded in API-03; per-family freeze separate) |
| Date | 2026-07-18 |
| Owners | Unassigned |
| Supersedes | None |
| Superseded by | None |
| Affects | API-03, API-04, API-09, API-17 |

## Context

The API-03 draft grew recruitment-shaped machinery: a `ConsentRecord` subsystem,
`WaveSpec` scheduling, and invitation/targeting concepts. Researchers already
recruit, remind, and pay participants through Prolific, MTurk, email, and
institutional channels. Duplicating those tools makes MUG a panel manager it
does not need to be, while the one guarantee only MUG can provide —
pseudonymous, study-scoped identity kept apart from external identity — risks
being diluted (review decision F-2, D04-1 through D04-4).

## Decision

MUG owns pseudonymous participant identity and nothing else at this boundary.

- Every arriving participant receives an opaque, expiring `LaunchTicket` that
  resolves to a pseudonymous, study-scoped `Enrollment` structurally unable to
  hold account, panel, or PII data.
- An external identifier arriving with the launch (for example a Prolific ID in
  the URL) is captured once as a blinded `ExternalIdentityLink`, classified PII,
  and stored apart from research data. It is never joined into the research
  dataset by default; its only runtime use is an optional completion redirect.
- Each enrollment has a stable per-participant **return link**. Following it
  resolves the existing enrollment and routes to the participant's next part.
- **Consent is an ordinary flow activity** (`Content`/`Form`) in the versioned
  study. Its response is recorded like any other activity response. There is no
  `ConsentRecord` subsystem and no scope-gating engine; conditional consent
  logic is an ordinary flow branch, and the exact consent text a participant saw
  is fixed by the immutable study version.
- **Longitudinal waves are multi-part flows plus the stable return link.**
  There is no `WaveSpec`, no wave window, no targeting, and no scheduler.

MUG does not recruit: no invitations, no emails or reminders, no panel
management or scheduling, no wave orchestration, no payment. The deploy URL is
the entire recruitment surface; the researcher distributes it with their own
tools. Recruitment platforms remain the system of record for participant
contact.

## Scope and non-goals

This decision fixes the API-03 scope boundary. It does not decide launch-ticket
cryptography, connection fencing, or channel authorization (ADR 0002, ADR 0010),
and it does not decide data-rights handling for enrollments (ADR 0015: not a
MUG feature). It does not preclude a post-v0 completion-code convention richer
than a redirect.

## Invariants

- An `Enrollment` carries no external identity, account, panel, or PII fields.
- External identifiers exist only as blinded links stored apart from research
  data and never enter exports by default.
- The same person following their return link resolves to the same enrollment;
  MUG never merges or re-identifies enrollments on its own.
- Consent evidence is an activity response bound to the immutable study version
  that presented it.
- No MUG component sends outbound participant communication.

## Consequences

### Positive

- API-03 sheds consent, wave, and invitation subsystems while keeping the
  identity guarantees only MUG can provide.
- Identity leakage into datasets is structurally prevented at zero author
  effort.
- Longitudinal studies work with almost no platform machinery: author a
  multi-part flow, export the return links, send them however you like.

### Costs and constraints

- Re-contact logistics (who to remind, when) are entirely the researcher's.
- There is no built-in consent-scope concept; studies needing conditional
  consent logic express it as flow branches.
- Panel integration is limited to opaque ID capture and completion redirect.

### Failure consequences

- A lost return link is a dead end: the participant is directed to contact the
  researcher; there is no automated re-entry or account recovery.
- If a recruitment platform recycles or misreports an external ID, MUG still
  keeps enrollments distinct; reconciliation is the researcher's task in their
  own store.

## Security and privacy

The enrollment/external-link separation is the load-bearing privacy control:
research data is keyed by pseudonymous enrollment only, and the PII-classified
link table is the sole join point, held apart under ADR 0011 classification.
Identity and condition are server-derived; the client and URL are never trusted
for them.

## API and schema impact

- API-03 drops `ConsentRecord`, `WaveSpec`, and all invitation/targeting/
  scheduling schemas; it keeps `Enrollment`, `LaunchTicket`, and
  `ExternalIdentityLink`, plus the stable return-link resolution.
- API-17 gains nothing: consent uses the existing `Content`/`Form` activity
  types and response recording.
- API-04 routes returning enrollments to the next part using the materialized
  plan (ADR 0003); no new wave concepts.

## Alternatives considered

### Build consent as a dedicated subsystem with scopes and gating

Rejected because a versioned flow activity already gives reproducible consent
text, recorded responses, and branchable logic without a parallel engine.

### Manage waves, invitations, and reminders in MUG

Rejected because it duplicates recruitment platforms and email, drags contact
PII into MUG, and adds a scheduler with no research-evidence payoff.

### Treat the external panel ID as the participant key

Rejected because it makes a third party's identifier the research key, breaks
pseudonymity, and couples data integrity to panel ID hygiene.

## Validation

- Schema-level proof that `Enrollment` cannot carry external identity or PII.
- Launch with and without an external ID in the URL; both work with zero
  configuration and the ID never appears in research exports.
- Consent presented, recorded, and branch-on-response as an ordinary activity;
  the consent text is recoverable from the study version.
- Multi-part flow: complete part one, return via the stable link, verify same
  enrollment, same pinned version, correct next part (NS-08).

## Follow-up decisions

- Whether routing to "the right part" needs named parts/checkpoints or flow
  position suffices — API-03/API-04 owners
- Completion redirect/code shape for panel round-trips in v0 — API-03 owner

### Resolved 2026-07-20 (accountable-owner)

- **Routing granularity:** the participant's recorded flow position in the
  materialized visit plan suffices; no separate named-checkpoint concept.
- Completion redirect/code shape remains routed to the API-03 gate.
