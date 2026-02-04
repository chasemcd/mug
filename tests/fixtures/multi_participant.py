"""
Multi-participant test orchestration helpers.

Provides GameOrchestrator class for managing 3 concurrent 2-player games,
used by multi-participant stress tests (STRESS-01 through STRESS-07).
"""
import time
from typing import List, Tuple

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
)
from tests.fixtures.network_helpers import set_tab_visibility
from tests.fixtures.export_helpers import (
    get_experiment_id,
    get_subject_ids_from_pages,
    wait_for_export_files,
    run_comparison,
)


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
        self.game_ids: List[str] = [None, None, None]
        self.subject_ids: List[Tuple[str, str]] = [None, None, None]

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

    def start_all_games(self) -> None:
        """
        Run all games through the full startup flow.

        This is a convenience method that runs:
        1. navigate_all_staggered
        2. wait_for_all_sockets
        3. advance_all_through_instructions
        4. start_all_matchmaking
        5. wait_for_all_games_started
        6. verify_game_pairings
        """
        print("Starting 3 games with 6 participants...")

        self.navigate_all_staggered()
        self.wait_for_all_sockets()
        self.advance_all_through_instructions()
        self.start_all_matchmaking()
        self.wait_for_all_games_started()
        self.verify_game_pairings()

        print("All 3 games started and verified")

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
