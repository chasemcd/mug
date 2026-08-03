"""Content, forms, presentation, and gating (API-17, layer L1).

This family owns the authored ``ContentSpec`` and its ``ContentBody``, the
``FormSpec`` and its submitted ``FormResponse``, the shipped
``PresentationComponent``, the ``GateControl`` readiness control (RP-8), and the
``AccessibilityProfile``. Each shipped object references the kernel (L0) schema
and digest types.

The ``service`` module runs the single-participant flow over these records: it
materializes a flow for a visit, presents the active activity, and advances the
pointer as the participant answers each form.

The ``study`` module is the author's own surface: ``Study`` and the steps it holds,
and ``players`` holds the three kinds a seating names -- ``Human``, ``Model``, and
``Bot``. Both are re-exported here, so a whole study is written from one import.
The author's ``Comparison`` (``mug.authoring``) and the treatment vocabulary
(``mug.visits.design``) are steps and placements of the same study, so both are
re-exported here and a study is written from one import.
"""

from __future__ import annotations

from mug.content.players import Bot, Human, Model
from mug.content.service import (
    AdvanceFlowCommand,
    FlowState,
    MaterializeFlowCommand,
    advance_flow,
    demo_study,
    flow_of,
    materialize_flow,
    plan_of,
    present,
)
from mug.content.study import (
    Activity,
    Assign,
    Chat,
    Choice,
    Comparison,
    Conversation,
    Design,
    Execution,
    Form,
    Game,
    GameActivity,
    Likert,
    Order,
    Page,
    Placement,
    Rounds,
    Scope,
    Screen,
    Step,
    Study,
    Text,
    Treatment,
    Unit,
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
    "Activity",
    "AdvanceFlowCommand",
    "Assign",
    "Bot",
    "Chat",
    "Choice",
    "Comparison",
    "ContentBody",
    "ContentSpec",
    "Conversation",
    "Design",
    "Execution",
    "FlowState",
    "Form",
    "FormResponse",
    "FormSpec",
    "Game",
    "GameActivity",
    "GateControl",
    "Human",
    "Likert",
    "MaterializeFlowCommand",
    "Model",
    "Order",
    "Page",
    "Placement",
    "PresentationComponent",
    "Rounds",
    "Scope",
    "Screen",
    "Step",
    "Study",
    "Text",
    "Treatment",
    "Unit",
    "advance_flow",
    "content_schema",
    "demo_study",
    "flow_of",
    "materialize_flow",
    "plan_of",
    "present",
]
