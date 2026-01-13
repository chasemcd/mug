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
    player_subjects: Dict[str | int, str]  # player_id -> subject_id (participant name)
    pending_actions: Dict[str | int, Any]
    frame_number: int
    action_ready_event: threading.Event
    state_hashes: Dict[int, Dict[str | int, str]]  # frame_number -> {player_id -> hash}
    verification_frame: int  # Next frame to verify
    is_active: bool
    rng_seed: int  # Shared seed for deterministic AI
    num_expected_players: int
    action_timeout_seconds: float
    created_at: float

    # State broadcast/sync interval (frames between state verification or server broadcasts)
    state_broadcast_interval: int = 30

    # Server-authoritative mode fields
    server_authoritative: bool = False
    server_runner: Any = None  # ServerGameRunner instance when enabled

    # Diagnostics for lag tracking
    last_action_times: Dict[str | int, float] = dataclasses.field(default_factory=dict)  # player_id -> last action timestamp
    action_delays: Dict[str | int, list] = dataclasses.field(default_factory=dict)  # player_id -> recent delays
    last_diagnostics_log: float = 0.0


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
        self.action_timeout = 5.0  # Seconds to wait for actions
        self.max_games = 1000  # Prevent memory exhaustion

        # Statistics
        self.total_games_created = 0
        self.total_desyncs_detected = 0
        self.total_host_migrations = 0

        logger.info("PyodideGameCoordinator initialized")

    def create_game(
        self,
        game_id: str,
        num_players: int,
        server_authoritative: bool = False,
        environment_code: str | None = None,
        state_broadcast_interval: int = 30,
    ) -> PyodideGameState:
        """
        Initialize a new Pyodide multiplayer game.

        Args:
            game_id: Unique identifier for the game
            num_players: Expected number of human players
            server_authoritative: If True, server runs parallel env for state sync
            environment_code: Python code to initialize environment (required if server_authoritative)
            state_broadcast_interval: Frames between server state broadcasts

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
                player_subjects={},  # player_id -> subject_id mapping
                pending_actions={},
                frame_number=0,
                action_ready_event=threading.Event(),
                state_hashes={},
                verification_frame=state_broadcast_interval,  # First verification after this many frames
                is_active=False,
                rng_seed=rng_seed,
                num_expected_players=num_players,
                action_timeout_seconds=self.action_timeout,
                created_at=time.time(),
                state_broadcast_interval=state_broadcast_interval,
                server_authoritative=server_authoritative,
            )

            # Create server runner if server_authoritative mode enabled
            if server_authoritative and environment_code:
                from interactive_gym.server.server_game_runner import ServerGameRunner

                game_state.server_runner = ServerGameRunner(
                    game_id=game_id,
                    environment_code=environment_code,
                    num_players=num_players,
                    state_broadcast_interval=state_broadcast_interval,
                    sio=self.sio,
                )
                logger.info(
                    f"Created ServerGameRunner for game {game_id} "
                    f"(broadcast every {state_broadcast_interval} frames)"
                )

            self.games[game_id] = game_state
            self.total_games_created += 1

            logger.info(
                f"Created Pyodide game {game_id} for {num_players} players "
                f"with seed {rng_seed}"
                f"{' (server-authoritative)' if server_authoritative else ''}"
            )

            return game_state

    def add_player(
        self,
        game_id: str,
        player_id: str | int,
        socket_id: str,
        subject_id: str | None = None
    ):
        """
        Add a player to the game and elect host if needed.

        The first player to join becomes the host. Host is responsible for:
        - Sending data logs (others send nothing to avoid duplicates)
        - Providing full state for resync if desync detected

        Args:
            game_id: Game identifier
            player_id: Player identifier (0, 1, 2, ...)
            socket_id: Player's socket connection ID
            subject_id: Subject/participant identifier (for data logging)
        """
        with self.lock:
            if game_id not in self.games:
                logger.error(f"Attempted to add player to non-existent game {game_id}")
                return

            game = self.games[game_id]
            game.players[player_id] = socket_id
            if subject_id is not None:
                game.player_subjects[player_id] = subject_id

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

        # Initialize server runner if enabled
        if game.server_authoritative and game.server_runner:
            # Add all players to the server runner
            for player_id in game.players.keys():
                game.server_runner.add_player(player_id)

            # Initialize with same seed as clients
            success = game.server_runner.initialize_environment(game.rng_seed)
            if success:
                logger.info(
                    f"Server runner initialized for game {game_id} "
                    f"with seed {game.rng_seed}"
                )
            else:
                logger.error(
                    f"Failed to initialize server runner for game {game_id}, "
                    f"falling back to host-based sync"
                )
                game.server_authoritative = False
                game.server_runner = None

        logger.info(
            f"Emitting pyodide_game_ready to room {game_id} with players {list(game.players.keys())}, "
            f"server_authoritative={game.server_authoritative}"
        )
        self.sio.emit('pyodide_game_ready',
                     {
                         'game_id': game_id,
                         'players': list(game.players.keys()),
                         'player_subjects': game.player_subjects,  # player_id -> subject_id mapping
                         'server_authoritative': game.server_authoritative,  # Tell clients if server is authoritative
                     },
                     room=game_id)

        # Broadcast initial episode state so clients can sync before starting
        # Clients wait for this server_episode_start event before beginning the game loop
        if game.server_authoritative and game.server_runner:
            game.server_runner.broadcast_state(event_type="server_episode_start")
            logger.info(
                f"Broadcast initial episode state for game {game_id}"
            )

        logger.info(
            f"Game {game_id} started with {len(game.players)} players"
            f"{' (server-authoritative)' if game.server_authoritative else ' (host-based)'}"
        )

    def receive_action(
        self,
        game_id: str,
        player_id: str | int,
        action: Any,
        frame_number: int,
        client_timestamp: float | None = None
    ):
        """
        Receive action from a player and broadcast to others immediately.

        Action Queue approach: No waiting for all players. Each action is
        immediately relayed to other clients who queue it for their next step.

        If server_authoritative mode is enabled, also feeds the action to
        the server runner which steps when all actions for a frame are received.

        Args:
            game_id: Game identifier
            player_id: Player who sent the action
            action: The action value (int, dict, etc.)
            frame_number: Frame number (for logging/debugging)
            client_timestamp: Client-side timestamp when action was sent (for lag tracking)
        """
        with self.lock:
            if game_id not in self.games:
                logger.warning(f"Action received for non-existent game {game_id}")
                return

            game = self.games[game_id]

            if not game.is_active:
                logger.warning(f"Action received for inactive game {game_id}")
                return

            # Track timing for diagnostics
            now = time.time()
            player_id_str = str(player_id)

            # Calculate inter-action delay for this player
            if player_id_str in game.last_action_times:
                delay = now - game.last_action_times[player_id_str]
                if player_id_str not in game.action_delays:
                    game.action_delays[player_id_str] = []
                game.action_delays[player_id_str].append(delay)
                # Keep only last 50 measurements
                if len(game.action_delays[player_id_str]) > 50:
                    game.action_delays[player_id_str].pop(0)

            game.last_action_times[player_id_str] = now

            # Log diagnostics periodically (every 5 seconds)
            if now - game.last_diagnostics_log > 5.0:
                self._log_game_diagnostics(game)
                game.last_diagnostics_log = now

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

            # Feed action to server runner if enabled (frame-aligned stepper)
            if game.server_authoritative and game.server_runner:
                all_received = game.server_runner.receive_action(
                    player_id, action, frame_number
                )

                if all_received:
                    # Step the server environment
                    result = game.server_runner.step_frame(frame_number)

                    if result:
                        # Broadcast state if it's time
                        if result.get("should_broadcast"):
                            game.server_runner.broadcast_state()

                        # Handle episode end
                        if result.get("episode_done"):
                            game.server_runner.handle_episode_end()

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
        Only used in host-based mode; server-authoritative mode broadcasts state directly.
        """
        game = self.games[game_id]

        # Skip state verification in server-authoritative mode
        # Server broadcasts authoritative state instead of requesting hashes
        if game.server_authoritative:
            logger.debug(
                f"Game {game_id}: Skipping state verification (server-authoritative mode)"
            )
            return

        self.sio.emit('pyodide_verify_state',
                     {'frame_number': game.frame_number},
                     room=game_id)

        game.verification_frame = game.frame_number + game.state_broadcast_interval
        # Note: We don't clear state_hashes here anymore since we track by frame number.
        # Old frames are cleaned up in _cleanup_old_frame_hashes() after verification.

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

        Hashes are grouped by frame number to ensure we only compare
        hashes from the same frame across all players.

        Only used in host-based mode; server-authoritative mode ignores hashes.

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

            # Skip hash processing in server-authoritative mode
            # Server broadcasts authoritative state instead of verifying client hashes
            if game.server_authoritative:
                logger.debug(
                    f"Game {game_id}: Ignoring state hash from player {player_id} "
                    f"(server-authoritative mode)"
                )
                return

            # Initialize hash dict for this frame if needed
            if frame_number not in game.state_hashes:
                game.state_hashes[frame_number] = {}

            # Store hash for this player at this frame
            game.state_hashes[frame_number][player_id] = state_hash

            frame_hashes = game.state_hashes[frame_number]

            logger.debug(
                f"Game {game_id} frame {frame_number}: "
                f"Received hash from player {player_id} "
                f"({len(frame_hashes)}/{len(game.players)} received for this frame)"
            )

            # Once all hashes received for this frame, verify
            if len(frame_hashes) == len(game.players):
                self._verify_synchronization(game_id, frame_number)
                # Clean up old frame hashes to prevent memory growth
                self._cleanup_old_frame_hashes(game, frame_number)

    def _verify_synchronization(self, game_id: str, frame_number: int):
        """
        Check if all players have matching state hashes for a specific frame.

        If hashes don't match, desync has occurred and we need to resync.
        """
        game = self.games[game_id]

        # Get hashes for this specific frame
        frame_hashes = game.state_hashes.get(frame_number, {})
        if not frame_hashes:
            logger.warning(f"Game {game_id}: No hashes found for frame {frame_number}")
            return

        hashes = list(frame_hashes.values())
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
            for player_id, hash_val in frame_hashes.items():
                logger.error(f"  Player {player_id}: {hash_val[:16]}...")

            self._handle_desync(game_id, frame_number)

    def _cleanup_old_frame_hashes(self, game: PyodideGameState, current_frame: int):
        """
        Remove hash data for old frames to prevent memory growth.

        Keeps only recent frames in case of delayed hash arrivals.
        """
        # Keep hashes for frames within last 100 frames
        frames_to_keep = 100
        min_frame_to_keep = current_frame - frames_to_keep

        frames_to_remove = [
            frame for frame in game.state_hashes.keys()
            if frame < min_frame_to_keep
        ]

        for frame in frames_to_remove:
            del game.state_hashes[frame]

        if frames_to_remove:
            logger.debug(
                f"Game {game.game_id}: Cleaned up hashes for {len(frames_to_remove)} old frames"
            )

    def _handle_desync(self, game_id: str, frame_number: int):
        """
        Handle desynchronization by requesting resync.

        If server_authoritative mode is enabled, broadcast server state directly.
        Otherwise, request full state from host.

        Process (host-based):
        1. Request full state from host
        2. Host sends serialized state
        3. Broadcast state to non-host clients
        4. Clients apply state (snapping to correct state without pausing)

        Process (server-authoritative):
        1. Broadcast server state directly to all clients
        """
        game = self.games[game_id]

        # If server-authoritative, broadcast server state directly
        if game.server_authoritative and game.server_runner:
            game.server_runner.broadcast_state()
            logger.info(f"Game {game_id}: Broadcast server state for resync")
            return

        # Fall back to host-based resync
        host_socket = game.players[game.host_player_id]
        self.sio.emit('pyodide_request_full_state',
                     {'frame_number': frame_number},
                     room=host_socket)

        logger.info(f"Game {game_id}: Initiated resync from host {game.host_player_id}")

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

    def remove_player(self, game_id: str, player_id: str | int, notify_others: bool = True):
        """
        Handle player disconnection.

        If host disconnects, elect new host and trigger resync.
        If all players disconnect, remove game.
        Notifies remaining players that the game has ended.

        Args:
            game_id: Game identifier
            player_id: Player who disconnected
            notify_others: Whether to notify remaining players (default True)
        """
        with self.lock:
            if game_id not in self.games:
                return

            game = self.games[game_id]

            if player_id not in game.players:
                return

            was_host = (player_id == game.host_player_id)

            # Get remaining player sockets before removing the disconnected player
            remaining_player_sockets = [
                socket_id for pid, socket_id in game.players.items()
                if pid != player_id
            ]

            del game.players[player_id]

            logger.info(
                f"Player {player_id} disconnected from game {game_id} "
                f"({'host' if was_host else 'client'})"
            )

            # Notify remaining players that the game has ended due to disconnection
            if notify_others and len(remaining_player_sockets) > 0:
                logger.info(
                    f"Notifying {len(remaining_player_sockets)} remaining players "
                    f"about disconnection in game {game_id}"
                )
                for socket_id in remaining_player_sockets:
                    self.sio.emit(
                        'end_game',
                        {
                            'message': 'You were matched with a partner but your game ended because the other player disconnected.'
                        },
                        room=socket_id
                    )

            # If no players left, remove game
            if len(game.players) == 0:
                # Stop server runner if it exists
                if game.server_runner:
                    game.server_runner.stop()
                del self.games[game_id]
                logger.info(f"Removed empty game {game_id}")
            # If there are remaining players, also remove the game since we ended it
            elif notify_others:
                # Stop server runner if it exists
                if game.server_runner:
                    game.server_runner.stop()
                del self.games[game_id]
                logger.info(f"Removed game {game_id} after player disconnection")

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

    def _log_game_diagnostics(self, game: PyodideGameState):
        """
        Log diagnostics for a game to help identify lag sources.

        Tracks:
        - Inter-action delay per player (time between actions from same player)
        - Frame number disparity between server runner and clients
        """
        diagnostics = []

        # Calculate average inter-action delay per player
        for player_id, delays in game.action_delays.items():
            if delays:
                avg_delay = sum(delays) / len(delays)
                max_delay = max(delays)
                min_delay = min(delays)
                diagnostics.append(
                    f"Player {player_id}: avg={avg_delay*1000:.1f}ms, "
                    f"max={max_delay*1000:.1f}ms, min={min_delay*1000:.1f}ms"
                )

        # Server runner frame info
        if game.server_runner and game.server_runner.is_initialized:
            diagnostics.append(f"Server frame: {game.server_runner.frame_number}")

        if diagnostics:
            logger.info(
                f"[Diagnostics] Game {game.game_id} - " +
                " | ".join(diagnostics)
            )

        # Warn if there's significant disparity in action rates
        if len(game.action_delays) >= 2:
            avg_delays = {
                pid: sum(delays) / len(delays) if delays else 0
                for pid, delays in game.action_delays.items()
            }
            if avg_delays:
                min_avg = min(avg_delays.values())
                max_avg = max(avg_delays.values())
                if min_avg > 0 and max_avg / min_avg > 1.5:
                    logger.warning(
                        f"[Diagnostics] Game {game.game_id}: Action rate disparity detected! "
                        f"Fastest player: {min_avg*1000:.1f}ms avg, "
                        f"Slowest player: {max_avg*1000:.1f}ms avg. "
                        f"This may cause queue buildup and lag."
                    )

    def get_stats(self) -> dict:
        """Get coordinator statistics for monitoring/debugging."""
        return {
            'active_games': len(self.games),
            'total_games_created': self.total_games_created,
            'total_desyncs_detected': self.total_desyncs_detected,
            'total_host_migrations': self.total_host_migrations,
        }
