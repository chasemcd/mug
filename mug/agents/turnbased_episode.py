"""Run one turn-based (AEC) episode: many seats, one moving each turn.

This is the turn-based sibling of ``mug.agents.multiseat_episode``. The
simultaneous runner samples every seat each frame and never blocks on a slow
model; the turn-based runner drives a game where the seats act one at a time, and
so it *waits* for the seat whose turn it is -- because a turn-based game genuinely
waits for the player in turn. One LLM against another, or an LLM against a human,
takes turns over one shared, server-authoritative AEC environment.

Each LLM seat keeps its own runtime -- its ``LLMController`` (prompt, thoughts,
history), its held-action ``ScheduledSeat``, and its recorded decisions -- and
records every turn into its own history, so a seat reads the moves the other seats
already played this game. The study's AEC environment satisfies both seams: the
loop steps it through the ``AecEnv`` adapter, and each controller reads the same
instance for its text view, so the model sees the live board. A human seat
contributes a ``SeatActionSource`` the transport updates; on its turn the loop
reads the held key.

The runner mints a fresh decision id per decision and reads the clock, so it is a
producer boundary the caller injects into, the same as the other episode runners.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from mug.agents.multiseat_episode import (
    AgentSeat,
    AgentSeatResult,
    LocalSeat,
)
from mug.authoring import Message, Step
from mug.game.aec import (
    TurnBasedEnv,
    TurnBasedObserver,
    TurnBasedSummary,
    TurnState,
    TurnStepInfo,
    run_turnbased_episode,
)
from mug.game.seams import SeatActionSource
from mug.kernel import Duration, compute_digest
from mug.providers import ModelCallResult
from mug.scheduling import DecisionRequest, Scheduler
from mug.scheduling.runtime import NewContext

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"

# The live study environment both the loop steps and each controller reads.
AgentEnv = object

# How long a decision has to return before the seat falls back, in seconds.
DecisionTimeout = float


def _instant(moment: datetime) -> str:
    """Return one moment in the canonical UTC wire form."""
    return moment.astimezone(timezone.utc).strftime(_INSTANT)


def _name(names: Sequence[str], action: int | None) -> str:
    """Return the action name for an index, or its string form when out of range."""
    if action is not None and 0 <= action < len(names):
        return names[action]
    return str(action)


@dataclass(frozen=True)
class TurnBasedAgentEpisodeResult:
    """The result of one turn-based episode: the shared turns and each seat's run.

    ``summary`` is the loop's shared timeline (the recorded turns and the
    boundary). ``seats`` holds one result per LLM seat, keyed by agent id, each
    carrying that seat's recorded decisions; its history and thoughts stay on its
    own controller.
    """

    summary: TurnBasedSummary
    seats: dict[str, AgentSeatResult]

    def model_calls(self) -> list[ModelCallResult]:
        """Return every seat's model calls, in seat order, for a decision tape.

        ``mug.replay.build_decision_tape`` turns the flat list into the API-16 tape
        for a replay bundle; the runner cannot build it, because the builder lives
        above the agent layer.
        """
        calls: list[ModelCallResult] = []
        for seat in self.seats.values():
            calls.extend(seat.model_calls)
        return calls


class _TurnSeatDriver:
    """Drive one LLM seat inside the turn-based loop.

    On the seat's turn the driver awaits its decision and applies it to the held
    seat, so the loop reads the fresh action; the turn-based game waits for the
    seat, so this decision is not a background task. Each turn -- its own and the
    others' -- it records the move into this seat's history, so the seat reads what
    the other seats played before its next turn.
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
        self.agent_id = seat.agent_id
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
        # The held-action seat the loop reads on this seat's turn.
        self.source: SeatActionSource = seat.seat
        self.result = AgentSeatResult(
            seat_key=seat.seat_key, agent_id=seat.agent_id, actor_id=seat.actor_id
        )

    def deliver(self, message: Message) -> None:
        """Record one chat message on this seat's controller, for its next prompt."""
        self._controller.record_message(message)

    def finish(self) -> None:
        """Copy the controller's model calls onto the seat result at episode end.

        A decision tape is built one layer up from every seat's model calls, so the
        driver records them on its result when the game ends.
        """
        self.result.model_calls = list(self._controller.results)

    async def decide_turn(self, observation: object) -> None:
        """Await this seat's decision and apply it to the held seat for the loop."""
        self._latest_obs = observation
        outcome = await self._scheduler.decide(
            request=self._build_request(),
            observation=observation,
            controller=self._controller.decide,
            new_context=self._new_context,
            last_action=self._last_action,
        )
        self.result.decisions.append(outcome)
        self._seat.apply(outcome.action)
        self._last_action = outcome.action

    def record(self, info: TurnStepInfo) -> None:
        """Record one turn into this seat's history: the one mover and the rewards.

        Only the seat whose turn it was moved, so the step names that one move; the
        rewards name every seat. The move is named with this seat's own action
        vocabulary, which the turn-based games this targets share across seats.
        """
        names = self._agent.available_actions(self._env, self.agent_id)
        actions = {info.agent: _name(names, info.action)}
        rewards = {
            agent_id: info.state.rewards.get(agent_id, 0.0)
            for agent_id in self._all_ids
        }
        views = None
        if self._plan.text_view is not None:
            views = {self.agent_id: self._plan.text_view(self._env, self.agent_id)}
        self._controller.record_step(
            Step(tick=info.frame, actions=actions, rewards=rewards, views=views)
        )

    def _build_request(self) -> DecisionRequest:
        """Mint the decision request for this turn's state and deadline."""
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


class TurnBasedAgentEpisode:
    """Drive a turn-based interaction of seats through one AEC episode.

    The caller composes one ``AgentSeat`` per LLM seat and one ``LocalSeat`` per
    person, and hands them here with the shared scheduler, store context, and
    episode identity, plus the ``AecEnv`` that adapts the study's turn-based
    environment. The runner owns the loop: each turn it lets the active seat decide,
    steps the one move, and records the turn into every LLM seat's history.
    """

    def __init__(
        self,
        *,
        env: AgentEnv,
        step_env: TurnBasedEnv,
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
        frame_sink: TurnBasedObserver | None = None,
        fps: int = 0,
        max_steps: int = 200,
    ) -> None:
        if not seats:
            raise ValueError("a turn-based agent episode needs at least one LLM seat")
        self._env = env
        self._step_env = step_env
        # An optional per-turn sink the transport wires to push each played turn to a
        # watching participant; the loop stays render-neutral.
        self._frame_sink = frame_sink
        self._channel_key = channel_key
        self._episode_id = episode_id
        self._interaction_id = interaction_id
        self._now = now
        self._fps = fps
        self._max_steps = max_steps
        self._local = tuple(local_seats)

        # The seat order for the summary: the model seats, then the local seats.
        self._agent_ids = tuple(
            [seat.agent_id for seat in seats]
            + [seat.agent_id for seat in self._local]
        )
        if len(set(self._agent_ids)) != len(self._agent_ids):
            raise ValueError("each seat must play a distinct environment agent")

        self._drivers = [
            _TurnSeatDriver(
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
        self._driver_by_agent = {driver.agent_id: driver for driver in self._drivers}

    async def run(self) -> TurnBasedAgentEpisodeResult:
        """Run to the end; return the shared turns and each seat's run."""
        sources: dict[str, SeatActionSource] = {
            driver.agent_id: driver.source for driver in self._drivers
        }
        for seat in self._local:
            sources[seat.agent_id] = seat.source

        summary = await run_turnbased_episode(
            self._step_env,
            channel_key=self._channel_key,
            episode_id=self._episode_id,
            interaction_id=self._interaction_id,
            agent_ids=self._agent_ids,
            sources=sources,
            now=lambda: _instant(self._now()),
            fps=self._fps,
            max_steps=self._max_steps,
            on_turn=self._on_turn,
            on_step=self._on_step,
        )
        for driver in self._drivers:
            driver.finish()
        return TurnBasedAgentEpisodeResult(
            summary=summary,
            seats={driver.agent_id: driver.result for driver in self._drivers},
        )

    def post_message(self, *, sender: str, text: str, tick: int | None = None) -> None:
        """Hand one chat message to every agent seat (the transport calls this)."""
        for driver in self._drivers:
            driver.deliver(Message(sender=sender, text=text, tick=tick))

    async def _on_turn(self, state: TurnState) -> None:
        """Let the active LLM seat decide before the loop reads it.

        A human seat holds its key, so it needs no preparation; an LLM seat awaits
        its model here and applies the action to its held seat, so the loop reads
        the fresh move on this turn.
        """
        driver = self._driver_by_agent.get(state.agent)
        if driver is not None:
            await driver.decide_turn(state.observation)

    async def _on_step(self, info: TurnStepInfo) -> None:
        """Record the turn into every agent seat's history, then push the frame."""
        for driver in self._drivers:
            driver.record(info)
        if self._frame_sink is not None:
            await self._frame_sink(info)


__all__ = [
    "TurnBasedAgentEpisode",
    "TurnBasedAgentEpisodeResult",
]
