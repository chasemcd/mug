"""Visits, plans, treatment, exposure, and state (API-04, layer L1).

This family owns the runtime ``Visit``, the materialized ``VisitPlan``, the
``TreatmentPlan`` design and its records (``TreatmentAssignment`` intent and
``TreatmentExposure`` delivery), the ``AllocationState`` counter, the per-visit
``StateDocument``, and the flow-level ``EligibilityCallback``. Each record
references the kernel (L0) references; the family adds no runtime.
"""

from __future__ import annotations

from mug.visits.service import (
    AdvanceVisitCommand,
    StartVisitCommand,
    advance_visit,
    start_visit,
)
from mug.visits.types import (
    AllocationState,
    EligibilityCallback,
    StateDocument,
    TreatmentAssignment,
    TreatmentExposure,
    TreatmentPlan,
    Visit,
    VisitPlan,
    visits_schema,
)

__all__ = [
    "AdvanceVisitCommand",
    "AllocationState",
    "EligibilityCallback",
    "StartVisitCommand",
    "StateDocument",
    "TreatmentAssignment",
    "TreatmentExposure",
    "TreatmentPlan",
    "Visit",
    "VisitPlan",
    "advance_visit",
    "start_visit",
    "visits_schema",
]
