"""
Game automation helpers for Playwright E2E tests.

These helpers encapsulate waiting for game states and UI interactions,
making tests cleaner and more maintainable.

Note: The game object is exposed via window.game (defined in index.js).
For multiplayer, this is an instance of MultiplayerPyodideGame.
"""
from __future__ import annotations

from playwright.sync_api import Page

from tests.fixtures.network_helpers import set_tab_visibility


def wait_for_socket_connected(page: Page, timeout: int = 10000) -> None:
    """Wait for SocketIO connection to be established."""
    page.wait_for_function(
        "() => window.socket && window.socket.connected",
        timeout=timeout
    )


def wait_for_game_canvas(page: Page, timeout: int = 60000) -> None:
    """Wait for Phaser game canvas to become visible (game started)."""
    # Canvas is inside gameContainer, look for canvas element
    page.wait_for_selector("#gameContainer canvas", state="visible", timeout=timeout)


def wait_for_game_object(page: Page, timeout: int = 30000) -> None:
    """Wait for game object to be initialized (window.game)."""
    page.wait_for_function(
        "() => window.game !== undefined && window.game !== null",
        timeout=timeout
    )


def wait_for_episode_complete(page: Page, episode_num: int = 1, timeout: int = 180000) -> None:
    """
    Wait for episode completion.

    The game increments num_episodes when an episode completes.
    We check num_episodes counter on the game object.
    """
    page.wait_for_function(
        f"() => window.game && window.game.num_episodes >= {episode_num}",
        timeout=timeout
    )


def get_game_state(page: Page) -> dict:
    """Get current game state for assertions."""
    return page.evaluate("""() => {
        const game = window.game;
        if (!game) return null;
        return {
            state: game.state,
            frameNumber: game.frameNumber,
            numEpisodes: game.num_episodes,
            maxEpisodes: game.max_episodes,
            gameId: game.gameId,
            playerId: game.myPlayerId
        };
    }""")


def wait_for_advance_button(page: Page, timeout: int = 30000) -> None:
    """Wait for advanceButton to be visible (scene activated after screening)."""
    page.wait_for_selector("#advanceButton", state="visible", timeout=timeout)


def wait_for_start_button_enabled(page: Page, timeout: int = 60000) -> None:
    """Wait for startButton to be visible and enabled (Pyodide loaded)."""
    # Wait for button to be visible first
    page.wait_for_selector("#startButton", state="visible", timeout=timeout)
    # Then wait for it to be enabled (not disabled)
    page.wait_for_function(
        "() => !document.getElementById('startButton').disabled",
        timeout=timeout
    )


def click_advance_button(page: Page, timeout: int = 30000) -> None:
    """Wait for and click the advanceButton (for static/instruction scenes)."""
    wait_for_advance_button(page, timeout)
    page.locator("#advanceButton").click()


def click_start_button(page: Page, timeout: int = 60000) -> None:
    """Wait for startButton to be enabled and click it (for GymScenes)."""
    wait_for_start_button_enabled(page, timeout)
    page.locator("#startButton").click()


def click_continue(page: Page, timeout: int = 30000) -> None:
    """
    Click the appropriate continue button to progress through scenes.

    Tries advanceButton first (for static scenes), then startButton (for GymScenes).
    This function waits for buttons to become visible before checking.
    """
    # Wait for either button to become visible
    try:
        page.wait_for_selector("#advanceButton:visible, #startButton:visible", timeout=timeout)
    except Exception:
        raise Exception("No continue button found within timeout")

    # Check which button is visible and click it
    advance_btn = page.locator("#advanceButton")
    if advance_btn.is_visible():
        # For advanceButton, just click (always enabled when visible)
        advance_btn.click()
        return

    start_btn = page.locator("#startButton")
    if start_btn.is_visible():
        # For startButton, wait for it to be enabled first
        page.wait_for_function(
            "() => !document.getElementById('startButton').disabled",
            timeout=timeout
        )
        start_btn.click()
        return

    raise Exception("No continue button found")


def wait_for_waitroom(page: Page, timeout: int = 10000) -> None:
    """Wait for waitroom text to appear (matchmaking started)."""
    page.wait_for_selector("#waitroomText", state="visible", timeout=timeout)


def wait_for_waitroom_matched(page: Page, timeout: int = 60000) -> None:
    """Wait for waitroom to complete (matched with partner)."""
    # Waitroom disappears when matched, or game canvas appears
    page.wait_for_function(
        """() => {
            const waitroom = document.getElementById('waitroomText');
            const canvas = document.querySelector('#gameContainer canvas');
            return (waitroom && waitroom.style.display === 'none') ||
                   (canvas && canvas.offsetParent !== null);
        }""",
        timeout=timeout
    )


def wait_for_scene_header_contains(page: Page, text: str, timeout: int = 60000) -> None:
    """Wait for scene header to contain specific text."""
    page.wait_for_function(
        f"() => document.getElementById('sceneHeader')?.innerText?.includes('{text}')",
        timeout=timeout
    )


def complete_tutorial_and_advance(page: Page, timeout: int = 120000) -> None:
    """
    Complete the tutorial scene and advance to the next scene.

    This helper handles the full tutorial flow:
    1. Click startButton to begin tutorial
    2. Wait for tutorial game canvas to appear
    3. Wait for tutorial to complete and scene to advance to multiplayer
    """
    click_start_button(page, timeout)
    wait_for_game_canvas(page, timeout)
    # Wait for scene to advance to multiplayer (detected by header change)
    wait_for_scene_header_contains(page, "Multiplayer", timeout)


def get_page_debug_info(page: Page) -> dict:
    """Get debugging info about the current page state."""
    return page.evaluate("""() => {
        const result = {
            url: window.location.href,
            socketConnected: window.socket && window.socket.connected,
            gameExists: window.game !== undefined && window.game !== null,
            gameState: null,
            visibleElements: {
                startButton: document.getElementById('startButton')?.offsetParent !== null,
                advanceButton: document.getElementById('advanceButton')?.offsetParent !== null,
                waitroomText: document.getElementById('waitroomText')?.offsetParent !== null,
                gameContainer: document.getElementById('gameContainer')?.offsetParent !== null,
                canvas: document.querySelector('#gameContainer canvas')?.offsetParent !== null
            },
            waitroomContent: document.getElementById('waitroomText')?.innerText || null,
            sceneHeader: document.getElementById('sceneHeader')?.innerText || null
        };
        if (result.gameExists) {
            const game = window.game;
            result.gameState = {
                state: game.state,
                frameNumber: game.frameNumber,
                numEpisodes: game.num_episodes,
                gameId: game.gameId,
                playerId: game.myPlayerId,
                pyodideReady: game.pyodideReady
            };
        }
        return result;
    }""")


def get_scene_id(page: Page) -> str:
    """
    Get the current scene ID from the game object.

    The scene ID is used in export file paths and identifies the game layout
    (e.g., "cramped_room", "asymmetric_advantages").

    Args:
        page: Playwright Page object

    Returns:
        str: The scene ID, or None if game not initialized
    """
    return page.evaluate("() => window.game?.sceneId || null")


def get_subject_id(page: Page) -> str:
    """
    Get the subject ID for this player.

    Subject IDs are unique identifiers assigned by the server to each
    participant and used in export filenames.

    Args:
        page: Playwright Page object

    Returns:
        str: The subject ID, or None if not available
    """
    return page.evaluate("() => window.subjectId || window.game?.subjectId || null")


def run_full_episode_flow(
    page1: Page, page2: Page, base_url: str,
    episode_timeout: int = 180000,
    setup_timeout: int = 120000,
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

    # Override visibility for Playwright automation
    # Without this, FocusManager thinks tab is backgrounded and skips frame processing
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)

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


def run_full_episode_flow_until_gameplay(page1: Page, page2: Page, base_url: str) -> None:
    """
    Progress both players from navigation to active gameplay.

    This helper runs both players through:
    1. Navigate to base URL
    2. Wait for socket connection
    3. Click advance button (instructions)
    4. Click start button (multiplayer matchmaking)
    5. Wait for game canvas and game object

    Note: Tutorial scene is disabled in test config for faster execution.

    After this function returns, both players are in-game and ready
    for action injection or waiting for episode completion.

    Args:
        page1: Playwright Page for player 1
        page2: Playwright Page for player 2
        base_url: Flask server URL
    """
    # Navigate to game
    page1.goto(base_url)
    page2.goto(base_url)

    # Wait for socket connection
    wait_for_socket_connected(page1, timeout=30000)
    wait_for_socket_connected(page2, timeout=30000)

    # Pass instructions
    click_advance_button(page1, timeout=60000)
    click_advance_button(page2, timeout=60000)

    # Start multiplayer (tutorial scene is disabled in test config)
    click_start_button(page1, timeout=60000)
    click_start_button(page2, timeout=60000)

    # Wait for game to start
    wait_for_game_canvas(page1, timeout=120000)
    wait_for_game_canvas(page2, timeout=120000)
    wait_for_game_object(page1, timeout=60000)
    wait_for_game_object(page2, timeout=60000)

    # CRITICAL: Override document.hidden for Playwright
    # Without this, FocusManager thinks tab is backgrounded and skips frame processing
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)
