"""The five records that API-14 owns: tool version, call, approval, result, mailbox.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``tools_schema`` loads it for the conformance test.

This family models the tool registry version, the gated tool call, the human
approval, the executed result, and the environment command mailbox. It adds no
runtime. The tool broker, the approval workflow, and command delivery stay
deferred.

Two invariants are not expressible in JSON Schema and live here as validators on
``ToolResult``:

- an executed result names its result digest;
- an executed result that needs approval names its approval digest.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    Digest,
    IdempotencyKey,
    PrincipalRef,
    SchemaBundle,
    SchemaRef,
    UtcInstant,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import (
    InteractionId,
    ToolCallId,
    ToolDefinitionId,
    ToolVersionId,
)

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-14/schemas/v0/tools.schema.json"
)


@lru_cache(maxsize=1)
def tools_schema() -> SchemaBundle:
    """Return the loaded API-14 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=tools_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]

_Hostname = Annotated[
    str,
    Field(
        pattern=r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$",
        max_length=255,
    ),
]


class ToolVersion(KernelModel):
    """One immutable tool version: kind, mutation class, gate, and egress allowlist."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-14.tool-version")
    )
    tool_version_id: ToolVersionId
    tool_definition_id: ToolDefinitionId
    tool_kind: Literal["native", "mcp"]
    mutating: bool
    approval_gate: bool
    egress_allowlist: Annotated[list[_Hostname], Field(max_length=64)]


class ToolCall(KernelModel):
    """One idempotent request to run a tool version, with its gate flags."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-14.tool-call")
    )
    tool_call_id: ToolCallId
    tool_version_id: ToolVersionId
    arguments_digest: Digest
    idempotency_key: IdempotencyKey
    mutating: bool
    approval_required: bool


class ToolApproval(KernelModel):
    """One human decision on a gated tool call: who decided, what, and when."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-14.tool-approval")
    )
    tool_call_id: ToolCallId
    approver: PrincipalRef
    decision: Literal["approved", "denied"]
    decided_at: UtcInstant


class ToolResult(KernelModel):
    """The outcome of a tool call: what happened, its effect, and its evidence."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-14.tool-result")
    )
    tool_call_id: ToolCallId
    outcome: Literal["executed", "denied", "failed"]
    effect: Literal["none", "mutating"]
    approval_required: bool
    approval_digest: Digest | None = None
    result_digest: Digest | None = None
    executed_at: UtcInstant

    @model_validator(mode="after")
    def _executed_names_evidence(self) -> ToolResult:
        if self.outcome != "executed":
            return self
        if self.result_digest is None:
            raise ValueError("an executed result must name its result digest")
        if self.approval_required and self.approval_digest is None:
            raise ValueError("a gated executed result must name its approval digest")
        return self


class EnvironmentCommandMailbox(KernelModel):
    """One environment command queued to an interaction, keyed and delivery-tracked."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-14.environment-command-mailbox")
    )
    interaction_id: InteractionId
    command_key: _AuthoringKey
    delivered: bool
    enqueued_at: UtcInstant
