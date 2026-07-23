"""The dispatch layer drains queued jobs and rediscovers them after a restart.

These tests drive ``mug.workers.JobQueue`` and ``mug.workers.WorkerPool`` against
the in-memory store with a fixed clock and hand-built command contexts. They prove
the durable-queue properties above the correctness core: a queued job drains to a
recorded success, a fresh queue rebuilt from the store rediscovers work that was
accepted but never started, a claimed or terminal job is not rediscovered, a
duplicate offer is ignored, and concurrent workers each take a distinct job.
"""

from __future__ import annotations

import asyncio
import itertools
from datetime import datetime, timedelta, timezone

from mug.kernel import ArtifactRef, DataHandlingRef, Digest, compute_digest
from mug.runtime import CommandContext
from mug.storage import InMemoryStore
from mug.workers import JobQueue, JobRunner, WorkerPool, WorkOutcome

_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_DH = DataHandlingRef(privacy_labels=["research"])
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_TTL = timedelta(seconds=30)
_LEASE_EPOCH = "leaseepoch_019b6000-0000-7000-8000-000000000001"
_ARTIFACT = ArtifactRef(
    artifact_id="artifact_019b6000-0000-7000-8000-00000000000b",
    digest=_DIGEST,
    size_bytes=4,
    media_type="application/json",
    content_encoding="identity",
    data_handling=_DH,
)


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


def _job_id(work_key: Digest) -> str:
    return "job_" + _uuid7(work_key.hex)


class _Factory:
    """Mint a fresh command context on a job's stream, keyed by its id.

    One global counter keeps the command, receipt, event, and idempotency ids
    distinct across every operation and job, while the stream and aggregate bind
    to the named job, as a real gateway would mint them.
    """

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def __call__(self, job_id: str) -> CommandContext:
        n = next(self._counter)
        body = f"019b6000-0000-7000-8000-{n:012x}"
        return CommandContext.model_validate(
            {
                "command_id": "command_" + body,
                "receipt_id": "receipt_" + body,
                "error_id": "error_" + body,
                "idempotency_key": "idem_" + f"{n:021d}" + "A",
                "event_id": "event_" + body,
                "stream_id": "stream_" + job_id.split("_", 1)[1],
                "producer": {
                    "epoch_id": "prodepoch_019b6000-0000-7000-8000-000000000009",
                    "sequence": n,
                    "content_digest": _DIGEST.model_dump(mode="json"),
                },
                "aggregate_id": job_id,
                "principal": {
                    "kind": "service",
                    "id": "service_019b6000-0000-7000-8000-00000000000a",
                },
                "recorded_at": "2026-07-22T00:00:00.000000Z",
                "event_data_handling": {"privacy_labels": ["research"]},
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


async def _submit(runner: JobRunner, factory: _Factory, work_key: Digest) -> str:
    job_id = _job_id(work_key)
    receipt, _ = await runner.submit(
        context=factory(job_id),
        job_kind="simulate-batch",
        work_key=work_key,
        submitted_at="2026-07-22T00:00:00.000000Z",
    )
    assert receipt.outcome == "accepted"
    return job_id


async def _succeed(_: object) -> WorkOutcome:
    return WorkOutcome(outcome="success", result_ref=_ARTIFACT)


def _pool(
    store: InMemoryStore,
    runner: JobRunner,
    queue: JobQueue,
    factory: _Factory,
    *,
    handler: object = _succeed,
    workers: int = 1,
) -> WorkerPool:
    return WorkerPool(
        runner=runner,
        queue=queue,
        store=store,
        handler=handler,  # type: ignore[arg-type]
        new_context=factory,
        workers=workers,
    )


async def test_the_pool_drains_a_queued_job_to_success() -> None:
    """A queued job the pool drains ends terminal, with the result recorded."""
    store, clock = InMemoryStore(), _Clock()
    runner, factory, queue = _runner(store, clock), _Factory(), JobQueue()
    job_id = await _submit(runner, factory, _work_key("alpha"))
    queue.offer(job_id)

    processed = await _pool(store, runner, queue, factory).drain()

    assert processed == 1
    state = store.load_aggregate(job_id)
    assert state is not None
    assert state["status"] == "succeeded"
    assert state["result_digest"] is not None


async def test_rebuild_rediscovers_a_queued_job_after_a_restart() -> None:
    """A fresh queue rebuilt from the store rediscovers a submitted job."""
    store, clock = InMemoryStore(), _Clock()
    runner, factory = _runner(store, clock), _Factory()
    job_id = await _submit(runner, factory, _work_key("beta"))

    # A restart: a brand-new queue with no in-process memory of the submit.
    queue = JobQueue()
    assert queue.rebuild(store) == 1
    assert len(queue) == 1

    await _pool(store, runner, queue, factory).drain()
    state = store.load_aggregate(job_id)
    assert state is not None
    assert state["status"] == "succeeded"


async def test_rebuild_skips_a_claimed_or_terminal_job() -> None:
    """A job past its request head is not rediscovered by a rebuild."""
    store, clock = InMemoryStore(), _Clock()
    runner, factory = _runner(store, clock), _Factory()

    claimed = await _submit(runner, factory, _work_key("gamma"))
    assert await runner.claim(context=factory(claimed)) is not None

    done = await _submit(runner, factory, _work_key("delta"))
    claim = await runner.claim(context=factory(done))
    assert claim is not None
    await runner.complete(
        context=factory(done),
        claim=claim,
        work_key=_work_key("delta"),
        outcome="failure",
    )

    queue = JobQueue()
    assert queue.rebuild(store) == 0
    assert len(queue) == 0


async def test_a_duplicate_offer_is_ignored() -> None:
    """Offering the same job id twice leaves one entry in the queue."""
    store, clock = InMemoryStore(), _Clock()
    runner, factory, queue = _runner(store, clock), _Factory(), JobQueue()
    job_id = await _submit(runner, factory, _work_key("epsilon"))

    assert queue.offer(job_id) is True
    assert queue.offer(job_id) is False
    assert len(queue) == 1


async def test_the_pool_skips_a_job_that_lost_its_queued_head() -> None:
    """A job claimed out of band is dropped by the pool, not double-run.

    The queue still names the job, but another worker has already claimed it, so
    its head is a running run. The pool reads the head, finds it is no longer a
    queued request, and takes no action -- the out-of-band lease is untouched.
    """
    store, clock = InMemoryStore(), _Clock()
    runner, factory, queue = _runner(store, clock), _Factory(), JobQueue()
    job_id = await _submit(runner, factory, _work_key("zeta"))
    queue.offer(job_id)

    # Another worker claims the job before the pool gets to it.
    claim = await runner.claim(context=factory(job_id))
    assert claim is not None
    revision = store.revision_of(job_id)

    assert await _pool(store, runner, queue, factory).run_once() is True
    # The pool did not commit anything: the revision is unchanged.
    assert store.revision_of(job_id) == revision


async def test_concurrent_workers_each_take_a_distinct_job() -> None:
    """Four workers draining the same queue each complete a distinct job once."""
    store, clock = InMemoryStore(), _Clock()
    runner, factory, queue = _runner(store, clock), _Factory(), JobQueue()
    job_ids = [
        await _submit(runner, factory, _work_key(f"job-{i}")) for i in range(4)
    ]
    for job_id in job_ids:
        queue.offer(job_id)

    pool = _pool(store, runner, queue, factory, workers=4)
    results = await asyncio.gather(*(pool.run_once() for _ in job_ids))

    assert all(results)
    assert len(queue) == 0
    for job_id in job_ids:
        state = store.load_aggregate(job_id)
        assert state is not None
        assert state["status"] == "succeeded"
        assert state["attempt"] == 1


async def test_start_and_close_run_the_worker_loops() -> None:
    """The worker loops drain the queue between ``start`` and ``aclose``."""
    store, clock = InMemoryStore(), _Clock()
    runner, factory, queue = _runner(store, clock), _Factory(), JobQueue()
    job_id = await _submit(runner, factory, _work_key("eta"))
    queue.offer(job_id)

    pool = _pool(store, runner, queue, factory, workers=2)
    await pool.start()
    try:
        for _ in range(200):
            head = store.load_aggregate(job_id)
            if head is not None and head.get("status") == "succeeded":
                break
            await asyncio.sleep(0.01)
    finally:
        await pool.aclose()

    state = store.load_aggregate(job_id)
    assert state is not None
    assert state["status"] == "succeeded"
