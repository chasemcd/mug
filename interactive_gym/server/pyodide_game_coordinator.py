"""
Pyodide Game Coordinator for Multiplayer Support

Coordinates client-side Pyodide games by:
- Generating shared RNG seeds for determinism
- Collecting and broadcasting player actions
- Verifying state synchronization across clients
- Assigning player IDs to symmetric peers
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

    # WebRTC TURN configuration
    turn_username: str | None = None
    turn_credential: str | None = None
    force_turn_relay: bool = False

    # P2P validation state (Phase 19)
    p2p_validation_enabled: bool = True
    p2p_validation_timeout_s: float = 10.0
    p2p_validated_players: set = dataclasses.field(default_factory=set)
    validation_start_time: float | None = None


class PyodideGameCoordinator:
    """
    Coordinates multiplayer Pyodide games.

    Key responsibilities:
    1. Generate and distribute shared RNG seeds
    2. Collect actions from all players each frame
    3. Broadcast actions when all received (or timeout)
    4. Verify state synchronization periodically
    5. Assign player IDs to symmetric peers
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
        # WebRTC TURN configuration
        turn_username: str | None = None,
        turn_credential: str | None = None,
        force_turn_relay: bool = False,
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
                turn_username=turn_username,
                turn_credential=turn_credential,
                force_turn_relay=force_turn_relay,
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
        Add a player to the game.

        All players are symmetric peers - no host/client distinction.

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

            # Send player assignment to all players (symmetric - no host distinction)
            self.sio.emit('pyodide_player_assigned',
                         {
                             'player_id': player_id,
                             'game_id': game_id,
                             'game_seed': game.rng_seed,
                             'num_players': game.num_expected_players
                         },
                         room=socket_id)

            logger.info(
                f"Player {player_id} assigned to game {game_id} "
                f"(seed: {game.rng_seed})"
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
                         # Include TURN config only if credentials are provided
                         'turn_config': {
                             'username': game.turn_username,
                             'credential': game.turn_credential,
                             'force_relay': game.force_turn_relay,
                         } if game.turn_username else None,
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

            # Log frame info for debugging
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

            # Get remaining player sockets before removing the disconnected player
            remaining_player_sockets = [
                socket_id for pid, socket_id in game.players.items()
                if pid != player_id
            ]

            del game.players[player_id]

            logger.info(f"Player {player_id} disconnected from game {game_id}")

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

    def handle_webrtc_signal(
        self,
        game_id: str,
        target_player_id: str | int,
        signal_type: str,
        payload: Any,
        sender_socket_id: str,
    ):
        """
        Relay WebRTC signaling messages between peers.

        Routes SDP offers/answers and ICE candidates from one player to another
        without inspecting or modifying the payload.

        Args:
            game_id: Game identifier
            target_player_id: Player ID to receive the signal
            signal_type: Type of signal (offer, answer, ice-candidate)
            payload: The signaling payload (SDP or ICE candidate)
            sender_socket_id: Socket ID of the sender (for reverse lookup)
        """
        with self.lock:
            if game_id not in self.games:
                logger.warning(
                    f"WebRTC signal for unknown game {game_id}"
                )
                return

            game = self.games[game_id]

            # Find target player's socket
            target_socket = game.players.get(target_player_id)
            if target_socket is None:
                # Try with string/int conversion
                target_socket = game.players.get(str(target_player_id))
                if target_socket is None:
                    target_socket = game.players.get(int(target_player_id) if isinstance(target_player_id, str) and target_player_id.isdigit() else target_player_id)
                if target_socket is None:
                    logger.warning(
                        f"WebRTC signal for unknown player {target_player_id} in game {game_id}"
                    )
                    return

            # Find sender's player ID by reverse lookup
            sender_player_id = None
            for player_id, socket_id in game.players.items():
                if socket_id == sender_socket_id:
                    sender_player_id = player_id
                    break

            if sender_player_id is None:
                logger.warning(
                    f"WebRTC signal from unknown socket {sender_socket_id} in game {game_id}"
                )
                return

            # Relay the signal to target peer
            self.sio.emit(
                'webrtc_signal',
                {
                    'type': signal_type,
                    'from_player_id': sender_player_id,
                    'game_id': game_id,
                    'payload': payload,
                },
                room=target_socket,
            )

            logger.debug(
                f"Relayed WebRTC {signal_type} from player {sender_player_id} "
                f"to player {target_player_id} in game {game_id}"
            )

    def handle_player_exclusion(
        self,
        game_id: str,
        excluded_player_id: str | int,
        reason: str,
        frame_number: int
    ):
        """
        Handle player exclusion from continuous monitoring.

        Notifies partner with clear message, triggers data export,
        and cleans up game state.

        Args:
            game_id: Game identifier
            excluded_player_id: ID of excluded player
            reason: Exclusion reason ('sustained_ping', 'tab_hidden')
            frame_number: Frame number when exclusion occurred
        """
        with self.lock:
            if game_id not in self.games:
                logger.warning(f"Exclusion for non-existent game {game_id}")
                return

            game = self.games[game_id]

            if excluded_player_id not in game.players:
                logger.warning(
                    f"Excluded player {excluded_player_id} not in game {game_id}"
                )
                return

            # Find partner socket(s) before any cleanup
            partner_sockets = [
                socket_id for pid, socket_id in game.players.items()
                if pid != excluded_player_id
            ]

            # Notify partner(s) with clear, non-alarming message
            for socket_id in partner_sockets:
                self.sio.emit(
                    'partner_excluded',
                    {
                        'message': 'Your partner experienced a technical issue. The game has ended.',
                        'frame_number': frame_number,
                        'reason': 'partner_exclusion'
                    },
                    room=socket_id
                )

                # Trigger data export for partner before cleanup
                self.sio.emit(
                    'trigger_data_export',
                    {
                        'is_partial': True,
                        'termination_reason': 'partner_exclusion',
                        'termination_frame': frame_number
                    },
                    room=socket_id
                )

            logger.info(
                f"Notified {len(partner_sockets)} partner(s) of exclusion "
                f"in game {game_id}"
            )

            # Brief delay to ensure messages are delivered
            eventlet.sleep(0.1)

            # Now clean up the game
            # Stop server runner if it exists
            if game.server_runner:
                game.server_runner.stop()

            del self.games[game_id]
            logger.info(f"Cleaned up game {game_id} after player exclusion")

    def start_validation(self, game_id: str) -> bool:
        """Mark validation phase started for a game (Phase 19)."""
        with self.lock:
            game = self.games.get(game_id)
            if not game:
                return False

            game.validation_start_time = time.time()
            game.p2p_validated_players = set()
            logger.info(f"P2P validation started for game {game_id}")
            return True

    def record_validation_success(self, game_id: str, player_id: str | int) -> str | None:
        """
        Record that a player validated their P2P connection (Phase 19).

        Returns:
            'complete' if all players validated
            'waiting' if still waiting for other players
            None if game not found
        """
        with self.lock:
            game = self.games.get(game_id)
            if not game:
                logger.warning(f"Validation success for non-existent game {game_id}")
                return None

            game.p2p_validated_players.add(str(player_id))
            logger.info(
                f"Player {player_id} validated P2P in game {game_id} "
                f"({len(game.p2p_validated_players)}/{game.num_expected_players})"
            )

            # Check if all players validated
            if len(game.p2p_validated_players) >= game.num_expected_players:
                return 'complete'
            return 'waiting'

    def handle_validation_failure(self, game_id: str, player_id: str | int, reason: str) -> list:
        """
        Handle P2P validation failure - prepare for re-pool (Phase 19).

        Returns list of socket_ids that need to be notified for re-pool.
        Game is NOT removed yet - caller should emit events first.
        """
        with self.lock:
            game = self.games.get(game_id)
            if not game:
                logger.warning(f"Validation failure for non-existent game {game_id}")
                return []

            logger.warning(
                f"P2P validation failed for game {game_id}, "
                f"player {player_id}: {reason}"
            )

            # Return all player socket_ids for notification
            return list(game.players.values())

    def remove_game(self, game_id: str) -> None:
        """Remove a game from the coordinator (Phase 19)."""
        with self.lock:
            if game_id in self.games:
                game = self.games[game_id]
                # Stop server runner if exists
                if game.server_authoritative and game.server_runner:
                    game.server_runner.stop()
                del self.games[game_id]
                logger.info(f"Removed game {game_id} from coordinator")

    def get_stats(self) -> dict:
        """Get coordinator statistics for monitoring/debugging."""
        return {
            'active_games': len(self.games),
            'total_games_created': self.total_games_created,
            'total_desyncs_detected': self.total_desyncs_detected,
        }
