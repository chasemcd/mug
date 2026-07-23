"""In-memory storage backend (the API-11 reference implementation).

This proves the durability contract without infrastructure. Finalizing an
artifact verifies its digest and size; one commit writes aggregate state, the
idempotency record, the canonical events, and the outbox together, with a
revision guard and idempotent replay.

A Postgres/asyncpg backend implements the same methods later. We extract a
Protocol only when that second backend exists.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from mug.kernel import (
    ArtifactRef,
    Digest,
    ReceiptDurability,
    ResourceRef,
    VersionStamp,
    etag,
    sha256_hex,
)
from mug.storage.types import (
    ArtifactStaging,
    FinalizedArtifact,
    OutboxRecord,
    UnitOfWorkReceipt,
)


class StorageError(Exception):
    """A storage failure carrying a stable kernel error ``code``.

    The transport edge turns this into a wire ``DomainError``; the codes come
    from the kernel taxonomy (for example ``command.revision_conflict``).
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def digest_of(data: bytes) -> Digest:
    """Return the SHA-256 digest of raw bytes."""
    return Digest(algorithm="sha-256", hex=hashlib.sha256(data).hexdigest())


# The pure logic below is shared by every backend, so they never drift on the
# idempotency fingerprint, the receipt shape, or the position assignment.


def commit_fingerprint(
    command_id: str, aggregate_id: str, event_ids: list[str]
) -> str:
    """The idempotency fingerprint of one aggregate commit."""
    return sha256_hex(
        {
            "command_id": command_id,
            "aggregate_id": aggregate_id,
            "event_ids": event_ids,
        }
    )


def token_fingerprint(command_id: str, handle: str, event_ids: list[str]) -> str:
    """The idempotency fingerprint of one token issuance."""
    return sha256_hex(
        {"command_id": command_id, "handle": handle, "event_ids": event_ids}
    )


def build_uow_receipt(
    *,
    command_id: str,
    aggregate_id: str,
    revision: int,
    new_state: Any,
    committed_event_ids: list[str],
    outbox_included: bool,
    durability_profile: str,
) -> UnitOfWorkReceipt:
    """Assemble the unit-of-work receipt for one committed aggregate."""
    return UnitOfWorkReceipt(
        command_id=command_id,
        aggregate_ref=ResourceRef(id=aggregate_id),
        aggregate_version=VersionStamp(revision=revision, etag=etag(new_state)),
        committed_event_ids=committed_event_ids,
        outbox_included=outbox_included,
        durability=ReceiptDurability(
            receipt="transactional", effect="transactional", profile=durability_profile
        ),
    )


def build_finalized_artifact(
    staging: ArtifactStaging,
    data: bytes,
    *,
    artifact_id: str,
    finalized_at: str,
    content_encoding: Literal["identity", "gzip", "zstd", "br"],
) -> FinalizedArtifact:
    """Verify uploaded bytes against the staging ticket and build the record.

    A digest or size mismatch raises and never finalizes. The caller stores the
    bytes only after this returns, so a rejected upload leaves no object. Both
    backends share this, so they never drift on the integrity check.
    """
    if (
        len(data) != staging.size_bytes
        or digest_of(data).hex != staging.intended_digest.hex
    ):
        raise StorageError(
            "artifact.integrity_failed",
            "bytes do not match the staged digest or size",
        )
    artifact = ArtifactRef(
        artifact_id=artifact_id,
        digest=staging.intended_digest,
        size_bytes=staging.size_bytes,
        media_type=staging.media_type,
        content_encoding=content_encoding,
        data_handling=staging.data_handling,
    )
    return FinalizedArtifact(
        artifact=artifact,
        staged_upload_id=staging.upload_id,
        intended_digest=staging.intended_digest,
        finalized_at=finalized_at,
    )


def plan_appends(
    heads: Mapping[str, int],
    stream_events: Sequence[tuple[str, str]],
    event_details: Mapping[str, Any] | None,
) -> tuple[dict[str, int], dict[str, int], list[dict[str, Any]]]:
    """Assign each event its next stream sequence and draft its ledger record.

    The head advances within one commit so several events on a stream stay
    contiguous. An event named in ``event_details`` also drafts a full ledger
    record with its assigned position; a bare event (a seed) records none.
    Returns the advanced heads, the positions, and the ledger records to add.
    """
    details = event_details or {}
    advanced = dict(heads)
    positions: dict[str, int] = {}
    records: list[dict[str, Any]] = []
    for stream_id, event_id in stream_events:
        sequence = advanced.get(stream_id, 0) + 1
        advanced[stream_id] = sequence
        positions[stream_id] = sequence
        detail = details.get(event_id)
        if detail is not None:
            records.append(
                {
                    "stream_id": stream_id,
                    "sequence": sequence,
                    "event_id": event_id,
                    **detail,
                }
            )
    return advanced, positions, records


class InMemoryStore:
    """A content-addressed object store and a relational Unit of Work, in memory."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._revisions: dict[str, int] = {}
        self._aggregates: dict[str, Any] = {}
        self._receipts: dict[str, tuple[str, UnitOfWorkReceipt]] = {}
        self._tokens: dict[str, Any] = {}
        self._token_fingerprints: dict[str, str] = {}
        self._events: list[str] = []
        self._outbox: list[OutboxRecord] = []
        self._stream_heads: dict[str, int] = {}
        self._positions: dict[str, dict[str, int]] = {}
        self._fencing: dict[str, int] = {}
        self._ledger: list[dict[str, Any]] = []

    def stream_records(
        self, stream_id: str, after_sequence: int = 0
    ) -> list[dict[str, Any]]:
        """Return a stream's ledger records after a sequence, in order.

        A read-model above the store turns each record into an event envelope.
        """
        return sorted(
            (
                record
                for record in self._ledger
                if record["stream_id"] == stream_id
                and record["sequence"] > after_sequence
            ),
            key=lambda record: record["sequence"],
        )

    def installed_generation(self, stream_id: str) -> int:
        """Return the fencing generation installed on a stream, or 0 if none."""
        return self._fencing.get(stream_id, 0)

    def _check_fence(
        self, stream_events: Sequence[tuple[str, str]], generation: int | None
    ) -> None:
        """Refuse a write from a superseded producer generation.

        A producer installs itself on a stream with a strictly greater
        generation; a write whose generation is below the installed one is
        fenced. ``None`` skips the check, for a direct seed with no producer.
        """
        if generation is None:
            return
        for stream_id, _event_id in stream_events:
            if generation < self._fencing.get(stream_id, 0):
                raise StorageError(
                    "lease.stale_generation",
                    f"producer generation {generation} is fenced on {stream_id}",
                )

    def _install_fence(
        self, stream_events: Sequence[tuple[str, str]], generation: int | None
    ) -> None:
        """Install this write's generation as the current one on each stream."""
        if generation is None:
            return
        for stream_id, _event_id in stream_events:
            self._fencing[stream_id] = max(self._fencing.get(stream_id, 0), generation)

    def stream_head(self, stream_id: str) -> int:
        """Return the highest committed sequence for a stream, or 0 if empty."""
        return self._stream_heads.get(stream_id, 0)

    def positions_for(self, idempotency_key: str) -> dict[str, int]:
        """Return the stream positions one commit assigned, by its key.

        A replay returns the positions the first commit assigned, so a rebuilt
        receipt names the real, stable position and never a recomputed one.
        """
        return dict(self._positions.get(idempotency_key, {}))

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
        self._objects[artifact_id] = data
        return finalized

    async def read_artifact(self, artifact_id: str) -> bytes:
        """Return a finalized artifact's bytes, or raise if unavailable."""
        try:
            return self._objects[artifact_id]
        except KeyError:
            raise StorageError(
                "artifact.unavailable", f"artifact {artifact_id} is unavailable"
            ) from None

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
        """Commit one atomic change and return the unit-of-work receipt.

        ``expected_revision`` is ``None`` for a create (the aggregate must be
        absent). ``stream_events`` names the ``(stream_id, event_id)`` pairs this
        commit appends; the store assigns each the next sequence on its stream and
        records the positions under the key, so a replay reports the same ones. A
        repeat of the same key and content returns the original receipt without a
        second effect; a revision or existence conflict raises.
        """
        committed = list(event_ids) + [event_id for _, event_id in stream_events]
        fingerprint = commit_fingerprint(command_id, aggregate_id, committed)
        seen = self._receipts.get(idempotency_key)
        if seen is not None:
            if seen[0] == fingerprint:
                return seen[1]
            raise StorageError(
                "command.idempotency_conflict",
                "idempotency key reused with different content",
            )

        current = self._revisions.get(aggregate_id)
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
            self._stream_heads, stream_events, event_details
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
        # Apply the whole write set together. The dictionaries change only after
        # the guards pass, so a rejected commit leaves no partial effect.
        self._revisions[aggregate_id] = revision
        self._aggregates[aggregate_id] = new_state
        self._events.extend(committed)
        self._ledger.extend(ledger_adds)
        self._stream_heads = heads
        self._positions[idempotency_key] = positions
        self._install_fence(stream_events, producer_generation)
        self._outbox.extend(outbox)
        self._receipts[idempotency_key] = (fingerprint, receipt)
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
        """Issue one handle-keyed token and return the stream positions.

        A token has no revision and no version, so it does not fit the
        aggregate ``commit`` path; it is keyed by a public handle and issued
        once. A repeat of the same key and content returns the original
        positions with no second effect; a reused handle or a reused key with
        different content raises. The issuance event joins the ledger.
        """
        committed = [event_id for _, event_id in stream_events]
        fingerprint = token_fingerprint(command_id, handle, committed)
        seen = self._token_fingerprints.get(idempotency_key)
        if seen is not None:
            if seen == fingerprint:
                return dict(self._positions.get(idempotency_key, {}))
            raise StorageError(
                "command.idempotency_conflict",
                "idempotency key reused with different content",
            )
        if handle in self._tokens:
            raise StorageError(
                "resource.already_exists", f"token {handle} already exists"
            )
        self._check_fence(stream_events, producer_generation)
        heads, positions, ledger_adds = plan_appends(
            self._stream_heads, stream_events, event_details
        )

        self._tokens[handle] = new_state
        self._events.extend(committed)
        self._ledger.extend(ledger_adds)
        self._stream_heads = heads
        self._positions[idempotency_key] = positions
        self._install_fence(stream_events, producer_generation)
        self._token_fingerprints[idempotency_key] = fingerprint
        self._outbox.extend(outbox)
        return positions

    # Read helpers for tests and projectors.
    def revision_of(self, aggregate_id: str) -> int | None:
        return self._revisions.get(aggregate_id)

    def load_token(self, handle: str) -> Any | None:
        """Return an issued token's state, or None if the handle is unknown."""
        return self._tokens.get(handle)

    def load_aggregate(self, aggregate_id: str) -> Any | None:
        """Return the committed state of an aggregate, or None if it is absent.

        An update command reads the current state to check the transition and to
        carry the unchanged fields forward.
        """
        return self._aggregates.get(aggregate_id)

    def scan_aggregates(self) -> list[tuple[str, Any]]:
        """Return every aggregate as an id and its committed state.

        A projector rebuilds an index from the committed state on start; the
        durable job queue folds this to rediscover queued work after a restart.
        """
        return list(self._aggregates.items())

    def committed_event_ids(self) -> tuple[str, ...]:
        return tuple(self._events)

    def outbox_records(self) -> tuple[OutboxRecord, ...]:
        return tuple(self._outbox)
