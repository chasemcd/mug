"""The three records that API-22 owns: job request, run, and result.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``jobs_schema`` loads it for the conformance test.

This family models the durable job records and the leased run state machine, but
adds no runtime. The worker, the queue, the heartbeat, and lease acquisition stay
deferred (review decisions A22-O01..O03). ``JobRun.lease`` reuses the kernel
``LeaseRef`` fencing token.

Two invariants are not expressible in JSON Schema and live here as validators:

- a succeeded run names its result digest;
- a successful result names its artifact reference.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    ArtifactRef,
    Digest,
    LeaseRef,
    SchemaBundle,
    SchemaRef,
    UtcInstant,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import JobId
from mug.kernel.refs import PositiveSafeInteger

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-22/schemas/v0/jobs.schema.json"
)

FirstClassJobKind = Literal[
    "compile-at-publish", "simulate-batch", "export-bundle-build", "replay-bundle-build"
]
"""The registry of first-class job kinds in version 0. ``job_kind`` is an open
key, so any authoring key is legal; these are the named, first-class members."""


@lru_cache(maxsize=1)
def jobs_schema() -> SchemaBundle:
    """Return the loaded API-22 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=jobs_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]


class JobRequest(KernelModel):
    """An idempotent submission of one unit of work, keyed by its content."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-22.job-request")
    )
    job_id: JobId
    job_kind: _AuthoringKey
    work_key: Digest
    submitted_at: UtcInstant
    priority: Literal["low", "normal", "high"] | None = None


class JobRun(KernelModel):
    """One leased attempt at running a job, with its fenced lease and status."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-22.job-run")
    )
    job_id: JobId
    attempt: PositiveSafeInteger
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    lease: LeaseRef
    result_digest: Digest | None = None
    started_at: UtcInstant | None = None

    @model_validator(mode="after")
    def _succeeded_names_result(self) -> JobRun:
        if self.status == "succeeded" and self.result_digest is None:
            raise ValueError("a succeeded run must name its result digest")
        return self


class JobResult(KernelModel):
    """The single durable result per work key, tying back to the request."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-22.job-result")
    )
    job_id: JobId
    work_key: Digest
    outcome: Literal["success", "failure"]
    result_ref: ArtifactRef | None = None
    completed_at: UtcInstant

    @model_validator(mode="after")
    def _success_names_artifact(self) -> JobResult:
        if self.outcome == "success" and self.result_ref is None:
            raise ValueError("a successful result must name its artifact reference")
        return self
