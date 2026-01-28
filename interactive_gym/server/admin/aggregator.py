"""
Admin Event Aggregator for collecting and projecting experiment state.

Uses observer pattern - reads existing state structures without modifying them.
Emits to admin namespace at 1-2 Hz (throttled).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import eventlet

if TYPE_CHECKING:
    import flask_socketio
    from interactive_gym.server.pyodide_game_coordinator import PyodideGameCoordinator
    from interactive_gym.server.app import ParticipantSession

logger = logging.getLogger(__name__)


@dataclass
class ActivityEvent:
    """Single activity event for the timeline."""
    timestamp: float
    event_type: str  # join, scene_advance, disconnect, game_start, game_end
    subject_id: str
    details: dict = field(default_factory=dict)


class AdminEventAggregator:
    """
    Central hub for collecting and projecting experiment state to admin dashboard.

    Uses observer pattern - reads existing state structures without modifying them.
    Emits to admin namespace at 1-2 Hz (throttled).
    """

    # Maximum number of activity events to retain
    MAX_ACTIVITY_LOG_SIZE = 500
    # Maximum number of console log entries to retain
    MAX_CONSOLE_LOG_SIZE = 1000

    # Directory for persisted console logs
    CONSOLE_LOGS_DIR = "data/console_logs"

    def __init__(
        self,
        sio: flask_socketio.SocketIO,
        participant_sessions: dict,  # PARTICIPANT_SESSIONS
        stagers: dict,               # STAGERS
        game_managers: dict,         # GAME_MANAGERS
        pyodide_coordinator: PyodideGameCoordinator | None = None,
        processed_subjects: list | None = None,  # PROCESSED_SUBJECT_NAMES
        save_console_logs: bool = True
    ):
        """
        Initialize the aggregator with references to experiment state.

        Args:
            sio: Flask-SocketIO instance for emitting updates
            participant_sessions: Reference to PARTICIPANT_SESSIONS dict
            stagers: Reference to STAGERS dict
            game_managers: Reference to GAME_MANAGERS dict
            pyodide_coordinator: Optional PyodideGameCoordinator reference
            processed_subjects: Optional list of completed subject IDs
            save_console_logs: Whether to persist console logs to disk
        """
        # Store references (read-only access)
        # Do NOT modify these - observer pattern only
        self.sio = sio
        self.participant_sessions = participant_sessions
        self.stagers = stagers
        self.game_managers = game_managers
        self.pyodide_coordinator = pyodide_coordinator
        self.processed_subjects = processed_subjects or []

        # Activity log - capped FIFO queue
        self._activity_log: deque[ActivityEvent] = deque(maxlen=self.MAX_ACTIVITY_LOG_SIZE)

        # Console log - capped FIFO queue for participant console output
        self._console_logs: deque[dict] = deque(maxlen=self.MAX_CONSOLE_LOG_SIZE)

        # Console log file persistence
        self._save_console_logs = save_console_logs
        self._console_log_files: dict[str, Any] = {}  # subject_id -> file handle

        # Create console logs directory if saving enabled
        if self._save_console_logs:
            os.makedirs(self.CONSOLE_LOGS_DIR, exist_ok=True)
            logger.info(f"Console logs will be saved to {self.CONSOLE_LOGS_DIR}/")

        # Session completion tracking for duration calculation
        # Maps subject_id -> {started_at: float, completed_at: float}
        self._completed_sessions: dict[str, dict] = {}

        # Track all subjects who have ever started (for total_started calculation)
        self._all_started_subjects: set[str] = set()

        # P2P health cache (Phase 33)
        # Maps game_id -> {player_id -> health_data}
        # health_data: {connection_type, latency_ms, status, episode, timestamp}
        self._p2p_health_cache: dict[str, dict[str, dict]] = {}
        self._p2p_health_expiry_seconds = 10  # Auto-expire entries older than this

        # Session termination tracking (Phase 34)
        # Maps game_id -> {reason: str, timestamp: float, players: list[str], details: dict}
        self._session_terminations: dict[str, dict] = {}

        # Broadcast loop state
        self._broadcast_running = False
        self._last_state_hash: str | None = None
        self._last_broadcast_time: float = 0

        logger.info("AdminEventAggregator initialized")

    def record_session_completion(
        self,
        subject_id: str,
        started_at: float,
        completed_at: float
    ) -> None:
        """
        Record session completion data for duration calculation.

        Called when a participant finishes their experiment (enters PROCESSED_SUBJECT_NAMES).

        Args:
            subject_id: The participant's subject ID
            started_at: Unix timestamp when session started (ParticipantSession.created_at)
            completed_at: Unix timestamp when session completed
        """
        self._completed_sessions[subject_id] = {
            'started_at': started_at,
            'completed_at': completed_at
        }
        # Ensure subject is in started set
        self._all_started_subjects.add(subject_id)
        logger.debug(f"Recorded session completion for {subject_id}: duration={completed_at - started_at:.1f}s")

    def track_session_start(self, subject_id: str) -> None:
        """
        Track that a subject has started a session.

        Called when a participant connects for the first time.

        Args:
            subject_id: The participant's subject ID
        """
        self._all_started_subjects.add(subject_id)

    def record_session_termination(
        self,
        game_id: str,
        reason: str,
        players: list[str],
        details: dict | None = None
    ) -> None:
        """
        Record session termination with reason for detail view.

        Args:
            game_id: The game ID
            reason: Termination reason (partner_disconnected, focus_loss_timeout,
                    sustained_ping, tab_hidden, exclusion, normal)
            players: List of player subject IDs
            details: Optional additional details (exclusion message, etc.)
        """
        self._session_terminations[game_id] = {
            'reason': reason,
            'timestamp': time.time(),
            'players': players,
            'details': details or {}
        }
        logger.debug(f"Session termination recorded for {game_id}: {reason}")

    def get_session_detail(self, game_id: str) -> dict | None:
        """
        Get detailed information for a specific session.

        Args:
            game_id: The game ID

        Returns:
            Dict with session info, termination reason, and player console logs
        """
        # Get active game state if still running
        game_state = None
        if self.pyodide_coordinator and game_id in self.pyodide_coordinator.games:
            game = self.pyodide_coordinator.games[game_id]
            p2p_health = self._get_p2p_health_for_game(game_id)
            game_state = {
                'game_id': game_id,
                'players': list(game.players.keys()),
                'host_id': game.host_id,
                'is_server_authoritative': game.server_authoritative,
                'created_at': getattr(game, 'created_at', None),
                'p2p_health': p2p_health,
                'session_health': self._compute_session_health(p2p_health)
            }

        # Get termination info if session ended
        termination = self._session_terminations.get(game_id)

        # Get player list from game_state or termination
        players = []
        if game_state:
            players = game_state['players']
        elif termination:
            players = termination.get('players', [])

        # Filter console logs for these players (last 50 per player, errors prioritized)
        player_logs = []
        for log in list(self._console_logs):
            if log.get('subject_id') in players:
                player_logs.append(log)

        # Sort by timestamp descending, prioritize errors
        player_logs.sort(key=lambda x: (
            0 if x.get('level') == 'error' else 1,
            -x.get('timestamp', 0)
        ))
        player_logs = player_logs[:100]  # Limit to 100 logs

        return {
            'game_state': game_state,
            'termination': termination,
            'player_logs': player_logs
        }

    def receive_p2p_health(
        self,
        game_id: str,
        player_id: str,
        health_data: dict
    ) -> None:
        """
        Receive P2P health report from a client (Phase 33).

        Stores health data in cache for inclusion in admin state updates.
        Entries auto-expire after _p2p_health_expiry_seconds.

        Args:
            game_id: The game ID
            player_id: The player ID reporting health
            health_data: Dict with connection_type, latency_ms, status, episode, timestamp
        """
        if not game_id or not player_id:
            return

        if game_id not in self._p2p_health_cache:
            self._p2p_health_cache[game_id] = {}

        self._p2p_health_cache[game_id][player_id] = health_data
        logger.debug(f"P2P health update for game {game_id}, player {player_id}: {health_data.get('status')}")

    def _get_p2p_health_for_game(self, game_id: str) -> dict:
        """
        Get P2P health data for a game, filtering out expired entries.

        Args:
            game_id: The game ID

        Returns:
            Dict of player_id -> health_data for non-expired entries
        """
        if game_id not in self._p2p_health_cache:
            return {}

        now = time.time()
        valid_entries = {}
        expired_players = []

        for player_id, health_data in self._p2p_health_cache[game_id].items():
            timestamp = health_data.get('timestamp', 0)
            if now - timestamp < self._p2p_health_expiry_seconds:
                valid_entries[player_id] = health_data
            else:
                expired_players.append(player_id)

        # Clean up expired entries
        for player_id in expired_players:
            del self._p2p_health_cache[game_id][player_id]

        # Clean up empty game entries
        if not self._p2p_health_cache[game_id]:
            del self._p2p_health_cache[game_id]

        return valid_entries

    def _compute_session_health(self, p2p_health: dict) -> str:
        """
        Compute overall session health from individual player health reports.

        Args:
            p2p_health: Dict of player_id -> health_data

        Returns:
            'healthy' if all players healthy
            'degraded' if any degraded or using SocketIO fallback
            'reconnecting' if any reconnecting
        """
        if not p2p_health:
            return 'healthy'  # No data means assume healthy

        has_reconnecting = False
        has_degraded = False

        for health_data in p2p_health.values():
            status = health_data.get('status', 'healthy')
            conn_type = health_data.get('connection_type', '')

            if status == 'reconnecting':
                has_reconnecting = True
            elif status == 'degraded' or conn_type == 'socketio_fallback':
                has_degraded = True

        if has_reconnecting:
            return 'reconnecting'
        if has_degraded:
            return 'degraded'
        return 'healthy'

    def get_experiment_snapshot(self) -> dict:
        """
        Returns complete state dict for admin dashboard.

        Returns:
            dict with:
                - participants: List of participant state dicts
                - waiting_rooms: List of waiting room state dicts
                - activity_log: Recent activity events (last 100)
                - summary: Aggregate stats (total participants, active games, etc.)
        """
        # Copy data before building snapshot (don't hold refs while emitting)
        participants = []
        for subject_id in list(self.participant_sessions.keys()):
            participant_state = self._get_participant_state(subject_id)
            if participant_state:
                participants.append(participant_state)

        waiting_rooms = []
        for scene_id, game_manager in list(self.game_managers.items()):
            room_state = self._get_waiting_room_state(scene_id, game_manager)
            if room_state:
                waiting_rooms.append(room_state)

        # Get active games (both multiplayer and single-player)
        active_games_list = self._get_active_games_state()
        active_games = len(active_games_list)

        # Get recent activity (last 100 for display)
        recent_activity = [
            {
                'timestamp': event.timestamp,
                'event_type': event.event_type,
                'subject_id': event.subject_id,
                'details': event.details
            }
            for event in list(self._activity_log)[-100:]
        ]

        # Count connection statuses
        connected_count = sum(
            1 for p in participants if p.get('connection_status') == 'connected'
        )
        disconnected_count = sum(
            1 for p in participants if p.get('connection_status') == 'disconnected'
        )
        reconnecting_count = sum(
            1 for p in participants if p.get('connection_status') == 'reconnecting'
        )
        completed_count = sum(
            1 for p in participants if p.get('connection_status') == 'completed'
        )

        # Total waiting across all rooms
        waiting_count = sum(r.get('waiting_count', 0) for r in waiting_rooms)

        # Calculate total started (current sessions + completed not in current)
        current_subject_ids = set(self.participant_sessions.keys())
        all_started = self._all_started_subjects | current_subject_ids
        total_started = len(all_started)

        # Calculate completion rate using the same completed_count (includes participants on final scene)
        completion_rate = (completed_count / total_started * 100) if total_started > 0 else 0

        # Calculate average session duration from completed sessions
        avg_session_duration_ms = None
        if self._completed_sessions:
            durations = [
                (s['completed_at'] - s['started_at']) * 1000  # Convert to ms
                for s in self._completed_sessions.values()
            ]
            avg_session_duration_ms = int(sum(durations) / len(durations))

        summary = {
            'total_participants': len(participants),
            'connected_count': connected_count,
            'disconnected_count': disconnected_count,
            'reconnecting_count': reconnecting_count,
            'completed_count': completed_count,
            'active_games': active_games,
            'waiting_count': waiting_count,
            'timestamp': time.time(),
            # New summary stats
            'total_started': total_started,
            'completion_rate': round(completion_rate, 1),
            'avg_session_duration_ms': avg_session_duration_ms
        }

        # Get recent console logs (last 100 for display)
        recent_console_logs = list(self._console_logs)[-100:]

        return {
            'participants': participants,
            'waiting_rooms': waiting_rooms,
            'multiplayer_games': active_games_list,  # Now includes both single-player and multiplayer
            'activity_log': recent_activity,
            'console_logs': recent_console_logs,
            'summary': summary
        }

    def _get_participant_state(self, subject_id: str) -> dict | None:
        """
        Extract participant state for dashboard display.

        Args:
            subject_id: The participant's subject ID

        Returns:
            dict with subject_id, connection_status, current_scene_id, etc.
            or None if session doesn't exist
        """
        session = self.participant_sessions.get(subject_id)
        if not session:
            return None

        stager = self.stagers.get(subject_id)
        scene_progress = None
        if stager:
            try:
                scene_progress = {
                    'current_index': stager.current_scene_index,
                    'total_scenes': len(stager.scenes),
                    'current_scene_id': session.current_scene_id
                }
            except Exception as e:
                logger.debug(f"Error getting scene progress for {subject_id}: {e}")

        return {
            'subject_id': subject_id,
            'connection_status': self._compute_connection_status(session, subject_id, stager),
            'current_scene_id': session.current_scene_id,
            'scene_progress': scene_progress,
            'created_at': session.created_at,
            'last_updated_at': session.last_updated_at
        }

    def _compute_connection_status(self, session: Any, subject_id: str, stager: Any = None) -> str:
        """
        Compute connection status for display.

        Returns:
            'connected' (green) - Currently connected
            'reconnecting' (yellow) - Disconnected recently (< 30 seconds)
            'disconnected' (red) - Disconnected for > 30 seconds
            'completed' (gray) - Finished experiment
        """
        # Check if completed (need access to PROCESSED_SUBJECT_NAMES)
        if subject_id in self.processed_subjects:
            return 'completed'

        # Check if participant is on the final scene (considered completed)
        if stager is not None:
            try:
                current_index = stager.current_scene_index
                total_scenes = len(stager.scenes)
                # If on the last scene, consider completed
                if current_index >= total_scenes - 1:
                    # Record completion for duration tracking (if not already recorded)
                    if subject_id not in self._completed_sessions:
                        self.record_session_completion(
                            subject_id=subject_id,
                            started_at=session.created_at,
                            completed_at=time.time()
                        )
                    return 'completed'
            except Exception:
                pass  # If we can't determine scene progress, fall through to other checks

        if session.is_connected:
            return 'connected'

        # Check how long disconnected
        if session.last_updated_at:
            seconds_since_update = time.time() - session.last_updated_at
            if seconds_since_update < 30:
                return 'reconnecting'

        return 'disconnected'

    def _get_waiting_room_state(self, scene_id: str, game_manager: Any) -> dict | None:
        """
        Extract waiting room state for a scene.

        Args:
            scene_id: The scene ID
            game_manager: The GameManager instance for this scene

        Returns:
            dict with scene_id, waiting_count, target_size, groups, etc.
        """
        try:
            # Get basic info from game manager
            waiting_count = 0
            target_size = 0
            groups = []

            # Check if game_manager has waiting_games attribute
            if hasattr(game_manager, 'waiting_games'):
                waiting_games = game_manager.waiting_games
                waiting_count = len(waiting_games) if waiting_games else 0

            # Get target game size from scene
            if hasattr(game_manager, 'scene') and game_manager.scene:
                scene = game_manager.scene
                if hasattr(scene, 'num_players'):
                    target_size = scene.num_players

            # Check for group waitrooms if they exist
            import time
            now = time.time()
            total_wait_ms = 0
            wait_count = 0

            if hasattr(game_manager, 'group_waitrooms'):
                # Get wait start times dict if available
                wait_times = getattr(game_manager, 'group_wait_start_times', {})

                for group_id, waitroom in game_manager.group_waitrooms.items():
                    if waitroom:
                        waiting_subjects = list(waitroom) if isinstance(waitroom, list) else list(waitroom.keys())

                        # Calculate wait duration from earliest member
                        group_wait_ms = 0
                        for sid in waiting_subjects:
                            if sid in wait_times:
                                wait_ms = int((now - wait_times[sid]) * 1000)
                                group_wait_ms = max(group_wait_ms, wait_ms)
                                total_wait_ms += wait_ms
                                wait_count += 1

                        groups.append({
                            'group_id': group_id,
                            'waiting_subjects': waiting_subjects,
                            'waiting_count': len(waiting_subjects),
                            'wait_duration_ms': group_wait_ms
                        })

            # Calculate average wait duration
            avg_wait_ms = int(total_wait_ms / wait_count) if wait_count > 0 else 0

            return {
                'scene_id': scene_id,
                'waiting_count': waiting_count,
                'target_size': target_size,
                'groups': groups,
                'avg_wait_duration_ms': avg_wait_ms
            }
        except Exception as e:
            logger.debug(f"Error getting waiting room state for {scene_id}: {e}")
            return None

    def _get_active_games_state(self) -> list[dict]:
        """
        Extract active game states (both multiplayer and single-player).

        Returns:
            List of dicts with game_id, players, p2p_health, session_health, etc.
        """
        games = []
        tracked_game_ids = set()  # Avoid duplicates

        # 1. Get multiplayer games from coordinator
        if self.pyodide_coordinator:
            try:
                for game_id, game_state in list(self.pyodide_coordinator.games.items()):
                    tracked_game_ids.add(game_id)

                    # Get P2P health data for this game (Phase 33)
                    p2p_health = self._get_p2p_health_for_game(game_id)
                    session_health = self._compute_session_health(p2p_health)

                    # Get current episode from health reports (max across players)
                    current_episode = None
                    for health_data in p2p_health.values():
                        ep = health_data.get('episode')
                        if ep is not None:
                            if current_episode is None or ep > current_episode:
                                current_episode = ep

                    games.append({
                        'game_id': game_id,
                        'players': list(game_state.players.keys()),
                        'subject_ids': list(game_state.player_subjects.values()),
                        'current_frame': game_state.frame_number,
                        'is_server_authoritative': game_state.server_authoritative,
                        'created_at': game_state.created_at,
                        'game_type': 'multiplayer',
                        # Phase 33: P2P health data
                        'p2p_health': p2p_health,
                        'session_health': session_health,
                        'current_episode': current_episode,
                        # Phase 34: Termination info if session ended
                        'termination': self._session_terminations.get(game_id),
                    })
            except Exception as e:
                logger.error(f"Error getting multiplayer games state: {e}", exc_info=True)

        # 2. Get single-player Pyodide games from game managers
        try:
            for scene_id, game_manager in list(self.game_managers.items()):
                # Check if this is a single-player Pyodide scene
                scene = game_manager.scene
                if not getattr(scene, 'run_through_pyodide', False):
                    continue  # Not a Pyodide scene
                if getattr(scene, 'pyodide_multiplayer', False):
                    continue  # Multiplayer - already tracked via coordinator

                # Get active games from this manager
                for game_id in list(game_manager.active_games):
                    if game_id in tracked_game_ids:
                        continue  # Already tracked
                    tracked_game_ids.add(game_id)

                    game = game_manager.games.get(game_id)
                    if not game:
                        continue

                    # Get subject IDs for players in this game
                    subject_ids = []
                    for subject_id, gid in list(game_manager.subject_games.items()):
                        if gid == game_id:
                            subject_ids.append(subject_id)

                    games.append({
                        'game_id': game_id,
                        'players': list(game.human_players.keys()) if hasattr(game, 'human_players') else [],
                        'subject_ids': subject_ids,
                        'current_frame': getattr(game, 'tick_num', None),
                        'is_server_authoritative': False,
                        'created_at': None,
                        'game_type': 'single_player',
                        'scene_id': scene_id,
                        # No P2P for single-player
                        'p2p_health': {},
                        'session_health': 'healthy',
                        'current_episode': getattr(game, 'episode_num', None),
                        'termination': self._session_terminations.get(game_id),
                    })
        except Exception as e:
            logger.error(f"Error getting single-player games state: {e}", exc_info=True)

        return games

    def receive_console_log(
        self,
        subject_id: str,
        level: str,
        message: str,
        timestamp: float | None = None
    ) -> None:
        """
        Receive and store a console log from a participant, emit to admins immediately.

        Also persists to disk for retrospective analysis.

        Args:
            subject_id: The participant's subject ID
            level: Log level (log, info, warn, error)
            message: The log message
            timestamp: Optional timestamp (defaults to now)
        """
        log_entry = {
            'timestamp': timestamp or time.time(),
            'subject_id': subject_id,
            'level': level,
            'message': message[:500] if message else ''  # Truncate long messages
        }

        # Append to console log (deque auto-removes old entries when full)
        self._console_logs.append(log_entry)

        # Persist to disk (non-blocking)
        if self._save_console_logs:
            self._persist_console_log(subject_id, log_entry)

        # Immediately emit to admins for real-time log view
        self.emit_console_log(log_entry)

    def _persist_console_log(self, subject_id: str, log_entry: dict) -> None:
        """
        Persist a console log entry to disk.

        Uses JSON Lines format (.jsonl) for efficient appending.
        Each participant gets their own log file.

        Args:
            subject_id: The participant's subject ID
            log_entry: The log entry dict to persist
        """
        try:
            # Get or create file handle for this subject
            if subject_id not in self._console_log_files:
                filepath = os.path.join(
                    self.CONSOLE_LOGS_DIR,
                    f"{subject_id}_console.jsonl"
                )
                self._console_log_files[subject_id] = open(filepath, 'a', encoding='utf-8')
                logger.debug(f"Opened console log file for {subject_id}: {filepath}")

            # Write log entry as JSON line
            file_handle = self._console_log_files[subject_id]
            file_handle.write(json.dumps(log_entry) + '\n')
            file_handle.flush()  # Ensure data is written immediately

        except Exception as e:
            logger.warning(f"Failed to persist console log for {subject_id}: {e}")

    def close_console_log_files(self) -> None:
        """
        Close all open console log file handles.

        Should be called during server shutdown or when cleaning up.
        """
        for subject_id, file_handle in list(self._console_log_files.items()):
            try:
                file_handle.close()
                logger.debug(f"Closed console log file for {subject_id}")
            except Exception as e:
                logger.warning(f"Error closing console log file for {subject_id}: {e}")
        self._console_log_files.clear()
        logger.info("All console log files closed")

    def close_subject_console_log(self, subject_id: str) -> None:
        """
        Close the console log file for a specific subject.

        Called when a participant completes their session.

        Args:
            subject_id: The participant's subject ID
        """
        if subject_id in self._console_log_files:
            try:
                self._console_log_files[subject_id].close()
                del self._console_log_files[subject_id]
                logger.debug(f"Closed console log file for completed subject: {subject_id}")
            except Exception as e:
                logger.warning(f"Error closing console log file for {subject_id}: {e}")

    def emit_console_log(self, log_entry: dict) -> None:
        """
        Immediately emit single console log entry to admins.

        Args:
            log_entry: The log entry dict to emit
        """
        try:
            self.sio.emit(
                'console_log',
                log_entry,
                namespace='/admin',
                room='admin_broadcast'
            )
        except Exception as e:
            logger.debug(f"Error emitting console log: {e}")

    def log_activity(self, event_type: str, subject_id: str, details: dict | None = None) -> None:
        """
        Log an activity event and immediately emit to admins.

        Args:
            event_type: Type of event (join, scene_advance, disconnect, game_start, game_end)
            subject_id: The subject ID involved
            details: Optional additional details dict
        """
        event = ActivityEvent(
            timestamp=time.time(),
            event_type=event_type,
            subject_id=subject_id,
            details=details or {}
        )

        # Append to activity log (deque auto-removes old entries when full)
        self._activity_log.append(event)

        logger.debug(f"Activity logged: {event_type} for {subject_id}")

        # Immediately emit to admins for real-time timeline
        self.emit_activity(event)

    def emit_activity(self, event: ActivityEvent) -> None:
        """
        Immediately emit single activity event to admins.

        Args:
            event: The ActivityEvent to emit
        """
        try:
            self.sio.emit(
                'activity_event',
                {
                    'timestamp': event.timestamp,
                    'event_type': event.event_type,
                    'subject_id': event.subject_id,
                    'details': event.details
                },
                namespace='/admin',
                room='admin_broadcast'
            )
        except Exception as e:
            logger.debug(f"Error emitting activity event: {e}")

    def start_broadcast_loop(self, interval_seconds: float = 1.0) -> None:
        """
        Start periodic state broadcast to admin clients.

        Uses eventlet.spawn to run in background.
        Throttles emissions: only emits if state changed or every 2 seconds regardless.

        Args:
            interval_seconds: How often to check for state changes (default 1.0)
        """
        if self._broadcast_running:
            logger.warning("Broadcast loop already running")
            return

        self._broadcast_running = True
        self._broadcast_interval = interval_seconds

        def _broadcast_loop():
            logger.info(f"Admin broadcast loop started (interval: {interval_seconds}s)")
            while self._broadcast_running:
                try:
                    self._broadcast_state()
                except Exception as e:
                    logger.error(f"Error in broadcast loop: {e}")
                eventlet.sleep(interval_seconds)

        eventlet.spawn(_broadcast_loop)
        logger.info("Admin broadcast loop spawned")

    def stop_broadcast_loop(self) -> None:
        """Stop the periodic broadcast loop and clean up resources."""
        self._broadcast_running = False
        self.close_console_log_files()
        logger.info("Admin broadcast loop stopped")

    def _broadcast_state(self) -> None:
        """
        Broadcast state to admin clients if changed or timeout elapsed.

        Only emits if:
        - State hash changed since last broadcast, OR
        - More than 2 seconds since last broadcast (heartbeat)
        """
        snapshot = self.get_experiment_snapshot()

        # Compute hash of current state for change detection
        # Use summary + participant count for quick hash (not full state)
        state_key = json.dumps({
            'summary': snapshot['summary'],
            'participant_count': len(snapshot['participants']),
            'waiting_room_count': len(snapshot['waiting_rooms'])
        }, sort_keys=True)
        state_hash = hashlib.md5(state_key.encode()).hexdigest()

        current_time = time.time()
        time_since_last = current_time - self._last_broadcast_time

        # Emit if state changed OR 2 seconds elapsed (heartbeat)
        should_emit = (
            state_hash != self._last_state_hash or
            time_since_last >= 2.0
        )

        if should_emit:
            try:
                self.sio.emit(
                    'state_update',
                    snapshot,
                    namespace='/admin',
                    room='admin_broadcast'
                )
                self._last_state_hash = state_hash
                self._last_broadcast_time = current_time
                logger.debug(f"Broadcast state update (changed={state_hash != self._last_state_hash})")
            except Exception as e:
                logger.error(f"Error broadcasting state: {e}")
