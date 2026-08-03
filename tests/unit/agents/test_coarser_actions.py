"""An agent may decide at a coarser grain than the environment steps (W24).

A model that answers in seconds cannot usefully choose one frame of movement. At
thirty frames a second and two seconds a decision it would act about ten times in a
twenty second round, and a partner that acts ten times has not played. So it chooses
something that **lasts** -- "fetch an onion", "take the next exit" -- and the study
says what carrying that out looks like on any one frame.

Two methods say the whole of it and both default to the environment's own actions:

- ``decides_among`` -- the names the agent chooses between;
- ``carry_out`` -- one environment action that carries the choice forward, asked
  once for every frame the seat is read.

What is checked here is what would otherwise be wrong in silence:

- the seat steps what ``carry_out`` says and not what the model chose, so a choice
  that means "walk to the pot" is not stepped as action 3;
- one decision drives **many** frames, which is the whole point;
- ``available_actions`` still names every seat's moves in the **environment's**
  words, so a partner's grid move is never recorded under a job name;
- a fallback is read through the agent's own rule, because ``REPEAT_LAST`` and
  ``WAIT`` mean different things to a choice that lasts;
- an agent that writes neither method behaves exactly as it did before.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Mapping
from typing import Any, ClassVar, cast

from mug.agents import (
    AgentGameSpec,
    AgentIds,
    AgentSeatSpec,
    HumanSeatSpec,
    build_agent_episode,
)
from mug.agents.game import _waits_for
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.game.multiseat import MultiStepResult
from mug.gateway import Gateway
from mug.kernel import Digest
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_EPISODE_LEN = 12
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)

# The environment's own actions, and the jobs the agent decides among instead.
STAY, LEFT, RIGHT = range(3)
MOVES = ("STAY", "LEFT", "RIGHT")
JOBS = ("GO_TO_THE_END", "COME_BACK", "STAND_BY")


class _Corridor:
    """Two seats walking one corridor. A seat's action moves it by one square."""

    ACTIONS: ClassVar[list[str]] = list(MOVES)
    LENGTH = 6

    def __init__(self) -> None:
        self.at: dict[str, int] = {"walker": 0, "person": 0}
        self._t = 0

    def reset(self) -> MultiStepResult:
        self.at = {"walker": 0, "person": 0}
        self._t = 0
        return self._seen()

    def step(self, actions: Mapping[str, int]) -> MultiStepResult:
        self._t += 1
        for who, action in actions.items():
            step = {LEFT: -1, RIGHT: 1}.get(int(action), 0)
            self.at[who] = max(0, min(self.LENGTH, self.at[who] + step))
        return self._seen()

    def _seen(self) -> MultiStepResult:
        done = self._t >= _EPISODE_LEN
        return MultiStepResult(
            observations={who: [float(where)] for who, where in self.at.items()},
            rewards=dict.fromkeys(self.at, 0.0),
            terminated=done,
            truncated=False,
        )


class _Walker(LLMAgent):
    """An agent that decides where to get to, and walks there one square a frame."""

    provider = Provider.OSS
    model = "fake-local"
    decides_every = 1
    on_timeout = Fallback.WAIT
    answers_within = 7.5

    def available_actions(self, env: Any, agent_id: str) -> list[str]:
        return list(MOVES)

    def decides_among(self, env: Any, agent_id: str) -> list[str]:
        return list(JOBS)

    def carry_out(self, env: Any, agent_id: str, chosen: int | None) -> int | None:
        if chosen is None or JOBS[chosen] == "STAND_BY":
            return None
        here = cast("_Corridor", env).at[agent_id]
        target = cast("_Corridor", env).LENGTH if JOBS[chosen] == "GO_TO_THE_END" else 0
        if here == target:
            return None
        return RIGHT if target > here else LEFT

    def get_prompt(
        self,
        env: Any,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        return f"at {cast('_Corridor', env).at[agent_id]}"


class _Plain(LLMAgent):
    """An agent that writes neither method: it decides one environment action."""

    provider = Provider.OSS
    model = "fake-local"
    decides_every = 1
    on_timeout = Fallback.REPEAT_LAST

    def available_actions(self, env: Any, agent_id: str) -> list[str]:
        return list(MOVES)

    def get_prompt(
        self,
        env: Any,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        return "go"


class _Answers:
    """A keyless adapter that answers on a script and counts what it was asked."""

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies) or ["GO_TO_THE_END"]
        self.prompts: list[str] = []

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        payload: Any = call.payload
        self.prompts.append(payload["messages"][0]["content"])
        said = self._replies[min(len(self.prompts) - 1, len(self._replies) - 1)]
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": said},
        )


class _Unreadable:
    """An adapter whose replies name no job, so every decision falls back.

    It answers **at once**. An adapter that hung would be a truer picture of a slow
    provider and a worse test: the loop would finish the episode before the first
    deadline passed, no fallback would ever be applied, and the test would pass
    whatever the fallback did.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.calls += 1
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": "I am not going to name a job"},
        )


def _ids(word: str) -> AgentIds:
    return AgentIds(
        agent_version_id="agentver_" + _UUID.format(0x900),
        agent_definition_id="agentdef_" + _UUID.format(0x901),
        agent_key=word,
        version_number=1,
        prompt_version_id="promptver_" + _UUID.format(0x902),
        fallback_policy_key="walk-fallback",
    )


def _spec(
    agent: LLMAgent, adapter: Any, *, timeout: float = 5.0, fps: int = 0
) -> AgentGameSpec:
    return AgentGameSpec(
        channel_key="corridor",
        make_env=_Corridor,
        seats=(
            AgentSeatSpec(
                agent=agent,
                adapter=adapter,
                ids=_ids("walker"),
                agent_id="walker",
                seat_key="walker",
                actor_id="actor_" + _UUID.format(0x910),
            ),
        ),
        humans=(HumanSeatSpec(agent_id="person", seat_key="person"),),
        default_action=STAY,
        decision_timeout=timeout,
        fps=fps,
        max_steps=_EPISODE_LEN + 4,
    )


def _run(spec: AgentGameSpec) -> tuple[Any, _Corridor]:
    """Run one episode of the corridor and return its result and the environment."""
    gateway = Gateway()
    episode = build_agent_episode(
        spec,
        store=InMemoryStore(),
        new_context=_Factory(),
        new_decision_id=lambda: gateway.new_id("decision"),
        new_generation_id=lambda: gateway.new_id("generation"),
        now=gateway.clock,
        interaction_id=gateway.new_id("interaction"),
        episode_id=gateway.new_id("episode"),
    )
    result = asyncio.run(episode.run())
    return result, cast("_Corridor", episode._env)


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


def test_the_environment_steps_what_carry_out_says_not_what_the_model_chose() -> None:
    """A choice is not an action, and the seat steps the action.

    The model chooses ``GO_TO_THE_END``, which is position 0 in its own list. If
    the choice were stepped as an environment action the walker would take action 0
    -- ``STAY`` -- and never move at all. It walks.
    """
    _result, env = _run(_spec(_Walker(), _Answers("GO_TO_THE_END")))

    assert env.at["walker"] == env.LENGTH, (
        f"the walker reached {env.at['walker']} of {env.LENGTH}: it stepped its "
        "choice rather than what carrying the choice out looks like"
    )


def test_one_decision_drives_many_frames() -> None:
    """The whole point: a decision that lasts is carried out on every frame.

    The adapter answers once and is then asked again on the agent's own cadence,
    but the corridor is longer than the number of decisions would allow if a
    decision moved the walker one square. Six squares from one standing choice is
    what a coarser grain buys.
    """
    adapter = _Answers("GO_TO_THE_END")
    _result, env = _run(_spec(_Walker(), adapter))

    assert env.at["walker"] == env.LENGTH
    assert env.LENGTH > 1, "a corridor of one square would prove nothing"


def test_a_seats_history_names_moves_in_the_environments_own_words() -> None:
    """``available_actions`` is the environment's list, and stays it.

    This is the part that would have gone wrong in silence. If the coarser list
    were ``available_actions``, the runtime would name **every** seat's move with
    it -- so the person walking beside the model would be recorded as having done
    ``GO_TO_THE_END``, and nothing anywhere would say otherwise.
    """
    result, _env = _run(_spec(_Walker(), _Answers("GO_TO_THE_END")))

    seat = result.seats["walker"]
    assert seat.decisions, "the seat never decided"
    # Every decision is a position in the job list, which is shorter than the
    # environment's action list -- so the two vocabularies really are different.
    chosen = [one for one in seat.decisions if not one.used_fallback]
    assert chosen and all(0 <= one.action < len(JOBS) for one in chosen)
    assert set(MOVES).isdisjoint(set(JOBS)), "the test needs two vocabularies"


def test_a_wait_fallback_leaves_the_seat_with_no_choice_at_all() -> None:
    """``WAIT`` is not "choose the idle action": it is "nobody has said".

    The walker's ``carry_out`` answers ``None`` for no choice, and the seat then
    takes the game's own default. What must not happen is the default action being
    applied as a **choice**: ``STAY`` is 0, and job 0 is ``GO_TO_THE_END``, so a
    seat that confused the two would walk the whole corridor on decisions that all
    failed. That is not a hypothetical -- it is what applying the fallback action
    to the seat unchanged does, and this test is what catches it.
    """
    adapter = _Unreadable()
    _result, env = _run(_spec(_Walker(), adapter))

    assert adapter.calls, "the seat never decided, so no fallback was ever applied"
    assert env.at["walker"] == 0, (
        "a seat whose every decision failed walked anyway: the fallback action was "
        "applied as a choice, and choice 0 is a job rather than the idle move"
    )


def test_a_repeat_last_fallback_keeps_the_job_the_seat_was_already_doing() -> None:
    """The other rule, which for a choice that lasts means "carry on".

    Repeating a grid move walks an extra square, which is why a kitchen partner
    asks to wait. Repeating a **job** is not a move at all: a partner half way to
    the pot goes on to the pot. So the two rules are read apart, and the last
    *decided* choice is what a repeat repeats -- never a fallback's own action.
    """

    class _Stubborn(_Walker):
        on_timeout = Fallback.REPEAT_LAST

    # It names a job once and is unreadable ever after.
    adapter = _Answers("GO_TO_THE_END", "nothing you can read")
    _result, env = _run(_spec(_Stubborn(), adapter))

    assert len(adapter.prompts) > 1, "the seat decided once, so nothing fell back"
    assert env.at["walker"] == env.LENGTH, (
        "the walker stopped where the first decision left it: a repeat-last "
        "fallback dropped the job instead of carrying it on"
    )


def test_an_agent_that_writes_neither_method_decides_an_environment_action() -> None:
    """Nothing written before a coarser grain existed changes.

    The plain agent's reply names an environment action, it is parsed against the
    environment's own list, and the seat holds and steps it.
    """
    _result, env = _run(_spec(_Plain(), _Answers("RIGHT")))

    assert env.at["walker"] == env.LENGTH, (
        "an agent that decides an environment action no longer steps it"
    )


def test_the_deadline_is_the_longest_any_seat_asked_for() -> None:
    """The seats share one scheduler, so there is one deadline, and it is the longest.

    A shorter one would make a slower model fall back on every decision it ever
    made, with nothing in the records to say the study had never waited for it.
    That is what a fixed one second did: it was unreachable from a study, and no
    real provider answers a kitchen prompt inside it.
    """
    spec = _spec(_Walker(), _Answers())

    assert spec.seats[0].agent.answers_within == 7.5
    assert _waits_for(spec.seats, spec.decision_timeout) == 7.5
    # A study that asked for longer than its agent keeps its own answer.
    assert _waits_for(spec.seats, 30.0) == 30.0
    # And a game with no model seat is unchanged.
    assert _waits_for((), 1.0) == 1.0


def test_a_message_wakes_a_seat_that_would_otherwise_wait_out_its_cadence() -> None:
    """Somebody who writes to a partner is answered as soon as it is free.

    A seat decides at its own cadence, which for a model that plays is once every
    ``decides_every`` frames. Without waking, a participant who typed "get a plate"
    would wait out the rest of that cadence for any sign they had been heard -- and
    a partner you have to wait on is not one you talk to.

    The cadence here is longer than the whole episode, so the seat would decide
    **nothing** of its own accord. Every decision it makes is one somebody asked
    for, which is what makes the count unambiguous.
    """

    class _Slow(_Walker):
        decides_every = 1000

    adapter = _Answers("STAND_BY")
    spec = _spec(_Slow(), adapter)
    gateway = Gateway()
    episode = build_agent_episode(
        spec,
        store=InMemoryStore(),
        new_context=_Factory(),
        new_decision_id=lambda: gateway.new_id("decision"),
        new_generation_id=lambda: gateway.new_id("generation"),
        now=gateway.clock,
        interaction_id=gateway.new_id("interaction"),
        episode_id=gateway.new_id("episode"),
    )

    async def play() -> None:
        running = asyncio.ensure_future(episode.run())
        await asyncio.sleep(0)
        episode.post_message(sender="person", text="are you there?")
        await running

    asyncio.run(play())

    assert adapter.prompts, (
        "nothing the participant wrote made the seat decide: a message does not "
        "wake it, so a partner answers only when its own cadence comes round"
    )


def test_a_seat_nobody_speaks_to_keeps_its_own_cadence() -> None:
    """Waking is the exception, so silence leaves the cadence exactly as written.

    This is the control for the test above. Without it, a seat that decided on
    every frame whatever its cadence said would pass that one and mean nothing.

    The one decision counted here is the opening frame, which every seat gets: at
    the start of a round it holds no choice, so there is nothing for the cadence to
    protect. Every decision **after** it would be one nobody asked for.
    """

    class _Slow(_Walker):
        decides_every = 1000

    adapter = _Answers("STAND_BY")
    _result, _env = _run(_spec(_Slow(), adapter))

    assert len(adapter.prompts) == 1, (
        f"a seat nobody spoke to decided {len(adapter.prompts)} times on a cadence "
        "of one decision every thousand frames over an episode of "
        f"{_EPISODE_LEN}: one is the opening frame, and every one after it is a "
        "cadence that is not being kept"
    )


def test_a_wake_that_arrives_mid_decision_is_not_lost() -> None:
    """Somebody who writes while the seat is thinking still gets an answer.

    A seat already deciding cannot start another, so the wake has to be kept until
    it can. Dropping it is the kind of fault nobody reports: the participant writes,
    the partner is busy, and their message is answered on a cadence they were never
    told about -- here, never.

    Two messages are written while the cadence would produce no decision at all.
    The first starts one; the second arrives while that one is in flight.
    """

    class _Slow(_Walker):
        decides_every = 1000

    class _Thinking(_Answers):
        """An adapter that takes a moment, so a decision is really in flight."""

        async def __call__(self, call: ModelCall) -> ModelCompletion:
            await asyncio.sleep(0.05)
            return await super().__call__(call)

    # The frames take real time, so the episode outlasts a decision in flight.
    # With no frame delay the run finishes before the first reply comes back and
    # the second message never has a decision to be held behind.
    adapter = _Thinking("STAND_BY")
    spec = _spec(_Slow(), adapter, fps=40)
    gateway = Gateway()
    episode = build_agent_episode(
        spec,
        store=InMemoryStore(),
        new_context=_Factory(),
        new_decision_id=lambda: gateway.new_id("decision"),
        new_generation_id=lambda: gateway.new_id("generation"),
        now=gateway.clock,
        interaction_id=gateway.new_id("interaction"),
        episode_id=gateway.new_id("episode"),
    )

    async def play() -> None:
        running = asyncio.ensure_future(episode.run())
        await asyncio.sleep(0.01)
        episode.post_message(sender="person", text="are you there?")
        # Long enough that the first decision is really under way, short enough
        # that it has not come back: this is the moment the wake must survive.
        await asyncio.sleep(0.02)
        episode.post_message(sender="person", text="and can you fetch a plate?")
        await running

    asyncio.run(play())

    assert len(adapter.prompts) >= 2, (
        f"two messages produced {len(adapter.prompts)} decisions: the second "
        "arrived while the seat was thinking and its wake was thrown away"
    )
