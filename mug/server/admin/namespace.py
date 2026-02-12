"""
Admin SocketIO namespace for real-time dashboard updates.

This namespace is isolated from the participant namespace (/) to ensure:
- Admin traffic doesn't pollute participant rooms
- Different authentication can be applied
- Can be disabled in production without affecting participants
"""
from __future__ import annotations

import logging

from flask import session
from flask_login import current_user
from flask_socketio import Namespace, emit, join_room, leave_room

logger = logging.getLogger(__name__)


class AdminNamespace(Namespace):
    """
    Handles all admin client connections on /admin namespace.

    Security: Requires authenticated admin session before allowing connection.
    """

    def __init__(self, namespace, aggregator=None):
        """
        Initialize admin namespace.

        Args:
            namespace: The namespace path (should be '/admin')
            aggregator: Optional AdminEventAggregator for state access (Phase 8+)
        """
        super().__init__(namespace)
        self.aggregator = aggregator
        logger.info(f"AdminNamespace initialized on {namespace}")

    def on_connect(self):
        """
        Handle admin client connection.

        Verifies the user is authenticated before allowing connection.
        Joins the admin_broadcast room for receiving updates.
        """
        # Check if user is authenticated via Flask-Login session
        if not current_user.is_authenticated:
            logger.warning("Unauthenticated admin connection attempt rejected")
            return False  # Reject connection

        logger.info(f"Admin connected: {current_user.get_id()}")

        # Join broadcast room for receiving state updates
        join_room('admin_broadcast')

        # Send initial connection confirmation
        emit('admin_connected', {
            'status': 'connected',
            'message': 'Admin dashboard connected to /admin namespace'
        })

        return True

    def on_disconnect(self):
        """Handle admin client disconnection."""
        logger.info("Admin disconnected from /admin namespace")
        leave_room('admin_broadcast')

    def on_request_state(self):
        """
        Admin requests current experiment state snapshot.

        Will be implemented in Phase 8 when AdminEventAggregator is added.
        """
        logger.debug("Admin requested state snapshot")

        if self.aggregator:
            # Phase 8: Return aggregated state
            state = self.aggregator.get_experiment_snapshot()
            emit('state_update', state)
        else:
            # Fallback if aggregator not initialized
            emit('state_update', {
                'participants': [],
                'waiting_rooms': [],
                'activity_log': [],
                'summary': {'total_participants': 0, 'active_games': 0, 'waiting_count': 0},
                'message': 'Aggregator not initialized'
            })

    def on_subscribe_participant(self, data):
        """
        Subscribe to updates for a specific participant.

        Args:
            data: {'subject_id': str}
        """
        subject_id = data.get('subject_id')
        if subject_id:
            join_room(f'admin_participant_{subject_id}')
            logger.debug(f"Admin subscribed to participant {subject_id}")

    def on_unsubscribe_participant(self, data):
        """
        Unsubscribe from a specific participant's updates.

        Args:
            data: {'subject_id': str}
        """
        subject_id = data.get('subject_id')
        if subject_id:
            leave_room(f'admin_participant_{subject_id}')
            logger.debug(f"Admin unsubscribed from participant {subject_id}")
