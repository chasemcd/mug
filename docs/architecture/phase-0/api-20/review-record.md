# API-20 Review Record

| Field | Value |
| --- | --- |
| Status | Removed (out of scope) |
| Review opened | 2026-07-17 |
| Review closed | 2026-07-18 |
| Outcome | Family removed under foundational decision F-4 (ADR-0015) |

## Decision

The phase-0 user-surface review (surface 14) concluded that **governance is out of
scope for MUG** (foundational decision F-4). MUG is self-hosted; the researcher and
their institution own access control, IRB/compliance, retention, and deletion. The
drafted API-20 contract — `AuthorizationGrant`, `AuditRecord`, `RetentionSchedule`,
`DeletionRequest`, `SecretProviderBinding` — is removed, along with its v0 schemas,
fixtures, and contract-fixture tests.

Two drafted concerns were deliberately re-homed because they are not governance:
immutable event capture for reproducibility (→ API-10) and minimal secret
storage/reference (→ API-02 and the shared kernel). See the
[tombstone index](index.md) for the full resolution table.

## Change log

| Date | Revision | Change |
| --- | --- | --- |
| 2026-07-17 | `0.1` | Opened API-20: authorization-grant, audit-record, retention-schedule, deletion-request, secret-provider-binding schemas, deletion reconciliation, secret boundary, 10 fixtures, 14 tests |
| 2026-07-18 | — | **Removed** under F-4 (ADR-0015): schemas, fixtures, and tests deleted; index rewritten as a tombstone; event capture re-homed to API-10 and secret storage to API-02/shared kernel |
