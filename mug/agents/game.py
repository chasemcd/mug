"""Build a runnable multi-seat episode from a study's game specification.

This is the study-facing seam that a study author fills to run a multi-seat game
over the realtime transport, the analog of ``mug.game.spec.GameSpec`` for a
one-person game. A study supplies an ``AgentGameSpec``: the multi-agent
environment factory and who sits in it -- an ``AgentSeatSpec`` per model seat (its
agent definition, its provider adapter, and its pinned identity), a
``HumanSeatSpec`` per person, and a ``BotSeatSpec`` per seat the study's own policy
plays. ``build_agent_episode`` composes the built stack behind it -- one
``ModelProvider`` and ``LLMController`` per model seat, one shared ``Scheduler``,
and the held-action ``ScheduledSeat`` the loop reads -- into a
``MultiAgentEpisode`` ready to run.

**Who plays is a list, not a shape.** There is one specification for every mix,
so a study says who is in the environment rather than picking the specification
that happens to allow it: two people and a model partner, one person and two
bots, or four models alone are all seat lists over this one builder.

The composition lives here, in the agent layer above providers and scheduling,
because it wires those two siblings together (the same reason the controller does).
The transport glue one layer up (``mug.participant``) supplies the impure seams --
the store, the clock, and the id minters -- and owns the socket; this builder holds
no clock and no entropy of its own.

The shared scheduler applies one fallback rule to every seat, so it uses the first
seat's declared timeout fallback; a per-seat scheduler stays deferred, the same
limitation the episode runtime already carries.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from mug.agents.multiseat_episode import (
    AgentSeat,
    LocalSeat,
    MultiAgentEpisode,
    TextView,
)
from mug.agents.runtime import AgentIds, LLMController, compile_agent
from mug.agents.turnbased_episode import TurnBasedAgentEpisode
from mug.authoring import Fallback, LLMAgent, Thoughts, Transcript
from mug.diagnostics import Diagnostics
from mug.game.aec import AecEnv, TurnBasedEnv, TurnBasedObserver
from mug.game.controllers import ScheduledSeat
from mug.game.keys import Bindings
from mug.game.multiseat import MultiSeatEnv, MultiSeatObserver
from mug.game.seams import SeatActionSource
from mug.game.spec import HudFn, RenderFn
from mug.providers import ModelProvider
from mug.providers.runtime import NewContext, ProviderAdapter, SecretResolver
from mug.scheduling import FallbackRule, Scheduler
from mug.storage import Store


@dataclass(frozen=True)
class AgentSeatSpec:
    """One model seat a study places in an agent game: who plays and how.

    ``agent`` is the author's ``LLMAgent`` definition; ``adapter`` is the provider
    adapter that runs its calls; ``ids`` pins the published build. ``agent_id`` is
    the environment agent the seat plays (the key the loop steps), and ``seat_key`` /
    ``actor_id`` are the recorded seat and actor identity. ``resolve_secret`` resolves
    the agent's credential at call time (unset for a keyless local runner), and
    ``text_view`` renders the game for this seat's prompt.
    """

    agent: LLMAgent
    adapter: ProviderAdapter
    ids: AgentIds
    agent_id: str
    seat_key: str
    actor_id: str
    resolve_secret: SecretResolver | None = None
    text_view: TextView | None = None


@dataclass(frozen=True)
class HumanSeatSpec:
    """One human seat a participant plays beside the models in an agent game."""

    agent_id: str
    seat_key: str


@dataclass(frozen=True)
class BotSeatSpec:
    """One seat a study's own policy plays, beside the people and the models.

    ``controller`` decides the seat's action each frame -- a heuristic or an ONNX
    policy, the same ``SeatActionSource`` seam a person's held keys satisfy.
    ``actor_id`` is the seat's recorded identity; with none the room casts one.

    A bot is not a model seat: it makes no model call, keeps no thoughts, and
    reaches no provider. So it is its own kind of seat rather than a model with the
    provider left out.
    """

    agent_id: str
    seat_key: str
    controller: SeatActionSource
    actor_id: str | None = None


class SeatMemory:
    """What a model seat carries from one round of an activity into the next.

    An activity of several rounds runs one episode per round: a fresh environment,
    a fresh trajectory, and -- until this held it -- a fresh controller, which meant
    a partner walked into round two having forgotten every word of round one. The
    conversation had not forgotten, because the room is the activity's and outlives
    the round. A partner that can be reminded of what it agreed to and has no memory
    of agreeing is worse than one that never agreed.

    So two things are carried and one is not:

    - **thoughts** carry, because a plan is about the task and not about the round.
    - **the transcript** carries, because it is one conversation. It is the same
      conversation the participant can see the whole of on their own screen.
    - **the history** does not, because it is the episode's own transitions. Each
      round is its own episode with its own trajectory and its own frame numbers,
      and joining two of them would make one list whose ticks run 1..600, 1..600.
      What carried between rounds is then exactly what was said and what was
      planned, which is also the cleaner thing to write a paper about.

    It is held per activity by whatever owns the rounds, and it is keyed by the
    environment agent a seat plays, so a seat gets its own memory back and never
    another seat's.
    """

    def __init__(self) -> None:
        self._thoughts: dict[str, Thoughts] = {}
        self._chat: dict[str, Transcript] = {}

    def knows(self, agent_id: str) -> bool:
        """Return whether this seat has played a round of the activity already."""
        return agent_id in self._chat

    def thoughts_of(self, agent_id: str) -> Thoughts:
        """Return one seat's carried reasoning, empty before its first round."""
        return self._thoughts.setdefault(agent_id, Thoughts())

    def chat_of(self, agent_id: str) -> Transcript:
        """Return one seat's carried transcript, empty before its first round."""
        return self._chat.setdefault(agent_id, Transcript())


def _no_bindings() -> dict[str, int]:
    """Return an empty, typed key-to-action binding map for a spec default."""
    return {}


def _no_model_seats() -> tuple[AgentSeatSpec, ...]:
    """Return an empty, typed model-seat tuple for a spec default."""
    return ()


def _no_human_seats() -> tuple[HumanSeatSpec, ...]:
    """Return an empty, typed human-seat tuple for a spec default."""
    return ()


def _no_bot_seats() -> tuple[BotSeatSpec, ...]:
    """Return an empty, typed bot-seat tuple for a spec default."""
    return ()


@dataclass(frozen=True)
class AgentGameSpec:
    """One multi-seat game a study supplies: its environment, its seats, its cadence.

    ``make_env`` builds the multi-agent environment the loop steps and every seat's
    controller reads (one live object). The seats are three lists of what plays,
    and a study writes whichever it needs: ``seats`` are the model seats,
    ``humans`` the seats people play, and ``bots`` the seats a local policy plays.
    Any mix is one interaction over one environment -- two people and a model
    partner is the case the north star asks for.

    ``human`` is the older one-person spelling and still works; a study that names
    it names one human seat. Naming both is refused, because two statements of who
    sits where is one too many.

    ``render`` draws one frame for whoever is watching; the transport gives each
    watching connection its own surface and pushes what changed. A game with none
    draws nothing, which is right for seats that are all models.

    ``action_bindings`` and ``default_action`` map a human seat's keys;
    ``decision_timeout`` bounds each model decision, and ``fps`` / ``max_steps``
    shape the loop.
    """

    channel_key: str
    make_env: Callable[[], MultiSeatEnv]
    render: RenderFn | None = None
    hud: HudFn | None = None
    input_mode: str = "pressed_keys"
    seats: tuple[AgentSeatSpec, ...] = field(default_factory=_no_model_seats)
    human: HumanSeatSpec | None = None
    humans: tuple[HumanSeatSpec, ...] = field(default_factory=_no_human_seats)
    bots: tuple[BotSeatSpec, ...] = field(default_factory=_no_bot_seats)
    action_bindings: Bindings = field(default_factory=_no_bindings)
    default_action: int = 0
    decision_timeout: float = 1.0
    fps: int = 0
    max_steps: int = 50

    def __post_init__(self) -> None:
        if self.human is not None and self.humans:
            raise ValueError("name the human seats once: 'human' or 'humans'")
        if not self.seats and not self.human_seats and not self.bots:
            raise ValueError("a multi-seat game needs at least one seat")

    @property
    def human_seats(self) -> tuple[HumanSeatSpec, ...]:
        """Return every seat a person plays, however the study spelled it."""
        if self.human is not None:
            return (self.human,)
        return self.humans


@dataclass(frozen=True)
class TurnBasedGameSpec:
    """One turn-based (AEC) agent game a study supplies: seats act one at a time.

    ``make_env`` builds the live turn-based environment the seats read; ``step_env``
    wraps it in the ``TurnBasedEnv`` seam the loop steps (the default adapts a
    PettingZoo AEC environment through ``AecEnv``). The rest mirrors the simultaneous
    ``AgentGameSpec``.
    """

    channel_key: str
    make_env: Callable[[], Any]
    seats: tuple[AgentSeatSpec, ...]
    step_env: Callable[[Any], TurnBasedEnv] = AecEnv
    human: HumanSeatSpec | None = None
    action_bindings: Bindings = field(default_factory=_no_bindings)
    default_action: int = 0
    decision_timeout: float = 1.0
    fps: int = 0
    max_steps: int = 50


def _compose_seats(
    seat_specs: tuple[AgentSeatSpec, ...],
    env: Any,
    *,
    store: Store,
    new_context: NewContext,
    new_generation_id: Callable[[], str],
    now: Callable[[], datetime],
    default_action: int,
    memory: SeatMemory | None = None,
    diagnostics: Diagnostics | None = None,
) -> tuple[Scheduler, list[AgentSeat]]:
    """Compose one scheduler and one model seat per spec over the shared stack.

    Each seat gets its own provider and controller reading the one live env; the
    seats share one scheduler, which applies the first seat's declared timeout
    fallback (a per-seat scheduler stays deferred).

    A game with no model seat composes an empty seat list and a scheduler nothing
    submits to. That is what two people in one environment is, and it steps through
    the same loop rather than through a second one.
    """
    fallback = (
        seat_specs[0].agent.on_timeout.value if seat_specs else Fallback.WAIT.value
    )
    scheduler = Scheduler(
        store=store,
        now=now,
        fallback=FallbackRule(on_timeout=fallback, on_stale=fallback),
        default_action=default_action,
    )
    seats: list[AgentSeat] = []
    for seat_spec in seat_specs:
        provider = ModelProvider(
            store=store,
            adapter=seat_spec.adapter,
            now=now,
            new_generation_id=new_generation_id,
            diagnostics=diagnostics,
        )
        controller = LLMController(
            agent=seat_spec.agent,
            agent_version=compile_agent(seat_spec.agent, ids=seat_spec.ids),
            provider=provider,
            env=env,
            agent_id=seat_spec.agent_id,
            new_context=new_context,
            resolve_secret=seat_spec.resolve_secret,
            # What this seat carries out of the last round, when something owns the
            # rounds and kept it. The history is deliberately not among it: it is
            # the episode's own transitions, and this episode is a new one.
            chat=memory.chat_of(seat_spec.agent_id) if memory else None,
            thoughts=memory.thoughts_of(seat_spec.agent_id) if memory else None,
            diagnostics=diagnostics,
            seat_key=seat_spec.seat_key,
        )
        seats.append(
            AgentSeat(
                seat_key=seat_spec.seat_key,
                agent_id=seat_spec.agent_id,
                actor_id=seat_spec.actor_id,
                agent=seat_spec.agent,
                controller=controller,
                seat=ScheduledSeat(
                    default_action=default_action,
                    carry_out=_carrying_out(seat_spec.agent, env, seat_spec.agent_id),
                ),
                text_view=seat_spec.text_view,
            )
        )
    return scheduler, seats


def _carrying_out(
    agent: LLMAgent, env: Any, agent_id: str
) -> Callable[[int | None], int | None] | None:
    """Bind one agent's ``carry_out`` to the seat it plays, if it wrote one.

    An agent that wrote none is answered ``None``, and the seat then holds its
    choice and steps it -- which is what every scheduled seat did before an agent
    could decide at a coarser grain than the environment steps. Asking the base
    method once a frame instead would be the same answer at the cost of a call and,
    worse, would make the two cases indistinguishable to anything reading the seat.
    """
    if type(agent).carry_out is LLMAgent.carry_out:
        return None
    return lambda chosen: agent.carry_out(env, agent_id, chosen)


def _waits_for(seat_specs: tuple[AgentSeatSpec, ...], written: float) -> float:
    """Return how long a decision has, given every model seat in one activity.

    The seats share one scheduler, so there is one deadline, and it is the longest
    any of them asked for: a shorter one would make a slower model fall back on
    every decision it ever made, with nothing in the records to say the study had
    never waited for it.
    """
    asked = [seat.agent.answers_within for seat in seat_specs]
    return max([written, *asked]) if asked else written


def _held(
    spec: AgentGameSpec,
    human_source: SeatActionSource | None,
    human_sources: Mapping[str, SeatActionSource] | None,
) -> dict[str, SeatActionSource]:
    """Return the input each human seat is driven by, keyed by seat key.

    ``human_sources`` names the seat each input belongs to, which is what several
    people in one environment needs. ``human_source`` is the one-person spelling and
    binds to the spec's first human seat.
    """
    held = dict(human_sources or {})
    if human_source is not None and spec.human_seats:
        held.setdefault(spec.human_seats[0].seat_key, human_source)
    return held


def _local_seats(
    spec: AgentGameSpec,
    human_source: SeatActionSource | None,
    human_sources: Mapping[str, SeatActionSource] | None,
) -> list[LocalSeat]:
    """Wire every seat a local source drives: the people first, then the bots.

    A human seat is wired only when its input was supplied, so a specification read
    without a transport (a test, or a run nobody is watching) steps the model seats
    alone rather than steps a seat nobody holds. Every bot seat is always wired,
    because its policy is the study's own and needs no connection.
    """
    held = _held(spec, human_source, human_sources)
    seats = [
        LocalSeat(
            seat_key=human.seat_key,
            agent_id=human.agent_id,
            source=held[human.seat_key],
        )
        for human in spec.human_seats
        if human.seat_key in held
    ]
    seats.extend(
        LocalSeat(
            seat_key=bot.seat_key,
            agent_id=bot.agent_id,
            source=bot.controller,
        )
        for bot in spec.bots
    )
    return seats


def _turnbased_local_seats(
    human: HumanSeatSpec | None, human_source: SeatActionSource | None
) -> list[LocalSeat]:
    """Wire the one human seat a turn-based game seats, when its input is supplied.

    A turn-based game seats at most one person: the loop waits for the seat whose
    turn it is, and several people taking turns is a different loop with a different
    wait. So this stays the one-person spelling on purpose.
    """
    if human is None or human_source is None:
        return []
    return [
        LocalSeat(
            seat_key=human.seat_key,
            agent_id=human.agent_id,
            source=human_source,
        )
    ]


def build_agent_episode(
    spec: AgentGameSpec,
    *,
    store: Store,
    new_context: NewContext,
    new_decision_id: Callable[[], str],
    new_generation_id: Callable[[], str],
    now: Callable[[], datetime],
    interaction_id: str,
    episode_id: str,
    episode_generation: int = 1,
    human_source: SeatActionSource | None = None,
    human_sources: Mapping[str, SeatActionSource] | None = None,
    frame_sink: MultiSeatObserver | None = None,
    memory: SeatMemory | None = None,
    diagnostics: Diagnostics | None = None,
) -> MultiAgentEpisode:
    """Compose the built stack for one simultaneous multi-seat game into an episode.

    Each model seat gets its own provider and controller over the shared store and
    clock; the seats share one scheduler and one live environment. The people and
    the bots are wired beside them through the one action-source seam, so two
    participants, a model partner, and a scripted bot are one episode over one
    environment. ``human_sources`` names each person's input by seat key; the
    ``frame_sink`` is the transport's per-frame push to whoever is watching.
    ``diagnostics`` is where each seat says what it was asked and what came back, for
    a process started in debug mode; with none, nothing is written down.
    """
    env = spec.make_env()
    scheduler, seats = _compose_seats(
        spec.seats,
        env,
        store=store,
        new_context=new_context,
        new_generation_id=new_generation_id,
        now=now,
        default_action=spec.default_action,
        memory=memory,
        diagnostics=diagnostics,
    )
    return MultiAgentEpisode(
        env=env,
        seats=seats,
        scheduler=scheduler,
        channel_key=spec.channel_key,
        episode_id=episode_id,
        interaction_id=interaction_id,
        episode_generation=episode_generation,
        new_context=new_context,
        new_decision_id=new_decision_id,
        now=now,
        decision_timeout=_waits_for(spec.seats, spec.decision_timeout),
        local_seats=_local_seats(spec, human_source, human_sources),
        frame_sink=frame_sink,
        fps=spec.fps,
        max_steps=spec.max_steps,
        make_env=_spare_env(spec),
    )


async def warm_up_seats(
    spec: AgentGameSpec,
    *,
    store: Store,
    new_context: NewContext,
    new_modelcall_id: Callable[[], str],
    new_generation_id: Callable[[], str],
    now: Callable[[], datetime],
    diagnostics: Diagnostics | None = None,
) -> list[str]:
    """Reach every model seat of a game once, and name the ones that did not answer.

    This is the warm-up as a study can run it **before there is a round**, which is
    the only place it is worth anything. Two things are paid on the first call a
    model seat makes: loading the model, which a runner does after a quiet spell,
    and reading the fixed part of the study's prompt. Paid inside the round they are
    a partner frozen in a running kitchen; paid while the participant is still on
    the consent form they are paid by nobody.

    So it composes seats of its own over an environment of its own -- neither the
    round's seats nor the round's environment, which do not exist yet -- asks each
    one the study's real question, and throws all of it away. What is left behind is
    a model in the runner's memory, a prompt prefix in its cache, and the answer to
    "does this provider answer": which is the whole of what a warm-up is for.

    A game with no model seat needs none and makes no call.
    """
    if not spec.seats:
        return []
    spare = _spare_env(spec)
    env = spare() if spare is not None else None
    _scheduler, seats = _compose_seats(
        spec.seats,
        env,
        store=store,
        new_context=new_context,
        new_generation_id=new_generation_id,
        now=now,
        default_action=spec.default_action,
        diagnostics=diagnostics,
    )
    answered = await asyncio.gather(
        *[seat.controller.warm_up(new_modelcall_id(), on=env) for seat in seats]
    )
    return [
        seat.seat_key
        for seat, ready in zip(seats, answered, strict=True)
        if not ready
    ]


def _spare_env(spec: AgentGameSpec) -> Callable[[], Any] | None:
    """Return how to make one throwaway environment, for a warm-up to read.

    A warm-up asks the study's own question, which means reading an environment --
    and the one the round is about to be played on must not be read or reset by
    anything but the round. So it reads one of its own, built the same way and
    thrown away. A game with no model seat needs none and is given none.
    """
    if not spec.seats:
        return None

    def spare() -> Any:
        env = spec.make_env()
        # A fresh environment has nothing in it until it is reset, and a study's
        # prompt is written about a kitchen that exists.
        with contextlib.suppress(Exception):
            cast("Any", env).reset()
        return env

    return spare


def build_turnbased_episode(
    spec: TurnBasedGameSpec,
    *,
    store: Store,
    new_context: NewContext,
    new_decision_id: Callable[[], str],
    new_generation_id: Callable[[], str],
    now: Callable[[], datetime],
    interaction_id: str,
    episode_id: str,
    episode_generation: int = 1,
    human_source: SeatActionSource | None = None,
    frame_sink: TurnBasedObserver | None = None,
) -> TurnBasedAgentEpisode:
    """Compose the built stack for one turn-based (AEC) agent game into an episode.

    The seats are composed exactly as for a simultaneous game; the difference is the
    loop, which waits for the seat whose turn it is. The live env the seats read is
    wrapped in the ``TurnBasedEnv`` seam the loop steps. The ``frame_sink`` pushes
    each played turn to a watching participant.
    """
    env = spec.make_env()
    scheduler, seats = _compose_seats(
        spec.seats,
        env,
        store=store,
        new_context=new_context,
        new_generation_id=new_generation_id,
        now=now,
        default_action=spec.default_action,
    )
    return TurnBasedAgentEpisode(
        env=env,
        step_env=spec.step_env(env),
        seats=seats,
        scheduler=scheduler,
        channel_key=spec.channel_key,
        episode_id=episode_id,
        interaction_id=interaction_id,
        episode_generation=episode_generation,
        new_context=new_context,
        new_decision_id=new_decision_id,
        now=now,
        decision_timeout=_waits_for(spec.seats, spec.decision_timeout),
        local_seats=_turnbased_local_seats(spec.human, human_source),
        frame_sink=frame_sink,
        fps=spec.fps,
        max_steps=spec.max_steps,
    )


__all__ = [
    "AgentGameSpec",
    "AgentSeatSpec",
    "BotSeatSpec",
    "HumanSeatSpec",
    "TurnBasedGameSpec",
    "build_agent_episode",
    "build_turnbased_episode",
    "warm_up_seats",
]
