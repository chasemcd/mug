# API-02 Deployment and Secrets Contract

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Owner | Unassigned |
| Last updated | 2026-07-19 |

This document defines how API-02 takes an immutable `StudyVersion` live in one
call, proves that the binding satisfies the study's declared deployment
requirement, isolates secrets, pins in-flight visits, and delivers a
participant-safe projection.

## Operator surface

Two verbs, ungated (self-hosted; ADR-0015). No role split, no grant check, no
revision ceremony (D03-1, D03-5).

| Verb | Effect |
| --- | --- |
| `mug deploy study@version --at URL --secret key=$VAL` | One call: **publishes implicitly** when `version` is unused (R-21 — compiles the current git state under that string; byte-identical re-deploys idempotent; changed content under a used string is a plain error per the D02-3 collision rules), records an immutable `DeploymentRevision`, stores passed secrets by reference, verifies needs are met, goes live. Also the verb for rewiring, key rotation, and bringing a stopped study back. |
| `mug deploy study` (no `@version`) | **Dev preview** (R-21): serves the current working tree at localhost only; no version is minted; collected data is marked preview/non-citable; a non-localhost `--at` is refused. |
| `mug stop study` | Takes the study down: no new participants. In-flight visits finish on their pinned revision. Deletes nothing. |

An unsatisfiable deploy fails before going live with a plain diagnostic
(missing secret, disallowed region, unbound execution slot) — not a report
object the operator queries. There is no suspend/resume/retire vocabulary:
"stopped" means "not live," and `deploy` brings it back.

## Process model (settled 2026-07-19, R-20 — one typical run path)

MUG runs like a typical self-hosted web app (the Deliberate-Lab shape: one
command starts everything; "production" is the same app on real hosting).
There is **no remote deployment protocol, no operator API, and no artifact
push**:

- **One machine hosts the study** — a laptop for development, a lab box/VM for
  collection. The study source reaches that machine the normal way: `git
  clone`/`pull` (the same repo that F-1 versions).
- `mug deploy study@version --secret key=$VAL` is executed **on that
  machine**: it ensures the local MUG server process is running (starting it
  if not — web server, durable store, workers in one process group), records
  the `DeploymentRevision` in the machine's local store, runs satisfaction,
  and serves. `mug stop` on the same machine takes it down.
- `--at URL` declares the **public base URL** the deployment presents (used
  for participant links and completion redirects; defaults to
  `http://localhost:<port>`). It is not a remote target: reachability — DNS,
  TLS, reverse proxy, ports — is the researcher's hosting, exactly like any
  web app (ADR-0015 scope; MUG provisions nothing).
- The deployed version lives in the machine's local store — and `mug deploy`
  **publishes it implicitly** when the string is unused (R-21). Publication is
  idempotent by content (ADR-0013), so the same commit under the same version
  string yields the identical version and digests on any machine: after
  `git pull`, one `mug deploy study@1.0` on the host does everything.
- Dev and production are the **same path**: the same commands on a different
  machine. The machine's durable store is what makes in-flight pinning survive
  restart and redeploy (NS-08).

## Vocabulary and owned state

| Term | Meaning | Identity |
| --- | --- | --- |
| Deployment | Stable operational launch identity for one study | `deploy_…` |
| Deployment revision | Immutable internal record of one deploy: study version + exact builds, region, endpoints, and secret refs. Created by `mug deploy`; never operator-managed | `deployrev_…` |
| Deployment requirement | The typed capability/secret/execution contract a study version demands, authored in API-01 and owned here | schema `mug.api-02.deployment-requirement` |
| Secret binding | Mapping of a logical secret requirement key to a shared-kernel `SecretRef`; value stored by API-02, held by reference only | `secret_…` via `SecretRef.binding_id` |
| Satisfaction report | Immutable proof a revision covers a pinned requirement (internal; surfaced only as a deploy error) | schema `mug.api-02.satisfaction-report` |
| Client deployment projection | Participant-safe delivery view | schema `mug.api-02.client-deployment` |

The `Deployment` aggregate owns an append-only sequence of immutable
`DeploymentRevision` records plus a live/stopped disposition. Dispositions are
append-only and never rewrite revision bytes. The revision history exists for
in-flight pinning, provenance, and rollback — it is a guarantee (D03-4), not a
surface.

## Deployment requirement composition

API-01's `ScientificManifest.deployment_requirements` is a `TypedObject` whose
`schema` is `mug.api-02.deployment-requirement` and whose `data` is a
`DeploymentRequirementData`:

- `secret_requirements` — logical secret keys with a purpose and an `optional`
  flag. No secret material and no `SecretRef` appear here; the study declares a
  *need*, not a binding (D01-6).
- `execution_slots` — server/browser/worker slots. Every slot must receive a
  build binding at deploy time.
- `provider_adapters` — logical model/tool adapter needs.
- `region_policy` — allowed regions and residency (`flexible` or `pinned`).

API-01 composes this object and pins its bytes; API-02 owns its exact schema.
Until API-02 is Accepted, API-01 keeps a fixture placeholder rather than binding
the real schema (open decision A01-O14).

## Requirement satisfaction

A deploy goes live only if it satisfies the study version's requirement. The
satisfaction relation, proven internally by `SatisfactionReport`, is:

1. **Secret completeness:** every non-optional `secret_requirements` key has a
   matching `secret_bindings` entry (from `--secret` / passed values). A missing
   binding is an `unbound_secret_requirements` entry.
2. **Execution coverage:** every `execution_slots` `(slot, runtime)` has a
   matching `execution_bindings` entry. A missing slot is a
   `missing_execution_slots` entry.
3. **Region policy:** the deploy's region is allowed by the requirement's
   `region_policy`.

`satisfied` is true if and only if all gap lists are empty; gaps surface as the
one plain deploy error, before anything is live (D03-4). The revision records
`requirement_digest` equal to the canonical bytes of the exact composed
requirement it was checked against, so a later requirement change cannot be
silently treated as satisfied.

## Secret boundary

- Secrets are **passed at deploy time** (`--secret key=$VAL`, typically from an
  env var, or via the Python `study.deploy(secrets={...})` call). API-02 stores
  the value and wires a reference — no pre-register step, no hand-managed
  `SecretRef` (D03-3).
- The revision references secrets only through the shared-kernel `SecretRef`
  (`binding_id` plus `resolution`, and `binding_revision` when pinned). Raw
  credential/token/password fields are forbidden at every depth. The value
  never enters the study source, compiled artifact, deployment record, logs,
  exports, or the client.
- `provider_bindings` reference a secret by `secret_requirement_key`; that key
  must resolve to a `secret_bindings` entry in the same revision.
- API-02 owns this minimal secret storage itself (F-4): it is a security
  mechanism, not a governance layer. There is no separate rotation authority or
  access-audit subsystem; the self-hosting institution controls access to its
  own install.
- Rotation is `mug deploy` with a new value. `Resolution.CURRENT` follows the
  latest binding; `Resolution.PINNED` fixes an exact `binding_revision` (F-3).
  **`Resolution.CURRENT` is the default** (settled 2026-07-18): the new value is
  used everywhere going forward, including in-flight visits' subsequent calls —
  matching why keys get rotated. Pinning is the advanced opt-in for studies that
  must reproduce an exact historical exposure.

## Client projection and disclosure

`ClientDeploymentProjection` is the only deployment artifact delivered to a
browser (through API-09). It is a positive allowlist: participant-facing
endpoints, coarse region, protocol capabilities, and the non-secret
`DeploymentRevisionRef`. It structurally cannot carry a `SecretRef`, server or
execution build, provider or model identity, or any operator/internal endpoint —
those keys and endpoint roles are absent from the schema. The projection's
`manifest_digest` closes over the exact revision body, and every projected
endpoint must be one of the revision's participant endpoints, so a projection
cannot invent an endpoint or point at the wrong revision.

## Concurrency and idempotency

Every deploy carries a shared-kernel `CommandContext`. Revision creation uses
`(deployment_id, revision_number)` optimistic concurrency and a content
fingerprint over the exact bound inputs for idempotency. No effect-time grant
check exists: deployment is ungated (self-hosted; ADR-0015).

## Failure and recovery

- Duplicate deploy with the same command key returns the original receipt and
  creates no second revision.
- A crash before the revision Unit of Work commits leaves no partial revision
  and no accepted receipt; a crash after commit returns the original receipt on
  retry.
- A deploy that fails satisfaction is rejected with a plain diagnostic, not an
  infrastructure error, and never becomes live.
- A visit's pinned `DeploymentRevisionRef` is stable across `mug stop`, server
  restart, and redeploy; recovery reloads the pinned revision and never rebinds
  to current (NS-08). This is what makes stop/redeploy safe mid-study.
- Runtime secret resolution failure is surfaced as a bounded operational error;
  it never mutates or invalidates the immutable revision.

## Scenario obligations

| Scenario | API-02 obligation |
| --- | --- |
| NS-08 | Pin an immutable revision per visit; preserve it across restart/redeploy/stop; a later study version gets its own revision without disturbing in-flight visits |
| NS-12 | Keep secret material and refs out of client projections/exports; expose only `SecretRef`/binding lineage in export lineage. Deletion/data-rights workflows are out of MUG's scope (ADR-0015); the institution acts on its own store |
