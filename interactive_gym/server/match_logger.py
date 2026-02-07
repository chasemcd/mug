"""Match assignment logging for research data collection.

This module provides logging infrastructure to record match decisions
(who matched with whom, RTT values, timestamps) for post-experiment analysis.

Completes DATA-01 (assignment logging) and supports DATA-02 (RTT exposure).
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from interactive_gym.server.matchmaker import MatchCandidate
    from interactive_gym.server.admin.aggregator import AdminEventAggregator

logger = logging.getLogger(__name__)


@dataclass
class MatchAssignment:
    """Immutable record of a match decision.

    Attributes:
        timestamp: Unix timestamp when match formed
        scene_id: Scene where match occurred
        game_id: Unique game identifier
        participants: List of dicts with subject_id and rtt_ms for each participant
        matchmaker_class: Name of matchmaker that formed the match
    """

    timestamp: float
    scene_id: str
    game_id: str
    participants: list[dict] = field(default_factory=list)
    matchmaker_class: str = "Unknown"


class MatchAssignmentLogger:
    """Logger for match assignment events.

    Writes match events to:
    1. JSONL files in data/match_logs/{scene_id}_matches.jsonl
    2. Admin dashboard activity timeline (via AdminEventAggregator)

    Thread-safe: File writes are synchronous but fast at match rate.
    """

    MATCH_LOGS_DIR = "data/match_logs"

    def __init__(self, admin_aggregator: AdminEventAggregator | None = None):
        """Initialize the match logger.

        Args:
            admin_aggregator: Optional AdminEventAggregator for dashboard updates
        """
        self.admin_aggregator = admin_aggregator

        # Create logs directory
        os.makedirs(self.MATCH_LOGS_DIR, exist_ok=True)
        logger.info(f"Match logs will be saved to {self.MATCH_LOGS_DIR}/")

    def log_match(
        self,
        scene_id: str,
        game_id: str,
        matched_candidates: list[MatchCandidate],
        matchmaker_class: str,
    ) -> None:
        """Log a match assignment event.

        Args:
            scene_id: The scene ID where match occurred
            game_id: The unique game identifier
            matched_candidates: List of MatchCandidate objects that were matched
            matchmaker_class: Name of the matchmaker class that formed this match
        """
        # Build participants list from MatchCandidate objects
        participants = [
            {
                "subject_id": candidate.subject_id,
                "rtt_ms": candidate.rtt_ms,
            }
            for candidate in matched_candidates
        ]

        # Create assignment record
        assignment = MatchAssignment(
            timestamp=time.time(),
            scene_id=scene_id,
            game_id=game_id,
            participants=participants,
            matchmaker_class=matchmaker_class,
        )

        # Log to admin dashboard if aggregator available
        if self.admin_aggregator:
            subject_ids = [p["subject_id"] for p in participants]
            rtt_values = [p["rtt_ms"] for p in participants]
            self.admin_aggregator.log_activity(
                event_type="match_formed",
                subject_id=subject_ids[0] if subject_ids else "unknown",
                details={
                    "game_id": game_id,
                    "participants": subject_ids,
                    "rtt_values": rtt_values,
                    "matchmaker": matchmaker_class,
                },
            )

        # Write to file
        self._write_to_file(scene_id, assignment)

        logger.info(
            f"Match logged: game={game_id}, participants={[p['subject_id'] for p in participants]}, "
            f"matchmaker={matchmaker_class}"
        )

    def _write_to_file(self, scene_id: str, assignment: MatchAssignment) -> None:
        """Write assignment record to JSONL file.

        Args:
            scene_id: The scene ID (used for filename)
            assignment: The MatchAssignment to persist
        """
        filepath = os.path.join(self.MATCH_LOGS_DIR, f"{scene_id}_matches.jsonl")

        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(assignment)) + "\n")
        except Exception as e:
            logger.error(f"Failed to write match log to {filepath}: {e}")
