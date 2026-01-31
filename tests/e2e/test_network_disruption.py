"""
Network disruption tests - validate rollback and fast-forward mechanisms.

These tests use CDP and JavaScript event injection to simulate network disruptions
and verify that the game correctly handles:
- NET-02: Packet loss triggering rollback scenarios
- NET-03: Tab unfocus/refocus exercising fast-forward path

The tests validate that episodes complete successfully under disruption,
and that rollback/fast-forward events are observable in game state.

Key behaviors tested:
1. Packet loss causes late/lost inputs, triggering GGPO rollbacks
2. Tab backgrounding causes frame deficit, triggering fast-forward on refocus
3. Both disruption types complete episode without data corruption
"""
import pytest
import time
from tests.fixtures.network_helpers import (
    apply_packet_loss,
    set_tab_visibility,
    wait_for_focus_manager_state,
    get_rollback_stats,
    get_fast_forward_state,
)
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
from tests.e2e.test_latency_injection import run_full_episode_flow


# =============================================================================
# NET-02: Packet Loss Test
# =============================================================================

@pytest.mark.timeout(300)  # 5 minutes max
def test_packet_loss_triggers_rollback(flask_server, player_contexts):
    """
    NET-02: Test that packet loss triggers rollback scenarios.

    Strategy:
    1. Apply packet loss to player 2 (15% loss, 50ms base latency)
    2. Let episode run (players idle)
    3. Verify rollbacks occurred due to late/lost packets
    4. Verify episode completes despite disruption

    Note: Uses 15% packet loss which is aggressive enough to trigger
    mispredictions but not so severe as to break the P2P connection.
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Apply packet loss to player 2 BEFORE navigation
    cdp2 = apply_packet_loss(page2, packet_loss_percent=15, latency_ms=50)

    try:
        # Run full episode flow (reuse from latency tests)
        final_state1, final_state2 = run_full_episode_flow(page1, page2, base_url)

        # Get rollback stats from both players
        stats1 = get_rollback_stats(page1)
        stats2 = get_rollback_stats(page2)

        # Verify at least one player experienced rollbacks
        # (packet loss causes late inputs which trigger misprediction correction)
        total_rollbacks = (stats1['rollbackCount'] or 0) + (stats2['rollbackCount'] or 0)

        # Log for debugging (useful when test passes but we want visibility)
        print(f"\n[Packet Loss 15%] Rollback statistics:")
        print(f"  Player 1: rollbacks={stats1['rollbackCount']}, maxFrames={stats1['maxRollbackFrames']}")
        print(f"  Player 2: rollbacks={stats2['rollbackCount']}, maxFrames={stats2['maxRollbackFrames']}")
        print(f"  Total rollbacks: {total_rollbacks}")

        assert total_rollbacks > 0, (
            f"Expected rollbacks due to packet loss, but got 0. "
            f"Player 1: {stats1}, Player 2: {stats2}"
        )

        # Verify episode completed despite rollbacks
        assert final_state1['numEpisodes'] >= 1, "Player 1 should complete episode"
        assert final_state2['numEpisodes'] >= 1, "Player 2 should complete episode"

        # Verify they stayed in same game
        assert final_state1['gameId'] == final_state2['gameId'], "Players should be in same game"

        print(f"  Episode completed: gameId={final_state1['gameId']}")

    finally:
        try:
            cdp2.detach()
        except Exception:
            pass


# =============================================================================
# NET-03: Tab Visibility Test
# =============================================================================

@pytest.mark.timeout(300)  # 5 minutes max
def test_tab_visibility_triggers_fast_forward(flask_server, player_contexts):
    """
    NET-03: Test that tab unfocus/refocus exercises fast-forward path.

    Strategy:
    1. Start game normally
    2. Let both players run for a few seconds
    3. Hide player 1's tab (simulated via JS)
    4. Wait 5 seconds while player 2 continues
    5. Show player 1's tab (should trigger fast-forward)
    6. Verify player 1 caught up (frame number jumped)
    7. Verify episode completes

    Note: Fast-forward processes buffered partner inputs and steps
    through frames rapidly without rendering to catch up.
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Navigate to game
    page1.goto(base_url)
    page2.goto(base_url)

    # Socket connect
    wait_for_socket_connected(page1, timeout=30000)
    wait_for_socket_connected(page2, timeout=30000)

    # Pass instructions
    click_advance_button(page1, timeout=60000)
    click_advance_button(page2, timeout=60000)

    # Complete tutorials
    complete_tutorial_and_advance(page1, timeout=120000)
    complete_tutorial_and_advance(page2, timeout=120000)

    # Start multiplayer
    click_start_button(page1, timeout=60000)
    click_start_button(page2, timeout=60000)

    # Wait for game to start
    wait_for_game_canvas(page1, timeout=120000)
    wait_for_game_canvas(page2, timeout=120000)
    wait_for_game_object(page1, timeout=60000)
    wait_for_game_object(page2, timeout=60000)

    # Let game run for 3 seconds (build up some frames)
    time.sleep(3)

    # Record player 1's frame number before hiding
    state_before = get_fast_forward_state(page1)
    frame_before_hide = state_before['frameNumber']
    print(f"\n[Tab Visibility] Before hide: frame={frame_before_hide}")

    # Hide player 1's tab
    set_tab_visibility(page1, visible=False)
    wait_for_focus_manager_state(page1, backgrounded=True, timeout=5000)

    print(f"  Player 1 backgrounded, waiting 5 seconds...")

    # Wait 5 seconds while player 2 continues (player 2 advances frames)
    time.sleep(5)

    # Record player 2's frame number (they advanced while player 1 was hidden)
    state_p2_during = get_fast_forward_state(page2)
    print(f"  Player 2 frame during hide: {state_p2_during['frameNumber']}")

    # Show player 1's tab (triggers fast-forward)
    set_tab_visibility(page1, visible=True)
    wait_for_focus_manager_state(page1, backgrounded=False, timeout=5000)

    # Wait for fast-forward to complete (frame number should catch up)
    # Give it up to 30 seconds since fast-forward has safety limits
    page1.wait_for_function(
        f"""() => {{
            const game = window.game;
            return game &&
                   !game._pendingFastForward &&
                   game.frameNumber > {frame_before_hide + 20};  // Should have advanced significantly
        }}""",
        timeout=30000
    )

    # Get final state
    state_after = get_fast_forward_state(page1)
    frame_after_show = state_after['frameNumber']

    print(f"  After show: frame={frame_after_show}")
    print(f"  Frame jump: {frame_after_show - frame_before_hide} frames")

    # Verify fast-forward occurred (frame number jumped significantly)
    frame_jump = frame_after_show - frame_before_hide
    assert frame_jump > 30, (
        f"Expected significant frame jump after fast-forward, "
        f"but only got {frame_jump} frames (before={frame_before_hide}, after={frame_after_show})"
    )

    # Now complete the episode
    wait_for_episode_complete(page1, episode_num=1, timeout=180000)
    wait_for_episode_complete(page2, episode_num=1, timeout=180000)

    # Get final game states
    final_state1 = get_game_state(page1)
    final_state2 = get_game_state(page2)

    # Verify completion
    assert final_state1['numEpisodes'] >= 1, "Player 1 should complete episode"
    assert final_state2['numEpisodes'] >= 1, "Player 2 should complete episode"
    assert final_state1['gameId'] == final_state2['gameId'], "Players should be in same game"

    print(f"  Episode completed: gameId={final_state1['gameId']}")
