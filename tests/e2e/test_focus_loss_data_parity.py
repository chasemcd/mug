"""
Focus loss episode boundary parity test.

Extracted from test_data_comparison.py to get a fresh module-scoped flask_server
instance. The module-scoped fixture exhausts eventlet/socketio state after 4 game
sessions within a single module, causing Page.goto timeouts on the 5th test.
By placing this test in its own module, it gets a fresh server instance via the
existing module-scoped fixture in conftest.py.
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
                                         get_scene_id,
                                         run_full_episode_flow_until_gameplay,
                                         wait_for_episode_complete,
                                         wait_for_game_canvas,
                                         wait_for_game_object,
                                         wait_for_socket_connected)
from tests.fixtures.network_helpers import (set_tab_visibility,
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


@pytest.mark.timeout(300)
def test_focus_loss_episode_boundary_parity(flask_server, player_contexts, clean_data_dir):
    """
    FOCUS-02: Test data parity maintained when one client loses focus at episode boundary.

    Strategy:
    1. Run both players to active gameplay
    2. Wait until close to episode end (frame count approaching max)
    3. Hide player 1's tab near the boundary
    4. Episode ends while player 1 is backgrounded
    5. Player 1 refocuses after episode boundary promotion occurs
    6. Compare export files for parity

    This validates that the dual-buffer data recording correctly handles:
    - _promoteRemainingAtBoundary() when player is backgrounded
    - Episode completion detection while backgrounded
    - Data consistency at episode boundaries with pending fast-forward
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

    print("\n[Focus Loss Boundary] Waiting for game to approach episode end...")

    # Wait until game is close to episode end (e.g., 80% of max frames)
    # Test config uses max_steps=450 (~15 seconds at 30 FPS)
    # We wait for 360 frames (80%) to be close to the boundary
    page1.wait_for_function(
        "() => window.game && window.game.frameNumber >= 360",
        timeout=120000
    )

    frame_at_hide = page1.evaluate("() => window.game?.frameNumber || 0")
    print(f"  Player 1 frame at hide: {frame_at_hide}")

    # Hide player 1's tab near episode boundary
    set_tab_visibility(page1, visible=False)
    wait_for_focus_manager_state(page1, backgrounded=True, timeout=5000)
    print("  Player 1 backgrounded near episode boundary")

    # Wait for episode complete on player 2
    # Player 1 may still be backgrounded when episode ends
    print("  Waiting for player 2 episode completion...")
    wait_for_episode_complete(page2, episode_num=1, timeout=60000)
    print("  Player 2 episode complete")

    # Brief delay to let episode boundary processing occur
    time.sleep(2)

    # Show player 1's tab after episode should have ended
    set_tab_visibility(page1, visible=True)
    wait_for_focus_manager_state(page1, backgrounded=False, timeout=5000)
    print("  Player 1 refocused")

    # Wait for player 1's episode completion (may already be complete)
    wait_for_episode_complete(page1, episode_num=1, timeout=60000)
    print("  Player 1 episode complete")

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
            f"Data parity check failed at episode boundary (exit code {exit_code}):\n{output}"
        )

    print("\n[Focus Loss Boundary] Data parity verified: both players exported identical data")
