from __future__ import annotations

import collections
import dataclasses
import logging
import threading
import typing
import uuid
from enum import Enum, auto

import eventlet

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

    def tear_down(self):
        self.status = GameStatus.Inactive
