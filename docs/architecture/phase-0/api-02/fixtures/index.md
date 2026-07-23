# API-02 Golden Fixtures

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Last updated | 2026-07-19 |

These fixtures exercise the two-verb 0.2 surface (D03-1, D03-5; ADR-0015).

The machine-readable [version-0 fixture manifest](v0/manifest.json) binds every
case to an exact schema fragment, validation layer, expected result, keyword,
and JSON Pointer. Every invalid case has one intended defect.

## Valid draft cases

- [Composed deployment requirement](v0/valid/deployment-requirement.minimal-static.json)
- [Satisfying deployment revision, `Resolution.CURRENT` default](v0/valid/deployment-revision.minimal-static.json)
- [Localhost dev-machine revision, `Resolution.PINNED` opt-in (R-20)](v0/valid/deployment-revision.localhost-dev.json)
- [Participant-safe client deployment projection](v0/valid/client-deployment.minimal-static.json)
- [Satisfied satisfaction report](v0/valid/satisfaction-report.minimal-static.json)
- [Unsatisfied satisfaction report (deploy-error surface; no revision recorded)](v0/valid/satisfaction-report.unsatisfied-static.json)
- [Live deployment disposition](v0/valid/deployment.live-static.json)
- [Stopped deployment disposition pinning the same revision](v0/valid/deployment.stopped-static.json)

The revision pins the requirement's exact bytes; the projection, satisfied
report, and both dispositions close over the revision's exact bytes.

## Invalid cases

- [Deployment requirement embeds secret material](v0/invalid/deployment-requirement.inline-secret.json)
- [Deployment requirement carries 0.1 grant coupling](v0/invalid/deployment-requirement.grant-coupling.json)
- [Revision carries 0.1 `capability_grants`](v0/invalid/deployment-revision.capability-grants.json)
- [Provider binding references an unbound secret key](v0/invalid/deployment-revision.dangling-provider-secret.json)
- [Duplicate secret binding key](v0/invalid/deployment-revision.duplicate-secret-key.json)
- [`binding_revision` on a `deployment-current` secret ref](v0/invalid/deployment-revision.unpinned-binding-revision.json)
- [Client projection exposes an internal endpoint](v0/invalid/client-deployment.operator-endpoint.json)
- [Client projection leaks a secret reference](v0/invalid/client-deployment.secret-field.json)
- [Satisfaction verdict contradicts its gap lists](v0/invalid/satisfaction-report.inconsistent.json)
- [Report carries 0.1 `capability_gaps`](v0/invalid/satisfaction-report.capability-gaps.json)
- [Retired five-op disposition (`suspended`)](v0/invalid/deployment.retired-disposition.json)
- [Deployment pins a revision of another deployment](v0/invalid/deployment.mismatched-revision.json)

Fixture values are synthetic. They contain no usable credential, endpoint,
participant data, or production identifier.
