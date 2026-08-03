"""A seat driven by an exported network in the participant's own browser.

The environment steps in Pyodide, where no ONNX runtime can be installed, so a
browser-run study that wants a trained partner has to score it beside the
environment with the browser's own inference runtime. That runtime is not on the
server, so the partner's decisions travel with the run and are replayed when the
server re-executes it.

What is checked here is the whole of the server's half of that:

- the manifest tells the client which **declared asset** holds the model, so a
  study names a network the way it names a picture and never an address;
- a bundle that declares a partner and does not meet it is refused where the study
  is written, rather than playing a whole round against a seat that never moves;
- the re-execution really replays the reported decisions -- a run verified without
  them would be a run verified against a partner that stood still, which is a
  different run and would record the wrong trajectory.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from typing import Any

import pytest

from mug.game.browser import (
    BrowserGameSpec,
    BrowserPartner,
    client_manifest,
    parse_client_episode,
)
from mug.game.determinism import state_hash
from mug.replay.verify import verify_browser_episode

# A one-seat environment with a partner beside it. The observation is the pair of
# places, so a frame the partner moved on hashes differently from one it did not:
# that is what makes the replay of its decisions load-bearing rather than decorative.
_BUNDLE = '''
_partner_action = 0
_env = None


def partner_acts(action):
    global _partner_action
    _partner_action = int(action)


def partner_observation():
    return [float(_env.mine), float(_env.theirs)]


class Lane:
    """Two walkers on one lane. Each action is a step, and 0 stands still."""

    def __init__(self):
        self.mine = 0
        self.theirs = 0

    def reset(self, seed=None):
        self.mine = 0
        self.theirs = 0
        return [float(self.mine), float(self.theirs)], {}

    def step(self, action):
        self.mine += int(action)
        self.theirs += int(_partner_action)
        return [float(self.mine), float(self.theirs)], 0.0, False, False, {}


def make_env():
    global _env
    _env = Lane()
    return _env


def draw(observation):
    return [
        {"op": "circle", "id": "me", "relative": True, "color": "#ff0000",
         "x": 0.1, "y": 0.5, "radius": 0.02},
    ]
'''

_SEAT = "player"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000000a"
_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000000b"


def _spec(**changed: object) -> BrowserGameSpec:
    """Return the browser specification, with an exported partner beside the seat."""
    return BrowserGameSpec(
        channel_key="lane",
        source_bundle=_BUNDLE,
        requires=(),
        action_bindings={"ArrowRight": 1},
        default_action=0,
        seed=11,
        fps=0,
        max_steps=16,
        countdown_seconds=0,
        partner=BrowserPartner(model="lane-policy", decide_every=2, **changed),  # pyright: ignore[reportArgumentType]
    )


def _reported(actions: list[int], partner_actions: list[int]) -> dict[str, object]:
    """Build the run a browser reports, by really running the bundle over it."""
    namespace: dict[str, Any] = {}
    exec(_BUNDLE, namespace)
    env: Any = namespace["make_env"]()
    env.reset(seed=11)
    transitions: list[dict[str, object]] = []
    for index, action in enumerate(actions):
        namespace["partner_acts"](partner_actions[index])
        observation, _reward, _terminated, _truncated, _info = env.step(action)
        transitions.append(
            {
                "interaction_id": _INTERACTION,
                "channel_key": "lane",
                "episode_id": _EPISODE,
                "frame_number": index + 1,
                "action_digest": state_hash(action).model_dump(mode="json"),
                "state_digest": state_hash(observation).model_dump(mode="json"),
                "authority": "browser",
                "applied_decisions": [],
                "recorded_at": "2026-07-28T00:00:00.000000Z",
            }
        )
    return {
        "transitions": transitions,
        "boundary": {
            "episode_id": _EPISODE,
            "interaction_id": _INTERACTION,
            "kind": "reset",
            "end_frame_exclusive": len(actions),
            "authority": "browser",
            "state_hash": state_hash([float(env.mine), float(env.theirs)]).model_dump(
                mode="json"
            ),
        },
    }


def _summary(run: dict[str, object]) -> Any:
    """Validate one reported run into the contract the server verifies."""
    return parse_client_episode(
        run,
        expected_channel_key="lane",
        expected_episode_id=_EPISODE,
        seat_key=_SEAT,
    )


def test_the_manifest_names_the_declared_asset_that_holds_the_model() -> None:
    """A study names its network; nothing about where it is served reaches here."""
    manifest = client_manifest(
        _spec(), episode_id=_EPISODE, interaction_id=_INTERACTION, seat_key=_SEAT
    )

    partner: Any = manifest["partner"]
    assert partner["model"] == "lane-policy"
    assert partner["decide_every"] == 2
    assert "/" not in partner["model"], "a study names a model, it does not address it"


def test_a_game_with_no_partner_says_so_rather_than_leaving_it_out() -> None:
    """A client must be able to tell "no partner" from "a field I do not know"."""
    plain = BrowserGameSpec(
        channel_key="lane",
        source_bundle=_BUNDLE,
        requires=(),
        action_bindings={},
        default_action=0,
        seed=11,
    )

    manifest = client_manifest(
        plain, episode_id=_EPISODE, interaction_id=_INTERACTION, seat_key=_SEAT
    )

    assert manifest["partner"] is None


def test_a_bundle_that_declares_a_partner_and_does_not_meet_it_is_refused() -> None:
    """Refused where the study is written, not a round into a participant's run."""
    with pytest.raises(ValueError, match="partner_observation"):
        BrowserGameSpec(
            channel_key="lane",
            source_bundle="def make_env():\n    return None\n",
            requires=(),
            action_bindings={},
            default_action=0,
            seed=11,
            partner=BrowserPartner(model="lane-policy"),
        )


def test_a_partner_that_decides_less_than_once_a_frame_is_refused() -> None:
    """A frame skip below one is a study's mistake, and it is caught as one."""
    with pytest.raises(ValueError, match="at least once"):
        BrowserPartner(model="lane-policy", decide_every=0)


def test_the_re_execution_replays_what_the_partner_did() -> None:
    """The run verifies, which it can only do if the partner moved as reported."""
    actions = [1, 1, 1, 1, 1, 1]
    partner_actions = [1, 0, 1, 0, 1, 0]
    run = _reported(actions, partner_actions)

    report = verify_browser_episode(
        _spec(),
        actions=actions,
        summary=_summary(run),
        partner_actions=partner_actions,
    )

    assert report.verification == "deterministic"
    assert report.verified, "the server could not reproduce a run it was given in full"
    assert len(report.trajectory) == len(actions)


def test_a_run_whose_partner_decisions_are_missing_does_not_verify() -> None:
    """Silence about the partner is refused rather than read as a partner at rest.

    Without this the server would re-execute against a seat that never moved, find
    different state hashes, and either reject an honest run or -- worse, if the
    partner happened to matter little -- record a trajectory nobody played.
    """
    actions = [1, 1, 1, 1]
    partner_actions = [1, 1, 1, 1]
    run = _reported(actions, partner_actions)

    report = verify_browser_episode(
        _spec(),
        actions=actions,
        summary=_summary(run),
    )

    assert not report.verified
    assert report.reason == "partner-action-count-mismatch"
    assert report.trajectory == ()


def test_a_run_that_misreports_what_the_partner_did_does_not_verify() -> None:
    """The state hashes are the consequence of both seats, so both are checked."""
    actions = [1, 1, 1, 1]
    run = _reported(actions, [1, 1, 1, 1])

    report = verify_browser_episode(
        _spec(),
        actions=actions,
        summary=_summary(run),
        partner_actions=[0, 0, 0, 0],
    )

    assert not report.verified, "a run was accepted against a partner it did not play"


def test_a_browser_study_that_asks_for_rounds_it_cannot_play_is_refused() -> None:
    """The worst fault is the one nothing says: an author asked and was ignored.

    A browser-executed game is written by the client and captured once, so the
    server has no round loop for it. ``Game("play", episodes=3)`` would have played
    one round and moved on, with nothing in the records to say so.
    """
    from mug.app import build_study_app
    from mug.content import Game, Page, Study

    study = Study(
        Page("start", "# Ready"), Game("play", episodes=3), Page("end", "# X")
    )

    with pytest.raises(ValueError, match="one round per activity"):
        build_study_app(study=study, browser_game=_spec())


def test_a_browser_study_that_plays_one_round_builds() -> None:
    """The refusal is about rounds nobody can play, not about browser studies."""
    from mug.app import build_study_app
    from mug.content import Game, Page, Study

    study = Study(Page("start", "# Ready"), Game("play"), Page("end", "# X"))

    assert build_study_app(study=study, browser_game=_spec()) is not None


def test_a_peer_to_peer_study_that_asks_for_rounds_it_cannot_play_is_refused() -> None:
    """A room runs once to its end, so the mesh has no round loop either.

    A shipped example asked for five rounds of a peer-to-peer kitchen and played
    one, which is how this was found.
    """
    from mug.app import build_study_app
    from mug.content import Game, Page, Study
    from mug.game.browser_mesh import BrowserMeshSpec
    from mug.participant_p2p_types import BrowserP2PConfig

    mesh = BrowserMeshSpec(
        channel_key="lane",
        source_bundle="def make_replica(peers, seed):\n    return None\n",
        requires=(),
        action_bindings={},
        default_action=0,
    )
    study = Study(
        Page("start", "# Ready"), Game("play", episodes=5), Page("end", "# X")
    )

    with pytest.raises(ValueError, match="one round per activity"):
        build_study_app(
            study=study,
            browser_p2p=BrowserP2PConfig(
                channel_key="lane", size=2, game=mesh, seed=11
            ),
        )
