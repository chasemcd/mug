"""A second storage backend on the standard-library sqlite3.

This backend proves the ``Store`` Protocol with real persistence and identical
semantics to the in-memory backend: idempotent replay, the revision and existence
guards, producer-epoch fencing, stream positions, the event ledger, and tokens.
It shares the pure fingerprint, receipt, and position logic, so the two backends
never drift. The production asyncpg backend follows the same shape.

The writes are ``async`` to match the Protocol but do synchronous sqlite work, as
the in-memory backend does; a genuine asyncpg backend awaits its driver instead.
The object store and the outbox stay with the in-memory backend for now.

**One database, one connection per thread.** A deployment does not keep its store
on the thread that built it: a server runs it from the event-loop thread while a
worker or an operator command drives it from another. A sqlite connection belongs
to the thread that opened it, so each thread opens its own and sqlite does the
locking between them, which is what it is for. Without this the store raises as
soon as a second thread reads it, and the run it recorded is unreachable.

An in-memory database is private to its connection, so the memory case is opened
through a shared-cache URI and one connection is held open for the lifetime of the
store. Otherwise each thread would get a database of its own and a run written by
one would be invisible to the next.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from mug.storage.store import (
    StorageError,
    build_finalized_artifact,
    build_uow_receipt,
    commit_fingerprint,
    plan_appends,
    token_fingerprint,
)
from mug.storage.types import (
    ArtifactStaging,
    FinalizedArtifact,
    OutboxRecord,
    UnitOfWorkReceipt,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS aggregates(
    aggregate_id TEXT PRIMARY KEY, revision INTEGER, state TEXT);
CREATE TABLE IF NOT EXISTS receipts(
    idempotency_key TEXT PRIMARY KEY, fingerprint TEXT, receipt TEXT);
CREATE TABLE IF NOT EXISTS tokens(handle TEXT PRIMARY KEY, state TEXT);
CREATE TABLE IF NOT EXISTS token_fp(
    idempotency_key TEXT PRIMARY KEY, fingerprint TEXT);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT);
CREATE TABLE IF NOT EXISTS stream_heads(stream_id TEXT PRIMARY KEY, head INTEGER);
CREATE TABLE IF NOT EXISTS positions(
    idempotency_key TEXT, stream_id TEXT, sequence INTEGER);
CREATE TABLE IF NOT EXISTS fencing(stream_id TEXT PRIMARY KEY, generation INTEGER);
CREATE TABLE IF NOT EXISTS ledger(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id TEXT, sequence INTEGER, record TEXT);
CREATE TABLE IF NOT EXISTS objects(artifact_id TEXT PRIMARY KEY, data BLOB);
CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, record TEXT);
"""


class SqliteStore:
    """A relational Unit of Work on sqlite, with the same semantics as memory."""

    def __init__(self, path: str = ":memory:") -> None:
        if path == ":memory:":
            self._name = f"file:mug-{id(self):x}?mode=memory&cache=shared"
            self._uri = True
        else:
            self._name = path
            self._uri = False
        self._local = threading.local()
        # One connection outlives every thread's own. A shared-cache in-memory
        # database exists only while a connection to it is open, so this is what
        # keeps the store from disappearing between two callers.
        self._kept = self._connect()
        self._kept.executescript(_SCHEMA)
        self._kept.commit()

    def _connect(self) -> sqlite3.Connection:
        """Open one connection to this store's database."""
        return sqlite3.connect(self._name, uri=self._uri)

    @property
    def _db(self) -> sqlite3.Connection:
        """Return this thread's own connection, opening it the first time."""
        found: sqlite3.Connection | None = getattr(self._local, "db", None)
        if found is None:
            found = self._connect()
            self._local.db = found
        return found

    def close(self) -> None:
        """Close this thread's connection and the one the store keeps open."""
        found: sqlite3.Connection | None = getattr(self._local, "db", None)
        if found is not None:
            found.close()
            self._local.db = None
        self._kept.close()

    # --- reads --------------------------------------------------------------
    def _heads(self) -> dict[str, int]:
        rows = self._db.execute("SELECT stream_id, head FROM stream_heads")
        return {stream_id: head for stream_id, head in rows}

    def positions_for(self, idempotency_key: str) -> dict[str, int]:
        rows = self._db.execute(
            "SELECT stream_id, sequence FROM positions WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        return {stream_id: sequence for stream_id, sequence in rows}

    def stream_records(
        self, stream_id: str, after_sequence: int = 0
    ) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT record FROM ledger WHERE stream_id = ? AND sequence > ? "
            "ORDER BY sequence",
            (stream_id, after_sequence),
        )
        return [json.loads(record) for (record,) in rows]

    def load_aggregate(self, aggregate_id: str) -> Any | None:
        row = self._db.execute(
            "SELECT state FROM aggregates WHERE aggregate_id = ?", (aggregate_id,)
        ).fetchone()
        return json.loads(row[0]) if row is not None else None

    def scan_aggregates(self) -> list[tuple[str, Any]]:
        rows = self._db.execute("SELECT aggregate_id, state FROM aggregates")
        return [(aggregate_id, json.loads(state)) for aggregate_id, state in rows]

    def load_token(self, handle: str) -> Any | None:
        row = self._db.execute(
            "SELECT state FROM tokens WHERE handle = ?", (handle,)
        ).fetchone()
        return json.loads(row[0]) if row is not None else None

    def revision_of(self, aggregate_id: str) -> int | None:
        row = self._db.execute(
            "SELECT revision FROM aggregates WHERE aggregate_id = ?", (aggregate_id,)
        ).fetchone()
        return row[0] if row is not None else None

    def stream_head(self, stream_id: str) -> int:
        row = self._db.execute(
            "SELECT head FROM stream_heads WHERE stream_id = ?", (stream_id,)
        ).fetchone()
        return row[0] if row is not None else 0

    def installed_generation(self, stream_id: str) -> int:
        row = self._db.execute(
            "SELECT generation FROM fencing WHERE stream_id = ?", (stream_id,)
        ).fetchone()
        return row[0] if row is not None else 0

    def committed_event_ids(self) -> tuple[str, ...]:
        rows = self._db.execute("SELECT event_id FROM events ORDER BY seq")
        return tuple(event_id for (event_id,) in rows)

    def outbox_records(self) -> tuple[OutboxRecord, ...]:
        rows = self._db.execute("SELECT record FROM outbox ORDER BY id")
        return tuple(OutboxRecord.model_validate_json(record) for (record,) in rows)

    # --- object store -------------------------------------------------------
    async def finalize_artifact(
        self,
        staging: ArtifactStaging,
        data: bytes,
        *,
        artifact_id: str,
        finalized_at: str,
        content_encoding: Literal["identity", "gzip", "zstd", "br"] = "identity",
    ) -> FinalizedArtifact:
        """Verify uploaded bytes against the staging ticket and finalize them.

        A digest or size mismatch raises and never finalizes.
        """
        finalized = build_finalized_artifact(
            staging,
            data,
            artifact_id=artifact_id,
            finalized_at=finalized_at,
            content_encoding=content_encoding,
        )
        self._db.execute(
            "INSERT OR REPLACE INTO objects VALUES (?, ?)", (artifact_id, data)
        )
        self._db.commit()
        return finalized

    async def read_artifact(self, artifact_id: str) -> bytes:
        """Return a finalized artifact's bytes, or raise if unavailable."""
        row = self._db.execute(
            "SELECT data FROM objects WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        if row is None:
            raise StorageError(
                "artifact.unavailable", f"artifact {artifact_id} is unavailable"
            )
        return row[0]

    # --- shared write mechanics --------------------------------------------
    def _append_outbox(self, outbox: Sequence[OutboxRecord]) -> None:
        """Persist each outbox entry as part of the commit's write set."""
        for record in outbox:
            self._db.execute(
                "INSERT INTO outbox(record) VALUES (?)", (record.model_dump_json(),)
            )

    def _check_fence(
        self, stream_events: Sequence[tuple[str, str]], generation: int | None
    ) -> None:
        if generation is None:
            return
        for stream_id, _event_id in stream_events:
            if generation < self.installed_generation(stream_id):
                raise StorageError(
                    "lease.stale_generation",
                    f"producer generation {generation} is fenced on {stream_id}",
                )

    def _apply_appends(
        self,
        idempotency_key: str,
        heads: dict[str, int],
        positions: dict[str, int],
        ledger_adds: list[dict[str, Any]],
        stream_events: Sequence[tuple[str, str]],
        generation: int | None,
    ) -> None:
        for stream_id, sequence in positions.items():
            self._db.execute(
                "INSERT OR REPLACE INTO stream_heads VALUES (?, ?)",
                (stream_id, heads[stream_id]),
            )
            self._db.execute(
                "INSERT INTO positions VALUES (?, ?, ?)",
                (idempotency_key, stream_id, sequence),
            )
        for record in ledger_adds:
            self._db.execute(
                "INSERT INTO ledger(stream_id, sequence, record) VALUES (?, ?, ?)",
                (record["stream_id"], record["sequence"], json.dumps(record)),
            )
        if generation is not None:
            for stream_id, _event_id in stream_events:
                installed = max(self.installed_generation(stream_id), generation)
                self._db.execute(
                    "INSERT OR REPLACE INTO fencing VALUES (?, ?)",
                    (stream_id, installed),
                )

    # --- writes -------------------------------------------------------------
    async def commit(
        self,
        *,
        command_id: str,
        idempotency_key: str,
        aggregate_id: str,
        expected_revision: int | None,
        new_state: Any,
        event_ids: Sequence[str] = (),
        stream_events: Sequence[tuple[str, str]] = (),
        event_details: Mapping[str, Any] | None = None,
        outbox: Sequence[OutboxRecord] = (),
        producer_generation: int | None = None,
        durability_profile: str,
    ) -> UnitOfWorkReceipt:
        """Commit one atomic change and return the unit-of-work receipt."""
        committed = list(event_ids) + [event_id for _, event_id in stream_events]
        fingerprint = commit_fingerprint(command_id, aggregate_id, committed)
        seen = self._db.execute(
            "SELECT fingerprint, receipt FROM receipts WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if seen is not None:
            if seen[0] == fingerprint:
                return UnitOfWorkReceipt.model_validate_json(seen[1])
            raise StorageError(
                "command.idempotency_conflict",
                "idempotency key reused with different content",
            )

        current = self.revision_of(aggregate_id)
        if expected_revision is None and current is not None:
            raise StorageError(
                "resource.already_exists", f"aggregate {aggregate_id} already exists"
            )
        if expected_revision is not None and current != expected_revision:
            raise StorageError(
                "command.revision_conflict",
                f"expected revision {expected_revision}, current {current}",
            )
        self._check_fence(stream_events, producer_generation)
        heads, positions, ledger_adds = plan_appends(
            self._heads(), stream_events, event_details
        )
        revision = 1 if expected_revision is None else expected_revision + 1
        receipt = build_uow_receipt(
            command_id=command_id,
            aggregate_id=aggregate_id,
            revision=revision,
            new_state=new_state,
            committed_event_ids=committed,
            outbox_included=len(outbox) > 0,
            durability_profile=durability_profile,
        )

        self._db.execute(
            "INSERT OR REPLACE INTO aggregates VALUES (?, ?, ?)",
            (aggregate_id, revision, json.dumps(new_state)),
        )
        for event_id in committed:
            self._db.execute("INSERT INTO events(event_id) VALUES (?)", (event_id,))
        self._apply_appends(
            idempotency_key,
            heads,
            positions,
            ledger_adds,
            stream_events,
            producer_generation,
        )
        self._append_outbox(outbox)
        self._db.execute(
            "INSERT INTO receipts VALUES (?, ?, ?)",
            (idempotency_key, fingerprint, receipt.model_dump_json()),
        )
        self._db.commit()
        return receipt

    async def issue_token(
        self,
        *,
        command_id: str,
        idempotency_key: str,
        handle: str,
        new_state: Any,
        stream_events: Sequence[tuple[str, str]] = (),
        event_details: Mapping[str, Any] | None = None,
        outbox: Sequence[OutboxRecord] = (),
        producer_generation: int | None = None,
    ) -> dict[str, int]:
        """Issue one handle-keyed token and return the stream positions."""
        committed = [event_id for _, event_id in stream_events]
        fingerprint = token_fingerprint(command_id, handle, committed)
        seen = self._db.execute(
            "SELECT fingerprint FROM token_fp WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if seen is not None:
            if seen[0] == fingerprint:
                return self.positions_for(idempotency_key)
            raise StorageError(
                "command.idempotency_conflict",
                "idempotency key reused with different content",
            )
        if self.load_token(handle) is not None:
            raise StorageError(
                "resource.already_exists", f"token {handle} already exists"
            )
        self._check_fence(stream_events, producer_generation)
        heads, positions, ledger_adds = plan_appends(
            self._heads(), stream_events, event_details
        )

        self._db.execute(
            "INSERT INTO tokens VALUES (?, ?)", (handle, json.dumps(new_state))
        )
        for event_id in committed:
            self._db.execute("INSERT INTO events(event_id) VALUES (?)", (event_id,))
        self._apply_appends(
            idempotency_key,
            heads,
            positions,
            ledger_adds,
            stream_events,
            producer_generation,
        )
        self._append_outbox(outbox)
        self._db.execute(
            "INSERT INTO token_fp VALUES (?, ?)", (idempotency_key, fingerprint)
        )
        self._db.commit()
        return positions
