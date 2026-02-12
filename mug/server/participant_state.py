"""Participant lifecycle state tracking.

This module provides state tracking for participants across the experiment lifecycle,
complementary to SessionState which tracks game/session lifecycle.

SessionState (in remote_game.py): Tracks GAME lifecycle (per-game)
ParticipantState (this file): Tracks PARTICIPANT lifecycle (per-participant, across games)
"""

from __future__ import annotations

import logging
from enum import Enum, auto

logger = logging.getLogger(__name__)


class ParticipantState(Enum):
    """Participant lifecycle states.

    These states track where a participant is in their experiment flow:
    - IDLE: Not in any game or waiting room
    - IN_WAITROOM: Waiting to be matched with other players
    - IN_GAME: Actively playing a game
    - GAME_ENDED: Game finished (terminal until reset)
    """
    IDLE = auto()
    IN_WAITROOM = auto()
    IN_GAME = auto()
    GAME_ENDED = auto()


# Valid participant state transitions
VALID_TRANSITIONS = {
    ParticipantState.IDLE: {ParticipantState.IN_WAITROOM},  # Join waiting room
    ParticipantState.IN_WAITROOM: {
        ParticipantState.IN_GAME,  # Match found, game starts
        ParticipantState.IDLE,     # Waitroom timeout, disconnect
    },
    ParticipantState.IN_GAME: {
        ParticipantState.GAME_ENDED,  # Game completes
        ParticipantState.IDLE,        # Disconnect mid-game
    },
    ParticipantState.GAME_ENDED: {ParticipantState.IDLE},  # Ready for new game
}


class ParticipantStateTracker:
    """Tracks participant lifecycle states as single source of truth.

    Prevents participants from being routed to wrong games by validating
    state before routing and updating state at every transition point.
    """

    def __init__(self):
        """Initialize the tracker with empty state dictionary."""
        self._states: dict[str, ParticipantState] = {}

    def get_state(self, subject_id: str) -> ParticipantState:
        """Get current state for a participant.

        Args:
            subject_id: The participant's subject ID

        Returns:
            Current ParticipantState, or IDLE if not tracked
        """
        return self._states.get(subject_id, ParticipantState.IDLE)

    def transition_to(self, subject_id: str, new_state: ParticipantState) -> bool:
        """Validate and apply state transition.

        Args:
            subject_id: The participant's subject ID
            new_state: Target state

        Returns:
            True if transition successful, False if invalid
        """
        current_state = self.get_state(subject_id)
        valid_targets = VALID_TRANSITIONS.get(current_state, set())

        if new_state not in valid_targets:
            logger.error(
                f"[ParticipantState] Invalid transition for {subject_id}: "
                f"{current_state.name} -> {new_state.name}. "
                f"Valid transitions: {[s.name for s in valid_targets]}"
            )
            return False

        self._states[subject_id] = new_state
        logger.info(
            f"[ParticipantState] {subject_id}: {current_state.name} -> {new_state.name}"
        )
        return True

    def reset(self, subject_id: str) -> None:
        """Remove participant from tracking (returns to implicit IDLE).

        Args:
            subject_id: The participant's subject ID
        """
        if subject_id in self._states:
            old_state = self._states[subject_id]
            del self._states[subject_id]
            logger.info(
                f"[ParticipantState] {subject_id}: reset from {old_state.name} to IDLE"
            )

    def is_idle(self, subject_id: str) -> bool:
        """Check if participant is in IDLE state.

        Args:
            subject_id: The participant's subject ID

        Returns:
            True if IDLE (or not tracked), False otherwise
        """
        return self.get_state(subject_id) == ParticipantState.IDLE

    def can_join_waitroom(self, subject_id: str) -> bool:
        """Check if participant can join a waiting room.

        Only participants in IDLE state can join waiting rooms.

        Args:
            subject_id: The participant's subject ID

        Returns:
            True if can join, False otherwise
        """
        return self.is_idle(subject_id)
