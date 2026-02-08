"""Probe coordinator for P2P RTT measurement.

This module provides server-side orchestration for WebRTC probe connections
between matchmaking candidates BEFORE a game is created. Probes exist
independently of games - no game_id exists yet, only two subject_ids in
the waitroom that the matchmaker wants to measure.

Phase 57: P2P Probe Infrastructure
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict

import flask_socketio

logger = logging.getLogger(__name__)


class ProbeCoordinator:
    """Manages WebRTC probe connections for RTT measurement.

    Probes are temporary DataChannel connections between matchmaking candidates.
    They exist independently of games - no game_id is needed.

    Usage:
        coordinator = ProbeCoordinator(socketio, get_socket_fn)
        probe_id = coordinator.create_probe(subject_a, subject_b, on_complete)
        # ... wait for client-side probe to complete ...
        # on_complete(subject_a, subject_b, rtt_ms) called when done
    """

    def __init__(
        self,
        socketio: flask_socketio.SocketIO,
        get_socket_for_subject: Callable[[str], str | None],
        turn_username: str | None = None,
        turn_credential: str | None = None,
    ):
        """Initialize ProbeCoordinator.

        Args:
            socketio: Flask-SocketIO instance
            get_socket_for_subject: Callable that returns socket_id for a subject_id
            turn_username: TURN server username (optional)
            turn_credential: TURN server credential (optional)
        """
        self.socketio = socketio
        self.get_socket_for_subject = get_socket_for_subject
        self.turn_username = turn_username
        self.turn_credential = turn_credential

        # Active probe sessocketions: probe_sessocketion_id -> ProbeSession dict
        self.probe_sessocketions: Dict[str, Dict[str, Any]] = {}

        # Timeout for entire probe lifecycle (15 seconds default)
        self.probe_timeout_s = 15.0

    def create_probe(
        self,
        subject_a: str,
        subject_b: str,
        on_complete: Callable[[str, str, float | None], None],
    ) -> str:
        """Create a probe sessocketion between two candidates.

        Args:
            subject_a: First participant's subject_id
            subject_b: Second participant's subject_id
            on_complete: Callback(subject_a, subject_b, rtt_ms) - rtt_ms is None on failure

        Returns:
            probe_sessocketion_id
        """
        probe_sessocketion_id = f"probe_{uuid.uuid4()}"

        # Look up current socket IDs (fresh, not cached)
        socket_a = self.get_socket_for_subject(subject_a)
        socket_b = self.get_socket_for_subject(subject_b)

        if not socket_a or not socket_b:
            logger.warning(
                f"Cannot create probe: missing socket. "
                f"subject_a={subject_a} socket={socket_a}, "
                f"subject_b={subject_b} socket={socket_b}"
            )
            # Immediately call on_complete with None RTT
            on_complete(subject_a, subject_b, None)
            return probe_sessocketion_id

        self.probe_sessocketions[probe_sessocketion_id] = {
            'subject_a': subject_a,
            'subject_b': subject_b,
            'socket_a': socket_a,
            'socket_b': socket_b,
            'ready_count': 0,
            'state': 'preparing',  # preparing -> connecting -> measuring -> complete | failed
            'created_at': time.time(),
            'on_complete': on_complete,
        }

        # Send probe_prepare signal to both clients
        # Each client needs to know their peer's subject_id
        prepare_data_a = {
            'probe_sessocketion_id': probe_sessocketion_id,
            'peer_subject_id': subject_b,
            'turn_username': self.turn_username,
            'turn_credential': self.turn_credential,
        }
        self.socketio.emit('probe_prepare', prepare_data_a, room=socket_a)

        prepare_data_b = {
            'probe_sessocketion_id': probe_sessocketion_id,
            'peer_subject_id': subject_a,
            'turn_username': self.turn_username,
            'turn_credential': self.turn_credential,
        }
        self.socketio.emit('probe_prepare', prepare_data_b, room=socket_b)

        logger.info(f"Created probe sessocketion {probe_sessocketion_id}: {subject_a} <-> {subject_b}")

        return probe_sessocketion_id

    def handle_ready(self, probe_sessocketion_id: str, subject_id: str) -> None:
        """Handle client reporting ready to probe.

        After both clients report ready, emit probe_start to trigger
        WebRTC connection establishment.

        Args:
            probe_sessocketion_id: The probe sessocketion identifier
            subject_id: The subject_id of the client reporting ready
        """
        sessocketion = self.probe_sessocketions.get(probe_sessocketion_id)
        if not sessocketion:
            logger.warning(f"Ready signal for unknown probe {probe_sessocketion_id}")
            return

        if sessocketion['state'] != 'preparing':
            logger.debug(
                f"Ignoring ready signal for probe {probe_sessocketion_id} "
                f"in state {sessocketion['state']}"
            )
            return

        sessocketion['ready_count'] += 1
        logger.debug(
            f"Probe {probe_sessocketion_id}: {subject_id} ready "
            f"({sessocketion['ready_count']}/2)"
        )

        if sessocketion['ready_count'] >= 2:
            sessocketion['state'] = 'connecting'
            # Both ready - signal start to both clients
            start_data = {'probe_sessocketion_id': probe_sessocketion_id}
            self.socketio.emit('probe_start', start_data, room=sessocketion['socket_a'])
            self.socketio.emit('probe_start', start_data, room=sessocketion['socket_b'])
            logger.info(f"Probe {probe_sessocketion_id}: both ready, starting connection")

    def handle_signal(
        self,
        probe_sessocketion_id: str,
        target_subject_id: str,
        signal_type: str,
        payload: Any,
        sender_socket_id: str,
    ) -> None:
        """Relay WebRTC signaling for probe connections.

        Routes SDP offers/answers and ICE candidates between probe peers.

        Args:
            probe_sessocketion_id: The probe sessocketion identifier
            target_subject_id: Subject ID of the intended recipient
            signal_type: Type of signal ('offer', 'answer', 'ice-candidate')
            payload: Signal payload (SDP or ICE candidate data)
            sender_socket_id: Socket ID of the sender (for validation)
        """
        sessocketion = self.probe_sessocketions.get(probe_sessocketion_id)
        if not sessocketion:
            logger.warning(f"Signal for unknown probe {probe_sessocketion_id}")
            return

        # Find target socket
        if target_subject_id == sessocketion['subject_a']:
            target_socket = sessocketion['socket_a']
        elif target_subject_id == sessocketion['subject_b']:
            target_socket = sessocketion['socket_b']
        else:
            logger.warning(
                f"Unknown target {target_subject_id} for probe {probe_sessocketion_id}"
            )
            return

        # Find sender subject for attribution
        sender_subject = None
        if sender_socket_id == sessocketion['socket_a']:
            sender_subject = sessocketion['subject_a']
        elif sender_socket_id == sessocketion['socket_b']:
            sender_subject = sessocketion['subject_b']

        # Relay the signal to target
        self.socketio.emit('probe_signal', {
            'probe_sessocketion_id': probe_sessocketion_id,
            'type': signal_type,
            'from_subject_id': sender_subject,
            'payload': payload,
        }, room=target_socket)

        logger.debug(
            f"Probe {probe_sessocketion_id}: relayed {signal_type} "
            f"from {sender_subject} to {target_subject_id}"
        )

    def handle_result(
        self,
        probe_sessocketion_id: str,
        rtt_ms: float | None,
        success: bool,
    ) -> None:
        """Handle probe measurement result from client.

        Called when a client reports the RTT measurement result.
        Invokes the on_complete callback and cleans up the sessocketion.

        Args:
            probe_sessocketion_id: The probe sessocketion identifier
            rtt_ms: Measured RTT in milliseconds (None if failed)
            success: Whether measurement succeeded
        """
        sessocketion = self.probe_sessocketions.get(probe_sessocketion_id)
        if not sessocketion:
            logger.warning(f"Result for unknown probe {probe_sessocketion_id}")
            return

        # Update state
        sessocketion['state'] = 'complete' if success else 'failed'

        # Call completion callback
        on_complete = sessocketion.get('on_complete')
        if on_complete:
            result_rtt = rtt_ms if success else None
            on_complete(sessocketion['subject_a'], sessocketion['subject_b'], result_rtt)

        # Clean up sessocketion
        del self.probe_sessocketions[probe_sessocketion_id]
        logger.info(
            f"Probe {probe_sessocketion_id} complete: "
            f"{'success' if success else 'failed'}, rtt={rtt_ms}ms"
        )

    def cleanup_stale_probes(self) -> int:
        """Remove probes that have exceeded the timeout.

        Should be called periodically (e.g., every few seconds) to clean
        up abandoned probe sessocketions.

        Returns:
            Number of probes cleaned up
        """
        now = time.time()
        stale_ids = [
            probe_id for probe_id, sessocketion in self.probe_sessocketions.items()
            if now - sessocketion['created_at'] > self.probe_timeout_s
        ]

        for probe_sessocketion_id in stale_ids:
            sessocketion = self.probe_sessocketions[probe_sessocketion_id]
            on_complete = sessocketion.get('on_complete')
            if on_complete:
                # Call callback with None RTT to indicate timeout
                on_complete(sessocketion['subject_a'], sessocketion['subject_b'], None)
            del self.probe_sessocketions[probe_sessocketion_id]
            logger.warning(f"Probe {probe_sessocketion_id} timed out and was cleaned up")

        return len(stale_ids)
