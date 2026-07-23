# API-01 Conformance Plan

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Owner | API-01 owner and contract-test maintainers |
| Last updated | 2026-07-20 |

## Validation layers

| Layer | Required proof |
| --- | --- |
| Strict parser | Duplicate keys, unsafe integers, nonfinite values, and lone surrogates are rejected before schema validation |
| JSON Schema | Exact versions, closed unions, bounds, conditionals (including dirty-implies-patch), and unknown-field rejection pass Draft 2020-12 offline |
| Typed object | Every `TypedObject` name/version/digest resolves from the allowlist and its `data` passes the exact domain schema |
| Definitions and flow | Definition kind/ID/key uniqueness and prefixes, activity references, flow reachability, cycle/terminal rules, and randomization bounds hold |
| Git provenance | Dirty provenance carries a patch, clean provenance carries none, and an identity-encoded patch artifact matches the declared patch digest and size |
| Privacy and partition | Secret values/refs and private identities are absent from forbidden representations; only the selected client projection is deliverable |
| Manifest closure | Role/schema/digest/size/artifact links, the scientific projection references, and the published version's manifest digest close over the exact canonical bytes with no digest cycle |
| Publication | Every transitive schema is positive/accepted, artifacts remain finalized/readable and digest-verified, warnings are bound to the candidate, the version string is well-formed, and no mutable input remains |
| Stateful/fault | Git capture, jobs, and publication satisfy optimistic concurrency, idempotency, version-string reservation, atomicity, crash, reconnect, and retry rules |

The 34-test
[`test_api01_contract_fixtures.py`](../../../../tests/architecture/test_api01_contract_fixtures.py)
suite currently implements the first seven layers for the synthetic v0 slice,
rejects the retired `plugin.*` capability namespace and server binding kind,
and proves that publication scanning rejects proposal-only schemas. It resolves
both API-01 and shared-kernel schemas from an offline registry and validates
that the fixture manifest is complete.

## Required deterministic build tests

For each retained reference study:

1. Capture the same commit + patch twice in clean, declared build environments.
2. Normalize twice with the same exact schema and artifact registry plus the
   same closed set of MUG-owned capabilities.
3. Compile twice under the same content-bound `CompilationInputs`.
4. Compare canonical bytes and digests for authoring, scientific, every client
   audience, server, provenance, schema bundle, package lock, and report.
5. Permute harmless Python construction order, filesystem enumeration order,
   locale, timezone, process ID, username, hostname, and worker assignment.
6. Assert no byte changes. A mismatch yields
   `compiler.nondeterministic_output`, quarantines that compiler build, and
   makes neither candidate publishable.

Validation, diff, dependency discovery, and compilation must leave source and
patch bytes unchanged and never sample a randomization rule. A clean build may
read only the captured commit + patch and declared inputs and may
not resolve a secret, contact a provider, or fetch an unpinned network
resource.

## Required stateful and fault cases

| Case | Assertion |
| --- | --- |
| Publish from clean HEAD | Provenance records commit, `dirty=false`, no patch |
| Publish from dirty tree | Provenance records commit + stored patch; commit + patch reconstructs the compiled source |
| Unresolvable commit or failed patch capture | `git.provenance_unavailable` / `git.patch_capture_failed`; no platform state |
| Same publish command after lost reply | Original receipt; no second version/event |
| Identical content, existing string, new command key | One version and `published` event; explicit reuse fact/receipt resolves to it |
| Identical content under a new string | `publication.content_already_published`; no version, ordinal, or reservation |
| New content under a used string | `publication.version_string_reserved`; no mutation |
| Concurrent publications racing one string | Study lock serializes; exactly one reservation wins |
| Definition-key reuse incompatible with published history | `definition.key_incompatible_reuse` at publish; no version |
| Duplicate compile work key | One API-22 job/result |
| Compiler crash/cancellation | No fabricated invalid candidate; safe job retry/status |
| Equal compile inputs, unequal output | Compiler quarantine; neither candidate publishable |
| Archive during compile | Job may finish; publication rejects current study state |
| Artifact or patch loss before publish | No partial version or accepted commit receipt |
| Two different concurrent publications | Study lock serializes distinct display ordinals |
| Crash before/after publication commit | No visible version or string reservation, or original receipt on retry, respectively |
| Resolved diff after dependency bump | `diff_versions` reports the behavior change despite zero source diff |
| Fork failure | No partial destination study or copied participant/deployment state |
| Withdraw version | No new deployment when policy forbids; historical bytes and stored artifact remain readable |

Fault injection must cover the shared Unit-of-Work and artifact-finalization
points, including the stored patch artifact. API-01 cannot be accepted until
API-11 and API-22 define the concrete ports needed to execute these cases.

## Required future north-star and parity coverage

These are promotion targets, not claims about the current synthetic version-0
fixture set. Today the executable harness proves only the minimal static slice
described above. Each item becomes an executable conformance case after the
owning domain API publishes exact schemas and API-01 composes them.

- NS-01/NS-02 must prove that generic preference protocols, replay/output
  artifacts, blinded client projections, and offline closure compile before
  recruitment.
- NS-03 through NS-07 must prove that exact actor/channel/controller/provider/
  tool requirements compile without revealing private prompt/model/treatment
  configuration.
- NS-08 must prove that an intentional later version under a new hand-typed
  version string and stable definition lineage publish and that runtime
  recovery consumes an already-materialized plan rather than source.
- Current-parity ports must prove that static/form/randomized flow,
  browser-local controllers, P2P, server authority, independent concurrent
  game instances, connection probe/re-pooling, renderer surfaces, external
  clients, evidence capture, and administration compile through typed
  domain-owned schemas and immutable packages.

## Promotion gate

Version 1 requires all v0 fixtures and semantic validators in Python and the
browser, deterministic build vectors, stateful/fault tests for available ports,
accepted dependent ADRs (including ADRs 0013 and 0015), scenario walkthroughs,
four named review sign-offs, and review of the exact promoted bytes.
Publication and deployment tests must then prove every version-0 closure is
rejected.
