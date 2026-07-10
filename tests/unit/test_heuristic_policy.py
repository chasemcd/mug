"""Unit tests for heuristic (Python code) policies.

Covers the HeuristicPolicy base class machinery, GymScene policy_mapping
decomposition/validation, and the server-side load/execute path in
ServerGame. No running server or browser needed.

The subclasses defined in this module double as test payloads: to_config()
ships this file's source, and load_from_config() re-executes it to
reconstruct the class.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from mug.configurations import configuration_constants
from mug.configurations.configuration_constants import (
    HEURISTIC_POLICY_PREFIX, HeuristicPolicy)
from mug.scenes import gym_scene
from mug.server.remote_game import ServerGame


class Chaser(HeuristicPolicy):
    def compute_action(self, env, agent_id):
        return 5


class AgentAware(HeuristicPolicy):
    def compute_action(self, env, agent_id):
        # Derive the action from the live env and agent id so tests can
        # verify both were passed through correctly.
        return env.marker + (1 if agent_id == 1 else 0)


class Stateful(HeuristicPolicy):
    def __init__(self):
        self.calls = 0

    def compute_action(self, env, agent_id):
        self.calls += 1
        return self.calls


# ---------------------------------------------------------------------------
# HeuristicPolicy base class machinery
# ---------------------------------------------------------------------------

def test_policy_id_uses_prefix_and_class_name():
    assert Chaser.policy_id() == f"{HEURISTIC_POLICY_PREFIX}Chaser"


def test_to_config_ships_defining_module_source():
    config = Chaser.to_config()
    assert config["type"] == "heuristic"
    assert config["name"] == "Chaser"
    assert "class Chaser(HeuristicPolicy):" in config["code"]


def test_to_config_rejects_main_module_classes():
    main_cls = type(
        "MainPolicy", (HeuristicPolicy,), {"__module__": "__main__"}
    )
    with pytest.raises(ValueError, match="main script"):
        main_cls.to_config()


def test_load_from_config_returns_instance():
    policy = HeuristicPolicy.load_from_config(Chaser.to_config())
    assert policy.compute_action(env=None, agent_id="agent_right") == 5


def test_load_from_config_missing_class_raises():
    with pytest.raises(ValueError, match="compute_action"):
        HeuristicPolicy.load_from_config(
            {"type": "heuristic", "name": "Missing", "code": "x = 1"}
        )


def test_load_from_config_instances_are_independent():
    a = HeuristicPolicy.load_from_config(Stateful.to_config())
    b = HeuristicPolicy.load_from_config(Stateful.to_config())
    assert a.compute_action(None, 0) == 1
    assert a.compute_action(None, 0) == 2
    assert b.compute_action(None, 0) == 1


def test_base_compute_action_is_abstract():
    with pytest.raises(NotImplementedError):
        HeuristicPolicy().compute_action(None, 0)


# ---------------------------------------------------------------------------
# GymScene decomposition and validation
# ---------------------------------------------------------------------------

def _make_scene(policy_mapping):
    return gym_scene.GymScene().policies(policy_mapping=policy_mapping)


def test_scene_decomposes_heuristic_policy_class():
    scene = _make_scene(
        {
            "agent_left": configuration_constants.PolicyTypes.Human,
            "agent_right": Chaser,
        }
    )

    assert scene.policy_mapping["agent_right"] == "heuristic:Chaser"
    config = scene.policy_configs["agent_right"]
    assert config["type"] == "heuristic"
    assert "class Chaser(HeuristicPolicy):" in config["code"]


def test_scene_rejects_heuristic_policy_instance():
    with pytest.raises(ValueError, match="pass the class"):
        _make_scene({"agent_right": Chaser()})


def test_scene_metadata_serializes_heuristic_config():
    scene = _make_scene({"agent_right": Chaser}).scene(
        scene_id="s", experiment_config={}
    )
    metadata = scene.scene_metadata
    assert metadata["policy_mapping"]["agent_right"] == "heuristic:Chaser"
    assert "class Chaser" in metadata["policy_configs"]["agent_right"]["code"]
    json.dumps(metadata)  # must be JSON-serializable for the JS client


def test_heuristic_marker_without_config_raises():
    with pytest.raises(ValueError, match="no code"):
        _make_scene({"agent_right": "heuristic:Missing"})


def test_duplicate_name_with_different_code_raises():
    scene = gym_scene.GymScene()
    scene.policy_configs = {
        0: {"type": "heuristic", "name": "Same", "code": "code A"},
        1: {"type": "heuristic", "name": "Same", "code": "code B"},
    }
    with pytest.raises(ValueError, match="unique"):
        scene.policies(
            policy_mapping={0: "heuristic:Same", 1: "heuristic:Same"}
        )


def test_shared_policy_class_across_agents_is_allowed():
    scene = _make_scene({0: Chaser, 1: Chaser})
    assert scene.policy_mapping == {
        0: "heuristic:Chaser",
        1: "heuristic:Chaser",
    }


# ---------------------------------------------------------------------------
# Server-side execution (ServerGame)
# ---------------------------------------------------------------------------

class MockEnv:
    """Minimal multi-agent env that records the actions it receives."""

    def __init__(self, **kwargs):
        self.marker = 10
        self.last_actions = None

    def reset(self):
        return {0: [0.0], 1: [0.0]}, {}

    def step(self, actions):
        self.last_actions = dict(actions)
        obs = {0: [0.0], 1: [0.0]}
        rewards = {0: 0.0, 1: 0.0}
        terminated = {0: False, 1: False}
        truncated = {0: False, 1: False}
        return obs, rewards, terminated, truncated, {}


class MockScene:
    def __init__(self, policy_mapping, policy_configs):
        self.policy_mapping = policy_mapping
        self.policy_configs = policy_configs
        self.default_action = 0
        self.action_population_method = (
            configuration_constants.ActionSettings.DefaultAction
        )
        self.num_episodes = 1
        self.max_steps = 100
        self.callback = None
        self.load_policy_fn = None
        self.policy_inference_fn = None
        self.env_creator = lambda **kwargs: MockEnv(**kwargs)
        self.env_config = {}


def _make_game(scene):
    with patch("mug.server.remote_game.eventlet"):
        game = ServerGame(scene=scene, game_id=0)
    return game


def test_server_game_runs_heuristic_with_live_env():
    scene = MockScene(
        policy_mapping={
            0: configuration_constants.PolicyTypes.Human,
            1: AgentAware.policy_id(),
        },
        policy_configs={1: AgentAware.to_config()},
    )
    game = _make_game(scene)
    game._build_env()
    game._load_policies()
    game.reset()

    game.enqueue_action(0, 3)
    game.step()

    # Heuristic received the live env (marker=10) and agent_id=1 -> 11
    assert game.env.last_actions[1] == 11
    assert game.env.last_actions[0] == 3


def test_server_game_gives_each_agent_its_own_instance():
    scene = MockScene(
        policy_mapping={
            0: Stateful.policy_id(),
            1: Stateful.policy_id(),
        },
        policy_configs={0: Stateful.to_config(), 1: Stateful.to_config()},
    )
    game = _make_game(scene)
    game._build_env()
    game._load_policies()
    game.reset()

    game.step()
    game.step()

    # Each agent's instance counts its own calls: both at 2 after two steps
    assert game.env.last_actions == {0: 2, 1: 2}


def test_server_game_heuristic_load_failure_surfaces_at_load_time():
    scene = MockScene(
        policy_mapping={1: "heuristic:Bad"},
        policy_configs={
            1: {"type": "heuristic", "name": "Bad", "code": "x = 1"}
        },
    )
    game = _make_game(scene)
    game._build_env()
    with pytest.raises(ValueError, match="compute_action"):
        game._load_policies()
