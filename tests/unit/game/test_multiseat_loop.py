"""The multi-seat loop steps every seat's action set on one shared timeline.

These tests drive ``mug.game.multiseat.run_multiseat_episode`` with scripted seat
sources and a collecting observer, with no socket and no real clock. They prove the
loop reads every seat each frame, steps the whole action set at once, records one
shared transition per frame, and closes the episode on the shared terminal. They
also prove the ``solo_env`` lift makes a single-seat environment the one-agent case
of the same loop.
"""

from __future__ import annotations

from collections.abc import Mapping

from mug.game.env import StepResult
from mug.game.multiseat import (
    MultiSeatStepInfo,
    MultiStepResult,
    run_multiseat_episode,
    solo_env,
)


class _PairEnv:
    """A tiny two-seat env: it steps a shared counter and ends after ``steps``.

    It records the action set it stepped each frame, so a test reads what the loop
    supplied per seat, and it reports a per-seat observation and reward.
    """

    def __init__(self, *, agents: tuple[str, ...], steps: int = 4) -> None:
        self._agents = agents
        self._t = 0
        self._max = steps
        self.stepped: list[dict[str, int]] = []

    def reset(self) -> MultiStepResult:
        self._t = 0
        self.stepped = []
        return self._result()

    def step(self, actions: Mapping[str, int]) -> MultiStepResult:
        self.stepped.append(dict(actions))
        self._t += 1
        return self._result()

    def _result(self) -> MultiStepResult:
        terminated = self._t >= self._max
        return MultiStepResult(
            observations={a: [float(self._t)] for a in self._agents},
            rewards={a: 1.0 if terminated else 0.0 for a in self._agents},
            terminated=terminated,
            truncated=False,
        )


class _Fixed:
    """A seat source that always supplies one action, ignoring the observation."""

    def __init__(self, action: int) -> None:
        self._action = action

    def decide(self, observation: object) -> int:
        return self._action


class _SoloCounter:
    """A single-seat env for the ``solo_env`` lift: a counter that ends at ``steps``."""

    def __init__(self, *, steps: int = 3) -> None:
        self._t = 0
        self._max = steps
        self.actions: list[int] = []

    def reset(self) -> StepResult:
        self._t = 0
        self.actions = []
        return StepResult([0.0], 0.0, False, False)

    def step(self, action: int) -> StepResult:
        self.actions.append(int(action))
        self._t += 1
        terminated = self._t >= self._max
        return StepResult(
            [float(self._t)], 1.0 if terminated else 0.0, terminated, False
        )


async def test_the_loop_steps_every_seat_each_frame() -> None:
    """Both seats' actions reach the env in one step, on one shared timeline."""
    env = _PairEnv(agents=("chef-1", "chef-2"), steps=4)
    seen: list[MultiSeatStepInfo] = []

    async def collect(info: MultiSeatStepInfo) -> None:
        seen.append(info)

    summary = await run_multiseat_episode(
        env,
        channel_key="kitchen",
        episode_id="episode_019b6000-0000-7000-8000-000000000001",
        interaction_id="interaction_019b6000-0000-7000-8000-000000000002",
        agent_ids=["chef-1", "chef-2"],
        sources={"chef-1": _Fixed(1), "chef-2": _Fixed(2)},
        now=lambda: "2026-07-22T00:00:00.000000Z",
        fps=0,
        on_step=collect,
    )

    # The episode ran to the shared terminal, one transition per frame.
    assert summary.frames == 4
    assert summary.solved is True
    assert summary.seat_keys == ("chef-1", "chef-2")
    assert len(summary.transitions) == 4
    # Every frame stepped both seats' scripted actions at once.
    assert env.stepped == [{"chef-1": 1, "chef-2": 2}] * 4
    # The observer saw each frame's whole action set.
    assert [info.actions for info in seen] == [{"chef-1": 1, "chef-2": 2}] * 4


async def test_a_truncating_seat_set_closes_the_episode() -> None:
    """The step cap closes an episode whose env never terminates."""
    env = _PairEnv(agents=("a", "b"), steps=999)

    summary = await run_multiseat_episode(
        env,
        channel_key="c",
        episode_id="episode_019b6000-0000-7000-8000-000000000003",
        interaction_id="interaction_019b6000-0000-7000-8000-000000000004",
        agent_ids=["a", "b"],
        sources={"a": _Fixed(0), "b": _Fixed(0)},
        now=lambda: "2026-07-22T00:00:00.000000Z",
        fps=0,
        max_steps=5,
    )

    assert summary.frames == 5
    assert summary.solved is False


async def test_solo_env_is_the_one_agent_case_of_the_loop() -> None:
    """A single-seat env, lifted, runs on the same multi-seat loop."""
    inner = _SoloCounter(steps=3)

    summary = await run_multiseat_episode(
        solo_env(inner, "only"),
        channel_key="solo",
        episode_id="episode_019b6000-0000-7000-8000-000000000005",
        interaction_id="interaction_019b6000-0000-7000-8000-000000000006",
        agent_ids=["only"],
        sources={"only": _Fixed(1)},
        now=lambda: "2026-07-22T00:00:00.000000Z",
        fps=0,
    )

    # The lift forwarded each single action to the underlying env and closed on it.
    assert inner.actions == [1, 1, 1]
    assert summary.frames == 3
    assert summary.solved is True
