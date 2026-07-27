"""The durable jobs runtime drives one job through submit, lease, and complete.

These tests drive ``mug.workers.JobRunner`` against the in-memory store with a
fixed, movable clock and hand-built command contexts, with no worker pool and no
socket. They prove the correctness core the family promises: a submission keyed by
its work key (a duplicate coalesces, an identical retry replays), a lease that only
one worker wins, a lease that a new worker takes over once it expires while the
store fences the stale worker, and a result the store records exactly once.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from mug.kernel import ArtifactRef, DataHandlingRef, Digest, compute_digest
from mug.runtime import CommandContext, read_ledger
from mug.storage import InMemoryStore
from mug.workers import JobRunner, JobUnknown, LeaseHeld, attempt_aggregate_id

_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_DH = DataHandlingRef(privacy_labels=["research"])
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_TTL = timedelta(seconds=30)
_LEASE_EPOCH = "leaseepoch_019b6000-0000-7000-8000-000000000001"
_DATA_HANDLING = {"privacy_labels": ["research"]}


class _Clock:
    """A movable clock: it returns a fixed instant until a test advances it."""

    def __init__(self) -> None:
        self._now = _START

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta


def _uuid7(hexseed: str) -> str:
    """Return a UUIDv7-shaped body from a hex seed, with the nibbles forced."""
    raw = bytearray(bytes.fromhex(hexseed[:32]))
    raw[6] = 0x70 | (raw[6] & 0x0F)
    raw[8] = 0x80 | (raw[8] & 0x3F)
    body = raw.hex()
    return f"{body[0:8]}-{body[8:12]}-{body[12:16]}-{body[16:20]}-{body[20:32]}"


def _work_key(seed: str) -> Digest:
    """Build a distinct work-key digest from a short seed."""
    return Digest(algorithm="sha-256", hex=compute_digest(seed).hex)


class _Contexts:
    """Mint distinct command contexts for one job's aggregate and stream.

    Every context an aggregate uses shares the aggregate's stream, so the job's
    events land on one stream; the command, receipt, error, event, and idempotency
    identifiers differ per operation, as a real gateway would mint them.
    """

    def __init__(self, job_id: str) -> None:
        self._job_id = job_id
        self._stream_body = job_id.split("_", 1)[1]
        self._counter = itertools.count(1)

    def next(self) -> CommandContext:
        n = next(self._counter)
        body = f"019b6000-0000-7000-8000-{n:012x}"
        return CommandContext.model_validate(
            {
                "command_id": "command_" + body,
                "receipt_id": "receipt_" + body,
                "error_id": "error_" + body,
                "idempotency_key": "idem_" + f"{n:021d}" + "A",
                "event_id": "event_" + body,
                "stream_id": "stream_" + self._stream_body,
                "producer": {
                    "epoch_id": "prodepoch_019b6000-0000-7000-8000-000000000009",
                    "sequence": n,
                    "content_digest": _DIGEST.model_dump(mode="json"),
                },
                "aggregate_id": self._job_id,
                "principal": {
                    "kind": "service",
                    "id": "service_019b6000-0000-7000-8000-00000000000a",
                },
                "recorded_at": "2026-07-22T00:00:00.000000Z",
                "event_data_handling": _DATA_HANDLING,
            }
        )


def _runner(store: InMemoryStore, clock: _Clock) -> JobRunner:
    lease_ids = itertools.count(1)
    return JobRunner(
        store=store,
        now=clock,
        lease_ttl=_TTL,
        lease_epoch_id=_LEASE_EPOCH,
        new_lease_id=lambda: "lease_" + _uuid7(f"{next(lease_ids):032x}"),
    )


def _job_id(work_key: Digest) -> str:
    return "job_" + _uuid7(work_key.hex)


async def _submit(
    runner: JobRunner, contexts: _Contexts, work_key: Digest
) -> None:
    receipt, _ = await runner.submit(
        context=contexts.next(),
        job_kind="simulate-batch",
        work_key=work_key,
        submitted_at="2026-07-22T00:00:00.000000Z",
    )
    assert receipt.outcome == "accepted"


async def test_submit_records_a_queued_job() -> None:
    """A submission commits the job aggregate at its first revision."""
    store, clock = InMemoryStore(), _Clock()
    runner = _runner(store, clock)
    work_key = _work_key("alpha")
    job_id = _job_id(work_key)
    await _submit(runner, _Contexts(job_id), work_key)

    assert store.revision_of(job_id) == 1
    state = store.load_aggregate(job_id)
    assert state is not None
    assert state["job_kind"] == "simulate-batch"
    assert "status" not in state


async def test_a_duplicate_work_key_is_coalesced() -> None:
    """A second submission of the same work key is refused with no effect."""
    store, clock = InMemoryStore(), _Clock()
    runner = _runner(store, clock)
    work_key = _work_key("beta")
    job_id = _job_id(work_key)
    contexts = _Contexts(job_id)
    await _submit(runner, contexts, work_key)

    receipt, _ = await runner.submit(
        context=contexts.next(),
        job_kind="simulate-batch",
        work_key=work_key,
        submitted_at="2026-07-22T00:00:00.000000Z",
    )
    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.code == "resource.already_exists"
    assert store.revision_of(job_id) == 1


async def test_an_identical_submission_replays() -> None:
    """An identical retry of the same submit replays with no second effect."""
    store, clock = InMemoryStore(), _Clock()
    runner = _runner(store, clock)
    work_key = _work_key("gamma")
    job_id = _job_id(work_key)
    context = _Contexts(job_id).next()

    first, _ = await runner.submit(
        context=context,
        job_kind="simulate-batch",
        work_key=work_key,
        submitted_at="2026-07-22T00:00:00.000000Z",
    )
    second, _ = await runner.submit(
        context=context,
        job_kind="simulate-batch",
        work_key=work_key,
        submitted_at="2026-07-22T00:00:00.000000Z",
    )
    assert first.outcome == "accepted"
    assert second.outcome == "accepted"
    assert second.receipt_id == first.receipt_id
    assert store.revision_of(job_id) == 1


async def test_a_second_worker_is_refused_the_held_lease() -> None:
    """One worker leases the queued job; a second worker is refused the lease.

    The first claim installs a live lease and moves the aggregate revision. A
    second worker then reads a running attempt whose lease has not expired, so the
    runner refuses it with ``LeaseHeld`` -- only one worker holds the lease. (A
    genuinely concurrent double-commit resolves the same way through the store's
    revision guard, on a backend whose commits truly interleave.)
    """
    store, clock = InMemoryStore(), _Clock()
    runner = _runner(store, clock)
    work_key = _work_key("delta")
    job_id = _job_id(work_key)
    contexts = _Contexts(job_id)
    await _submit(runner, contexts, work_key)

    won = await runner.claim(context=contexts.next())
    assert won is not None
    assert won.generation == 1
    # The claim lands on the attempt aggregate; the request head never moves, which
    # is what keeps the work key readable by a later worker.
    assert store.revision_of(job_id) == 1
    assert store.revision_of(attempt_aggregate_id(job_id)) == 1
    with pytest.raises(LeaseHeld):
        await runner.claim(context=contexts.next())


async def test_a_live_lease_is_not_reclaimable() -> None:
    """A claim of a running attempt whose lease is live raises ``LeaseHeld``."""
    store, clock = InMemoryStore(), _Clock()
    runner = _runner(store, clock)
    work_key = _work_key("epsilon")
    job_id = _job_id(work_key)
    contexts = _Contexts(job_id)
    await _submit(runner, contexts, work_key)
    await runner.claim(context=contexts.next())

    clock.advance(_TTL - timedelta(seconds=1))
    with pytest.raises(LeaseHeld):
        await runner.claim(context=contexts.next())


async def test_claiming_an_unsubmitted_job_raises() -> None:
    """A claim of a job that was never submitted raises ``JobUnknown``."""
    store, clock = InMemoryStore(), _Clock()
    runner = _runner(store, clock)
    job_id = _job_id(_work_key("zeta"))
    with pytest.raises(JobUnknown):
        await runner.claim(context=_Contexts(job_id).next())


async def test_a_success_binds_the_result_digest_on_the_lineage() -> None:
    """A completed job records a terminal run that binds the result digest."""
    store, clock = InMemoryStore(), _Clock()
    runner = _runner(store, clock)
    work_key = _work_key("eta")
    job_id = _job_id(work_key)
    contexts = _Contexts(job_id)
    await _submit(runner, contexts, work_key)
    claim = await runner.claim(context=contexts.next())
    assert claim is not None

    artifact = ArtifactRef(
        artifact_id="artifact_019b6000-0000-7000-8000-00000000000b",
        digest=_DIGEST,
        size_bytes=4,
        media_type="application/json",
        content_encoding="identity",
        data_handling=_DH,
    )
    receipt, result = await runner.complete(
        context=contexts.next(),
        claim=claim,
        work_key=work_key,
        outcome="success",
        result_ref=artifact,
    )
    assert receipt.outcome == "accepted"
    assert result.outcome == "success"
    assert result.result_ref is not None

    state: dict[str, Any] | None = store.load_aggregate(attempt_aggregate_id(job_id))
    assert state is not None
    assert state["status"] == "succeeded"
    assert state["result_digest"] == compute_digest(
        result.model_dump(mode="json", exclude_none=True)
    ).model_dump(mode="json")
    # The stream is the full lineage: request, one claim, and the completion.
    lineage = read_ledger(store, "stream_" + job_id.split("_", 1)[1])
    assert len(lineage) == 3


async def test_a_failure_completes_without_an_artifact() -> None:
    """A failed job records a failed run and a result that names no artifact."""
    store, clock = InMemoryStore(), _Clock()
    runner = _runner(store, clock)
    work_key = _work_key("theta")
    job_id = _job_id(work_key)
    contexts = _Contexts(job_id)
    await _submit(runner, contexts, work_key)
    claim = await runner.claim(context=contexts.next())
    assert claim is not None

    receipt, result = await runner.complete(
        context=contexts.next(),
        claim=claim,
        work_key=work_key,
        outcome="failure",
    )
    assert receipt.outcome == "accepted"
    assert result.outcome == "failure"
    assert result.result_ref is None
    state = store.load_aggregate(attempt_aggregate_id(job_id))
    assert state is not None
    assert state["status"] == "failed"
    assert "result_digest" not in state


async def test_an_expired_lease_is_taken_over_and_the_stale_worker_is_fenced() -> None:
    """A new worker takes over an expired lease; the stale completion is refused.

    The first worker leases the job and then stalls past the lease deadline. A
    second worker re-claims with the next generation, which the store installs on
    the job's stream. The stalled worker's completion carries the old generation,
    so the store fences it; the second worker completes the job, and the result is
    recorded exactly once.
    """
    store, clock = InMemoryStore(), _Clock()
    runner = _runner(store, clock)
    work_key = _work_key("iota")
    job_id = _job_id(work_key)
    contexts = _Contexts(job_id)
    await _submit(runner, contexts, work_key)

    stale = await runner.claim(context=contexts.next())
    assert stale is not None
    assert stale.generation == 1

    clock.advance(_TTL + timedelta(seconds=1))
    fresh = await runner.claim(context=contexts.next())
    assert fresh is not None
    assert fresh.generation == 2

    stale_receipt, _ = await runner.complete(
        context=contexts.next(),
        claim=stale,
        work_key=work_key,
        outcome="success",
        result_ref=ArtifactRef(
            artifact_id="artifact_019b6000-0000-7000-8000-00000000000c",
            digest=_DIGEST,
            size_bytes=4,
            media_type="application/json",
            content_encoding="identity",
            data_handling=_DH,
        ),
    )
    assert stale_receipt.outcome == "rejected"

    fresh_receipt, _ = await runner.complete(
        context=contexts.next(),
        claim=fresh,
        work_key=work_key,
        outcome="success",
        result_ref=ArtifactRef(
            artifact_id="artifact_019b6000-0000-7000-8000-00000000000d",
            digest=_DIGEST,
            size_bytes=4,
            media_type="application/json",
            content_encoding="identity",
            data_handling=_DH,
        ),
    )
    assert fresh_receipt.outcome == "accepted"
    state = store.load_aggregate(attempt_aggregate_id(job_id))
    assert state is not None
    assert state["status"] == "succeeded"
    assert state["attempt"] == 2
