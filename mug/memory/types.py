"""The four records that API-15 owns: scope, read, proposal, and commit.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``memory_schema`` loads it for the conformance test.

This family models the experimental agent-memory records. It states which scope a
memory lives in, how the experiment treats that scope, and the compare-and-swap
read/propose/commit cycle over a memory value. The family adds no runtime; the
store, the swap, and provenance minting stay deferred.

One invariant is not expressible in JSON Schema and lives here as a validator:

- a commit advances the memory version by exactly one revision.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from mug.kernel import (
    Digest,
    SchemaBundle,
    SchemaRef,
    UtcInstant,
    VersionStamp,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import DecisionId, EnrollmentId, MemorySnapshotId

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-15/schemas/v0/memory.schema.json"
)

MemoryScopeName = Literal["working", "episodic", "longitudinal"]
"""The registry of memory scope kinds in version 0."""

MemoryModeName = Literal["shared", "isolated", "ablated"]
"""The registry of experimental treatment modes in version 0."""


@lru_cache(maxsize=1)
def memory_schema() -> SchemaBundle:
    """Return the loaded API-15 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=memory_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


class MemoryScope(KernelModel):
    """One memory scope: its kind, its treatment mode, and its owner."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-15.memory-scope")
    )
    scope_kind: MemoryScopeName
    treatment_mode: MemoryModeName
    owner_enrollment_id: EnrollmentId


class MemoryRead(KernelModel):
    """A read of one memory value: its content digest and the base version read."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-15.memory-read")
    )
    memory_id: MemorySnapshotId
    scope_kind: MemoryScopeName
    content_digest: Digest
    base_version: VersionStamp
    read_at: UtcInstant


class MemoryProposal(KernelModel):
    """A proposed new memory value, keyed to the base version it read."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-15.memory-proposal")
    )
    memory_id: MemorySnapshotId
    scope_kind: MemoryScopeName
    proposed_digest: Digest
    base_version: VersionStamp
    provenance_decision_id: DecisionId


class MemoryCommit(KernelModel):
    """A committed memory value: the applied swap from a prior to a new version."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-15.memory-commit")
    )
    memory_id: MemorySnapshotId
    scope_kind: MemoryScopeName
    committed_digest: Digest
    prior_version: VersionStamp
    new_version: VersionStamp
    provenance_decision_id: DecisionId

    @model_validator(mode="after")
    def _version_advances_by_one(self) -> MemoryCommit:
        if self.new_version.revision != self.prior_version.revision + 1:
            raise ValueError("a commit must advance the memory version by one revision")
        return self
