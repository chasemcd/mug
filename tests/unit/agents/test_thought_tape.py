"""A carried thought replays exactly when the model output is on the durable tape.

These tests drive ``mug.agents.LLMController`` against the in-memory store with a
fixed clock and a counting fake adapter. They prove the durable output tape closes
the replay gap: a decision that carries its own reply forward as a thought, when
replayed by a fresh controller sharing the same store and tape (a crash-and-retry),
re-derives the identical thought and action without a second model call. Without the
tape the same replay sees no output, carries the wrong thought, and falls back --
the bug the tape fixes -- which the contrast test pins.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

from mug.agents import AgentIds, LLMController, compile_agent
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.kernel import Digest, Duration
from mug.providers import (
    InMemoryOutputTape,
    ModelCall,
    ModelCompletion,
    ModelProvider,
    OutputTape,
    Usage,
)
from mug.runtime import CommandContext
from mug.scheduling import DecisionRequest
from mug.scheduling.runtime import DecisionContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


def _ids() -> AgentIds:
    return AgentIds(
        agent_version_id="agentver_" + _UUID.format(0x500),
        agent_definition_id="agentdef_" + _UUID.format(0x510),
        agent_key="thinker",
        version_number=1,
        prompt_version_id="promptver_" + _UUID.format(0x520),
        fallback_policy_key="thinker-fallback",
    )


class _Thinker(LLMAgent):
    """An agent that reasons over its own carried thought, then names an action."""

    provider = Provider.ANTHROPIC
    model = "claude-sonnet-4-5"
    secret = "chat-provider-key"
    on_timeout = Fallback.REPEAT_LAST

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        return (
            f"prior thought: {thoughts.latest or '(none)'}\n"
            "reason, then end with 'Action: <one word>'.\n"
            f"actions: {', '.join(self.available_actions(env, agent_id))}"
        )


class _Env:
    """A tiny env answering the controller's action-vocabulary read."""

    def legal_actions(self, agent_id: str) -> list[str]:
        return ["WAIT", "GO"]


class _CountingAdapter:
    """A fake adapter that answers a fixed reply and counts every call."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _call: ModelCall) -> ModelCompletion:
        self.calls += 1
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=1),
            output={"text": "I will commit to the plan. Action: GO"},
        )


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


def _controller(
    *, store: InMemoryStore, adapter: _CountingAdapter, tape: OutputTape | None
) -> LLMController:
    gens = itertools.count(1)
    provider = ModelProvider(
        store=store,
        adapter=adapter,  # type: ignore[arg-type]
        now=lambda: _START,
        new_generation_id=lambda: "generation_" + _UUID.format(next(gens)),
        output_tape=tape,
    )
    return LLMController(
        agent=_Thinker(),
        agent_version=compile_agent(_Thinker(), ids=_ids()),
        provider=provider,
        env=_Env(),
        agent_id="p1",
        new_context=_Factory(),
        resolve_secret=lambda _: "sk-secret",
    )


def _context() -> DecisionContext:
    """Build one decision context; its id fixes the model call id on replay."""
    request = DecisionRequest(
        decision_id="decision_" + _UUID.format(0xD01),
        actor_id="actor_" + _UUID.format(0x400),
        channel_key="game",
        execution_mode="server",
        episode_generation=1,
        source_observation_digest=_DIGEST,
        deadline=(_START + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        validity_window=Duration(microseconds=1_000_000),
        submitted_at=_START.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    )
    return DecisionContext(request=request, observation=[0.0])


async def test_a_carried_thought_and_action_replay_exactly_with_the_tape() -> None:
    """A fresh controller replays the exact thought and action, model call once."""
    store, tape = InMemoryStore(), InMemoryOutputTape()

    live = _CountingAdapter()
    first = _controller(store=store, adapter=live, tape=tape)
    action = await first.decide(_context())

    # A fresh controller (a new process after a crash) shares the durable store and
    # tape, and never calls the model again.
    fresh_adapter = _CountingAdapter()
    replay = _controller(store=store, adapter=fresh_adapter, tape=tape)
    replay_action = await replay.decide(_context())

    assert action == 1  # GO
    assert replay_action == action
    # The carried thought is byte-identical, so the next prompt reproduces exactly.
    assert replay.thoughts.latest == first.thoughts.latest
    assert first.thoughts.latest == "I will commit to the plan. Action: GO"
    # The model ran only for the first decision; the replay read the tape.
    assert live.calls == 1
    assert fresh_adapter.calls == 0


async def test_without_the_tape_the_replay_loses_the_thought_and_falls_back() -> None:
    """The contrast: no tape, so the replay cannot re-derive the reply.

    A replayed call with no tape returns no output, so the fresh controller carries
    the wrong thought and cannot read the action -- the exact gap the tape closes.
    """
    store = InMemoryStore()

    first = _controller(store=store, adapter=_CountingAdapter(), tape=None)
    await first.decide(_context())

    from mug.agents import ControllerDecodeMiss

    replay = _controller(store=store, adapter=_CountingAdapter(), tape=None)
    raised = False
    try:
        await replay.decide(_context())
    except ControllerDecodeMiss:
        raised = True

    # The action could not be re-derived (decode miss -> the seat would fall back),
    # and the carried thought is not the real one.
    assert raised is True
    assert replay.thoughts.latest != first.thoughts.latest
