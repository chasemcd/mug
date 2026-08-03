"""An exported network plays a seat, and the run it played is recorded.

The legacy suite proved this by opening a browser against a study whose partner
was an ONNX model and watching the episode finish. Two things were really being
checked, and they fail separately, so they are two tests here:

- **the platform's half.** A seat driven by an exported network is stepped by the
  same loop as a person's seat, its actions are recorded under its own seat key,
  and the run is captured. None of that needs a runtime, because the inference is
  a seam the study supplies -- and holding it to a stub is what proves the seam is
  really a seam.
- **the study's half.** The example really loads its shipped ``.onnx`` file and
  really scores an observation. That needs ``onnxruntime``, which this repository
  does not depend on, so it is skipped where the package is absent and says so.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mug.casting import OnnxPolicy
from mug.casting.types import OnnxPreprocessing
from mug.game.controllers import OnnxController
from mug.game.env import NO_INFO
from mug.game.multiseat import MultiStepResult, run_multiseat_episode
from mug.game.runtime import InputState
from tests.robustness._runs import off_loop

_SEATS = ("person", "network")
_FRAMES = 12
_MODEL = (
    Path(__file__).resolve().parents[2]
    / "examples/slime_volleyball/assets/models/slimevb_policy.onnx"
)


class _TwoSeats:
    """The smallest two-seat environment: it remembers what each seat did."""

    def __init__(self) -> None:
        self.frame = 0

    def reset(self) -> MultiStepResult:
        """Start the run with an empty board."""
        self.frame = 0
        return self._result({seat: 0 for seat in _SEATS})

    def step(self, actions: Any) -> MultiStepResult:
        """Step one frame from the action every seat supplied."""
        self.frame += 1
        return self._result({seat: int(actions[seat]) for seat in _SEATS})

    def _result(self, taken: dict[str, int]) -> MultiStepResult:
        return MultiStepResult(
            observations={seat: [self.frame, taken[seat]] for seat in _SEATS},
            rewards=dict.fromkeys(_SEATS, 0.0),
            terminated=self.frame >= _FRAMES,
            truncated=False,
            info=NO_INFO,
        )


def _network(scores: list[float]) -> OnnxController:
    """Return an exported-network seat whose inference is a fixed score vector."""
    policy = OnnxPolicy(
        policy_ref="robustness-policy@1",
        preprocessing=OnnxPreprocessing(transform="flatten"),
        selection_mode="argmax",
    )
    return OnnxController(policy, lambda _observation: scores)


def test_an_exported_network_plays_a_seat_beside_a_person() -> None:
    """The run steps both seats, and the network's own action is what it chose.

    The scores make the third action the greatest, so a loop that recorded a
    default, or that gave the network the person's action, records a two rather
    than a three.
    """
    chosen = 3
    scores = [0.1, 0.2, 0.9, 4.0, 0.3]
    person = InputState({"ArrowLeft": 1}, 0)

    summary = off_loop(
        run_multiseat_episode(
            _TwoSeats(),
            channel_key="exported",
            episode_id="episode_019b6000-0000-7000-8000-00000000000a",
            interaction_id="interaction_019b6000-0000-7000-8000-00000000000b",
            agent_ids=list(_SEATS),
            sources={"person": person, "network": _network(scores)},
            now=lambda: "2026-07-28T00:00:00.000000Z",
            fps=0,
            max_steps=_FRAMES + 4,
        )
    )

    assert summary.frames == _FRAMES
    assert summary.solved, "the environment ended the run, so the loop ran it out"
    assert len(summary.trajectory) == _FRAMES
    for frame in summary.trajectory:
        assert frame.actions["network"] == chosen
        assert frame.actions["person"] == 0


def test_the_network_seat_is_recorded_under_its_own_name() -> None:
    """A study asks what the model did, so the model must be in the record.

    A run that recorded one action per frame, or that keyed both seats the same,
    would step correctly and answer no question about the pair.
    """
    summary = off_loop(
        run_multiseat_episode(
            _TwoSeats(),
            channel_key="exported",
            episode_id="episode_019b6000-0000-7000-8000-00000000000c",
            interaction_id="interaction_019b6000-0000-7000-8000-00000000000d",
            agent_ids=list(_SEATS),
            sources={
                "person": InputState({}, 1),
                "network": _network([5.0, 0.0]),
            },
            now=lambda: "2026-07-28T00:00:00.000000Z",
            fps=0,
            max_steps=_FRAMES + 4,
        )
    )

    for frame in summary.trajectory:
        assert set(frame.actions) == set(_SEATS)
        assert set(frame.observations) == set(_SEATS)
        assert frame.actions["network"] == 0
        assert frame.actions["person"] == 1


def test_a_network_that_scores_nothing_is_refused_rather_than_guessed_at() -> None:
    """An empty score vector is a broken model, and a seat must not invent an action."""
    from mug.game.controllers import ControllerUnavailable

    with pytest.raises(ControllerUnavailable):
        _network([]).decide([0.0])


@pytest.mark.skipif(
    not _MODEL.is_file(), reason="the example's exported model is not in the tree"
)
def test_the_shipped_model_really_loads_and_really_scores() -> None:
    """The study's own half: the file on disk is a model, and it answers.

    This is what the legacy browser test was really checking behind the episode:
    that the exported network in the repository is loadable and produces one score
    per action.
    """
    pytest.importorskip("onnxruntime", reason="uv pip install onnxruntime")
    from examples.slime_volleyball.policies import exported_partner

    partner = exported_partner(str(_MODEL))
    # The seat is handed its own observation, which for this court is the twelve
    # numbers the network was trained on -- not a dictionary holding them.
    action = partner.decide([0.0] * 12)

    assert isinstance(action, int)
    assert action >= 0
