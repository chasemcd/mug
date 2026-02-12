"""
Data comparison tests - validate export parity between two players.

These tests validate that both players export identical game state data,
proving that v1.8 data export parity works in practice under controlled
test conditions.

The tests:
1. Run a full episode flow (matchmaking, gameplay, completion)
2. Collect export files from both players after episode ends
3. Invoke validate_action_sequences.py --compare on the exports
4. Assert parity (exit code 0 = identical files)

Data flow:
- Server writes exports to: data/{experiment_id}/{scene_id}/{subject_id}_ep{N}.csv
- The validate_action_sequences.py --compare script compares column-by-column
- Identical files = exit code 0; divergences = exit code 1 with details

Important:
- Tests depend on episode completion (which has known timeout issues in E2E)
- When episode completion works, these tests validate data parity end-to-end
"""
from __future__ import annotations

import os
import shutil
import time

import pytest

from tests.fixtures.export_helpers import (get_experiment_id,
                                           get_subject_ids_from_pages,
                                           run_comparison,
                                           wait_for_export_files)
from tests.fixtures.game_helpers import (click_advance_button,
                                         click_start_button, get_game_state,
                                         get_scene_id, run_full_episode_flow,
                                         run_full_episode_flow_until_gameplay,
                                         wait_for_episode_complete,
                                         wait_for_game_canvas,
                                         wait_for_game_object,
                                         wait_for_socket_connected)
from tests.fixtures.input_helpers import (start_random_actions,
                                          stop_random_actions)
from tests.fixtures.network_helpers import (apply_latency, set_tab_visibility,
                                            wait_for_focus_manager_state)


@pytest.fixture
def clean_data_dir():
    """
    Clean the data directory before each test to avoid stale export files.

    Yields the data directory path for tests to use if needed.
    Cleans up after test as well.
    """
    experiment_id = get_experiment_id()
    # Scene ID varies - we clean all scene subdirs for this experiment
    data_dir = f"data/{experiment_id}"

    # Clean before test
    if os.path.exists(data_dir):
        shutil.rmtree(data_dir)
    os.makedirs(data_dir, exist_ok=True)

    yield data_dir

    # Optional: clean after test (commented out to allow inspection on failure)
    # if os.path.exists(data_dir):
    #     shutil.rmtree(data_dir)


@pytest.mark.timeout(300)  # 5 minutes max for full flow
def test_export_parity_basic(flask_server, player_contexts, clean_data_dir):
    """
    Test that export files from both players are identical after basic episode.

    Validates DATA-01: Both players should export identical game state data
    when playing under normal conditions (no network stress).

    Flow:
    1. Run full episode (matchmaking, gameplay, completion)
    2. Extract subject IDs from game objects
    3. Wait for export files to appear on disk
    4. Run comparison script
    5. Assert exit code is 0 (files identical)
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Run full episode flow
    final_state1, final_state2 = run_full_episode_flow(page1, page2, base_url)

    # Verify completion
    assert final_state1["numEpisodes"] >= 1, "Player 1 should complete 1+ episodes"
    assert final_state2["numEpisodes"] >= 1, "Player 2 should complete 1+ episodes"

    # Extract identifiers for finding export files
    experiment_id = get_experiment_id()
    scene_id = get_scene_id(page1)
    assert scene_id, "Could not get scene ID from game"

    subject_ids = get_subject_ids_from_pages(page1, page2)
    print(f"\nSubject IDs: {subject_ids[0]}, {subject_ids[1]}")
    print(f"Scene ID: {scene_id}")

    # Wait for export files to be written
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

    print(f"Found export files: {file1}, {file2}")

    # Run comparison
    exit_code, output = run_comparison(file1, file2, verbose=True)

    # Print output for diagnostics
    print(f"\nComparison output:\n{output}")

    # Assert parity
    if exit_code != 0:
        pytest.fail(f"Data parity check failed (exit code {exit_code}):\n{output}")

    print("\nData parity verified: both players exported identical data")


@pytest.mark.timeout(300)  # 5 minutes max for full flow
def test_export_parity_with_latency(flask_server, player_contexts, clean_data_dir):
    """
    Test that export files are identical even under network latency.

    Validates DATA-02: Exports should be identical even when one player
    has network latency, which triggers rollbacks and data confirmation delays.

    This validates that the dual-buffer data recording (v1.8) correctly
    handles speculative data and confirmation under latency conditions.

    Configuration:
    - Player 1: no artificial latency
    - Player 2: 100ms latency
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Apply latency to player 2 BEFORE navigation
    cdp2 = apply_latency(page2, latency_ms=100)

    try:
        # Run full episode flow
        final_state1, final_state2 = run_full_episode_flow(page1, page2, base_url)

        # Verify completion
        assert final_state1["numEpisodes"] >= 1, "Player 1 should complete 1+ episodes"
        assert final_state2["numEpisodes"] >= 1, "Player 2 should complete 1+ episodes"

        # Extract identifiers
        experiment_id = get_experiment_id()
        scene_id = get_scene_id(page1)
        assert scene_id, "Could not get scene ID from game"

        subject_ids = get_subject_ids_from_pages(page1, page2)
        print(f"\nSubject IDs: {subject_ids[0]}, {subject_ids[1]}")
        print(f"Scene ID: {scene_id}")
        print("Latency: Player 1 = 0ms, Player 2 = 100ms")

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

        print(f"Found export files: {file1}, {file2}")

        # Run comparison
        exit_code, output = run_comparison(file1, file2, verbose=True)

        # Print output for diagnostics
        print(f"\nComparison output:\n{output}")

        # Assert parity
        if exit_code != 0:
            pytest.fail(
                f"Data parity check failed under latency (exit code {exit_code}):\n{output}"
            )

        print("\nData parity verified under latency: both players exported identical data")

    finally:
        # Cleanup CDP session
        try:
            cdp2.detach()
        except Exception:
            pass  # Session may already be closed


@pytest.mark.timeout(300)  # 5 minutes max for full flow
def test_active_input_parity(flask_server, player_contexts, clean_data_dir):
    """
    Test that export files are identical when both players actively input actions.

    Unlike idle tests where both players emit Noop every frame, this test
    validates data parity with real gameplay inputs. This is critical because:
    - Idle tests could mask bugs where action values are incorrectly recorded
    - Rollback correction must handle real action values, not just Noop
    - Real gameplay has both players pressing different keys at different times

    Configuration:
    - Player 1: random actions every 150ms
    - Player 2: random actions every 200ms
    - Different intervals create input conflicts that stress rollback handling
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Run through to gameplay (shared helper handles matchmaking + tutorial)
    run_full_episode_flow_until_gameplay(page1, page2, base_url)

    # Verify both players are in same game
    from tests.fixtures.game_helpers import get_game_state
    state1 = get_game_state(page1)
    state2 = get_game_state(page2)
    assert state1["gameId"] == state2["gameId"], "Players should be in same game"
    assert state1["playerId"] != state2["playerId"], "Players should have different IDs"

    # Start random action injection on both players (different intervals)
    interval1 = start_random_actions(page1, interval_ms=150)
    interval2 = start_random_actions(page2, interval_ms=200)

    print(f"\n[Active Input] Started random actions (P1: 150ms, P2: 200ms)")

    try:
        # Wait for episode completion
        wait_for_episode_complete(page1, episode_num=1, timeout=180000)
        wait_for_episode_complete(page2, episode_num=1, timeout=180000)
    finally:
        # Stop actions regardless of episode completion
        stop_random_actions(page1, interval1)
        stop_random_actions(page2, interval2)

    # Note: Action stats verification after episode completion is unreliable
    # because frameDataBuffer is cleared after export. The export comparison
    # below verifies that actions were correctly recorded.

    # Get final states
    final_state1 = get_game_state(page1)
    final_state2 = get_game_state(page2)

    # Verify completion
    assert final_state1["numEpisodes"] >= 1, "Player 1 should complete 1+ episodes"
    assert final_state2["numEpisodes"] >= 1, "Player 2 should complete 1+ episodes"

    # Extract identifiers for finding export files
    experiment_id = get_experiment_id()
    scene_id = get_scene_id(page1)
    assert scene_id, "Could not get scene ID from game"

    subject_ids = get_subject_ids_from_pages(page1, page2)
    print(f"  Subject IDs: {subject_ids[0]}, {subject_ids[1]}")
    print(f"  Scene ID: {scene_id}")

    # Wait for export files to be written
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

    print(f"  Found export files: {file1}, {file2}")

    # Run comparison
    exit_code, output = run_comparison(file1, file2, verbose=True)

    # Print output for diagnostics
    print(f"\nComparison output:\n{output}")

    # Assert parity
    if exit_code != 0:
        pytest.fail(
            f"Data parity check failed with active inputs (exit code {exit_code}):\n{output}"
        )

    print("\nData parity verified with active inputs: both players exported identical data")


@pytest.mark.timeout(300)
def test_focus_loss_mid_episode_parity(flask_server, player_contexts, clean_data_dir):
    """
    FOCUS-01: Test data parity maintained when one client loses focus mid-episode.

    Strategy:
    1. Run both players to active gameplay
    2. Let game run for 3 seconds (establish frames)
    3. Hide player 1's tab (simulated focus loss)
    4. Wait 5 seconds while player 2 continues
    5. Show player 1's tab (triggers fast-forward)
    6. Wait for fast-forward to complete
    7. Complete episode
    8. Compare export files for parity

    This validates that the dual-buffer data recording correctly handles:
    - Backgrounded player using defaultAction
    - Fast-forward processing buffered partner inputs
    - Data promotion after fast-forward completes

    Validates dual-buffer fixes from Phases 48-49:
    - Phase 48: isFocused column consistency (getFocusStatePerPlayer ensures both
      players always export isFocused.0 and isFocused.1 columns)
    - Phase 49: Episode boundary row parity (BOUND-02/03 guards)
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Run through to gameplay (shared helper handles matchmaking + UI flow)
    run_full_episode_flow_until_gameplay(page1, page2, base_url)

    # Verify both players are in same game
    state1 = get_game_state(page1)
    state2 = get_game_state(page2)
    assert state1["gameId"] == state2["gameId"], "Players should be in same game"
    assert state1["playerId"] != state2["playerId"], "Players should have different IDs"

    # Let game run for 3 seconds (establish some frames before focus loss)
    print("\n[Focus Loss Mid-Episode] Letting game run for 3 seconds...")
    time.sleep(3)

    # Record frame number before hiding
    frame_before = page1.evaluate("() => window.game?.frameNumber || 0")
    print(f"  Player 1 frame before hide: {frame_before}")

    # Hide player 1's tab (simulated focus loss)
    set_tab_visibility(page1, visible=False)
    wait_for_focus_manager_state(page1, backgrounded=True, timeout=5000)
    print("  Player 1 backgrounded")

    # Wait 5 seconds while player 2 continues (player 2 advances frames)
    print("  Waiting 5 seconds with player 1 hidden...")
    time.sleep(5)

    # Record player 2's frame number during hide
    frame_p2_during = page2.evaluate("() => window.game?.frameNumber || 0")
    print(f"  Player 2 frame during hide: {frame_p2_during}")

    # Show player 1's tab (triggers fast-forward)
    set_tab_visibility(page1, visible=True)
    wait_for_focus_manager_state(page1, backgrounded=False, timeout=5000)
    print("  Player 1 refocused, waiting for fast-forward...")

    # Wait for fast-forward to complete
    page1.wait_for_function(
        "() => window.game && !window.game._pendingFastForward",
        timeout=30000
    )

    # Record frame after fast-forward
    frame_after = page1.evaluate("() => window.game?.frameNumber || 0")
    print(f"  Player 1 frame after fast-forward: {frame_after}")
    print(f"  Frame jump: {frame_after - frame_before}")

    # Wait for episode completion
    wait_for_episode_complete(page1, episode_num=1, timeout=180000)
    wait_for_episode_complete(page2, episode_num=1, timeout=180000)

    # Get final states
    final_state1 = get_game_state(page1)
    final_state2 = get_game_state(page2)

    # Verify completion
    assert final_state1["numEpisodes"] >= 1, "Player 1 should complete 1+ episodes"
    assert final_state2["numEpisodes"] >= 1, "Player 2 should complete 1+ episodes"

    # Extract identifiers for finding export files
    experiment_id = get_experiment_id()
    scene_id = get_scene_id(page1)
    assert scene_id, "Could not get scene ID from game"

    subject_ids = get_subject_ids_from_pages(page1, page2)
    print(f"  Subject IDs: {subject_ids[0]}, {subject_ids[1]}")
    print(f"  Scene ID: {scene_id}")

    # Wait for export files to be written
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

    print(f"  Found export files: {file1}, {file2}")

    # Run comparison
    exit_code, output = run_comparison(file1, file2, verbose=True)

    # Print output for diagnostics
    print(f"\nComparison output:\n{output}")

    # Assert parity
    if exit_code != 0:
        pytest.fail(
            f"Data parity check failed after focus loss (exit code {exit_code}):\n{output}"
        )

    print("\n[Focus Loss Mid-Episode] Data parity verified: both players exported identical data")
