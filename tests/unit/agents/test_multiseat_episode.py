"""The multi-seat runner drives many seats over one shared environment.

These tests drive ``mug.agents.MultiAgentEpisode`` against the in-memory store with
a fixed clock and scripted fake adapters. They prove the runner joins the built
pieces for more than one seat: the shared loop steps every seat's action set each
frame, each LLM seat decides at its own cadence on its own controller, and each
agent's history records the whole frame -- so an agent reads what its partner did.
They also prove a human seat drives one env agent beside an LLM, and a posted chat
message reaches every agent seat.

With the in-memory store a decision resolves within one event-loop yield, so a
decided action lands on its seat the frame after it is requested; the tests assert
that concrete behaviour, not a wall-clock race.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import ClassVar

from mug.agents import (
    AgentIds,
    AgentSeat,
    HumanSeat,
    LLMController,
    MultiAgentEpisode,
    compile_agent,
)
from mug.authoring import (
    Chat,
    Fallback,
    History,
    LLMAgent,
    Provider,
    Thoughts,
)
from mug.game.controllers import ScheduledSeat
from mug.game.multiseat import MultiStepResult
from mug.game.runtime import InputState
from mug.kernel import Digest
from mug.providers import ModelCall, ModelCompletion, ModelProvider, Usage
from mug.runtime import CommandContext
from mug.scheduling import FallbackRule, Scheduler
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


def _ids(tag: int) -> AgentIds:
    return AgentIds(
        agent_version_id="agentver_" + _UUID.format(0x500 + tag),
        agent_definition_id="agentdef_" + _UUID.format(0x510 + tag),
        agent_key=f"cook-{tag}",
        version_number=1,
        prompt_version_id="promptver_" + _UUID.format(0x520 + tag),
        fallback_policy_key="cook-fallback",
    )


class _KitchenEnv:
    """A tiny two-seat env: it steps both cooks' actions and ends after ``steps``.

    It duck-types the multi-seat loop (reset/step -> ``MultiStepResult``) and the
    controller's reads (legal actions, text view), so the loop steps it and each
    model reads the same live object. It records the action set it stepped.
    """

    ACTIONS: ClassVar[list[str]] = ["WAIT", "LEFT", "RIGHT"]

    def __init__(self, *, agents: tuple[str, ...], steps: int = 4) -> None:
        self._agents = agents
        self._t = 0
        self._max = steps
        self.stepped: list[dict[str, int]] = []

    def reset(self) -> MultiStepResult:
        self._t = 0
        self.stepped = []
        return self._result()

    def step(self, actions: Mapping[str, int]) -> MultiStepResult:
        self.stepped.append(dict(actions))
        self._t += 1
        return self._result()

    def _result(self) -> MultiStepResult:
        terminated = self._t >= self._max
        return MultiStepResult(
            observations={a: [float(self._t)] for a in self._agents},
            rewards={a: 1.0 if terminated else 0.0 for a in self._agents},
            terminated=terminated,
            truncated=False,
        )

    def legal_actions(self, agent_id: str) -> list[str]:
        return list(self.ACTIONS)

    def text_view(self, agent_id: str) -> str:
        return f"t={self._t}; you are {agent_id}"


class _Cook(LLMAgent):
    """An author's agent: it derives the partner from its own id, not a field.

    Like the turn-based example, the one class fills any seat: it reads the
    partner's moves as "the moves that are not mine," so the same instance drives
    both cooks and holds no per-seat state.
    """

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
        partner_moves = ", ".join(
            move
            for step in history.last(20)
            for who, move in step.actions.items()
            if who != agent_id and move
        )
        said = "; ".join(m.text for m in chat.last(3))
        return (
            f"partner moves: {partner_moves}\n"
            f"chat: {said}\n"
            f"{env.text_view(agent_id)}\n"  # type: ignore[attr-defined]
            f"actions: {', '.join(self.available_actions(env, agent_id))}"
        )


class _Adapter:
    """A fake adapter that always answers one action word and records each call."""

    def __init__(self, action_word: str) -> None:
        self._word = action_word
        self.seen: list[ModelCall] = []

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.seen.append(call)
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=1),
            output={"text": f"Action: {self._word}"},
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


def _controller(
    *,
    agent: LLMAgent,
    env: object,
    agent_id: str,
    adapter: _Adapter,
    store: InMemoryStore,
    factory: _Factory,
    tag: int,
) -> LLMController:
    gens = itertools.count(1 + tag * 100)
    provider = ModelProvider(
        store=store,
        adapter=adapter,  # type: ignore[arg-type]
        now=lambda: _START,
        new_generation_id=lambda: "generation_" + _UUID.format(next(gens)),
    )
    return LLMController(
        agent=agent,
        agent_version=compile_agent(agent, ids=_ids(tag)),
        provider=provider,
        env=env,
        agent_id=agent_id,
        new_context=factory,
        resolve_secret=lambda _: "sk-secret",
    )


def _episode(
    *,
    env: _KitchenEnv,
    seats: list[AgentSeat],
    humans: list[HumanSeat],
    store: InMemoryStore,
    factory: _Factory,
    max_steps: int = 20,
) -> MultiAgentEpisode:
    scheduler = Scheduler(
        store=store,
        now=lambda: _START,
        fallback=FallbackRule(on_timeout="repeat-last", on_stale="repeat-last"),
        default_action=0,
    )
    decisions = itertools.count(0xC01)
    return MultiAgentEpisode(
        env=env,
        seats=seats,
        humans=humans,
        scheduler=scheduler,
        channel_key="kitchen",
        episode_id="episode_" + _UUID.format(0x7),
        interaction_id="interaction_" + _UUID.format(0x6),
        episode_generation=1,
        new_context=factory,
        new_decision_id=lambda: "decision_" + _UUID.format(next(decisions)),
        now=lambda: _START,
        decision_timeout=1.0,
        max_steps=max_steps,
    )


def _agent_seat(
    *,
    agent: LLMAgent,
    env: _KitchenEnv,
    store: InMemoryStore,
    factory: _Factory,
    agent_id: str,
    seat_key: str,
    tag: int,
    adapter: _Adapter,
) -> AgentSeat:
    controller = _controller(
        agent=agent,
        env=env,
        agent_id=agent_id,
        adapter=adapter,
        store=store,
        factory=factory,
        tag=tag,
    )
    return AgentSeat(
        seat_key=seat_key,
        agent_id=agent_id,
        actor_id="actor_" + _UUID.format(0x400 + tag),
        agent=agent,
        controller=controller,
        seat=ScheduledSeat(default_action=0),
        text_view=lambda env, agent_id: env.text_view(agent_id),  # type: ignore[attr-defined]
    )


async def test_two_agents_share_one_environment() -> None:
    """Two LLM seats step one env together; each reads the other's moves."""
    env = _KitchenEnv(agents=("chef-1", "chef-2"), steps=4)
    store, factory = InMemoryStore(), _Factory()

    left, right = _Adapter("LEFT"), _Adapter("RIGHT")
    cook = _Cook()  # one instance drives both seats
    seats = [
        _agent_seat(
            agent=cook,
            env=env,
            store=store,
            factory=factory,
            agent_id="chef-1",
            seat_key="seat-1",
            tag=1,
            adapter=left,
        ),
        _agent_seat(
            agent=cook,
            env=env,
            store=store,
            factory=factory,
            agent_id="chef-2",
            seat_key="seat-2",
            tag=2,
            adapter=right,
        ),
    ]
    runner = _episode(env=env, seats=seats, humans=[], store=store, factory=factory)

    result = await runner.run()

    left_i = _KitchenEnv.ACTIONS.index("LEFT")
    right_i = _KitchenEnv.ACTIONS.index("RIGHT")
    # Frame 1 steps both defaults (0); then each seat holds its own decided action.
    assert env.stepped == [
        {"chef-1": 0, "chef-2": 0},
        {"chef-1": left_i, "chef-2": right_i},
        {"chef-1": left_i, "chef-2": right_i},
        {"chef-1": left_i, "chef-2": right_i},
    ]
    # The shared timeline is one episode; each seat kept its own decisions.
    assert result.summary.frames == 4
    assert result.summary.solved is True
    assert len(result.seats["chef-1"].decisions) == 4
    assert len(result.seats["chef-2"].decisions) == 4
    # chef-1's prompt read chef-2's RIGHT move from its own history, and the one
    # shared instance still played LEFT here and RIGHT on the other seat.
    assert any("partner moves:" in p for p in left.prompts())
    assert any("RIGHT" in p for p in left.prompts()[1:])


async def test_a_human_seat_plays_beside_an_llm() -> None:
    """A human seat drives one env agent while an LLM drives the other."""
    env = _KitchenEnv(agents=("chef-1", "chef-2"), steps=3)
    store, factory = InMemoryStore(), _Factory()

    cook = _Cook()
    seats = [
        _agent_seat(
            agent=cook,
            env=env,
            store=store,
            factory=factory,
            agent_id="chef-2",
            seat_key="bot",
            tag=3,
            adapter=_Adapter("LEFT"),
        )
    ]
    # A human seat: its input maps a held key to an action, sampled each frame.
    human_input = InputState(bindings={"ArrowRight": 2}, default_action=0)
    human_input.press(["ArrowRight"])
    humans = [HumanSeat(seat_key="human", agent_id="chef-1", source=human_input)]
    runner = _episode(env=env, seats=seats, humans=humans, store=store, factory=factory)

    result = await runner.run()

    left_i = _KitchenEnv.ACTIONS.index("LEFT")
    # The human's held ArrowRight (2) reaches the env every frame beside the bot.
    assert [s["chef-1"] for s in env.stepped] == [2, 2, 2]
    # The bot defaults on frame 1, then holds its decided LEFT.
    assert [s["chef-2"] for s in env.stepped] == [0, left_i, left_i]
    assert result.summary.frames == 3
    assert len(result.seats["chef-2"].decisions) == 3


async def test_a_posted_message_reaches_every_agent_seat() -> None:
    """One human instruction is read by both agent seats' next prompt."""
    env = _KitchenEnv(agents=("chef-1", "chef-2"), steps=2)
    store, factory = InMemoryStore(), _Factory()

    a, b = _Adapter("LEFT"), _Adapter("RIGHT")
    cook = _Cook()  # one instance drives both seats
    seats = [
        _agent_seat(
            agent=cook,
            env=env,
            store=store,
            factory=factory,
            agent_id="chef-1",
            seat_key="seat-1",
            tag=1,
            adapter=a,
        ),
        _agent_seat(
            agent=cook,
            env=env,
            store=store,
            factory=factory,
            agent_id="chef-2",
            seat_key="seat-2",
            tag=2,
            adapter=b,
        ),
    ]
    runner = _episode(env=env, seats=seats, humans=[], store=store, factory=factory)
    runner.post_message(sender="human", text="cover the left side")

    await runner.run()

    assert any("cover the left side" in p for p in a.prompts())
    assert any("cover the left side" in p for p in b.prompts())
