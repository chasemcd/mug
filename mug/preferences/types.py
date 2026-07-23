"""The five records that API-18 owns: protocol, candidate, assignment, response,
and quality evidence.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``preferences_schema`` loads it for the conformance test.

This family models the preference protocol and its blinded, randomized query
records, but adds no runtime. The assignment machinery, the seed reveal, and the
receipt flow stay deferred (review decisions D12-3..D12-5).

Two invariants are not expressible in JSON Schema and live here as validators:

- an assignment lists each candidate once in its display order;
- a response names a choice that was one of the presented candidates.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    ArtifactRef,
    Digest,
    PublicHandle,
    SchemaBundle,
    SchemaRef,
    UtcInstant,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import (
    EnrollmentId,
    PreferenceAssignmentId,
    PreferenceProtocolDefinitionId,
    PreferenceProtocolVersionId,
    PreferenceQueryId,
    PreferenceResponseId,
)
from mug.kernel.refs import NonNegativeSafeInteger

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-18/schemas/v0/preference.schema.json"
)


@lru_cache(maxsize=1)
def preferences_schema() -> SchemaBundle:
    """Return the loaded API-18 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=preferences_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]

_CandidateKind = Literal[
    "trajectory", "model-output", "chat-message", "conversation-segment", "media"
]


class ComparisonTask(KernelModel):
    """The comparison task a protocol asks for: a typed kind and an optional prompt."""

    kind: Literal["pairwise", "rating"]
    prompt: Annotated[str, Field(min_length=1, max_length=1024)] | None = None


class PreferenceProtocol(KernelModel):
    """A blinded, randomized comparison protocol over one candidate kind."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-18.preference-protocol")
    )
    protocol_version_id: PreferenceProtocolVersionId
    protocol_definition_id: PreferenceProtocolDefinitionId
    candidate_kind: _CandidateKind
    task: ComparisonTask
    blinded: bool
    randomize_order: bool


class CandidateRef(KernelModel):
    """One comparison candidate: an authoring key over an opaque content reference."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-18.candidate-ref")
    )
    candidate_key: _AuthoringKey
    kind: _CandidateKind
    content_ref: ArtifactRef
    display_handle: PublicHandle


class PreferenceAssignment(KernelModel):
    """One participant's blinded, ordered assignment of candidates for a query."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-18.preference-assignment")
    )
    assignment_id: PreferenceAssignmentId
    query_id: PreferenceQueryId
    enrollment_id: EnrollmentId
    candidate_display_order: Annotated[
        list[_AuthoringKey], Field(min_length=2, max_length=64)
    ]
    blinded: bool
    seed_commitment: Digest

    @model_validator(mode="after")
    def _display_order_has_no_duplicates(self) -> PreferenceAssignment:
        seen: set[str] = set()
        for key in self.candidate_display_order:
            if key in seen:
                raise ValueError(
                    "candidate display order must list each candidate once"
                )
            seen.add(key)
        return self


class PreferenceResponse(KernelModel):
    """A recorded choice over the order a participant was shown."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-18.preference-response")
    )
    response_id: PreferenceResponseId
    assignment_id: PreferenceAssignmentId
    choice: _AuthoringKey
    presented_order: Annotated[
        list[_AuthoringKey], Field(min_length=2, max_length=64)
    ]
    receipt_required: bool
    submitted_at: UtcInstant

    @model_validator(mode="after")
    def _choice_was_presented(self) -> PreferenceResponse:
        if self.choice not in self.presented_order:
            raise ValueError(
                "the recorded choice must be one of the presented candidates"
            )
        return self


class QualityEvidence(KernelModel):
    """Per-response quality signals: attention, response time, and a flag."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-18.quality-evidence")
    )
    response_id: PreferenceResponseId
    attention_check_passed: bool
    response_time_ms: NonNegativeSafeInteger
    flagged: bool
