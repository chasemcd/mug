"""Verify a browser-reported run by re-executing it (API-16 state-hash check).

The server re-runs the reported run from the fixed seed and the client's own
action sequence and checks every state hash against the re-execution. A run whose
hashes match the re-execution verifies deterministically; a run whose hashes were
tampered with fails; a run whose environment the server cannot build declares an
honest visual fallback rather than a faked match. One test also checks that the
state-hash hook source the server ships to the client computes the same hex as the
server's own hook, so the two never drift.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from examples.mountain_car.browser_env import mountain_car_browser_spec
from mug.game.browser import BrowserGameSpec, parse_client_episode
from mug.game.determinism import state_hash, state_hash_source
from mug.game.env import GymEnv
from mug.replay.verify import verify_browser_episode

_EPISODE = "episode_019b6000-0000-7000-8000-00000000000e"
_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000000f"
_CHANNEL = "mountain-car"


def _genuine_episode(
    spec: BrowserGameSpec, actions: list[int]
) -> dict[str, Any]:
    """Build the exact episode an honest client reports for these actions.

    It re-executes the run the same way the verifier does, so its hashes match a
    server re-execution. A short action run does not solve MountainCar, so the run
    closes on a reset boundary.
    """
    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)
    env = GymEnv(namespace["make_env"], seed=spec.seed)
    env.reset()
    transitions: list[dict[str, Any]] = []
    state = None
    for frame, action in enumerate(actions, start=1):
        state = env.step(action)
        transitions.append(
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
                "recorded_at": "2026-07-21T00:00:00.000000Z",
            }
        )
    assert state is not None
    boundary = {
        "episode_id": _EPISODE,
        "interaction_id": _INTERACTION,
        "kind": "reset",
        "end_frame_exclusive": len(actions),
        "authority": "browser",
        "state_hash": state_hash(state.observation).model_dump(mode="json"),
    }
    return {"transitions": transitions, "boundary": boundary}


def _parse(payload: dict[str, Any]) -> Any:
    return parse_client_episode(
        payload,
        expected_channel_key=_CHANNEL,
        expected_episode_id=_EPISODE,
        seat_key="player",
    )


def test_the_shipped_hook_matches_the_server_hook() -> None:
    """The state-hash source shipped to the client agrees with the server hook."""
    namespace: dict[str, Any] = {}
    exec(state_hash_source(), namespace)
    shipped = namespace["_mug_state_hash_hex"]
    for value in ([0.5, -1.2], 1, [0.0, 0.0], -0.4815162342):
        assert shipped(value) == state_hash(value).hex


def test_a_genuine_run_verifies_deterministically() -> None:
    """A run whose hashes match the re-execution verifies and binds a chain."""
    spec = mountain_car_browser_spec()
    actions = [0, 2, 1, 0]
    summary = _parse(_genuine_episode(spec, actions))

    report = verify_browser_episode(spec, actions=actions, summary=summary)

    assert report.verification == "deterministic"
    assert report.verified
    assert report.state_hash_chain_digest is not None
    assert len(report.checks) == len(actions)
    assert all(getattr(check, "result", None) == "match" for check in report.checks)
    # A browser reports digests and its own actions, never the values, so the
    # server's own re-execution is the only place a browser run's data exists.
    assert [frame.frame_number for frame in report.trajectory] == [1, 2, 3, 4]
    assert [frame.actions for frame in report.trajectory] == [
        {"player": action} for action in actions
    ]


def test_a_tampered_state_hash_fails_verification() -> None:
    """A run that reports a state hash it did not produce does not verify."""
    spec = mountain_car_browser_spec()
    actions = [1, 1, 1]
    episode = _genuine_episode(spec, actions)
    episode["transitions"][1]["state_digest"] = state_hash("forged").model_dump(
        mode="json"
    )
    summary = _parse(episode)

    report = verify_browser_episode(spec, actions=actions, summary=summary)

    assert report.verification == "deterministic"
    assert not report.verified
    results = [getattr(check, "result", None) for check in report.checks]
    assert results == ["match", "mismatch", "match"]
    # The re-execution is not this run, so its values are withheld: recording them
    # would attach a trajectory to a run that diverged from it.
    assert report.trajectory == ()


def test_a_forged_solve_boundary_fails_verification() -> None:
    """A run that fakes a different closing state does not verify."""
    spec = mountain_car_browser_spec()
    actions = [2, 2]
    episode = _genuine_episode(spec, actions)
    episode["boundary"]["state_hash"] = state_hash([0.5, 0.0]).model_dump(
        mode="json"
    )
    summary = _parse(episode)

    report = verify_browser_episode(spec, actions=actions, summary=summary)

    assert not report.verified


def test_a_wrong_action_count_fails_before_re_execution() -> None:
    """A run whose action count does not match its frames cannot verify."""
    spec = mountain_car_browser_spec()
    summary = _parse(_genuine_episode(spec, [1, 1, 1]))

    report = verify_browser_episode(spec, actions=[1, 1], summary=summary)

    assert report.verification == "deterministic"
    assert not report.verified
    assert report.reason == "action-count-mismatch"


def test_an_unbuildable_environment_declares_a_visual_fallback() -> None:
    """When the server cannot re-execute the run, it does not fake a match."""
    spec = mountain_car_browser_spec()
    actions = [1, 1]
    summary = _parse(_genuine_episode(spec, actions))
    broken = replace(spec, source_bundle="raise RuntimeError('no env here')")

    report = verify_browser_episode(broken, actions=actions, summary=summary)

    assert report.verification == "visual-fallback"
    assert not report.verified
    assert all(
        getattr(check, "verification", None) == "visual-fallback"
        for check in report.checks
    )
