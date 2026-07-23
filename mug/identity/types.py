"""The three records that API-03 owns: enrollment, launch ticket, and link.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``identity_schema`` loads it for the conformance test.

This family models the enrollment record, the launch ticket that admits a
participant to a deployment, and the external identity link. It adds no runtime.
The principal, deployment, and privacy references all live in the kernel (L0).

Two invariants are not expressible in JSON Schema and live here as validators:

- an enrollment principal is always a participant;
- an external identity link carries a pii privacy label.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from mug.kernel import (
    DataHandlingRef,
    Digest,
    PrincipalRef,
    PublicHandle,
    SchemaBundle,
    SchemaRef,
    UtcInstant,
    VersionStamp,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import EnrollmentId, StudyId
from mug.kernel.refs import DeploymentRevisionRef

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-03/schemas/v0/identity-enrollment.schema.json"
)


@lru_cache(maxsize=1)
def identity_schema() -> SchemaBundle:
    """Return the loaded API-03 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=identity_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


class Enrollment(KernelModel):
    """One participant's enrolment in a study: identity, status, and version."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-03.enrollment")
    )
    enrollment_id: EnrollmentId
    study_id: StudyId
    principal: PrincipalRef
    status: Literal["active", "withdrawn", "completed"]
    created_at: UtcInstant
    version: VersionStamp

    @model_validator(mode="after")
    def _principal_is_participant(self) -> Enrollment:
        if self.principal.kind != "participant":
            raise ValueError("an enrollment principal must be a participant")
        return self


class LaunchTicket(KernelModel):
    """A time-bound admission to run one deployment of a study."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-03.launch-ticket")
    )
    ticket_handle: PublicHandle
    study_id: StudyId
    deployment: DeploymentRevisionRef
    issued_at: UtcInstant
    expires_at: UtcInstant


class ExternalIdentityLink(KernelModel):
    """A link from an enrolment to an external provider's subject handle."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-03.external-identity-link")
    )
    enrollment_id: EnrollmentId
    provider: Literal["prolific", "mturk", "oidc", "institution", "contact"]
    external_subject_handle: PublicHandle
    data_handling: DataHandlingRef

    @model_validator(mode="after")
    def _link_carries_pii_label(self) -> ExternalIdentityLink:
        if "pii" not in self.data_handling.privacy_labels:
            raise ValueError("an external identity link must carry a pii label")
        return self
