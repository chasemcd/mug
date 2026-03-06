"""
E2E test for server-authoritative mode (TEST-03).

Proves that two browser clients can connect to a server-auth game,
see the game state rendered, and complete an episode driven by the
server's game loop (max_steps=200, ~7 seconds).

Server-authoritative mode differences from P2P:
- No Pyodide loading (environment runs on the server)
- Game state arrives via server_render_state events (not WebRTC)
- window.serverAuthoritative is set to true on start_game
- Episode completion is driven by the server's step count
- end_game event clears serverAuthoritative and shows post-game UI

Scene flow: StartScene (advanceButton) -> GymScene (server-auth) -> EndScene
"""
from __future__ import annotations

import pytest

from tests.fixtures.game_helpers import (click_advance_button,
                                         click_start_button,
                                         wait_for_game_canvas,
                                         wait_for_socket_connected)
from tests.fixtures.network_helpers import set_tab_visibility


@pytest.mark.timeout(300)
def test_server_auth_two_players_complete_episode(flask_server_auth, player_contexts):
    """
    Test that two players can connect to a server-authoritative game and
    complete an episode with validated rendering.

    Verifies:
    1. Both players connect via socket and progress through start scene
    2. Server-auth GymScene starts without Pyodide loading
    3. window.serverAuthoritative is true for both players
    4. Game canvas renders (Phaser is running)
    5. Objects actually render on canvas (objectMap populated)
    6. No texture errors in console logs
    7. Episode completes via server timer (max_steps=200)
    8. Server process remains healthy throughout
    """
    page1, page2 = player_contexts
    base_url = flask_server_auth["url"]

    # Step 1: Both players navigate to game
    page1.goto(base_url)
    page2.goto(base_url)

    # Install console error collectors after navigation
    for page in (page1, page2):
        page.evaluate("""() => {
            window._consoleErrors = [];
            const origError = console.error;
            console.error = function(...args) {
                window._consoleErrors.push(args.map(a => String(a)).join(' '));
                origError.apply(console, args);
            };
            const origWarn = console.warn;
            console.warn = function(...args) {
                window._consoleErrors.push(args.map(a => String(a)).join(' '));
                origWarn.apply(console, args);
            };
        }""")

    # Step 2: Wait for socket connections
    wait_for_socket_connected(page1)
    wait_for_socket_connected(page2)

    # Step 3: Pass the instructions scene (StartScene with advanceButton)
    click_advance_button(page1)
    click_advance_button(page2)

    # Step 4: Click startButton for the server-auth GymScene
    # No Pyodide loading needed -- button should enable quickly
    click_start_button(page1)
    click_start_button(page2)

    # Step 5: Wait for game canvas to appear (matchmaking still applies)
    wait_for_game_canvas(page1, timeout=90000)
    wait_for_game_canvas(page2, timeout=90000)

    # Step 6: Override tab visibility for Playwright automation
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)

    # Step 7: Verify server-authoritative mode is active on both clients
    sa1 = page1.evaluate("() => window.serverAuthoritative === true")
    sa2 = page2.evaluate("() => window.serverAuthoritative === true")
    assert sa1, "Player 1 should be in server-authoritative mode"
    assert sa2, "Player 2 should be in server-authoritative mode"

    # Step 8: Verify game ID is set (both players matched into same game)
    game_id1 = page1.evaluate("() => window.currentGameId")
    game_id2 = page2.evaluate("() => window.currentGameId")
    assert game_id1 is not None, "Player 1 should have a game ID"
    assert game_id1 == game_id2, "Players should be in the same game"

    # Step 9: Validate that objects are actually being rendered
    # window._phaserScene is exposed by GymScene.create() for introspection
    page1.wait_for_function(
        """() => {
            const scene = window._phaserScene;
            return scene && scene.objectMap && scene.objectMap.size > 10;
        }""",
        timeout=30000,
    )
    obj_count = page1.evaluate(
        "() => window._phaserScene?.objectMap?.size || 0"
    )
    assert obj_count > 10, (
        f"Expected >10 rendered objects (tiles, agents, etc.), got {obj_count}"
    )

    # Step 10: Check for texture errors in console logs
    for i, page in enumerate((page1, page2), 1):
        errors = page.evaluate("() => window._consoleErrors || []")
        texture_errors = [e for e in errors if "__MISSING" in e or "has no frame" in e]
        assert not texture_errors, (
            f"Player {i} has texture errors in console: {texture_errors[:5]}"
        )

    # Step 11: Wait for the episode to complete
    # Server-auth games with max_steps=200 complete in ~7 seconds.
    # The server emits end_game when all episodes are done.
    # The client's end_game handler clears serverAuthoritative.
    page1.wait_for_function(
        """() => {
            // end_game clears serverAuthoritative
            if (window.serverAuthoritative === false || window.serverAuthoritative === undefined) {
                return true;
            }
            // Or end scene appeared (advanceButton or redirectButton visible)
            const advBtn = document.getElementById('advanceButton');
            const redBtn = document.getElementById('redirectButton');
            if (advBtn && advBtn.offsetParent !== null) return true;
            if (redBtn && redBtn.offsetParent !== null) return true;
            return false;
        }""",
        timeout=120000,
    )

    # Step 12: Verify server process is still running (no crash)
    assert flask_server_auth["process"].poll() is None, \
        "Server should still be running after episode completion"
