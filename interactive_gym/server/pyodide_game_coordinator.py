"""
Pyodide Game Coordinator for Multiplayer Support

Coordinates client-side Pyodide games by:
- Generating shared RNG seeds for determinism
- Collecting and broadcasting player actions
- Verifying state synchronization across clients
- Managing host election and migration
- Routing data logging to prevent duplicates
"""

from __future__ import annotations

import dataclasses
import threading
import logging
import random
import time
from typing import Any, Dict

import eventlet
import flask_socketio

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class PyodideGameState:
    """State for a single Pyodide multiplayer game."""

    game_id: str
    host_player_id: str | int | None
    players: Dict[str | int, str]  # player_id -> socket_id
    pending_actions: Dict[str | int, Any]
    frame_number: int
    action_ready_event: threading.Event
    state_hashes: Dict[str | int, str]
    verification_frame: int  # Next frame to verify
    is_active: bool
    rng_seed: int  # Shared seed for deterministic AI
    num_expected_players: int
    action_timeout_seconds: float
    created_at: float
    accumulated_frame_data: list = dataclasses.field(default_factory=list)  # Frame data from host


class PyodideGameCoordinator:
    """
    Coordinates multiplayer Pyodide games.

    Key responsibilities:
    1. Generate and distribute shared RNG seeds
    2. Collect actions from all players each frame
    3. Broadcast actions when all received (or timeout)
    4. Verify state synchronization periodically
    5. Handle host election and migration
    6. Route data logging to host only
    """

    def __init__(self, sio: flask_socketio.SocketIO):
        self.sio = sio
        self.games: Dict[str, PyodideGameState] = {}
        self.lock = threading.Lock()

        # Configuration
        self.verification_frequency = 300  # Verify every N frames (reduced from 30)
        self.action_timeout = 5.0  # Seconds to wait for actions
        self.max_games = 1000  # Prevent memory exhaustion

        # Statistics
        self.total_games_created = 0
        self.total_desyncs_detected = 0
        self.total_host_migrations = 0

        logger.info("PyodideGameCoordinator initialized")

    def create_game(self, game_id: str, num_players: int) -> PyodideGameState:
        """
        Initialize a new Pyodide multiplayer game.

        Args:
            game_id: Unique identifier for the game
            num_players: Expected number of human players

        Returns:
            PyodideGameState object

        Raises:
            ValueError: If max games exceeded
        """
        with self.lock:
            if len(self.games) >= self.max_games:
                raise ValueError(f"Maximum games ({self.max_games}) exceeded")

            # Generate seed using Python's random (server-side)
            rng_seed = random.randint(0, 2**32 - 1)

            game_state = PyodideGameState(
                game_id=game_id,
                host_player_id=None,  # Will be set when first player joins
                players={},
                pending_actions={},
                frame_number=0,
                action_ready_event=threading.Event(),
                state_hashes={},
                verification_frame=self.verification_frequency,
                is_active=False,
                rng_seed=rng_seed,
                num_expected_players=num_players,
                action_timeout_seconds=self.action_timeout,
                created_at=time.time()
            )

            self.games[game_id] = game_state
            self.total_games_created += 1

            logger.info(
                f"Created Pyodide game {game_id} for {num_players} players "
                f"with seed {rng_seed}"
            )

            return game_state

    def add_player(self, game_id: str, player_id: str | int, socket_id: str):
        """
        Add a player to the game and elect host if needed.

        The first player to join becomes the host. Host is responsible for:
        - Sending data logs (others send nothing to avoid duplicates)
        - Providing full state for resync if desync detected

        Args:
            game_id: Game identifier
            player_id: Player identifier (0, 1, 2, ...)
            socket_id: Player's socket connection ID
        """
        with self.lock:
            if game_id not in self.games:
                logger.error(f"Attempted to add player to non-existent game {game_id}")
                return

            game = self.games[game_id]
            game.players[player_id] = socket_id

            # First player becomes host
            if game.host_player_id is None:
                game.host_player_id = player_id

                self.sio.emit('pyodide_host_elected',
                             {
                                 'is_host': True,
                                 'player_id': player_id,
                                 'game_id': game_id,
                                 'game_seed': game.rng_seed,
                                 'num_players': game.num_expected_players
                             },
                             room=socket_id)

                logger.info(
                    f"Player {player_id} elected as host for game {game_id} "
                    f"(seed: {game.rng_seed})"
                )
            else:
                # Non-host player
                self.sio.emit('pyodide_host_elected',
                             {
                                 'is_host': False,
                                 'player_id': player_id,
                                 'game_id': game_id,
                                 'host_id': game.host_player_id,
                                 'game_seed': game.rng_seed,
                                 'num_players': game.num_expected_players
                             },
                             room=socket_id)

                logger.info(
                    f"Player {player_id} joined game {game_id} as client "
                    f"(host: {game.host_player_id})"
                )

            # Check if game is ready to start
            if len(game.players) == game.num_expected_players:
                self._start_game(game_id)

    def _start_game(self, game_id: str):
        """Mark game as active once all players joined."""
        game = self.games[game_id]
        game.is_active = True

        logger.info(f"Emitting pyodide_game_ready to room {game_id} with players {list(game.players.keys())}")
        self.sio.emit('pyodide_game_ready',
                     {'game_id': game_id, 'players': list(game.players.keys())},
                     room=game_id)

        logger.info(f"Game {game_id} started with {len(game.players)} players")

    def receive_action(
        self,
        game_id: str,
        player_id: str | int,
        action: Any,
        frame_number: int
    ):
        """
        Receive action from a player and broadcast to others immediately.

        Action Queue approach: No waiting for all players. Each action is
        immediately relayed to other clients who queue it for their next step.

        Args:
            game_id: Game identifier
            player_id: Player who sent the action
            action: The action value (int, dict, etc.)
            frame_number: Frame number (for logging/debugging)
        """
        with self.lock:
            if game_id not in self.games:
                logger.warning(f"Action received for non-existent game {game_id}")
                return

            game = self.games[game_id]

            if not game.is_active:
                logger.warning(f"Action received for inactive game {game_id}")
                return

            # Track last known action from this player (for debugging)
            game.pending_actions[player_id] = action

            # Log frame info for debugging (no longer used for sync)
            logger.debug(
                f"Game {game_id}: Received action {action} from player {player_id} "
                f"at frame {frame_number}"
            )

            # Broadcast to ALL OTHER players immediately (Action Queue approach)
            for other_player_id, socket_id in game.players.items():
                if other_player_id != player_id:
                    self.sio.emit('pyodide_other_player_action', {
                        'player_id': player_id,
                        'action': action,
                        'frame_number': frame_number,
                        'timestamp': time.time()
                    }, room=socket_id)

            logger.debug(
                f"Game {game_id}: Relayed action from player {player_id} "
                f"to {len(game.players) - 1} other player(s)"
            )

    # Keep _broadcast_actions for backwards compatibility but it's no longer used
    def _broadcast_actions(self, game_id: str):
        """
        [DEPRECATED] Broadcast collected actions to all players.

        This was used in the lock-step approach. Now using Action Queue approach
        where actions are relayed immediately in receive_action().
        """
        game = self.games[game_id]

        actions_payload = {
            'type': 'pyodide_actions_ready',
            'game_id': game_id,
            'actions': game.pending_actions.copy(),
            'frame_number': game.frame_number,
            'timestamp': time.time()
        }

        # Broadcast to all players in game
        self.sio.emit('pyodide_actions_ready',
                     actions_payload,
                     room=game_id)

        logger.debug(
            f"Game {game_id} frame {game.frame_number}: "
            f"Broadcasted actions {game.pending_actions}"
        )

        # Clear pending actions and increment frame
        game.pending_actions.clear()
        game.frame_number += 1

        # Check if we need to verify state this frame
        if game.frame_number >= game.verification_frame:
            self._request_state_verification(game_id)

    def _request_state_verification(self, game_id: str):
        """
        Request state hash from all players for verification.

        Verification detects desyncs early before they cascade.
        """
        game = self.games[game_id]

        self.sio.emit('pyodide_verify_state',
                     {'frame_number': game.frame_number},
                     room=game_id)

        game.verification_frame = game.frame_number + self.verification_frequency
        game.state_hashes.clear()

        logger.debug(f"Game {game_id}: Requested state verification at frame {game.frame_number}")

    def receive_state_hash(
        self,
        game_id: str,
        player_id: str | int,
        state_hash: str,
        frame_number: int
    ):
        """
        Collect and verify state hashes from players.

        Args:
            game_id: Game identifier
            player_id: Player who sent the hash
            state_hash: SHA256 hash of game state
            frame_number: Frame number for this hash
        """
        with self.lock:
            if game_id not in self.games:
                return

            game = self.games[game_id]
            game.state_hashes[player_id] = state_hash

            logger.debug(
                f"Game {game_id} frame {frame_number}: "
                f"Received hash from player {player_id} "
                f"({len(game.state_hashes)}/{len(game.players)} received)"
            )

            # Once all hashes received, verify
            if len(game.state_hashes) == len(game.players):
                self._verify_synchronization(game_id, frame_number)

    def _verify_synchronization(self, game_id: str, frame_number: int):
        """
        Check if all players have matching state hashes.

        If hashes don't match, desync has occurred and we need to resync.
        """
        game = self.games[game_id]

        hashes = list(game.state_hashes.values())
        unique_hashes = set(hashes)

        if len(unique_hashes) == 1:
            # All hashes match - synchronized! ✓
            logger.info(
                f"Game {game_id} frame {frame_number}: "
                f"States synchronized ✓ (hash: {hashes[0][:8]}...)"
            )
        else:
            # Desync detected! ✗
            self.total_desyncs_detected += 1

            logger.error(
                f"Game {game_id} frame {frame_number}: "
                f"DESYNC DETECTED! "
                f"Unique hashes: {len(unique_hashes)}"
            )

            # Log which players have which hashes
            for player_id, hash_val in game.state_hashes.items():
                logger.error(f"  Player {player_id}: {hash_val[:16]}...")

            self._handle_desync(game_id, frame_number)

    def _handle_desync(self, game_id: str, frame_number: int):
        """
        Handle desynchronization by requesting resync from host.

        Process:
        1. Pause all clients
        2. Request full state from host
        3. Host sends serialized state
        4. Broadcast state to non-host clients
        5. Clients restore state
        6. Resume game
        """
        game = self.games[game_id]

        # Request full state from host
        host_socket = game.players[game.host_player_id]
        self.sio.emit('pyodide_request_full_state',
                     {'frame_number': frame_number},
                     room=host_socket)

        # Notify all players to pause and wait for resync
        self.sio.emit('pyodide_pause_for_resync',
                     {'frame_number': frame_number},
                     room=game_id)

        logger.info(f"Game {game_id}: Initiated resync from host {game.host_player_id}")

    def handle_resync_request(
        self,
        game_id: str,
        requesting_player_id: str | int,
        frame_number: int
    ):
        """
        Handle a resync request from a client that has fallen behind.

        This is triggered when a client's action queue grows too large,
        indicating it cannot keep up. We request state from host and
        send it to the requesting client.

        Args:
            game_id: Game identifier
            requesting_player_id: Player who requested resync
            frame_number: Frame number of requesting client
        """
        with self.lock:
            if game_id not in self.games:
                logger.warning(f"Resync request for non-existent game {game_id}")
                return

            game = self.games[game_id]

            logger.info(
                f"Game {game_id}: Player {requesting_player_id} requested resync "
                f"at frame {frame_number}"
            )

            # Use existing desync handler to request state from host
            self._handle_desync(game_id, frame_number)

    def receive_full_state(self, game_id: str, full_state: dict):
        """
        Receive full state from host and broadcast to clients for resync.

        Args:
            game_id: Game identifier
            full_state: Serialized game state from host
        """
        game = self.games[game_id]

        # Broadcast to non-host players
        for player_id, socket_id in game.players.items():
            if player_id != game.host_player_id:
                self.sio.emit('pyodide_apply_full_state',
                             {'state': full_state},
                             room=socket_id)

        logger.info(f"Game {game_id}: Resynced all clients from host")

    def log_data(self, game_id: str, player_id: str | int, data: dict):
        """
        Route data logging - only accept data from host player.

        This prevents duplicate data logging. Non-host players send data
        but it's rejected by this function.

        Args:
            game_id: Game identifier
            player_id: Player attempting to log data
            data: Data to log

        Returns:
            The data if from host, None if from non-host (rejected)
        """
        with self.lock:
            if game_id not in self.games:
                logger.warning(f"Data log for non-existent game {game_id}")
                return None

            game = self.games[game_id]

            # Only log data from host
            if player_id != game.host_player_id:
                logger.debug(
                    f"Rejected data from non-host player {player_id} "
                    f"in game {game_id}"
                )
                return None

            # Host data - accept for logging
            logger.debug(f"Accepted data from host {player_id} in game {game_id}")
            return data

    def remove_player(self, game_id: str, player_id: str | int):
        """
        Handle player disconnection.

        If host disconnects, elect new host and trigger resync.
        If all players disconnect, remove game.

        Args:
            game_id: Game identifier
            player_id: Player who disconnected
        """
        with self.lock:
            if game_id not in self.games:
                return

            game = self.games[game_id]

            if player_id not in game.players:
                return

            was_host = (player_id == game.host_player_id)
            del game.players[player_id]

            logger.info(
                f"Player {player_id} disconnected from game {game_id} "
                f"({'host' if was_host else 'client'})"
            )

            # If host disconnected, elect new host
            if was_host and len(game.players) > 0:
                self._elect_new_host(game_id)

            # If no players left, remove game
            if len(game.players) == 0:
                del self.games[game_id]
                logger.info(f"Removed empty game {game_id}")

    def _elect_new_host(self, game_id: str):
        """
        Elect a new host when the current host disconnects.

        New host must:
        1. Start logging data
        2. Provide full state for resync (since states may have diverged)

        Args:
            game_id: Game identifier
        """
        game = self.games[game_id]

        # Choose first remaining player as new host
        new_host_id = list(game.players.keys())[0]
        game.host_player_id = new_host_id
        new_host_socket = game.players[new_host_id]

        self.total_host_migrations += 1

        # Notify new host
        self.sio.emit('pyodide_host_elected',
                     {
                         'is_host': True,
                         'promoted': True,
                         'game_seed': game.rng_seed
                     },
                     room=new_host_socket)

        # Notify other players
        for player_id, socket_id in game.players.items():
            if player_id != new_host_id:
                self.sio.emit('pyodide_host_changed',
                             {'new_host_id': new_host_id},
                             room=socket_id)

        logger.info(
            f"Elected new host {new_host_id} for game {game_id} "
            f"(migration #{self.total_host_migrations})"
        )

        # Trigger resync from new host
        self._handle_desync(game_id, game.frame_number)

    def get_stats(self) -> dict:
        """Get coordinator statistics for monitoring/debugging."""
        return {
            'active_games': len(self.games),
            'total_games_created': self.total_games_created,
            'total_desyncs_detected': self.total_desyncs_detected,
            'total_host_migrations': self.total_host_migrations,
        }
