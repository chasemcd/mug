"""The wire command envelope and the command receipt.

A gateway receives a ``WireCommandEnvelope``, verifies it, and builds a trusted
context (not modeled here — the context is a runtime structure). A handler
answers with a ``CommandReceipt``: an ingress, commit, or artifact-commit
receipt. The receipt class and the outcome together fix the durability rules.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel._base import KernelModel
from mug.kernel.clock import ProducerPosition, StreamPositions
from mug.kernel.command_types import CommandPreconditions, CommandTypeRef
from mug.kernel.errors import DomainError
from mug.kernel.ids import CommandId, ReceiptId, RequestId
from mug.kernel.refs import (
    CommandEnvelopeSchemaRef,
    CommandReceiptSchemaRef,
    ResourceRef,
    SemVer,
    UtcInstant,
    VersionStamp,
)
from mug.kernel.typed_object import TypedObject

IdempotencyKey = Annotated[
    str, Field(pattern=r"^idem_[A-Za-z0-9_-]{21}[AQgw]$", max_length=27)
]


class WireCommandEnvelope(KernelModel):
    """An untrusted command as received at the wire boundary.

    The envelope never carries a trusted principal, enrollment, or visit. The
    gateway derives those from verified state.
    """

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: CommandEnvelopeSchemaRef  # pyright: ignore[reportIncompatibleMethodOverride]
    protocol_version: SemVer
    command: CommandTypeRef
    request_id: RequestId
    idempotency_key: IdempotencyKey
    target: ResourceRef
    preconditions: CommandPreconditions | None = None
    producer: ProducerPosition | None = None
    lease_token: Annotated[str, Field(min_length=32, max_length=2048)] | None = None
    timeout_ms: Annotated[int, Field(ge=1, le=86400000)] | None = None
    client_observed_at: UtcInstant | None = None
    payload: TypedObject


class ReceiptDurability(KernelModel):
    """The durability of a receipt and of the effect it acknowledges."""

    receipt: Literal["runtime", "journaled", "transactional"]
    effect: Literal[
        "none", "runtime", "journaled", "transactional", "artifact_committed", "unknown"
    ]
    profile: Annotated[
        str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=96)
    ]


class CommandReceipt(KernelModel):
    """The durable answer to a command.

    ``receipt_class`` and ``outcome`` fix the durability and stream-position
    rules. An accepted receipt carries a result; a rejected or indeterminate
    receipt carries an error.
    """

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: CommandReceiptSchemaRef  # pyright: ignore[reportIncompatibleMethodOverride]
    receipt_id: ReceiptId
    command_id: CommandId
    command: CommandTypeRef
    idempotency_key: IdempotencyKey
    outcome: Literal["accepted", "rejected", "indeterminate"]
    receipt_class: Literal["ingress", "commit", "artifact_commit"]
    durability: ReceiptDurability
    recorded_at: UtcInstant
    resource: ResourceRef | None = None
    version_stamp: VersionStamp | None = None
    stream_positions: StreamPositions
    result: TypedObject | None = None
    error: DomainError | None = None

    @model_validator(mode="after")
    def _enforce_receipt_rules(self) -> CommandReceipt:
        self._check_result_error_pairing()
        self._check_durability_rules()
        return self

    def _check_result_error_pairing(self) -> None:
        if self.outcome == "accepted":
            if self.result is None or self.error is not None:
                raise ValueError("an accepted receipt carries a result and no error")
        elif self.error is None or self.result is not None:
            raise ValueError(
                "a rejected or indeterminate receipt carries an error and no result"
            )

    def _check_durability_rules(self) -> None:
        durability = self.durability
        stream_count = len(self.stream_positions)

        if self.outcome == "accepted" and self.receipt_class == "ingress":
            if durability.receipt not in ("runtime", "journaled"):
                raise ValueError("an ingress receipt is runtime or journaled")
            if durability.effect not in ("runtime", "journaled"):
                raise ValueError("an ingress effect is runtime or journaled")
        elif self.outcome == "accepted" and self.receipt_class == "commit":
            if (
                durability.receipt != "transactional"
                or durability.effect != "transactional"
            ):
                raise ValueError("a commit receipt is transactional")
            if stream_count < 1:
                raise ValueError(
                    "a commit receipt records at least one stream position"
                )
        elif self.outcome == "accepted" and self.receipt_class == "artifact_commit":
            if (
                durability.receipt != "transactional"
                or durability.effect != "artifact_committed"
            ):
                raise ValueError(
                    "an artifact-commit receipt commits an artifact transactionally"
                )
            if stream_count < 1:
                raise ValueError(
                    "an artifact-commit receipt records at least one stream position"
                )
        elif self.outcome == "rejected":
            if durability.effect != "none":
                raise ValueError("a rejected receipt has no effect")
        elif self.outcome == "indeterminate":
            if self.receipt_class != "commit":
                raise ValueError("an indeterminate receipt is a commit receipt")
            if durability.receipt != "transactional" or durability.effect != "unknown":
                raise ValueError(
                    "an indeterminate receipt is transactional with an unknown effect"
                )
            if (
                self.error is not None
                and self.error.retry.mode != "operator_reconciliation"
            ):
                raise ValueError(
                    "an indeterminate error requires operator reconciliation"
                )
