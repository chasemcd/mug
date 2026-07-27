"""Preferences, annotation, and quality (API-18, layer L1).

This family owns five record types: the ``PreferenceProtocol`` that declares a
comparison, the ``CandidateRef`` that names an opaque candidate, the blinded
``PreferenceAssignment``, the recorded ``PreferenceResponse``, and the
per-response ``QualityEvidence``. Each record references the kernel (L0).

A response says more than which candidate won. ``verdict`` admits a tie without a
phantom choice, and ``ratings`` carries the per-dimension answers a protocol asked
for -- each named by the candidate key it is about, never by a screen position.
"""

from __future__ import annotations

from mug.preferences.compile import (
    ComparisonIds,
    CompiledComparison,
    candidate_key_for,
    compile_comparison,
)
from mug.preferences.runtime import (
    PreferenceService,
    ResponseRequired,
    UnknownAssignment,
    candidate_from_artifact,
    display_order,
)
from mug.preferences.types import (
    CandidateRef,
    ComparisonTask,
    Dimension,
    DimensionRating,
    PreferenceAssignment,
    PreferenceProtocol,
    PreferenceResponse,
    QualityEvidence,
    preferences_schema,
)

__all__ = [
    "CandidateRef",
    "ComparisonIds",
    "ComparisonTask",
    "CompiledComparison",
    "Dimension",
    "DimensionRating",
    "PreferenceAssignment",
    "PreferenceProtocol",
    "PreferenceResponse",
    "PreferenceService",
    "QualityEvidence",
    "ResponseRequired",
    "UnknownAssignment",
    "candidate_from_artifact",
    "candidate_key_for",
    "compile_comparison",
    "display_order",
    "preferences_schema",
]
