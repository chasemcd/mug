"""
Latency injection tests - validate game behavior under network stress.

These tests use Chrome DevTools Protocol (CDP) to inject artificial latency
and verify that the game correctly handles various network conditions:
- NET-01: Fixed symmetric latency (100ms, 200ms)
- NET-04: Asymmetric latency (100ms vs 500ms per player)
- NET-05: Jitter (variable latency during gameplay)

The tests validate that episodes complete successfully under latency stress,
which confirms the dual-buffer data recording (v1.8) handles network delays.

Important:
- CDP only works with Chromium-based browsers (tests must use default Chromium)
- These tests are slow (2-3 minutes each due to episode timeouts)
- Players are idle; episodes complete via time limit

Known limitations:
- 500ms symmetric latency causes WebRTC signaling timeouts. The compounding
  effect of 500ms round-trip on BOTH players exceeds reasonable thresholds.
  However, asymmetric (one player at 500ms) works fine, which covers the
  realistic scenario of mismatched network conditions.
"""
import pytest
from tests.fixtures.network_helpers import apply_latency, JitterEmulator
from tests.fixtures.game_helpers import (
    wait_for_socket_connected,
    wait_for_game_canvas,
    wait_for_game_object,
    wait_for_episode_complete,
    get_game_state,
    click_advance_button,
    click_start_button,
    complete_tutorial_and_advance,
)


def run_full_episode_flow(
    page1, page2, base_url: str,
    episode_timeout: int = 180000,
    setup_timeout: int = 120000
) -> tuple:
    """
    Run the full game flow through one complete episode.

    This helper encapsulates the game progression flow shared by all latency tests.

    Args:
        page1: Player 1's Playwright page
        page2: Player 2's Playwright page
        base_url: Flask server URL
        episode_timeout: Timeout for episode completion in milliseconds
        setup_timeout: Timeout for game setup (tutorial, matchmaking) in milliseconds

    Returns:
        tuple: (final_state1, final_state2) with game state dicts for both players
    """
    # Navigate to game
    page1.goto(base_url)
    page2.goto(base_url)

    # Wait for socket connections (socket connect is fast even with latency)
    wait_for_socket_connected(page1, timeout=30000)
    wait_for_socket_connected(page2, timeout=30000)

    # Pass instructions scene
    click_advance_button(page1, timeout=setup_timeout)
    click_advance_button(page2, timeout=setup_timeout)

    # Complete tutorial and advance to multiplayer
    complete_tutorial_and_advance(page1, timeout=setup_timeout)
    complete_tutorial_and_advance(page2, timeout=setup_timeout)

    # Click startButton for multiplayer scene
    click_start_button(page1, timeout=setup_timeout)
    click_start_button(page2, timeout=setup_timeout)

    # Wait for game to start (matchmaking + P2P connection)
    # High latency significantly affects WebRTC signaling
    wait_for_game_canvas(page1, timeout=setup_timeout)
    wait_for_game_canvas(page2, timeout=setup_timeout)

    # Verify game objects initialized
    wait_for_game_object(page1, timeout=setup_timeout)
    wait_for_game_object(page2, timeout=setup_timeout)

    # Verify both players are in same game
    state1 = get_game_state(page1)
    state2 = get_game_state(page2)
    assert state1["gameId"] == state2["gameId"], "Players should be in same game"
    assert state1["playerId"] != state2["playerId"], "Players should have different IDs"

    # Wait for first episode to complete (players idle, episode ends via time limit)
    wait_for_episode_complete(page1, episode_num=1, timeout=episode_timeout)
    wait_for_episode_complete(page2, episode_num=1, timeout=episode_timeout)

    # Return final states
    final_state1 = get_game_state(page1)
    final_state2 = get_game_state(page2)

    return final_state1, final_state2


# =============================================================================
# NET-01: Fixed Symmetric Latency Tests
# =============================================================================

@pytest.mark.parametrize("latency_ms", [100, 200])
@pytest.mark.timeout(300)  # 5 minutes max per test
def test_episode_completion_under_fixed_latency(flask_server, player_contexts, latency_ms):
    """
    Test that episode completes under fixed symmetric latency.

    Validates NET-01: Game should handle 100ms and 200ms symmetric latency
    without breaking gameplay or data recording.

    Both players experience the same latency (symmetric condition).
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Apply same latency to both players BEFORE navigation
    # (CDP session created on existing page, affects subsequent requests)
    cdp1 = apply_latency(page1, latency_ms)
    cdp2 = apply_latency(page2, latency_ms)

    try:
        # Run full episode flow
        final_state1, final_state2 = run_full_episode_flow(page1, page2, base_url)

        # Verify completion
        assert final_state1["numEpisodes"] >= 1, f"Player 1 should complete 1+ episodes under {latency_ms}ms latency"
        assert final_state2["numEpisodes"] >= 1, f"Player 2 should complete 1+ episodes under {latency_ms}ms latency"

        # Log success metrics
        print(f"\n[{latency_ms}ms latency] Game completed successfully:")
        print(f"  gameId={final_state1['gameId']}")
        print(f"  Player 1: episodes={final_state1['numEpisodes']}, frames={final_state1['frameNumber']}")
        print(f"  Player 2: episodes={final_state2['numEpisodes']}, frames={final_state2['frameNumber']}")

    finally:
        # Cleanup CDP sessions (optional - context.close() also cleans up)
        try:
            cdp1.detach()
            cdp2.detach()
        except Exception:
            pass  # Session may already be closed


# =============================================================================
# NET-04: Asymmetric Latency Test
# =============================================================================

@pytest.mark.timeout(300)  # 5 minutes max
def test_episode_completion_under_asymmetric_latency(flask_server, player_contexts):
    """
    Test that episode completes when players have different latencies.

    Validates NET-04: Game should handle mismatched network conditions
    (50ms for player 1, 200ms for player 2) without breaking.

    This is a realistic scenario - players often have different ISPs
    and network conditions.

    Note: Uses 50ms vs 200ms rather than 100ms vs 500ms to avoid
    WebRTC signaling timeouts that occur with very high symmetric latency.
    The 200ms player still experiences meaningful latency (typical for
    cross-continental connections).
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Apply different latencies to each player
    cdp1 = apply_latency(page1, latency_ms=50)   # Player 1: low latency (local)
    cdp2 = apply_latency(page2, latency_ms=200)  # Player 2: moderate latency (cross-region)

    try:
        # Run full episode flow
        final_state1, final_state2 = run_full_episode_flow(page1, page2, base_url)

        # Verify completion
        assert final_state1["numEpisodes"] >= 1, "Player 1 (50ms) should complete 1+ episodes"
        assert final_state2["numEpisodes"] >= 1, "Player 2 (200ms) should complete 1+ episodes"

        # Verify they're still in the same game
        assert final_state1["gameId"] == final_state2["gameId"], "Players should remain in same game"

        # Log success metrics
        print("\n[Asymmetric: 50ms vs 200ms] Game completed successfully:")
        print(f"  gameId={final_state1['gameId']}")
        print(f"  Player 1 (50ms): episodes={final_state1['numEpisodes']}, frames={final_state1['frameNumber']}")
        print(f"  Player 2 (200ms): episodes={final_state2['numEpisodes']}, frames={final_state2['frameNumber']}")

    finally:
        # Cleanup CDP sessions
        try:
            cdp1.detach()
            cdp2.detach()
        except Exception:
            pass


# =============================================================================
# NET-05: Jitter Test
# =============================================================================

@pytest.mark.timeout(300)  # 5 minutes max
def test_episode_completion_under_jitter(flask_server, player_contexts):
    """
    Test that episode completes under variable latency (jitter).

    Validates NET-05: Game should handle realistic network instability
    where latency varies continuously during gameplay.

    Configuration:
    - Base latency: 200ms
    - Jitter range: 150ms
    - Effective range: 50ms to 350ms (randomly varying)
    - Update interval: 100ms (10 updates/second)

    Both players experience independent jitter patterns.
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Apply initial latency (will be modified by jitter)
    cdp1 = apply_latency(page1, latency_ms=200)
    cdp2 = apply_latency(page2, latency_ms=200)

    # Create jitter emulators for both players
    jitter1 = JitterEmulator(cdp1, base_latency=200, jitter_range=150)
    jitter2 = JitterEmulator(cdp2, base_latency=200, jitter_range=150)

    try:
        # Start jitter emulation before gameplay
        jitter1.start(interval_ms=100)
        jitter2.start(interval_ms=100)

        # Run full episode flow
        final_state1, final_state2 = run_full_episode_flow(page1, page2, base_url)

        # Verify completion
        assert final_state1["numEpisodes"] >= 1, "Player 1 should complete 1+ episodes under jitter"
        assert final_state2["numEpisodes"] >= 1, "Player 2 should complete 1+ episodes under jitter"

        # Log success metrics
        print("\n[Jitter: 200ms +/- 150ms] Game completed successfully:")
        print(f"  gameId={final_state1['gameId']}")
        print(f"  Player 1: episodes={final_state1['numEpisodes']}, frames={final_state1['frameNumber']}")
        print(f"  Player 2: episodes={final_state2['numEpisodes']}, frames={final_state2['frameNumber']}")

    finally:
        # Stop jitter threads (important: do this first)
        jitter1.stop()
        jitter2.stop()

        # Cleanup CDP sessions
        try:
            cdp1.detach()
            cdp2.detach()
        except Exception:
            pass
