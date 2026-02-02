"""
Basic multiplayer test - two players connect and complete one episode.

This test validates INFRA-01 and INFRA-02:
- Two browser contexts connect to same game session
- Both progress through matchmaking to gameplay
- Game completion state can be captured

The game runs with idle inputs (no keystrokes) - this is valid because:
1. Overcooked has a time limit, so episodes end naturally
2. We're testing infrastructure, not gameplay strategy

Scene flow for the example experiment:
1. StartScene (static) - advanceButton
2. Tutorial GymScene (single player) - startButton -> auto-completes
3. Multiplayer GymScene - startButton -> waitroom -> P2P game
"""
import pytest
from tests.fixtures.game_helpers import (
    wait_for_socket_connected,
    wait_for_game_canvas,
    wait_for_game_object,
    wait_for_episode_complete,
    get_game_state,
    click_advance_button,
    click_start_button,
)
from tests.fixtures.network_helpers import set_tab_visibility


@pytest.mark.timeout(300)  # 5 minutes max for full flow
def test_two_players_connect_and_complete_episode(flask_server, player_contexts):
    """
    Test that two players can:
    1. Connect to the game server
    2. Progress through start scene (instructions)
    3. Complete tutorial scene (single-player warm-up)
    4. Enter multiplayer waitroom and get matched
    5. Start gameplay
    6. Complete at least one episode (via timeout, players are idle)
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Step 1: Both players navigate to game
    page1.goto(base_url)
    page2.goto(base_url)

    # Step 2: Wait for socket connections
    wait_for_socket_connected(page1)
    wait_for_socket_connected(page2)

    # Step 3: Pass the instructions scene (StartScene with advanceButton)
    click_advance_button(page1)
    click_advance_button(page2)

    # Step 4: Click startButton for the multiplayer scene
    # (Tutorial scene removed in commit 607b60a)
    click_start_button(page1)
    click_start_button(page2)

    # Step 5: Wait for game to start (matchmaking)
    # When both players join, they enter waitroom then P2P connection establishes
    wait_for_game_canvas(page1, timeout=90000)
    wait_for_game_canvas(page2, timeout=90000)

    # Step 6: Verify game objects initialized
    wait_for_game_object(page1)
    wait_for_game_object(page2)

    # Override visibility for Playwright automation
    # Without this, FocusManager thinks tab is backgrounded and skips frame processing
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)

    # Get initial state
    state1 = get_game_state(page1)
    state2 = get_game_state(page2)

    # Verify both are in same game
    assert state1["gameId"] == state2["gameId"], "Players should be in same game"
    assert state1["playerId"] != state2["playerId"], "Players should have different IDs"

    # Step 7: Wait for first episode to complete
    # Players are idle, so episode completes via time limit
    # Overcooked cramped_room has short episodes (~60s)
    wait_for_episode_complete(page1, episode_num=1, timeout=180000)
    wait_for_episode_complete(page2, episode_num=1, timeout=180000)

    # Step 8: Verify completion state
    final_state1 = get_game_state(page1)
    final_state2 = get_game_state(page2)

    assert final_state1["numEpisodes"] >= 1, "Player 1 should have completed 1+ episodes"
    assert final_state2["numEpisodes"] >= 1, "Player 2 should have completed 1+ episodes"

    # Log success metrics
    print(f"Game completed: gameId={final_state1['gameId']}")
    print(f"Player 1: episodes={final_state1['numEpisodes']}, frames={final_state1['frameNumber']}")
    print(f"Player 2: episodes={final_state2['numEpisodes']}, frames={final_state2['frameNumber']}")


@pytest.mark.timeout(180)  # 3 minutes for matchmaking test
def test_matchmaking_pairs_two_players(flask_server, player_contexts):
    """
    Test that matchmaking successfully pairs two players.

    This is a lighter test that just verifies matchmaking works
    without waiting for full episode completion.
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Navigate and connect
    page1.goto(base_url)
    page2.goto(base_url)
    wait_for_socket_connected(page1)
    wait_for_socket_connected(page2)

    # Pass through instructions scene
    click_advance_button(page1)
    click_advance_button(page2)

    # Click startButton for the multiplayer scene
    # (Tutorial scene removed in commit 607b60a)
    click_start_button(page1)
    click_start_button(page2)

    # Wait for either waitroom or game canvas (matchmaking may be instant)
    # When both players join quickly, they may skip the visible waitroom phase
    wait_for_game_canvas(page1, timeout=90000)
    wait_for_game_canvas(page2, timeout=90000)

    # Verify game objects exist and have same gameId
    wait_for_game_object(page1)
    wait_for_game_object(page2)

    # Override visibility for Playwright automation
    # Without this, FocusManager thinks tab is backgrounded and skips frame processing
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)

    state1 = get_game_state(page1)
    state2 = get_game_state(page2)

    assert state1 is not None, "Player 1 game object should exist"
    assert state2 is not None, "Player 2 game object should exist"
    assert state1["gameId"] == state2["gameId"], "Players should be matched in same game"
