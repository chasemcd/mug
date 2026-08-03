"""A study says what its environment can support, and its runs are recorded.

The server records a browser run by re-executing it and matching every state hash.
That is the right default and it is what makes a client-written record evidence.
But it was also the *only* behaviour: an environment that does not reproduce had no
way to say so, and a re-execution that succeeded and disagreed was always a refusal.

So an environment that did not repeat refused **every** participant's run, at the
end of the round, and recorded nothing -- which is exactly what happened here when
CoGrid drew its agent order from operating-system entropy. The fault was upstream;
the reason it cost whole rounds was that the platform had no way to be told.

``BrowserGameSpec.verification`` is that way. It changes what is recorded, never
whether something is: a run under ``visual-fallback`` carries the verdict saying it
was not checked, so a reader can tell what the record is worth.
"""

from __future__ import annotations

from typing import Any

import pytest

from mug.game.browser import BrowserGameSpec
from mug.game.determinism import state_hash
from mug.game.env import GymEnv
from mug.game.runtime import EpisodeSummary
from mug.game.types import EpisodeBoundary, GameTransition
from mug.replay.verify import verify_browser_episode

_UUID = "019b6000-0000-7000-8000-{:012x}"
_EPISODE = "episode_" + _UUID.format(0x900)
_INTERACTION = "interaction_" + _UUID.format(0x901)

# An environment that never gives the same run twice. It is the shape of the real
# fault -- a step that draws from somewhere the seed does not reach.
_ROVING = """
import random


class _Roving:
    def reset(self, seed=None):
        self.at = 0.0
        return [self.at], {}

    def step(self, action):
        self.at += float(action) + random.random()
        return [self.at], 0.0, False, False, {}


def make_env():
    return _Roving()
"""

_STEADY = """
class _Steady:
    def reset(self, seed=None):
        self.at = 0.0
        return [self.at], {}

    def step(self, action):
        self.at += float(action)
        return [self.at], 0.0, False, False, {}


def make_env():
    return _Steady()
"""


def _spec(bundle: str, **extra: Any) -> BrowserGameSpec:
    return BrowserGameSpec(
        channel_key="roving",
        source_bundle=bundle,
        requires=(),
        action_bindings={"ArrowRight": 1},
        default_action=1,
        seed=7,
        **extra,
    )


def _reported(spec: BrowserGameSpec, actions: list[int]) -> EpisodeSummary:
    """Build the run an honest client reports, by running the bundle once."""
    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)
    env = GymEnv(namespace["make_env"], seed=spec.seed)
    env.reset()
    transitions: list[GameTransition] = []
    state = None
    for frame, action in enumerate(actions, start=1):
        state = env.step(action)
        transitions.append(
            GameTransition.model_validate(
                {
                    "interaction_id": _INTERACTION,
                    "channel_key": spec.channel_key,
                    "episode_id": _EPISODE,
                    "frame_number": frame,
                    "action_digest": state_hash(action).model_dump(mode="json"),
                    "state_digest": state_hash(state.observation).model_dump(
                        mode="json"
                    ),
                    "authority": "browser",
                    "applied_decisions": [],
                    "recorded_at": "2026-07-28T00:00:00.000000Z",
                }
            )
        )
    assert state is not None
    boundary = EpisodeBoundary.model_validate(
        {
            "episode_id": _EPISODE,
            "interaction_id": _INTERACTION,
            "kind": "reset",
            "end_frame_exclusive": len(actions),
            "authority": "browser",
            "state_hash": state_hash(state.observation).model_dump(mode="json"),
        }
    )
    return EpisodeSummary(
        channel_key=spec.channel_key,
        seat_key="agent-0",
        frames=len(transitions),
        transitions=transitions,
        boundary=boundary,
        solved=False,
    )


def test_an_environment_that_does_not_repeat_loses_every_run_by_default() -> None:
    """The default is strict, and strictness against a roving environment is total.

    This is the fault as the participant met it: they played the whole round and the
    report of it was refused. The verdict is what a study reads to know it must
    declare something else.
    """
    spec = _spec(_ROVING)
    actions = [1, 1, 1, 1, 1]

    reported = _reported(spec, actions)
    report = verify_browser_episode(spec, actions=actions, summary=reported)

    assert report.verification == "deterministic"
    assert not report.verified


def test_a_study_may_say_its_environment_does_not_repeat() -> None:
    """Declared, the same run is recorded rather than discarded."""
    spec = _spec(_ROVING, verification="visual-fallback")
    actions = [1, 1, 1, 1, 1]

    reported = _reported(spec, actions)
    report = verify_browser_episode(spec, actions=actions, summary=reported)

    assert report.verification == "visual-fallback"
    assert report.reason == "environment-not-reproducible"
    # Every frame carries a check saying what was not done, so the record never
    # claims more than was checked.
    assert len(report.checks) == len(actions)
    # No values are attached: the server's re-execution is not this run, so
    # recording its numbers would be inventing a trajectory nobody played.
    assert report.trajectory == ()
    assert report.state_hash_chain_digest is None


def test_declaring_it_does_not_weaken_a_study_that_can_be_verified() -> None:
    """A reproducible environment still verifies, and still refuses a forged run."""
    spec = _spec(_STEADY)
    actions = [1, 2, 3]
    honest = _reported(spec, actions)

    assert verify_browser_episode(spec, actions=actions, summary=honest).verified

    forged = honest._replace(
        transitions=[
            honest.transitions[0].model_copy(
                update={"state_digest": state_hash("nonsense")}
            ),
            *honest.transitions[1:],
        ]
    )
    assert not verify_browser_episode(spec, actions=actions, summary=forged).verified


def test_a_study_cannot_ask_for_a_verification_that_does_not_exist() -> None:
    """An unknown level is refused where the author is reading their own code."""
    with pytest.raises(ValueError, match="deterministic"):
        _spec(_STEADY, verification="trust-me")
