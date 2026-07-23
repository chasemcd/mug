"""The five records that API-02 owns: the deployment platform surface.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``platform_schema`` loads it for the conformance test.

This family owns the composed ``DeploymentRequirement`` a study version needs, the
mutable ``Deployment`` aggregate with its live or stopped disposition, the
immutable ``DeploymentRevision`` that ``mug deploy`` records, the internal
``SatisfactionReport`` that a check produces, and the positive-allowlist
``ClientDeploymentProjection`` a participant client receives. Each record
references the kernel (L0) types; the family adds no runtime. Secret bindings hold
only a shared-kernel ``SecretRef``; the secret value never appears.

Four invariants are not expressible in JSON Schema and live here as validators:

- a revision binds each secret requirement key at most once;
- every provider binding names a secret requirement the revision also binds;
- every execution binding fills a distinct slot;
- a satisfaction report is satisfied when, and only when, every gap list is empty,
  and it pins the checked revision under exactly that condition.

The schema also forbids any secret-material field by name. Every model here forbids
unknown fields, so that rule holds by construction and needs no validator.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    ArtifactRef,
    CapabilitySet,
    DataHandlingRef,
    Digest,
    SchemaBundle,
    SchemaRef,
    SecretRef,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import DeploymentId, DeploymentRevisionId, StudyId
from mug.kernel.refs import DeploymentRevisionRef, PositiveSafeInteger, StudyVersionRef

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-02/schemas/v0/platform-deployment.schema.json"
)


@lru_cache(maxsize=1)
def platform_schema() -> SchemaBundle:
    """Return the loaded API-02 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=platform_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


DeploymentKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]
Region = Annotated[str, Field(pattern=r"^[a-z]{2}(?:-[a-z0-9]+)+$", max_length=64)]
EndpointUrl = Annotated[
    str,
    Field(
        pattern=(
            r"^(?:(?:https|wss)://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
            r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+"
            r"|(?:http|ws)://localhost)"
            r"(?::[1-9][0-9]{0,4})?"
            r"(?:/[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]*)?$"
        ),
        max_length=512,
    ),
]
_ProviderClass = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-.][a-z0-9]+)*$", max_length=128)
]
_ModelSelector = Annotated[
    str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$", max_length=200)
]

SecretPurpose = Literal[
    "provider-credential", "signing-key", "storage-credential", "integration-token"
]
DeploymentDisposition = Literal["live", "stopped"]
_SlotRuntime = Literal["server", "browser", "worker"]


# --- Composed requirement ------------------------------------------------


class DeploymentSecretRequirement(KernelModel):
    """One secret a deployment must bind, its purpose, and whether it is optional."""

    requirement_key: DeploymentKey
    purpose: SecretPurpose
    optional: bool


class ExecutionSlotRequirement(KernelModel):
    """One execution slot a deployment must fill, with the runtime it needs."""

    slot: DeploymentKey
    runtime: _SlotRuntime


class ProviderAdapterRequirement(KernelModel):
    """One provider adapter class a deployment must supply."""

    adapter_key: DeploymentKey
    provider_class: _ProviderClass


class RegionPolicy(KernelModel):
    """The regions a deployment may run in, and whether residency is pinned."""

    allowed_regions: Annotated[list[Region], Field(min_length=1, max_length=32)]
    residency: Literal["flexible", "pinned"]


class DeploymentRequirementData(KernelModel):
    """What one study version needs from a deployment to run."""

    secret_requirements: Annotated[
        list[DeploymentSecretRequirement], Field(max_length=64)
    ]
    execution_slots: Annotated[
        list[ExecutionSlotRequirement], Field(min_length=1, max_length=256)
    ]
    provider_adapters: Annotated[
        list[ProviderAdapterRequirement], Field(max_length=64)
    ] | None = None
    region_policy: RegionPolicy | None = None


class DeploymentRequirement(KernelModel):
    """The composed requirement a study version pins for a deployment to satisfy."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-02.deployment-requirement")
    )
    data: DeploymentRequirementData


# --- Deployment aggregate ------------------------------------------------


class Deployment(KernelModel):
    """One deployment of a study: its disposition and the revision it points at."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-02.deployment")
    )
    deployment_id: DeploymentId
    study_id: StudyId
    disposition: DeploymentDisposition
    current_revision: DeploymentRevisionRef

    @model_validator(mode="after")
    def _revision_names_this_deployment(self) -> Deployment:
        if self.current_revision.deployment_id != self.deployment_id:
            raise ValueError("current revision must name this deployment")
        return self


# --- Immutable revision --------------------------------------------------


class ClientBuildBinding(KernelModel):
    """The client build one audience class receives."""

    audience_class: DeploymentKey
    build: ArtifactRef


class ExecutionBinding(KernelModel):
    """The artifact that fills one execution slot on one runtime."""

    slot: DeploymentKey
    runtime: _SlotRuntime
    artifact: ArtifactRef


class SecretBinding(KernelModel):
    """A pass-at-deploy secret bound by reference alone, never by value."""

    requirement_key: DeploymentKey
    purpose: SecretPurpose
    secret_ref: SecretRef


class ProviderBinding(KernelModel):
    """One provider adapter wired to a model selector and a secret requirement."""

    adapter_key: DeploymentKey
    provider_class: _ProviderClass
    model_selector: _ModelSelector
    secret_requirement_key: DeploymentKey


class EndpointBinding(KernelModel):
    """One endpoint the revision exposes, to a participant or internal audience."""

    role: Literal["participant-realtime", "participant-http", "worker"]
    audience: Literal["participant", "internal"]
    url: EndpointUrl
    protocol_capabilities: CapabilitySet


class DeploymentRevision(KernelModel):
    """One immutable deployment revision that ``mug deploy`` records."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-02.deployment-revision")
    )
    deployment_id: DeploymentId
    deployment_revision_id: DeploymentRevisionId
    revision_number: PositiveSafeInteger
    study_version: StudyVersionRef
    requirement_digest: Digest
    server_build: ArtifactRef
    client_builds: Annotated[
        list[ClientBuildBinding], Field(min_length=1, max_length=64)
    ]
    execution_bindings: Annotated[
        list[ExecutionBinding], Field(min_length=1, max_length=256)
    ]
    provider_bindings: Annotated[
        list[ProviderBinding], Field(max_length=64)
    ] | None = None
    secret_bindings: Annotated[list[SecretBinding], Field(max_length=64)]
    region: Region
    endpoints: Annotated[list[EndpointBinding], Field(min_length=1, max_length=64)]
    data_handling: DataHandlingRef

    @model_validator(mode="after")
    def _bindings_are_consistent(self) -> DeploymentRevision:
        secret_keys: set[str] = set()
        for binding in self.secret_bindings:
            if binding.requirement_key in secret_keys:
                raise ValueError("a secret requirement key is bound more than once")
            secret_keys.add(binding.requirement_key)
        for provider in self.provider_bindings or ():
            if provider.secret_requirement_key not in secret_keys:
                raise ValueError("a provider binding names an unbound secret key")
        slots: set[str] = set()
        for binding in self.execution_bindings:
            if binding.slot in slots:
                raise ValueError("an execution slot is filled more than once")
            slots.add(binding.slot)
        return self


# --- Client projection ---------------------------------------------------


class ParticipantEndpoint(KernelModel):
    """One participant-facing endpoint that a client projection exposes."""

    role: Literal["participant-realtime", "participant-http"]
    url: EndpointUrl
    protocol_capabilities: CapabilitySet


class ClientDeploymentProjection(KernelModel):
    """The positive-allowlist view a participant client receives of a deployment."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-02.client-deployment")
    )
    deployment: DeploymentRevisionRef
    region: Region
    endpoints: Annotated[list[ParticipantEndpoint], Field(min_length=1, max_length=16)]
    protocol_capabilities: CapabilitySet


# --- Satisfaction report -------------------------------------------------


class SatisfactionReport(KernelModel):
    """The internal check of a revision against a pinned requirement."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-02.satisfaction-report")
    )
    deployment_revision: DeploymentRevisionRef | None = None
    study_version: StudyVersionRef
    requirement_digest: Digest
    satisfied: bool
    unbound_secret_requirements: Annotated[list[DeploymentKey], Field(max_length=64)]
    missing_execution_slots: Annotated[list[DeploymentKey], Field(max_length=256)]
    region_gaps: Annotated[list[Region], Field(max_length=32)]

    @model_validator(mode="after")
    def _satisfied_matches_gaps(self) -> SatisfactionReport:
        consistent = not (
            self.unbound_secret_requirements
            or self.missing_execution_slots
            or self.region_gaps
        )
        if self.satisfied != consistent:
            raise ValueError("satisfied must agree with the gap lists")
        if self.satisfied != (self.deployment_revision is not None):
            raise ValueError("a satisfied report pins the checked revision")
        return self
