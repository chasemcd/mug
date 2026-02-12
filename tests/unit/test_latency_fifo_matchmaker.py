"""Unit tests for LatencyFIFOMatchmaker.

Covers all four success criteria from the v1.21 roadmap:
1. Configurable max_server_rtt_ms threshold
2. find_match() skips candidates where sum of server RTTs > threshold
3. find_match() returns None when no candidate passes RTT filter
4. find_match() does NOT exclude candidates with rtt_ms=None (graceful fallback)
"""

from interactive_gym.server.matchmaker import LatencyFIFOMatchmaker, MatchCandidate


class TestLatencyFIFOMatchmaker:
    """Tests for LatencyFIFOMatchmaker."""

    def test_instantiation_with_threshold(self):
        """MATCH-01/MATCH-02: threshold is stored correctly."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        assert m.max_server_rtt_ms == 200
        assert m.max_p2p_rtt_ms is None

        m2 = LatencyFIFOMatchmaker(max_server_rtt_ms=200, max_p2p_rtt_ms=150)
        assert m2.max_server_rtt_ms == 200
        assert m2.max_p2p_rtt_ms == 150

    def test_basic_match_within_threshold(self):
        """Success Criteria 1+2: match when sum of RTTs <= threshold."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=50)
        waiting = [MatchCandidate(subject_id="b", rtt_ms=80)]
        result = m.find_match(arriving, waiting, group_size=2)
        assert result is not None
        ids = [c.subject_id for c in result]
        assert "a" in ids
        assert "b" in ids
        assert len(result) == 2

    def test_skip_candidate_exceeding_threshold(self):
        """Success Criteria 2: skip when sum of RTTs > threshold."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=120)
        waiting = [MatchCandidate(subject_id="b", rtt_ms=150)]
        result = m.find_match(arriving, waiting, group_size=2)
        # 120+150=270 > 200, no match
        assert result is None

    def test_skip_high_rtt_pick_lower(self):
        """Success Criteria 2: skip high-RTT candidate, pick lower one."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=50)
        cand_a = MatchCandidate(subject_id="cand_a", rtt_ms=180)
        cand_b = MatchCandidate(subject_id="cand_b", rtt_ms=60)
        waiting = [cand_a, cand_b]
        result = m.find_match(arriving, waiting, group_size=2)
        # cand_a filtered (50+180=230 > 200), cand_b passes (50+60=110 <= 200)
        assert result is not None
        ids = [c.subject_id for c in result]
        assert "cand_b" in ids
        assert "a" in ids
        assert "cand_a" not in ids

    def test_no_candidate_passes_filter_returns_none(self):
        """Success Criteria 3: returns None when all candidates filtered out."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=150)
        waiting = [MatchCandidate(subject_id="b", rtt_ms=200)]
        result = m.find_match(arriving, waiting, group_size=2)
        # 150+200=350 > 200
        assert result is None

    def test_not_enough_participants(self):
        """Basic FIFO behavior: not enough participants returns None."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=50)
        result = m.find_match(arriving, [], group_size=2)
        assert result is None

    def test_none_rtt_arriving_not_excluded(self):
        """Success Criteria 4: arriving with None RTT does not exclude candidate."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=None)
        waiting = [MatchCandidate(subject_id="b", rtt_ms=100)]
        result = m.find_match(arriving, waiting, group_size=2)
        assert result is not None
        ids = [c.subject_id for c in result]
        assert "a" in ids
        assert "b" in ids

    def test_none_rtt_candidate_not_excluded(self):
        """Success Criteria 4: candidate with None RTT is not excluded."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=100)
        waiting = [MatchCandidate(subject_id="b", rtt_ms=None)]
        result = m.find_match(arriving, waiting, group_size=2)
        assert result is not None
        ids = [c.subject_id for c in result]
        assert "a" in ids
        assert "b" in ids

    def test_both_rtt_none_not_excluded(self):
        """Success Criteria 4: both participants with None RTT still match."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=None)
        waiting = [MatchCandidate(subject_id="b", rtt_ms=None)]
        result = m.find_match(arriving, waiting, group_size=2)
        assert result is not None
        ids = [c.subject_id for c in result]
        assert "a" in ids
        assert "b" in ids

    def test_match_returns_group_size_candidates(self):
        """Structural correctness: result has exactly group_size candidates."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=30)
        cand_a = MatchCandidate(subject_id="cand_a", rtt_ms=40)
        cand_b = MatchCandidate(subject_id="cand_b", rtt_ms=50)
        waiting = [cand_a, cand_b]
        result = m.find_match(arriving, waiting, group_size=2)
        # Both pass filter, but group_size=2 means only 1 from waiting + arriving
        assert result is not None
        assert len(result) == 2

    def test_fifo_order_preserved(self):
        """FIFO semantics: first candidate in waiting list is picked first."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=50)
        cand_a = MatchCandidate(subject_id="cand_a", rtt_ms=60)
        cand_b = MatchCandidate(subject_id="cand_b", rtt_ms=70)
        cand_c = MatchCandidate(subject_id="cand_c", rtt_ms=40)
        waiting = [cand_a, cand_b, cand_c]
        result = m.find_match(arriving, waiting, group_size=2)
        # All pass filter, FIFO picks cand_a (first in waiting list)
        assert result is not None
        ids = [c.subject_id for c in result]
        assert ids == ["cand_a", "a"]

    def test_threshold_boundary_exact_match(self):
        """Edge case: sum of RTTs exactly equals threshold passes filter."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=100)
        waiting = [MatchCandidate(subject_id="b", rtt_ms=100)]
        result = m.find_match(arriving, waiting, group_size=2)
        # 100+100=200 <= 200 (exactly at boundary)
        assert result is not None
        ids = [c.subject_id for c in result]
        assert "a" in ids
        assert "b" in ids

    def test_group_size_three(self):
        """Supports larger groups: group_size=3 matches three participants."""
        m = LatencyFIFOMatchmaker(max_server_rtt_ms=200)
        arriving = MatchCandidate(subject_id="a", rtt_ms=30)
        cand_a = MatchCandidate(subject_id="cand_a", rtt_ms=40)
        cand_b = MatchCandidate(subject_id="cand_b", rtt_ms=50)
        waiting = [cand_a, cand_b]
        result = m.find_match(arriving, waiting, group_size=3)
        assert result is not None
        assert len(result) == 3
        ids = [c.subject_id for c in result]
        assert "a" in ids
        assert "cand_a" in ids
        assert "cand_b" in ids
