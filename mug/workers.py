"""The durable jobs runtime: submit, lease, and complete one unit of work (API-22).

The API-22 family (``mug.jobs``) owns three records -- the idempotent
``JobRequest``, the leased ``JobRun`` attempt, and the single durable
``JobResult`` per work key -- but adds no runtime. This module is that runtime. It
drives the three records through the shared command spine (``mug.runtime``), so a
job's lineage is a canonical event stream like any other aggregate, and it reuses
the store's own generation fencing to make a lease safe. It adds no new durability
primitive.

The design rests on one identity rule: a job's id is its aggregate and its stream.
The caller content-addresses the ``job_id`` from the ``work_key`` (the same way the
gateway content-addresses a command id), so two submissions of the same work key
name the same aggregate and the store coalesces the duplicate. The job's stream is
then the ordered lineage of the run: the request, each leased attempt, and the
terminal state.

A lease is safe because a claim carries a fencing generation equal to its attempt.
The store installs a strictly greater generation on the job's stream at each claim
and refuses a write from a generation below the installed one. So a worker whose
lease expired cannot complete a job after a newer worker has taken it over: its
completion carries the old generation and the store fences it
(``lease.stale_generation``). The revision guard refuses the same write a second
way, so the guarantee holds even when the generations coincide.

The runtime is a producer boundary, so the caller injects the impure parts: the
store, the clock, the lease time-to-live, and a lease-id minter. The caller also
mints the ``CommandContext`` for each operation (the one entropy-and-clock
boundary), exactly as every other family service takes an already-minted context.
So a test drives the whole lifecycle with a fixed clock and hand-built contexts,
with no worker pool and no socket.

Above the correctness core sits a thin dispatch layer: a durable ``JobQueue`` and a
``WorkerPool``. The queue is an index of jobs ready to claim; a live submit offers
its job id, and a restart rebuilds the index from the store, so a worker
rediscovers work that was accepted but never started. The pool drains the queue
with N concurrent workers, each of which claims a lease, runs an injected handler,
and completes the job. The pool owns no clock and no entropy; it takes a context
factory that mints a fresh ``CommandContext`` on a job's stream, exactly as the
gateway mints one for every other family. The ``mug simulate`` batch runner (the
CLI face of the pool) stays out of this slice.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, cast

from mug.jobs import JobRequest, JobResult, JobRun
from mug.kernel import (
    ArtifactRef,
    CommandReceipt,
    CommandTypeRef,
    Digest,
    LeaseRef,
    TypedObject,
    UtcInstant,
    compute_digest,
)
from mug.runtime import CommandContext, FencingClaim, commit_command
from mug.storage import Store

_JobRecord = JobRequest | JobRun | JobResult

_SUBMIT = CommandTypeRef(name="job.submit", version=0)
_CLAIM = CommandTypeRef(name="job.claim", version=0)
_COMPLETE = CommandTypeRef(name="job.complete", version=0)

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"


class LeaseHeld(Exception):
    """A claim was refused because a live worker still holds the lease.

    The current attempt is running and its lease has not expired, so a second
    worker must not take the job. A caller waits for the lease to expire (or for
    the holder to complete the job) and tries again.
    """


class JobUnknown(Exception):
    """A claim named a job that was never submitted; there is nothing to lease."""


class JobTerminal(Exception):
    """A claim named a job that already reached a terminal state; it is done."""


@dataclass(frozen=True)
class JobClaim:
    """A held lease on one job: the run, its fencing generation, and its revision.

    The worker carries ``generation`` on its completion so the store fences a
    superseded worker, and ``revision`` is the aggregate revision the completion
    expects, so a re-claim by a newer worker also refuses the stale completion.
    """

    run: JobRun
    generation: int
    revision: int


class JobRunner:
    """Drive one job's records through the command spine, with a fenced lease.

    The runner holds the injected impurity -- the store, the clock, the lease
    time-to-live, and the lease-id minter -- and exposes the three lifecycle
    operations. Each operation takes a ``CommandContext`` the caller minted for the
    job's aggregate; the runner adds the fencing generation a lease needs.
    """

    def __init__(
        self,
        *,
        store: Store,
        now: Callable[[], datetime],
        lease_ttl: timedelta,
        lease_epoch_id: str,
        new_lease_id: Callable[[], str],
    ) -> None:
        self._store = store
        self._now = now
        self._lease_ttl = lease_ttl
        self._lease_epoch_id = lease_epoch_id
        self._new_lease_id = new_lease_id

    async def submit(
        self,
        *,
        context: CommandContext,
        job_kind: str,
        work_key: Digest,
        submitted_at: UtcInstant,
        priority: Literal["low", "normal", "high"] | None = None,
    ) -> tuple[CommandReceipt, JobRequest]:
        """Record one job submission, keyed by its content, and return the request.

        The commit creates the job aggregate. A second submission of the same work
        key names the same aggregate (the caller content-addresses the id), so the
        store refuses it with a no-effect ``resource.already_exists`` rejection --
        the work-key idempotency the family promises. An identical retry of the
        same command replays to the original receipt with no second effect.
        """
        request = JobRequest(
            job_id=context.aggregate_id,
            job_kind=job_kind,
            work_key=work_key,
            submitted_at=submitted_at,
            priority=priority,
        )
        receipt = await commit_command(
            context,
            command=_SUBMIT,
            new_state=_state(request),
            result=_typed(request),
            store=self._store,
        )
        return receipt, request

    async def claim(self, *, context: CommandContext) -> JobClaim | None:
        """Lease the job for one attempt, or refuse a job that is not claimable.

        The runner reads the job's current state. A queued request is a first
        attempt; a running attempt whose lease has expired is a re-attempt with the
        next generation; a running attempt whose lease is live raises
        ``LeaseHeld``; a terminal job raises ``JobTerminal``. The claim commits a
        running ``JobRun`` under a fencing generation equal to the attempt, so the
        store installs a strictly greater generation on the stream. A concurrent
        claim that loses the revision race gets a no-effect rejection, and the
        runner returns ``None``.
        """
        job_id = context.aggregate_id
        state = self._store.load_aggregate(job_id)
        if state is None:
            raise JobUnknown(job_id)
        revision = self._store.revision_of(job_id) or 0
        attempt = self._next_attempt(state, job_id)

        run = JobRun(
            job_id=job_id,
            attempt=attempt,
            status="running",
            lease=LeaseRef(
                lease_id=self._new_lease_id(),
                namespace_epoch_id=self._lease_epoch_id,
                generation=attempt,
            ),
            started_at=self._now_text(),
        )
        receipt = await commit_command(
            self._fenced(context, attempt),
            command=_CLAIM,
            new_state=_state(run),
            result=_typed(run),
            store=self._store,
            expected_revision=revision,
        )
        if receipt.outcome != "accepted":
            return None
        return JobClaim(run=run, generation=attempt, revision=revision + 1)

    async def complete(
        self,
        *,
        context: CommandContext,
        claim: JobClaim,
        work_key: Digest,
        outcome: Literal["success", "failure"],
        result_ref: ArtifactRef | None = None,
    ) -> tuple[CommandReceipt, JobResult]:
        """Record the job's terminal state and its single durable result.

        The completion commits the terminal ``JobRun`` under the claim's fencing
        generation, so a worker whose lease was taken over cannot complete the job
        (the store fences the stale generation, and the revision guard refuses it a
        second way). A successful run binds the result digest, so the result the
        runner returns is verifiable from the ledger. The result names its artifact
        for a success and names none for a failure.
        """
        result = JobResult(
            job_id=context.aggregate_id,
            work_key=work_key,
            outcome=outcome,
            result_ref=result_ref,
            completed_at=self._now_text(),
        )
        succeeded = outcome == "success"
        run = JobRun(
            job_id=context.aggregate_id,
            attempt=claim.generation,
            status="succeeded" if succeeded else "failed",
            lease=claim.run.lease,
            result_digest=compute_digest(_state(result)) if succeeded else None,
            started_at=claim.run.started_at,
        )
        receipt = await commit_command(
            self._fenced(context, claim.generation),
            command=_COMPLETE,
            new_state=_state(run),
            result=_typed(run),
            store=self._store,
            expected_revision=claim.revision,
        )
        return receipt, result

    # -- internals --------------------------------------------------------------

    def _next_attempt(self, state: dict[str, Any], job_id: str) -> int:
        """Return the attempt number a claim of the current state may take."""
        status = state.get("status")
        if status is None:
            return 1
        if status == "running":
            if not self._expired(state):
                raise LeaseHeld(job_id)
            return int(state["attempt"]) + 1
        raise JobTerminal(job_id)

    def _expired(self, state: dict[str, Any]) -> bool:
        """Return whether the running attempt's lease has passed its deadline."""
        return _lease_expired(state, self._now(), self._lease_ttl)

    def _fenced(self, context: CommandContext, generation: int) -> CommandContext:
        """Return the context stamped with the claim's fencing generation."""
        return context.model_copy(
            update={
                "fencing": FencingClaim(
                    epoch_id=context.producer.epoch_id, generation=generation
                )
            }
        )

    def _now_text(self) -> str:
        """Return the current instant in the canonical wire form."""
        return self._now().strftime(_INSTANT)


@dataclass(frozen=True)
class WorkOutcome:
    """What a handler decided about one job: its outcome and any artifact.

    A success names the artifact the work produced (the family binds it into the
    durable result); a failure names none.
    """

    outcome: Literal["success", "failure"]
    result_ref: ArtifactRef | None = None


WorkHandler = Callable[[JobRequest], Awaitable[WorkOutcome]]
NewContext = Callable[[str], CommandContext]


class JobQueue:
    """A durable-backed index of jobs ready to claim, drained by the worker pool.

    The queue holds job ids in arrival order and never a duplicate. A live submit
    offers its job id; a restart calls ``rebuild`` to fold the store's committed
    state, so a worker rediscovers work that was accepted but never started.

    Rediscovery covers a *queued* job -- one whose aggregate head is still its
    ``JobRequest``. A job a worker had already claimed carries a ``JobRun`` head
    that does not retain the work key, so re-completing a mid-flight job after a
    cold restart stays a follow-up: it needs the request retained beside the run.
    """

    def __init__(self) -> None:
        self._pending: deque[str] = deque()
        self._seen: set[str] = set()

    def rebuild(self, store: Store) -> int:
        """Fold the store's committed state and offer every queued job.

        Return how many jobs the rebuild added. A job already in the queue is not
        offered twice, so a rebuild is safe to run beside a live submit.
        """
        offered = 0
        for job_id, state in store.scan_aggregates():
            if _is_queued(state) and self.offer(job_id):
                offered += 1
        return offered

    def offer(self, job_id: str) -> bool:
        """Add a job id to the tail of the queue, unless it is already waiting."""
        if job_id in self._seen:
            return False
        self._seen.add(job_id)
        self._pending.append(job_id)
        return True

    def poll(self) -> str | None:
        """Take the next waiting job id, or None when the queue is empty."""
        if not self._pending:
            return None
        job_id = self._pending.popleft()
        self._seen.discard(job_id)
        return job_id

    def __len__(self) -> int:
        return len(self._pending)


class WorkerPool:
    """Drain the queue with N concurrent workers over one shared ``JobRunner``.

    A worker takes a job id, claims a lease, runs the injected handler, and
    completes the job. The fenced lease makes the whole pool safe: two workers
    that race the same job resolve to one success, and a worker whose lease was
    taken over cannot complete the job. A worker that finds the job no longer
    claimable -- another worker holds the lease, or the job is already done --
    drops it and takes the next.

    The pool owns no clock and no entropy. It takes ``new_context``, a factory
    that mints a fresh ``CommandContext`` on a job's stream (the one entropy-and-
    clock boundary), exactly as every other family service takes an already-minted
    context. A test drains the pool by hand with ``run_once``; a deployment calls
    ``start`` to spawn the worker loops and ``aclose`` to stop them.
    """

    def __init__(
        self,
        *,
        runner: JobRunner,
        queue: JobQueue,
        store: Store,
        handler: WorkHandler,
        new_context: NewContext,
        workers: int = 1,
        poll_interval: float = 0.05,
    ) -> None:
        self._runner = runner
        self._queue = queue
        self._store = store
        self._handler = handler
        self._new_context = new_context
        self._workers = workers
        self._poll_interval = poll_interval
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    async def run_once(self) -> bool:
        """Process one queued job, or return False when the queue is empty.

        The worker reads the job's request (its head still carries the work key),
        claims a lease, runs the handler, and completes the job. A job that is no
        longer a queued request, a claim that is refused, and a claim that loses
        the revision race each end the attempt with no effect; the worker returns
        True so the caller keeps draining.
        """
        job_id = self._queue.poll()
        if job_id is None:
            return False
        state = self._store.load_aggregate(job_id)
        if state is None or not _is_queued(state):
            return True
        request = JobRequest.model_validate(state)
        try:
            claim = await self._runner.claim(context=self._new_context(job_id))
        except (LeaseHeld, JobTerminal, JobUnknown):
            return True
        if claim is None:
            return True
        outcome = await self._handler(request)
        await self._runner.complete(
            context=self._new_context(job_id),
            claim=claim,
            work_key=request.work_key,
            outcome=outcome.outcome,
            result_ref=outcome.result_ref,
        )
        return True

    async def drain(self) -> int:
        """Process queued jobs until the queue is empty; return the count."""
        processed = 0
        while await self.run_once():
            processed += 1
        return processed

    async def start(self) -> None:
        """Spawn the worker loops; each drains the queue until ``aclose``."""
        self._stop.clear()
        self._tasks = [
            asyncio.create_task(self._loop()) for _ in range(self._workers)
        ]

    async def aclose(self) -> None:
        """Stop the worker loops and wait for them to finish."""
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def _loop(self) -> None:
        """Drain the queue, then wait a beat when it is empty, until stopped."""
        while not self._stop.is_set():
            if not await self.run_once():
                await asyncio.sleep(self._poll_interval)


def _state(record: _JobRecord) -> dict[str, Any]:
    """Dump one job record to its canonical persisted form."""
    return record.model_dump(mode="json", exclude_none=True)


def _typed(record: _JobRecord) -> TypedObject:
    """Wrap one job record as the command result that carries its own schema."""
    return TypedObject(schema=record.schema, data=_state(record))


def _parse_instant(text: str) -> datetime:
    """Parse a canonical UTC instant into a timezone-aware datetime."""
    return datetime.strptime(text, _INSTANT).replace(tzinfo=timezone.utc)


def _lease_expired(state: dict[str, Any], now: datetime, lease_ttl: timedelta) -> bool:
    """Return whether a running attempt's lease has passed its deadline."""
    started = state.get("started_at")
    if started is None:
        return True
    return now >= _parse_instant(started) + lease_ttl


def _is_job(state: Any) -> bool:
    """Return whether an aggregate state is one of the API-22 job records."""
    if not isinstance(state, dict):
        return False
    schema = cast("dict[str, Any]", state).get("schema")
    if not isinstance(schema, dict):
        return False
    name = cast("dict[str, Any]", schema).get("name")
    return isinstance(name, str) and name.startswith("mug.api-22.")


def _is_queued(state: Any) -> bool:
    """Return whether an aggregate is a job still at its request head.

    A ``JobRequest`` head carries no ``status`` and still names the work key, so a
    worker can complete it; a ``JobRun`` head (claimed or terminal) does not.
    """
    return _is_job(state) and "status" not in state


__all__ = [
    "JobClaim",
    "JobQueue",
    "JobRunner",
    "JobTerminal",
    "JobUnknown",
    "LeaseHeld",
    "NewContext",
    "WorkHandler",
    "WorkOutcome",
    "WorkerPool",
]
