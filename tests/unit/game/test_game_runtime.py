"""The environment-neutral stepping loop, over a fake environment and render.

These tests drive the game runtime with no socket, no real clock, and no specific
environment. A fake environment and a fake render function stand in for a study,
so the tests prove the loop is generic: it resolves an action from study bindings,
steps the environment, pushes a render packet per frame, records a normalized
transition per frame, and closes the episode on the environment terminal or the
step cap.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from mug.game.env import EnvFactory, GymEnv, StepResult
from mug.game.runtime import (
    EpisodeSummary,
    InputState,
    RenderPacket,
    resolve_action,
    run_episode,
)
from mug.game.surface import Surface

_EPISODE = "episode_019b6000-0000-7000-8000-00000000000e"
_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000000f"
_BINDINGS = {"Go": 1}


class _FakeEnv:
    """A minimal environment: it counts steps and terminates after five."""

    def __init__(self) -> None:
        self._t = 0

    def reset(self, *, seed: int | None = None) -> tuple[list[float], dict[str, Any]]:
        self._t = 0
        return [0.0], {}

    def step(
        self, action: int
    ) -> tuple[list[float], float, bool, bool, dict[str, Any]]:
        self._t += 1
        return [float(self._t)], -1.0, self._t >= 5, False, {}


def _factory() -> Any:
    return _FakeEnv()


def _env() -> GymEnv:
    return GymEnv(cast("EnvFactory", _factory))


def _render(surface: Surface, state: StepResult) -> None:
    observation = cast("list[float]", state.observation)
    surface.circle(
        x=min(observation[0] / 10, 1.0),
        y=0.5,
        radius=0.02,
        color="#f00",
        object_id="dot",
    )


def _now() -> str:
    return "2026-07-21T00:00:00.000000Z"


def test_resolve_action_uses_the_study_bindings() -> None:
    """A bound key maps to its action; anything else is the study default."""
    assert resolve_action(["Go"], _BINDINGS, 0) == 1
    assert resolve_action(["Other"], _BINDINGS, 0) == 0
    assert resolve_action([], _BINDINGS, 0) == 0


# A study whose jump and direction are different keys: holding both means "jump
# that way", which is its own action and not either key alone.
_CHORDS = {
    "ArrowLeft": 1,
    "ArrowRight": 2,
    "ArrowUp": 3,
    ("ArrowUp", "ArrowLeft"): 4,
    ("ArrowUp", "ArrowRight"): 5,
}


def test_two_keys_held_together_are_their_own_action() -> None:
    """The gap this closes: the legacy runtime bound chords and this did not.

    A game where a player jumps diagonally can not be expressed by "the first
    bound key wins" -- whichever key that was, the other one is thrown away and
    the player never jumps in a direction.
    """
    assert resolve_action(["ArrowUp", "ArrowLeft"], _CHORDS, 0) == 4
    assert resolve_action(["ArrowLeft", "ArrowUp"], _CHORDS, 0) == 4
    assert resolve_action(["ArrowUp", "ArrowRight"], _CHORDS, 0) == 5


def test_a_chord_beats_either_of_the_keys_in_it() -> None:
    """The most specific thing the player is doing is what the seat does.

    Without this the answer would depend on the order the browser reported the
    held keys, so the same two fingers would mean different things on different
    frames.
    """
    assert resolve_action(["ArrowUp"], _CHORDS, 0) == 3
    assert resolve_action(["ArrowLeft"], _CHORDS, 0) == 1
    assert resolve_action(["ArrowUp", "ArrowLeft"], _CHORDS, 0) == 4


def test_a_longer_chord_beats_a_shorter_one() -> None:
    """Three keys held is more specific than two of them, so it wins."""
    bindings = {("a", "b"): 1, ("a", "b", "c"): 2}
    assert resolve_action(["a", "b"], bindings, 0) == 1
    assert resolve_action(["a", "b", "c"], bindings, 0) == 2


def test_a_chord_that_is_not_fully_held_does_not_fire() -> None:
    """Every key in a chord must be down, or it is not that chord."""
    assert resolve_action(["ArrowUp"], {("ArrowUp", "ArrowLeft"): 4}, 0) == 0
    assert resolve_action(["ArrowLeft"], {("ArrowUp", "ArrowLeft"): 4}, 0) == 0


def test_a_study_with_no_chords_resolves_exactly_as_it_always_did() -> None:
    """The rule is added, not changed: nothing an old study did moves."""
    assert resolve_action(["Go", "Other"], _BINDINGS, 7) == 1
    assert resolve_action(["Other", "Go"], _BINDINGS, 7) == 1
    assert resolve_action(["Nothing"], _BINDINGS, 7) == 7


def test_the_adapter_resets_and_steps_any_environment() -> None:
    """The adapter returns a json-able observation and a per-step reward."""
    env = _env()
    start = env.reset()
    assert start.observation == [0.0]
    result = env.step(1)
    assert result.observation == [1.0]
    assert result.reward == -1.0


async def test_the_loop_steps_pushes_renders_and_closes_the_episode() -> None:
    """A capped episode pushes a keyframe plus one render per frame, then closes."""
    frames: list[RenderPacket] = []

    async def sink(packet: RenderPacket) -> None:
        frames.append(packet)

    inputs = InputState(_BINDINGS, 0)
    inputs.press(["Go"])

    summary = await run_episode(
        _env(),
        render=_render,
        channel_key="fake-game",
        episode_id=_EPISODE,
        interaction_id=_INTERACTION,
        seat_key="player",
        input_state=inputs,
        sink=sink,
        now=_now,
        fps=0,
        max_steps=3,
    )

    assert isinstance(summary, EpisodeSummary)
    assert summary.frames == 3
    assert len(summary.transitions) == 3
    assert not summary.solved
    assert len(frames) == 4
    assert frames[0].keyframe is True
    assert frames[-1].frame_number == 3
    assert any(command.id == "dot" for command in frames[-1].commands)


async def test_the_loop_holds_a_countdown_before_the_first_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-roll pauses after the keyframe, before any step or transition."""
    import mug.game.runtime as runtime_module

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(runtime_module.asyncio, "sleep", _fake_sleep)

    frames: list[int] = []

    async def sink(packet: RenderPacket) -> None:
        frames.append(packet.frame_number)

    summary = await run_episode(
        _env(),
        render=_render,
        channel_key="fake-game",
        episode_id=_EPISODE,
        interaction_id=_INTERACTION,
        seat_key="player",
        input_state=InputState(_BINDINGS, 0),
        sink=sink,
        now=_now,
        fps=0,
        max_steps=3,
        countdown_seconds=2,
    )

    # With no per-frame delay, the only pause is the pre-roll, and it comes first.
    assert sleeps == [2]
    assert frames[0] == 0
    assert summary.frames == 3


async def test_the_loop_stops_on_the_environment_terminal() -> None:
    """The loop ends when the environment terminates, and records the boundary."""

    async def sink(_packet: RenderPacket) -> None:
        return None

    inputs = InputState(_BINDINGS, 0)
    summary = await run_episode(
        _env(),
        render=_render,
        channel_key="fake-game",
        episode_id=_EPISODE,
        interaction_id=_INTERACTION,
        seat_key="player",
        input_state=inputs,
        sink=sink,
        now=_now,
        fps=0,
        max_steps=50,
    )

    assert summary.solved
    assert summary.frames == 5
    assert summary.boundary.end_frame_exclusive == 5
    transition = summary.transitions[0]
    assert transition.authority == "server"
    assert transition.channel_key == "fake-game"
    assert transition.applied_decisions == []


async def test_the_facade_records_the_same_frames_as_the_shared_loop() -> None:
    """``run_episode`` is the one-seat case of ``run_multiseat_episode``.

    Driving the single-seat facade and the multi-seat loop with the same lifted
    env, seat, and clock yields byte-identical transitions and boundary, so the
    facade truly runs the one shared loop rather than a parallel implementation.
    """
    from mug.game.multiseat import run_multiseat_episode, solo_env

    async def sink(_packet: RenderPacket) -> None:
        return None

    facade = await run_episode(
        _env(),
        render=_render,
        channel_key="fake-game",
        episode_id=_EPISODE,
        interaction_id=_INTERACTION,
        seat_key="player",
        input_state=InputState(_BINDINGS, 1),
        sink=sink,
        now=_now,
        fps=0,
        max_steps=50,
    )
    shared = await run_multiseat_episode(
        solo_env(_env(), "player"),
        channel_key="fake-game",
        episode_id=_EPISODE,
        interaction_id=_INTERACTION,
        agent_ids=["player"],
        sources={"player": InputState(_BINDINGS, 1)},
        now=_now,
        fps=0,
        max_steps=50,
    )

    assert [t.action_digest for t in facade.transitions] == [
        t.action_digest for t in shared.transitions
    ]
    assert [t.state_digest for t in facade.transitions] == [
        t.state_digest for t in shared.transitions
    ]
    assert facade.boundary.state_hash == shared.boundary.state_hash
