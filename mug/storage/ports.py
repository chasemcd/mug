"""The repository Protocol the runtime and handlers depend on.

The spine and the command handlers speak to storage through this narrow surface,
never a concrete backend. The in-memory backend and the sqlite backend both
satisfy it structurally, and the production asyncpg backend implements the same
methods. The Protocol was extracted only once a second backend existed.

The writes are async; the reads are synchronous, because the runtime reads
positions and the ledger while it assembles a receipt.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

from mug.storage.types import (
    ArtifactStaging,
    FinalizedArtifact,
    OutboxRecord,
    UnitOfWorkReceipt,
)


class Store(Protocol):
    """The storage surface a command needs to commit state and read it back."""

    async def commit(
        self,
        *,
        command_id: str,
        idempotency_key: str,
        aggregate_id: str,
        expected_revision: int | None,
        new_state: Any,
        event_ids: Sequence[str] = ...,
        stream_events: Sequence[tuple[str, str]] = ...,
        event_details: Mapping[str, Any] | None = ...,
        outbox: Sequence[OutboxRecord] = ...,
        producer_generation: int | None = ...,
        durability_profile: str,
    ) -> UnitOfWorkReceipt: ...

    async def issue_token(
        self,
        *,
        command_id: str,
        idempotency_key: str,
        handle: str,
        new_state: Any,
        stream_events: Sequence[tuple[str, str]] = ...,
        event_details: Mapping[str, Any] | None = ...,
        outbox: Sequence[OutboxRecord] = ...,
        producer_generation: int | None = ...,
    ) -> dict[str, int]: ...

    def positions_for(self, idempotency_key: str) -> dict[str, int]: ...

    def stream_records(
        self, stream_id: str, after_sequence: int = ...
    ) -> list[dict[str, Any]]: ...

    def load_aggregate(self, aggregate_id: str) -> Any | None: ...

    def scan_aggregates(self) -> list[tuple[str, Any]]: ...

    def load_token(self, handle: str) -> Any | None: ...

    def revision_of(self, aggregate_id: str) -> int | None: ...


class ArtifactStore(Protocol):
    """The object-store surface a producer needs to persist and read blobs.

    The command spine speaks only to ``Store``; a caller that stages a bundle
    artifact (a replay bundle, an export document) needs the content-addressed
    object store beside it. Every concrete backend implements both, so one instance
    satisfies both Protocols; the seam is separate so a caller declares exactly the
    surface it uses.
    """

    async def finalize_artifact(
        self,
        staging: ArtifactStaging,
        data: bytes,
        *,
        artifact_id: str,
        finalized_at: str,
        content_encoding: Literal["identity", "gzip", "zstd", "br"] = ...,
    ) -> FinalizedArtifact: ...

    async def read_artifact(self, artifact_id: str) -> bytes: ...
