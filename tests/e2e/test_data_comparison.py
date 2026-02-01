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
import os
import shutil
import pytest

from tests.fixtures.export_helpers import (
    get_experiment_id,
    get_subject_ids_from_pages,
    wait_for_export_files,
    run_comparison,
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
    get_scene_id,
    run_full_episode_flow_until_gameplay,
)
from tests.fixtures.network_helpers import apply_latency
from tests.fixtures.input_helpers import (
    start_random_actions,
    stop_random_actions,
    verify_non_noop_actions,
)


def run_full_episode_flow(
    page1, page2, base_url: str,
    episode_timeout: int = 180000,
    setup_timeout: int = 120000
) -> tuple:
    """
    Run the full game flow through one complete episode.

    This helper encapsulates the game progression flow shared by all tests.

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

    # Wait for socket connections
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
    try:
        file1, file2 = wait_for_export_files(
            experiment_id=experiment_id,
            scene_id=scene_id,
            subject_ids=subject_ids,
            episode_num=1,
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
        try:
            file1, file2 = wait_for_export_files(
                experiment_id=experiment_id,
                scene_id=scene_id,
                subject_ids=subject_ids,
                episode_num=1,
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

    # Verify both players recorded non-trivial actions
    passed1, stats1, count1 = verify_non_noop_actions(page1)
    passed2, stats2, count2 = verify_non_noop_actions(page2)

    print(f"  Player 1 non-Noop actions: {count1} (stats: {stats1})")
    print(f"  Player 2 non-Noop actions: {count2} (stats: {stats2})")

    assert passed1, f"Player 1 should have non-Noop actions: {stats1}"
    assert passed2, f"Player 2 should have non-Noop actions: {stats2}"

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
            episode_num=1,
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
