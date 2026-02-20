"""Integration tests for ServerGame action-step-render-broadcast flow.

Tests cover the full flow: enqueue action -> step -> render -> reward tracking.
These tests use mock environments -- no running server or browser needed.
"""

from __future__ import annotations

import collections
from unittest.mock import patch

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


class MockEnvWithRender:
    """Mock environment that supports render() returning Phaser-compatible state."""

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
        obs = {0: [10, 20, 30], 1: [40, 50, 60]}
        rewards = {0: 1.0, 1: 0.5}
        terminated = {0: False, 1: False}
        truncated = {0: False, 1: False}
        infos = {0: {}, 1: {}}

        if self._terminate_after is not None and self._step_count >= self._terminate_after:
            terminated = {0: True, 1: True}

        return obs, rewards, terminated, truncated, infos

    def render(self):
        """Return Phaser-compatible state list of dicts."""
        return [
            {"id": "agent-0", "x": 0.1 * self._step_count, "y": 0.2},
            {"id": "agent-1", "x": 0.5, "y": 0.3 * self._step_count},
        ]

    def close(self):
        self.closed = True


class MockScene:
    """Mock scene for integration tests."""

    def __init__(
        self,
        num_episodes=3,
        terminate_after=None,
        default_action=0,
    ):
        self.policy_mapping = {
            0: configuration_constants.PolicyTypes.Human,
            1: configuration_constants.PolicyTypes.Human,
        }
        self.default_action = default_action
        self.action_population_method = configuration_constants.ActionSettings.DefaultAction
        self.num_episodes = num_episodes
        self.max_steps = 100
        self.callback = None
        self.load_policy_fn = None
        self.policy_inference_fn = None
        _term = terminate_after
        self.env_creator = lambda **kwargs: MockEnvWithRender(
            terminate_after=_term, **kwargs
        )
        self.env_config = {"render_mode": "interactive_gym"}


def _make_game(scene=None, game_id=0):
    """Create a ServerGame with mock scene, patching eventlet."""
    if scene is None:
        scene = MockScene()
    with patch("mug.server.remote_game.eventlet"):
        game = ServerGame(scene=scene, game_id=game_id)
    return game


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_action_step_render_broadcast():
    """Full flow: enqueue action -> step -> render -> verify rewards and tick."""
    scene = MockScene()
    game = _make_game(scene=scene)
    game._build_env()
    game.reset()

    # Enqueue an action for the human agent 0
    game.enqueue_action(0, 3)

    # Step the game
    obs, rewards, terminated, truncated, infos = game.step()

    # Verify tick incremented
    assert game.tick_num == 1

    # Verify render returns expected state
    render_state = game.env.render()
    assert isinstance(render_state, list)
    assert len(render_state) == 2
    assert render_state[0]["id"] == "agent-0"
    assert render_state[1]["id"] == "agent-1"

    # Verify rewards were tracked
    assert game.episode_rewards[0] == 1.0
    assert game.episode_rewards[1] == 0.5

    # Verify prev_actions recorded
    assert game.prev_actions[0] == 3


def test_multi_step_reward_accumulation():
    """Rewards accumulate correctly across multiple steps."""
    scene = MockScene()
    game = _make_game(scene=scene)
    game._build_env()
    game.reset()

    # Step 3 times
    for _ in range(3):
        game.step()

    # Each step gives agent 0 reward=1.0, agent 1 reward=0.5
    assert game.episode_rewards[0] == 3.0
    assert game.episode_rewards[1] == 1.5

    # Total rewards should also accumulate
    assert game.total_rewards[0] == 3.0
    assert game.total_rewards[1] == 1.5

    # Tick should be at 3
    assert game.tick_num == 3


def test_episode_reset_clears_state():
    """After episode completes and reset is called, state is properly cleared."""
    scene = MockScene(num_episodes=3, terminate_after=2)
    game = _make_game(scene=scene)
    game._build_env()
    game.reset()

    # Step twice (terminates after 2)
    game.step()
    game.step()

    # Should be in Reset status (more episodes remain)
    assert game.status == GameStatus.Reset
    assert game.episode_num == 1
    assert game.episode_rewards[0] == 2.0

    # Reset for next episode
    game.reset()

    # Episode num incremented
    assert game.episode_num == 2
    # Tick reset to 0
    assert game.tick_num == 0
    # Episode rewards cleared
    assert game.episode_rewards[0] == 0
    assert game.episode_rewards[1] == 0
    # Status back to Active
    assert game.status == GameStatus.Active
    # Total rewards persist across episodes
    assert game.total_rewards[0] == 2.0
    assert game.total_rewards[1] == 1.0
