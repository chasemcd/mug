"""The agent episode runner drives one LLM seat through a whole episode.

These tests drive ``mug.agents.AgentEpisode`` against the in-memory store with a
fixed clock, a scripted fake adapter, and hand-built command contexts. They prove
the runner joins the three built pieces: the stepping loop samples the seat every
frame, the scheduler drives a decision at the agent's cadence, and the decided
action lands on the seat so the loop steps on it. They also prove the runner feeds
the agent -- one history step per frame, and a chat message the transport posts --
and that the cadence gates how often the model is called.

With the in-memory store a decision resolves within one event-loop yield, so the
decided action lands on the seat the frame after it is requested; the tests assert
that concrete behaviour, not a wall-clock race.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import Any, ClassVar

from mug.agents import AgentEpisode, AgentIds, LLMController, compile_agent
from mug.authoring import (
    Chat,
    Fallback,
    History,
    LLMAgent,
    Provider,
    Thoughts,
)
from mug.game.controllers import ScheduledSeat
from mug.game.env import StepResult
from mug.kernel import Digest
from mug.providers import ModelCall, ModelCompletion, ModelProvider, Usage
from mug.runtime import CommandContext
from mug.scheduling import FallbackRule, Scheduler
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)

_IDS = AgentIds(
    agent_version_id="agentver_" + _UUID.format(0x430),
    agent_definition_id="agentdef_" + _UUID.format(0x431),
    agent_key="grid-runner",
    version_number=1,
    prompt_version_id="promptver_" + _UUID.format(0x440),
    fallback_policy_key="grid-fallback",
)


class _GridEnv:
    """A tiny single-seat env: it steps a counter and ends after ``steps`` frames.

    It duck-types the loop's ``SteppableEnv`` (reset, step -> ``StepResult``) and
    the controller's reads (legal actions, text view, canonical state), so the loop
    steps it and the model reads the same object. It records the applied actions.
    """

    ACTIONS: ClassVar[list[str]] = ["LEFT", "RIGHT", "STAY"]

    def __init__(self, *, steps: int = 6) -> None:
        self._t = 0
        self._max = steps
        self.actions: list[int] = []

    def reset(self) -> StepResult:
        self._t = 0
        self.actions = []
        return StepResult([0.0], 0.0, False, False)

    def step(self, action: int) -> StepResult:
        self.actions.append(int(action))
        self._t += 1
        terminated = self._t >= self._max
        reward = 1.0 if terminated else 0.0
        return StepResult([float(self._t)], reward, terminated, False)

    def legal_actions(self, agent_id: str) -> list[str]:
        return list(self.ACTIONS)

    def text_view(self, agent_id: str) -> str:
        return f"t={self._t}; you are {agent_id}"

    def get_state(self) -> dict[str, int]:
        return {"t": self._t}


class GridRunner(LLMAgent):
    """An author's agent: it shows its plan, its past moves, the chat, the game."""

    provider = Provider.ANTHROPIC
    model = "claude-sonnet-4-5"
    secret = "chat-provider-key"
    decides_every = 1
    on_timeout = Fallback.REPEAT_LAST

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Chat,
        thoughts: Thoughts,
    ) -> str:
        moves = ", ".join(a or "-" for a in history.actions_of(agent_id))
        said = "; ".join(m.text for m in chat.last(3))
        return (
            f"plan: {thoughts.latest or 'none'}\n"
            f"moves: {moves}\n"
            f"chat: {said}\n"
            f"{env.text_view(agent_id)}\n"  # type: ignore[attr-defined]
            f"actions: {', '.join(self.available_actions(env, agent_id))}"
        )


def _view(env: Any, agent_id: str) -> str:
    """Render one seat's game as text for its prompt (a study seam)."""
    return env.text_view(agent_id)


class _Adapter:
    """A fake provider adapter: it records each call and always answers RIGHT."""

    def __init__(self) -> None:
        self.seen: list[ModelCall] = []

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.seen.append(call)
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=1),
            output={"text": "Move over. Action: RIGHT"},
        )

    def prompts(self) -> list[str]:
        return [call.payload["messages"][0]["content"] for call in self.seen]


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


def _episode(
    *,
    env: _GridEnv,
    adapter: _Adapter,
    decides_every: int = 1,
    max_steps: int = 20,
) -> tuple[AgentEpisode, InMemoryStore]:
    store, factory = InMemoryStore(), _Factory()
    gens = itertools.count(1)
    provider = ModelProvider(
        store=store,
        adapter=adapter,  # type: ignore[arg-type]
        now=lambda: _START,
        new_generation_id=lambda: "generation_" + _UUID.format(next(gens)),
    )
    agent = GridRunner()
    agent.decides_every = decides_every
    controller = LLMController(
        agent=agent,
        agent_version=compile_agent(agent, ids=_IDS),
        provider=provider,
        env=env,
        agent_id="runner",
        new_context=factory,
        resolve_secret=lambda _: "sk-secret",
    )
    scheduler = Scheduler(
        store=store,
        now=lambda: _START,
        fallback=FallbackRule(on_timeout="repeat-last", on_stale="repeat-last"),
        default_action=0,
    )
    decisions = itertools.count(0xB01)
    runner = AgentEpisode(
        agent=agent,
        controller=controller,
        scheduler=scheduler,
        seat=ScheduledSeat(default_action=0),
        env=env,
        agent_id="runner",
        actor_id="actor_" + _UUID.format(0x411),
        channel_key="game",
        episode_id="episode_" + _UUID.format(0x7),
        interaction_id="interaction_" + _UUID.format(0x6),
        seat_key="left",
        episode_generation=1,
        new_context=factory,
        new_decision_id=lambda: "decision_" + _UUID.format(next(decisions)),
        now=lambda: _START,
        decision_timeout=1.0,
        text_view=_view,
        max_steps=max_steps,
    )
    return runner, store


async def test_the_runner_drives_a_full_episode() -> None:
    """The model decides each frame and the decided action lands on the seat."""
    env, adapter = _GridEnv(steps=6), _Adapter()
    runner, store = _episode(env=env, adapter=adapter)

    result = await runner.run()

    # The episode ran to the env terminal, one history step recorded per frame.
    assert result.summary.frames == 6
    assert result.summary.solved is True
    assert len(result.history) == 6
    # Every decision produced an action; the model reasoned each step.
    assert len(result.decisions) == 6
    assert all(d.result.outcome == "produced" for d in result.decisions)
    assert len(result.thoughts) == 6
    # The seat holds the default (0) for the first frame, then the model's RIGHT (1):
    # a decision requested on a frame lands before the next frame samples the seat.
    right = _GridEnv.ACTIONS.index("RIGHT")
    assert env.actions == [0, right, right, right, right, right]
    # The decision and its model call are both recorded on their own streams.
    decision_head = store.load_aggregate("decision_" + _UUID.format(0xB01))
    assert decision_head is not None
    assert decision_head["schema"]["name"] == "mug.api-12.decision-result"
    call_head = store.load_aggregate("modelcall_" + _UUID.format(0xB01))
    assert call_head is not None
    assert call_head["schema"]["name"] == "mug.api-13.provider-response"


async def test_a_rare_cadence_fires_no_decision() -> None:
    """A cadence wider than the episode never calls the model; the seat defaults."""
    env, adapter = _GridEnv(steps=6), _Adapter()
    runner, _ = _episode(env=env, adapter=adapter, decides_every=100)

    result = await runner.run()

    # No frame lands on the cadence, so no decision runs and no model call is made.
    assert result.decisions == []
    assert adapter.seen == []
    # The seat holds its default action the whole episode; history is still fed.
    assert env.actions == [0, 0, 0, 0, 0, 0]
    assert len(result.history) == 6


async def test_the_runner_exposes_its_model_calls_for_a_decision_tape() -> None:
    """Every model call is collected on the result and builds the API-16 tape."""
    from mug.replay import build_decision_tape

    env, adapter = _GridEnv(steps=4), _Adapter()
    runner, _ = _episode(env=env, adapter=adapter)

    result = await runner.run()

    # One model call per frame, each a completed response with an output digest.
    assert len(result.model_calls) == 4
    assert all(call.response is not None for call in result.model_calls)
    # The collected calls assemble a valid decision tape for a replay bundle.
    tape = build_decision_tape(
        interaction_id="interaction_" + _UUID.format(0x6),
        results=result.model_calls,
    )
    assert len(tape.entries) == 4


async def test_a_posted_chat_message_reaches_the_model() -> None:
    """A chat message the transport posts is in the prompt the model then sees."""
    env, adapter = _GridEnv(steps=2), _Adapter()
    runner, _ = _episode(env=env, adapter=adapter)
    runner.post_message(sender="human", text="please cover the right side")

    await runner.run()

    assert any("please cover the right side" in prompt for prompt in adapter.prompts())
