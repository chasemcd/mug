from __future__ import annotations

import collections
import dataclasses
import logging
import queue
import threading
import time
import typing
import uuid
from enum import Enum, auto

import eventlet
import numpy as np
from gymnasium import spaces

from interactive_gym.configurations import configuration_constants
from interactive_gym.server import thread_utils
from interactive_gym.scenes import gym_scene

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


class RemoteGameV2:
    def __init__(
        self,
        scene: gym_scene.GymScene,
        game_id: int | None = None,
        experiment_config: dict = {},
    ):
        self.scene = scene
        self.status = GameStatus.Inactive
        self.session_state = SessionState.WAITING  # Session lifecycle state (SESS-01)
        self.lock = threading.Lock()
        self.reset_event: eventlet.event.Event | None = None
        self.set_reset_event()

        self.document_focus_status: dict[str | int, bool] = (
            collections.defaultdict(lambda: True)
        )
        self.current_ping: dict[str | int, int] = collections.defaultdict(
            lambda: 0
        )

        # Players and actions
        self.pending_actions = None
        self.reset_pending_actions()

        self.state_queues = None
        self.reset_state_queues()

        self.human_players = {}
        self.bot_players = {}
        self.bot_threads = {}

        # Game environment
        self.env = None
        self.obs: np.ndarray | dict[str, typing.Any] | None = None
        self.game_uuid: str = str(uuid.uuid4())
        self.game_id: int | str = (
            game_id if game_id is not None else self.game_uuid
        )
        assert (
            game_id is not None
        ), f"Must pass valid game id! Got {game_id} but expected an int."

        self.tick_num: int = 0
        self.episode_num: int = 0
        self.episode_rewards = collections.defaultdict(lambda: 0)
        self.total_rewards = collections.defaultdict(
            lambda: 0
        )  # score across episodes
        self.total_positive_rewards = collections.defaultdict(
            lambda: 0
        )  # sum of positives
        self.total_negative_rewards = collections.defaultdict(
            lambda: 0
        )  # sum of negatives
        self.prev_rewards: dict[str | int, float] = {}
        self.prev_actions: dict[str | int, str | int] = {}

        self._build()

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

    def _build_env(self) -> None:
        self.env = self.scene.env_creator(
            **self.scene.env_config, render_mode="rgb_array"
        )

    def _load_policies(self) -> None:
        """Load and instantiates all policies"""
        for agent_id, policy_id in self.scene.policy_mapping.items():
            if policy_id == configuration_constants.PolicyTypes.Human:
                self.human_players[agent_id] = thread_utils.AvailableSlot
            elif policy_id == configuration_constants.PolicyTypes.Random:
                self.bot_players[agent_id] = policy_id
            elif self.scene.run_through_pyodide:
                continue
            else:
                assert (
                    self.scene.load_policy_fn is not None
                ), "Must provide a method to load policies via policy name to RemoteConfig!"
                self.bot_players[agent_id] = self.scene.load_policy_fn(
                    policy_id
                )

    def _init_bot_threads(self):
        # TODO(chase): put this in a separate function
        for agent_id, pid in self.bot_players.items():
            if pid == configuration_constants.PolicyTypes.Random:
                continue
            self.bot_threads[agent_id] = eventlet.spawn(
                self.policy_consumer, agent_id=agent_id
            )

    def policy_consumer(self, agent_id: str | int) -> None:
        while self.status == GameStatus.Active:

            # Game hangs if we don't do this
            time.sleep(1 / self.scene.fps)

            try:
                state = self.state_queues[agent_id].get(block=False)
            except queue.Empty:
                continue

            policy = self.bot_players[agent_id]
            action = self.scene.policy_inference_fn(state, policy)
            self.enqueue_action(agent_id, action)

    def get_available_human_agent_ids(self) -> list[str]:
        """List the available human player IDs"""
        return [
            agent_id
            for agent_id, subject_id in self.human_players.items()
            if subject_id is thread_utils.AvailableSlot
        ]

    def is_at_player_capacity(self) -> bool:
        """Check if there are any available human player IDs."""
        return not self.get_available_human_agent_ids()

    def cur_num_human_players(self) -> int:
        return len(
            [
                agent_id
                for agent_id, subject_id in self.human_players.items()
                if subject_id != thread_utils.AvailableSlot
            ]
        )

    def remove_human_player(self, subject_id) -> None:
        """Remove a human player from the game.

        Args:
            subject_id: The subject identifier to remove.

        Note: human_players is keyed by player_id (slot), with subject_id as value.
        We need to find the player_id that maps to this subject_id.
        """
        # Find the player_id (slot) that has this subject_id
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

        self.human_players[player_id_to_remove] = thread_utils.AvailableSlot
        logger.debug(f"Removed {subject_id} from slot {player_id_to_remove}")

        if subject_id in self.document_focus_status:
            del self.document_focus_status[subject_id]
            del self.current_ping[subject_id]

    def is_ready_to_start(self) -> bool:
        ready = self.is_at_player_capacity()
        return ready

    def _build(self):
        if not self.scene.run_through_pyodide:
            self._build_env()
        self._load_policies()

    def tear_down(self):
        self.status = GameStatus.Inactive

        for bot_thread in self.bot_threads.values():
            bot_thread.kill()

        for q in self.pending_actions.values():
            q.queue.clear()

    def enqueue_action(self, subject_id, action) -> None:
        """Queue an action for a human player"""
        if self.status != GameStatus.Active:
            return

        try:
            self.pending_actions[subject_id].put(action, block=False)
        except queue.Full:
            pass

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

    def tick(self) -> None:

        # If the queue is empty, we have a mechanism for deciding which action to submit
        # Either the previous submitted action or the default action.
        player_actions = {}

        for pid, sid in self.human_players.items():
            action = None
            # Attempt to get an action from the action queue
            # If there's no action, use default or previous depending
            # on the method specified.

            # TODO(chase): Right now pending actions is keyed by the game agent id
            # rather than the subject id. Check if this is correct or we
            # should be keying it by subject id.
            index_id = pid

            try:
                action = self.pending_actions[index_id].get(block=False)
            except queue.Empty:
                if (
                    self.scene.action_population_method
                    == configuration_constants.ActionSettings.PreviousSubmittedAction
                ):
                    action = self.prev_actions.get(index_id)

            if action is None:
                action = self.scene.default_action

            player_actions[pid] = action

        # Bot actions
        for pid, bot in self.bot_players.items():

            # set default action
            if (
                self.scene.action_population_method
                == configuration_constants.ActionSettings.PreviousSubmittedAction
            ):
                action = self.prev_actions.get(pid)
                if action is None:
                    action = self.scene.default_action
                player_actions[pid] = self.scene.default_action
            elif (
                self.scene.action_population_method
                == configuration_constants.ActionSettings.DefaultAction
            ):
                player_actions[pid] = self.scene.default_action
            else:
                raise NotImplementedError(
                    f"Action population method logic not specified for method: {self.scene.action_population_method}"
                )

            # If the bot is random, just sample the action space at
            # frame_skip intervals
            if (
                bot == configuration_constants.PolicyTypes.Random
                and self.tick_num % self.scene.frame_skip == 0
            ):
                if isinstance(self.env.action_space, spaces.Dict) or isinstance(
                    self.env.action_space, dict
                ):
                    player_actions[pid] = self.env.action_space[pid].sample()
                elif callable(self.env.action_space):
                    player_actions[pid] = self.env.action_space(pid).sample()
                else:
                    player_actions[pid] = self.env.action_space.sample()

            # If we have a specified policy, pop an action from the pending actions queue
            # if there are any
            elif self.pending_actions[pid].qsize() > 0:
                player_actions[pid] = self.pending_actions[pid].get(block=False)

        self.prev_actions = player_actions
        try:
            self.obs, rewards, terminateds, truncateds, _ = self.env.step(
                player_actions
            )

        except AssertionError:
            player_actions = list(player_actions.values())[0]
            self.obs, rewards, terminateds, truncateds, _ = self.env.step(
                player_actions
            )

        self.prev_rewards = (
            rewards if isinstance(rewards, dict) else {"reward": rewards}
        )

        if self.tick_num % self.scene.frame_skip == 0:
            self.enqueue_observations()

        if not isinstance(rewards, dict):
            self.episode_rewards[0] += rewards
            self.total_rewards[0] += rewards
        else:
            for k, v in rewards.items():
                self.episode_rewards[k] += v
                self.total_rewards[k] += v
                self.total_positive_rewards[k] += max(0, v)
                self.total_negative_rewards[k] += min(0, v)

        if isinstance(terminateds, dict):
            terminateds = all([t for t in terminateds.values()])
            truncateds = all([t for t in truncateds.values()])

        self.tick_num += 1
        if terminateds or truncateds:
            if self.episode_num < self.scene.num_episodes:
                self.status = GameStatus.Reset
            else:
                self.status = GameStatus.Done

    def enqueue_observations(self) -> None:
        """Add self.obs to the state queues for all bots"""
        if self.status != GameStatus.Active:
            return

        if not self.bot_players:
            return

        for pid, obs in self.obs.items():
            if pid not in self.bot_players:
                continue

            try:
                self.state_queues[pid].put(obs, block=False)
            except queue.Full:
                pass

    def reset_pending_actions(self) -> None:
        self.pending_actions = collections.defaultdict(
            lambda: queue.Queue(maxsize=1)
        )

    def reset_state_queues(self) -> None:
        self.state_queues = collections.defaultdict(
            lambda: queue.Queue(maxsize=1)
        )

    def reset(self, seed: int | None = None) -> None:
        self.reset_pending_actions()
        self.prev_actions = {}
        self.prev_rewards = {}
        self.obs, _ = self.env.reset(seed=seed)
        self.status = GameStatus.Active

        self._init_bot_threads()

        self.tick_num = 0

        self.enqueue_observations()

        self.episode_num += 1
        self.episode_rewards = collections.defaultdict(lambda: 0)
