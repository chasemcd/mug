"""The turn-based runner drives many seats that take turns over one AEC game.

These tests drive ``mug.agents.TurnBasedAgentEpisode`` against the in-memory store
with a fixed clock and scripted fake adapters. They prove the runner takes turns:
one seat acts each turn, the runner waits for the active seat (so its first move is
already its decided move, not a default), each seat records every turn into its own
history -- so a seat reads the move the other just played -- and a human seat takes
turns beside an LLM. The fake AEC environment duck-types the PettingZoo AEC API and
also answers the controller reads (legal actions, text view), so PettingZoo is not
a dependency.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import ClassVar

from mug.agents import (
    AgentIds,
    AgentSeat,
    LLMController,
    LocalSeat,
    TurnBasedAgentEpisode,
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
from mug.game.aec import AecEnv
from mug.game.controllers import ScheduledSeat
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
        agent_key=f"duel-{tag}",
        version_number=1,
        prompt_version_id="promptver_" + _UUID.format(0x520 + tag),
        fallback_policy_key="duel-fallback",
    )


class _DuelAec:
    """A two-seat turn-based AEC game: ``a`` and ``b`` alternate for ``turns`` moves.

    It duck-types the AEC API the ``AecEnv`` adapter reads and also answers the
    controller reads (legal actions, text view), so the loop steps it and each model
    reads the same live object. It records the real moves in order.
    """

    ACTIONS: ClassVar[list[str]] = ["WAIT", "LEFT", "RIGHT"]

    def __init__(self, *, turns: int) -> None:
        self._turns = turns
        self._order = ("a", "b")
        self.agents: list[str] = []
        self.agent_selection = "a"
        self.rewards: dict[str, float] = {}
        self.terminations: dict[str, bool] = {}
        self.truncations: dict[str, bool] = {}
        self.moves: list[tuple[str, int]] = []

    def reset(self, *, seed: int | None = None) -> None:
        self.agents = list(self._order)
        self.agent_selection = "a"
        self.rewards = {a: 0.0 for a in self._order}
        self.terminations = {a: False for a in self._order}
        self.truncations = {a: False for a in self._order}
        self.moves = []

    def observe(self, agent: str) -> list[float]:
        return [float(len(self.moves))]

    def step(self, action: int | None) -> None:
        agent = self.agent_selection
        if self.terminations[agent] or self.truncations[agent]:
            self._clear_dead()
            return
        self.moves.append((agent, int(action or 0)))
        self.rewards = {a: 0.0 for a in self._order}
        self.rewards[agent] = 1.0
        if len(self.moves) >= self._turns:
            self.terminations = {a: True for a in self.agents}
        index = self._order.index(agent)
        self.agent_selection = self._order[(index + 1) % len(self._order)]

    def _clear_dead(self) -> None:
        self.rewards = {a: 0.0 for a in self._order}
        dead = self.agent_selection
        self.agents = [a for a in self.agents if a != dead]
        live = [a for a in self._order if a in self.agents]
        if live:
            self.agent_selection = live[0]

    def legal_actions(self, agent_id: str) -> list[str]:
        return list(self.ACTIONS)

    def text_view(self, agent_id: str) -> str:
        return f"move {len(self.moves)}; you are {agent_id}"


class _Duelist(LLMAgent):
    """An author's agent: it derives the opponent from its own id, not a field.

    It reads the opponent's moves as "the moves that are not mine," so the one class
    plays either seat with nothing passed to it -- the pattern the turn-based example
    doc shows.
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
        moves = ", ".join(
            move
            for step in history.last(9)
            for who, move in step.actions.items()
            if who != agent_id
        )
        said = "; ".join(m.text for m in chat.last(3))
        return (
            f"opponent moves: {moves}\n"
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


def _agent_seat(
    *,
    agent: LLMAgent,
    env: _DuelAec,
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


def _episode(
    *,
    env: _DuelAec,
    seats: list[AgentSeat],
    local_seats: list[LocalSeat],
    store: InMemoryStore,
    factory: _Factory,
    max_steps: int = 20,
) -> TurnBasedAgentEpisode:
    scheduler = Scheduler(
        store=store,
        now=lambda: _START,
        fallback=FallbackRule(on_timeout="repeat-last", on_stale="repeat-last"),
        default_action=0,
    )
    decisions = itertools.count(0xC01)
    return TurnBasedAgentEpisode(
        env=env,
        step_env=AecEnv(env),
        seats=seats,
        local_seats=local_seats,
        scheduler=scheduler,
        channel_key="duel",
        episode_id="episode_" + _UUID.format(0x7),
        interaction_id="interaction_" + _UUID.format(0x6),
        episode_generation=1,
        new_context=factory,
        new_decision_id=lambda: "decision_" + _UUID.format(next(decisions)),
        now=lambda: _START,
        decision_timeout=1.0,
        max_steps=max_steps,
    )


async def test_one_agent_instance_drives_both_seats() -> None:
    """One `_Duelist()` fills both seats; each seat keeps its own runtime.

    The agent holds no per-seat state, so the same instance plays both marks. Its
    per-seat state -- history, chat, thoughts, and even which model answers it --
    lives on each seat's own controller, so seat ``a`` plays LEFT and seat ``b``
    plays RIGHT from the one shared definition, and each reads only its own history.
    """
    env = _DuelAec(turns=4)
    store, factory = InMemoryStore(), _Factory()

    left, right = _Adapter("LEFT"), _Adapter("RIGHT")
    duelist = _Duelist()  # one instance, both seats
    seats = [
        _agent_seat(
            agent=duelist,
            env=env,
            store=store,
            factory=factory,
            agent_id="a",
            seat_key="seat-a",
            tag=1,
            adapter=left,
        ),
        _agent_seat(
            agent=duelist,
            env=env,
            store=store,
            factory=factory,
            agent_id="b",
            seat_key="seat-b",
            tag=2,
            adapter=right,
        ),
    ]
    runner = _episode(
        env=env, seats=seats, local_seats=[], store=store, factory=factory
    )

    result = await runner.run()

    left_i = _DuelAec.ACTIONS.index("LEFT")
    right_i = _DuelAec.ACTIONS.index("RIGHT")
    # The runner waits for the active seat, so even the first move is decided, and
    # the seats alternated a, b, a, b.
    assert env.moves == [
        ("a", left_i),
        ("b", right_i),
        ("a", left_i),
        ("b", right_i),
    ]
    assert result.summary.frames == 4
    assert result.summary.solved is True
    assert len(result.seats["a"].decisions) == 2
    assert len(result.seats["b"].decisions) == 2
    # a derived its opponent from its own id and read b's RIGHT move from history.
    assert any("opponent moves: RIGHT" in p for p in left.prompts())


async def test_a_human_takes_turns_beside_an_llm() -> None:
    """A human seat and an LLM seat alternate over one turn-based game."""
    env = _DuelAec(turns=4)
    store, factory = InMemoryStore(), _Factory()

    bot = _Duelist()
    seats = [
        _agent_seat(
            agent=bot,
            env=env,
            store=store,
            factory=factory,
            agent_id="b",
            seat_key="bot",
            tag=3,
            adapter=_Adapter("LEFT"),
        )
    ]
    human_input = InputState(bindings={"ArrowRight": 2}, default_action=0)
    human_input.press(["ArrowRight"])
    local_seats = [LocalSeat(seat_key="human", agent_id="a", source=human_input)]
    runner = _episode(
        env=env, seats=seats, local_seats=local_seats, store=store, factory=factory
    )

    result = await runner.run()

    left_i = _DuelAec.ACTIONS.index("LEFT")
    # The human's held ArrowRight (2) plays on a's turns; the bot's LEFT on b's.
    assert env.moves == [("a", 2), ("b", left_i), ("a", 2), ("b", left_i)]
    assert result.summary.frames == 4
    assert len(result.seats["b"].decisions) == 2


async def test_a_posted_message_reaches_every_agent_seat() -> None:
    """One instruction is read by both agent seats' next turn."""
    env = _DuelAec(turns=2)
    store, factory = InMemoryStore(), _Factory()

    a, b = _Adapter("LEFT"), _Adapter("RIGHT")
    duel_a, duel_b = _Duelist(), _Duelist()
    seats = [
        _agent_seat(
            agent=duel_a,
            env=env,
            store=store,
            factory=factory,
            agent_id="a",
            seat_key="seat-a",
            tag=1,
            adapter=a,
        ),
        _agent_seat(
            agent=duel_b,
            env=env,
            store=store,
            factory=factory,
            agent_id="b",
            seat_key="seat-b",
            tag=2,
            adapter=b,
        ),
    ]
    runner = _episode(
        env=env, seats=seats, local_seats=[], store=store, factory=factory
    )
    runner.post_message(sender="human", text="take the center")

    await runner.run()

    assert any("take the center" in p for p in a.prompts())
    assert any("take the center" in p for p in b.prompts())
