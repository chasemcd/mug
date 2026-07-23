"""Storage, artifacts, transactions, and outbox (API-11, layer L1).

This family owns four persisted objects and one in-memory backend. The backend's
``commit`` writes aggregate state, the idempotency record, the canonical events,
and the outbox together. It depends only on the kernel (L0).
"""

from __future__ import annotations

from mug.storage.ports import ArtifactStore, Store
from mug.storage.sqlite_store import SqliteStore
from mug.storage.store import InMemoryStore, StorageError, digest_of
from mug.storage.types import (
    ArtifactStaging,
    FinalizedArtifact,
    OutboxRecord,
    UnitOfWorkReceipt,
    storage_schema,
)

__all__ = [
    "ArtifactStaging",
    "ArtifactStore",
    "FinalizedArtifact",
    "InMemoryStore",
    "OutboxRecord",
    "SqliteStore",
    "StorageError",
    "Store",
    "UnitOfWorkReceipt",
    "digest_of",
    "storage_schema",
]
