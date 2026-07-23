"""The server-authoritative stepping loop for a multi-seat environment.

The single-seat loop (``mug.game.runtime.run_episode``) steps one action per
frame and reads one seat. This loop steps a *multi-agent* environment: each frame
it reads every seat's next action, steps the whole action set at once, and records
one shared ``GameTransition``. So two or more seats -- a human beside an LLM, or two
agents -- drive one shared environment on one authoritative timeline.

The loop stays environment-neutral and transport-neutral, the same as the
single-seat loop. The study supplies the environment behind the ``MultiSeatEnv``
seam (reset, and step one action set). Each seat's action comes from a
``SeatActionSource``: a human seat maps its held keys (its ``InputState``), an LLM
seat holds the latest decided action (its ``ScheduledSeat``), and both satisfy the
one seam, so the loop reads a person and a model the same way. A frame with a slow
model never blocks, because the seat holds an action while the model decides off
the frame clock.

The loop draws no surface itself. A two-agent interaction needs none, and a human
seat's view is the transport's concern: it wires the optional ``on_step`` observer
to push each seat its frame. So this loop owns only the shared stepping and the
recorded transition timeline; the human-watching render path stays with the
transport. A test drives the whole episode with scripted seat sources and a
collecting observer, with no socket and no real clock.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, NamedTuple, Protocol

from mug.game.env import StepResult
from mug.game.seams import Clock, SeatActionSource, SteppableEnv
from mug.game.types import EpisodeBoundary, GameTransition
from mug.kernel import compute_digest


class MultiStepResult(NamedTuple):
    """The outcome of one multi-seat step: per-seat observations, rewards, flags.

    ``observations`` and ``rewards`` are keyed by the environment's agent id. The
    terminal and truncation flags are episode-level: the loop ends when the whole
    episode ends, so every seat's timeline closes on the same frame.
    """

    observations: dict[str, Any]
    rewards: dict[str, float]
    terminated: bool
    truncated: bool


class MultiSeatEnv(Protocol):
    """The minimal multi-agent environment the loop steps: reset and step a set.

    ``step`` takes one action per active agent, keyed by agent id, and returns the
    whole result. A study's PettingZoo-parallel environment satisfies this seam
    behind a small wrapper; the loop names no environment itself.
    """

    def reset(self) -> MultiStepResult: ...
    def step(self, actions: Mapping[str, int]) -> MultiStepResult: ...


class MultiSeatStepInfo(NamedTuple):
    """One stepped frame handed to an ``on_step`` observer: frame, actions, result.

    The observer runs after the transition is recorded, so it sees the frame the
    loop just produced. The multi-seat LLM runtime uses it to record the step into
    each agent's history and to fire each seat's decision at its own cadence.
    """

    frame: int
    actions: dict[str, int]
    result: MultiStepResult


# An optional per-frame observer the loop awaits after each step. It adds no
# authority -- it observes the frame the loop produced and never changes it.
MultiSeatObserver = Callable[[MultiSeatStepInfo], Awaitable[None]]

# An optional observer the loop awaits once, after the reset and before the first
# step, with the reset result. A render transport uses it to push the initial
# keyframe and to hold a pre-roll (a countdown) before the episode advances, so the
# loop stays render-neutral yet a facade can still draw the opening frame.
MultiSeatStart = Callable[["MultiStepResult"], Awaitable[None]]


class MultiSeatSummary(NamedTuple):
    """The result of one multi-seat episode: the shared transitions and outcome.

    Unlike the single-seat summary, one multi-seat episode holds many seats on one
    timeline, so the summary names every seat and carries the one shared transition
    per frame and the closing boundary.
    """

    channel_key: str
    seat_keys: tuple[str, ...]
    frames: int
    transitions: list[GameTransition]
    boundary: EpisodeBoundary
    solved: bool


def _transition(
    actions: Mapping[str, int],
    result: MultiStepResult,
    *,
    episode_id: str,
    interaction_id: str,
    channel_key: str,
    frame: int,
    now: Clock,
) -> GameTransition:
    """Build the shared server transition for one multi-seat frame.

    The action digest commits to the whole action set, and the state digest to the
    whole per-seat observation set, so one transition records the frame every seat
    stepped. ``applied_decisions`` stays empty, as the single-seat loop does: the
    per-seat decisions are recorded on their own decision streams, and the runtime
    keeps the decision outcomes beside the summary.
    """
    return GameTransition(
        interaction_id=interaction_id,
        channel_key=channel_key,
        episode_id=episode_id,
        frame_number=frame,
        action_digest=compute_digest(dict(actions)),
        state_digest=compute_digest(result.observations),
        authority="server",
        applied_decisions=[],
        recorded_at=now(),
    )


def _boundary(
    result: MultiStepResult, *, episode_id: str, interaction_id: str, frame: int
) -> EpisodeBoundary:
    """Close the multi-seat episode on the shared final state."""
    return EpisodeBoundary(
        episode_id=episode_id,
        interaction_id=interaction_id,
        kind="terminal",
        end_frame_exclusive=frame,
        authority="server",
        state_hash=compute_digest(result.observations),
    )


async def run_multiseat_episode(
    env: MultiSeatEnv,
    *,
    channel_key: str,
    episode_id: str,
    interaction_id: str,
    agent_ids: Sequence[str],
    sources: Mapping[str, SeatActionSource],
    now: Clock,
    fps: int = 30,
    max_steps: int = 200,
    on_start: MultiSeatStart | None = None,
    on_step: MultiSeatObserver | None = None,
) -> MultiSeatSummary:
    """Run one multi-seat episode: step every seat's action set, record the frames.

    Each frame the loop reads every seat's next action through the shared
    ``SeatActionSource`` seam, steps the whole action set at once, records one
    shared ``GameTransition``, and runs the optional ``on_step`` observer. It ends
    on the environment terminal or on the step cap, and closes the episode with an
    ``EpisodeBoundary``. The server owns the authority: a seat supplies an action,
    never a state.

    The optional ``on_start`` observer runs once, after the reset and before the
    first step, with the reset result. A render facade uses it to push the opening
    keyframe and to hold a pre-roll before the episode advances; the loop itself
    draws nothing, so it stays render-neutral.
    """
    result = env.reset()
    if on_start is not None:
        await on_start(result)
    transitions: list[GameTransition] = []
    frame = 0
    solved = False
    while frame < max_steps:
        actions = {
            agent_id: int(sources[agent_id].decide(result.observations.get(agent_id)))
            for agent_id in agent_ids
        }
        result = env.step(actions)
        frame += 1
        transitions.append(
            _transition(
                actions,
                result,
                episode_id=episode_id,
                interaction_id=interaction_id,
                channel_key=channel_key,
                frame=frame,
                now=now,
            )
        )
        if on_step is not None:
            await on_step(MultiSeatStepInfo(frame, actions, result))
        if result.terminated:
            solved = True
            break
        if result.truncated:
            break
        if fps > 0:
            await asyncio.sleep(1 / fps)

    boundary = _boundary(
        result, episode_id=episode_id, interaction_id=interaction_id, frame=frame
    )
    return MultiSeatSummary(
        channel_key, tuple(agent_ids), frame, transitions, boundary, solved
    )


class _SoloEnv:
    """Lift a single-seat ``SteppableEnv`` into the multi-seat seam for one agent.

    A single-seat environment is the one-agent case of a multi-seat one. This
    wrapper keys the single action, observation, and reward under one agent id, so
    the one multi-seat loop steps a solo environment with no special case. It
    forwards to the same underlying environment the controller reads, so the model
    still sees the live state the loop just produced.
    """

    def __init__(self, env: SteppableEnv, agent_id: str) -> None:
        self._env = env
        self._agent_id = agent_id

    def reset(self) -> MultiStepResult:
        """Reset the underlying environment and key its result under the agent."""
        return self._lift(self._env.reset())

    def step(self, actions: Mapping[str, int]) -> MultiStepResult:
        """Step the underlying environment on this agent's action alone."""
        return self._lift(self._env.step(int(actions[self._agent_id])))

    def _lift(self, result: StepResult) -> MultiStepResult:
        """Key one single-seat step result under the sole agent id."""
        return MultiStepResult(
            observations={self._agent_id: result.observation},
            rewards={self._agent_id: result.reward},
            terminated=result.terminated,
            truncated=result.truncated,
        )


def solo_env(env: SteppableEnv, agent_id: str) -> MultiSeatEnv:
    """Return a single-seat environment lifted into the multi-seat seam.

    So the one multi-seat loop drives a solo run as the one-agent case, with no
    separate single-seat loop.
    """
    return _SoloEnv(env, agent_id)


__all__ = [
    "MultiSeatEnv",
    "MultiSeatObserver",
    "MultiSeatStart",
    "MultiSeatStepInfo",
    "MultiSeatSummary",
    "MultiStepResult",
    "run_multiseat_episode",
    "solo_env",
]
