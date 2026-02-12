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

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

logger = logging.getLogger(__name__)


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
    group_history: GroupHistory | None = None  # Phase 78: group history for re-pairing


@dataclass
class GroupHistory:
    """Group membership history for a participant.

    Provided to matchmakers via MatchCandidate.group_history to enable
    re-pairing decisions. Contains the most recent group information.

    Attributes:
        previous_partners: Subject IDs of other members in the most recent group
        source_scene_id: Scene where the group was last formed
        group_id: Unique identifier for the group
    """

    previous_partners: list[str]
    source_scene_id: str | None = None
    group_id: str | None = None


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

    def rank_candidates(
        self,
        arriving: MatchCandidate,
        waiting: list[MatchCandidate],
        group_size: int,
    ) -> list[MatchCandidate]:
        """Return viable candidates in priority order for iterative P2P probing.

        When P2P RTT probing is enabled and a probe fails, GameManager uses
        this ordered list to try the next candidate. Override to customize
        candidate ordering or filtering.

        Default returns all waiting candidates in their current order (FIFO).

        Args:
            arriving: The participant who just arrived
            waiting: Participants already in the waitroom
            group_size: Number needed for a match

        Returns:
            Ordered list of candidates to try pairing with the arriving
            participant. Empty list if not enough participants.
        """
        if len(waiting) + 1 < group_size:
            return []
        return list(waiting)

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
        logger.info(
            f"[FIFOMatchmaker] find_match called: "
            f"arriving={arriving.subject_id}, "
            f"waiting={[w.subject_id for w in waiting]}, "
            f"group_size={group_size}"
        )

        # Need enough participants to form a group
        if len(waiting) + 1 < group_size:
            logger.info(
                f"[FIFOMatchmaker] Not enough participants: "
                f"{len(waiting) + 1} < {group_size}. Returning None (wait)."
            )
            return None

        # Take first (group_size - 1) waiting participants + arriving
        matched = waiting[: group_size - 1] + [arriving]
        logger.info(
            f"[FIFOMatchmaker] Match found! Returning: {[m.subject_id for m in matched]}"
        )
        return matched


class LatencyFIFOMatchmaker(Matchmaker):
    """Latency-aware FIFO matchmaker that pre-filters by estimated P2P RTT.

    Before proposing a FIFO match, this matchmaker estimates the peer-to-peer
    round-trip time between the arriving participant and each waiting candidate
    using the sum of their server RTTs as a heuristic:

        estimated_p2p_rtt = arriving.rtt_ms + candidate.rtt_ms

    Candidates whose estimated P2P RTT exceeds ``max_server_rtt_ms`` are skipped.
    Among the remaining candidates, standard FIFO ordering applies (earliest
    arrival is matched first).

    Missing RTT data (``rtt_ms is None``) does NOT exclude a candidate. When
    either participant lacks RTT measurements, the pair is treated as compatible
    to avoid penalizing participants for missing data.

    If ``max_p2p_rtt_ms`` is also set, GameManager will additionally probe the
    real P2P RTT after the match is proposed and reject matches exceeding that
    threshold. ``max_server_rtt_ms`` is a cheap pre-filter; ``max_p2p_rtt_ms``
    is a precise post-filter.

    Example:
        from mug.server.matchmaker import LatencyFIFOMatchmaker

        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200)

    Args:
        max_server_rtt_ms: Maximum allowed estimated P2P RTT in milliseconds,
            computed as the sum of the two participants' server RTTs. Candidates
            exceeding this threshold are skipped during match proposal.
        max_p2p_rtt_ms: Maximum allowed measured P2P RTT in milliseconds for
            post-match probe filtering. None disables post-match filtering.
    """

    def __init__(
        self,
        max_server_rtt_ms: int,
        max_p2p_rtt_ms: int | None = None,
    ):
        super().__init__(max_p2p_rtt_ms=max_p2p_rtt_ms)
        self.max_server_rtt_ms = max_server_rtt_ms

    def _filter_by_server_rtt(
        self,
        arriving: MatchCandidate,
        waiting: list[MatchCandidate],
    ) -> list[MatchCandidate]:
        """Filter waiting candidates by estimated P2P RTT (sum of server RTTs)."""
        filtered = []
        for candidate in waiting:
            if arriving.rtt_ms is None or candidate.rtt_ms is None:
                logger.info(
                    f"[LatencyFIFOMatchmaker] Candidate {candidate.subject_id} "
                    f"has missing RTT data (arriving={arriving.rtt_ms}, "
                    f"candidate={candidate.rtt_ms}). Not excluded."
                )
                filtered.append(candidate)
            else:
                estimated_rtt = arriving.rtt_ms + candidate.rtt_ms
                if estimated_rtt <= self.max_server_rtt_ms:
                    logger.info(
                        f"[LatencyFIFOMatchmaker] Candidate {candidate.subject_id} "
                        f"passes RTT filter: {estimated_rtt}ms <= "
                        f"{self.max_server_rtt_ms}ms"
                    )
                    filtered.append(candidate)
                else:
                    logger.info(
                        f"[LatencyFIFOMatchmaker] Candidate {candidate.subject_id} "
                        f"SKIPPED: estimated RTT {estimated_rtt}ms > "
                        f"{self.max_server_rtt_ms}ms"
                    )
        return filtered

    def rank_candidates(
        self,
        arriving: MatchCandidate,
        waiting: list[MatchCandidate],
        group_size: int,
    ) -> list[MatchCandidate]:
        if len(waiting) + 1 < group_size:
            return []
        return self._filter_by_server_rtt(arriving, waiting)

    def find_match(
        self,
        arriving: MatchCandidate,
        waiting: list[MatchCandidate],
        group_size: int,
    ) -> list[MatchCandidate] | None:
        logger.info(
            f"[LatencyFIFOMatchmaker] find_match called: "
            f"arriving={arriving.subject_id} (rtt={arriving.rtt_ms}), "
            f"waiting={[(w.subject_id, w.rtt_ms) for w in waiting]}, "
            f"group_size={group_size}, "
            f"max_server_rtt_ms={self.max_server_rtt_ms}"
        )

        # Need enough participants to form a group
        if len(waiting) + 1 < group_size:
            logger.info(
                f"[LatencyFIFOMatchmaker] Not enough participants: "
                f"{len(waiting) + 1} < {group_size}. Returning None (wait)."
            )
            return None

        filtered = self._filter_by_server_rtt(arriving, waiting)

        # Check if enough candidates passed the filter
        if len(filtered) < group_size - 1:
            logger.info(
                f"[LatencyFIFOMatchmaker] Not enough candidates after RTT filter: "
                f"{len(filtered)} < {group_size - 1}. Returning None (wait)."
            )
            return None

        # FIFO order: take first (group_size - 1) from filtered list + arriving
        matched = filtered[: group_size - 1] + [arriving]
        logger.info(
            f"[LatencyFIFOMatchmaker] Match found! "
            f"Returning: {[m.subject_id for m in matched]}"
        )
        return matched


class GroupReunionMatchmaker(Matchmaker):
    """Re-pairs previous partners when possible, falls back to FIFO.

    When a participant arrives who was previously paired with someone
    (group_history is populated), this matchmaker checks if any of their
    previous partners are in the waiting list. If found, it reunites them.

    If no previous partners are waiting (or if the arriving participant
    has no group history), falls back to FIFO matching.

    This is the recommended matchmaker for multi-GymScene experiments
    where the same partners should play together across scenes.

    Example:
        from mug.server.matchmaker import GroupReunionMatchmaker

        scene_2 = (
            GymScene()
            .scene(scene_id="game_2")
            .matchmaking(matchmaker=GroupReunionMatchmaker())
        )

    Args:
        max_p2p_rtt_ms: Maximum allowed P2P RTT in ms. None disables filtering.
        fallback_to_fifo: If True (default), falls back to FIFO when no
            reunion is possible. If False, waits until previous partners arrive.
    """

    def __init__(
        self,
        max_p2p_rtt_ms: int | None = None,
        fallback_to_fifo: bool = True,
    ):
        super().__init__(max_p2p_rtt_ms=max_p2p_rtt_ms)
        self.fallback_to_fifo = fallback_to_fifo

    def rank_candidates(
        self,
        arriving: MatchCandidate,
        waiting: list[MatchCandidate],
        group_size: int,
    ) -> list[MatchCandidate]:
        if len(waiting) + 1 < group_size:
            return []
        # Previous partners first, then others in FIFO order
        partners = []
        others = []
        prev_ids = set()
        if arriving.group_history and arriving.group_history.previous_partners:
            prev_ids = set(arriving.group_history.previous_partners)
        # Also check reverse: waiting participants who want the arriving player
        reverse_ids = set()
        for w in waiting:
            if (
                w.group_history
                and w.group_history.previous_partners
                and arriving.subject_id in w.group_history.previous_partners
            ):
                reverse_ids.add(w.subject_id)
        for w in waiting:
            if w.subject_id in prev_ids or w.subject_id in reverse_ids:
                partners.append(w)
            else:
                others.append(w)
        if self.fallback_to_fifo:
            return partners + others
        return partners

    def find_match(
        self,
        arriving: MatchCandidate,
        waiting: list[MatchCandidate],
        group_size: int,
    ) -> list[MatchCandidate] | None:
        logger.info(
            f"[GroupReunionMatchmaker] find_match called: "
            f"arriving={arriving.subject_id}, "
            f"waiting={[w.subject_id for w in waiting]}, "
            f"group_size={group_size}, "
            f"has_group_history={arriving.group_history is not None}"
        )

        # Try reunion: check if arriving has previous partners in the waiting list
        if arriving.group_history and arriving.group_history.previous_partners:
            previous_partner_ids = set(arriving.group_history.previous_partners)
            reunited = [w for w in waiting if w.subject_id in previous_partner_ids]

            if len(reunited) + 1 >= group_size:
                matched = reunited[: group_size - 1] + [arriving]
                logger.info(
                    f"[GroupReunionMatchmaker] Reunion match! "
                    f"Returning: {[m.subject_id for m in matched]}"
                )
                return matched
            else:
                logger.info(
                    f"[GroupReunionMatchmaker] Previous partners "
                    f"{previous_partner_ids} not all in waiting list "
                    f"({[w.subject_id for w in reunited]} found). "
                    f"{'Falling back to FIFO.' if self.fallback_to_fifo else 'Waiting.'}"
                )

        # Also check: is arriving participant a previous partner of someone waiting?
        # This handles the case where the arriving participant has no group_history
        # but a waiting participant does (e.g., arriving has None because they're new,
        # but a waiting participant was previously paired with someone who dropped).
        for w in waiting:
            if (
                w.group_history
                and w.group_history.previous_partners
                and arriving.subject_id in w.group_history.previous_partners
            ):
                # The waiting participant wants to reunite with the arriving one
                if group_size == 2:
                    matched = [w, arriving]
                    logger.info(
                        f"[GroupReunionMatchmaker] Reverse reunion match! "
                        f"Waiting {w.subject_id} wanted {arriving.subject_id}. "
                        f"Returning: {[m.subject_id for m in matched]}"
                    )
                    return matched

        # Fallback to FIFO if enabled
        if self.fallback_to_fifo:
            if len(waiting) + 1 >= group_size:
                matched = waiting[: group_size - 1] + [arriving]
                logger.info(
                    f"[GroupReunionMatchmaker] FIFO fallback match. "
                    f"Returning: {[m.subject_id for m in matched]}"
                )
                return matched

        logger.info(
            f"[GroupReunionMatchmaker] No match possible. "
            f"Returning None (wait)."
        )
        return None
