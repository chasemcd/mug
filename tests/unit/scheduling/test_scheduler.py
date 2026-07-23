"""The scheduler runtime awaits a controller under a deadline and records it.

These tests drive ``mug.scheduling.runtime.Scheduler`` against the in-memory store
with a movable clock, fake async controllers, and hand-built command contexts. They
prove the server-mode decision properties: a controller that returns before the
deadline is produced and fresh, one that returns late is timed out and falls back,
a controller that raises is failed and falls back, a decision past its deadline
never runs the controller, the fallback choice picks the repeat or the default
action, and a retry replays the recorded result.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

from mug.kernel import Digest, Duration
from mug.runtime import CommandContext
from mug.scheduling import DecisionRequest, FallbackRule, Scheduler
from mug.scheduling.runtime import DecisionContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_DEADLINE = "2026-07-22T00:00:01.000000Z"
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


class _Clock:
    """A movable clock: it returns a fixed instant until a test advances it."""

    def __init__(self) -> None:
        self._now = _START

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta


class _Factory:
    """Mint a fresh command context on an aggregate's stream, keyed by its id."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def __call__(self, aggregate_id: str) -> CommandContext:
        n = next(self._counter)
        body = _UUID.format(n)
        return CommandContext.model_validate(
            {
                "command_id": "command_" + body,
                "receipt_id": "receipt_" + body,
                "error_id": "error_" + body,
                "idempotency_key": "idem_" + f"{n:021d}" + "A",
                "event_id": "event_" + body,
                "stream_id": "stream_" + aggregate_id.split("_", 1)[1],
                "producer": {
                    "epoch_id": "prodepoch_" + _UUID.format(9),
                    "sequence": n,
                    "content_digest": _DIGEST.model_dump(mode="json"),
                },
                "aggregate_id": aggregate_id,
                "principal": {"kind": "service", "id": "service_" + _UUID.format(0xA)},
                "recorded_at": "2026-07-22T00:00:00.000000Z",
                "event_data_handling": {"privacy_labels": ["research"]},
            }
        )


def _request(seed: int = 0xB01) -> DecisionRequest:
    return DecisionRequest(
        decision_id="decision_" + _UUID.format(seed),
        actor_id="actor_" + _UUID.format(0x411),
        channel_key="game",
        execution_mode="server",
        episode_generation=3,
        source_observation_digest=_DIGEST,
        deadline=_DEADLINE,
        validity_window=Duration(microseconds=200000),
        submitted_at="2026-07-22T00:00:00.000000Z",
    )


def _scheduler(
    store: InMemoryStore,
    clock: _Clock,
    *,
    on_timeout: str = "repeat-last",
    default_action: int = 0,
) -> Scheduler:
    return Scheduler(
        store=store,
        now=clock,
        fallback=FallbackRule(on_timeout=on_timeout, on_stale="repeat-last"),  # type: ignore[arg-type]
        default_action=default_action,
    )


async def test_a_controller_that_returns_in_time_is_produced_and_fresh() -> None:
    """A decision the controller returns before the deadline is produced fresh."""
    store, clock, factory = InMemoryStore(), _Clock(), _Factory()
    request = _request()

    async def controller(ctx: DecisionContext) -> int:
        assert ctx.request.decision_id == request.decision_id
        return 2

    outcome = await _scheduler(store, clock).decide(
        request=request, observation=[0.0], controller=controller, new_context=factory
    )

    assert outcome.result.outcome == "produced"
    assert outcome.result.staleness == "fresh"
    assert outcome.result.action_digest is not None
    assert outcome.action == 2
    assert outcome.used_fallback is False
    head = store.load_aggregate(request.decision_id)
    assert head is not None
    assert head["schema"]["name"] == "mug.api-12.decision-result"


async def test_a_late_controller_is_timed_out_and_repeats_the_last_action() -> None:
    """A decision that arrives after the deadline times out and reuses the last."""
    store, clock, factory = InMemoryStore(), _Clock(), _Factory()

    async def late(_: DecisionContext) -> int:
        clock.advance(timedelta(seconds=2))
        return 2

    outcome = await _scheduler(store, clock).decide(
        request=_request(),
        observation=[0.0],
        controller=late,
        new_context=factory,
        last_action=5,
    )

    assert outcome.result.outcome == "timed-out"
    assert outcome.result.action_digest is None
    assert outcome.used_fallback is True
    assert outcome.action == 5  # repeat-last reused the last applied action


async def test_a_late_controller_with_no_last_action_uses_the_default() -> None:
    """Repeat-last with no last action falls through to the default action."""
    store, clock, factory = InMemoryStore(), _Clock(), _Factory()

    async def late(_: DecisionContext) -> int:
        clock.advance(timedelta(seconds=2))
        return 2

    outcome = await _scheduler(store, clock, default_action=7).decide(
        request=_request(), observation=[0.0], controller=late, new_context=factory
    )

    assert outcome.result.outcome == "timed-out"
    assert outcome.action == 7


async def test_a_raising_controller_is_failed_and_falls_back() -> None:
    """A controller that raises is recorded as failed and applies the fallback."""
    store, clock, factory = InMemoryStore(), _Clock(), _Factory()

    async def boom(_: DecisionContext) -> int:
        raise RuntimeError("provider down")

    outcome = await _scheduler(store, clock, default_action=1).decide(
        request=_request(), observation=[0.0], controller=boom, new_context=factory
    )

    assert outcome.result.outcome == "failed"
    assert outcome.used_fallback is True
    assert outcome.action == 1


async def test_a_decision_past_its_deadline_never_runs_the_controller() -> None:
    """A deadline already passed times out without calling the controller."""
    store, clock, factory = InMemoryStore(), _Clock(), _Factory()
    clock.advance(timedelta(seconds=2))
    ran: list[int] = []

    async def controller(_: DecisionContext) -> int:
        ran.append(1)
        return 3

    outcome = await _scheduler(store, clock).decide(
        request=_request(),
        observation=[0.0],
        controller=controller,
        new_context=factory,
    )

    assert not ran
    assert outcome.result.outcome == "timed-out"


async def test_the_default_action_fallback_ignores_the_last_action() -> None:
    """A default-action fallback uses the default even when a last action exists."""
    store, clock, factory = InMemoryStore(), _Clock(), _Factory()

    async def late(_: DecisionContext) -> int:
        clock.advance(timedelta(seconds=2))
        return 2

    outcome = await _scheduler(
        store, clock, on_timeout="default-action", default_action=9
    ).decide(
        request=_request(),
        observation=[0.0],
        controller=late,
        new_context=factory,
        last_action=5,
    )

    assert outcome.action == 9


async def test_a_retry_replays_the_recorded_result() -> None:
    """A second decide of the same decision id replays and skips the controller."""
    store, clock, factory = InMemoryStore(), _Clock(), _Factory()
    request = _request()
    calls: list[int] = []

    async def controller(_: DecisionContext) -> int:
        calls.append(1)
        return 2

    scheduler = _scheduler(store, clock)
    first = await scheduler.decide(
        request=request, observation=[0.0], controller=controller, new_context=factory
    )
    second = await scheduler.decide(
        request=request, observation=[0.0], controller=controller, new_context=factory
    )

    assert first.replayed is False
    assert second.replayed is True
    assert second.result.outcome == "produced"
    assert len(calls) == 1  # the replay did not run the controller again
