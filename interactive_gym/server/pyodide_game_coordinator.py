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
    host_player_id: str | int | None  # First player to join (used for logging)
    players: Dict[str | int, str]  # player_id -> socket_id
    player_subjects: Dict[str | int, str]  # player_id -> subject_id (participant name)
    frame_number: int
    is_active: bool
    rng_seed: int  # Shared seed for deterministic AI
    num_expected_players: int
    action_timeout_seconds: float
    created_at: float

    # State broadcast/sync interval (frames between server broadcasts)
    state_broadcast_interval: int = 30

    # Server-authoritative mode fields
    server_authoritative: bool = False
    server_runner: Any = None  # ServerGameRunner instance when enabled

    # Diagnostics for lag tracking
    last_action_times: Dict[str | int, float] = dataclasses.field(default_factory=dict)
    action_delays: Dict[str | int, list] = dataclasses.field(default_factory=dict)
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
        # New config options for real-time mode
        fps: int = 30,
        default_action: int = 0,
        action_population_method: str = "previous_submitted_action",
        realtime_mode: bool = True,
        input_buffer_size: int = 300,
        max_episodes: int = 1,
        max_steps: int = 10000,
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
                frame_number=0,
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
                    # New config options
                    fps=fps,
                    default_action=default_action,
                    action_population_method=action_population_method,
                    realtime_mode=realtime_mode,
                    input_buffer_size=input_buffer_size,
                    max_episodes=max_episodes,
                    max_steps=max_steps,
                )
                mode_str = "real-time" if realtime_mode else "frame-aligned"
                logger.info(
                    f"Created ServerGameRunner for game {game_id} "
                    f"({mode_str} mode, {fps} FPS, broadcast every {state_broadcast_interval} frames)"
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
                # Start real-time loop
                game.server_runner.start_realtime()
            else:
                logger.error(
                    f"Failed to initialize server runner for game {game_id}"
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
                         'player_subjects': game.player_subjects,
                         'server_authoritative': game.server_authoritative,
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
        client_timestamp: float | None = None,
        sync_epoch: int | None = None
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
            sync_epoch: Sync epoch from client to prevent stale action matching
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

            # Feed action to server runner
            if game.server_authoritative and game.server_runner:
                game.server_runner.receive_action_realtime(
                    player_id, action, frame_number, sync_epoch
                )

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
