"""The domain-error taxonomy.

A boundary returns a ``DomainError`` or a receipt, never a bare failure. The
error carries a stable machine code, a broad category, a safe human message, and
a retry directive. It never carries a provider stack trace, a credential, prompt
text, or protected participant data.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from mug.kernel._base import KernelModel

# The command-type reference is defined in command.py; import it lazily to avoid
# a cycle by re-declaring the small shape here is not needed — errors reference
# it only structurally through the model below.
from mug.kernel.command_types import CommandTypeRef
from mug.kernel.ids import ErrorId, RequestId
from mug.kernel.refs import DomainErrorSchemaRef, UtcInstant
from mug.kernel.typed_object import TypedObject

ErrorCategory = Literal[
    "protocol",
    "validation",
    "authentication",
    "authorization",
    "not_found",
    "conflict",
    "stale",
    "deadline",
    "unsupported",
    "rate_limit",
    "backpressure",
    "dependency",
    "integrity",
    "privacy",
    "internal",
]

RetryMode = Literal[
    "never",
    "same_command",
    "poll_existing",
    "refresh_then_new_command",
    "after_reauthentication",
    "operator_reconciliation",
]

# The stable error codes. Each code owns one registered details schema.
ERROR_CODES: tuple[str, ...] = (
    "protocol.invalid_envelope",
    "protocol.unsupported_version",
    "schema.validation_failed",
    "auth.unauthenticated",
    "auth.forbidden",
    "resource.not_found",
    "resource.already_exists",
    "command.idempotency_conflict",
    "command.revision_conflict",
    "command.state_conflict",
    "command.uniqueness_conflict",
    "command.deadline_exceeded",
    "command.cancelled",
    "lease.expired",
    "lease.stale_generation",
    "decision.stale_generation",
    "sequence.gap",
    "sequence.conflict",
    "sequence.stale",
    "event.cursor_expired",
    "capability.unsupported",
    "quota.rate_limited",
    "quota.budget_exceeded",
    "runtime.backpressure",
    "dependency.unavailable",
    "external.unknown_outcome",
    "artifact.integrity_failed",
    "artifact.unavailable",
    "privacy.policy_violation",
    "internal.unexpected",
)


class RetryDirective(KernelModel):
    """How a caller may retry: a mode and an optional delay in milliseconds."""

    mode: RetryMode
    retry_after_ms: Annotated[int, Field(ge=0, le=86400000)] | None = None


class DomainError(KernelModel):
    """A safe, typed error envelope returned across a boundary."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: DomainErrorSchemaRef  # pyright: ignore[reportIncompatibleMethodOverride]
    error_id: ErrorId
    request_id: RequestId | None = None
    recorded_at: UtcInstant
    command: CommandTypeRef | None = None
    code: Annotated[
        str, Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$", max_length=128)
    ]
    category: ErrorCategory
    safe_message: Annotated[str, Field(min_length=1, max_length=512)]
    retry: RetryDirective
    details: TypedObject | None = None
    support_reference: ErrorId
