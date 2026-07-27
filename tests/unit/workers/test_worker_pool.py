"""The dispatch layer drains queued jobs and rediscovers them after a restart.

These tests drive ``mug.workers.JobQueue`` and ``mug.workers.WorkerPool`` against
the in-memory store with a fixed clock and hand-built command contexts. They prove
the durable-queue properties above the correctness core: a queued job drains to a
recorded success, a fresh queue rebuilt from the store rediscovers work that was
accepted but never started, a job under a live lease and a terminal job are not
rediscovered, a duplicate offer is ignored, and concurrent workers each take a
distinct job.

They also prove the cold-restart takeover: a job whose worker went away with its
lease is rediscovered by a restarted process, and the work key and job kind the
takeover needs are read from the request, which no claim ever rewrites.
"""

from __future__ import annotations

import asyncio
import itertools
import re
from datetime import datetime, timedelta, timezone

from mug.jobs import JobRequest, JobResult
from mug.kernel import ArtifactRef, DataHandlingRef, Digest, compute_digest
from mug.kernel.ids import id_pattern
from mug.runtime import CommandContext
from mug.storage import InMemoryStore
from mug.workers import (
    JobQueue,
    JobRunner,
    WorkerPool,
    WorkOutcome,
    attempt_aggregate_id,
)

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
    state = store.load_aggregate(attempt_aggregate_id(job_id))
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
    assert queue.rebuild(store, runner) == 1
    assert len(queue) == 1

    await _pool(store, runner, queue, factory).drain()
    state = store.load_aggregate(attempt_aggregate_id(job_id))
    assert state is not None
    assert state["status"] == "succeeded"


async def test_rebuild_skips_a_live_lease_and_a_terminal_job() -> None:
    """A job under a live lease, and a finished job, are not rediscovered.

    Both have an attempt: one is running with time left on its lease, the other is
    terminal. Neither is waiting for a worker, so a rebuild leaves both alone -- the
    takeover rule is bounded by the lease deadline, not by the restart.
    """
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
    assert queue.rebuild(store, runner) == 0
    assert len(queue) == 0


async def test_a_duplicate_offer_is_ignored() -> None:
    """Offering the same job id twice leaves one entry in the queue."""
    store, clock = InMemoryStore(), _Clock()
    runner, factory, queue = _runner(store, clock), _Factory(), JobQueue()
    job_id = await _submit(runner, factory, _work_key("epsilon"))

    assert queue.offer(job_id) is True
    assert queue.offer(job_id) is False
    assert len(queue) == 1


async def test_the_pool_skips_a_job_under_a_live_lease() -> None:
    """A job claimed out of band is dropped by the pool, not double-run.

    The queue still names the job, but another worker has already claimed it and its
    lease is live. The pool asks for a lease, is refused, and takes no action -- the
    out-of-band lease is untouched.
    """
    store, clock = InMemoryStore(), _Clock()
    runner, factory, queue = _runner(store, clock), _Factory(), JobQueue()
    job_id = await _submit(runner, factory, _work_key("zeta"))
    queue.offer(job_id)

    # Another worker claims the job before the pool gets to it.
    claim = await runner.claim(context=factory(job_id))
    assert claim is not None
    attempt_id = attempt_aggregate_id(job_id)
    revision = store.revision_of(attempt_id)

    assert await _pool(store, runner, queue, factory).run_once() is True
    # The pool did not commit anything: the attempt revision is unchanged.
    assert store.revision_of(attempt_id) == revision


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
        state = store.load_aggregate(attempt_aggregate_id(job_id))
        assert state is not None
        assert state["status"] == "succeeded"
        assert state["attempt"] == 1


async def test_a_cold_restart_takes_over_a_job_its_worker_went_away_with() -> None:
    """A job whose worker went away mid-flight is rediscovered and finished.

    The first worker leases the job and then the process it ran in disappears: the
    test builds a new runner, a new queue, and a new pool over the same store, which
    is all a restarted container keeps. Once the lease deadline passes, the rebuild
    rediscovers the job, and the new worker takes the attempt over and completes it.
    """
    store, clock = InMemoryStore(), _Clock()
    runner, factory, queue = _runner(store, clock), _Factory(), JobQueue()
    job_id = await _submit(runner, factory, _work_key("theta"))
    queue.offer(job_id)
    assert await runner.claim(context=factory(job_id)) is not None

    # The process goes away with the lease, and nothing in it survives.
    del runner, queue
    clock.advance(_TTL + timedelta(seconds=1))
    restarted = _runner(store, clock)
    rebuilt = JobQueue()
    assert rebuilt.rebuild(store, restarted) == 1

    assert await _pool(store, restarted, rebuilt, factory).drain() == 1
    state = store.load_aggregate(attempt_aggregate_id(job_id))
    assert state is not None
    assert state["status"] == "succeeded"
    # The second attempt: the takeover raised the generation the store fences on.
    assert state["attempt"] == 2


async def test_a_takeover_reads_the_work_key_from_the_request() -> None:
    """The work key the takeover records is the one the submission named.

    This is what the two heads buy. The handler is handed the original request, and
    the durable result the completion binds is keyed by the original work key, so a
    restarted worker produces the same result as the worker that went away.
    """
    store, clock = InMemoryStore(), _Clock()
    runner, factory = _runner(store, clock), _Factory()
    work_key = _work_key("iota")
    job_id = await _submit(runner, factory, work_key)
    assert await runner.claim(context=factory(job_id)) is not None
    clock.advance(_TTL + timedelta(seconds=1))

    seen: list[JobRequest] = []

    async def _capture(request: JobRequest) -> WorkOutcome:
        seen.append(request)
        return WorkOutcome(outcome="success", result_ref=_ARTIFACT)

    restarted = _runner(store, clock)
    rebuilt = JobQueue()
    rebuilt.rebuild(store, restarted)
    await _pool(store, restarted, rebuilt, factory, handler=_capture).drain()

    assert [request.work_key for request in seen] == [work_key]
    assert seen[0].job_kind == "simulate-batch"
    state = store.load_aggregate(attempt_aggregate_id(job_id))
    assert state is not None
    # The bound result digest is the digest of the result keyed by that work key.
    expected = JobResult(
        job_id=job_id,
        work_key=work_key,
        outcome="success",
        result_ref=_ARTIFACT,
        completed_at="2026-07-22T00:00:31.000000Z",
    )
    assert state["result_digest"] == compute_digest(
        expected.model_dump(mode="json", exclude_none=True)
    ).model_dump(mode="json")


async def test_the_request_head_outlives_every_attempt() -> None:
    """No claim and no completion ever rewrites the submitted request."""
    store, clock = InMemoryStore(), _Clock()
    runner, factory, queue = _runner(store, clock), _Factory(), JobQueue()
    work_key = _work_key("kappa")
    job_id = await _submit(runner, factory, work_key)
    for _ in range(3):
        assert await runner.claim(context=factory(job_id)) is not None
        clock.advance(_TTL + timedelta(seconds=1))
    queue.offer(job_id)
    await _pool(store, runner, queue, factory).drain()

    head = store.load_aggregate(job_id)
    assert head is not None
    assert head["work_key"] == work_key.model_dump(mode="json")
    assert "status" not in head
    # The request was written once, by the submission, and never again.
    assert store.revision_of(job_id) == 1


def test_the_attempt_aggregate_id_is_derived_from_the_job_id_alone() -> None:
    """The derived id is stable, distinct from the job's, and job-shaped.

    A worker that starts with no memory must find the attempt with no lookup, so the
    derivation may read nothing but the job id -- no clock, no entropy, no secret.
    """
    job_id = _job_id(_work_key("lambda"))
    other = _job_id(_work_key("mu"))

    derived = attempt_aggregate_id(job_id)
    assert derived == attempt_aggregate_id(job_id)
    assert derived != job_id
    assert derived != attempt_aggregate_id(other)
    # It is a legal job identifier: the kernel's identifier kinds are frozen, and
    # the attempt state belongs to the job.
    assert re.fullmatch(id_pattern("job"), derived) is not None


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
            head = store.load_aggregate(attempt_aggregate_id(job_id))
            if head is not None and head.get("status") == "succeeded":
                break
            await asyncio.sleep(0.01)
    finally:
        await pool.aclose()

    state = store.load_aggregate(attempt_aggregate_id(job_id))
    assert state is not None
    assert state["status"] == "succeeded"
