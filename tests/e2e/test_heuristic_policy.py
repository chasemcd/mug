"""
E2E test for heuristic (Python code) policies running in Pyodide.

Verifies that a human+heuristic game:
1. Loads Pyodide and registers the heuristic policy code in the interpreter
2. Executes the heuristic each frame against the live env (AI partner acts)
3. Completes the episode without heuristic execution errors

Usage:
    pytest tests/e2e/test_heuristic_policy.py --headed -v
"""

from __future__ import annotations

import pytest

from tests.fixtures.game_helpers import (click_advance_button,
                                         click_start_button, get_game_state,
                                         wait_for_episode_complete,
                                         wait_for_game_canvas,
                                         wait_for_socket_connected)
from tests.fixtures.network_helpers import set_tab_visibility


@pytest.mark.e2e
def test_heuristic_policy_episode_completes(
    flask_server_slimevb_human_heuristic, single_player_context
):
    """
    Verify heuristic policy execution works end-to-end in Pyodide.

    Flow:
    1. Navigate to server
    2. Socket connects
    3. Advance through start scene
    4. Click start (waits for Pyodide load + env init)
    5. Game canvas appears, episode runs
    6. Episode completes (AI acts via the ball_chaser heuristic)
    7. Assert: episode completed, frames advanced, no heuristic errors
    """
    page = single_player_context
    base_url = flask_server_slimevb_human_heuristic["url"]

    # Collect console errors during the test
    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))

    # Navigate to server
    page.goto(base_url)

    # Wait for socket connection
    wait_for_socket_connected(page, timeout=15000)

    # Advance through start scene (instruction page)
    click_advance_button(page, timeout=30000)

    # Click start button — this triggers Pyodide bootstrap + env init
    click_start_button(page, timeout=120000)

    # Wait for game canvas to appear (game loop started)
    wait_for_game_canvas(page, timeout=120000)

    # Override tab visibility so FocusManager doesn't pause the game
    set_tab_visibility(page, visible=True)

    # Wait for the episode to complete
    # 200 steps at 30fps = ~7s, but Pyodide init can take 30-60s
    wait_for_episode_complete(page, episode_num=1, timeout=120000)

    # --- Assertions ---

    # 1. Episode completed
    state = get_game_state(page)
    assert state is not None, "Game state should be available"
    assert state["numEpisodes"] >= 1, (
        f"Expected at least 1 completed episode, got {state['numEpisodes']}"
    )

    # 2. Game had frames (game loop ran with the heuristic active)
    assert state["frameNumber"] > 0, (
        f"Expected frames to advance, got frameNumber={state['frameNumber']}"
    )

    # 3. No heuristic execution errors in the browser console
    heuristic_errors = [e for e in console_errors if any(
        keyword in e for keyword in [
            "Heuristic policy error", "actionFromHeuristic",
            "_mug_heuristic", "PythonError",
        ]
    )]
    assert not heuristic_errors, (
        "Heuristic policy errors detected in browser console:\n"
        + "\n".join(heuristic_errors)
    )

    # 4. No uncaught exceptions
    has_fatal_errors = page.evaluate("""() => {
        if (window._uncaughtErrors && window._uncaughtErrors.length > 0) {
            return window._uncaughtErrors;
        }
        return false;
    }""")
    assert not has_fatal_errors, (
        f"Fatal JS errors detected: {has_fatal_errors}"
    )
