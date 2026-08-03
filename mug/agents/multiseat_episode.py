"""Run one multi-seat episode: any mix of people, models, and bots, on one timeline.

This is the one multi-seat episode runtime; a single-seat run is its one-seat case
(``mug.agents.AgentEpisode`` is a thin facade over it). It drives a whole
interaction of seats over one shared, server-authoritative environment: one LLM,
a person beside an LLM, two LLM agents together, or two people and a model
partner. Each frame the
shared loop (``mug.game.multiseat.run_multiseat_episode``) steps every seat's
action at once; this runner samples each LLM seat, fires its decision at its own
cadence without blocking the frame, and records the frame into each agent's own
history -- so an agent reads the whole game, including what its partner just did.

Each LLM seat keeps its own runtime: its own ``LLMController`` (so its own prompt,
thoughts, and history), its own held-action ``ScheduledSeat``, and its own recorded
decisions. A human seat contributes only a ``SeatActionSource`` the transport
updates; the loop reads it beside the model seats through the one seam. The
scheduler, the store command context, the clock, and the episode identity are
shared, because the seats share one interaction and one episode.

Every agent records its own history, so it names the other seats' moves with its
own action vocabulary. The multi-agent environments this targets share one action
set across seats, so an agent reads its partner's moves correctly; an environment
with per-seat action names would name a partner's move by index instead. A posted
chat message reaches every agent seat, so one human instruction is read by all.

The runner mints a fresh decision id per decision and reads the clock, so it is a
producer boundary the caller injects into, the same as the single-seat runner.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import cast

from mug.agents.runtime import LLMController
from mug.authoring import Fallback, LLMAgent, Message, Step
from mug.game.controllers import ScheduledSeat
from mug.game.multiseat import (
    MultiSeatEnv,
    MultiSeatObserver,
    MultiSeatStepInfo,
    MultiSeatSummary,
    run_multiseat_episode,
)
from mug.game.runtime import SeatActionSource
from mug.kernel import Duration, compute_digest
from mug.providers import ModelCallResult
from mug.scheduling import DecisionRequest, Scheduler
from mug.scheduling.runtime import DecisionOutcome, NewContext

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"

# The live study environment both the loop steps and each controller reads.
AgentEnv = object

# How long a decision has to return before the seat falls back, in seconds.
DecisionTimeout = float

# Render one seat's game as text for its own prompt (the study supplies it).
TextView = Callable[[AgentEnv, str], str]


def _instant(moment: datetime) -> str:
    """Return one moment in the canonical UTC wire form."""
    return moment.astimezone(timezone.utc).strftime(_INSTANT)


@dataclass(frozen=True)
class AgentSeat:
    """One LLM seat in a multi-seat interaction: a model drives it.

    ``agent_id`` is the environment agent the seat plays (the key the loop steps and
    the reward is drawn on); ``seat_key`` and ``actor_id`` are the recorded seat and
    actor identity. ``controller`` and ``seat`` are the seat's own runtime -- its
    prompt, thoughts, and history, and its held action. ``text_view`` renders the
    game for this seat's prompt, when the study records one.
    """

    seat_key: str
    agent_id: str
    actor_id: str
    agent: LLMAgent
    controller: LLMController
    seat: ScheduledSeat
    text_view: TextView | None = None


@dataclass(frozen=True)
class LocalSeat:
    """One seat in a multi-seat interaction that a local source drives.

    ``agent_id`` is the environment agent the seat plays; ``source`` is what the
    seat holds each frame. A person's source is an ``InputState`` a websocket
    updates; a bot's is the study's own policy. The loop reads both beside the model
    seats through the one ``SeatActionSource`` seam, which is why they are one type.

    The seat carries no actor id and no label for what drives it. Who sat here and
    whether they were a person is recorded by the room that cast the seat, and one
    record of that is enough.
    """

    seat_key: str
    agent_id: str
    source: SeatActionSource


def _no_decisions() -> list[DecisionOutcome]:
    """Return an empty, typed decision list for a fresh seat result."""
    return []


def _no_model_calls() -> list[ModelCallResult]:
    """Return an empty, typed model-call list for a fresh seat result."""
    return []


@dataclass
class AgentSeatResult:
    """What one LLM seat produced this episode: its decisions and its transcript.

    ``model_calls`` is every model call this seat made, in call order, so a caller
    one layer up (``mug.replay.build_decision_tape``) assembles the decision tape for
    a replay bundle; the runner cannot build the tape itself, because the builder
    lives above the agent layer.
    """

    seat_key: str
    agent_id: str
    actor_id: str
    decisions: list[DecisionOutcome] = field(default_factory=_no_decisions)
    model_calls: list[ModelCallResult] = field(default_factory=_no_model_calls)


@dataclass(frozen=True)
class MultiAgentEpisodeResult:
    """The result of one multi-seat episode: the shared frames and each seat's run.

    ``summary`` is the loop's shared timeline (the transitions and the boundary).
    ``seats`` holds one result per LLM seat, keyed by agent id, each carrying that
    seat's recorded decisions; its history and thoughts stay on its own controller.
    """

    summary: MultiSeatSummary
    seats: dict[str, AgentSeatResult]

    def model_calls(self) -> list[ModelCallResult]:
        """Return every seat's model calls, in seat order, for a decision tape.

        The seats keep their insertion order (the order the loop steps them), so the
        flat list is deterministic. ``mug.replay.build_decision_tape`` turns it into
        the API-16 tape for a replay bundle.
        """
        calls: list[ModelCallResult] = []
        for seat in self.seats.values():
            calls.extend(seat.model_calls)
        return calls


class _AgentSeatDriver:
    """Drive one LLM seat inside the shared multi-seat loop.

    The driver holds the seat's runtime and the shared machinery it decides
    through. Each frame it records the whole step into this seat's history, applies
    a finished decision to the held seat, and, at this seat's cadence, starts a
    background decision. It never blocks the loop: a decision runs as a task, and
    its action lands on the seat when the model returns.
    """

    def __init__(
        self,
        *,
        seat: AgentSeat,
        all_agent_ids: Sequence[str],
        scheduler: Scheduler,
        env: AgentEnv,
        channel_key: str,
        episode_id: str,
        interaction_id: str,
        episode_generation: int,
        new_context: NewContext,
        new_decision_id: Callable[[], str],
        now: Callable[[], datetime],
        decision_timeout: DecisionTimeout,
    ) -> None:
        self._plan = seat
        self._agent = seat.agent
        self._controller = seat.controller
        self._seat = seat.seat
        self._agent_id = seat.agent_id
        self._all_ids = tuple(all_agent_ids)
        self._scheduler = scheduler
        self._env = env
        self._channel_key = channel_key
        self._episode_id = episode_id
        self._interaction_id = interaction_id
        self._episode_generation = episode_generation
        self._new_context = new_context
        self._new_decision_id = new_decision_id
        self._now = now
        self._timeout = decision_timeout
        self._window = Duration(microseconds=int(decision_timeout * 1_000_000))

        self._latest_obs: object = None
        self._last_action: int | None = None
        self._task: asyncio.Task[DecisionOutcome] | None = None
        # Set when somebody speaks to this seat, cleared when a decision starts. It
        # is what lets a partner answer as soon as it is free instead of at its
        # next turn.
        self._woken = False
        # Whether this seat has been asked anything at all this round. Until it has,
        # it holds no choice, so there is nothing for the cadence to protect and the
        # first frame asks.
        self._ever_asked = False
        # The held-action seat the loop reads each frame, exposed for the episode.
        self.source: SeatActionSource = seat.seat
        self.result = AgentSeatResult(
            seat_key=seat.seat_key, agent_id=seat.agent_id, actor_id=seat.actor_id
        )
        # What this seat has said and nobody has published yet. The loop must not
        # wait on a channel commit, so the driver collects and the episode drains.
        self.said: list[str] = []
        self.actor_id = seat.actor_id

    def deliver(self, message: Message) -> None:
        """Record one chat message on this seat's controller, and wake it.

        Waking is what makes a partner answerable. A seat decides at its own
        cadence, which for a model that plays is once every ``decides_every``
        frames; without this, somebody who typed "get a plate" would wait out the
        rest of that cadence for any sign they had been heard, and a partner you
        have to wait on is not one you talk to.

        It sets a flag rather than starting a decision, so the decision still starts
        on the loop's own frame and never on the socket's thread of control. A seat
        already deciding is not disturbed: the message is in its history and the
        decision in flight has not been sent yet or cannot be recalled, and either
        way the next one reads it.
        """
        self._controller.record_message(message)
        self._woken = True
        self._controller.diagnostics.note(
            "agent.heard",
            subject=self._controller.label,
            sender=message.sender,
            text=message.text,
            deciding=self._task is not None,
        )

    def take_said(self) -> list[str]:
        """Take everything this seat has said and not yet had published."""
        said, self.said = self.said, []
        return said

    async def warm_up(self, modelcall_id: str, *, on: AgentEnv = None) -> bool:
        """Reach this seat's model before the round, and say whether it answered."""
        return await self._controller.warm_up(modelcall_id, on=on)

    async def answer(self, modelcall_id: str) -> None:
        """Say something back, with nothing stepping and no action to read.

        The loop is not running, so nothing here is a decision: no deadline is
        applied and no fallback stands in for an answer that did not come. A seat
        that says nothing has answered, and the wake is spent either way.
        """
        self._woken = False
        said = await self._controller.answer(modelcall_id)
        if said:
            self.said.append(said)

    def record_and_maybe_decide(self, info: MultiSeatStepInfo) -> None:
        """Record the frame, apply a ready decision, and maybe start a new one.

        A seat somebody has spoken to decides on this frame whatever its cadence
        says, so it answers as soon as it is free rather than at its next turn.

        **A seat that has not been asked anything yet is asked now.** The cadence
        exists to stop a seat re-choosing a job it has not started; at the first
        frame of a round there is no job to protect, so waiting out a whole cadence
        period buys nothing and costs the participant every frame of it. It cost a
        second at ``decides_every=30`` and thirty frames a second -- one second of a
        partner standing still before the model was even asked, on top of however
        long the model then took.
        """
        self._latest_obs = info.result.observations.get(self._agent_id)
        self._record_step(info)
        self._apply_ready()
        due = info.frame % self._agent.decides_every == 0
        if not self._ever_asked or due or self._woken:
            self._start_decision()

    def drain(self) -> None:
        """Apply a decision that finished during the loop's yield, if any."""
        self._apply_ready()

    async def finish(self) -> None:
        """Drain an in-flight decision and record the seat's model calls.

        A decision still in flight at the episode end is drained first, so none is
        lost; then the controller's model calls are copied onto the seat result, so
        a decision tape can be built from the whole episode one layer up.
        """
        if self._task is not None:
            self._settle(await self._task)
            self._task = None
        self.result.model_calls = list(self._controller.results)

    # -- internals --------------------------------------------------------------

    def _record_step(self, info: MultiSeatStepInfo) -> None:
        """Record one frame into this seat's history: every seat's move and reward.

        The step names every seat's action and reward, so this agent reads what its
        partner did. The action names use this seat's own vocabulary; the target
        multi-agent environments share one action set across seats.
        """
        names = self._agent.available_actions(self._env, self._agent_id)
        actions = {
            agent_id: _name(names, info.actions.get(agent_id))
            for agent_id in self._all_ids
        }
        rewards = {
            agent_id: info.result.rewards.get(agent_id, 0.0)
            for agent_id in self._all_ids
        }
        views = None
        if self._plan.text_view is not None:
            views = {self._agent_id: self._plan.text_view(self._env, self._agent_id)}
        self._controller.record_step(
            Step(tick=info.frame, actions=actions, rewards=rewards, views=views)
        )

    def _start_decision(self) -> None:
        """Start a background decision, unless one is already in flight.

        A seat that was woken and could not start keeps its wake, so somebody who
        spoke while the seat was mid-decision is answered on the frame after it
        returns rather than losing their turn to it.
        """
        if self._task is not None:
            # The cadence came round and the last decision has not come back. It is
            # the reading behind "the partner only moves every few seconds": the
            # model is slower than the rate the study asked it to decide at, and
            # nothing else in the run says so.
            self._controller.diagnostics.note(
                "agent.busy",
                subject=self._controller.label,
                decides_every=self._agent.decides_every,
            )
            return
        self._woken = False
        self._ever_asked = True
        self._task = asyncio.create_task(self._decide(self._build_request()))

    async def _decide(self, request: DecisionRequest) -> DecisionOutcome:
        """Drive one decision through the scheduler, awaiting the LLM controller."""
        return await self._scheduler.decide(
            request=request,
            observation=self._latest_obs,
            controller=self._controller.decide,
            new_context=self._new_context,
            last_action=self._last_action,
        )

    def _apply_ready(self) -> None:
        """Apply a finished decision's action to the seat, if one has returned."""
        task = self._task
        if task is not None and task.done():
            self._settle(task.result())
            self._task = None

    def _settle(self, outcome: DecisionOutcome) -> None:
        """Record a decision outcome and set what the seat has chosen.

        A decision that fell back is read through the agent's own ``on_timeout``,
        because the two rules mean different things to a seat that decides at a
        coarser grain than the environment steps:

        - ``REPEAT_LAST`` keeps the choice, which is the whole point of a choice that
          lasts: a partner half way to the pot goes on to the pot.
        - ``WAIT`` leaves the seat with **no** choice, which is not the same as
          choosing the idle action. ``carry_out`` is told nobody has said what to do
          and answers for itself; a seat with no ``carry_out`` takes the game's
          default action, exactly as it did before.

        The last **decided** choice is kept either way, so a repeat-last fallback
        has something real to repeat rather than repeating a fallback.

        What the seat said on the same decision is taken here too. It is taken even
        when the outcome fell back, because falling back is a statement about the
        **action**: a reply nobody could read an action out of may still have said
        something, and dropping it would lose a message the model really produced.
        """
        self.result.decisions.append(outcome)
        waited = outcome.used_fallback and self._agent.on_timeout is Fallback.WAIT
        if outcome.used_fallback:
            # The seat did not choose this; the rule did. A partner that plays the
            # same move all round is either a model repeating itself or a fallback
            # firing every decision, and from the screen the two are the same
            # picture.
            self._controller.diagnostics.note(
                "agent.fallback",
                subject=self._controller.label,
                rule=self._agent.on_timeout.name,
                action=None if waited else outcome.action,
                waited_ms=int(self._timeout * 1000),
            )
        self._seat.apply(None if waited else outcome.action)
        if not outcome.used_fallback:
            self._last_action = outcome.action
        said = self._controller.take_message()
        if said:
            self.said.append(said)

    def _build_request(self) -> DecisionRequest:
        """Mint the decision request for the current frame's state and deadline."""
        now = self._now()
        deadline = now + timedelta(seconds=self._timeout)
        return DecisionRequest(
            decision_id=self._new_decision_id(),
            actor_id=self._plan.actor_id,
            channel_key=self._channel_key,
            execution_mode="server",
            episode_generation=self._episode_generation,
            source_observation_digest=compute_digest(self._latest_obs),
            deadline=_instant(deadline),
            validity_window=self._window,
            submitted_at=_instant(now),
        )


class MultiAgentEpisode:
    """Drive a multi-seat interaction through one episode on the built stack.

    The caller composes the seats a study composes -- one ``AgentSeat`` per LLM seat
    (its agent, controller, and held seat) and one ``LocalSeat`` per person or bot
    -- and
    hands them here with the shared scheduler, store context, and episode identity.
    The runner owns the loop: it steps every seat's action set each frame, samples
    every model seat, fires each decision at its own cadence, and feeds each agent's
    history and chat.
    """

    def __init__(
        self,
        *,
        env: AgentEnv,
        seats: Sequence[AgentSeat],
        scheduler: Scheduler,
        channel_key: str,
        episode_id: str,
        interaction_id: str,
        episode_generation: int,
        new_context: NewContext,
        new_decision_id: Callable[[], str],
        now: Callable[[], datetime],
        decision_timeout: DecisionTimeout,
        local_seats: Sequence[LocalSeat] = (),
        step_env: MultiSeatEnv | None = None,
        frame_sink: MultiSeatObserver | None = None,
        fps: int = 0,
        max_steps: int = 200,
        make_env: Callable[[], AgentEnv] | None = None,
    ) -> None:
        if not seats and not local_seats:
            # A model seat is no longer what makes an episode: several people in one
            # environment is an episode too, and it steps through this same loop.
            raise ValueError("a multi-seat episode needs at least one seat")
        self._env = env
        # An optional per-frame sink the transport wires to push each stepped frame
        # to a watching participant. The loop stays render-neutral; the sink is the
        # human-watching render path the module docstring names.
        self._frame_sink = frame_sink
        # The frame the loop has reached, so a message a seat said is placed at the
        # frame it was said at rather than at the end of the run.
        self._frame = 0
        # A multi-agent study env satisfies both seams, so the loop steps the same
        # object the controllers read; the solo facade passes a lifted step env.
        self._step_env: MultiSeatEnv = (
            step_env if step_env is not None else cast("MultiSeatEnv", env)
        )
        self._channel_key = channel_key
        self._episode_id = episode_id
        self._interaction_id = interaction_id
        self._now = now
        self._fps = fps
        self._max_steps = max_steps
        self._local = tuple(local_seats)
        # How to make one more environment of the same kind, for a warm-up to read.
        # A round is never warmed up on the environment it is about to be played on.
        self._make_env = make_env

        # The loop steps the model seats first, then the local seats, in one order.
        self._agent_ids = tuple(
            [seat.agent_id for seat in seats]
            + [seat.agent_id for seat in self._local]
        )
        if len(set(self._agent_ids)) != len(self._agent_ids):
            raise ValueError("each seat must play a distinct environment agent")

        self._drivers = [
            _AgentSeatDriver(
                seat=seat,
                all_agent_ids=self._agent_ids,
                scheduler=scheduler,
                env=env,
                channel_key=channel_key,
                episode_id=episode_id,
                interaction_id=interaction_id,
                episode_generation=episode_generation,
                new_context=new_context,
                new_decision_id=new_decision_id,
                now=now,
                decision_timeout=decision_timeout,
            )
            for seat in seats
        ]

    async def run(self) -> MultiAgentEpisodeResult:
        """Run the episode to its end and return the shared frames and each seat's run.

        The loop drives every seat; ``_observe`` records each frame into every
        agent's history and starts each due decision. A decision runs in the
        background, so the loop never waits on a model; any decision still in flight
        at the end is drained, so no model call is left recorded without its outcome.
        """
        sources: dict[str, SeatActionSource] = {
            driver.result.agent_id: driver.source for driver in self._drivers
        }
        for seat in self._local:
            sources[seat.agent_id] = seat.source

        summary = await run_multiseat_episode(
            self._step_env,
            channel_key=self._channel_key,
            episode_id=self._episode_id,
            interaction_id=self._interaction_id,
            agent_ids=self._agent_ids,
            sources=sources,
            now=lambda: _instant(self._now()),
            fps=self._fps,
            max_steps=self._max_steps,
            on_step=self._observe,
        )
        for driver in self._drivers:
            await driver.finish()
        return MultiAgentEpisodeResult(
            summary=summary,
            seats={driver.result.agent_id: driver.result for driver in self._drivers},
        )

    def post_message(self, *, sender: str, text: str, tick: int | None = None) -> None:
        """Hand one chat message to every agent seat the transport says may see it.

        A message reaches the seats in the channel it was said on, so each reads it
        in its prompt next decision. Who may see it is the room's decision and not
        this runner's: the transport calls this only for the seats the membership
        admits, which is what keeps a private channel private (W5).
        """
        for driver in self._drivers:
            driver.deliver(Message(sender=sender, text=text, tick=tick))

    async def warm_up(self, new_modelcall_id: Callable[[], str]) -> list[str]:
        """Reach every model seat once before the round, and name the ones that fail.

        A provider that cannot be reached draws itself as a partner that stands
        still, which is the one picture a participant cannot read. Reaching it
        before the first frame turns that into something the study knows: the seats
        that answered, and the seats that did not.

        It also pays for loading the model and for reading the fixed part of the
        study's prompt, which a runner does on the first call after a quiet spell --
        and the quiet spell is the consent form and the instructions. A wait before
        a game starts is a wait somebody can read.

        Nothing here touches the environment or what a seat carries, so a round that
        is warmed up plays exactly the round it would have played. Every seat is
        reached at once, so a table of several models waits for one of them.
        """
        # One throwaway environment for every seat: it is read to build the prompts
        # and then dropped. The round's own environment is never touched, so a round
        # that was warmed up plays exactly the round it would have played -- which
        # is why this is not simply the round's environment reset early.
        spare = self._make_env() if self._make_env is not None else None
        answered = await asyncio.gather(
            *[driver.warm_up(new_modelcall_id(), on=spare) for driver in self._drivers]
        )
        return [
            driver.result.seat_key
            for driver, ready in zip(self._drivers, answered, strict=True)
            if not ready
        ]

    async def answer(self, new_modelcall_id: Callable[[], str]) -> None:
        """Let every model seat answer what it has been told, with nothing stepping.

        This is the seat between rounds. The loop has ended and the environment is
        standing at the state the round left it in, which is what the seat is asked
        about: the kitchen as it ended is exactly what "we ran out of time on that
        last soup" is about.

        Nothing is recorded as a decision, because nothing decided anything: the
        turn leaves a model call and, when the seat says something, a message. What
        is said is collected here and published by the transport, the same way a
        seat's words are published during a round.

        Every seat is asked at once, so a table of several models answers in the
        time one of them takes.
        """
        await asyncio.gather(
            *[driver.answer(new_modelcall_id()) for driver in self._drivers]
        )

    def take_said(self) -> list[tuple[str, str, int]]:
        """Take what every seat has said since the last drain, in seat order.

        Each entry is the seat's actor, its words, and the frame it said them at.
        The runner collects rather than publishes: committing a message to a
        channel is a store write, and the stepping loop must never wait on one
        (NS-06). The transport drains this between frames and publishes.
        """
        said: list[tuple[str, str, int]] = []
        for driver in self._drivers:
            for text in driver.take_said():
                said.append((driver.actor_id, text, self._frame))
        return said

    async def _observe(self, info: MultiSeatStepInfo) -> None:
        """Record the frame into every seat, then let a due decision resolve.

        Each driver records the step and starts its decision at its cadence. The
        yield lets the background decisions make progress even with no real frame
        delay, so a slow model resolves within a few frames instead of only at the
        episode's end; the second drain applies any that finished on the yield.
        """
        self._frame = info.frame
        for driver in self._drivers:
            driver.record_and_maybe_decide(info)
        await asyncio.sleep(0)
        for driver in self._drivers:
            driver.drain()
        if self._frame_sink is not None:
            await self._frame_sink(info)


def _name(names: Sequence[str], action: int | None) -> str:
    """Return the action name for an index, or its string form when out of range."""
    if action is not None and 0 <= action < len(names):
        return names[action]
    return str(action)


__all__ = [
    "AgentSeat",
    "AgentSeatResult",
    "LocalSeat",
    "MultiAgentEpisode",
    "MultiAgentEpisodeResult",
]
