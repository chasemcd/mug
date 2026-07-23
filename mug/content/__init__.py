"""Content, forms, presentation, and gating (API-17, layer L1).

This family owns the authored ``ContentSpec`` and its ``ContentBody``, the
``FormSpec`` and its submitted ``FormResponse``, the shipped
``PresentationComponent``, the ``GateControl`` readiness control (RP-8), and the
``AccessibilityProfile``. Each shipped object references the kernel (L0) schema
and digest types.

The ``service`` module runs the single-participant flow over these records: it
materializes a flow for a visit, presents the active activity, and advances the
pointer as the participant answers each form.
"""

from __future__ import annotations

from mug.content.service import (
    AdvanceFlowCommand,
    FlowState,
    MaterializeFlowCommand,
    advance_flow,
    materialize_flow,
    present,
)
from mug.content.types import (
    AccessibilityProfile,
    ContentBody,
    ContentSpec,
    FormResponse,
    FormSpec,
    GateControl,
    PresentationComponent,
    content_schema,
)

__all__ = [
    "AccessibilityProfile",
    "AdvanceFlowCommand",
    "ContentBody",
    "ContentSpec",
    "FlowState",
    "FormResponse",
    "FormSpec",
    "GateControl",
    "MaterializeFlowCommand",
    "PresentationComponent",
    "advance_flow",
    "content_schema",
    "materialize_flow",
    "present",
]
