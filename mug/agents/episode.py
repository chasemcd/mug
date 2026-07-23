"""Run one full episode with a single LLM seat: the one-seat case of many.

A single-seat agent run is the one-actor case of a multi-seat one, so this runner
is a thin facade over ``MultiAgentEpisode``: it wires one ``AgentSeat``, lifts the
study's single-seat environment into the multi-seat stepping seam
(``mug.game.multiseat.solo_env``), and adapts the shared result back to the
single-seat shape a one-bot caller expects. There is one stepping loop and one
agent runtime under both; this class only keeps the simple constructor for the
common one-bot case.

The runner is server execution only. It steps a single environment that both the
loop drives and the controller reads, so the model sees the same live state the
loop just produced.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from mug.agents.multiseat_episode import (
    AgentSeat,
    MultiAgentEpisode,
    TextView,
)
from mug.agents.runtime import LLMController
from mug.authoring import History, LLMAgent, Thoughts
from mug.game.controllers import ScheduledSeat
from mug.game.multiseat import MultiSeatSummary, solo_env
from mug.game.runtime import EpisodeSummary, SteppableEnv
from mug.providers import ModelCallResult
from mug.scheduling import Scheduler
from mug.scheduling.runtime import DecisionOutcome, NewContext

# How long a decision has to return before the seat falls back, in seconds.
DecisionTimeout = float


@dataclass(frozen=True)
class AgentEpisodeResult:
    """What one agent episode produced: the frames, the decisions, the transcript.

    ``summary`` is the loop's own result (transitions and the closing boundary).
    ``decisions`` is one outcome per decision the runner drove, in order.
    ``model_calls`` is every model call the seat made, in call order, so a caller one
    layer up builds the API-16 decision tape for a replay bundle
    (``mug.replay.build_decision_tape``). ``history`` and ``thoughts`` are the
    transcript the model built up -- the steps it saw and the reasoning it carried
    forward -- so a caller can inspect or capture the run.
    """

    summary: EpisodeSummary
    decisions: list[DecisionOutcome]
    model_calls: list[ModelCallResult]
    history: History
    thoughts: Thoughts


class AgentEpisode:
    """Drive one LLM seat through a full episode: the one-seat multi-seat case.

    The caller composes the parts a study composes -- the agent definition, the
    controller that wraps the provider, the scheduler, and the held-action seat --
    and hands them here. The facade builds the one-seat ``MultiAgentEpisode`` over
    them, so a solo run and a many-seat run share one loop and one runtime.
    """

    def __init__(
        self,
        *,
        agent: LLMAgent,
        controller: LLMController,
        scheduler: Scheduler,
        seat: ScheduledSeat,
        env: SteppableEnv,
        agent_id: str,
        actor_id: str,
        channel_key: str,
        episode_id: str,
        interaction_id: str,
        seat_key: str,
        episode_generation: int,
        new_context: NewContext,
        new_decision_id: Callable[[], str],
        now: Callable[[], datetime],
        decision_timeout: DecisionTimeout,
        text_view: TextView | None = None,
        fps: int = 0,
        max_steps: int = 200,
    ) -> None:
        self._agent_id = agent_id
        self._seat_key = seat_key
        self._controller = controller
        self._inner = MultiAgentEpisode(
            env=env,
            step_env=solo_env(env, agent_id),
            seats=[
                AgentSeat(
                    seat_key=seat_key,
                    agent_id=agent_id,
                    actor_id=actor_id,
                    agent=agent,
                    controller=controller,
                    seat=seat,
                    text_view=text_view,
                )
            ],
            scheduler=scheduler,
            channel_key=channel_key,
            episode_id=episode_id,
            interaction_id=interaction_id,
            episode_generation=episode_generation,
            new_context=new_context,
            new_decision_id=new_decision_id,
            now=now,
            decision_timeout=decision_timeout,
            fps=fps,
            max_steps=max_steps,
        )

    async def run(self) -> AgentEpisodeResult:
        """Run the episode to its end and return the frames, decisions, transcript."""
        result = await self._inner.run()
        seat = result.seats[self._agent_id]
        return AgentEpisodeResult(
            summary=_single_summary(result.summary, self._seat_key),
            decisions=seat.decisions,
            model_calls=seat.model_calls,
            history=self._controller.history,
            thoughts=self._controller.thoughts,
        )

    def post_message(self, *, sender: str, text: str, tick: int | None = None) -> None:
        """Hand one chat message to the agent (the transport calls this).

        The message joins the chat the model reads next decision, so a human
        partner can instruct the agent on strategy between frames.
        """
        self._inner.post_message(sender=sender, text=text, tick=tick)


def _single_summary(summary: MultiSeatSummary, seat_key: str) -> EpisodeSummary:
    """Adapt the shared multi-seat summary to the single-seat shape."""
    return EpisodeSummary(
        channel_key=summary.channel_key,
        seat_key=seat_key,
        frames=summary.frames,
        transitions=summary.transitions,
        boundary=summary.boundary,
        solved=summary.solved,
    )


__all__ = [
    "AgentEpisode",
    "AgentEpisodeResult",
]
