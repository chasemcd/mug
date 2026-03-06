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

    from mug.server.app import ParticipantSession
    from mug.server.pyodide_game_coordinator import PyodideGameCoordinator

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

    def __init__(
        self,
        socketio: flask_socketio.SocketIO,
        participant_sessions: dict,  # PARTICIPANT_SESSIONS
        stagers: dict,               # STAGERS
        game_managers: dict,         # GAME_MANAGERS
        pyodide_coordinator: PyodideGameCoordinator | None = None,
        processed_subjects: list | None = None,  # PROCESSED_SUBJECT_NAMES
        save_console_logs: bool = True,
        experiment_id: str | None = None
    ):
        """
        Initialize the aggregator with references to experiment state.

        Args:
            socketio: Flask-SocketIO instance for emitting updates
            participant_sessions: Reference to PARTICIPANT_SESSIONS dict
            stagers: Reference to STAGERS dict
            game_managers: Reference to GAME_MANAGERS dict
            pyodide_coordinator: Optional PyodideGameCoordinator reference
            processed_subjects: Optional list of completed subject IDs
            save_console_logs: Whether to persist console logs to disk
        """
        # Set console logs directory using experiment_id
        if experiment_id:
            self.console_logs_dir = f"data/{experiment_id}/console_logs"
        else:
            self.console_logs_dir = "data/console_logs"

        # Store references (read-only access)
        # Do NOT modify these - observer pattern only
        self.socketio = socketio
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
            os.makedirs(self.console_logs_dir, exist_ok=True)
            logger.info(f"Console logs will be saved to {self.console_logs_dir}/")

        # Session completion tracking for duration calculation
        # Maps subject_id -> {started_at: float, completed_at: float}
        self._completed_sessions: dict[str, dict] = {}

        # Track all subjects who have ever started (for total_started calculation)
        self._all_started_subjects: set[str] = set()

        # Participant lifecycle tracking (Phase 35 rework)
        # Maps subject_id -> list of game participations
        # Each entry: {game_id, started_at, ended_at, role, termination_reason}
        self._participant_games: dict[str, list[dict]] = {}

        # P2P health cache (Phase 33)
        # Maps game_id -> {player_id -> health_data}
        # health_data: {connection_type, latency_ms, status, episode, timestamp}
        self._p2p_health_cache: dict[str, dict[str, dict]] = {}
        self._p2p_health_expiry_seconds = 10  # Auto-expire entries older than this

        # Session termination tracking (Phase 34)
        # Maps game_id -> {reason: str, timestamp: float, players: list[str], details: dict}
        self._session_terminations: dict[str, dict] = {}

        # Completed/historical sessions (Phase 35)
        # Stores finished sessions for historical viewing in admin console
        # Maps game_id -> full session state dict at time of completion
        self._completed_games: dict[str, dict] = {}
        self.MAX_COMPLETED_GAMES = 100  # Limit historical sessions

        # === Aggregate Metrics (Admin Console v2) ===

        # Session termination counts by reason
        self._termination_counts: dict[str, int] = {
            'normal': 0,
            'partner_disconnected': 0,
            'focus_loss_timeout': 0,
            'sustained_ping': 0,
            'tab_hidden': 0,
            'exclusion': 0,
            'reconnection_timeout': 0,
            'waitroom_timeout': 0,
            'other': 0
        }

        # Wait time samples (milliseconds) for waitroom duration analysis
        self._wait_time_samples: deque[float] = deque(maxlen=500)

        # Latency samples for trend visualization
        # Each entry: {timestamp: float, latency_ms: int, game_id: str}
        self._latency_samples: deque[dict] = deque(maxlen=1000)

        # Problems list for real-time alerts
        # Each entry: {timestamp, type, severity, message, subject_id, game_id}
        self._problems: deque[dict] = deque(maxlen=200)

        # Scene ending counts for histogram
        # Maps scene_id -> count of sessions that ended at that scene
        self._scene_ending_counts: dict[str, int] = {}

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
        # Initialize participant games list
        if subject_id not in self._participant_games:
            self._participant_games[subject_id] = []

    def record_session_termination(
        self,
        game_id: str,
        reason: str,
        players: list[str],
        details: dict | None = None,
        session_snapshot: dict | None = None
    ) -> None:
        """
        Record session termination with reason for detail view.

        Args:
            game_id: The game ID
            reason: Termination reason (partner_disconnected, focus_loss_timeout,
                    sustained_ping, tab_hidden, exclusion, normal)
            players: List of player subject IDs
            details: Optional additional details (exclusion message, etc.)
            session_snapshot: Optional full session state at time of termination
        """
        termination_info = {
            'reason': reason,
            'timestamp': time.time(),
            'players': players,
            'details': details or {}
        }
        self._session_terminations[game_id] = termination_info

        # Increment termination count for aggregates
        if reason in self._termination_counts:
            self._termination_counts[reason] += 1
        else:
            self._termination_counts['other'] += 1

        # Add problem entry for non-normal terminations
        if reason != 'normal':
            self._add_problem(
                problem_type='session',
                severity='warning' if reason in ('tab_hidden', 'focus_loss_timeout') else 'error',
                message=f"Session ended: {reason}",
                subject_id=players[0] if players else None,
                game_id=game_id
            )

        # Track scene ending for histogram
        if session_snapshot:
            scene_id = session_snapshot.get('scene_id')
            if scene_id:
                self._scene_ending_counts[scene_id] = self._scene_ending_counts.get(scene_id, 0) + 1

        # Store completed session for history
        if session_snapshot:
            self._add_completed_game(game_id, session_snapshot, termination_info)

        logger.debug(f"Session termination recorded for {game_id}: {reason}")

    def _add_completed_game(
        self,
        game_id: str,
        session_snapshot: dict,
        termination_info: dict
    ) -> None:
        """
        Add a completed game to history.

        Args:
            game_id: The game ID
            session_snapshot: Full session state at completion
            termination_info: Termination reason and details
        """
        # Get player console logs before archiving
        subject_ids = session_snapshot.get('subject_ids', [])
        archived_logs = [
            log for log in list(self._console_logs)
            if log.get('subject_id') in subject_ids
        ][-100:]  # Keep last 100 logs for this session

        # Add termination info and logs to snapshot
        completed_session = {
            **session_snapshot,
            'termination': termination_info,
            'completed_at': time.time(),
            'archived_logs': archived_logs
        }
        self._completed_games[game_id] = completed_session

        # Trim old entries if over limit (keep most recent)
        if len(self._completed_games) > self.MAX_COMPLETED_GAMES:
            # Sort by completed_at and remove oldest
            sorted_ids = sorted(
                self._completed_games.keys(),
                key=lambda gid: self._completed_games[gid].get('completed_at', 0)
            )
            # Remove oldest entries
            for old_id in sorted_ids[:len(self._completed_games) - self.MAX_COMPLETED_GAMES]:
                del self._completed_games[old_id]

        logger.debug(f"Added completed game to history: {game_id}")

    def track_waitroom_timeout(self, subject_id: str, scene_id: str | None = None) -> None:
        """
        Track when a participant times out in the waitroom.

        Args:
            subject_id: The participant's subject ID
            scene_id: Optional scene ID where timeout occurred
        """
        self._termination_counts['waitroom_timeout'] += 1

        # Track scene ending
        if scene_id:
            self._scene_ending_counts[scene_id] = self._scene_ending_counts.get(scene_id, 0) + 1

        # Add as a problem (info level - not really an error)
        self._add_problem(
            problem_type='session',
            severity='info',
            message='Waitroom timeout',
            subject_id=subject_id
        )

        logger.debug(f"Waitroom timeout recorded for {subject_id} at scene {scene_id}")

    def _add_problem(
        self,
        problem_type: str,
        severity: str,
        message: str,
        subject_id: str | None = None,
        game_id: str | None = None
    ) -> None:
        """
        Add a problem entry for the problems panel.

        Args:
            problem_type: 'error', 'warning', or 'session'
            severity: 'error', 'warning', or 'info'
            message: Problem description
            subject_id: Optional participant ID
            game_id: Optional game ID
        """
        self._problems.append({
            'timestamp': time.time(),
            'type': problem_type,
            'severity': severity,
            'message': message,
            'subject_id': subject_id,
            'game_id': game_id
        })

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

        # Store latency sample for trend visualization
        latency_ms = health_data.get('latency_ms')
        if latency_ms is not None:
            self._latency_samples.append({
                'timestamp': time.time(),
                'latency_ms': latency_ms,
                'game_id': game_id
            })

            # Add problem for high latency
            if latency_ms > 200:
                self._add_problem(
                    problem_type='warning',
                    severity='warning',
                    message=f"High latency: {latency_ms}ms",
                    game_id=game_id
                )

        # Add problem for degraded/reconnecting status
        status = health_data.get('status')
        if status == 'reconnecting':
            self._add_problem(
                problem_type='warning',
                severity='error',
                message="P2P reconnecting",
                game_id=game_id
            )
        elif status == 'degraded':
            self._add_problem(
                problem_type='warning',
                severity='warning',
                message="P2P connection degraded",
                game_id=game_id
            )

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

        # Get completed/historical sessions (last 50 for display)
        completed_games = self._get_completed_games_state()

        # Build aggregate metrics
        aggregates = self._get_aggregates()

        # Get recent problems (last 50)
        recent_problems = list(self._problems)[-50:]

        return {
            'participants': participants,
            'waiting_rooms': waiting_rooms,
            'multiplayer_games': active_games_list,  # Now includes both single-player and multiplayer
            'completed_games': completed_games,  # Historical sessions
            'activity_log': recent_activity,
            'console_logs': recent_console_logs,
            'summary': summary,
            'aggregates': aggregates,
            'problems': recent_problems
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

        # Get current game ID if in a game
        current_game_id = None
        if self.pyodide_coordinator:
            for game_id, game in self.pyodide_coordinator.games.items():
                if subject_id in game.player_subjects.values():
                    current_game_id = game_id
                    break

        # Get game history for this participant
        game_history = self._participant_games.get(subject_id, [])

        # Count logs for this participant (for badge display)
        log_count = sum(1 for log in self._console_logs if log.get('subject_id') == subject_id)
        error_count = sum(1 for log in self._console_logs
                        if log.get('subject_id') == subject_id and log.get('level') == 'error')

        # Check if participant is in a waitroom
        waitroom_info = self._get_participant_waitroom_info(subject_id)

        # Get current episode/round from game if in one
        current_episode = None
        if current_game_id and self.pyodide_coordinator:
            game = self.pyodide_coordinator.games.get(current_game_id)
            if game:
                # Try to get episode from P2P health data first
                p2p_health = self._get_p2p_health_for_game(current_game_id)
                for health_data in p2p_health.values():
                    ep = health_data.get('episode')
                    if ep is not None:
                        current_episode = ep
                        break

        return {
            'subject_id': subject_id,
            'connection_status': self._compute_connection_status(session, subject_id, stager),
            'current_scene_id': session.current_scene_id,
            'scene_progress': scene_progress,
            'created_at': session.created_at,
            'last_updated_at': session.last_updated_at,
            'current_game_id': current_game_id,
            'game_history': game_history,
            'log_count': log_count,
            'error_count': error_count,
            'waitroom_info': waitroom_info,
            'current_episode': current_episode
        }

    def _get_participant_waitroom_info(self, subject_id: str) -> dict | None:
        """
        Check if a participant is in a waitroom and return info.

        Args:
            subject_id: The participant's subject ID

        Returns:
            Dict with waitroom info (wait_duration_ms, group_id, waiting_count, target_size)
            or None if not waiting
        """
        import time
        now = time.time()

        # First check pyodide coordinator games (is_active=False means waiting)
        if self.pyodide_coordinator:
            for game_id, game in self.pyodide_coordinator.games.items():
                if subject_id in game.player_subjects.values():
                    # Check if game hasn't started yet (waiting room)
                    if not game.is_active:
                        # Calculate wait duration from game creation
                        wait_duration_ms = 0
                        if hasattr(game, 'created_at'):
                            wait_duration_ms = int((now - game.created_at) * 1000)

                        # Get current and target player counts
                        waiting_count = len(game.player_subjects)
                        target_size = game.num_expected_players

                        # Get scene_id from participant session if available
                        scene_id = None
                        session = self.participant_sessions.get(subject_id)
                        if session:
                            scene_id = session.current_scene_id

                        return {
                            'scene_id': scene_id,
                            'group_id': game_id,
                            'wait_duration_ms': max(0, wait_duration_ms),
                            'waiting_count': waiting_count,
                            'target_size': target_size
                        }
                    # Game is active, not in waitroom
                    return None

        for scene_id, game_manager in list(self.game_managers.items()):
            # Note: Group reunion waitrooms removed (deferred to REUN-01/REUN-02)
            # Check individual waiting games
            if hasattr(game_manager, 'waiting_games') and game_manager.waiting_games:
                for game_id in game_manager.waiting_games:
                    game = game_manager.games.get(game_id)
                    if game and hasattr(game, 'human_players'):
                        if subject_id in [str(p) for p in game.human_players.keys()]:
                            # Get wait duration from waitroom_timeouts if available
                            wait_duration_ms = 0
                            if hasattr(game_manager, 'waitroom_timeouts') and game_id in game_manager.waitroom_timeouts:
                                # Calculate how long they've been waiting
                                timeout_time = game_manager.waitroom_timeouts[game_id]
                                if hasattr(game_manager.scene, 'waitroom_timeout'):
                                    total_timeout = game_manager.scene.waitroom_timeout / 1000
                                    wait_duration_ms = int((total_timeout - (timeout_time - now)) * 1000)

                            target_size = getattr(game_manager.scene, 'num_players', 2) if hasattr(game_manager, 'scene') else 2

                            return {
                                'scene_id': scene_id,
                                'group_id': None,
                                'wait_duration_ms': max(0, wait_duration_ms),
                                'waiting_count': len(game.human_players),
                                'target_size': target_size
                            }

        return None

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

            # Note: Group reunion waitrooms removed (deferred to REUN-01/REUN-02)
            # Average wait time tracked through _wait_time_samples
            avg_wait_ms = 0

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

        # Build set of connected participant IDs for filtering stale games
        connected_subjects = set()
        for subject_id in list(self.participant_sessions.keys()):
            session = self.participant_sessions.get(subject_id)
            if session and session.socket_id:
                connected_subjects.add(subject_id)

        # 1. Get multiplayer games from coordinator
        if self.pyodide_coordinator:
            try:
                for game_id, game_state in list(self.pyodide_coordinator.games.items()):
                    tracked_game_ids.add(game_id)

                    # Get subject IDs for this game
                    subject_ids = list(game_state.player_subjects.values())

                    # Filter: Only show games with at least one connected participant
                    if not any(sid in connected_subjects for sid in subject_ids):
                        continue  # No connected participants - skip stale game

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
                        'subject_ids': subject_ids,
                        'current_frame': game_state.frame_number,
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

                    # Filter: Only show games with at least one connected participant
                    if not any(sid in connected_subjects for sid in subject_ids):
                        continue  # No connected participants - skip stale game

                    games.append({
                        'game_id': game_id,
                        'players': list(game.human_players.keys()) if hasattr(game, 'human_players') else [],
                        'subject_ids': subject_ids,
                        'current_frame': getattr(game, 'tick_num', None),
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

    def _get_completed_games_state(self) -> list[dict]:
        """
        Get completed/historical game sessions for admin viewing.

        Returns:
            List of completed session dicts, sorted by completion time (most recent first)
        """
        # Sort by completed_at descending (most recent first)
        completed = sorted(
            self._completed_games.values(),
            key=lambda g: g.get('completed_at', 0),
            reverse=True
        )
        # Return last 50 for display
        return completed[:50]

    def _get_aggregates(self) -> dict:
        """
        Build aggregate metrics for admin dashboard.

        Returns:
            Dict with termination_counts, wait_time stats, latency samples
        """
        # Calculate total sessions ended
        total_ended = sum(self._termination_counts.values())

        # Calculate wait time stats
        wait_samples = list(self._wait_time_samples)
        wait_time = {
            'avg_ms': int(sum(wait_samples) / len(wait_samples)) if wait_samples else None,
            'max_ms': int(max(wait_samples)) if wait_samples else None,
            'min_ms': int(min(wait_samples)) if wait_samples else None,
            'count': len(wait_samples)
        }

        # Get latency samples for sparkline (last 100)
        latency_samples = list(self._latency_samples)[-100:]
        latency_values = [s['latency_ms'] for s in latency_samples if s.get('latency_ms') is not None]

        latency = {
            'current_avg_ms': int(sum(latency_values[-10:]) / len(latency_values[-10:])) if latency_values else None,
            'samples': latency_values[-50:]  # Last 50 for sparkline
        }

        # Calculate termination proportions with detailed breakdown
        # Completed = normal game completion
        completed_count = self._termination_counts.get('normal', 0)

        # Waitroom timeout = couldn't find a partner in time
        waitroom_timeout_count = self._termination_counts.get('waitroom_timeout', 0)

        # Partner away = partner stopped responding (focus loss, tab hidden)
        partner_away_count = (
            self._termination_counts.get('focus_loss_timeout', 0) +
            self._termination_counts.get('tab_hidden', 0)
        )

        # Partner left = partner explicitly disconnected/closed window
        partner_left_count = (
            self._termination_counts.get('partner_disconnected', 0) +
            self._termination_counts.get('reconnection_timeout', 0)
        )

        # Other = ping issues, exclusions, etc.
        other_count = (
            self._termination_counts.get('sustained_ping', 0) +
            self._termination_counts.get('exclusion', 0) +
            self._termination_counts.get('other', 0)
        )

        summary_stats = {
            'completed': completed_count,
            'waitroom_timeout': waitroom_timeout_count,
            'partner_away': partner_away_count,
            'partner_left': partner_left_count,
            'other': other_count,
            'total': total_ended
        }

        return {
            'termination_counts': dict(self._termination_counts),
            'total_sessions_ended': total_ended,
            'wait_time': wait_time,
            'latency': latency,
            'summary_stats': summary_stats,
            'scene_endings': dict(self._scene_ending_counts)
        }

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

        # Track errors and warnings as problems
        if level == 'error':
            self._add_problem(
                problem_type='error',
                severity='error',
                message=message[:100] if message else 'Unknown error',
                subject_id=subject_id
            )
        elif level == 'warn':
            self._add_problem(
                problem_type='warning',
                severity='warning',
                message=message[:100] if message else 'Warning',
                subject_id=subject_id
            )

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
                    self.console_logs_dir,
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
            self.socketio.emit(
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
            self.socketio.emit(
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
                self.socketio.emit(
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
