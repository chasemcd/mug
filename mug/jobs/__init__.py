"""Durable jobs and workers (API-22, layer L1).

This family owns three records: the idempotent ``JobRequest``, the leased
``JobRun`` attempt, and the single durable ``JobResult`` per work key. It reuses
the kernel (L0) lease and digest types and adds no worker runtime.
"""

from __future__ import annotations

from mug.jobs.types import (
    FirstClassJobKind,
    JobRequest,
    JobResult,
    JobRun,
    jobs_schema,
)

__all__ = [
    "FirstClassJobKind",
    "JobRequest",
    "JobResult",
    "JobRun",
    "jobs_schema",
]
