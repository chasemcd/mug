"""
E2E test for ONNX inference via the declarative ModelConfig path.

Verifies that a human+AI game with an ONNX model:
1. Loads Pyodide and the ONNX model in the browser
2. Runs inference each frame (AI partner takes actions)
3. Completes the episode without fatal JS errors

This exercises the Phase 89 ModelConfig declarative path end-to-end.

Usage:
    pytest tests/e2e/test_onnx_inference.py --headed -v
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
def test_onnx_inference_episode_completes(
    flask_server_human_ai, single_player_context
):
    """
    Verify ONNX inference works end-to-end with ModelConfig.

    Flow:
    1. Navigate to server
    2. Socket connects
    3. Advance through start scene
    4. Click start (waits for Pyodide + ONNX model load)
    5. Game canvas appears, episode runs
    6. Episode completes (AI takes actions via ONNX inference)
    7. Assert: episode completed, frames advanced, no fatal JS errors
    """
    page = single_player_context
    base_url = flask_server_human_ai["url"]

    # Navigate to server
    page.goto(base_url)

    # Wait for socket connection
    wait_for_socket_connected(page, timeout=15000)

    # Advance through start scene (instruction page)
    click_advance_button(page, timeout=30000)

    # Click start button — this triggers Pyodide + ONNX model loading
    # Give extra time for Pyodide bootstrap + ONNX runtime init
    click_start_button(page, timeout=120000)

    # Wait for game canvas to appear (game loop started)
    wait_for_game_canvas(page, timeout=120000)

    # Override tab visibility so FocusManager doesn't pause the game
    set_tab_visibility(page, visible=True)

    # Wait for the episode to complete
    # 200 steps at 30fps = ~7s, but Pyodide init can take 30-60s
    # Use generous timeout to account for first-time ONNX model load
    wait_for_episode_complete(page, episode_num=1, timeout=120000)

    # --- Assertions ---

    # 1. Episode completed
    state = get_game_state(page)
    assert state is not None, "Game state should be available"
    assert state["numEpisodes"] >= 1, (
        f"Expected at least 1 completed episode, got {state['numEpisodes']}"
    )

    # 2. Game had frames (game loop ran with ONNX inference active)
    assert state["frameNumber"] > 0, (
        f"Expected frames to advance, got frameNumber={state['frameNumber']}"
    )

    # 3. No fatal JS console errors
    # Check for errors that would indicate ONNX load failure or inference crash
    has_fatal_errors = page.evaluate("""() => {
        // Check if there were any uncaught errors stored by the game
        if (window._uncaughtErrors && window._uncaughtErrors.length > 0) {
            return window._uncaughtErrors;
        }
        return false;
    }""")
    assert not has_fatal_errors, (
        f"Fatal JS errors detected: {has_fatal_errors}"
    )
