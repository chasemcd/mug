"""
Scene isolation test - validates Phase 77's P2P connection scoping.

Two players complete an Overcooked game, both advance to the survey scene,
one player exits (closes browser), and the remaining player does NOT see
a partner-disconnected overlay. The survey scene remains functional.

This is the capstone validation for v1.19 P2P Lifecycle Cleanup:
- Phase 77 added cleanupForSceneExit() and sceneExited guards
- When a GymScene ends and players advance to the next scene,
  terminateGymScene() calls cleanupForSceneExit() which sets
  sceneExited=true and closes WebRTC
- If the partner then disconnects, _handleReconnectionGameEnd checks
  sceneExited and returns early, never creating the overlay

Scene flow:
1. StartScene (instructions) - advanceButton
2. GymScene (multiplayer Overcooked, 1 episode, 450 steps) - startButton -> P2P game
3. ScalesAndTextBox (multiplayer feedback) - survey scene (isolation tested here)
4. CompletionCodeScene (end)
"""
from __future__ import annotations

import pytest

from tests.fixtures.export_helpers import (get_experiment_id,
                                           wait_for_episode_with_parity)
from tests.fixtures.game_helpers import (click_advance_button,
                                         click_start_button, get_scene_id,
                                         wait_for_episode_complete,
                                         wait_for_game_canvas,
                                         wait_for_game_object,
                                         wait_for_scene_header_contains,
                                         wait_for_socket_connected)
from tests.fixtures.network_helpers import set_tab_visibility


@pytest.mark.timeout(300)  # 5 minutes max for full flow
def test_partner_exit_on_survey_no_overlay(flask_server_scene_isolation, player_contexts):
    """
    Test that closing one player's browser on the survey scene does NOT
    trigger a partner-disconnected overlay on the remaining player.

    Validates all three Phase 79 success criteria:
    1. Two players complete an Overcooked game and advance to survey scene
    2. When one player closes their browser, no partner-disconnected overlay appears
    3. The remaining player's survey scene stays functional and interactive
    """
    page1, page2 = player_contexts
    base_url = flask_server_scene_isolation["url"]

    # ---- Step 1: Navigate both players to game ----
    page1.goto(base_url)
    page2.goto(base_url)

    # ---- Step 2: Wait for socket connections ----
    wait_for_socket_connected(page1, timeout=30000)
    wait_for_socket_connected(page2, timeout=30000)

    # ---- Step 3: Pass instructions scene (StartScene with advanceButton) ----
    click_advance_button(page1)
    click_advance_button(page2)

    # ---- Step 4: Start multiplayer GymScene ----
    click_start_button(page1)
    click_start_button(page2)

    # ---- Step 5: Wait for game to start (matchmaking + P2P connection) ----
    wait_for_game_canvas(page1, timeout=90000)
    wait_for_game_canvas(page2, timeout=90000)

    wait_for_game_object(page1)
    wait_for_game_object(page2)

    # Override visibility for Playwright automation
    # Without this, FocusManager thinks tab is backgrounded and skips frame processing
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)

    # ---- Step 6: Wait for episode completion ----
    # Players are idle, episode ends via time limit (~15s at 30fps with 450 steps)
    wait_for_episode_complete(page1, episode_num=1, timeout=180000)
    wait_for_episode_complete(page2, episode_num=1, timeout=180000)

    # ---- Step 6b: Validate data parity for the completed episode ----
    scene_id = get_scene_id(page1)
    success, parity_msg = wait_for_episode_with_parity(
        page1, page2,
        experiment_id="overcooked_multiplayer_hh_scene_isolation_test",
        scene_id=scene_id,
        episode_num=0,
        episode_timeout_sec=10,  # Episode already complete
        export_timeout_sec=30,
        parity_row_tolerance=0,
        verbose=True,
    )
    assert success, f"Episode parity validation failed: {parity_msg}"

    # ---- Step 7: Wait for both players to advance to survey scene ----
    # After episode completes, the game auto-advances.
    # The survey scene is multiplayer_feedback_scene (ScalesAndTextBox) with
    # scene_header="Multiplayer Feedback". Both players exiting the GymScene
    # triggers terminateGymScene() -> cleanupForSceneExit() which sets sceneExited=true.
    wait_for_scene_header_contains(page1, "Feedback", timeout=60000)
    wait_for_scene_header_contains(page2, "Feedback", timeout=60000)

    # ---- Step 8: Verify both players are on survey scene ----
    header1 = page1.evaluate(
        "() => document.getElementById('sceneHeader')?.innerText || ''"
    )
    header2 = page2.evaluate(
        "() => document.getElementById('sceneHeader')?.innerText || ''"
    )
    assert "Feedback" in header1, f"Player 1 should be on feedback scene, got: {header1}"
    assert "Feedback" in header2, f"Player 2 should be on feedback scene, got: {header2}"

    # Verify no partner-disconnected container exists on either page before disconnect
    # The overlay is created as #partnerDisconnectedContainer by _showPartnerDisconnectedOverlay()
    # We check both that the element exists AND is visible (offsetParent !== null)
    overlay1_before = page1.evaluate(
        "() => { const el = document.getElementById('partnerDisconnectedContainer'); return el !== null && el.offsetParent !== null; }"
    )
    overlay2_before = page2.evaluate(
        "() => { const el = document.getElementById('partnerDisconnectedContainer'); return el !== null && el.offsetParent !== null; }"
    )
    assert not overlay1_before, "No overlay should exist on page1 before disconnect"
    assert not overlay2_before, "No overlay should exist on page2 before disconnect"

    # ---- Step 9: Set up console listener on page1 before closing page2 ----
    # Capture console messages related to partner disconnect / sceneExited guard
    console_messages = []
    page1.on(
        "console",
        lambda msg: console_messages.append(msg.text)
        if any(
            kw in msg.text.lower()
            for kw in ["partner", "disconnected", "p2p_game_ended", "scene already exited"]
        )
        else None,
    )

    # ---- Step 10: Close player 2's browser context ----
    # This severs the socket connection for player 2, which would normally
    # trigger a partner-disconnected overlay on player 1 during gameplay.
    # With Phase 77's sceneExited guard, this should be suppressed.
    page2.context.close()

    # ---- Step 11: Wait and verify no overlay appears on player 1 ----
    # 5 seconds is enough time for any disconnect event to propagate
    page1.wait_for_timeout(5000)

    # Check 1: No partner-disconnected container visible
    # partnerDisconnectedContainer is created by _showPartnerDisconnectedOverlay() and
    # hides all other page content. If sceneExited guard works, it's never created.
    overlay1_after = page1.evaluate(
        "() => { const el = document.getElementById('partnerDisconnectedContainer'); return el !== null && el.offsetParent !== null; }"
    )
    assert not overlay1_after, (
        "Partner-disconnected overlay should NOT appear on player 1 after partner exits on survey scene"
    )

    # Check 2: Survey scene is still showing (header not replaced by overlay)
    header1_after = page1.evaluate(
        "() => document.getElementById('sceneHeader')?.innerText || ''"
    )
    assert "Feedback" in header1_after, (
        f"Survey scene should still be showing, got header: {header1_after}"
    )

    # Check 3: Survey form elements are still present and interactive
    form_visible = page1.evaluate("""() => {
        // Check for scale containers (survey questions) or advanceButton (submit)
        const scales = document.querySelector('.scale-container');
        const advanceBtn = document.getElementById('advanceButton');
        const sceneContent = document.querySelector('.scene-content');
        return !!(scales || advanceBtn || sceneContent);
    }""")
    assert form_visible, "Survey form elements should still be present and interactive"

    # ---- Step 12: Log console messages for debugging ----
    print(f"\nScene isolation test passed!")
    print(f"Console messages captured on page1 after partner exit:")
    for msg in console_messages:
        print(f"  - {msg}")

    # If sceneExited guard is working, we expect to see a message like
    # "Ignoring p2p_game_ended - scene already exited"
    # This is informational, not an assertion, since the message may not
    # always appear depending on timing (server may not send p2p_game_ended
    # if the game was already cleaned up server-side)
    scene_exit_guard_msgs = [
        m for m in console_messages if "scene already exited" in m.lower()
    ]
    if scene_exit_guard_msgs:
        print(f"\nsceneExited guard confirmed active ({len(scene_exit_guard_msgs)} messages)")
    else:
        print("\nNo sceneExited guard messages captured (server may have already cleaned up game)")
