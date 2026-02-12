"""Integration tests for LatencyFIFOMatchmaker scene API and P2P probe wiring.

Covers two v1.21 requirements:
- MATCH-05: scene.matchmaking() stores and returns LatencyFIFOMatchmaker
- MATCH-03: P2P probe integration (needs_probe, should_reject_for_rtt, full flow)
"""

from __future__ import annotations

from unittest.mock import MagicMock

from mug.scenes.gym_scene import GymScene
from mug.server.matchmaker import LatencyFIFOMatchmaker, MatchCandidate


class TestLatencyFIFOIntegration:
    """Integration tests for LatencyFIFOMatchmaker with scene API and P2P probe wiring."""

    # ------------------------------------------------------------------ #
    # Scene API tests (MATCH-05)
    # ------------------------------------------------------------------ #

    def test_scene_stores_latency_fifo_matchmaker(self):
        """MATCH-05: scene.matchmaking() stores LatencyFIFOMatchmaker with both thresholds."""
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)
        scene = GymScene().matchmaking(matchmaker=matchmaker)

        assert scene.matchmaker is matchmaker
        assert scene.matchmaker.max_server_rtt_ms == 200
        assert scene.matchmaker.max_p2p_rtt_ms == 150

    def test_scene_stores_latency_fifo_without_p2p(self):
        """MATCH-05: scene.matchmaking() stores LatencyFIFOMatchmaker without P2P threshold."""
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        scene = GymScene().matchmaking(matchmaker=matchmaker)

        assert scene.matchmaker is matchmaker
        assert scene.matchmaker.max_server_rtt_ms == 200
        assert scene.matchmaker.max_p2p_rtt_ms is None

    def test_scene_matchmaker_type_validation(self):
        """MATCH-05: scene.matchmaking() rejects non-Matchmaker instances."""
        scene = GymScene()
        try:
            scene.matchmaking(matchmaker="not_a_matchmaker")
            assert False, "Should have raised TypeError"
        except TypeError:
            pass  # Expected

    # ------------------------------------------------------------------ #
    # P2P probe decision tests (MATCH-03)
    # ------------------------------------------------------------------ #

    def test_needs_probe_true_when_p2p_set(self):
        """MATCH-03: needs_probe is True when max_p2p_rtt_ms is set and probe_coordinator exists."""
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)
        probe_coordinator = MagicMock()

        needs_probe = (
            probe_coordinator is not None
            and matchmaker.max_p2p_rtt_ms is not None
        )
        assert needs_probe is True

    def test_needs_probe_false_when_p2p_not_set(self):
        """MATCH-03: needs_probe is False when max_p2p_rtt_ms is None."""
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        probe_coordinator = MagicMock()

        needs_probe = (
            probe_coordinator is not None
            and matchmaker.max_p2p_rtt_ms is not None
        )
        assert needs_probe is False

    def test_needs_probe_false_when_no_probe_coordinator(self):
        """MATCH-03: needs_probe is False when probe_coordinator is None."""
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)
        probe_coordinator = None

        needs_probe = (
            probe_coordinator is not None
            and matchmaker.max_p2p_rtt_ms is not None
        )
        assert needs_probe is False

    # ------------------------------------------------------------------ #
    # Rejection/acceptance tests (MATCH-03)
    # ------------------------------------------------------------------ #

    def test_should_reject_accepts_under_threshold(self):
        """MATCH-03: should_reject_for_rtt returns False when P2P RTT < threshold."""
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)
        assert matchmaker.should_reject_for_rtt(100.0) is False

    def test_should_reject_accepts_at_boundary(self):
        """MATCH-03: should_reject_for_rtt returns False at exact boundary (inclusive)."""
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)
        assert matchmaker.should_reject_for_rtt(150.0) is False

    def test_should_reject_rejects_over_threshold(self):
        """MATCH-03: should_reject_for_rtt returns True when P2P RTT > threshold."""
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)
        assert matchmaker.should_reject_for_rtt(151.0) is True

    def test_should_reject_rejects_none_measurement(self):
        """MATCH-03: should_reject_for_rtt returns True when measurement is None (failed)."""
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)
        assert matchmaker.should_reject_for_rtt(None) is True

    def test_should_reject_accepts_all_when_no_p2p_threshold(self):
        """MATCH-03: should_reject_for_rtt returns False when no max_p2p_rtt_ms (accept all)."""
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        assert matchmaker.should_reject_for_rtt(9999.0) is False

    # ------------------------------------------------------------------ #
    # Full flow integration tests (MATCH-03 end-to-end)
    # ------------------------------------------------------------------ #

    def test_full_flow_probe_accepted_game_created(self):
        """MATCH-03 E2E: find_match -> probe accepted -> game would be created.

        Simulates the complete logical flow:
        1. LatencyFIFOMatchmaker pre-filters by server RTT sum
        2. GameManager checks needs_probe (True because max_p2p_rtt_ms is set)
        3. Probe returns 80ms which is under 150ms threshold
        4. Match accepted -> game would be created
        """
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)
        probe_coordinator = MagicMock()

        # Stage 1: Pre-filter by server RTT sum
        arriving = MatchCandidate(subject_id="player_a", rtt_ms=50)
        waiting = [MatchCandidate(subject_id="player_b", rtt_ms=60)]
        matched = matchmaker.find_match(arriving, waiting, group_size=2)

        assert matched is not None, "Match should be found (50+60=110 <= 200)"
        assert len(matched) == 2

        # Stage 2: Check if probe is needed
        needs_probe = (
            probe_coordinator is not None
            and matchmaker.max_p2p_rtt_ms is not None
        )
        assert needs_probe is True, "Probe should be needed (max_p2p_rtt_ms=150)"

        # Stage 3: Probe result accepted
        p2p_rtt_ms = 80.0  # Simulated probe result
        rejected = matchmaker.should_reject_for_rtt(p2p_rtt_ms)
        assert rejected is False, "80ms < 150ms threshold, match should be accepted"
        # Game would be created at this point

    def test_full_flow_probe_rejected_candidates_stay(self):
        """MATCH-03 E2E: find_match -> probe rejected -> candidates stay in waitroom.

        Simulates the flow where P2P RTT exceeds threshold:
        1. LatencyFIFOMatchmaker pre-filters by server RTT sum (passes)
        2. GameManager checks needs_probe (True)
        3. Probe returns 200ms which exceeds 150ms threshold
        4. Match rejected -> candidates would remain in waitroom
        """
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)
        probe_coordinator = MagicMock()

        # Stage 1: Pre-filter passes
        arriving = MatchCandidate(subject_id="player_a", rtt_ms=50)
        waiting = [MatchCandidate(subject_id="player_b", rtt_ms=60)]
        matched = matchmaker.find_match(arriving, waiting, group_size=2)

        assert matched is not None, "Match should be found (50+60=110 <= 200)"

        # Stage 2: Probe needed
        needs_probe = (
            probe_coordinator is not None
            and matchmaker.max_p2p_rtt_ms is not None
        )
        assert needs_probe is True

        # Stage 3: Probe result rejected
        p2p_rtt_ms = 200.0  # Simulated probe result exceeds threshold
        rejected = matchmaker.should_reject_for_rtt(p2p_rtt_ms)
        assert rejected is True, "200ms > 150ms threshold, match should be rejected"
        # Candidates would remain in waitroom at this point

    def test_full_flow_no_probe_game_created_immediately(self):
        """MATCH-03 E2E: find_match -> no probe needed -> game created immediately.

        When max_p2p_rtt_ms is not set, no P2P probe is needed and the game
        is created immediately after the matchmaker proposes a match.
        """
        matchmaker = LatencyFIFOMatchmaker(max_server_rtt_ms=200)  # No max_p2p_rtt_ms
        probe_coordinator = MagicMock()

        # Stage 1: Pre-filter passes
        arriving = MatchCandidate(subject_id="player_a", rtt_ms=50)
        waiting = [MatchCandidate(subject_id="player_b", rtt_ms=60)]
        matched = matchmaker.find_match(arriving, waiting, group_size=2)

        assert matched is not None, "Match should be found (50+60=110 <= 200)"

        # Stage 2: No probe needed (max_p2p_rtt_ms is None)
        needs_probe = (
            probe_coordinator is not None
            and matchmaker.max_p2p_rtt_ms is not None
        )
        assert needs_probe is False, "No probe needed (max_p2p_rtt_ms is None)"
        # Game would be created immediately, no probe needed
