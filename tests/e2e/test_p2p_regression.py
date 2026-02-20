"""
P2P multiplayer regression test (TEST-04).

Regression test ensuring P2P (Pyodide-based) multiplayer still works
end-to-end after the v1.1 server-authoritative cleanup.

This test mirrors test_two_players_connect_and_complete_episode from
test_multiplayer_basic.py but is explicitly named as a regression test
and verifies that server-authoritative mode is NOT active.

Scene flow: StartScene (advanceButton) -> P2P GymScene (startButton) -> episode

IMPORTANT: E2E tests using WebRTC require HEADED mode!
Run with: pytest tests/e2e/test_p2p_regression.py --headed
"""
from __future__ import annotations

import pytest

from tests.fixtures.game_helpers import (click_advance_button,
                                         click_start_button, get_game_state,
                                         wait_for_episode_complete,
                                         wait_for_game_canvas,
                                         wait_for_game_object,
                                         wait_for_socket_connected)
from tests.fixtures.network_helpers import set_tab_visibility


@pytest.mark.timeout(300)
def test_p2p_two_players_still_work(flask_server, player_contexts):
    """
    Regression test: P2P multiplayer still works after v1.1 server-auth changes.

    Verifies:
    1. Two players connect and progress through start scene
    2. Matchmaking pairs them in a P2P game
    3. Both players initialize game objects with matching game IDs
    4. window.serverAuthoritative is falsy (P2P mode, not server-auth)
    5. Episode completes via P2P game loop (idle players, time limit)
    6. Server process remains healthy

    This is a regression guard -- if server-authoritative refactoring
    accidentally breaks the P2P path, this test will catch it.
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

    # Step 4: Click startButton for the P2P GymScene
    click_start_button(page1)
    click_start_button(page2)

    # Step 5: Wait for game canvas (matchmaking + P2P connection)
    wait_for_game_canvas(page1, timeout=90000)
    wait_for_game_canvas(page2, timeout=90000)

    # Step 6: Wait for game objects to initialize
    wait_for_game_object(page1)
    wait_for_game_object(page2)

    # Step 7: Override tab visibility for Playwright automation
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)

    # Step 8: Verify both players are in the same game
    state1 = get_game_state(page1)
    state2 = get_game_state(page2)
    assert state1["gameId"] == state2["gameId"], "Players should be in same game"
    assert state1["playerId"] != state2["playerId"], "Players should have different IDs"

    # Step 9: Verify P2P mode (not server-authoritative)
    sa1 = page1.evaluate("() => window.serverAuthoritative")
    sa2 = page2.evaluate("() => window.serverAuthoritative")
    assert not sa1, "Player 1 should NOT be in server-authoritative mode (P2P regression)"
    assert not sa2, "Player 2 should NOT be in server-authoritative mode (P2P regression)"

    # Step 10: Wait for first episode to complete (players idle, time limit ends it)
    wait_for_episode_complete(page1, episode_num=1)
    wait_for_episode_complete(page2, episode_num=1)

    # Step 11: Verify server process is still running
    assert flask_server["process"].poll() is None, \
        "Server should still be running after P2P episode completion"

    # Log success metrics
    final_state1 = get_game_state(page1)
    final_state2 = get_game_state(page2)
    print(f"P2P regression test passed: gameId={final_state1['gameId']}")
    print(f"Player 1: episodes={final_state1['numEpisodes']}, frames={final_state1['frameNumber']}")
    print(f"Player 2: episodes={final_state2['numEpisodes']}, frames={final_state2['frameNumber']}")
