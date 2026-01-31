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


def click_continue(page: Page, timeout: int = 5000) -> None:
    """Click the Continue/Advance button to progress through scenes."""
    # Try advanceButton first (main continue button)
    advance_btn = page.locator("#advanceButton")
    if advance_btn.is_visible(timeout=timeout):
        advance_btn.click()
        return

    # Try startButton as fallback (for initial start)
    start_btn = page.locator("#startButton")
    if start_btn.is_visible(timeout=timeout):
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
