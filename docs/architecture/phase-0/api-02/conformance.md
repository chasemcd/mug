# API-02 Conformance Plan

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Owner | API-02 owner and contract-test maintainers |
| Last updated | 2026-07-19 |

The executable layers below target the 0.2 schema bundle: the two-verb,
ungated surface (D03-1, D03-5; ADR-0015) with its internal revision, report,
and disposition records.

## Validation layers

| Layer | Required proof |
| --- | --- |
| Strict parser | Duplicate keys, unsafe integers, nonfinite values, and lone surrogates are rejected before schema validation |
| JSON Schema | Exact versions, closed objects, enums, patterns, and bounds pass Draft 2020-12 offline against the shared-kernel and API-02 registry |
| Semantic — revision | No secret material at any depth; provider bindings resolve to a secret binding; secret-binding keys and execution slots are unique |
| Semantic — report | `satisfied` holds if and only if the secret, execution, and region gap lists are all empty |
| Semantic — deployment | The live/stopped aggregate's `current_revision` belongs to the same deployment |
| Satisfaction closure | The valid revision covers the valid requirement's secret/execution/region relation and pins the exact `requirement_digest` |
| Projection closure | The client projection closes over the exact revision bytes and exposes only the revision's participant endpoints |
| Disposition pinning | Live and stopped dispositions pin the identical revision bytes (`mug stop` rebinds nothing) |
| Digest binding | Every API-bundle schema ref embeds the current bundle digest |

[`test_api02_contract_fixtures.py`](../../../../tests/architecture/test_api02_contract_fixtures.py)
implements all of the above for the synthetic v0 slice: 20 fixture cases plus
six suite-level tests (schema validity/offline refs, manifest completeness,
bundle-digest binding, satisfaction closure, projection closure, and
disposition pinning).

## Required stateful and fault cases

These are promotion targets; they become executable once API-11 and API-22
define artifact-staging and build-job ports.

| Case | Assertion |
| --- | --- |
| Duplicate revision-create after lost reply | Original receipt; no second revision |
| Two revision-creates against one deployment head | One commit; one head conflict |
| Revision fails satisfaction | Rejected with a plain diagnostic before anything is live; no revision recorded |
| Crash before/after revision commit | No partial revision, or original receipt on retry |
| Build artifact loss before commit | No accepted revision receipt |
| Secret rotation via redeploy (`Resolution.CURRENT`) | Bound identity change forces a new revision; a pure rotation does not |
| Visit pinned across restart/redeploy/stop | Recovery reloads the pinned revision, never rebinds to current (NS-08) |
| `mug stop` | Live/stopped disposition appended; historical revision bytes remain readable; `mug deploy` brings the study back |

## Promotion gate

Version 1 requires
all fixtures and semantic validators in Python and the browser, satisfaction
and projection closure vectors, stateful/fault tests for available ports,
accepted dependent ADRs (0003, 0007, 0011, 0013, 0015), NS-08 and NS-12
walkthroughs, four named review sign-offs, and review of the exact promoted
bytes. Secret storage is owned by API-02 itself and deployment is ungated
(self-hosted; ADR-0015) — no external secret-store or authority boundary gates
promotion. Publication
and deployment tests must then prove every version-0 closure is rejected and no
secret material or `SecretRef` can reach a client projection.
