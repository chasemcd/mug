# API-01 Manifest and Packaging Boundaries

| Field | Value |
| --- | --- |
| Status | Draft |
| Contract revision | `0.2` |
| Owner | Unassigned |
| Consumers | Study authors, compiler and catalog implementers, deployment services, participant clients, workers, and replay/export readers |
| Last updated | 2026-07-20 |
| Depends on | [API design standard](../api-design-standard.md), [shared references](../shared-kernel/references.md), [serialization and schema evolution](../shared-kernel/serialization-and-schema-evolution.md), [privacy and secrets](../shared-kernel/privacy-retention-and-secrets.md), [ADR 0003](../../decisions/0003-immutable-study-versions-and-materialized-plans.md), [ADR 0007](../../decisions/0007-explicit-client-server-provenance-manifests.md), [ADR 0008](../../decisions/0008-shared-identifiers-serialization-and-schema-evolution.md), [ADR 0011](../../decisions/0011-data-classification-retention-and-secret-references.md), [ADR 0013](../../decisions/0013-git-native-study-versioning.md), and [ADR 0015](../../decisions/0015-governance-out-of-scope.md) |
| Implementation phase | Phase 1 |
| Stability tiers | Public authoring, internal compiler, participant wire, and archival |

## Purpose

API-01 turns a privileged researcher-authored study into immutable scientific
meaning and deliberately different runtime and archival views. It must prove
both completeness and non-disclosure:

- Every scientifically meaningful input is represented, resolved, and pinned,
  or compilation fails.
- The participant receives only the configuration selected for that exact
  session, audience, and activity.
- Trusted runtimes receive private scientific configuration without receiving
  secret material as ordinary data.
- Retained provenance records the exact declared reproducibility material without
  becoming an accidental copy of every input.
- Published bytes remain interpretable from a complete offline schema and
  package closure.

This contract replaces broad attribute serialization. It does not filter a
single universal dictionary into several outputs.

## Goals and non-goals

### Goals

1. Define five representations with different interpretive scope, stability,
   privacy, and consumers.
2. Define a digest graph with no self-reference or projection cycles.
3. Pin schemas, assets, executable packages, and capabilities without
   retaining local paths or mutable dependency selectors.
4. Keep scientific protocol versioning separate from deployment endpoints,
   builds, regions, and secret bindings.
5. Make participant-safe projection a positive allowlist enforced by schemas
   and tests.
6. Produce canonical, deterministic manifest bytes from the same resolved build
   inputs.

### Non-goals

- API-01 does not launch deployments or bind credentials. Those are API-02
  responsibilities.
- API-01 does not materialize participant treatment, randomization, or visit
  plans. API-04 records those outcomes before exposure.
- API-01 does not issue preference-candidate handles or artifact delivery
  bindings. API-18 and API-11 own those operations.
- API-01 does not define environment, model, tool, or replay semantics. It
  composes their exact MUG-owned domain schemas and protocols.
- Version 0 has no plugin framework, extension registry, or portable trust-class
  model. Researchers package their own study code through the fixed core package
  formats below. Execution admission and browser/process/worker isolation belong
  to API-02 and the owning core runtime contracts.
- This draft does not choose a package-signature format or compiler
  implementation library.

## The five representations

The representations form a compilation pipeline, not an inheritance hierarchy:

```text
privileged Python StudySpec
          │ normalize, resolve, validate, package
          ▼
normalized AuthoringDocument
          │
          ├──► participant-safe ClientManifest template(s)
          ├──► private StudyServerManifest template
          └──► protected ProvenanceManifest
                         │
                         ▼
              complete ScientificManifest
                         │ publish
                         ▼
                PublishedStudyVersion
```

The scientific manifest binds the exact projection digests. The projections do
not derive completeness or visibility from one another, and none is produced by
deleting keys from another representation.

### 1. `StudySpec` and normalized `AuthoringDocument`

`StudySpec` is the public Python authoring surface. It composes domain-owned
flow, activity, treatment, seat, channel, environment, controller, model,
prompt, tool, capture, preference, and data-handling declarations. API-01 owns
the composition wrappers, reference graph, destination projections, and
compilation rules, not those domain meanings. The owning API's exact schema is
authoritative inside each composed `TypedObject`; an API-01 wrapper cannot add,
reinterpret, or weaken that schema's semantics.

Deployment requirements follow the same rule. API-02 owns their vocabulary,
satisfaction semantics, and deployment overlay. API-01 must compose one exact,
content-bound API-02 requirement object into the accepted authoring and
scientific roots. The current version-0 API-01 schema composes a fixture
placeholder `TypedObject` in that slot until API-02's exact schema is
Accepted; this is a known Draft gap and does not allow deployment
providers in an API-01 capability requirement or to infer them at publication.

The Python object graph is not an archival format. Before hashing or
publication, the compiler produces a strict normalized `AuthoringDocument`:

```json
{
  "schema": {"name": "mug.study.authoring-document", "version": 0, "digest": {"algorithm": "sha-256", "hex": "..."}},
  "study_id": "study_01981c4e-7b64-7e81-8a72-a2537d5f6c91",
  "title": "Example study",
  "flow": {"entry_node_id": "flownode_01981c73-bb4c-7141-88cc-f53a011446cd", "nodes": []},
  "definitions": [
    {
      "kind": "activity",
      "key": "practice",
      "definition": {"id": "activitydef_01981c73-bb4c-7141-88cc-f53a011446cd"},
      "spec": {"schema": {"name": "mug.activity.game", "version": 0, "digest": {"algorithm": "sha-256", "hex": "..."}}, "data": {}}
    }
  ],
  "secret_requirements": [
    {
      "slot": "model-provider-primary",
      "purpose": "model-provider-credential",
      "consumers": ["model-runtime"]
    }
  ],
  "code_packages": [],
  "data_flows": [],
  "compilation_policy": {
    "unknown_fields": "reject",
    "warnings": "explicit_acknowledgment",
    "executable_content": "packaged_only",
    "hermetic_build": "required",
    "reproducibility_check": "required",
    "client_disclosure_check": "required"
  },
  "data_handling": {}
}
```

The abbreviated flow above is not a valid study by itself; the exact valid
minimal shape is the [authoring fixture](fixtures/v0/valid/authoring-document.minimal-static.json).

Authoring may temporarily refer to files, importable symbols, dependency
ranges, or source locations for diagnostics. Those values are build inputs, not
published identities. The compiler must resolve them to exact schemas,
artifacts, packages, versions, and entry points. It must then remove local
filesystem paths, current working directories, usernames, hostnames, and source
spans from semantic manifest content.

Authoring rules:

- Definition keys are permanent author-chosen names that live in the committed
  git source. Compilation validates them against the study's published history
  (ADR 0013); an incompatible key reuse fails at publish time. There is no
  server-side registry, rename, or tombstone machinery.
- Domain specs are `TypedObject` values with exact `SchemaRef`s. Provider SDK
  instances and arbitrary dictionaries are not portable specs.
- Defaults are materialized by the owning schema before semantic hashing.
- Lambdas, closures, Python pickles, live clients, sockets, database handles,
  and executable strings are forbidden scientific inputs.
- Authoring declares logical `SecretRequirement`s. It never contains a raw
  credential or `SecretRef`.
- An unsupported or unserializable field is an error. It is never omitted.

### 2. `ScientificManifest`

`ScientificManifest` is the complete, immutable, content-bound protocol. It is
the authoritative answer to “what did this study version mean?” Its canonical
body contains at least:

```json
{
  "schema": {"name": "mug.study.scientific-manifest", "version": 0, "digest": {"algorithm": "sha-256", "hex": "..."}},
  "study_id": "study_01981c4e-7b64-7e81-8a72-a2537d5f6c91",
  "source_digest": {"algorithm": "sha-256", "hex": "..."},
  "normalized_study": {
    "manifest_schema": {"name": "mug.study.authoring-document", "version": 0, "digest": {"algorithm": "sha-256", "hex": "..."}},
    "content_digest": {"algorithm": "sha-256", "hex": "..."},
    "artifact": {}
  },
  "deployment_requirements": {"schema": {"name": "...", "version": 0, "digest": {"algorithm": "sha-256", "hex": "..."}}, "data": {}},
  "capability_closure": {
    "requirements": [
      {"capability": "mug.game.server-runtime.v1", "criticality": "required"}
    ]
  },
  "compiler": {
    "name": "mug-study-compiler",
    "version": "1.0.0",
    "artifact_digest": {"algorithm": "sha-256", "hex": "..."},
    "contract": {"name": "mug.study.compiler-contract", "version": 1, "digest": {"algorithm": "sha-256", "hex": "..."}},
    "normalization_profile": "mug-normalization-v1"
  },
  "schema_bundle": {},
  "projections": {
    "clients": [],
    "server": {"manifest_schema": {}, "content_digest": {"algorithm": "sha-256", "hex": "..."}, "size_bytes": 0},
    "provenance": {"manifest_schema": {}, "content_digest": {"algorithm": "sha-256", "hex": "..."}, "size_bytes": 0}
  },
  "data_handling": {}
}
```

The exact schema and [valid scientific fixture](fixtures/v0/valid/scientific-manifest.minimal-static.json)
replace the abbreviated objects above with shared
`Digest`, `ArtifactRef`, `SchemaRef`, `DataHandlingRef`, and domain-owned typed
values.

The scientific manifest pins every input that can change assignment,
stimulus, participant experience, controller behavior, model/tool selection,
fallback, capture, interpretation, replay capability, or analysis. Hosted model
configuration pins the requested provider adapter, model selector, parameters,
and fallback rule. The actual provider-resolved model remains runtime exposure
evidence rather than a compile-time content-addressing claim.

The scientific body does not contain:

- `StudyVersionId`, display ordinal, publication time, publisher, catalog
  receipt, or signature
- Deployment endpoint, region, worker pool, secret binding, or mutable
  operational switch
- Raw credentials or a `SecretRef`
- Build-machine paths, timestamps, random build IDs, or unordered-set output

The catalog adds publication metadata in a separate
`PublishedStudyVersion` envelope after verifying the manifest set. Publishing
the same scientific digest under the same `StudyId` returns the existing
version. A different semantic digest creates a new version; a scientific fork
uses a new `StudyId` and explicit lineage.

### 3. Participant-safe `ClientManifest`

`ClientManifest` means safe for the selected participant/browser destination. It
does not mean publicly downloadable or classified `public` by default.

The compiler creates one common template and, where needed, separate audience
or treatment-specific templates. API-04 selects the applicable template while
materializing a visit plan. API-09 delivers only that projection. A browser must
never receive every blinded variant and be expected not to inspect them.

```json
{
  "schema": {"name": "mug.study.client-manifest", "version": 0, "digest": {"algorithm": "sha-256", "hex": "..."}},
  "protocol_requirements": ["mug.client.protocol.v1"],
  "required_capabilities": ["mug.game.client-runtime.v1"],
  "client_build_slot": "participant-runtime",
  "components": [
    {
      "slot": "primary-activity",
      "activation_slot": "primary-activity",
      "component_schema": {"name": "mug.client.game-component", "version": 0, "digest": {"algorithm": "sha-256", "hex": "..."}},
      "config": {"schema": {"name": "mug.client.game-config", "version": 0, "digest": {"algorithm": "sha-256", "hex": "..."}}, "data": {}}
    }
  ],
  "resource_slots": [
    {
      "slot": "game-background",
      "activation_slot": "primary-activity",
      "media_type": "image/webp",
      "presentation_policy": "required_before_activity"
    }
  ],
  "accessibility_profile": "wcag-aa",
  "locales": ["en-US"]
}
```

The stored client-manifest artifact carries its `DataHandlingRef` in its
`ArtifactRef` envelope. The delivered manifest body omits that
envelope because privacy labels, artifact identity, and protected content digests
are internal metadata and are not needed by the browser.

The compiled client template uses neutral logical slots. At delivery, the
server resolves those slots to scoped `PublicHandle`s and API-11 delivery
bindings.
The handle discloses neither resource kind nor UUID issuance time and does not
make the underlying resource deliverable by itself. API-18 issues preference-candidate handles; API-04/API-09
issue visit and activity presentation bindings. API-01 must not create one
globally linkable handle and reuse it across audiences.

Version 0 places no `ArtifactRef` in a delivered client-manifest body. A later
positive schema could add a separately reviewed public-integrity reference for
an explicitly public immutable client bundle. Protected or blinded content
always uses a slot, handle, and scoped delivery binding because artifact ID,
digest, size, media metadata, filename, or equality can reveal a condition.

Client manifests contain only participant-required fields. They exclude:

- Secret material, `SecretRef`, secret slot names that reveal providers, and
  backend credentials
- Private treatment, assignment, branch, partner, model, provider, prompt,
  tool, candidate, or coach identity
- Internal entity IDs, UUIDv7 timing, stable cross-context linkage, or protected
  digests
- Storage bucket, path, URI, signed URL, local filename, source module, or
  server entry point
- Unselected variants, server-only capabilities, capture internals, and
  researcher-only metadata
- Raw executable source, dynamic `eval` content, and private server-only code or
  configuration

### 4. Private `StudyServerManifest` template

The private server manifest produced by API-01 is an immutable scientific
runtime template. It contains the protected configuration trusted runtimes need:

```json
{
  "schema": {"name": "mug.study.server-manifest", "version": 0, "digest": {"algorithm": "sha-256", "hex": "..."}},
  "execution_requirements": ["mug.game.server-runtime.v1"],
  "domain_configs": [],
  "code_packages": [],
  "artifacts": [],
  "secret_requirements": [],
  "capture_policies": [],
  "data_flows": [],
  "data_handling": {}
}
```

It may contain internal IDs, protected `ArtifactRef`s, requested model/provider
configuration, prompts, tool policy, and blinded treatment mappings. It never
contains resolved secret material.

#### `SecretRequirement` versus deployment `SecretRef`

API-01 owns logical requirements:

```json
{
  "slot": "model-provider-primary",
  "purpose": "model-provider-credential",
  "consumers": ["model-runtime"]
}
```

API-02 owns deployment-time binding. A private deployment overlay may
contain:

```json
{
  "deployment_revision": {},
  "server_template_digest": {"algorithm": "sha-256", "hex": "..."},
  "endpoint_bindings": [],
  "build_bindings": [],
  "secret_bindings": [
    {
      "slot": "model-provider-primary",
      "secret_ref": {
        "binding_id": "secret_01981c66-2f5c-7658-b3da-76dcdf5b0486",
        "resolution": "pinned",
        "binding_revision": 7
      }
    }
  ]
}
```

This overlay is bound by `DeploymentRevision`, not by the study's scientific
digest. Credential rotation therefore cannot silently rewrite a study version,
and API-01 never owns secret-provider binding. A change to logical provider,
selector, data flow, or fallback is scientific and does require a new study
version. A credential binding or endpoint change creates a deployment revision;
if it can change semantics or participant experience, both versions change.

Only the server-side deployment/runtime components that need the template may
read it or the deployment overlay. Workers receive the minimal resolved subset
for one job, not the entire manifest.

### 5. `ProvenanceManifest`

`ProvenanceManifest` is an archival, protected build and interpretation record.
It is not automatically a public supplement and is not an unrestricted dump of
authoring inputs.

It records:

- Compiler contract and implementation package identity
- Normalization/default-resolution profile
- `GitProvenance` source lineage: commit SHA, optional branch/remote, dirty
  flag, and the stored patch digest/artifact for a dirty tree
- Exact input schema and digest closure
- Exact code-package, dependency-lock, asset, schema-bundle, and build outputs
- Transformations that produced client/server projections
- Projection digests and their data-handling classifications
- Source archive, SBOM, license, and build-recipe artifacts when the institution
  elects to retain them
- Explicit disposition when source/content is withheld, transformed, or not
  retained, including the resulting replay/evidence limitation

It does not record raw credentials, `SecretRef`, environment-variable names,
vault paths, signed URLs, direct participant PII, mutable backend locations, or
provider authentication data. Prompt, source, model/tool body, and other
sensitive content appears only when the compiled provenance projection includes
it; the self-hosting institution owns retention outside this contract. A
low-entropy content digest may itself be sensitive and must not be exposed merely
because the bytes are omitted.

Runtime facts do not belong here. The provider-resolved model, fallback used,
actual request body, tool effect, participant exposure, and delivery evidence
are recorded by their runtime APIs.

## Manifest set and digest domains

### Acyclic digest graph

Compilation and publication use this order:

```text
canonical ClientManifest body/bodies ──► client digest(s)
canonical StudyServerManifest template ──► server-template digest
canonical ProvenanceManifest body ──► provenance digest
                                      │
                                      ▼
ScientificManifest contains those exact digests
                                      │
                                      ▼
canonical ScientificManifest body ──► scientific manifest digest
                                      │
                                      ▼
PublishedStudyVersion contains StudyVersionRef + scientific digest
```

Child projections do not contain the scientific manifest digest or
`StudyVersionRef`. The scientific manifest does not contain its own digest,
version ID, publication time, or signature. The publication envelope may point
to all stored artifacts and the scientific digest because it is outside that
digest domain. This direction prevents self-reference and client/server/
provenance cycles.

### Digest meanings

| Digest | Exact byte domain |
| --- | --- |
| Manifest semantic digest | RFC 8785 canonical UTF-8 of the complete standalone manifest body, including its `schema`, excluding external publication metadata and any field that would contain its own digest |
| Projection digest | Canonical bytes of exactly one client, server-template, or provenance body |
| Schema digest | Canonical bytes of the immutable schema document selected by `SchemaRef` |
| Artifact digest | Finalized encoded artifact bytes before transparent storage encryption |
| Package digest | Artifact digest of the exact executable/package bytes; the package record separately binds fixed package kind, entry point, ABI, and dependency lock |
| Compilation-input digest | Canonical resolved semantic inputs declared by the compilation profile; never Python `repr`, filesystem metadata, or raw directory order |

An encoded manifest artifact may have the same SHA-256 value as its semantic
manifest digest when it stores the identical canonical JSON bytes with identity
encoding. The two fields still have different types and claimed domains.

The compiler returns a `ManifestSet` containing verified immutable bytes
or staged artifact references, their schemas/digests, a schema bundle, and a
diagnostic report. That container is not itself scientific identity. Publication
verifies and atomically records the transitive closure before returning a
`StudyVersionRef`.

## Schema bundle and exact validation

Every standalone manifest carries an exact `SchemaRef`. Version `0` is reserved
for this design work and fixtures; publication and deployment must reject it.
Accepted schema versions are positive and immutable.

The manifest set embeds or content-addresses an offline schema bundle containing
every transitive schema needed to validate:

- The scientific, client, server-template, provenance, and publication envelopes
- Every embedded domain `TypedObject`
- Every code-package record and its MUG-owned runtime ABI contract

The registry binds name, version, digest, owner, criticality, and supported
reader/upcaster information. `$ref` never causes a network fetch. A known
name/version with the wrong digest is an integrity failure. An unknown critical
schema blocks compilation, publication, deployment, replay, or export. Unknown
fields are rejected everywhere. Version 0 has no namespaced extension container,
package-supplied schema registration, or dynamic schema discovery.

## Code packaging

Executable behavior is a package, never an incidental string, import side
effect, local path, or pickle.

### `CodePackageRef`

```json
{
  "kind": "pyodide_wheel_bundle",
  "artifact": {},
  "entrypoint": "study_policies.ball_chaser:BallChaser",
  "runtime_abi": "mug.controller.heuristic.v1",
  "dependency_lock": {},
  "required_capabilities": ["mug.game.browser-runtime.v1"]
}
```

The version-0 schema types `artifact` and `dependency_lock` as `ArtifactRef`s,
uses one runtime ABI string, constrains entry-point syntax, and permits only these
fixed core kinds:

- `browser_esm`
- `browser_wasm`
- `pyodide_wheel_bundle`
- `server_python_wheel`
- `onnx_model`

Each kind selects a MUG-owned loader and ABI contract. `CodePackageRef` neither
admits execution nor claims that bytes are safe. API-02 and the owning browser,
game, controller, or worker runtime validate admission, CSP/process isolation,
resource limits, and supported entry points before execution. Adding another
kind is a new core contract version, not an author-defined extension.

Source archive, build recipe, dependency lock, SBOM, and license artifacts may
live in protected provenance when the institution retains them. Browser packages
must use the owning runtime's CSP-compatible loader and declared MUG APIs. Inline
JavaScript strings, `eval`, and raw Python module execution outside a declared
package/entry point are forbidden.

Artifact occurrence identity remains separate from package byte identity.
Compilation uses an idempotent build scope so a retry reuses the committed
package record rather than deriving an occurrence UUID from content.

### Study-code packages

Researchers retain the current platform's ability to provide their own
environments, policies, renderers, and native tools. They ship that code as
ordinary, content-pinned `CodePackageRef` artifacts from the study repository,
and the owning MUG domain protocol defines the typed configuration and runtime
ABI by which the code is used.

There is no `PluginRequirement`, plugin array, plugin manifest, capability
negotiation protocol, dynamic discovery, or registered extension namespace in
v0. Legacy plugin, extension-container, and portable trust-class fields are
unknown fields and fail strict validation; no compatibility translation is
performed.

## Capability closure and failure behavior

The compiler computes a static transitive closure of MUG-owned capabilities
required by every domain spec, schema, component, package, codec, and selected
core execution mode. Capability names use the closed shared-kernel
`mug.*.vN` namespace; packages cannot register new names. Capability arrays are
unique and lexicographically sorted.

```json
{
  "requirements": [
    {
      "capability": "mug.game.server-authoritative.v1",
      "criticality": "required"
    },
    {
      "capability": "mug.telemetry.client-frame-timing.v1",
      "criticality": "optional_observational",
      "omission_behavior": "record_omission",
      "completeness_fact": "client_frame_timing_available"
    }
  ]
}
```

This is API-01's exact version-0 capability-closure direction: a deterministic,
static set of logical requirements and, for observational options, the required
omission/completeness evidence. It intentionally has no `provider` or
`on_unavailable` field. API-02's separately owned deployment-requirement and
deployment-revision contracts name the satisfying implementation and prove that
it supplies the required capability. There is no runtime negotiation, nearest
match, or discovery step.

Rules:

1. Unknown or missing required capability, schema, package kind/ABI, artifact,
   or client feature fails compilation or deployment before exposure.
2. The platform never chooses a nearest version or silently removes a required
   capability.
3. A capability may be `optional_observational` only when its absence cannot
   change assignment, stimulus, action, progression, participant experience,
   interpretation, or a claimed replay level.
4. Optional omission produces explicit completeness evidence. It is not treated
   as successful capture.
5. A scientifically meaningful fallback is a separately pinned branch with its
   own requirements and exposure event, not an optional capability downgrade.
6. The client handshake checks the selected manifest's exact required set. A
   mismatch returns a safe unsupported result before treatment or plan content
   is exposed.
7. A server missing required capabilities is unready for that deployment
   revision. API-02 proves satisfaction against its immutable deployment
   requirements/revision; a worker receives only jobs compatible with its
   declared set.

## Privacy and forbidden-field matrix

Every persisted manifest has or inherits a `DataHandlingRef`. Participant
visibility is a destination-projection decision, not the same as a `public`
privacy label.

| Representation | Typical classification | Allowed shared references | Forbidden content |
| --- | --- | --- | --- |
| `StudySpec` / authoring document | `research` plus `sensitive` where needed | Internal typed IDs, `SchemaRef`, build-input handles, logical `SecretRequirement` | Raw secret, `SecretRef`, direct participant PII, live provider/tool client, socket, transaction, pickle, arbitrary closure |
| `ScientificManifest` | `research,sensitive` | Internal IDs, exact `SchemaRef`, protected `ArtifactRef`, digests, `SecretRequirement` | Raw secret, `SecretRef`, direct PII, deployment endpoint/region/binding, mutable path/URL, publication metadata |
| `ClientManifest` | `public` only when approved; otherwise audience-scoped `research` with any needed restrictions | Exact client schemas, approved public artifact integrity data, runtime `PublicHandle`/delivery bindings | Secret or `SecretRef`, PII, private treatment/model/provider/prompt/tool/candidate identity, unselected variants, protected ID/digest/path/URI/filename |
| `StudyServerManifest` template | `research,sensitive` | Internal IDs, `SchemaRef`, protected `ArtifactRef`, prompt/tool/model/treatment config, `SecretRequirement` | Raw secret, resolved `SecretRef`, direct identity data, deployment-only binding |
| API-02 deployment overlay | `research,sensitive`; tightly restricted | Deployment revision, endpoint/build refs, `SecretRef` | Raw secret material, client delivery, research export |
| `ProvenanceManifest` | `research,sensitive` and `pii` only for a separately justified protected record | Exact schemas, digests, artifacts, packages, lineage, explicitly included provenance content | Raw secret, `SecretRef`, signed URL, direct participant PII by default, mutable backend location, content excluded from the compiled provenance projection |

Field names such as `api_key`, `password`, `credential`, `token`, backend URI,
or vault path in a forbidden schema are rejected by schema/static checks as
defense in depth. Positive typed schemas and destination-aware compilation are
the primary controls; a denylist is not sufficient.

Effective privacy is the shared label-lattice join of inherited, declared, and
context-derived restrictions. A later classification decision may narrow
delivery without rewriting an immutable manifest. Lowering classification
requires a new, provenance-bearing transformation and output object.

## Canonical ordering and deterministic output

RFC 8785 canonicalizes object members, but the compiler must also normalize
arrays that represent sets. Initial canonical ordering is:

| Collection | Canonical order |
| --- | --- |
| Authored definitions | Definition kind, then authoring key |
| Schema references | Name, integer version, lowercase digest |
| Artifact references | Artifact ID after duplicate logical slots are rejected |
| Code packages | Package kind, entry point, artifact ID |
| Capabilities | Capability string lexicographically |
| Secret requirements | Slot, purpose, then sorted consumer set |
| Data-flow declarations | Stable flow definition ID |
| Client projections | Internal audience-class key; the compiler delivers only the selected projection |
| Named bindings and component/resource slots | Constrained slot key |

Arrays whose order is scientific content are not sorted. Flow priority,
fallback order, candidate display order rules, controller activation order, and
prompt/message sequence preserve their explicitly authored semantics. A schema
must identify whether an array is an ordered sequence or a canonical set.

Compiler output must not depend on Python dictionary/set iteration, filesystem
directory order, locale, timezone, current time, process ID, host path, or random
UUID generation. Randomization used during visits is not compilation. If a build
operation creates occurrence IDs for artifacts, its idempotent build record must
return the same committed inputs on retry; deterministic occurrence UUIDs are
forbidden.

## Manifest access and delivery

Manifest existence, ID, digest, handle, or artifact reference never determines
delivery.

| Object | Intended readers | Delivery rule |
| --- | --- | --- |
| Authoring source, stored patches, and diagnostics | Researchers operating the self-hosted store | Control-plane API only; source spans and local paths remain outside published outputs |
| Scientific manifest | Catalog, compiler, deployment validator, and researchers operating the self-hosted store | Protected immutable query or bundle; never sent wholesale to a participant |
| Client manifest | The participant session selected for the visit/activity projection | Delivered through API-09 under a deployment-pinned protocol; only the selected variant, with opaque handles and scoped delivery bindings |
| Private server template | Deployment compiler, coordinator, and required service/worker subset | Server-only; workers receive only the fragments required for execution |
| Deployment overlay | API-02 and runtime components using its bound resources | Never sent to browser, evidence stream, replay bundle, or ordinary export |
| Provenance manifest | Researchers operating the self-hosted store and replay/export builders | Protected archival query; redacted/audience-specific derivatives are new lineage-bearing objects |

Client delivery uses an opaque presentation reference, not a backend artifact
path. The server resolves the current participant session, visit, and deployment,
selects the matching projection, validates its digest and required
capabilities, and then creates scoped API-11 delivery bindings. Caching is keyed
by the selected projection and cannot make one treatment variant discoverable
to another audience.

A stopped deployment, integrity failure, or newly stricter classification can
prevent delivery while leaving retained immutable history unchanged. Missing or
corrupted manifest bytes make the affected deployment unavailable; the platform
never reconstructs a best-effort configuration from current code.

## Compilation and publication gates

Compilation proceeds through explicit gates:

1. Parse and structurally validate authoring types from the captured git
   state (commit + patch).
2. Resolve definition keys against the study's published history and
   materialize defaults.
3. Resolve every domain `TypedObject` against the offline schema registry.
4. Resolve and package assets, study code, dependency locks, and schemas.
5. Compute the transitive capability and data-flow closure.
6. Partition fields into client, private server, and provenance outputs using
   destination-aware typed schemas.
7. Run privacy, blinding, secret, and forbidden-field validation on each output.
8. Canonicalize and digest child projections.
9. Build, validate, canonicalize, and digest the scientific manifest.
10. Verify the complete offline closure and produce a `ManifestSet`.

Publication additionally requires:

- Positive immutable schema versions; version `0` is rejected
- Every `SchemaRef` resolves locally with its exact digest
- Every referenced artifact/package is finalized, readable, and digest/size
  verified
- Every logical required capability is represented in an exact API-02-owned
  deployment requirement; publication does not choose a provider or require a
  deployment revision. API-02 later proves satisfaction before activation, and
  that provider binding is not a field of API-01's `CapabilityRequirement`
- Every projection digest matches its canonical bytes
- No secret material or forbidden destination field is present
- No unresolved path, dependency range, mutable tag, branch, or URL remains
- The catalog's idempotent same-study manifest-digest uniqueness check and the
  version-string reservation both succeed

Publication writes the study version, immutable manifest references, terminal
idempotency result, canonical publication event, and outbox in one relational
Unit of Work. Artifact bytes are finalized and verified before that commit,
following API-11 semantics.

## Required contract fixtures

The lists below are the fixture set required for acceptance, not a claim about
the current executable bundle. Revision 0.2 currently exercises only the
minimal static authoring/manifest/provenance slice and the one-defect invalid
cases listed in the [fixture index](fixtures/index.md). The north-star, deployment,
controller, P2P, and package-runtime cases become executable only after their owning
domain schemas and the API-02 deployment-requirement composition are exact.

### Valid

- Minimal static/content study
- Browser/P2P game with a pinned Pyodide environment and packaged deterministic
  controller
- Server-authoritative game with an ONNX artifact and exact tensor contract
- Blinded two-condition trajectory preference with separately delivered client
  projections
- Human/LLM chat with private prompt/model/tool policy and a logical secret
  requirement
- Multi-human/multi-LLM game and chat study with a complete capability closure
- Offline-complete schema, package, and dependency bundle
- Same-study identical-manifest publication under its existing version string
  returning the existing version
- Dirty-tree publication whose commit + stored patch reconstructs the compiled
  source exactly
- New deployment `SecretRef` overlay leaving the scientific digest unchanged

### Invalid, one intended defect each

- Unknown or unserializable authoring field; lambda, closure, pickle, or provider
  SDK object
- Raw API key, TURN credential, or other secret material in any input/output
- `SecretRef` in authoring, scientific, client, server-template, or provenance
  output
- Version-0 schema at publication; unknown schema; digest mismatch; network-only
  `$ref`; missing transitive schema
- Mutable package URL, unpinned Git branch, dependency range, OCI tag, missing
  lockfile, or undeclared/dynamically discovered executable package left in the
  published closure
- Client manifest containing an internal ID, protected digest, storage path,
  filename, private prompt/model/provider/treatment identity, or every blinded
  variant
- Missing required capability or undeclared optional downgrade
- Legacy plugin, extension-container, or portable trust-class field accepted
  instead of rejected as unknown
- Missing, unreadable, wrong-size, or wrong-digest artifact/package
- Duplicate definition key, or key reuse incompatible with published history
- Dirty provenance without a stored patch, or a patch artifact whose digest
  disagrees with the declared patch digest
- New content published under an already-used version string, or identical
  content under a new string
- Child projection modified without changing the scientific root digest
- Build timestamp, working directory, set iteration, or locale changing canonical
  output for identical resolved inputs
- Provenance retaining content excluded from its compiled projection or silently
  omitting content required for a claimed replay/evidence capability
- A second same-study version accepted with an identical scientific manifest

The blinded client fixture must compare complete serialized outputs and request
behavior, not only known field names. IDs, UUID timing, digests, sizes, ordering,
error differences, asset requests, cache keys, and filenames are all possible
side channels.

## Existing-platform replacement constraints

The current platform derives scene metadata from broad object state and silently
removes unserializable values. It also ships model paths/configuration and whole
heuristic source modules to the browser. API-01 must replace these mechanisms
with the explicit schemas and packages above; it must not wrap them as the new
compiler backend. No pre-vNext source compatibility is required, but the current
human/game/P2P/server-authoritative functionality remains required through the
[functional-parity contract](../../functional-parity.md).

## Open decisions

- Exact accepted schema fields and size limits for each representation
- Compiler/build split and idempotent artifact-build protocol
- Package signature, transparency-log, SBOM, and vulnerability-metadata formats
- Whether a common client manifest may expose public artifact integrity directly
  or always uses runtime slots
- Schema-bundle packaging and retained reader-support lifetime
- Publication signing format
- Schema-aware semantic diff categories and migration-report format
