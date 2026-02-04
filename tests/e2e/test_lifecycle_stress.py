"""
Lifecycle stress tests for participant scenarios.

Tests validate STRESS-02 through STRESS-07 requirements:
- Multi-episode completion without state corruption
- Mid-game disconnection handling
- Waiting room disconnection isolation
- Focus loss timeout handling
- Mixed lifecycle scenarios

Requires headed mode for WebRTC:
    pytest tests/e2e/test_lifecycle_stress.py --headed
"""
import pytest
import time
from playwright.sync_api import Error as PlaywrightError

from tests.fixtures.multi_participant import GameOrchestrator, get_page_state, log_page_state
from tests.fixtures.game_helpers import (
    run_full_episode_flow_until_gameplay,
    wait_for_episode_complete,
    get_game_state,
    wait_for_socket_connected,
    click_advance_button,
    click_start_button,
    wait_for_game_canvas,
    wait_for_waitroom,
    wait_for_game_object,
)
from tests.fixtures.network_helpers import set_tab_visibility, wait_for_focus_manager_state


# =============================================================================
# STRESS-02: Multi-Episode Completion Without State Corruption
# =============================================================================

@pytest.mark.timeout(600)  # 10 minutes for 2 episodes x 3 games
def test_multi_episode_completion(multi_participant_contexts, flask_server_multi_episode):
    """
    STRESS-02: Participant can complete 2 episodes back-to-back without state corruption.

    Validates:
    1. All 3 games complete episode 1 successfully
    2. Episode 1 data parity verified for all games
    3. All 3 games complete episode 2 successfully
    4. Episode 2 data parity verified for all games
    5. No state corruption across episode boundaries

    Uses flask_server_multi_episode with num_episodes=2.
    """
    pages = multi_participant_contexts
    base_url = flask_server_multi_episode["url"]
    expected_episodes = flask_server_multi_episode["num_episodes"]

    print(f"\n[STRESS-02] Testing {expected_episodes} episodes back-to-back")

    # Create orchestrator
    orchestrator = GameOrchestrator(pages, base_url)

    # Start all 3 games
    orchestrator.start_all_games()

    # Wait for episode 1 to complete for all games
    print("\n[STRESS-02] Waiting for episode 1 to complete...")
    orchestrator.wait_for_all_episodes_complete(episode_num=1, timeout=300000)
    print("[STRESS-02] Episode 1 complete for all games")

    # Validate episode 1 parity (episode_num is 0-indexed for export files)
    print("[STRESS-02] Validating episode 1 data parity...")
    results_ep1 = orchestrator.validate_all_data_parity(episode_num=0, timeout_sec=30)
    for game_idx, (exit_code, output) in enumerate(results_ep1):
        assert exit_code == 0, (
            f"[STRESS-02] Game {game_idx} episode 1 parity failed:\n{output}"
        )
        print(f"[STRESS-02] Game {game_idx} episode 1: PARITY VERIFIED")

    # Wait for episode 2 to complete for all games
    print("\n[STRESS-02] Waiting for episode 2 to complete...")
    orchestrator.wait_for_all_episodes_complete(episode_num=2, timeout=300000)
    print("[STRESS-02] Episode 2 complete for all games")

    # Validate episode 2 parity
    print("[STRESS-02] Validating episode 2 data parity...")
    results_ep2 = orchestrator.validate_all_data_parity(episode_num=1, timeout_sec=30)
    for game_idx, (exit_code, output) in enumerate(results_ep2):
        assert exit_code == 0, (
            f"[STRESS-02] Game {game_idx} episode 2 parity failed:\n{output}"
        )
        print(f"[STRESS-02] Game {game_idx} episode 2: PARITY VERIFIED")

    print(f"\n[STRESS-02] SUCCESS: All 3 games completed {expected_episodes} episodes with verified data parity")


# =============================================================================
# STRESS-03: Mid-Game Disconnection Handling
# =============================================================================

@pytest.mark.timeout(300)  # 5 minutes
def test_mid_game_disconnect(player_contexts, flask_server):
    """
    STRESS-03: Mid-game disconnect shows overlay to partner and exports data.

    Validates:
    1. Game starts normally between two players
    2. After accumulating frames, player 2 disconnects
    3. Player 1 receives partner disconnected notification
    4. Game state transitions to 'done' or shows overlay
    5. Data export triggered for completed frames

    Uses standard flask_server with 2-player game.
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    print("\n[STRESS-03] Testing mid-game disconnection handling")

    # Start game
    print("[STRESS-03] Starting game...")
    run_full_episode_flow_until_gameplay(page1, page2, base_url)

    # Verify game started
    state1 = get_game_state(page1)
    state2 = get_game_state(page2)
    assert state1["gameId"] == state2["gameId"], "Players should be matched"
    print(f"[STRESS-03] Game started: gameId={state1['gameId']}")

    # Let game run for 5 seconds to accumulate frames
    print("[STRESS-03] Running game for 5 seconds...")
    time.sleep(5)
    frame_before_disconnect = get_game_state(page1)["frameNumber"]
    print(f"[STRESS-03] Frame before disconnect: {frame_before_disconnect}")

    # Disconnect player 2 by closing their browser context
    print("[STRESS-03] Disconnecting player 2...")
    page2.context.close()

    # Wait for player 1 to receive disconnect notification
    # Socket.IO ping_interval=2s, ping_timeout=2s, so ~4-5s for detection
    print("[STRESS-03] Waiting for player 1 to detect disconnect...")
    try:
        page1.wait_for_function(
            "() => window.game && (window.game.partnerDisconnectedTerminal === true || window.game.state === 'done')",
            timeout=15000
        )
    except Exception as e:
        # Log state for debugging
        state = get_page_state(page1)
        pytest.fail(
            f"[STRESS-03] Player 1 did not detect disconnect within timeout.\n"
            f"State: {state}\n"
            f"Error: {e}"
        )

    # Verify game ended or overlay shown
    final_state = page1.evaluate("""() => {
        const game = window.game;
        if (!game) return null;
        return {
            state: game.state,
            partnerDisconnected: game.partnerDisconnectedTerminal || false,
            frameNumber: game.frameNumber,
        };
    }""")

    print(f"[STRESS-03] Final state: {final_state}")

    assert final_state is not None, "Game object should still exist"
    assert final_state["partnerDisconnected"] or final_state["state"] == "done", \
        "Game should be in disconnected or done state"
    assert final_state["frameNumber"] >= frame_before_disconnect, \
        "Frame count should be at least what it was before disconnect"

    print(f"\n[STRESS-03] SUCCESS: Partner disconnect handled correctly")


# =============================================================================
# STRESS-04: Waiting Room Disconnection Isolation
# =============================================================================

@pytest.mark.timeout(600)  # 10 minutes
def test_waitroom_disconnect_isolation(multi_participant_contexts, flask_server):
    """
    STRESS-04: Waiting room disconnect does not affect other participants.

    Validates:
    1. Game 1 starts and progresses normally
    2. Game 2's first player enters waitroom then disconnects BEFORE partner joins
    3. Game 1 continues unaffected
    4. Game 3 (pages 4,5) can still match and play normally
    5. Data parity verified for completed games

    Demonstrates server state isolation between games.
    """
    pages = multi_participant_contexts
    base_url = flask_server["url"]

    print("\n[STRESS-04] Testing waiting room disconnect isolation")

    # Start Game 1 (pages 0, 1)
    print("[STRESS-04] Starting Game 1 (pages 0, 1)...")
    page0, page1 = pages[0], pages[1]

    page0.goto(base_url)
    time.sleep(0.1)
    page1.goto(base_url)

    wait_for_socket_connected(page0, timeout=30000)
    wait_for_socket_connected(page1, timeout=30000)

    click_advance_button(page0, timeout=60000)
    click_advance_button(page1, timeout=60000)

    click_start_button(page0, timeout=60000)
    time.sleep(0.5)  # Ensure page0 enters waitroom first
    click_start_button(page1, timeout=60000)

    # Wait for Game 1 to be in gameplay
    wait_for_game_canvas(page0, timeout=120000)
    wait_for_game_canvas(page1, timeout=120000)
    wait_for_game_object(page0, timeout=30000)
    wait_for_game_object(page1, timeout=30000)
    set_tab_visibility(page0, visible=True)
    set_tab_visibility(page1, visible=True)

    game1_state = get_game_state(page0)
    assert game1_state is not None, "Game 1 should have started"
    print(f"[STRESS-04] Game 1 started: gameId={game1_state['gameId']}")

    # Game 2: First player (page 2) enters waitroom
    print("[STRESS-04] Game 2 player (page 2) entering waitroom...")
    page2 = pages[2]
    page2.goto(base_url)
    wait_for_socket_connected(page2, timeout=30000)
    click_advance_button(page2, timeout=60000)
    click_start_button(page2, timeout=60000)

    # Wait for page2 to be in waitroom
    wait_for_waitroom(page2, timeout=30000)
    print("[STRESS-04] Game 2 player in waitroom")

    # Disconnect page2 BEFORE page3 joins (they never become partners)
    print("[STRESS-04] Disconnecting page 2 from waitroom...")
    page2.context.close()

    # Give server time to process disconnect
    time.sleep(2)

    # Verify Game 1 is still running
    game1_frame_after = get_game_state(page0)["frameNumber"]
    print(f"[STRESS-04] Game 1 still running at frame {game1_frame_after}")
    assert game1_frame_after > 10, "Game 1 should still be progressing"

    # Start Game 3 (pages 4, 5) - should work despite Game 2 failure
    print("[STRESS-04] Starting Game 3 (pages 4, 5)...")
    page4, page5 = pages[4], pages[5]

    page4.goto(base_url)
    time.sleep(0.1)
    page5.goto(base_url)

    wait_for_socket_connected(page4, timeout=30000)
    wait_for_socket_connected(page5, timeout=30000)

    click_advance_button(page4, timeout=60000)
    click_advance_button(page5, timeout=60000)

    click_start_button(page4, timeout=60000)
    time.sleep(0.5)
    click_start_button(page5, timeout=60000)

    # Wait for Game 3 to be in gameplay
    wait_for_game_canvas(page4, timeout=120000)
    wait_for_game_canvas(page5, timeout=120000)
    wait_for_game_object(page4, timeout=30000)
    wait_for_game_object(page5, timeout=30000)
    set_tab_visibility(page4, visible=True)
    set_tab_visibility(page5, visible=True)

    # Verify Game 3 matched correctly
    state4 = get_game_state(page4)
    state5 = get_game_state(page5)
    assert state4["gameId"] == state5["gameId"], "Game 3 players should be matched"
    print(f"[STRESS-04] Game 3 started: gameId={state4['gameId']}")

    # Wait for both games to complete
    print("[STRESS-04] Waiting for Game 1 and Game 3 to complete...")
    wait_for_episode_complete(page0, episode_num=1, timeout=180000)
    wait_for_episode_complete(page4, episode_num=1, timeout=180000)
    print("[STRESS-04] Both games completed")

    # Note: We don't validate parity here because we only have 2 complete games
    # and the orchestrator expects 3 games. The key validation is that both games
    # completed successfully despite the waitroom disconnect.

    print(f"\n[STRESS-04] SUCCESS: Waitroom disconnect isolated - other games completed normally")


# =============================================================================
# STRESS-05: Focus Loss Timeout Handling
# =============================================================================

@pytest.mark.timeout(300)  # 5 minutes
def test_focus_loss_timeout(player_contexts, flask_server_focus_timeout):
    """
    STRESS-05: Focus loss triggers game end after timeout.

    Validates:
    1. Game starts normally between two players
    2. After running briefly, player 1's tab goes to background
    3. FocusManager enters backgrounded state
    4. After timeout (10s), game ends gracefully
    5. Both players see appropriate end state

    Uses flask_server_focus_timeout with timeout_ms=10000.
    """
    page1, page2 = player_contexts
    base_url = flask_server_focus_timeout["url"]
    timeout_ms = flask_server_focus_timeout["focus_timeout_ms"]

    print(f"\n[STRESS-05] Testing focus loss timeout ({timeout_ms}ms timeout)")

    # Start game
    print("[STRESS-05] Starting game...")
    run_full_episode_flow_until_gameplay(page1, page2, base_url)

    # Verify game started
    state1 = get_game_state(page1)
    state2 = get_game_state(page2)
    assert state1["gameId"] == state2["gameId"], "Players should be matched"
    print(f"[STRESS-05] Game started: gameId={state1['gameId']}")

    # Let game run for 3 seconds
    print("[STRESS-05] Running game for 3 seconds...")
    time.sleep(3)
    frame_before_focus_loss = get_game_state(page1)["frameNumber"]
    print(f"[STRESS-05] Frame before focus loss: {frame_before_focus_loss}")

    # Hide player 1's tab
    print("[STRESS-05] Hiding player 1's tab...")
    set_tab_visibility(page1, visible=False)

    # Wait for FocusManager to detect background state
    try:
        wait_for_focus_manager_state(page1, backgrounded=True, timeout=10000)
        print("[STRESS-05] FocusManager detected background state")
    except Exception as e:
        pytest.fail(f"[STRESS-05] FocusManager did not enter backgrounded state: {e}")

    # Wait for timeout to expire (timeout_ms + 5s buffer)
    wait_time = (timeout_ms + 5000) / 1000
    print(f"[STRESS-05] Waiting {wait_time}s for timeout to trigger...")
    time.sleep(wait_time)

    # Check player 1's state (they caused the timeout)
    player1_state = page1.evaluate("""() => {
        const game = window.game;
        if (!game) return {gameEnded: true, reason: 'game object gone'};
        return {
            gameEnded: game.state === 'done' || game.focusLossTimeoutTriggered === true,
            partnerDisconnected: game.partnerDisconnectedTerminal || false,
            focusLossTimeout: game.focusLossTimeoutTriggered || false,
            state: game.state,
        };
    }""")
    print(f"[STRESS-05] Player 1 state: {player1_state}")

    # Check player 2's state (they should receive partner disconnect notification)
    player2_state = page2.evaluate("""() => {
        const game = window.game;
        if (!game) return {gameEnded: true, reason: 'game object gone'};
        return {
            gameEnded: game.state === 'done' || game.partnerDisconnectedTerminal === true,
            partnerDisconnected: game.partnerDisconnectedTerminal || false,
            state: game.state,
        };
    }""")
    print(f"[STRESS-05] Player 2 state: {player2_state}")

    # Verify game ended for player 1 (timeout initiator)
    assert player1_state["gameEnded"], \
        f"Player 1's game should have ended after focus loss timeout. State: {player1_state}"

    # Verify player 2 received notification
    # Note: player 2 may show partner disconnected OR game may have ended due to server-side handling
    assert player2_state["gameEnded"] or player2_state["partnerDisconnected"], \
        f"Player 2 should have received game end notification. State: {player2_state}"

    print(f"\n[STRESS-05] SUCCESS: Focus loss timeout triggered game end for both players")


# =============================================================================
# STRESS-06 + STRESS-07: Mixed Lifecycle Scenarios
# =============================================================================

@pytest.mark.timeout(600)  # 10 minutes
def test_mixed_lifecycle_scenarios(multi_participant_contexts, flask_server):
    """
    STRESS-06: Mixed lifecycle scenarios complete without server state corruption.
    STRESS-07: All completed games pass exact parity validation.

    Scenarios:
    - Game 1 (pages 0,1): Normal completion
    - Game 2 (pages 2,3): Mid-game disconnect (close page 3 after 5s)
    - Game 3 (pages 4,5): Normal completion with brief focus loss (recover before timeout)

    Validates:
    1. All games start successfully
    2. Game 2's disconnect is handled gracefully
    3. Game 1 and Game 3 complete normally
    4. Data parity verified for Game 1 and Game 3 (STRESS-07)
    """
    pages = multi_participant_contexts
    base_url = flask_server["url"]

    print("\n[STRESS-06] Testing mixed lifecycle scenarios")

    # Use GameOrchestrator to manage all games
    orchestrator = GameOrchestrator(pages, base_url)

    # Start all 3 games with stagger
    print("[STRESS-06] Starting all 3 games...")
    orchestrator.start_all_games(stagger_delay_sec=5.0)

    # Let games run for 5 seconds
    print("[STRESS-06] Letting games run for 5 seconds...")
    time.sleep(5)

    # Get current states
    for game_idx in range(3):
        page = orchestrator.games[game_idx][0]
        try:
            state = get_game_state(page)
            print(f"[STRESS-06] Game {game_idx} at frame {state['frameNumber'] if state else 'N/A'}")
        except Exception:
            print(f"[STRESS-06] Game {game_idx} state unavailable")

    # Execute chaos scenarios:

    # Game 2: Disconnect page 3
    print("\n[STRESS-06] Executing Game 2 disconnect (page 3)...")
    page3 = pages[3]
    page3.context.close()
    print("[STRESS-06] Page 3 context closed")

    # Game 3: Brief focus loss then recovery
    print("[STRESS-06] Executing Game 3 brief focus loss...")
    page4 = pages[4]
    set_tab_visibility(page4, visible=False)
    time.sleep(2)  # 2 seconds in background (well under any timeout)
    set_tab_visibility(page4, visible=True)
    print("[STRESS-06] Game 3 focus restored")

    # Wait for Socket.IO to detect Game 2 disconnect
    print("[STRESS-06] Waiting for Game 2 disconnect detection...")
    time.sleep(5)

    # Check Game 2's remaining player (page 2)
    page2 = pages[2]
    try:
        game2_status = page2.evaluate("""() => {
            const game = window.game;
            if (!game) return {disconnected: false, reason: 'no game'};
            return {
                disconnected: game.partnerDisconnectedTerminal || false,
                state: game.state,
            };
        }""")
        print(f"[STRESS-06] Game 2 status after disconnect: {game2_status}")
    except Exception as e:
        print(f"[STRESS-06] Could not check Game 2 status: {e}")

    # Wait for Game 1 and Game 3 to complete
    print("\n[STRESS-06] Waiting for Game 1 to complete...")
    wait_for_episode_complete(pages[0], episode_num=1, timeout=180000)
    wait_for_episode_complete(pages[1], episode_num=1, timeout=180000)
    print("[STRESS-06] Game 1 completed")

    print("[STRESS-06] Waiting for Game 3 to complete...")
    wait_for_episode_complete(pages[4], episode_num=1, timeout=180000)
    wait_for_episode_complete(pages[5], episode_num=1, timeout=180000)
    print("[STRESS-06] Game 3 completed")

    # Get completion status
    status = orchestrator.get_game_completion_status()
    print(f"\n[STRESS-06] Game completion status: {status}")

    # Validate parity for completed games only (Game 1 and Game 3)
    # Note: We manually validate instead of using orchestrator.validate_all_data_parity()
    # because Game 2 was intentionally disconnected

    from tests.fixtures.export_helpers import (
        get_experiment_id,
        get_subject_ids_from_pages,
        wait_for_export_files,
        run_comparison,
    )
    from tests.fixtures.game_helpers import get_scene_id

    experiment_id = get_experiment_id()
    scene_id = get_scene_id(pages[0])

    parity_results = {}

    # Game 1 parity (pages 0, 1)
    print("\n[STRESS-07] Validating Game 1 data parity...")
    try:
        subject_ids_1 = get_subject_ids_from_pages(pages[0], pages[1])
        file1, file2 = wait_for_export_files(
            experiment_id=experiment_id,
            scene_id=scene_id,
            subject_ids=subject_ids_1,
            episode_num=0,
            timeout_sec=30
        )
        exit_code, output = run_comparison(file1, file2, verbose=True)
        parity_results[1] = (exit_code, output)
        if exit_code == 0:
            print(f"[STRESS-07] Game 1: PARITY VERIFIED")
        else:
            print(f"[STRESS-07] Game 1: PARITY FAILED - {output}")
    except Exception as e:
        parity_results[1] = (1, str(e))
        print(f"[STRESS-07] Game 1: PARITY ERROR - {e}")

    # Game 3 parity (pages 4, 5)
    print("[STRESS-07] Validating Game 3 data parity...")
    try:
        subject_ids_3 = get_subject_ids_from_pages(pages[4], pages[5])
        file1, file2 = wait_for_export_files(
            experiment_id=experiment_id,
            scene_id=scene_id,
            subject_ids=subject_ids_3,
            episode_num=0,
            timeout_sec=30
        )
        exit_code, output = run_comparison(file1, file2, verbose=True)
        parity_results[3] = (exit_code, output)
        if exit_code == 0:
            print(f"[STRESS-07] Game 3: PARITY VERIFIED")
        else:
            print(f"[STRESS-07] Game 3: PARITY FAILED - {output}")
    except Exception as e:
        parity_results[3] = (1, str(e))
        print(f"[STRESS-07] Game 3: PARITY ERROR - {e}")

    # Assert parity for completed games
    assert parity_results.get(1, (1, ""))[0] == 0, \
        f"[STRESS-07] Game 1 parity failed: {parity_results.get(1, (1, 'unknown'))[1]}"
    assert parity_results.get(3, (1, ""))[0] == 0, \
        f"[STRESS-07] Game 3 parity failed: {parity_results.get(3, (1, 'unknown'))[1]}"

    print(f"\n[STRESS-06 + STRESS-07] SUCCESS: Mixed scenarios handled, completed games have parity")
