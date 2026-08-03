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
from mug.game.keys import Bindings, chord_of, single_keys
from mug.game.multiseat import (
    MultiSeatStepInfo,
    MultiStepResult,
    run_multiseat_episode,
    solo_env,
)
from mug.game.seams import Clock, SeatActionSource, SteppableEnv
from mug.game.spec import HudFn, RenderFn
from mug.game.surface import Surface
from mug.game.trajectory import TrajectoryFrame
from mug.game.types import EpisodeBoundary, GameTransition, RenderPacket
from mug.kernel import compute_digest

RenderSink = Callable[[RenderPacket], Awaitable[None]]


def resolve_action(keys: list[str], bindings: Bindings, default: int) -> int:
    """Map the currently pressed keys to one action.

    A binding written as a **sequence of keys** is a chord: every key in it must be
    held down together. A game where a jump and a direction are different keys
    needs this -- a player who holds both means "jump that way", which is not the
    same action as either key alone.

    A chord always beats a single key, and a longer chord beats a shorter one, so
    the most specific thing the player is doing is what the seat does. Among
    equally specific bindings the first held key wins, which is what a study with
    no chords at all has always got.
    """
    held = set(keys)
    best: tuple[int, int] | None = None
    for binding, action in bindings.items():
        parts = chord_of(binding)
        if len(parts) < 2 or not all(part in held for part in parts):
            continue
        if best is None or len(parts) > best[0]:
            best = (len(parts), action)
    if best is not None:
        return best[1]
    singles = single_keys(bindings)
    for key in keys:
        if key in singles:
            return singles[key]
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


# How many taps are held for a participant who presses faster than the game steps.
# Some buffer is what makes a quick double tap two moves rather than one; an
# unbounded one would let a held-down key that repeats, or a moment of panic at the
# end of a round, play out for seconds after the participant stopped.
_TAPS_HELD = 8


class InputState:
    """The latest pressed keys for one seat; the loop reads its action.

    The study's key bindings and no-input default fix how keys become an action.
    **How long a press lasts is the study's own decision**, and the two answers are
    different tasks rather than different settings (API-09 ``InputScheme.mode``):

    - ``pressed_keys`` -- a key that is held down acts on **every** frame while it
      is held. This is what a game of continuous control needs: a slime holding
      left is moving left, and letting go is the thing that stops it.
    - ``single_keystroke`` -- each press is **one** action, however long the key is
      held. This is what a game on a grid needs: one tap of the pick-up key picks
      one thing up. Held down at thirty frames a second it would pick a dish up and
      put it down fifteen times, and a tap of an arrow would cross the room.

    A press is counted when the key **arrives**, so a chord still works: pressing up
    while left is held resolves the pair, exactly as the held case would.
    """

    def __init__(
        self,
        bindings: Bindings,
        default_action: int,
        *,
        mode: str = "pressed_keys",
    ) -> None:
        self._bindings = bindings
        self._default = default_action
        self._mode = mode
        self._keys: list[str] = []
        self._held: set[str] = set()
        # The actions of presses that have arrived and not yet been played.
        self._taps: list[int] = []

    def press(self, keys: list[str]) -> None:
        """Record the keys the seat currently holds down.

        In single-keystroke mode this is also where a press is **counted**: a key
        in this set that was not in the last one has just been pressed, and it is
        worth exactly one action whenever the loop next asks.
        """
        arrived = [key for key in keys if key not in self._held]
        self._held = set(keys)
        self._keys = keys
        if arrived and self._mode == "single_keystroke":
            action = self._tap(arrived, keys)
            if action is not None and len(self._taps) < _TAPS_HELD:
                self._taps.append(action)

    def _tap(self, arrived: list[str], held: list[str]) -> int | None:
        """Return what one press is worth, or nothing when it is bound to nothing.

        The press is the key that **arrived**, not the first key that happens to be
        down: a participant holding an arrow and then tapping the pick-up key means
        one move and one pick-up. A chord still wins when the arrival completes one,
        which is what makes "up while left is held" the diagonal rather than the up.
        """
        down = set(held)
        new = set(arrived)
        best: tuple[int, int] | None = None
        for binding, action in self._bindings.items():
            parts = chord_of(binding)
            if len(parts) < 2 or not all(part in down for part in parts):
                continue
            if not any(part in new for part in parts):
                continue
            if best is None or len(parts) > best[0]:
                best = (len(parts), action)
        if best is not None:
            return best[1]
        singles = single_keys(self._bindings)
        for key in arrived:
            if key in singles:
                return singles[key]
        return None

    def action(self) -> int:
        """Return the action for this frame, as the study's input mode reads it."""
        if self._mode == "single_keystroke":
            return self._taps.pop(0) if self._taps else self._default
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


# Where the status line sits, and what it is drawn in. It is a band across the top
# of the surface, because that is where a person looks for a score and because the
# alternative -- shrinking the game to make room -- would change every drawing a
# study already wrote.
_HUD_HEIGHT = 0.085
_HUD_BACKGROUND = "#101418"
_HUD_COLOR = "#f5f7fa"
_HUD_FONT = 15


def draw_hud(surface: Surface, text: str) -> None:
    """Draw one line of status across the top of the surface.

    The band is drawn opaque, so the line is legible over whatever the study drew
    under it. It is persistent, so it travels once and then only when the words
    change -- a score that stays the same costs nothing to keep on the screen.
    """
    surface.rect(
        x=0.0,
        y=0.0,
        w=1.0,
        h=_HUD_HEIGHT,
        color=_HUD_BACKGROUND,
        object_id="mug-hud-band",
        persistent=True,
        depth=100,
    )
    surface.text(
        x=0.015,
        y=_HUD_HEIGHT * 0.72,
        text=text,
        color=_HUD_COLOR,
        font_size=_HUD_FONT,
        object_id="mug-hud-text",
        persistent=True,
        depth=101,
    )


def render_packet(
    surface: Surface,
    render: RenderFn,
    state: StepResult,
    episode_id: str,
    seat_key: str,
    frame: int,
    hud: HudFn | None = None,
) -> RenderPacket:
    """Draw one frame onto the episode's surface and pack what changed.

    The surface lives for the whole episode, which is what the object model needs:
    a persistent object is sent when it is introduced and again when it changes,
    and a frame that removed one is sent whole. The surface itself decides which
    this frame is, so nothing here has to be told when a scene is complete.

    The study's status line is drawn last and above everything, so a drawing can
    not paint over what the participant is being told.
    """
    surface.clear()
    render(surface, state)
    if hud is not None:
        draw_hud(surface, str(hud(state)))
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


def watched_state(result: MultiStepResult, seat_key: str) -> StepResult:
    """Return one shared frame in the shape a drawing reads, for somebody watching.

    Several people at one table watch one board, and each of them draws it with the
    study's one drawing. A watcher who plays a seat sees that seat's own
    observation; a watcher with no seat -- somebody reading along while the models
    play -- is given the whole set, because there is no one seat that is theirs. The
    frame's own metrics travel either way, and that is what a drawing of the whole
    board reads.
    """
    return StepResult(
        result.observations.get(seat_key, result.observations),
        result.rewards.get(seat_key, 0.0),
        result.terminated,
        result.truncated,
        result.info,
    )


def _solo_state(result: MultiStepResult, seat_key: str) -> StepResult:
    """Rebuild the one seat's step result from a multi-seat frame.

    The facade lifts the study env into the multi-seat seam, so each frame arrives
    keyed by the sole seat. The render function and the ``on_step`` observer both
    read a single-seat ``StepResult``, so this unwraps the one seat's slice back
    into that shape.

    The frame's own metrics travel with it. A drawing that needs more than the
    observation -- a grid of things, a court, a scoreboard -- reads them there, and
    an environment that stated them once had them dropped before anybody could.
    """
    return StepResult(
        result.observations[seat_key],
        result.rewards[seat_key],
        result.terminated,
        result.truncated,
        result.info,
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
    hud: HudFn | None = None,
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
        await sink(render_packet(surface, render, state, episode_id, seat_key, 0, hud))
        if countdown_seconds > 0:
            await asyncio.sleep(countdown_seconds)

    async def observe(info: MultiSeatStepInfo) -> None:
        state = _solo_state(info.result, seat_key)
        await sink(
            render_packet(surface, render, state, episode_id, seat_key, info.frame, hud)
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
    "Bindings",
    "EpisodeSummary",
    "GymEnv",
    "InputState",
    "RenderSink",
    "SeatActionSource",
    "StepInfo",
    "StepObserver",
    "SteppableEnv",
    "chord_of",
    "draw_hud",
    "render_packet",
    "resolve_action",
    "run_episode",
    "watched_state",
]
