"""
Multi-participant stress tests.

These tests validate infrastructure and scenarios requiring 6 concurrent
participants (3 simultaneous games). Builds on test infrastructure from
Phase 64 (STRESS-01) to enable lifecycle stress tests in Phase 65.

Tests:
- test_three_simultaneous_games: STRESS-01 infrastructure validation
- test_staggered_participant_arrival: Validates FIFO pairing under realistic timing

Requires headed mode for WebRTC:
    pytest tests/e2e/test_multi_participant.py --headed

Or set PWHEADED=1 environment variable.
"""
import pytest
import time

from tests.fixtures.multi_participant import GameOrchestrator
from tests.fixtures.game_helpers import (
    wait_for_socket_connected,
    click_advance_button,
    click_start_button,
    wait_for_game_canvas,
    get_game_state,
)
from tests.fixtures.network_helpers import set_tab_visibility


# =============================================================================
# STRESS-01: Multi-Participant Infrastructure Validation
# =============================================================================

@pytest.mark.timeout(600)  # 10 minutes for 3 concurrent games
def test_three_simultaneous_games(multi_participant_contexts, flask_server):
    """
    STRESS-01: Test infrastructure supports 6 concurrent participants.

    Validates:
    1. 6 browser contexts can be created from single browser
    2. Server handles 3 concurrent game sessions
    3. All intended pairs match correctly via FIFO matchmaker
    4. All games complete successfully
    5. Data parity verified for all games

    Episode completion is confirmed via data export parity validation,
    which verifies both players processed identical game state.
    """
    pages = multi_participant_contexts  # Tuple of 6 pages
    base_url = flask_server["url"]

    # Create orchestrator
    orchestrator = GameOrchestrator(pages, base_url)

    # Start all 3 games with increased stagger for WebRTC stability
    orchestrator.start_all_games(stagger_delay_sec=7.0)

    # Wait for all episodes to complete WITH parity validation
    # This is the definitive test: both players must export identical data
    results = orchestrator.wait_for_all_episodes_with_parity(
        episode_num=1,
        episode_timeout=300000,
        export_timeout_sec=60,
    )

    # Assert all games passed with verified parity
    for game_idx, status in results.items():
        assert status["success"], (
            f"Game {game_idx} failed: {status['message']}"
        )
        assert status["parity_verified"], (
            f"Game {game_idx} parity not verified: {status['message']}"
        )

    print(f"\n[STRESS-01] All 3 games completed with verified data parity")


@pytest.mark.timeout(600)  # 10 minutes
def test_staggered_participant_arrival(multi_participant_contexts, flask_server):
    """
    Test that infrastructure handles staggered participant arrival correctly.

    Simulates realistic scenario where participants arrive at different times:
    - Game 1 players arrive first
    - Delay between game pairs
    - Game 2 players arrive
    - Delay between game pairs
    - Game 3 players arrive

    Validates that FIFO matchmaker correctly pairs intended partners
    and all games complete with verified data parity.
    """
    pages = multi_participant_contexts
    base_url = flask_server["url"]

    # Create orchestrator and use per-pair orchestration with increased stagger
    orchestrator = GameOrchestrator(pages, base_url)

    # Start all games with staggered timing (7s between pairs for WebRTC stability)
    orchestrator.start_all_games(stagger_delay_sec=7.0)

    # Wait for all episodes to complete WITH parity validation
    # This confirms correct pairing AND correct game state synchronization
    results = orchestrator.wait_for_all_episodes_with_parity(
        episode_num=1,
        episode_timeout=300000,
        export_timeout_sec=60,
    )

    # Assert all games paired correctly and completed with parity
    for game_idx, status in results.items():
        assert status["success"], (
            f"Game {game_idx} failed: {status['message']}"
        )
        assert status["parity_verified"], (
            f"Game {game_idx} parity not verified: {status['message']}"
        )
        print(f"Game {game_idx}: Verified correct pairing and data parity")

    print(f"\n[Staggered Arrival] All 3 games paired and completed with verified data parity")
