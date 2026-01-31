"""
Game automation helpers for Playwright E2E tests.

These helpers encapsulate waiting for game states and UI interactions,
making tests cleaner and more maintainable.

Note: The game object is exposed via window.game (defined in index.js).
For multiplayer, this is an instance of MultiplayerPyodideGame.
"""
from playwright.sync_api import Page


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
