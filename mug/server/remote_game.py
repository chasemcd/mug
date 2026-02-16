from __future__ import annotations

import collections
import dataclasses
import logging
import threading
import typing
import uuid
from enum import Enum, auto
from typing import Any

import eventlet

from mug.configurations import configuration_constants

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Session lifecycle states per SESS-01.

    These states track the overall session lifecycle, orthogonal to GameStatus
    which tracks the game-loop phase (Active/Reset/Done).
    """
    WAITING = auto()     # In waiting room, waiting for players
    MATCHED = auto()     # All players matched, about to validate
    VALIDATING = auto()  # P2P validation in progress
    PLAYING = auto()     # Game running
    ENDED = auto()       # Terminal, session will be destroyed


@dataclasses.dataclass(frozen=True)
class GameStatus:
    Done = "done"
    Active = "active"
    Inactive = "inactive"
    Reset = "reset"


class GameExitStatus:
    """Exit status for game cleanup based on activity and player count."""
    ActiveWithOtherPlayers = "active_with_other_players"
    ActiveNoPlayers = "active_no_players"
    InactiveNoPlayers = "inactive_no_players"
    InactiveWithOtherPlayers = "inactive_with_other_players"


class _AvailableSlot:
    """Sentinel value indicating a human player slot is available.

    Adapted from RLLib's _NotProvided:
    https://github.com/ray-project/ray/rllib/utils/from_config.py#L261
    """

    class __AvailableSlot:
        pass

    instance = None

    def __init__(self):
        if _AvailableSlot.instance is None:
            _AvailableSlot.instance = _AvailableSlot.__AvailableSlot()


AvailableSlot = _AvailableSlot


class GameCallback:
    """Base callback interface for game lifecycle hooks."""

    def __init__(self, **kwargs) -> None:
        pass

    def on_episode_start(self, remote_game: ServerGame):
        pass

    def on_episode_end(self, remote_game: ServerGame):
        pass

    def on_game_tick_start(self, remote_game: ServerGame):
        pass

    def on_game_tick_end(self, remote_game: ServerGame):
        pass

    def on_graphics_start(self, remote_game: ServerGame):
        pass

    def on_graphics_end(self, remote_game: ServerGame):
        pass

    def on_waitroom_start(self, remote_game: ServerGame):
        pass

    def on_waitroom_join(self, remote_game: ServerGame):
        pass

    def on_waitroom_end(self, remote_game: ServerGame):
        pass

    def on_waitroom_timeout(self, remote_game: ServerGame):
        pass

    def on_game_end(self, remote_game: ServerGame):
        pass


class MultiCallback(GameCallback):
    """Aggregates multiple callbacks into a single callback interface."""

    def __init__(self, callbacks: list[GameCallback], **kwargs) -> None:
        # Initialize all callbacks
        self.callbacks = [callback() for callback in callbacks]

    def on_episode_start(self, remote_game: ServerGame):
        for callback in self.callbacks:
            callback.on_episode_start(remote_game)

    def on_episode_end(self, remote_game: ServerGame):
        for callback in self.callbacks:
            callback.on_episode_end(remote_game)

    def on_game_tick_start(self, remote_game: ServerGame):
        for callback in self.callbacks:
            callback.on_game_tick_start(remote_game)

    def on_game_tick_end(self, remote_game: ServerGame):
        for callback in self.callbacks:
            callback.on_game_tick_end(remote_game)

    def on_graphics_start(self, remote_game: ServerGame):
        for callback in self.callbacks:
            callback.on_graphics_start(remote_game)

    def on_graphics_end(self, remote_game: ServerGame):
        for callback in self.callbacks:
            callback.on_graphics_end(remote_game)

    def on_waitroom_start(self, remote_game: ServerGame):
        for callback in self.callbacks:
            callback.on_waitroom_start(remote_game)

    def on_waitroom_join(self, remote_game: ServerGame):
        for callback in self.callbacks:
            callback.on_waitroom_join(remote_game)

    def on_waitroom_end(self, remote_game: ServerGame):
        for callback in self.callbacks:
            callback.on_waitroom_end(remote_game)

    def on_waitroom_timeout(self, remote_game: ServerGame):
        for callback in self.callbacks:
            callback.on_waitroom_timeout(remote_game)

    def on_game_end(self, remote_game: ServerGame):
        for callback in self.callbacks:
            callback.on_game_end(remote_game)


class ServerGame:
    """Server-side game shell managing connection, room assignment, and player tracking.

    Game loop, tick, and environment methods were removed in Phase 92 cleanup.
    Phase 93 rebuilds the server game loop on this foundation.
    """

    def __init__(
        self,
        scene: typing.Any,
        game_id: int | None = None,
        experiment_config: dict = {},
    ):
        self.scene = scene
        self.status = GameStatus.Inactive
        self.session_state = SessionState.WAITING
        self.lock = threading.Lock()
        self.reset_event: eventlet.event.Event | None = None
        self.set_reset_event()

        self.document_focus_status: dict[str | int, bool] = (
            collections.defaultdict(lambda: True)
        )
        self.current_ping: dict[str | int, int] = collections.defaultdict(
            lambda: 0
        )

        self.human_players = {}
        self.bot_players = {}

        # Initialize player slots from scene's policy_mapping so that
        # add_player() / get_available_human_agent_ids() work correctly.
        # Human agents get an AvailableSlot sentinel; bots are recorded separately.
        if hasattr(scene, 'policy_mapping') and scene.policy_mapping:
            for agent_id, policy_type in scene.policy_mapping.items():
                if policy_type == configuration_constants.PolicyTypes.Human:
                    self.human_players[agent_id] = AvailableSlot
                else:
                    self.bot_players[agent_id] = policy_type

        self.game_uuid: str = str(uuid.uuid4())
        self.game_id: int | str = (
            game_id if game_id is not None else self.game_uuid
        )
        assert (
            game_id is not None
        ), f"Must pass valid game id! Got {game_id} but expected an int."

        self.episode_num: int = 0
        self.episode_rewards = collections.defaultdict(lambda: 0)
        self.total_rewards = collections.defaultdict(
            lambda: 0
        )
        self.total_positive_rewards = collections.defaultdict(
            lambda: 0
        )
        self.total_negative_rewards = collections.defaultdict(
            lambda: 0
        )
        self.prev_rewards: dict[str | int, float] = {}
        self.prev_actions: dict[str | int, str | int] = {}

        # Environment lifecycle (populated by _build_env / _load_policies)
        self.env = None
        self.observation = None
        self.policies: dict[str, Any] = {}
        self.pending_actions: dict[str | int, Any] = {}
        self.tick_num: int = 0

    def set_reset_event(self) -> None:
        """Reinitialize the reset event."""
        self.reset_event = eventlet.event.Event()

    # Valid session state transitions (SESS-01)
    VALID_TRANSITIONS = {
        SessionState.WAITING: {SessionState.MATCHED, SessionState.ENDED},
        SessionState.MATCHED: {SessionState.VALIDATING, SessionState.ENDED},
        SessionState.VALIDATING: {SessionState.PLAYING, SessionState.WAITING, SessionState.ENDED},
        SessionState.PLAYING: {SessionState.ENDED},
        SessionState.ENDED: set(),  # Terminal state
    }

    def transition_to(self, new_state: SessionState) -> bool:
        """Transition session to new state if valid.

        Args:
            new_state: Target session state

        Returns:
            True if transition successful, False if invalid
        """
        if new_state not in self.VALID_TRANSITIONS.get(self.session_state, set()):
            logger.error(
                f"Invalid session transition: {self.session_state} -> {new_state}. "
                f"Valid transitions from {self.session_state}: "
                f"{self.VALID_TRANSITIONS.get(self.session_state, set())}"
            )
            return False

        old_state = self.session_state
        self.session_state = new_state
        logger.info(f"Session {self.game_id}: {old_state.name} -> {new_state.name}")
        return True

    def get_available_human_agent_ids(self) -> list[str]:
        """List the available human player IDs"""
        return [
            agent_id
            for agent_id, subject_id in self.human_players.items()
            if subject_id is AvailableSlot
        ]

    def is_at_player_capacity(self) -> bool:
        """Check if there are any available human player IDs."""
        return not self.get_available_human_agent_ids()

    def cur_num_human_players(self) -> int:
        return len(
            [
                agent_id
                for agent_id, subject_id in self.human_players.items()
                if subject_id != AvailableSlot
            ]
        )

    def remove_human_player(self, subject_id) -> None:
        """Remove a human player from the game.

        Args:
            subject_id: The subject identifier to remove.

        Note: human_players is keyed by player_id (slot), with subject_id as value.
        We need to find the player_id that maps to this subject_id.
        """
        player_id_to_remove = None
        for player_id, sid in self.human_players.items():
            if sid == subject_id:
                player_id_to_remove = player_id
                break

        if player_id_to_remove is None:
            logger.warning(
                f"Attempted to remove {subject_id} but player wasn't found in human_players."
            )
            return

        self.human_players[player_id_to_remove] = AvailableSlot
        logger.debug(f"Removed {subject_id} from slot {player_id_to_remove}")

        if subject_id in self.document_focus_status:
            del self.document_focus_status[subject_id]
            del self.current_ping[subject_id]

    def is_ready_to_start(self) -> bool:
        ready = self.is_at_player_capacity()
        return ready

    def add_player(self, player_id: str | int, identifier: str | int) -> bool:
        """Add a player to the game.

        Returns True if the player was successfully added, False if the slot
        was not available (e.g., due to a race condition).
        """
        available_ids = self.get_available_human_agent_ids()
        if player_id not in available_ids:
            logger.error(
                f"Player slot {player_id} is not available! "
                f"Available IDs are: {available_ids}. "
                f"Attempted to add identifier: {identifier}"
            )
            return False

        self.human_players[player_id] = identifier
        logger.info(
            f"Successfully added player {identifier} to slot {player_id}. "
            f"Remaining slots: {self.get_available_human_agent_ids()}"
        )
        return True

    def update_document_focus_status_and_ping(
        self, player_identifier: str | int, hidden_status: bool, ping: int
    ) -> None:
        self.document_focus_status[player_identifier] = hidden_status
        self.current_ping[player_identifier] = ping

    def _build_env(self) -> None:
        """Create the environment from the scene's env_creator and env_config.

        Sets render_mode to 'interactive_gym' in the env config so the env
        produces Phaser-compatible state dicts from env.render().
        """
        env_config = dict(self.scene.env_config or {})
        env_config["render_mode"] = "interactive_gym"
        self.env = self.scene.env_creator(**env_config)
        logger.info(
            f"Game {self.game_id}: environment built via scene.env_creator"
        )

    def _load_policies(self) -> None:
        """Load bot policies server-side.

        Iterates policy_mapping; for each non-Human agent, loads the policy
        using scene.load_policy_fn (if provided). Random agents store None.
        """
        self.policies = {}
        for agent_id, policy_type in self.scene.policy_mapping.items():
            if policy_type == configuration_constants.PolicyTypes.Human:
                continue
            if policy_type == configuration_constants.PolicyTypes.Random:
                self.policies[agent_id] = None
            elif self.scene.load_policy_fn is not None:
                self.policies[agent_id] = self.scene.load_policy_fn(
                    agent_id, policy_type
                )
            else:
                logger.warning(
                    f"Game {self.game_id}: no load_policy_fn for bot agent "
                    f"{agent_id} with policy type {policy_type}"
                )
                self.policies[agent_id] = None
        logger.info(
            f"Game {self.game_id}: loaded policies for {list(self.policies.keys())}"
        )

    def _get_bot_action(self, agent_id: str | int) -> Any:
        """Get an action for a bot agent.

        If the agent has a policy and policy_inference_fn, uses those.
        If the agent's policy type is Random, samples from the env action space.
        """
        policy_type = self.scene.policy_mapping.get(agent_id)
        if policy_type == configuration_constants.PolicyTypes.Random:
            # Sample random action from the env's action space for this agent
            if hasattr(self.env, "action_space"):
                action_space = self.env.action_space
                # For multi-agent envs the action space may be a dict
                if hasattr(action_space, "__getitem__"):
                    try:
                        return action_space[agent_id].sample()
                    except (KeyError, TypeError):
                        return action_space.sample()
                return action_space.sample()
            return self.scene.default_action

        policy = self.policies.get(agent_id)
        if policy is not None and self.scene.policy_inference_fn is not None:
            return self.scene.policy_inference_fn(
                agent_id, policy, self.observation
            )

        return self.scene.default_action

    def reset(self) -> None:
        """Reset the environment and prepare for a new episode."""
        result = self.env.reset()
        # env.reset() returns (obs, info) or just obs depending on API
        if isinstance(result, tuple):
            self.observation = result[0]
        else:
            self.observation = result

        self.episode_num += 1
        self.episode_rewards = collections.defaultdict(lambda: 0)
        self.tick_num = 0
        self.status = GameStatus.Active
        self.prev_actions = {}
        self.pending_actions = {}
        logger.info(
            f"Game {self.game_id}: reset for episode {self.episode_num}"
        )

    def step(self):
        """Step the environment with current actions.

        Builds action dict for all agents:
        - Human agents: uses pending_actions or falls back per action_population_method
        - Bot agents: calls _get_bot_action

        Returns:
            Tuple of (observations, rewards, terminated, truncated, infos)
        """
        actions = {}
        for agent_id, policy_type in self.scene.policy_mapping.items():
            if policy_type == configuration_constants.PolicyTypes.Human:
                # Human agent: use pending action or fallback
                action = self.pending_actions.get(agent_id)
                if action is None:
                    pop_method = self.scene.action_population_method
                    if (
                        pop_method
                        == configuration_constants.ActionSettings.PreviousSubmittedAction
                    ):
                        action = self.prev_actions.get(
                            agent_id, self.scene.default_action
                        )
                    else:
                        # DefaultAction or any other
                        action = self.scene.default_action
                actions[agent_id] = action
            else:
                actions[agent_id] = self._get_bot_action(agent_id)

        # Step the environment
        observations, rewards, terminated, truncated, infos = self.env.step(
            actions
        )
        self.observation = observations

        # Update reward tracking
        for agent_id in self.scene.policy_mapping:
            reward = rewards.get(agent_id, 0) if isinstance(rewards, dict) else rewards
            self.episode_rewards[agent_id] += reward
            self.total_rewards[agent_id] += reward
            if reward > 0:
                self.total_positive_rewards[agent_id] += reward
            elif reward < 0:
                self.total_negative_rewards[agent_id] += reward

        self.prev_actions = actions
        self.prev_rewards = rewards if isinstance(rewards, dict) else {
            aid: rewards for aid in self.scene.policy_mapping
        }
        self.tick_num += 1
        self.pending_actions = {}

        # Determine episode status
        if isinstance(terminated, dict):
            all_terminated = all(terminated.values())
        else:
            all_terminated = bool(terminated)

        if isinstance(truncated, dict):
            all_truncated = all(truncated.values())
        else:
            all_truncated = bool(truncated)

        if all_terminated or all_truncated:
            if self.episode_num < self.scene.num_episodes:
                self.status = GameStatus.Reset
            else:
                self.status = GameStatus.Done

        return (observations, rewards, terminated, truncated, infos)

    def enqueue_action(self, agent_id: str | int, action: Any) -> None:
        """Store a player's latest action for the next step."""
        self.pending_actions[agent_id] = action

    def tear_down(self):
        self.status = GameStatus.Inactive
        if self.env is not None:
            try:
                self.env.close()
            except Exception as e:
                logger.warning(f"Game {self.game_id}: error closing env: {e}")
