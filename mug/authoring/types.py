"""The records that API-01 owns: study authoring, compilation, and publication.

You construct each document with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``authoring_schema`` loads it for the conformance test.

The family owns eight self-describing documents -- the ``AuthoringDocument`` a
researcher writes, the four compiled manifests (``ScientificManifest``,
``ClientManifest``, ``StudyServerManifest``, ``ProvenanceManifest``), their
``ManifestSet`` closure, the ``ValidationReport``, and the immutable
``PublishedStudyVersion``. It also owns the value objects those documents embed
and that the corpus validates on their own: ``FlowSpec``, ``GitProvenance``,
``CodePackageRef``, ``SecretRequirement``, ``CapabilityRequirement``,
``ServerRuntimeBindingBase``, ``Diagnostic``, and ``ManifestArtifact``. The
family adds no runtime; the compiler and the publication service stay deferred.

Several invariants are not expressible in JSON Schema and live here as
validators:

- a git provenance record carries a patch when, and only when, the tree is
  dirty, and the patch artifact digest agrees with the patch digest;
- a capability requirement states a disposition when, and only when, it is
  optional and observational;
- an error diagnostic is never suppressible;
- a code package agrees with its kind (artifact media type, entrypoint, and
  runtime ABI);
- a flow references only nodes it defines, and a random choice count never
  exceeds the number of choices;
- an authoring document uses each (kind, key) definition pair at most once;
- a client manifest never discloses an internal identifier;
- a manifest artifact content digest agrees with its identity artifact digest.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, TypeAlias, Union

from pydantic import Field, model_validator

from mug.kernel import (
    ArtifactRef,
    CapabilitySet,
    DataHandlingRef,
    Digest,
    PrincipalRef,
    ResourceRef,
    SchemaBundle,
    SchemaRef,
    SemVer,
    TypedObject,
    UtcInstant,
    load_family_schema,
    sha256_hex,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import ActivityDefinitionId, FlowNodeDefinitionId, StudyId
from mug.kernel.refs import NonNegativeSafeInteger, StudyVersionRef

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-01/schemas/v0/study-authoring.schema.json"
)


@lru_cache(maxsize=1)
def authoring_schema() -> SchemaBundle:
    """Return the loaded API-01 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one document from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=authoring_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


# --- Scalar formats -------------------------------------------------------

AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$", max_length=64)
]
_DottedKey = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"
VersionString = Annotated[
    str, Field(pattern=r"^[^\s](?:.*[^\s])?$", min_length=1, max_length=128)
]
JsonPointer = Annotated[
    str, Field(pattern=r"^(?:/(?:[^~/]|~0|~1)*)*$", max_length=1024)
]
GitCommitSha = Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
GitBranchName = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$", max_length=255),
]
GitRemoteUrl = Annotated[
    str,
    Field(
        pattern=(
            r"^(?:[a-z][a-z0-9+.-]*://[^\s]+"
            r"|[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:[^\s]+)$"
        ),
        max_length=512,
    ),
]
GitSourcePath = Annotated[
    str,
    Field(pattern=r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$", max_length=255),
]
_Capability = Annotated[
    str,
    Field(pattern=r"^mug(?:\.[a-z][a-z0-9-]*)+\.v[1-9][0-9]*$", max_length=160),
]
_Disposition = Annotated[str, Field(pattern=_DottedKey, max_length=128)]
_Locale = Annotated[
    str, Field(pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$", max_length=35)
]


# --- Git provenance -------------------------------------------------------


class GitPatch(KernelModel):
    """The uncommitted diff of a dirty working tree, referenced by digest."""

    patch_digest: Digest
    size_bytes: NonNegativeSafeInteger
    artifact: ArtifactRef | None = None


class GitProvenance(KernelModel):
    """The exact source revision a compilation ran against."""

    commit: GitCommitSha
    branch: GitBranchName | None = None
    remote: GitRemoteUrl | None = None
    dirty: bool
    patch: GitPatch | None = None
    source_path: GitSourcePath | None = None

    @model_validator(mode="after")
    def _patch_agrees_with_dirty(self) -> GitProvenance:
        if self.dirty and self.patch is None:
            raise ValueError("a dirty tree must carry a patch")
        if not self.dirty and self.patch is not None:
            raise ValueError("a clean tree must not carry a patch")
        patch = self.patch
        if patch is not None and patch.artifact is not None:
            artifact = patch.artifact
            if (
                artifact.content_encoding == "identity"
                and artifact.digest.hex != patch.patch_digest.hex
            ):
                raise ValueError("patch artifact digest must match the patch digest")
        return self


# --- Compilation policy and packaging -------------------------------------


class CompilationPolicy(KernelModel):
    """The fixed, safe-by-default rules the compiler applies to one build."""

    unknown_fields: Literal["reject"]
    warnings: Literal["reject", "explicit_acknowledgment"]
    executable_content: Literal["packaged_only"]
    hermetic_build: Literal["required"]
    reproducibility_check: Literal["required"]
    client_disclosure_check: Literal["required"]


_CODE_PACKAGE_RULES: dict[str, tuple[str, str, str]] = {
    "browser_esm": (
        "application/javascript",
        r"^[A-Za-z0-9_][A-Za-z0-9_./-]*#[A-Za-z_$][A-Za-z0-9_$]*$",
        r"^browser-esm-v[1-9][0-9]*$",
    ),
    "browser_wasm": (
        "application/wasm",
        r"^[A-Za-z0-9_][A-Za-z0-9_./-]*#[A-Za-z_$][A-Za-z0-9_$]*$",
        r"^wasi-preview[12]$",
    ),
    "pyodide_wheel_bundle": (
        "application/vnd.python.wheel",
        r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_.]*$",
        r"^pyodide-[1-9][0-9]*\.[0-9]+$",
    ),
    "server_python_wheel": (
        "application/vnd.python.wheel",
        r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_.]*$",
        r"^cpython-[1-9][0-9]*\.[0-9]+$",
    ),
    "onnx_model": (
        "application/vnd.onnx",
        r"^[A-Za-z][A-Za-z0-9_-]{0,63}$",
        r"^onnx-opset-[1-9][0-9]*$",
    ),
}


class CodePackageRef(KernelModel):
    """A reference to one immutable, packaged unit of executable content."""

    kind: Literal[
        "browser_esm",
        "browser_wasm",
        "pyodide_wheel_bundle",
        "server_python_wheel",
        "onnx_model",
    ]
    artifact: ArtifactRef
    entrypoint: Annotated[
        str, Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.:/#$-]*$", max_length=256)
    ]
    runtime_abi: Annotated[str, Field(pattern=_DottedKey, max_length=128)]
    dependency_lock: ArtifactRef
    required_capabilities: CapabilitySet

    @model_validator(mode="after")
    def _package_agrees_with_kind(self) -> CodePackageRef:
        media_type, entrypoint_pattern, abi_pattern = _CODE_PACKAGE_RULES[self.kind]
        if self.artifact.media_type != media_type:
            raise ValueError("artifact media type does not match the package kind")
        if re.search(entrypoint_pattern, self.entrypoint) is None:
            raise ValueError("entrypoint does not match the package kind")
        if re.search(abi_pattern, self.runtime_abi) is None:
            raise ValueError("runtime abi does not match the package kind")
        return self


# --- Authored definitions and secrets -------------------------------------

DefinitionKind = Literal[
    "activity",
    "agent",
    "channel",
    "flow_node",
    "preference_protocol",
    "prompt",
    "seat",
    "tool",
]


class AuthoredDefinition(KernelModel):
    """One reusable definition the study references by kind and key."""

    kind: DefinitionKind
    key: AuthoringKey
    definition: ResourceRef
    spec: TypedObject


class SecretRequirement(KernelModel):
    """A named secret slot the study needs, with its purpose and consumers."""

    slot: AuthoringKey
    purpose: Annotated[str, Field(pattern=_DottedKey, max_length=128)]
    consumers: Annotated[
        list[Annotated[str, Field(pattern=_DottedKey, max_length=128)]],
        Field(min_length=1, max_length=32),
    ]


class CapabilityRequirement(KernelModel):
    """One capability the study needs, with its criticality and disposition."""

    capability: _Capability
    criticality: Literal["required", "optional_observational"]
    omission_behavior: _Disposition | None = None
    completeness_fact: _Disposition | None = None

    @model_validator(mode="after")
    def _disposition_agrees_with_criticality(self) -> CapabilityRequirement:
        optional = self.criticality == "optional_observational"
        stated = (
            self.omission_behavior is not None
            or self.completeness_fact is not None
        )
        if optional and (
            self.omission_behavior is None or self.completeness_fact is None
        ):
            raise ValueError(
                "an optional capability must state omission and completeness"
            )
        if not optional and stated:
            raise ValueError("a required capability must not state a disposition")
        return self


class CapabilityClosure(KernelModel):
    """The complete set of capability requirements a study depends on."""

    requirements: Annotated[list[CapabilityRequirement], Field(max_length=512)]


# --- Flow specification ---------------------------------------------------


class _FlowNodeBase(KernelModel):
    """Fields common to every flow node: identity and authoring key."""

    node_id: FlowNodeDefinitionId
    key: AuthoringKey


class SequenceNode(_FlowNodeBase):
    """A node that runs its children in order."""

    kind: Literal["sequence"]
    children: Annotated[
        list[FlowNodeDefinitionId], Field(min_length=1, max_length=256)
    ]


class ActivityNode(_FlowNodeBase):
    """A node that runs one activity definition."""

    kind: Literal["activity"]
    activity_definition_id: ActivityDefinitionId


class RandomizedSelectNode(_FlowNodeBase):
    """A node that runs a random subset of its choices under a rule."""

    kind: Literal["randomized_select"]
    choices: Annotated[
        list[FlowNodeDefinitionId], Field(min_length=1, max_length=256)
    ]
    choose: Annotated[int, Field(ge=1, le=256)]
    rule: TypedObject


class RepeatNode(_FlowNodeBase):
    """A node that repeats its child a fixed number of times."""

    kind: Literal["repeat"]
    child: FlowNodeDefinitionId
    repetitions: Annotated[int, Field(ge=1, le=10000)]


class BranchCase(KernelModel):
    """One condition-guarded branch of a branch node."""

    condition: TypedObject
    child: FlowNodeDefinitionId


class BranchNode(_FlowNodeBase):
    """A node that runs the first case whose condition holds."""

    kind: Literal["branch"]
    cases: Annotated[list[BranchCase], Field(min_length=1, max_length=64)]
    default_child: FlowNodeDefinitionId | None = None


class TerminalNode(_FlowNodeBase):
    """A node that ends the flow with a terminal action."""

    kind: Literal["terminal"]
    terminal: TypedObject


FlowNode = Annotated[
    SequenceNode
    | ActivityNode
    | RandomizedSelectNode
    | RepeatNode
    | BranchNode
    | TerminalNode,
    Field(discriminator="kind"),
]


def _flow_child_references(node: _FlowNodeBase) -> list[str]:
    """Return the flow node ids that one node points at."""
    if isinstance(node, SequenceNode):
        return list(node.children)
    if isinstance(node, RandomizedSelectNode):
        return list(node.choices)
    if isinstance(node, RepeatNode):
        return [node.child]
    if isinstance(node, BranchNode):
        references = [case.child for case in node.cases]
        if node.default_child is not None:
            references.append(node.default_child)
        return references
    return []


class FlowSpec(KernelModel):
    """The study flow: an entry node and the closed set of nodes it reaches."""

    entry_node_id: FlowNodeDefinitionId
    nodes: Annotated[list[FlowNode], Field(min_length=1, max_length=4096)]

    @model_validator(mode="after")
    def _references_resolve(self) -> FlowSpec:
        node_ids = {node.node_id for node in self.nodes}
        if self.entry_node_id not in node_ids:
            raise ValueError("the flow entry node is not defined")
        for node in self.nodes:
            if isinstance(node, RandomizedSelectNode) and node.choose > len(
                node.choices
            ):
                raise ValueError("choose exceeds the number of choices")
            for reference in _flow_child_references(node):
                if reference not in node_ids:
                    raise ValueError("the flow references a node it does not define")
        return self


# --- Compiler identity and manifest artifacts -----------------------------


class CompilerIdentity(KernelModel):
    """The compiler build that produced a manifest, pinned by digest."""

    name: Annotated[str, Field(pattern=_DottedKey, max_length=128)]
    version: SemVer
    artifact_digest: Digest
    contract: SchemaRef
    normalization_profile: Annotated[str, Field(pattern=_DottedKey, max_length=128)]


class ManifestArtifact(KernelModel):
    """A manifest referenced by its content digest and stored artifact."""

    manifest_schema: SchemaRef
    content_digest: Digest
    artifact: ArtifactRef

    @model_validator(mode="after")
    def _content_digest_agrees_with_artifact(self) -> ManifestArtifact:
        if (
            self.artifact.content_encoding == "identity"
            and self.content_digest.hex != self.artifact.digest.hex
        ):
            raise ValueError(
                "content digest must match the identity artifact digest"
            )
        return self


class ProjectionDigestRef(KernelModel):
    """A projection referenced by its content digest and byte size."""

    manifest_schema: SchemaRef
    content_digest: Digest
    size_bytes: NonNegativeSafeInteger


class ClientProjectionDigestRef(KernelModel):
    """One client projection digest, keyed and selected by audience."""

    projection_key: AuthoringKey
    selector: TypedObject
    manifest: ProjectionDigestRef


class ClientProjectionArtifact(KernelModel):
    """One client projection artifact, keyed and selected by audience."""

    projection_key: AuthoringKey
    selector: TypedObject
    manifest: ManifestArtifact


# --- Scientific manifest --------------------------------------------------


class _ScientificProjections(KernelModel):
    """The client, server, and provenance projections of a scientific manifest."""

    clients: Annotated[
        list[ClientProjectionDigestRef], Field(min_length=1, max_length=64)
    ]
    server: ProjectionDigestRef
    provenance: ProjectionDigestRef


class ScientificManifest(KernelModel):
    """The canonical, normalized study and the digests of its projections."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.study.scientific-manifest")
    )
    study_id: StudyId
    source_digest: Digest
    normalized_study: ManifestArtifact
    deployment_requirements: TypedObject
    capability_closure: CapabilityClosure
    compiler: CompilerIdentity
    schema_bundle: ArtifactRef
    projections: _ScientificProjections
    data_handling: DataHandlingRef


# --- Client manifest ------------------------------------------------------


class ClientComponentBinding(KernelModel):
    """One client component bound to an activation slot with its config."""

    slot: AuthoringKey
    activation_slot: AuthoringKey
    component_schema: SchemaRef
    config: TypedObject


class ClientResourceSlot(KernelModel):
    """One client resource slot with its media type and presentation policy."""

    slot: AuthoringKey
    activation_slot: AuthoringKey
    media_type: Annotated[
        str,
        Field(
            pattern=r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$",
            max_length=127,
        ),
    ]
    presentation_policy: Literal[
        "required_before_activity", "stream_on_demand", "optional_observational"
    ]


_INTERNAL_ID = re.compile(
    r"^(?:study|studyver|flownode|deploy|deployrev|"
    r"activitydef|activity|seatdef|actor|controller|interaction|channeldef|"
    r"channel|artifact|agentdef|agentver|promptdef|promptver|tooldef|toolver|"
    r"prefdef|prefver|secret)_"
    r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


_JsonValue: TypeAlias = Union[
    None, bool, int, float, str, "list[_JsonValue]", "dict[str, _JsonValue]"
]


def _reject_internal_ids(value: _JsonValue) -> None:
    """Raise if any string in a projection is an internal identifier."""
    if isinstance(value, str):
        if _INTERNAL_ID.fullmatch(value):
            raise ValueError("a client projection must not disclose an internal id")
    elif isinstance(value, dict):
        for item in value.values():
            _reject_internal_ids(item)
    elif isinstance(value, list):
        for item in value:
            _reject_internal_ids(item)


class ClientManifest(KernelModel):
    """What one client audience needs to run the study, free of internal ids."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.study.client-manifest")
    )
    protocol_requirements: CapabilitySet
    required_capabilities: CapabilitySet
    client_build_slot: AuthoringKey
    components: Annotated[list[ClientComponentBinding], Field(max_length=512)]
    resource_slots: Annotated[list[ClientResourceSlot], Field(max_length=512)]
    accessibility_profile: AuthoringKey
    locales: Annotated[list[_Locale], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def _no_internal_disclosure(self) -> ClientManifest:
        _reject_internal_ids(self.model_dump(mode="json"))
        return self


# --- Server manifest ------------------------------------------------------


class ServerRuntimeScope(KernelModel):
    """One server runtime scope, keyed and selected for a subject."""

    scope_key: AuthoringKey
    selector: TypedObject


class _ServerRuntimeBindingKeys(KernelModel):
    """The keys common to every server runtime binding."""

    binding_key: AuthoringKey
    scope_key: AuthoringKey


class ServerRuntimeBindingBase(_ServerRuntimeBindingKeys):
    """The keys plus the kind discriminator of a server runtime binding."""

    kind: Literal[
        "domain_config",
        "code_package",
        "artifact",
        "secret_requirement",
        "capture_policy",
        "data_flow",
    ]


class _DomainConfigBinding(_ServerRuntimeBindingKeys):
    """A binding that carries a domain configuration value."""

    kind: Literal["domain_config"]
    value: TypedObject


class _CodePackageBinding(_ServerRuntimeBindingKeys):
    """A binding that carries a code package."""

    kind: Literal["code_package"]
    package: CodePackageRef


class _ArtifactBinding(_ServerRuntimeBindingKeys):
    """A binding that carries an artifact reference."""

    kind: Literal["artifact"]
    artifact: ArtifactRef


class _SecretRequirementBinding(_ServerRuntimeBindingKeys):
    """A binding that carries a secret requirement."""

    kind: Literal["secret_requirement"]
    secret_requirement: SecretRequirement


class _CapturePolicyBinding(_ServerRuntimeBindingKeys):
    """A binding that carries a capture policy value."""

    kind: Literal["capture_policy"]
    value: TypedObject


class _DataFlowBinding(_ServerRuntimeBindingKeys):
    """A binding that carries a data flow value."""

    kind: Literal["data_flow"]
    value: TypedObject


ServerRuntimeBinding = Annotated[
    _DomainConfigBinding
    | _CodePackageBinding
    | _ArtifactBinding
    | _SecretRequirementBinding
    | _CapturePolicyBinding
    | _DataFlowBinding,
    Field(discriminator="kind"),
]


class StudyServerManifest(KernelModel):
    """What the server runtime binds for the study, scoped per subject."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.study.server-manifest")
    )
    execution_requirements: CapabilitySet
    scopes: Annotated[list[ServerRuntimeScope], Field(min_length=1, max_length=1024)]
    bindings: Annotated[list[ServerRuntimeBinding], Field(max_length=4096)]
    data_handling: DataHandlingRef


# --- Provenance manifest --------------------------------------------------


class TransformationRecord(KernelModel):
    """One compiler transformation, pinned by its input and output digests."""

    name: Annotated[str, Field(pattern=_DottedKey, max_length=128)]
    version: SemVer
    input_digest: Digest
    output_digest: Digest


class ProvenanceProjectionRecord(KernelModel):
    """One emitted projection and how the study retains its data."""

    role: Literal["client", "server"]
    projection_key: AuthoringKey | None = None
    projection: ProjectionDigestRef
    data_handling: DataHandlingRef
    retention_disposition: Literal[
        "retained", "withheld", "transformed", "not_retained"
    ]
    reason_code: Annotated[str, Field(pattern=_DottedKey, max_length=128)] | None = None


class ProvenanceManifest(KernelModel):
    """The complete build provenance: source, dependencies, and outputs."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.study.provenance-manifest")
    )
    compiler: CompilerIdentity
    source_git: GitProvenance
    source_artifacts: Annotated[list[ArtifactRef], Field(max_length=1024)]
    dependency_artifacts: Annotated[list[ArtifactRef], Field(max_length=2048)]
    schema_bundle: ArtifactRef
    transformations: Annotated[list[TransformationRecord], Field(max_length=1024)]
    projection_outputs: Annotated[
        list[ProvenanceProjectionRecord], Field(min_length=2, max_length=66)
    ]
    limitations: Annotated[
        list[Annotated[str, Field(pattern=_DottedKey, max_length=160)]],
        Field(max_length=256),
    ]
    data_handling: DataHandlingRef


# --- Manifest set ---------------------------------------------------------


class ManifestSet(KernelModel):
    """The closure of every manifest a compiled study produces."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.study.manifest-set")
    )
    scientific: ManifestArtifact
    clients: Annotated[
        list[ClientProjectionArtifact], Field(min_length=1, max_length=64)
    ]
    server: ManifestArtifact
    provenance: ManifestArtifact
    schema_bundle: ArtifactRef
    validation_report: ArtifactRef


# --- Validation report ----------------------------------------------------


class SourceLocation(KernelModel):
    """One location in a source document, named by document and pointer."""

    document: Literal[
        "authoring", "registry", "client", "server", "provenance", "scientific"
    ]
    pointer: JsonPointer


class Diagnostic(KernelModel):
    """One compiler diagnostic, fingerprinted and safe to disclose."""

    fingerprint: Digest
    code: Annotated[
        str, Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$", max_length=160)
    ]
    severity: Literal["error", "warning", "info"]
    stage: Literal[
        "source", "identity", "flow", "capability", "privacy", "manifest", "publication"
    ]
    safe_message: Annotated[str, Field(min_length=1, max_length=512)]
    primary_location: SourceLocation | None = None
    related_locations: Annotated[list[SourceLocation], Field(max_length=32)] | None = (
        None
    )
    definition: ResourceRef | None = None
    suppressible: bool

    @model_validator(mode="after")
    def _error_is_not_suppressible(self) -> Diagnostic:
        if self.severity == "error" and self.suppressible:
            raise ValueError("an error diagnostic must not be suppressible")
        return self


class DiagnosticCounts(KernelModel):
    """The count of diagnostics at each severity."""

    error: NonNegativeSafeInteger
    warning: NonNegativeSafeInteger
    info: NonNegativeSafeInteger


class ValidationReport(KernelModel):
    """The complete verdict of one compilation, with its diagnostics."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.study.validation-report")
    )
    input_fingerprint: Digest
    valid: bool
    diagnostics: Annotated[list[Diagnostic], Field(max_length=10000)]
    counts: DiagnosticCounts
    compiler: CompilerIdentity


# --- Authoring document ---------------------------------------------------


class AuthoringDocument(KernelModel):
    """The mutable study a researcher authors, before compilation."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.study.authoring-document")
    )
    study_id: StudyId
    title: Annotated[str, Field(min_length=1, max_length=256)]
    flow: FlowSpec
    definitions: Annotated[list[AuthoredDefinition], Field(max_length=4096)]
    secret_requirements: Annotated[list[SecretRequirement], Field(max_length=64)]
    code_packages: Annotated[list[CodePackageRef], Field(max_length=256)]
    data_flows: Annotated[list[TypedObject], Field(max_length=256)]
    deployment_requirements: TypedObject
    compilation_policy: CompilationPolicy
    data_handling: DataHandlingRef

    @model_validator(mode="after")
    def _definition_keys_are_unique(self) -> AuthoringDocument:
        seen: set[tuple[str, str]] = set()
        for definition in self.definitions:
            pair = (definition.kind, definition.key)
            if pair in seen:
                raise ValueError("a (kind, key) definition pair repeats")
            seen.add(pair)
        return self


# --- Published study version ----------------------------------------------


class DiagnosticAcknowledgment(KernelModel):
    """A researcher's acknowledgment of one warning at publication."""

    diagnostic_fingerprint: Digest
    candidate_digest: Digest
    policy_schema: SchemaRef
    acknowledged_by: PrincipalRef
    acknowledged_at: UtcInstant


class PublishedStudyVersion(KernelModel):
    """The immutable, published record of one study version."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.study.published-version")
    )
    study_version: StudyVersionRef
    version_string: VersionString
    git_provenance: GitProvenance
    candidate: ArtifactRef
    scientific: ManifestArtifact
    clients: Annotated[
        list[ClientProjectionArtifact], Field(min_length=1, max_length=64)
    ]
    server: ManifestArtifact
    provenance: ManifestArtifact
    warning_acknowledgments: Annotated[
        list[DiagnosticAcknowledgment], Field(max_length=10000)
    ]
    publication_command: ResourceRef
    publication_receipt: ResourceRef
    published_at: UtcInstant
    published_by: PrincipalRef


# --- Compilation candidate and publication result -------------------------


class CompilationInputs(KernelModel):
    """The pinned inputs one compilation ran against."""

    git_provenance: GitProvenance
    source: ArtifactRef
    compiler: CompilerIdentity
    schema_registry_digest: Digest
    build_context_digest: Digest
    target_platform_contract: SchemaRef
    compilation_policy: CompilationPolicy


class CompiledStudyCandidate(KernelModel):
    """A compiled study ready to publish, with its release eligibility."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.study.compiled-candidate")
    )
    input_fingerprint: Digest
    inputs: CompilationInputs
    manifest_set: ManifestArtifact
    validation_report: ArtifactRef
    scientific_manifest_digest: Digest
    release_eligibility: Literal["design_unpublishable", "release_candidate"]

    @model_validator(mode="after")
    def _fingerprint_binds_the_inputs(self) -> CompiledStudyCandidate:
        """The fingerprint is the digest of the inputs, so it cannot drift.

        A candidate is content-bound: two compilations of the same inputs give
        the same fingerprint, and a fingerprint that names other inputs makes
        the idempotency of a publish untrue.
        """
        expected = sha256_hex(self.inputs.model_dump(mode="json", exclude_none=True))
        if self.input_fingerprint.hex != expected:
            raise ValueError("input fingerprint must be the digest of the inputs")
        return self


class StudyPublicationResult(KernelModel):
    """The result of a publish command: a new version, or the existing one.

    A publish is idempotent. ``created`` names a version this command minted;
    ``resolved_existing`` names the version a prior identical command minted.
    """

    outcome: Literal["created", "resolved_existing"]
    study_version: StudyVersionRef
    version_string: VersionString
    candidate_digest: Digest
