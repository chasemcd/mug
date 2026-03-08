"""
E2E tests for Slime Volleyball (human-AI and human-human).

Verifies that:
1. Pyodide loads slimevb==0.1.1 and the environment initializes
2. ONNX inference works with the new model format (input/logits)
3. Episodes complete without fatal JS errors
4. Data is exported correctly

Usage:
    pytest tests/e2e/test_slimevb.py --headed -v
"""

from __future__ import annotations

import glob
import os

import pytest

from tests.fixtures.game_helpers import (click_advance_button,
                                         click_start_button, get_game_state,
                                         wait_for_episode_complete,
                                         wait_for_game_canvas,
                                         wait_for_socket_connected)
from tests.fixtures.network_helpers import set_tab_visibility


@pytest.mark.e2e
def test_slimevb_human_ai_episode_completes(
    flask_server_slimevb_human_ai, single_player_context
):
    """
    Verify slime volleyball human-AI game completes an episode.

    Flow:
    1. Navigate to server
    2. Advance through start scene
    3. Click start (Pyodide + ONNX model load)
    4. Game runs with AI taking actions via ONNX inference
    5. Episode completes
    6. Assert: episode completed, frames advanced, no errors
    """
    page = single_player_context
    base_url = flask_server_slimevb_human_ai["url"]

    # Collect console errors
    console_errors = []
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text)
        if msg.type == "error"
        else None,
    )
    page.on("pageerror", lambda exc: console_errors.append(str(exc)))

    # Navigate
    page.goto(base_url)
    wait_for_socket_connected(page, timeout=15000)

    # Advance through start scene
    click_advance_button(page, timeout=30000)

    # Click start — triggers Pyodide + ONNX model loading
    click_start_button(page, timeout=120000)

    # Wait for game canvas
    wait_for_game_canvas(page, timeout=120000)
    set_tab_visibility(page, visible=True)

    # Wait for episode to complete
    wait_for_episode_complete(page, episode_num=1, timeout=120000)

    # --- Assertions ---

    # 1. Episode completed
    state = get_game_state(page)
    assert state is not None, "Game state should be available"
    assert state["numEpisodes"] >= 1, (
        f"Expected at least 1 completed episode, got {state['numEpisodes']}"
    )

    # 2. Frames advanced
    assert state["frameNumber"] > 0, (
        f"Expected frames to advance, got frameNumber={state['frameNumber']}"
    )

    # 3. No ONNX/Pyodide errors
    critical_errors = [
        e
        for e in console_errors
        if any(
            kw in e
            for kw in [
                "RangeError",
                "Float32Array",
                "inferenceONNXPolicy",
                "actionFromONNX",
                "onnx",
                "PythonError",
                "AttributeError",
            ]
        )
    ]
    assert not critical_errors, (
        f"Critical errors in console:\n" + "\n".join(critical_errors)
    )


@pytest.mark.e2e
def test_slimevb_human_ai_exports_data(
    flask_server_slimevb_human_ai, single_player_context
):
    """
    Verify slime volleyball human-AI game exports data after episode completion.
    """
    page = single_player_context
    base_url = flask_server_slimevb_human_ai["url"]

    page.goto(base_url)
    wait_for_socket_connected(page, timeout=15000)
    click_advance_button(page, timeout=30000)
    click_start_button(page, timeout=120000)
    wait_for_game_canvas(page, timeout=120000)
    set_tab_visibility(page, visible=True)
    wait_for_episode_complete(page, episode_num=1, timeout=120000)

    # Advance through end scene to trigger export
    click_advance_button(page, timeout=30000)

    # Check data export
    export_dir = "data/slimevb_human_ai_test/slime_gym_scene"
    # Wait briefly for file system writes
    page.wait_for_timeout(2000)

    csv_files = glob.glob(os.path.join(export_dir, "*.csv"))
    assert len(csv_files) > 0, (
        f"Expected exported CSV files in {export_dir}, found none"
    )


@pytest.mark.e2e
def test_slimevb_human_human_episode_completes(
    flask_server_slimevb_human_human, player_contexts
):
    """
    Verify slime volleyball human-human multiplayer game completes an episode.

    Flow:
    1. Both players navigate and connect
    2. Both advance through start scene
    3. Both click start (Pyodide loads, P2P connects)
    4. Game runs with both players
    5. Episode completes for both
    """
    page1, page2 = player_contexts
    base_url = flask_server_slimevb_human_human["url"]

    # Collect errors from both pages
    console_errors = []
    for p in [page1, page2]:
        p.on(
            "console",
            lambda msg: console_errors.append(msg.text)
            if msg.type == "error"
            else None,
        )
        p.on("pageerror", lambda exc: console_errors.append(str(exc)))

    # Both navigate
    page1.goto(base_url)
    page2.goto(base_url)

    wait_for_socket_connected(page1, timeout=15000)
    wait_for_socket_connected(page2, timeout=15000)

    # Both advance through start scene
    click_advance_button(page1, timeout=30000)
    click_advance_button(page2, timeout=30000)

    # Both click start
    click_start_button(page1, timeout=120000)
    click_start_button(page2, timeout=120000)

    # Wait for canvas on both
    wait_for_game_canvas(page1, timeout=120000)
    wait_for_game_canvas(page2, timeout=120000)

    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)

    # Wait for episode on both players
    wait_for_episode_complete(page1, episode_num=1, timeout=180000)
    wait_for_episode_complete(page2, episode_num=1, timeout=180000)

    # --- Assertions ---
    for i, page in enumerate([page1, page2], 1):
        state = get_game_state(page)
        assert state is not None, f"Player {i}: game state should be available"
        assert state["numEpisodes"] >= 1, (
            f"Player {i}: expected at least 1 completed episode"
        )
        assert state["frameNumber"] > 0, (
            f"Player {i}: expected frames to advance"
        )

    # No critical errors
    critical_errors = [
        e
        for e in console_errors
        if any(
            kw in e
            for kw in [
                "PythonError",
                "AttributeError",
                "RangeError",
                "TypeError",
            ]
        )
    ]
    assert not critical_errors, (
        f"Critical errors in console:\n" + "\n".join(critical_errors)
    )
