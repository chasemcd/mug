"""
Export file collection and comparison helpers for E2E tests.

These helpers enable automated validation that both players export identical
game state data by:
1. Collecting export CSV files from both players after episode completion
2. Invoking the validate_action_sequences.py --compare script
3. Reporting pass/fail based on comparison exit code

Usage:
    # In a test
    subject_ids = get_subject_ids_from_pages(page1, page2)
    paths = wait_for_export_files(experiment_id, scene_id, subject_ids, episode_num=0)
    exit_code, output = run_comparison(paths[0], paths[1])
    assert exit_code == 0, f"Data parity failed: {output}"
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from playwright.sync_api import Page


def get_experiment_id(override: str | None = None) -> str:
    """
    Get the experiment ID for the current test environment.

    Returns the experiment ID used by the server, which determines the
    directory structure for export files.

    Args:
        override: Optional experiment ID to use instead of default.
                  Use this for non-standard test server configs.

    Returns:
        str: The experiment ID (e.g., "overcooked_multiplayer_hh_test")
    """
    if override:
        return override
    # Default experiment ID from the test server config (overcooked_human_human_multiplayer_test.py)
    return "overcooked_multiplayer_hh_test"


def get_subject_ids_from_pages(page1: Page, page2: Page) -> tuple:
    """
    Extract subject IDs from both players' game objects.

    Subject IDs are assigned by the server when players connect and are used
    in export filenames ({subject_id}_ep{episode_num}.csv).

    Args:
        page1: Playwright Page for player 1
        page2: Playwright Page for player 2

    Returns:
        tuple: (subject_id_1, subject_id_2) as strings

    Raises:
        ValueError: If subject IDs cannot be extracted from either page
    """
    # Try various locations where subject ID/name may be stored
    subject1 = page1.evaluate(
        "() => window.subjectName || window.interactiveGymGlobals?.subjectName || window.subjectId || null"
    )
    subject2 = page2.evaluate(
        "() => window.subjectName || window.interactiveGymGlobals?.subjectName || window.subjectId || null"
    )

    if not subject1:
        raise ValueError("Could not extract subject ID from player 1")
    if not subject2:
        raise ValueError("Could not extract subject ID from player 2")

    return (str(subject1), str(subject2))


def collect_export_files(
    experiment_id: str,
    scene_id: str,
    subject_ids: tuple,
    episode_num: int = 0
) -> tuple:
    """
    Construct paths to export CSV files for both players.

    Export files are written by the server to:
    data/{experiment_id}/{scene_id}/{subject_id}_ep{episode_num}.csv

    Args:
        experiment_id: The experiment identifier
        scene_id: The scene identifier (e.g., "cramped_room")
        subject_ids: Tuple of (subject_id_1, subject_id_2)
        episode_num: Episode number (0-indexed, i.e., first episode is 0)

    Returns:
        tuple: (Path to file 1, Path to file 2)

    Raises:
        FileNotFoundError: If either export file does not exist
    """
    data_dir = Path("data") / experiment_id / scene_id

    file1 = data_dir / f"{subject_ids[0]}_ep{episode_num}.csv"
    file2 = data_dir / f"{subject_ids[1]}_ep{episode_num}.csv"

    if not file1.exists():
        raise FileNotFoundError(f"Export file not found: {file1}")
    if not file2.exists():
        raise FileNotFoundError(f"Export file not found: {file2}")

    return (file1, file2)


def wait_for_export_files(
    experiment_id: str,
    scene_id: str,
    subject_ids: tuple,
    episode_num: int = 0,
    timeout_sec: int = 30
) -> tuple:
    """
    Wait for export files to be written by the server.

    The server writes export files after each episode completes. This function
    polls for the files to exist, which is necessary because file writing
    may happen asynchronously after the game reports episode completion.

    Args:
        experiment_id: The experiment identifier
        scene_id: The scene identifier
        subject_ids: Tuple of (subject_id_1, subject_id_2)
        episode_num: Episode number to wait for (0-indexed, first episode is 0)
        timeout_sec: Maximum seconds to wait (default 30)

    Returns:
        tuple: (Path to file 1, Path to file 2) once both exist

    Raises:
        TimeoutError: If files do not appear within timeout
    """
    data_dir = Path("data") / experiment_id / scene_id

    file1 = data_dir / f"{subject_ids[0]}_ep{episode_num}.csv"
    file2 = data_dir / f"{subject_ids[1]}_ep{episode_num}.csv"

    start_time = time.time()
    poll_interval = 0.5  # seconds

    while (time.time() - start_time) < timeout_sec:
        if file1.exists() and file2.exists():
            return (file1, file2)
        time.sleep(poll_interval)

    # Build helpful error message
    missing = []
    if not file1.exists():
        missing.append(str(file1))
    if not file2.exists():
        missing.append(str(file2))

    raise TimeoutError(
        f"Export files did not appear within {timeout_sec}s. "
        f"Missing: {', '.join(missing)}"
    )


def run_comparison(
    file1: Path, file2: Path, verbose: bool = False, row_tolerance: int = 0
) -> tuple:
    """
    Run the validate_action_sequences.py --compare script on two export files.

    This invokes the comparison script as a subprocess and captures its output.
    Exit code 0 means files are identical (within tolerance); exit code 1 means divergences found.

    Args:
        file1: Path to first export CSV file
        file2: Path to second export CSV file
        verbose: If True, add --verbose flag for detailed divergence info
        row_tolerance: Allow up to this many row count differences (default 0, strict)

    Returns:
        tuple: (exit_code, output_text)
            exit_code: 0 if files identical (within tolerance), 1 if divergences found
            output_text: Combined stdout and stderr from the script
    """
    cmd = [
        "python",
        "scripts/validate_action_sequences.py",
        "--compare",
        str(file1),
        str(file2),
        "--row-tolerance",
        str(row_tolerance),
    ]

    if verbose:
        cmd.append("--verbose")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    output = result.stdout
    if result.stderr:
        output += "\n" + result.stderr

    return (result.returncode, output.strip())


def wait_for_episode_with_parity(
    page1,
    page2,
    experiment_id: str,
    scene_id: str,
    episode_num: int = 0,
    episode_timeout_sec: int = 180,
    export_timeout_sec: int = 30,
    parity_row_tolerance: int = 0,
    verbose: bool = True,
) -> tuple:
    """
    Wait for episode completion AND validate data export parity.

    This is the primary method for validating episode completion in multi-participant
    tests. It combines two validations:
    1. Wait for both players' game objects to report episode completion (num_episodes >= N)
    2. Wait for both export files to exist and verify they are identical

    Using data export parity as the source of truth ensures that both players
    processed the same game state, which is the definitive test for correct
    P2P synchronization.

    Args:
        page1: Playwright Page for player 1
        page2: Playwright Page for player 2
        experiment_id: The experiment identifier (e.g., "overcooked_multiplayer_hh_test")
        scene_id: The scene identifier (e.g., "cramped_room")
        episode_num: Episode number to validate (0-indexed: first episode = 0)
        episode_timeout_sec: Max seconds to wait for num_episodes increment
        export_timeout_sec: Max seconds to wait for export files
        parity_row_tolerance: Allow up to N row count differences (default 0, strict)
        verbose: If True, print progress and comparison details

    Returns:
        tuple: (success, message)
            success: True if episode completed with valid parity, False otherwise
            message: Description of result or error

    Raises:
        TimeoutError: If episode doesn't complete or export files don't appear
        AssertionError: If data parity validation fails
    """
    from playwright.sync_api import Page

    # The num_episodes counter we wait for (1-indexed: first episode complete = 1)
    target_episode_count = episode_num + 1

    if verbose:
        print(f"[Parity] Waiting for episode {episode_num + 1} to complete...")

    # Step 1: Wait for both players to complete episode (num_episodes >= target)
    try:
        page1.wait_for_function(
            f"() => window.game && window.game.num_episodes >= {target_episode_count}",
            timeout=episode_timeout_sec * 1000
        )
        if verbose:
            print(f"[Parity] Player 1: Episode {episode_num + 1} complete")
    except Exception as e:
        return (False, f"Player 1 episode completion timeout: {e}")

    try:
        page2.wait_for_function(
            f"() => window.game && window.game.num_episodes >= {target_episode_count}",
            timeout=episode_timeout_sec * 1000
        )
        if verbose:
            print(f"[Parity] Player 2: Episode {episode_num + 1} complete")
    except Exception as e:
        return (False, f"Player 2 episode completion timeout: {e}")

    # Step 2: Get subject IDs for export file lookup
    try:
        subject_ids = get_subject_ids_from_pages(page1, page2)
        if verbose:
            print(f"[Parity] Subject IDs: {subject_ids}")
    except ValueError as e:
        return (False, f"Failed to get subject IDs: {e}")

    # Step 3: Wait for export files to exist
    try:
        file1, file2 = wait_for_export_files(
            experiment_id=experiment_id,
            scene_id=scene_id,
            subject_ids=subject_ids,
            episode_num=episode_num,
            timeout_sec=export_timeout_sec
        )
        if verbose:
            print(f"[Parity] Export files found: {file1.name}, {file2.name}")
    except TimeoutError as e:
        return (False, f"Export files not found: {e}")

    # Step 4: Validate data parity
    exit_code, output = run_comparison(
        file1, file2, verbose=verbose, row_tolerance=parity_row_tolerance
    )

    if exit_code == 0:
        if verbose:
            print(f"[Parity] ✓ Episode {episode_num + 1} PARITY VERIFIED")
        return (True, f"Episode {episode_num + 1} complete with verified parity")
    else:
        if verbose:
            print(f"[Parity] ✗ Episode {episode_num + 1} PARITY FAILED:\n{output}")
        return (False, f"Data parity failed: {output}")
