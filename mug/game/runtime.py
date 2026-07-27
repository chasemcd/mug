"""The single-seat facade over the shared stepping loop.

A single-seat run is the one-agent case of a multi-seat one, so this module is a
thin facade over the core loop (``mug.game.multiseat.run_multiseat_episode``): it
lifts the study's single-seat environment into the multi-seat stepping seam
(``solo_env``), drives the one seat, and adds the human-watching render path the
core loop leaves to the transport. There is one stepping loop and one recorded
transition timeline under both a solo run and a many-seat run.

The facade stays environment-neutral and transport-neutral. The study supplies the
environment, the key bindings, and the drawing (a ``render`` function); the facade
reads the current action from an ``InputState`` the transport updates from input
frames, and it pushes each render packet to a ``sink`` the transport wires to the
seat. It draws the opening keyframe and holds the pre-roll before the first step
through the core loop's ``on_start`` hook, and it draws each frame through the
``on_step`` hook, so the render path stays here while the stepping stays in the one
loop. A test drives it with a scripted input and a collecting sink, with no real
clock and no socket.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import NamedTuple

from mug.game.env import GymEnv, StepResult
from mug.game.multiseat import (
    MultiSeatStepInfo,
    MultiStepResult,
    run_multiseat_episode,
    solo_env,
)
from mug.game.seams import Clock, SeatActionSource, SteppableEnv
from mug.game.spec import RenderFn
from mug.game.surface import Surface
from mug.game.trajectory import TrajectoryFrame
from mug.game.types import EpisodeBoundary, GameTransition, RenderPacket
from mug.kernel import compute_digest

RenderSink = Callable[[RenderPacket], Awaitable[None]]


def resolve_action(keys: list[str], bindings: dict[str, int], default: int) -> int:
    """Map the currently pressed keys to one action (first bound key wins)."""
    for key in keys:
        if key in bindings:
            return bindings[key]
    return default


class StepInfo(NamedTuple):
    """One stepped frame handed to an ``on_step`` observer: frame, action, state.

    The observer runs after the transition is recorded and the render is pushed, so
    it sees the frame the loop just produced. An LLM runtime uses it to record the
    step into the agent's history and to trigger a decision at its cadence.
    """

    frame: int
    action: int
    state: StepResult


# An optional per-frame observer the loop awaits after each step. It adds no
# authority -- it observes the frame the loop produced and never changes it.
StepObserver = Callable[[StepInfo], Awaitable[None]]


class InputState:
    """The latest pressed keys for one seat; the loop reads its action.

    The study's key bindings and no-input default fix how keys become an action.
    """

    def __init__(self, bindings: dict[str, int], default_action: int) -> None:
        self._bindings = bindings
        self._default = default_action
        self._keys: list[str] = []

    def press(self, keys: list[str]) -> None:
        """Record the keys the seat currently holds down."""
        self._keys = keys

    def action(self) -> int:
        """Return the action the current key set maps to."""
        return resolve_action(self._keys, self._bindings, self._default)

    def decide(self, observation: object) -> int:
        """Return the seat's action; a human decides from keys, not observation.

        The observation is unused: a human seat maps its held keys. The method
        exists so the loop reads a person and a controller through the one seam.
        """
        return self.action()


class EpisodeSummary(NamedTuple):
    """The result of one episode: its channel, seat, transitions, and outcome.

    The summary is self-describing, so the capture step needs no side channel:
    it carries the channel key and seat key the run used, the transition per
    frame, the closing boundary, and whether the environment terminated.
    """

    channel_key: str
    seat_key: str
    frames: int
    transitions: list[GameTransition]
    boundary: EpisodeBoundary
    solved: bool
    trajectory: Sequence[TrajectoryFrame] = ()


def _render_packet(
    surface: Surface,
    render: RenderFn,
    state: StepResult,
    episode_id: str,
    seat_key: str,
    frame: int,
) -> RenderPacket:
    """Draw one frame onto the episode's surface and pack what changed.

    The surface lives for the whole episode, which is what the object model needs:
    a persistent object is sent when it is introduced and again when it changes,
    and a frame that removed one is sent whole. The surface itself decides which
    this frame is, so nothing here has to be told when a scene is complete.
    """
    surface.clear()
    render(surface, state)
    commands, keyframe = surface.frame()
    digest = compute_digest(
        [command.model_dump(mode="json", exclude_none=True) for command in commands]
    )
    return RenderPacket(
        episode_id=episode_id,
        seat_key=seat_key,
        frame_number=frame,
        render_digest=digest,
        keyframe=keyframe,
        commands=commands,
    )


def _solo_state(result: MultiStepResult, seat_key: str) -> StepResult:
    """Rebuild the one seat's step result from a multi-seat frame.

    The facade lifts the study env into the multi-seat seam, so each frame arrives
    keyed by the sole seat. The render function and the ``on_step`` observer both
    read a single-seat ``StepResult``, so this unwraps the one seat's slice back
    into that shape.
    """
    return StepResult(
        result.observations[seat_key],
        result.rewards[seat_key],
        result.terminated,
        result.truncated,
    )


async def run_episode(
    env: SteppableEnv,
    *,
    render: RenderFn,
    channel_key: str,
    episode_id: str,
    interaction_id: str,
    seat_key: str,
    input_state: SeatActionSource,
    sink: RenderSink,
    now: Clock,
    fps: int = 30,
    max_steps: int = 200,
    countdown_seconds: int = 0,
    on_step: StepObserver | None = None,
) -> EpisodeSummary:
    """Run one single-seat episode: the one-agent case of the shared loop.

    The facade lifts the study env into the multi-seat stepping seam and drives the
    one seat through ``run_multiseat_episode``, so a solo run and a many-seat run
    share one loop and one recorded transition timeline. It adds the human-watching
    render path the core loop leaves to the transport.

    It pushes the initial keyframe, then holds for ``countdown_seconds`` before the
    first step (both through the loop's ``on_start`` hook), so the episode does not
    advance while the participant is still settling in after continuing. The seat
    sees the initial state during the pre-roll; no frame is stepped and no
    transition is recorded until it ends.

    An optional ``on_step`` observer runs after each frame's render, with the frame
    number, the applied action, and the new state. It observes only -- the loop's
    authority over the action and the state is unchanged -- so a runtime can record
    the frame into an agent's history and trigger a decision without altering the
    step.
    """

    # One surface for the whole episode: the seat keeps its persistent objects
    # between frames, so each frame ships what changed rather than everything.
    surface = Surface()

    async def on_start(result: MultiStepResult) -> None:
        state = _solo_state(result, seat_key)
        await sink(_render_packet(surface, render, state, episode_id, seat_key, 0))
        if countdown_seconds > 0:
            await asyncio.sleep(countdown_seconds)

    async def observe(info: MultiSeatStepInfo) -> None:
        state = _solo_state(info.result, seat_key)
        await sink(
            _render_packet(surface, render, state, episode_id, seat_key, info.frame)
        )
        if on_step is not None:
            await on_step(StepInfo(info.frame, info.actions[seat_key], state))

    summary = await run_multiseat_episode(
        solo_env(env, seat_key),
        channel_key=channel_key,
        episode_id=episode_id,
        interaction_id=interaction_id,
        agent_ids=[seat_key],
        sources={seat_key: input_state},
        now=now,
        fps=fps,
        max_steps=max_steps,
        on_start=on_start,
        on_step=observe,
    )
    return EpisodeSummary(
        channel_key,
        seat_key,
        summary.frames,
        summary.transitions,
        summary.boundary,
        summary.solved,
        summary.trajectory,
    )


__all__ = [
    "EpisodeSummary",
    "GymEnv",
    "InputState",
    "RenderSink",
    "SeatActionSource",
    "StepInfo",
    "StepObserver",
    "SteppableEnv",
    "resolve_action",
    "run_episode",
]
