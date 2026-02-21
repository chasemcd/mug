"""Unit tests for ServerGame lifecycle methods.

Tests cover: _build_env, reset, step, enqueue_action, tear_down, _load_policies.
These tests use mock environments and scene objects -- no running server or browser needed.
"""

from __future__ import annotations

import collections
from unittest.mock import MagicMock, patch

import pytest

from mug.configurations import configuration_constants
from mug.server.remote_game import GameStatus, ServerGame

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class MockActionSpace:
    """Minimal action space that supports sample()."""

    def sample(self):
        return 0


class MockEnv:
    """Mock Gymnasium-style environment for testing ServerGame.

    Supports:
    - reset() -> (obs_dict, info_dict)
    - step(actions) -> (obs, rewards, terminated, truncated, infos)
    - close()
    - action_space.sample()
    - render_mode stored in constructor
    """

    def __init__(self, render_mode=None, terminate_after=None, **kwargs):
        self.render_mode = render_mode
        self.action_space = MockActionSpace()
        self.closed = False
        self._step_count = 0
        self._terminate_after = terminate_after

    def reset(self):
        self._step_count = 0
        obs = {0: [1, 2, 3], 1: [4, 5, 6]}
        info = {}
        return obs, info

    def step(self, actions):
        self._step_count += 1
        obs = {0: [1, 2, 3], 1: [4, 5, 6]}
        rewards = {0: 1.0, 1: 0.5}
        terminated = {0: False, 1: False}
        truncated = {0: False, 1: False}
        infos = {0: {}, 1: {}}

        if self._terminate_after is not None and self._step_count >= self._terminate_after:
            terminated = {0: True, 1: True}

        return obs, rewards, terminated, truncated, infos

    def close(self):
        self.closed = True

    def render(self):
        return [{"id": "sprite-1", "x": 0.5, "y": 0.5}]


class MockScene:
    """Mock scene object providing the attributes ServerGame expects."""

    def __init__(
        self,
        policy_mapping=None,
        default_action=0,
        num_episodes=3,
        max_steps=100,
        env_creator=None,
        env_config=None,
        terminate_after=None,
    ):
        if policy_mapping is None:
            policy_mapping = {
                0: configuration_constants.PolicyTypes.Human,
                1: configuration_constants.PolicyTypes.Human,
            }
        self.policy_mapping = policy_mapping
        self.default_action = default_action
        self.action_population_method = configuration_constants.ActionSettings.DefaultAction
        self.num_episodes = num_episodes
        self.max_steps = max_steps
        self.callback = None
        self.load_policy_fn = None
        self.policy_inference_fn = None

        _terminate_after = terminate_after
        if env_creator is not None:
            self.env_creator = env_creator
        else:
            self.env_creator = lambda **kwargs: MockEnv(
                terminate_after=_terminate_after, **kwargs
            )

        self.env_config = env_config or {"render_mode": "mug"}


def _make_game(scene=None, game_id=0):
    """Create a ServerGame with a mock scene, patching eventlet for testing."""
    if scene is None:
        scene = MockScene()
    with patch("mug.server.remote_game.eventlet"):
        game = ServerGame(scene=scene, game_id=game_id)
    return game


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestServerGameLifecycle:
    """Unit tests for ServerGame lifecycle methods."""

    def test_build_env_creates_environment(self):
        """_build_env creates the env from scene.env_creator with render_mode='mug'."""
        game = _make_game()
        assert game.env is None

        game._build_env()

        assert game.env is not None
        assert isinstance(game.env, MockEnv)
        assert game.env.render_mode == "mug"

    def test_reset_initializes_episode(self):
        """After _build_env, reset() initializes episode state correctly."""
        game = _make_game()
        game._build_env()
        game.reset()

        assert game.episode_num == 1
        assert game.tick_num == 0
        assert game.status == GameStatus.Active
        assert game.observation is not None
        # observation should be the obs dict from MockEnv.reset()
        assert 0 in game.observation
        assert 1 in game.observation

    def test_step_with_enqueued_action(self):
        """step() uses enqueued actions and clears pending_actions."""
        game = _make_game()
        game._build_env()
        game.reset()

        # Enqueue action for agent 0
        game.enqueue_action(0, 3)
        game.step()

        assert game.tick_num == 1
        assert len(game.pending_actions) == 0
        # prev_actions should contain the enqueued action for agent 0
        assert game.prev_actions[0] == 3

    def test_step_with_default_action_fallback(self):
        """step() falls back to default_action when no action is enqueued."""
        scene = MockScene(default_action=6)
        game = _make_game(scene=scene)
        game._build_env()
        game.reset()

        # Do NOT enqueue any action
        game.step()

        assert game.tick_num == 1
        # Both human agents should have used default_action=6
        assert game.prev_actions[0] == 6
        assert game.prev_actions[1] == 6

    def test_step_episode_done_sets_reset_status(self):
        """When env returns terminated=True, status becomes Reset (if more episodes remain)."""
        scene = MockScene(num_episodes=3, terminate_after=1)
        game = _make_game(scene=scene)
        game._build_env()
        game.reset()

        game.step()

        assert game.status == GameStatus.Reset

    def test_step_episode_done_sets_done_status_final_episode(self):
        """When env returns terminated=True on the last episode, status becomes Done."""
        scene = MockScene(num_episodes=1, terminate_after=1)
        game = _make_game(scene=scene)
        game._build_env()
        game.reset()

        game.step()

        assert game.status == GameStatus.Done

    def test_tear_down_closes_env(self):
        """tear_down() closes the env and sets status to Inactive."""
        game = _make_game()
        game._build_env()
        assert game.env is not None

        game.tear_down()

        assert game.env.closed is True
        assert game.status == GameStatus.Inactive

    def test_enqueue_action_stores_pending(self):
        """enqueue_action stores the action in pending_actions dict."""
        game = _make_game()
        game.enqueue_action(0, 5)

        assert game.pending_actions[0] == 5

    def test_load_policies_with_bot_agent(self):
        """_load_policies loads Random agent policy as None."""
        scene = MockScene(
            policy_mapping={
                0: configuration_constants.PolicyTypes.Human,
                1: configuration_constants.PolicyTypes.Random,
            }
        )
        game = _make_game(scene=scene)
        game._build_env()
        game._load_policies()

        # Human agents should NOT be in policies dict
        assert 0 not in game.policies
        # Random agent should have None policy
        assert 1 in game.policies
        assert game.policies[1] is None
