"""Scalar formats and reference objects.

This module holds the small shared scalar types (``Digest``, ``SchemaRef``,
``SemVer``, ``UtcInstant``) and the reference objects that point at resources,
artifacts, secrets, and versions. A reference carries an identity plus the
minimum a reader needs; it never carries storage location or secret material.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    TypeAdapter,
    model_validator,
)

from mug.kernel._base import KernelModel
from mug.kernel.ids import RegisteredMugId, id_pattern
from mug.kernel.privacy import DataHandlingRef

# --- Scalar formats -------------------------------------------------------

SafeInteger = Annotated[int, Field(ge=-9007199254740991, le=9007199254740991)]
NonNegativeSafeInteger = Annotated[int, Field(ge=0, le=9007199254740991)]
PositiveSafeInteger = Annotated[int, Field(ge=1, le=9007199254740991)]

_SEMVER = (
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SemVer = Annotated[str, Field(pattern=_SEMVER, max_length=128)]

# A fixed-width RFC 3339 UTC instant: exactly six fractional digits, uppercase Z.
_UTC_INSTANT = (
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{6}Z$"
)
UtcInstant = Annotated[str, Field(pattern=_UTC_INSTANT)]

SchemaName = Annotated[
    str, Field(pattern=r"^mug(?:\.[a-z][a-z0-9-]*)+$", max_length=160)
]
PublicHandle = Annotated[
    str, Field(pattern=r"^handle_[A-Za-z0-9_-]{21}[AQgw]$", max_length=29)
]


def _written_down(value: object) -> object:
    """Write a whole number down as the text a record holds.

    A seat is named by the environment's own agent, and an environment names its
    agents with whatever it likes -- a PettingZoo environment that numbers them
    answers ``[0, 1]``. Every identifier in a record is **text**, so the number is
    written down here rather than each caller remembering to do it. What travels is
    still a string, so nothing that reads a record has two shapes to handle.
    """
    whole = isinstance(value, int) and not isinstance(value, bool)
    return str(value) if whole else value


# What a seat is called: the environment's own name for the agent that seat plays.
#
# It differs from an authoring key in one way -- it may **start with a digit** --
# because a seat name is not a name a study invented. Numbering agents is ordinary in
# both standard environment APIs, and the contract already accepts ``0`` as an
# environment agent id (``env_agent_id``) while refusing it as a seat key. That was an
# oversight, and it was not a small one: a study that seated a numbering environment
# composed, mounted, and stepped, and was then refused on the first drawn frame.
SeatKey = Annotated[
    str,
    BeforeValidator(_written_down),
    Field(pattern=r"^[a-z0-9][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128),
]


# --- Digest and schema reference -----------------------------------------


class Digest(KernelModel):
    """A content digest as a structured object (``{algorithm, hex}``)."""

    algorithm: Literal["sha-256"]
    hex: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SchemaRef(KernelModel):
    """A pinned reference to one schema: name, integer version, and digest."""

    name: SchemaName
    version: NonNegativeSafeInteger
    digest: Digest


# The pinned-name schema references. Each fixes one schema name at version 0.
# They are separate models (not subclasses) so a narrowed field type does not
# clash with the base and the checker stays clean.


class CommandEnvelopeSchemaRef(KernelModel):
    """A schema reference pinned to the command envelope at version 0."""

    name: Literal["mug.command-envelope"]
    version: Literal[0]
    digest: Digest


class CommandReceiptSchemaRef(KernelModel):
    """A schema reference pinned to the command receipt at version 0."""

    name: Literal["mug.command-receipt"]
    version: Literal[0]
    digest: Digest


class DomainErrorSchemaRef(KernelModel):
    """A schema reference pinned to the domain error at version 0."""

    name: Literal["mug.domain-error"]
    version: Literal[0]
    digest: Digest


class FixtureManifestSchemaRef(KernelModel):
    """A schema reference pinned to the fixture manifest at version 0."""

    name: Literal["mug.fixture-manifest"]
    version: Literal[0]
    digest: Digest


class CanonicalizationVectorsSchemaRef(KernelModel):
    """A schema reference pinned to the canonicalization vectors at version 0."""

    name: Literal["mug.canonicalization-vectors"]
    version: Literal[0]
    digest: Digest


# --- Resource and principal references -----------------------------------


class ResourceRef(KernelModel):
    """A reference to any registered resource by its identifier alone.

    The kind is derived from the identifier prefix. The reference never claims a
    separate ``kind`` field.
    """

    id: RegisteredMugId


class PrincipalRef(KernelModel):
    """A reference to an authenticated subject: a kind plus a matching id."""

    kind: Literal["participant", "researcher", "service", "system"]
    id: str

    @model_validator(mode="after")
    def _id_matches_kind(self) -> PrincipalRef:
        import re

        if not re.match(id_pattern(self.kind), self.id):
            raise ValueError(
                f"principal id {self.id!r} does not match kind {self.kind!r}"
            )
        return self


# --- Version stamps -------------------------------------------------------


class VersionStamp(KernelModel):
    """An aggregate revision plus its entity tag (``sha256:<hex>``)."""

    revision: PositiveSafeInteger
    etag: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class StudyVersionRef(KernelModel):
    """A pinned reference to one immutable study version."""

    study_id: Annotated[str, Field(pattern=id_pattern("study"))]
    study_version_id: Annotated[str, Field(pattern=id_pattern("studyver"))]
    version_number: PositiveSafeInteger
    manifest_digest: Digest


class DeploymentRevisionRef(KernelModel):
    """A pinned reference to one immutable deployment revision."""

    deployment_id: Annotated[str, Field(pattern=id_pattern("deploy"))]
    deployment_revision_id: Annotated[str, Field(pattern=id_pattern("deployrev"))]
    revision_number: PositiveSafeInteger
    study_version: StudyVersionRef
    manifest_digest: Digest


# --- Artifact and secret references --------------------------------------


class ArtifactRef(KernelModel):
    """A reference to a stored artifact: identity, digest, size, and handling.

    The reference never carries a storage URI, bucket, key, or signed URL.
    """

    artifact_id: Annotated[str, Field(pattern=id_pattern("artifact"))]
    digest: Digest
    size_bytes: NonNegativeSafeInteger
    media_type: Annotated[
        str,
        Field(
            pattern=r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$",
            max_length=127,
        ),
    ]
    content_encoding: Literal["identity", "gzip", "zstd", "br"]
    content_schema: SchemaRef | None = None
    data_handling: DataHandlingRef


class SecretRef(KernelModel):
    """A reference to a deployment secret binding; never the secret value."""

    binding_id: Annotated[str, Field(pattern=id_pattern("secret"))]
    resolution: Literal["deployment-current", "pinned"]
    binding_revision: PositiveSafeInteger | None = None

    @model_validator(mode="after")
    def _revision_matches_resolution(self) -> SecretRef:
        if self.resolution == "pinned" and self.binding_revision is None:
            raise ValueError("pinned resolution requires binding_revision")
        if self.resolution != "pinned" and self.binding_revision is not None:
            raise ValueError("binding_revision is only valid for pinned resolution")
        return self


# --- Inline bytes, capabilities, trace context ---------------------------


class InlineBytes(KernelModel):
    """Up to 4 KiB of bytes inline: base64url data plus size and digest."""

    encoding: Literal["base64url"]
    data: Annotated[
        str,
        Field(
            pattern=r"^(?:[A-Za-z0-9_-]{4})*(?:[A-Za-z0-9_-][AQgw]|[A-Za-z0-9_-]{2}[AEIMQUYcgkosw048])?$",
            max_length=5462,
        ),
    ]
    size_bytes: Annotated[int, Field(ge=0, le=4096)]
    digest: Digest

    @model_validator(mode="after")
    def _size_and_digest_match(self) -> InlineBytes:
        import base64
        import hashlib

        raw = base64.urlsafe_b64decode(self.data + "=" * (-len(self.data) % 4))
        if len(raw) != self.size_bytes:
            raise ValueError("size_bytes does not match the decoded length")
        if hashlib.sha256(raw).hexdigest() != self.digest.hex:
            raise ValueError("digest does not match the decoded bytes")
        return self


def _check_capability_set(value: list[str]) -> list[str]:
    """Reject a capability list that repeats a capability.

    The frozen schema treats a capability set as a unique, unordered list
    (``uniqueItems`` only). It states no order, and consuming families reuse
    this type with unsorted valid instances, so this type does not sort.
    """
    if len(set(value)) != len(value):
        raise ValueError("capability set must not repeat a capability")
    return value


_Capability = Annotated[
    str, Field(pattern=r"^mug(?:\.[a-z][a-z0-9-]*)+\.v[1-9][0-9]*$", max_length=160)
]
CapabilitySet = Annotated[
    list[Annotated[_Capability, Field()]],
    Field(max_length=256),
    AfterValidator(_check_capability_set),
]


class TraceContext(KernelModel):
    """A W3C trace context: a ``traceparent`` and an optional ``tracestate``."""

    traceparent: Annotated[
        str, Field(pattern=r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$", max_length=55)
    ]
    tracestate: Annotated[str, Field(max_length=512)] | None = None

    @model_validator(mode="after")
    def _forbid_all_zero_ids(self) -> TraceContext:
        trace_id = self.traceparent[3:35]
        parent_id = self.traceparent[36:52]
        if trace_id == "0" * 32:
            raise ValueError("traceparent trace-id must not be all zero")
        if parent_id == "0" * 16:
            raise ValueError("traceparent parent-id must not be all zero")
        return self


# Adapters for the bare-string and bare-array kernel types. They let the
# conformance test validate a top-level scalar or array against the schema.
PUBLIC_HANDLE_ADAPTER: TypeAdapter[str] = TypeAdapter(PublicHandle)
SEMVER_ADAPTER: TypeAdapter[str] = TypeAdapter(SemVer)
CAPABILITY_SET_ADAPTER: TypeAdapter[list[str]] = TypeAdapter(CapabilitySet)
