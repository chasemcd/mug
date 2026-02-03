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

Known flaky tests (documented bugs, not test issues):
- test_active_input_with_packet_loss: Intermittently fails with data parity
  divergences. Root cause: under packet loss + active inputs, rollback replay
  may use predicted actions if confirmed inputs haven't arrived yet. Both players
  record what they executed, which may differ. This is a real bug in
  _promoteRemainingAtBoundary() which force-promotes unconfirmed speculative
  data at episode end. Tracked for future fix.
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
    get_scene_id,
    run_full_episode_flow_until_gameplay,
)
from tests.fixtures.input_helpers import (
    start_random_actions,
    stop_random_actions,
)
from tests.fixtures.export_helpers import (
    get_experiment_id,
    get_subject_ids_from_pages,
    wait_for_export_files,
    run_comparison,
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
    2. Inject random inputs to create misprediction opportunities
    3. Verify rollbacks occurred due to late/lost packets
    4. Verify episode completes despite disruption

    Note: Uses 15% packet loss which is aggressive enough to trigger
    mispredictions but not so severe as to break the P2P connection.
    Active inputs are required because idle players (Noop) won't trigger
    rollbacks - the predicted action matches the actual action.
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Apply packet loss to player 2 BEFORE navigation
    cdp2 = apply_packet_loss(page2, packet_loss_percent=15, latency_ms=50)

    try:
        # Run through to gameplay (not full episode, we'll inject inputs first)
        run_full_episode_flow_until_gameplay(page1, page2, base_url)

        # Verify both players are in same game
        state1 = get_game_state(page1)
        state2 = get_game_state(page2)
        assert state1["gameId"] == state2["gameId"], "Players should be in same game"

        # Start random action injection to create misprediction opportunities
        # Without inputs, rollbacks won't occur (predicted Noop == actual Noop)
        interval1 = start_random_actions(page1, interval_ms=150)
        interval2 = start_random_actions(page2, interval_ms=200)

        try:
            # Wait for episode completion
            wait_for_episode_complete(page1, episode_num=1, timeout=180000)
            wait_for_episode_complete(page2, episode_num=1, timeout=180000)
        finally:
            stop_random_actions(page1, interval1)
            stop_random_actions(page2, interval2)

        # Get final states
        final_state1 = get_game_state(page1)
        final_state2 = get_game_state(page2)

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

    # Start multiplayer (tutorial scene removed in commit 607b60a)
    click_start_button(page1, timeout=60000)
    click_start_button(page2, timeout=60000)

    # Wait for game to start
    wait_for_game_canvas(page1, timeout=120000)
    wait_for_game_canvas(page2, timeout=120000)
    wait_for_game_object(page1, timeout=60000)
    wait_for_game_object(page2, timeout=60000)

    # Override visibility for Playwright automation (essential for frames to advance)
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)

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


# =============================================================================
# Active Input + Packet Loss Test (INPUT-05)
# =============================================================================

@pytest.mark.timeout(300)  # 5 minutes max
def test_active_input_with_packet_loss(flask_server, player_contexts):
    """
    Test data parity when both players actively input actions under packet loss.

    This is the most stress-testing scenario because:
    1. Packet loss causes rollbacks which re-predict actions
    2. With active inputs (not just Noop), rollback correction must handle
       real action values being overwritten and restored
    3. Both players are injecting different actions at different times

    Validates dual-buffer fixes from Phases 48-49:
    - Phase 48: isFocused column consistency (getFocusStatePerPlayer)
    - Phase 49: Episode boundary row parity (BOUND-02/03 guards)

    This validates that:
    - Rollback correctly restores actual action values
    - The dual-buffer data recording handles misprediction correction
    - Export parity is maintained despite frequent rollbacks

    Configuration:
    - Player 1: random actions every 150ms, no packet loss
    - Player 2: random actions every 200ms, 15% packet loss + 50ms latency
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Apply packet loss to player 2 BEFORE navigation
    cdp2 = apply_packet_loss(page2, packet_loss_percent=15, latency_ms=50)

    try:
        # Run through to gameplay
        run_full_episode_flow_until_gameplay(page1, page2, base_url)

        # Verify both players are in same game
        state1 = get_game_state(page1)
        state2 = get_game_state(page2)
        assert state1["gameId"] == state2["gameId"], "Players should be in same game"
        assert state1["playerId"] != state2["playerId"], "Players should have different IDs"

        # Start random action injection on both players
        interval1 = start_random_actions(page1, interval_ms=150)
        interval2 = start_random_actions(page2, interval_ms=200)

        print(f"\n[Active Input + 15% Packet Loss] Started random actions")

        try:
            # Wait for episode completion
            wait_for_episode_complete(page1, episode_num=1, timeout=180000)
            wait_for_episode_complete(page2, episode_num=1, timeout=180000)
        finally:
            stop_random_actions(page1, interval1)
            stop_random_actions(page2, interval2)

        # Verify rollbacks occurred (packet loss causes mispredictions)
        stats1 = get_rollback_stats(page1)
        stats2 = get_rollback_stats(page2)
        total_rollbacks = (stats1['rollbackCount'] or 0) + (stats2['rollbackCount'] or 0)

        print(f"  Rollback statistics:")
        print(f"    Player 1: rollbacks={stats1['rollbackCount']}, maxFrames={stats1['maxRollbackFrames']}")
        print(f"    Player 2: rollbacks={stats2['rollbackCount']}, maxFrames={stats2['maxRollbackFrames']}")
        print(f"    Total rollbacks: {total_rollbacks}")

        # Note: Rollbacks may not always occur with 15% packet loss - timing dependent.
        # The data parity check below is the primary validation.
        if total_rollbacks == 0:
            print("  WARNING: No rollbacks occurred despite packet loss (timing dependent)")
            print("  Proceeding with data parity check as primary validation")

        # Note: Action stats verification after episode completion is unreliable
        # because frameDataBuffer is cleared after export. The export comparison
        # below verifies that actions were correctly recorded despite packet loss.

        # Get final states
        final_state1 = get_game_state(page1)
        final_state2 = get_game_state(page2)

        # Verify completion
        assert final_state1["numEpisodes"] >= 1, "Player 1 should complete 1+ episodes"
        assert final_state2["numEpisodes"] >= 1, "Player 2 should complete 1+ episodes"

        # Extract identifiers for export files
        experiment_id = get_experiment_id()
        scene_id = get_scene_id(page1)
        assert scene_id, "Could not get scene ID from game"

        subject_ids = get_subject_ids_from_pages(page1, page2)

        # Wait for export files
        # Note: episode_num is 0-indexed in file names, so first episode is _ep0.csv
        try:
            file1, file2 = wait_for_export_files(
                experiment_id=experiment_id,
                scene_id=scene_id,
                subject_ids=subject_ids,
                episode_num=0,  # 0-indexed: first episode
                timeout_sec=30
            )
        except TimeoutError as e:
            pytest.fail(f"Export files not found: {e}")

        # Run comparison
        exit_code, output = run_comparison(file1, file2, verbose=True)

        print(f"\nComparison output:\n{output}")

        # Assert parity
        if exit_code != 0:
            pytest.fail(
                f"Data parity check failed with active inputs + packet loss "
                f"(exit code {exit_code}):\n{output}"
            )

        print(f"\n[Active Input + Packet Loss] Data parity verified despite {total_rollbacks} rollbacks")
        print(f"  Episodes completed: gameId={final_state1['gameId']}")

    finally:
        try:
            cdp2.detach()
        except Exception:
            pass
