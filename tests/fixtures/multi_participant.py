"""
Multi-participant test orchestration helpers.

Provides GameOrchestrator class for managing 3 concurrent 2-player games,
used by multi-participant stress tests (STRESS-01 through STRESS-07).
"""
import time
from typing import List, Tuple, Dict, Any, Optional

from playwright.sync_api import Page

from tests.fixtures.game_helpers import (
    wait_for_socket_connected,
    wait_for_game_canvas,
    wait_for_game_object,
    wait_for_episode_complete,
    get_game_state,
    click_advance_button,
    click_start_button,
    get_scene_id,
    wait_for_advance_button,
    wait_for_start_button_enabled,
)
from tests.fixtures.network_helpers import set_tab_visibility
from tests.fixtures.export_helpers import (
    get_experiment_id,
    get_subject_ids_from_pages,
    wait_for_export_files,
    run_comparison,
)


def get_page_state(page: Page) -> Dict[str, Any]:
    """
    Get comprehensive UI state from a page for debugging.

    Returns dict with:
    - url: Current page URL
    - socket_connected: Whether socket.io is connected
    - scene_type: Current scene type (from currentSceneMetadata)
    - scene_id: Current scene ID
    - advance_button_visible: Whether #advanceButton is visible
    - start_button_visible: Whether #startButton is visible
    - start_button_enabled: Whether #startButton is not disabled
    - game_canvas_visible: Whether game canvas is visible
    - game_object_exists: Whether window.game exists
    - waitroom_text_visible: Whether #waitroomText is visible
    - error_text_visible: Whether #errorText is visible
    - error_text_content: Content of #errorText if visible
    - game_id: Game ID if game exists
    - player_id: Player ID if game exists
    """
    return page.evaluate("""() => {
        const state = {
            url: window.location.href,
            socket_connected: window.socket && window.socket.connected,
            scene_type: window.currentSceneMetadata?.scene_type || null,
            scene_id: window.currentSceneMetadata?.scene_id || null,
            advance_button_visible: false,
            start_button_visible: false,
            start_button_enabled: false,
            game_canvas_visible: false,
            game_object_exists: false,
            waitroom_text_visible: false,
            error_text_visible: false,
            error_text_content: null,
            game_id: null,
            player_id: null,
        };

        // Check advance button
        const advBtn = document.getElementById('advanceButton');
        if (advBtn) {
            state.advance_button_visible = advBtn.offsetParent !== null &&
                                           getComputedStyle(advBtn).display !== 'none';
        }

        // Check start button
        const startBtn = document.getElementById('startButton');
        if (startBtn) {
            state.start_button_visible = startBtn.offsetParent !== null &&
                                         getComputedStyle(startBtn).display !== 'none';
            state.start_button_enabled = !startBtn.disabled;
        }

        // Check game canvas
        const canvas = document.querySelector('#gameContainer canvas');
        if (canvas) {
            state.game_canvas_visible = canvas.offsetParent !== null;
        }

        // Check game object
        state.game_object_exists = window.game !== undefined && window.game !== null;
        if (state.game_object_exists) {
            state.game_id = window.game.gameId || null;
            state.player_id = window.game.myPlayerId || null;
        }

        // Check waitroom text
        const waitroom = document.getElementById('waitroomText');
        if (waitroom) {
            state.waitroom_text_visible = waitroom.offsetParent !== null &&
                                          getComputedStyle(waitroom).display !== 'none';
        }

        // Check error text
        const errorText = document.getElementById('errorText');
        if (errorText) {
            state.error_text_visible = errorText.offsetParent !== null &&
                                       getComputedStyle(errorText).display !== 'none';
            if (state.error_text_visible) {
                state.error_text_content = errorText.textContent;
            }
        }

        return state;
    }""")


def log_page_state(page: Page, label: str) -> Dict[str, Any]:
    """Get and log page state with a label."""
    state = get_page_state(page)
    print(f"  [{label}] scene={state['scene_type']}, "
          f"socket={state['socket_connected']}, "
          f"advance={state['advance_button_visible']}, "
          f"start={state['start_button_visible']}(enabled={state['start_button_enabled']}), "
          f"canvas={state['game_canvas_visible']}, "
          f"game={state['game_object_exists']}, "
          f"waitroom={state['waitroom_text_visible']}, "
          f"error={state['error_text_visible']}")
    if state['error_text_visible'] and state['error_text_content']:
        print(f"    ERROR: {state['error_text_content']}")
    return state


def log_all_pages_state(pages: Tuple[Page, ...], step_name: str) -> List[Dict[str, Any]]:
    """Log state of all pages at a checkpoint."""
    print(f"\n=== {step_name} ===")
    states = []
    for i, page in enumerate(pages):
        state = log_page_state(page, f"Page {i}")
        states.append(state)
    return states


class GameOrchestrator:
    """
    Manages multiple concurrent 2-player games for stress testing.

    Organizes 6 pages into 3 game pairs and provides methods for:
    - Staggered navigation (ensures correct FIFO matchmaker pairing)
    - Parallel game progression through UI flow
    - Episode completion waiting
    - Data parity validation per game

    Usage:
        orchestrator = GameOrchestrator(pages, base_url)
        orchestrator.navigate_all_staggered()
        orchestrator.start_all_games()
        orchestrator.wait_for_all_episodes_complete()
        results = orchestrator.validate_all_data_parity()
    """

    def __init__(self, pages: Tuple[Page, ...], base_url: str):
        """
        Initialize orchestrator with 6 pages organized as 3 game pairs.

        Args:
            pages: Tuple of 6 Playwright Page objects
            base_url: Flask server URL

        Raises:
            ValueError: If pages tuple doesn't contain exactly 6 pages
        """
        if len(pages) != 6:
            raise ValueError(f"Expected 6 pages, got {len(pages)}")

        self.pages = pages
        self.base_url = base_url

        # Organize into game pairs: (page1, page2) = Game 0, etc.
        self.games: List[Tuple[Page, Page]] = [
            (pages[0], pages[1]),  # Game 0
            (pages[2], pages[3]),  # Game 1
            (pages[4], pages[5]),  # Game 2
        ]

        # Per-game tracking (populated after games start)
        self.game_ids: List[Optional[str]] = [None, None, None]
        self.subject_ids: List[Optional[Tuple[str, str]]] = [None, None, None]

    def navigate_all_staggered(self, delay_between_pairs_ms: int = 100, delay_between_games_ms: int = 1000) -> None:
        """
        Navigate all participants with staggered timing for correct FIFO pairing.

        The FIFO matchmaker pairs participants in arrival order. To ensure
        (page1, page2) become partners, they must navigate close together
        with a gap before (page3, page4).

        Args:
            delay_between_pairs_ms: Delay between partners in same game (small, ~100ms)
            delay_between_games_ms: Delay between game pairs (larger, ~1000ms)
        """
        for game_idx, (page1, page2) in enumerate(self.games):
            if game_idx > 0:
                # Wait before starting next game pair
                time.sleep(delay_between_games_ms / 1000)

            # Navigate both partners close together
            page1.goto(self.base_url)
            time.sleep(delay_between_pairs_ms / 1000)
            page2.goto(self.base_url)

    def wait_for_all_sockets(self, timeout: int = 30000) -> None:
        """Wait for all 6 participants to establish socket connections."""
        for page in self.pages:
            wait_for_socket_connected(page, timeout=timeout)

    def advance_all_through_instructions(self, timeout: int = 60000) -> None:
        """Click advance button for all participants (pass instruction screens)."""
        for page in self.pages:
            click_advance_button(page, timeout=timeout)

    def start_all_matchmaking(self, timeout: int = 60000) -> None:
        """Click start button for all participants (enter matchmaking)."""
        for page in self.pages:
            click_start_button(page, timeout=timeout)

    def wait_for_all_games_started(self, timeout: int = 120000) -> None:
        """
        Wait for all 6 participants to have game canvas and game object ready.
        Also sets tab visibility for Playwright automation.
        """
        for page in self.pages:
            wait_for_game_canvas(page, timeout=timeout)
            wait_for_game_object(page, timeout=timeout)
            set_tab_visibility(page, visible=True)

    def verify_game_pairings(self) -> None:
        """
        Verify that intended pairs are in the same game.

        Populates self.game_ids with verified game IDs.

        Raises:
            AssertionError: If any pair is not in the same game
        """
        for game_idx, (page1, page2) in enumerate(self.games):
            state1 = get_game_state(page1)
            state2 = get_game_state(page2)

            assert state1["gameId"] == state2["gameId"], (
                f"Game {game_idx}: Players not matched correctly. "
                f"Player 1 gameId={state1['gameId']}, Player 2 gameId={state2['gameId']}"
            )
            assert state1["playerId"] != state2["playerId"], (
                f"Game {game_idx}: Players have same playerId (should be different)"
            )

            self.game_ids[game_idx] = state1["gameId"]
            print(f"Game {game_idx}: Verified pairing, gameId={state1['gameId']}")

    def _wait_for_pair_game_started(self, page1: Page, page2: Page, timeout: int = 120000) -> None:
        """Wait for a single pair to have game canvas ready."""
        wait_for_game_canvas(page1, timeout=timeout)
        wait_for_game_canvas(page2, timeout=timeout)
        wait_for_game_object(page1, timeout=timeout)
        wait_for_game_object(page2, timeout=timeout)
        set_tab_visibility(page1, visible=True)
        set_tab_visibility(page2, visible=True)

    def start_all_games(self, stagger_delay_sec: float = 5.0) -> None:
        """
        Run all games through the full startup flow with per-pair orchestration.

        Each game pair completes its full startup sequence before the next pair
        begins. This prevents timing issues where early pairs timeout while
        waiting for later pairs to catch up.

        Flow per game pair:
        1. Navigate both players
        2. Wait for socket connections
        3. Click advance (pass instructions)
        4. Click start (enter matchmaking)
        5. Wait for game canvas + game object
        6. Verify pairing

        Args:
            stagger_delay_sec: Delay between starting each game pair
        """
        print("Starting 3 games with 6 participants (per-pair orchestration)...")

        for game_idx, (page1, page2) in enumerate(self.games):
            page1_idx = game_idx * 2
            page2_idx = game_idx * 2 + 1

            if game_idx > 0:
                print(f"\nWaiting {stagger_delay_sec}s before Game {game_idx}...")
                time.sleep(stagger_delay_sec)

            print(f"\n--- Game {game_idx} (pages {page1_idx}, {page2_idx}) ---")

            # Step 1: Navigate
            print(f"Game {game_idx}: Navigating...")
            page1.goto(self.base_url)
            time.sleep(0.1)  # Small gap between partners
            page2.goto(self.base_url)

            # Validate: pages loaded
            log_page_state(page1, f"Game{game_idx}-P1 after navigate")
            log_page_state(page2, f"Game{game_idx}-P2 after navigate")

            # Step 2: Wait for socket
            print(f"Game {game_idx}: Waiting for sockets...")
            wait_for_socket_connected(page1, timeout=30000)
            wait_for_socket_connected(page2, timeout=30000)

            # Validate: sockets connected
            s1 = log_page_state(page1, f"Game{game_idx}-P1 after socket")
            s2 = log_page_state(page2, f"Game{game_idx}-P2 after socket")
            assert s1['socket_connected'], f"Game {game_idx} P1: Socket not connected"
            assert s2['socket_connected'], f"Game {game_idx} P2: Socket not connected"

            # Step 3: Wait for advance button, then click
            print(f"Game {game_idx}: Waiting for advance buttons...")
            wait_for_advance_button(page1, timeout=30000)
            wait_for_advance_button(page2, timeout=30000)

            s1 = log_page_state(page1, f"Game{game_idx}-P1 before advance click")
            s2 = log_page_state(page2, f"Game{game_idx}-P2 before advance click")
            assert s1['advance_button_visible'], f"Game {game_idx} P1: Advance button not visible"
            assert s2['advance_button_visible'], f"Game {game_idx} P2: Advance button not visible"

            print(f"Game {game_idx}: Clicking advance buttons...")
            page1.locator("#advanceButton").click()
            page2.locator("#advanceButton").click()

            # Validate: advance button clicked, should now see start button
            time.sleep(0.5)  # Brief wait for scene transition
            s1 = log_page_state(page1, f"Game{game_idx}-P1 after advance click")
            s2 = log_page_state(page2, f"Game{game_idx}-P2 after advance click")

            # Step 4: Wait for start button to be enabled, then click
            print(f"Game {game_idx}: Waiting for start buttons to be enabled...")
            wait_for_start_button_enabled(page1, timeout=60000)
            wait_for_start_button_enabled(page2, timeout=60000)

            s1 = log_page_state(page1, f"Game{game_idx}-P1 before start click")
            s2 = log_page_state(page2, f"Game{game_idx}-P2 before start click")
            assert s1['start_button_visible'], f"Game {game_idx} P1: Start button not visible"
            assert s1['start_button_enabled'], f"Game {game_idx} P1: Start button not enabled"
            assert s2['start_button_visible'], f"Game {game_idx} P2: Start button not visible"
            assert s2['start_button_enabled'], f"Game {game_idx} P2: Start button not enabled"

            print(f"Game {game_idx}: Clicking start buttons...")
            page1.locator("#startButton").click()
            time.sleep(0.5)  # Wait for P1 to enter waitroom before P2 clicks
            page2.locator("#startButton").click()

            # Validate: start button clicked, should enter waitroom/matchmaking
            time.sleep(0.5)  # Brief wait for matchmaking to start
            s1 = log_page_state(page1, f"Game{game_idx}-P1 after start click")
            s2 = log_page_state(page2, f"Game{game_idx}-P2 after start click")

            # Check for errors
            if s1['error_text_visible']:
                raise AssertionError(f"Game {game_idx} P1: Error after start click: {s1['error_text_content']}")
            if s2['error_text_visible']:
                raise AssertionError(f"Game {game_idx} P2: Error after start click: {s2['error_text_content']}")

            # Step 5: Wait for game canvas
            print(f"Game {game_idx}: Waiting for game to start...")
            self._wait_for_pair_game_started(page1, page2, timeout=120000)

            # Validate: game started
            s1 = log_page_state(page1, f"Game{game_idx}-P1 after game start")
            s2 = log_page_state(page2, f"Game{game_idx}-P2 after game start")
            assert s1['game_canvas_visible'], f"Game {game_idx} P1: Canvas not visible"
            assert s1['game_object_exists'], f"Game {game_idx} P1: Game object not found"
            assert s2['game_canvas_visible'], f"Game {game_idx} P2: Canvas not visible"
            assert s2['game_object_exists'], f"Game {game_idx} P2: Game object not found"

            # Step 6: Verify pairing
            state1 = get_game_state(page1)
            state2 = get_game_state(page2)
            assert state1["gameId"] == state2["gameId"], (
                f"Game {game_idx}: Players not matched correctly. "
                f"Player 1 gameId={state1['gameId']}, Player 2 gameId={state2['gameId']}"
            )
            self.game_ids[game_idx] = state1["gameId"]
            print(f"Game {game_idx}: ✓ Started and verified, gameId={state1['gameId']}")

        print("\n=== All 3 games started and verified ===")

    def wait_for_all_episodes_complete(self, episode_num: int = 1, timeout: int = 180000) -> None:
        """
        Wait for all 6 participants to complete the specified episode.

        Args:
            episode_num: Episode number to wait for (1 = first episode complete)
            timeout: Timeout per participant in milliseconds
        """
        for game_idx, (page1, page2) in enumerate(self.games):
            wait_for_episode_complete(page1, episode_num=episode_num, timeout=timeout)
            wait_for_episode_complete(page2, episode_num=episode_num, timeout=timeout)
            print(f"Game {game_idx}: Episode {episode_num} complete")

    def collect_subject_ids(self) -> None:
        """
        Collect subject IDs from all games for export file lookup.

        Populates self.subject_ids with tuples of (subject1, subject2) per game.
        """
        for game_idx, (page1, page2) in enumerate(self.games):
            self.subject_ids[game_idx] = get_subject_ids_from_pages(page1, page2)

    def validate_all_data_parity(self, episode_num: int = 0, timeout_sec: int = 30) -> List[Tuple[int, str]]:
        """
        Validate data parity for all completed games.

        Args:
            episode_num: Episode number to validate (0-indexed: first episode = 0)
            timeout_sec: Timeout waiting for export files

        Returns:
            List of (exit_code, output) tuples for each game.
            exit_code 0 = parity verified, 1 = divergence found.
        """
        if not any(self.subject_ids):
            self.collect_subject_ids()

        experiment_id = get_experiment_id()
        scene_id = get_scene_id(self.pages[0])

        results = []

        for game_idx, subject_ids in enumerate(self.subject_ids):
            try:
                file1, file2 = wait_for_export_files(
                    experiment_id=experiment_id,
                    scene_id=scene_id,
                    subject_ids=subject_ids,
                    episode_num=episode_num,
                    timeout_sec=timeout_sec
                )
                exit_code, output = run_comparison(file1, file2, verbose=True)
                results.append((exit_code, output))

                if exit_code == 0:
                    print(f"Game {game_idx}: Data parity VERIFIED")
                else:
                    print(f"Game {game_idx}: Data parity FAILED - {output}")

            except TimeoutError as e:
                results.append((1, f"Export files not found: {e}"))
                print(f"Game {game_idx}: Export files not found")

        return results
