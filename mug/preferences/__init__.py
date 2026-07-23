"""Preferences, annotation, and quality (API-18, layer L1).

This family owns five record types: the ``PreferenceProtocol`` that declares a
comparison, the ``CandidateRef`` that names an opaque candidate, the blinded
``PreferenceAssignment``, the recorded ``PreferenceResponse``, and the
per-response ``QualityEvidence``. Each record references the kernel (L0); the
family adds no runtime.
"""

from __future__ import annotations

from mug.preferences.compile import (
    ComparisonIds,
    CompiledComparison,
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
    PreferenceAssignment,
    PreferenceProtocol,
    PreferenceResponse,
    QualityEvidence,
    preferences_schema,
)

__all__ = [
    "CandidateRef",
    "ComparisonIds",
    "CompiledComparison",
    "PreferenceAssignment",
    "PreferenceProtocol",
    "PreferenceResponse",
    "PreferenceService",
    "QualityEvidence",
    "ResponseRequired",
    "UnknownAssignment",
    "candidate_from_artifact",
    "compile_comparison",
    "display_order",
    "preferences_schema",
]
