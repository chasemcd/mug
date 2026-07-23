"""Events, capture, and provenance (API-10, layer L1).

This family owns three record types: the canonical ``EventEnvelope``, the
``CapturePolicy`` that declares which streams a session captures, and the
``ExperiencedFrame`` that records what a participant actually saw. Each record
references the kernel (L0) position types; the family adds no runtime.
"""

from __future__ import annotations

from mug.events.types import (
    CapturePolicy,
    CaptureStreamRule,
    EventEnvelope,
    ExperiencedFrame,
    events_schema,
)

__all__ = [
    "CapturePolicy",
    "CaptureStreamRule",
    "EventEnvelope",
    "ExperiencedFrame",
    "events_schema",
]
