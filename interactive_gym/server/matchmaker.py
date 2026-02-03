"""Matchmaking abstraction for participant grouping strategies.

This module provides the pluggable matchmaking interface that allows researchers
to customize how participants are grouped together for games.

The default FIFOMatchmaker implements first-in-first-out matching (current behavior).
Researchers can implement custom Matchmaker subclasses for RTT-based matching,
skill-based matching, or other grouping strategies.

RTT Configuration Notes:
    - rtt_ms in MatchCandidate is SERVER RTT (client <-> server round-trip)
    - max_p2p_rtt_ms is P2P RTT (peer-to-peer via WebRTC DataChannel)
    - P2P RTT filtering happens AFTER matchmaker proposes, not inside find_match()
    - GameManager orchestrates: propose match -> probe P2P RTT -> accept/reject
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class MatchCandidate:
    """Context for matchmaking decisions.

    Represents a participant who is either arriving at or already in the waitroom.

    Attributes:
        subject_id: Unique identifier for the participant
        rtt_ms: Round-trip time in milliseconds (None if not measured)
    """

    subject_id: str
    rtt_ms: int | None = None
    # Future: custom attributes from Phase 56


class Matchmaker(ABC):
    """Abstract base class for matchmaking strategies.

    Subclasses implement find_match() to determine when and how
    participants are grouped together for a game.

    The matchmaker is called each time a participant arrives at the waitroom.
    It receives the arriving participant, the list of waiting participants,
    and the group size needed. It returns either a list of matched participants
    or None to indicate the arriving participant should continue waiting.

    Thread safety: find_match() is called under the GameManager's waiting_games_lock.
    Custom matchmakers should not spawn threads or access external resources
    that could cause race conditions.

    P2P RTT Filtering:
        If max_p2p_rtt_ms is set, GameManager will probe the P2P RTT between
        matched candidates AFTER find_match() proposes them. If P2P RTT exceeds
        the threshold, the match is rejected and candidates are re-pooled.
        Subclasses can override should_reject_for_rtt() to customize rejection logic.
    """

    def __init__(self, max_p2p_rtt_ms: int | None = None):
        """Initialize matchmaker.

        Args:
            max_p2p_rtt_ms: Maximum allowed P2P RTT in milliseconds for matched pairs.
                            If None (default), no P2P RTT filtering is applied.
                            If set, matches exceeding this threshold are rejected.
        """
        self.max_p2p_rtt_ms = max_p2p_rtt_ms

    def should_reject_for_rtt(self, measured_rtt_ms: float | None) -> bool:
        """Determine if a match should be rejected based on measured P2P RTT.

        Called by GameManager after probing P2P RTT between matched candidates.
        Subclasses can override for custom rejection logic.

        Args:
            measured_rtt_ms: Measured P2P RTT in milliseconds, or None if measurement failed.

        Returns:
            True if match should be rejected, False if acceptable.
        """
        if self.max_p2p_rtt_ms is None:
            return False  # No threshold configured, accept all
        if measured_rtt_ms is None:
            return True  # Measurement failed, reject for safety
        return measured_rtt_ms > self.max_p2p_rtt_ms

    @abstractmethod
    def find_match(
        self,
        arriving: MatchCandidate,
        waiting: list[MatchCandidate],
        group_size: int,
    ) -> list[MatchCandidate] | None:
        """Attempt to form a group including the arriving participant.

        Args:
            arriving: The participant who just arrived at the waitroom.
                      This participant is NOT in the waiting list.
            waiting: List of participants already waiting in the waitroom.
                     May be empty if this is the first participant.
            group_size: Number of participants needed for a full group
                        (typically 2 for two-player games).

        Returns:
            list[MatchCandidate]: A list of exactly group_size MatchCandidates
                if a match is found. MUST include the arriving participant.
            None: If no match is possible and the arriving participant should
                wait in the waitroom.

        Notes:
            - The returned list MUST include the arriving participant
            - The returned list should have exactly group_size participants
            - Do NOT modify the waiting list - return a new list instead
            - If match is found, GameManager removes matched participants from waitroom
        """
        ...


class FIFOMatchmaker(Matchmaker):
    """First-in-first-out matchmaking (default behavior).

    Matches participants in arrival order without any filtering.
    This replicates the original hard-coded matching behavior.

    If max_p2p_rtt_ms is set, GameManager will probe P2P RTT between
    matched candidates after find_match() proposes them. Matches
    exceeding the threshold are rejected and candidates re-pooled.

    Example:
        For a 2-player game with group_size=2:
        - Player A arrives, waiting=[] -> returns None (wait)
        - Player B arrives, waiting=[A] -> returns [A, B] (match)

        For a 3-player game with group_size=3:
        - Player A arrives, waiting=[] -> returns None (wait)
        - Player B arrives, waiting=[A] -> returns None (wait)
        - Player C arrives, waiting=[A, B] -> returns [A, B, C] (match)

    Args:
        max_p2p_rtt_ms: Maximum allowed P2P RTT in ms. None disables filtering.
    """

    def __init__(self, max_p2p_rtt_ms: int | None = None):
        super().__init__(max_p2p_rtt_ms=max_p2p_rtt_ms)

    def find_match(
        self,
        arriving: MatchCandidate,
        waiting: list[MatchCandidate],
        group_size: int,
    ) -> list[MatchCandidate] | None:
        # Need enough participants to form a group
        if len(waiting) + 1 < group_size:
            return None

        # Take first (group_size - 1) waiting participants + arriving
        matched = waiting[: group_size - 1] + [arriving]
        return matched
