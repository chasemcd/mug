"""The production storage backend on Postgres, through the asyncpg driver.

This is the third backend behind the ``Store`` Protocol. It keeps the same
semantics as the in-memory and sqlite backends -- idempotent replay, the revision
and existence guards, producer-epoch fencing, stream positions, the event ledger,
tokens, the object store, and the outbox -- and it shares the pure fingerprint,
receipt, artifact, and position logic, so the three backends never drift. A commit
runs the whole write set inside one Postgres transaction, so a rejected commit
leaves no partial effect.

The ``Store`` Protocol reads are synchronous, because the runtime reads positions
and the ledger while it assembles a receipt; asyncpg is asynchronous only. So this
backend owns one background event loop in one thread, and every driver call runs
there: a write awaits its result without blocking the caller loop, and a read
blocks the caller thread briefly on that loop -- the same way the sqlite backend
blocks on its synchronous driver. One asyncpg pool lives on that loop, so no
connection ever crosses a loop.

Each instance owns one Postgres schema, dropped and recreated on ``create`` and
dropped on ``aclose``, so instances never share tables.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Coroutine, Mapping, Sequence
from typing import Any, Literal, TypeVar

import asyncpg as _asyncpg

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

# asyncpg ships no type information; bind it to ``Any`` so the driver surface
# stays dynamic under strict typing instead of leaking Unknown into this module.
asyncpg: Any = _asyncpg

_T = TypeVar("_T")

_SCHEMA = "mug_store"

_DDL = """
CREATE TABLE IF NOT EXISTS aggregates(
    aggregate_id TEXT PRIMARY KEY, revision INTEGER, state TEXT);
CREATE TABLE IF NOT EXISTS receipts(
    idempotency_key TEXT PRIMARY KEY, fingerprint TEXT, receipt TEXT);
CREATE TABLE IF NOT EXISTS tokens(handle TEXT PRIMARY KEY, state TEXT);
CREATE TABLE IF NOT EXISTS token_fp(
    idempotency_key TEXT PRIMARY KEY, fingerprint TEXT);
CREATE TABLE IF NOT EXISTS events(seq BIGSERIAL PRIMARY KEY, event_id TEXT);
CREATE TABLE IF NOT EXISTS stream_heads(stream_id TEXT PRIMARY KEY, head INTEGER);
CREATE TABLE IF NOT EXISTS positions(
    idempotency_key TEXT, stream_id TEXT, sequence INTEGER);
CREATE TABLE IF NOT EXISTS fencing(stream_id TEXT PRIMARY KEY, generation INTEGER);
CREATE TABLE IF NOT EXISTS ledger(
    id BIGSERIAL PRIMARY KEY, stream_id TEXT, sequence INTEGER, record TEXT);
CREATE TABLE IF NOT EXISTS objects(artifact_id TEXT PRIMARY KEY, data BYTEA);
CREATE TABLE IF NOT EXISTS outbox(id BIGSERIAL PRIMARY KEY, record TEXT);
"""


class PgStore:
    """A relational Unit of Work on Postgres, with memory-equivalent semantics."""

    def __init__(
        self, pool: Any, dsn: str, loop: Any, thread: threading.Thread
    ) -> None:
        self._pool = pool
        self._dsn = dsn
        self._loop = loop
        self._thread = thread

    # --- construction and teardown -----------------------------------------
    @classmethod
    async def create(cls, dsn: str) -> PgStore:
        """Start the backend's loop, make a fresh schema, and build the pool."""
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()

        async def _setup() -> Any:
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute(f'DROP SCHEMA IF EXISTS "{_SCHEMA}" CASCADE')
                await conn.execute(f'CREATE SCHEMA "{_SCHEMA}"')
            finally:
                await conn.close()
            pool = await asyncpg.create_pool(
                dsn, min_size=1, max_size=4, server_settings={"search_path": _SCHEMA}
            )
            async with pool.acquire() as conn:
                await conn.execute(_DDL)
            return pool

        pool = await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(_setup(), loop)
        )
        return cls(pool, dsn, loop, thread)

    @classmethod
    async def open(cls, dsn: str) -> PgStore:
        """Open the backend on an existing database without dropping any data.

        Unlike ``create``, this keeps the schema and its rows. It creates the
        schema and the tables only when they are absent, so a first run bootstraps
        and every later run resumes the stored aggregates, ledger, and positions.
        A deployment uses this; the destructive ``create`` is for a clean test.
        """
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever, daemon=True)
        thread.start()

        async def _setup() -> Any:
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{_SCHEMA}"')
            finally:
                await conn.close()
            pool = await asyncpg.create_pool(
                dsn, min_size=1, max_size=4, server_settings={"search_path": _SCHEMA}
            )
            async with pool.acquire() as conn:
                await conn.execute(_DDL)
            return pool

        pool = await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(_setup(), loop)
        )
        return cls(pool, dsn, loop, thread)

    async def aclose(self) -> None:
        """Close the pool, drop the schema, and stop the backend's loop."""

        async def _teardown() -> None:
            await self._pool.close()
            conn = await asyncpg.connect(self._dsn)
            try:
                await conn.execute(f'DROP SCHEMA IF EXISTS "{_SCHEMA}" CASCADE')
            finally:
                await conn.close()

        await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(_teardown(), self._loop)
        )
        self._loop.call_soon_threadsafe(self._loop.stop)

    async def close(self) -> None:
        """Close the pool and stop the loop, keeping the schema and its data.

        A deployment closes the store on shutdown; the stored rows must survive
        for the next run, so this never drops the schema (see ``aclose``).
        """

        async def _teardown() -> None:
            await self._pool.close()

        await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(_teardown(), self._loop)
        )
        self._loop.call_soon_threadsafe(self._loop.stop)

    # --- loop bridge --------------------------------------------------------
    def _run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        """Run a driver coroutine on the backend loop and block for its result."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    async def _await(self, coro: Coroutine[Any, Any, _T]) -> _T:
        """Await a driver coroutine on the backend loop without blocking here."""
        return await asyncio.wrap_future(
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        )

    # --- reads --------------------------------------------------------------
    def positions_for(self, idempotency_key: str) -> dict[str, int]:
        return self._run(self._read_positions(idempotency_key))

    async def _read_positions(self, idempotency_key: str) -> dict[str, int]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT stream_id, sequence FROM positions WHERE idempotency_key = $1",
                idempotency_key,
            )
        return {row["stream_id"]: row["sequence"] for row in rows}

    def stream_records(
        self, stream_id: str, after_sequence: int = 0
    ) -> list[dict[str, Any]]:
        return self._run(self._read_stream(stream_id, after_sequence))

    async def _read_stream(
        self, stream_id: str, after_sequence: int
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT record FROM ledger WHERE stream_id = $1 AND sequence > $2 "
                "ORDER BY sequence",
                stream_id,
                after_sequence,
            )
        return [json.loads(row["record"]) for row in rows]

    def load_aggregate(self, aggregate_id: str) -> Any | None:
        return self._run(self._read_state("aggregates", "aggregate_id", aggregate_id))

    def load_token(self, handle: str) -> Any | None:
        return self._run(self._read_state("tokens", "handle", handle))

    def scan_aggregates(self) -> list[tuple[str, Any]]:
        return self._run(self._scan_aggregates())

    async def _scan_aggregates(self) -> list[tuple[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT aggregate_id, state FROM aggregates")
        return [(row[0], json.loads(row[1])) for row in rows]

    async def _read_state(self, table: str, key: str, value: str) -> Any | None:
        async with self._pool.acquire() as conn:
            state = await conn.fetchval(
                f"SELECT state FROM {table} WHERE {key} = $1", value
            )
        return json.loads(state) if state is not None else None

    def revision_of(self, aggregate_id: str) -> int | None:
        return self._run(self._read_revision(aggregate_id))

    async def _read_revision(self, aggregate_id: str) -> int | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT revision FROM aggregates WHERE aggregate_id = $1", aggregate_id
            )

    def stream_head(self, stream_id: str) -> int:
        return self._run(self._read_head(stream_id))

    async def _read_head(self, stream_id: str) -> int:
        async with self._pool.acquire() as conn:
            head = await conn.fetchval(
                "SELECT head FROM stream_heads WHERE stream_id = $1", stream_id
            )
        return head if head is not None else 0

    def installed_generation(self, stream_id: str) -> int:
        return self._run(self._read_generation(stream_id))

    async def _read_generation(self, stream_id: str) -> int:
        async with self._pool.acquire() as conn:
            return await _generation_on(conn, stream_id)

    def committed_event_ids(self) -> tuple[str, ...]:
        return self._run(self._read_events())

    async def _read_events(self) -> tuple[str, ...]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT event_id FROM events ORDER BY seq")
        return tuple(row["event_id"] for row in rows)

    def outbox_records(self) -> tuple[OutboxRecord, ...]:
        return self._run(self._read_outbox())

    async def _read_outbox(self) -> tuple[OutboxRecord, ...]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT record FROM outbox ORDER BY id")
        return tuple(OutboxRecord.model_validate_json(row["record"]) for row in rows)

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
        return await self._await(
            self._store_object(
                staging, data, artifact_id, finalized_at, content_encoding
            )
        )

    async def _store_object(
        self,
        staging: ArtifactStaging,
        data: bytes,
        artifact_id: str,
        finalized_at: str,
        content_encoding: Literal["identity", "gzip", "zstd", "br"],
    ) -> FinalizedArtifact:
        finalized = build_finalized_artifact(
            staging,
            data,
            artifact_id=artifact_id,
            finalized_at=finalized_at,
            content_encoding=content_encoding,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO objects (artifact_id, data) VALUES ($1, $2) "
                "ON CONFLICT (artifact_id) DO UPDATE SET data = EXCLUDED.data",
                artifact_id,
                data,
            )
        return finalized

    async def read_artifact(self, artifact_id: str) -> bytes:
        """Return a finalized artifact's bytes, or raise if unavailable."""
        return await self._await(self._read_object(artifact_id))

    async def _read_object(self, artifact_id: str) -> bytes:
        async with self._pool.acquire() as conn:
            data = await conn.fetchval(
                "SELECT data FROM objects WHERE artifact_id = $1", artifact_id
            )
        if data is None:
            raise StorageError(
                "artifact.unavailable", f"artifact {artifact_id} is unavailable"
            )
        return data

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
        return await self._await(
            self._commit(
                command_id=command_id,
                idempotency_key=idempotency_key,
                aggregate_id=aggregate_id,
                expected_revision=expected_revision,
                new_state=new_state,
                event_ids=event_ids,
                stream_events=stream_events,
                event_details=event_details,
                outbox=outbox,
                producer_generation=producer_generation,
                durability_profile=durability_profile,
            )
        )

    async def _commit(
        self,
        *,
        command_id: str,
        idempotency_key: str,
        aggregate_id: str,
        expected_revision: int | None,
        new_state: Any,
        event_ids: Sequence[str],
        stream_events: Sequence[tuple[str, str]],
        event_details: Mapping[str, Any] | None,
        outbox: Sequence[OutboxRecord],
        producer_generation: int | None,
        durability_profile: str,
    ) -> UnitOfWorkReceipt:
        committed = list(event_ids) + [event_id for _, event_id in stream_events]
        fingerprint = commit_fingerprint(command_id, aggregate_id, committed)
        async with self._pool.acquire() as conn, conn.transaction():
            seen = await conn.fetchrow(
                "SELECT fingerprint, receipt FROM receipts WHERE idempotency_key = $1",
                idempotency_key,
            )
            if seen is not None:
                if seen["fingerprint"] == fingerprint:
                    return UnitOfWorkReceipt.model_validate_json(seen["receipt"])
                raise StorageError(
                    "command.idempotency_conflict",
                    "idempotency key reused with different content",
                )

            current = await conn.fetchval(
                "SELECT revision FROM aggregates WHERE aggregate_id = $1",
                aggregate_id,
            )
            if expected_revision is None and current is not None:
                raise StorageError(
                    "resource.already_exists",
                    f"aggregate {aggregate_id} already exists",
                )
            if expected_revision is not None and current != expected_revision:
                raise StorageError(
                    "command.revision_conflict",
                    f"expected revision {expected_revision}, current {current}",
                )
            await _check_fence(conn, stream_events, producer_generation)
            heads, positions, ledger_adds = plan_appends(
                await _heads(conn), stream_events, event_details
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

            await conn.execute(
                "INSERT INTO aggregates (aggregate_id, revision, state) "
                "VALUES ($1, $2, $3) ON CONFLICT (aggregate_id) "
                "DO UPDATE SET revision = EXCLUDED.revision, state = EXCLUDED.state",
                aggregate_id,
                revision,
                json.dumps(new_state),
            )
            await _record_events(conn, committed)
            await _apply_appends(
                conn,
                idempotency_key,
                heads,
                positions,
                ledger_adds,
                stream_events,
                producer_generation,
            )
            await _append_outbox(conn, outbox)
            await conn.execute(
                "INSERT INTO receipts (idempotency_key, fingerprint, receipt) "
                "VALUES ($1, $2, $3)",
                idempotency_key,
                fingerprint,
                receipt.model_dump_json(),
            )
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
        return await self._await(
            self._issue_token(
                command_id=command_id,
                idempotency_key=idempotency_key,
                handle=handle,
                new_state=new_state,
                stream_events=stream_events,
                event_details=event_details,
                outbox=outbox,
                producer_generation=producer_generation,
            )
        )

    async def _issue_token(
        self,
        *,
        command_id: str,
        idempotency_key: str,
        handle: str,
        new_state: Any,
        stream_events: Sequence[tuple[str, str]],
        event_details: Mapping[str, Any] | None,
        outbox: Sequence[OutboxRecord],
        producer_generation: int | None,
    ) -> dict[str, int]:
        committed = [event_id for _, event_id in stream_events]
        fingerprint = token_fingerprint(command_id, handle, committed)
        async with self._pool.acquire() as conn, conn.transaction():
            seen = await conn.fetchval(
                "SELECT fingerprint FROM token_fp WHERE idempotency_key = $1",
                idempotency_key,
            )
            if seen is not None:
                if seen == fingerprint:
                    return await self._read_positions(idempotency_key)
                raise StorageError(
                    "command.idempotency_conflict",
                    "idempotency key reused with different content",
                )
            exists = await conn.fetchval(
                "SELECT 1 FROM tokens WHERE handle = $1", handle
            )
            if exists is not None:
                raise StorageError(
                    "resource.already_exists", f"token {handle} already exists"
                )
            await _check_fence(conn, stream_events, producer_generation)
            heads, positions, ledger_adds = plan_appends(
                await _heads(conn), stream_events, event_details
            )

            await conn.execute(
                "INSERT INTO tokens (handle, state) VALUES ($1, $2)",
                handle,
                json.dumps(new_state),
            )
            await _record_events(conn, committed)
            await _apply_appends(
                conn,
                idempotency_key,
                heads,
                positions,
                ledger_adds,
                stream_events,
                producer_generation,
            )
            await _append_outbox(conn, outbox)
            await conn.execute(
                "INSERT INTO token_fp (idempotency_key, fingerprint) VALUES ($1, $2)",
                idempotency_key,
                fingerprint,
            )
        return positions


# The write mechanics are module functions over one transaction connection, so
# both write paths share them without a second concrete backend.


async def _heads(conn: Any) -> dict[str, int]:
    rows = await conn.fetch("SELECT stream_id, head FROM stream_heads")
    return {row["stream_id"]: row["head"] for row in rows}


async def _generation_on(conn: Any, stream_id: str) -> int:
    generation = await conn.fetchval(
        "SELECT generation FROM fencing WHERE stream_id = $1", stream_id
    )
    return generation if generation is not None else 0


async def _check_fence(
    conn: Any, stream_events: Sequence[tuple[str, str]], generation: int | None
) -> None:
    if generation is None:
        return
    for stream_id, _event_id in stream_events:
        if generation < await _generation_on(conn, stream_id):
            raise StorageError(
                "lease.stale_generation",
                f"producer generation {generation} is fenced on {stream_id}",
            )


async def _record_events(conn: Any, event_ids: Sequence[str]) -> None:
    for event_id in event_ids:
        await conn.execute("INSERT INTO events (event_id) VALUES ($1)", event_id)


async def _apply_appends(
    conn: Any,
    idempotency_key: str,
    heads: dict[str, int],
    positions: dict[str, int],
    ledger_adds: list[dict[str, Any]],
    stream_events: Sequence[tuple[str, str]],
    generation: int | None,
) -> None:
    for stream_id, sequence in positions.items():
        await conn.execute(
            "INSERT INTO stream_heads (stream_id, head) VALUES ($1, $2) "
            "ON CONFLICT (stream_id) DO UPDATE SET head = EXCLUDED.head",
            stream_id,
            heads[stream_id],
        )
        await conn.execute(
            "INSERT INTO positions (idempotency_key, stream_id, sequence) "
            "VALUES ($1, $2, $3)",
            idempotency_key,
            stream_id,
            sequence,
        )
    for record in ledger_adds:
        await conn.execute(
            "INSERT INTO ledger (stream_id, sequence, record) VALUES ($1, $2, $3)",
            record["stream_id"],
            record["sequence"],
            json.dumps(record),
        )
    if generation is not None:
        for stream_id, _event_id in stream_events:
            installed = max(await _generation_on(conn, stream_id), generation)
            await conn.execute(
                "INSERT INTO fencing (stream_id, generation) VALUES ($1, $2) "
                "ON CONFLICT (stream_id) "
                "DO UPDATE SET generation = EXCLUDED.generation",
                stream_id,
                installed,
            )


async def _append_outbox(conn: Any, outbox: Sequence[OutboxRecord]) -> None:
    for record in outbox:
        await conn.execute(
            "INSERT INTO outbox (record) VALUES ($1)", record.model_dump_json()
        )
