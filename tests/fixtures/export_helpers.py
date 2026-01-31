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
    paths = wait_for_export_files(experiment_id, scene_id, subject_ids, episode_num=1)
    exit_code, output = run_comparison(paths[0], paths[1])
    assert exit_code == 0, f"Data parity failed: {output}"
"""
import subprocess
import time
from pathlib import Path

from playwright.sync_api import Page


def get_experiment_id() -> str:
    """
    Get the experiment ID for the current test environment.

    Returns the experiment ID used by the server, which determines the
    directory structure for export files.

    Returns:
        str: The experiment ID (e.g., "overcooked_human_human_multiplayer")
    """
    # Default experiment ID from the example multiplayer server
    return "overcooked_human_human_multiplayer"


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
    # Try window.subjectId first (set by index.js), fall back to game object
    subject1 = page1.evaluate(
        "() => window.subjectId || window.game?.subjectId || null"
    )
    subject2 = page2.evaluate(
        "() => window.subjectId || window.game?.subjectId || null"
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
    episode_num: int = 1
) -> tuple:
    """
    Construct paths to export CSV files for both players.

    Export files are written by the server to:
    data/{experiment_id}/{scene_id}/{subject_id}_ep{episode_num}.csv

    Args:
        experiment_id: The experiment identifier
        scene_id: The scene identifier (e.g., "cramped_room")
        subject_ids: Tuple of (subject_id_1, subject_id_2)
        episode_num: Episode number (1-indexed)

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
    episode_num: int = 1,
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
        episode_num: Episode number to wait for
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


def run_comparison(file1: Path, file2: Path, verbose: bool = False) -> tuple:
    """
    Run the validate_action_sequences.py --compare script on two export files.

    This invokes the comparison script as a subprocess and captures its output.
    Exit code 0 means files are identical; exit code 1 means divergences found.

    Args:
        file1: Path to first export CSV file
        file2: Path to second export CSV file
        verbose: If True, add --verbose flag for detailed divergence info

    Returns:
        tuple: (exit_code, output_text)
            exit_code: 0 if files identical, 1 if divergences found
            output_text: Combined stdout and stderr from the script
    """
    cmd = [
        "python",
        "scripts/validate_action_sequences.py",
        "--compare",
        str(file1),
        str(file2),
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
