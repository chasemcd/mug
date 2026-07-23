"""The four objects that API-19 owns: export request, bundle, lineage, binding.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``export_schema`` loads it for the conformance test.

The study, artifact, and schema references live in the kernel (layer L0); an
export object references them. This family adds no runtime that produces an
export; the export machinery stays deferred.

Three invariants are not expressible in field types and live here as validators:

- a git provenance reference names a patch digest exactly when the tree is dirty;
- a lineage record names at least one source stream or source artifact;
- a derived lineage record names at least one source artifact.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    ArtifactRef,
    DataHandlingRef,
    Digest,
    SchemaBundle,
    SchemaRef,
    UtcInstant,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import ArtifactId, StreamId
from mug.kernel.refs import NonNegativeSafeInteger, StudyVersionRef

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-19/schemas/v0/export.schema.json"
)


@lru_cache(maxsize=1)
def export_schema() -> SchemaBundle:
    """Return the loaded API-19 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=export_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]
_DatasetKind = Literal["events", "trajectories", "preferences", "conversations"]
_GitCommitSha = Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
_GitBranchName = Annotated[
    str, Field(pattern=r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$", max_length=255)
]
_GitRemoteUrl = Annotated[
    str,
    Field(
        pattern=(
            r"^(?:[a-z][a-z0-9+.-]*://[^\s]+"
            r"|[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:[^\s]+)$"
        ),
        max_length=512,
    ),
]
_GitSourcePath = Annotated[
    str, Field(pattern=r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$", max_length=255)
]


class GitProvenanceRef(KernelModel):
    """The git state that produced an export: commit, tree state, and patch."""

    commit: _GitCommitSha
    branch: _GitBranchName | None = None
    remote: _GitRemoteUrl | None = None
    dirty: bool
    patch_digest: Digest | None = None
    source_path: _GitSourcePath | None = None

    @model_validator(mode="after")
    def _patch_agrees_with_dirty(self) -> GitProvenanceRef:
        if self.dirty and self.patch_digest is None:
            raise ValueError("a dirty tree must name a patch digest")
        if not self.dirty and self.patch_digest is not None:
            raise ValueError("a clean tree must not name a patch digest")
        return self


class ExportRequest(KernelModel):
    """A pinned request for one dataset export: study, kind, and filters."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-19.export-request")
    )
    export_key: _AuthoringKey
    study_version: StudyVersionRef
    dataset_kind: _DatasetKind
    filters_digest: Digest
    requested_at: UtcInstant


class ExportBundle(KernelModel):
    """A produced dataset export: the artifact, its rows, and its provenance."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-19.export-bundle")
    )
    export_key: _AuthoringKey
    study_version: StudyVersionRef
    dataset_kind: _DatasetKind
    artifact: ArtifactRef
    row_count: NonNegativeSafeInteger
    row_schema: SchemaRef
    lineage_digest: Digest
    completeness: Literal["complete", "partial"]
    snapshot_at: UtcInstant
    bundle_digest: Digest
    data_handling: DataHandlingRef

    @model_validator(mode="after")
    def _artifact_is_ndjson(self) -> ExportBundle:
        if self.artifact.media_type != "application/x-ndjson":
            raise ValueError("an export artifact must be application/x-ndjson")
        return self


class LineageRecord(KernelModel):
    """The origin of one export: git state, source data, and transformation."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-19.lineage-record")
    )
    export_key: _AuthoringKey
    study_version: StudyVersionRef
    git_provenance: GitProvenanceRef
    source_stream_ids: Annotated[list[StreamId], Field(max_length=1024)]
    source_artifact_ids: Annotated[list[ArtifactId], Field(max_length=4096)]
    transformation: Literal["none", "redacted", "aggregated"]

    @model_validator(mode="after")
    def _names_at_least_one_source(self) -> LineageRecord:
        if not self.source_stream_ids and not self.source_artifact_ids:
            raise ValueError("a lineage record must name at least one source")
        if self.transformation != "none" and not self.source_artifact_ids:
            raise ValueError("a derived export must name a source artifact")
        return self


class DatasetSchemaBinding(KernelModel):
    """The row schema bound to one dataset kind for export."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-19.dataset-schema-binding")
    )
    dataset_kind: _DatasetKind
    row_schema: SchemaRef
