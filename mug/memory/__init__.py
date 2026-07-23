"""Experimental agent memory (API-15, layer L1).

This family owns four record types: the ``MemoryScope`` that declares a scope and
its treatment mode, and the ``MemoryRead``, ``MemoryProposal``, and
``MemoryCommit`` records of the compare-and-swap cycle over a memory value. Each
record references the kernel (L0) digest and version types.

``mug.memory.runtime`` adds the memory runtime over these records: the
``MemoryLedger`` reads the current value and commits a compare-and-swap through the
command spine, refusing a stale swap with ``StaleMemoryVersion`` rather than
retrying.
"""

from __future__ import annotations

from mug.memory.runtime import MemoryLedger, StaleMemoryVersion
from mug.memory.types import (
    MemoryCommit,
    MemoryProposal,
    MemoryRead,
    MemoryScope,
    memory_schema,
)

__all__ = [
    "MemoryCommit",
    "MemoryLedger",
    "MemoryProposal",
    "MemoryRead",
    "MemoryScope",
    "StaleMemoryVersion",
    "memory_schema",
]
