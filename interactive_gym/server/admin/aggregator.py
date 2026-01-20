"""
Admin Event Aggregator for collecting and projecting experiment state.

Uses observer pattern - reads existing state structures without modifying them.
Emits to admin namespace at 1-2 Hz (throttled).
"""
from __future__ import annotations

import hashlib
import json
import logging
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

    def __init__(
        self,
        sio: flask_socketio.SocketIO,
        participant_sessions: dict,  # PARTICIPANT_SESSIONS
        stagers: dict,               # STAGERS
        game_managers: dict,         # GAME_MANAGERS
        pyodide_coordinator: PyodideGameCoordinator | None = None,
        processed_subjects: list | None = None  # PROCESSED_SUBJECT_NAMES
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

        # Broadcast loop state
        self._broadcast_running = False
        self._last_state_hash: str | None = None
        self._last_broadcast_time: float = 0

        logger.info("AdminEventAggregator initialized")

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

        # Get active games count
        active_games = 0
        if self.pyodide_coordinator:
            active_games = len(self.pyodide_coordinator.games)

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

        summary = {
            'total_participants': len(participants),
            'connected_count': connected_count,
            'disconnected_count': disconnected_count,
            'reconnecting_count': reconnecting_count,
            'completed_count': completed_count,
            'active_games': active_games,
            'waiting_count': waiting_count,
            'timestamp': time.time()
        }

        return {
            'participants': participants,
            'waiting_rooms': waiting_rooms,
            'activity_log': recent_activity,
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
            'connection_status': self._compute_connection_status(session, subject_id),
            'current_scene_id': session.current_scene_id,
            'scene_progress': scene_progress,
            'created_at': session.created_at,
            'last_updated_at': session.last_updated_at
        }

    def _compute_connection_status(self, session: Any, subject_id: str) -> str:
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
        """Stop the periodic broadcast loop."""
        self._broadcast_running = False
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
