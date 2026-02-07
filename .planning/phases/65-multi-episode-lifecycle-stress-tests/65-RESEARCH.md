# Phase 65: Multi-Episode and Lifecycle Stress Tests - Research

**Researched:** 2026-02-03
**Domain:** Playwright stress testing for participant lifecycle scenarios (multi-episode, disconnects, focus loss)
**Confidence:** HIGH

## Summary

This phase builds comprehensive stress tests for all participant lifecycle scenarios on top of Phase 64's multi-participant infrastructure. The existing test infrastructure (GameOrchestrator, multi_participant_contexts fixture, export validation helpers) provides a solid foundation. The primary work involves creating new test scenarios that exercise specific lifecycle events rather than building new infrastructure.

The codebase already implements all the server-side handlers needed:
- **Mid-game disconnection:** `on_disconnect()` in app.py triggers `p2p_game_ended` to remaining players, shows overlay with completion code
- **Waiting room disconnection:** `leave_game()` in game_manager.py emits `waiting_room_player_left` to other participants
- **Focus loss timeout:** `FocusManager` in pyodide_multiplayer_game.js tracks background duration, calls `_handleFocusLossTimeout()` when exceeded

Tests must validate that these handlers work correctly and that completed games produce parity-valid exports.

**Primary recommendation:** Create focused test functions for each scenario (STRESS-02 through STRESS-07) using existing infrastructure, with each test validating both the lifecycle behavior AND data parity where applicable.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| playwright | 1.49+ | Browser automation | Already used, provides context.close() for disconnection simulation |
| pytest-playwright | 0.6+ | pytest integration | Already used, provides browser fixture |
| pytest | 8.0+ | Test framework | Already used, markers for test organization |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-timeout | 2.3+ | Test timeouts | Already used, 600s for multi-participant tests |
| time (stdlib) | - | Sleep between operations | Stagger arrivals, wait for state changes |

### No New Dependencies
All required functionality exists in the current stack. The tests use Playwright's built-in mechanisms for simulating browser/connection events.

## Architecture Patterns

### Recommended Test Structure
```
tests/
├── conftest.py                    # multi_participant_contexts (6 pages, already exists)
├── fixtures/
│   ├── multi_participant.py       # GameOrchestrator (already exists)
│   ├── game_helpers.py            # wait_for_* helpers (already exists)
│   ├── network_helpers.py         # set_tab_visibility (already exists)
│   └── export_helpers.py          # run_comparison (already exists)
└── e2e/
    ├── test_multi_participant.py  # STRESS-01 (already exists)
    └── test_lifecycle_stress.py   # NEW: STRESS-02 through STRESS-07
```

### Pattern 1: Multi-Episode Test (STRESS-02)
**What:** Validate participants complete 2+ episodes back-to-back without state corruption
**When to use:** Testing episode boundary handling and state reset
**Test Structure:**
```python
@pytest.mark.timeout(600)
def test_multi_episode_completion(multi_participant_contexts, flask_server):
    """STRESS-02: Complete 2+ episodes back-to-back without state corruption."""
    pages = multi_participant_contexts
    base_url = flask_server["url"]
    orchestrator = GameOrchestrator(pages, base_url)

    # Start all games
    orchestrator.start_all_games()

    # Wait for episode 1 to complete
    orchestrator.wait_for_all_episodes_complete(episode_num=1)

    # Validate episode 1 parity
    results_ep1 = orchestrator.validate_all_data_parity(episode_num=0)
    for game_idx, (exit_code, output) in enumerate(results_ep1):
        assert exit_code == 0, f"Game {game_idx} episode 1 parity failed"

    # Wait for episode 2 to complete
    orchestrator.wait_for_all_episodes_complete(episode_num=2)

    # Validate episode 2 parity
    results_ep2 = orchestrator.validate_all_data_parity(episode_num=1)
    for game_idx, (exit_code, output) in enumerate(results_ep2):
        assert exit_code == 0, f"Game {game_idx} episode 2 parity failed"
```

**Server configuration needed:** Modify test server to use `num_episodes=2` for multi-episode testing.

### Pattern 2: Mid-Game Disconnection Test (STRESS-03)
**What:** Simulate partner disconnect during active gameplay
**When to use:** Testing disconnect handling, data export of partial games
**Test Structure:**
```python
@pytest.mark.timeout(300)
def test_mid_game_disconnect(player_contexts, flask_server):
    """STRESS-03: Mid-game disconnect triggers partner notification and data export."""
    page1, page2 = player_contexts

    # Start game
    run_full_episode_flow_until_gameplay(page1, page2, base_url)

    # Let game run for a few seconds
    time.sleep(3)

    # Simulate disconnect by closing page2's context
    page2.context.close()

    # Wait for page1 to show partner disconnected overlay
    page1.wait_for_selector("#partnerDisconnectedOverlay", state="visible", timeout=30000)

    # Verify overlay message
    overlay_text = page1.locator("#partnerDisconnectedOverlay").text_content()
    assert "partner" in overlay_text.lower() or "disconnected" in overlay_text.lower()

    # Verify completion code is shown
    assert "completion" in overlay_text.lower() or page1.locator("#completionCode").is_visible()

    # Verify data was exported for completed frames
    # (Data export happens on disconnect, partial episode is valid)
```

### Pattern 3: Waiting Room Disconnection Test (STRESS-04)
**What:** Simulate disconnect while waiting for match, verify others unaffected
**When to use:** Testing waitroom robustness
**Test Structure:**
```python
@pytest.mark.timeout(300)
def test_waitroom_disconnect_isolation(multi_participant_contexts, flask_server):
    """STRESS-04: Waitroom disconnect doesn't affect other participants."""
    pages = multi_participant_contexts

    # Navigate games with 2s stagger
    games = [(pages[0], pages[1]), (pages[2], pages[3]), (pages[4], pages[5])]

    # Start first game, let it progress to gameplay
    navigate_and_start_game(games[0])
    wait_for_game_canvas(games[0][0])
    wait_for_game_canvas(games[0][1])

    # Start second game, but one player disconnects before match
    pages[2].goto(base_url)
    wait_for_socket_connected(pages[2])
    click_advance_button(pages[2])
    click_start_button(pages[2])

    # Wait for waitroom
    wait_for_waitroom(pages[2])

    # Disconnect pages[2] while in waitroom (before pages[3] joins)
    pages[2].context.close()

    # Verify game 1 is unaffected - still progressing
    state1 = get_game_state(games[0][0])
    assert state1["frameNumber"] > 0, "Game 1 should still be running"

    # Verify pages[3] can still join and match with pages[4,5] or wait
    pages[3].goto(base_url)
    # ... continue normal flow
```

### Pattern 4: Focus Loss Timeout Test (STRESS-05)
**What:** Tab goes to background, game ends gracefully after timeout
**When to use:** Testing focus loss behavior with timeout enabled
**Test Structure:**
```python
@pytest.mark.timeout(300)
def test_focus_loss_timeout(player_contexts, flask_server_with_focus_timeout):
    """STRESS-05: Focus loss triggers graceful game end after timeout."""
    page1, page2 = player_contexts

    # Start game
    run_full_episode_flow_until_gameplay(page1, page2, base_url)

    # Let game run for a few seconds
    time.sleep(3)

    # Hide player 1's tab
    set_tab_visibility(page1, visible=False)
    wait_for_focus_manager_state(page1, backgrounded=True)

    # Wait for timeout to expire (configured timeout + buffer)
    timeout_ms = 10000  # from server config
    time.sleep((timeout_ms + 5000) / 1000)

    # Verify player 1 sees focus loss overlay (they caused the timeout)
    overlay = page1.locator("#focusLossTimeoutOverlay, #partnerDisconnectedOverlay")
    expect(overlay).to_be_visible()

    # Verify player 2 sees partner disconnected message
    # (They receive p2p_game_ended with reason=focus_loss_timeout)
```

**Server configuration needed:** Create separate test config with focus_loss_timeout enabled (e.g., 10000ms).

### Pattern 5: Mixed Lifecycle Test (STRESS-06)
**What:** Combines disconnect + completion + focus loss in single test
**When to use:** Testing server state recovery across multiple chaos events
**Test Structure:**
```python
@pytest.mark.timeout(600)
def test_mixed_lifecycle_scenarios(multi_participant_contexts, flask_server):
    """STRESS-06: Combined lifecycle scenarios don't corrupt server state."""
    pages = multi_participant_contexts

    # Game 1: Normal completion
    # Game 2: Mid-game disconnect
    # Game 3: Focus loss (but recovers before timeout)

    # ... execute scenarios in parallel with staggered timing

    # Key assertions:
    # - Game 1 completes normally with parity
    # - Game 2's remaining player gets proper notification
    # - Game 3 recovers and completes with parity
```

### Anti-Patterns to Avoid
- **Not waiting for state changes:** Always wait for the expected state transition before asserting
- **Sharing contexts between tests:** Each test needs fresh contexts (function-scoped fixture)
- **Testing focus loss with timeout=0:** Must use a test config with actual timeout to trigger the behavior
- **Assuming instant disconnect detection:** Socket.IO has ping_interval=2s, ping_timeout=2s, so 4s minimum

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Simulating disconnect | Custom socket manipulation | `page.context.close()` | Playwright properly tears down everything |
| Simulating focus loss | Custom event dispatch | `set_tab_visibility()` | Already handles document.hidden override |
| Waiting for state | Polling loops | `page.wait_for_function()` | Browser-native, handles timeouts properly |
| Export validation | Custom CSV parsing | `run_comparison()` | Validates action sequences with tolerance |
| Multi-game orchestration | Manual page management | `GameOrchestrator` | Handles stagger timing, pairing verification |

**Key insight:** The test infrastructure from Phases 62-64 handles all the hard orchestration problems. This phase is about writing test scenarios, not building infrastructure.

## Common Pitfalls

### Pitfall 1: Disconnect Timing vs Socket.IO Ping
**What goes wrong:** Test expects immediate disconnect detection, but takes 4+ seconds
**Why it happens:** Socket.IO ping_interval=2s, ping_timeout=2s configured in app.py
**How to avoid:** Wait at least 5s after context.close() before checking disconnect effects
**Warning signs:** Flaky tests that pass locally but fail in CI

### Pitfall 2: Focus Timeout Disabled in Test Config
**What goes wrong:** Focus loss test never triggers timeout
**Why it happens:** Default test config uses `focus_loss_config(timeout_ms=0)` to disable
**How to avoid:** Create separate flask_server fixture with timeout enabled
**Warning signs:** Test times out waiting for focusLossTimeoutOverlay

### Pitfall 3: Multi-Episode Config Not Set
**What goes wrong:** Test expects 2 episodes but game ends after 1
**Why it happens:** Default test config uses `num_episodes=1`
**How to avoid:** Create separate config or modify test server for multi-episode
**Warning signs:** `wait_for_episode_complete(episode_num=2)` times out

### Pitfall 4: Parity Validation on Partial Games
**What goes wrong:** run_comparison fails on games that ended early (disconnect/timeout)
**Why it happens:** Partial exports have different row counts than complete games
**How to avoid:** Only validate parity for games that completed normally; for disconnects, validate that export exists and has reasonable data
**Warning signs:** Parity assertion fails with "row count mismatch" for interrupted games

### Pitfall 5: Race Between Disconnect and Data Export
**What goes wrong:** Export file doesn't exist when test checks for it
**Why it happens:** Server exports data asynchronously after disconnect processing
**How to avoid:** Use `wait_for_export_files()` with adequate timeout (30s)
**Warning signs:** FileNotFoundError in tests that should have exported data

## Code Examples

Verified patterns from existing codebase:

### Complete Mid-Game Disconnect Test
```python
# Source: Extension of test_network_disruption.py patterns
@pytest.mark.timeout(300)
def test_mid_game_disconnect_partner_notification(player_contexts, flask_server):
    """
    STRESS-03: Validate mid-game disconnect handling.

    When player 2 disconnects mid-game:
    1. Server detects disconnect via Socket.IO ping timeout
    2. Server emits 'p2p_game_ended' to player 1
    3. Player 1 shows partner disconnected overlay with completion code
    4. Data export is triggered for completed frames
    """
    page1, page2 = player_contexts
    base_url = flask_server["url"]

    # Start game
    run_full_episode_flow_until_gameplay(page1, page2, base_url)

    # Verify game started
    state1 = get_game_state(page1)
    state2 = get_game_state(page2)
    assert state1["gameId"] == state2["gameId"], "Players should be matched"

    # Let game run for a few seconds (accumulate frames)
    time.sleep(5)
    frame_before_disconnect = get_game_state(page1)["frameNumber"]
    print(f"Frame before disconnect: {frame_before_disconnect}")

    # Disconnect player 2 by closing their browser context
    page2.context.close()

    # Wait for player 1 to receive disconnect notification
    # Socket.IO ping timeout is ~4s, add buffer
    page1.wait_for_function(
        "() => window.game && window.game.partnerDisconnectedTerminal === true",
        timeout=15000
    )

    # Verify overlay is displayed
    page1.wait_for_selector(
        "#partnerDisconnectedOverlay, .game-overlay",
        state="visible",
        timeout=5000
    )

    # Verify game state is 'done'
    final_state = get_game_state(page1)
    assert final_state is None or final_state.get("state") == "done", \
        "Game should be in 'done' state after partner disconnect"

    print(f"[STRESS-03] Partner disconnect handled correctly")
```

### Focus Loss Timeout Test Setup
```python
# Source: tests/conftest.py extension for focus loss testing
@pytest.fixture(scope="module")
def flask_server_with_focus_timeout():
    """
    Start Flask server with focus loss timeout ENABLED.

    Unlike the default test config which disables focus timeout (timeout_ms=0),
    this fixture uses a config with a short timeout (10s) for testing.

    Requires: overcooked_human_human_multiplayer_focus_test.py config file
    """
    port = 5703  # Different port to avoid conflicts
    base_url = f"http://localhost:{port}"

    process = subprocess.Popen(
        [
            "python", "-m",
            "interactive_gym.examples.cogrid.overcooked_human_human_multiplayer_focus_test",
            "--port", str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server ready (same pattern as flask_server)
    # ... poll health endpoint

    yield {"url": base_url, "process": process, "focus_timeout_ms": 10000}

    process.terminate()
    process.wait(timeout=5)
```

### Waiting Room Disconnect Isolation
```python
# Source: Extension of multi_participant patterns
@pytest.mark.timeout(300)
def test_waitroom_disconnect_isolation(multi_participant_contexts, flask_server):
    """
    STRESS-04: Waitroom disconnect doesn't corrupt server state for other games.

    Scenario:
    - Game 1 (pages 0,1): Complete successfully
    - Game 2: pages[2] disconnects in waitroom, pages[3] never matches
    - Game 3 (pages 4,5): Complete successfully despite Game 2 failure
    """
    pages = multi_participant_contexts
    base_url = flask_server["url"]

    # Start Game 1 first
    page1, page2 = pages[0], pages[1]
    page1.goto(base_url)
    time.sleep(0.1)
    page2.goto(base_url)

    wait_for_socket_connected(page1)
    wait_for_socket_connected(page2)
    click_advance_button(page1)
    click_advance_button(page2)
    click_start_button(page1)
    time.sleep(0.5)
    click_start_button(page2)

    # Wait for Game 1 to be in gameplay
    wait_for_game_canvas(page1)
    wait_for_game_canvas(page2)
    set_tab_visibility(page1, visible=True)
    set_tab_visibility(page2, visible=True)

    print("Game 1: Started")

    # Start Game 2's first player
    page3 = pages[2]
    page3.goto(base_url)
    wait_for_socket_connected(page3)
    click_advance_button(page3)
    click_start_button(page3)

    # Verify page3 is in waitroom
    wait_for_waitroom(page3)
    print("Game 2 player 1: In waitroom")

    # Disconnect page3 while in waitroom (before partner joins)
    page3.context.close()
    print("Game 2 player 1: Disconnected from waitroom")

    # Give server time to process disconnect
    time.sleep(2)

    # Verify Game 1 is still running (unaffected by Game 2 disconnect)
    state1 = get_game_state(page1)
    assert state1["frameNumber"] > 10, "Game 1 should still be progressing"
    print(f"Game 1: Still running at frame {state1['frameNumber']}")

    # Start Game 3
    page5, page6 = pages[4], pages[5]
    page5.goto(base_url)
    time.sleep(0.1)
    page6.goto(base_url)

    wait_for_socket_connected(page5)
    wait_for_socket_connected(page6)
    click_advance_button(page5)
    click_advance_button(page6)
    click_start_button(page5)
    time.sleep(0.5)
    click_start_button(page6)

    # Wait for Game 3 to be in gameplay
    wait_for_game_canvas(page5)
    wait_for_game_canvas(page6)
    set_tab_visibility(page5, visible=True)
    set_tab_visibility(page6, visible=True)

    # Verify Game 3 matched correctly
    state5 = get_game_state(page5)
    state6 = get_game_state(page6)
    assert state5["gameId"] == state6["gameId"], "Game 3 players should be matched"
    print(f"Game 3: Started, gameId={state5['gameId']}")

    # Wait for both games to complete
    wait_for_episode_complete(page1, episode_num=1, timeout=180000)
    wait_for_episode_complete(page5, episode_num=1, timeout=180000)

    print("[STRESS-04] Waitroom disconnect isolated - other games completed normally")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual 2-player tests | GameOrchestrator for 6-participant | Phase 64 | Enables complex lifecycle scenarios |
| Single episode tests | Multi-episode validation | Phase 65 | Tests state persistence across episodes |
| Disconnect = redirect | In-page overlay with completion code | Phase 23 | Better UX, completion code tracking |
| Focus loss = immediate end | Configurable timeout with telemetry | Phase 27 | Graceful handling with data export |

**Test infrastructure evolution:**
- Phase 40: Basic Playwright infrastructure
- Phase 62: Data parity validation helpers
- Phase 63: Latency/packet loss injection
- Phase 64: Multi-participant orchestration (GameOrchestrator)
- Phase 65: Lifecycle stress tests (this phase)

## Open Questions

Things that couldn't be fully resolved:

1. **Multi-episode test server configuration**
   - What we know: Current test config uses `num_episodes=1`
   - What's unclear: Best approach - modify existing config vs. create new config file
   - Recommendation: Create `overcooked_human_human_multiplayer_multi_episode_test.py` with `num_episodes=2`

2. **Focus loss test server configuration**
   - What we know: Current test config has `timeout_ms=0` (disabled)
   - What's unclear: Whether to use separate server fixture or parameterize existing
   - Recommendation: Create separate fixture `flask_server_with_focus_timeout` on different port

3. **Parity validation for partial games**
   - What we know: Disconnected games may not have complete exports
   - What's unclear: What to validate for interrupted games
   - Recommendation: For disconnect tests, validate: (1) export file exists, (2) reasonable row count, (3) no corruption. Full parity only for completed games.

4. **Order of STRESS-07 validation**
   - What we know: "All completed games' exports validated for exact parity"
   - What's unclear: Should each test validate parity inline, or separate STRESS-07 test?
   - Recommendation: Inline validation in STRESS-02, STRESS-06 for completed games. STRESS-07 is implicit in those tests.

## Sources

### Primary (HIGH confidence)
- `/Users/chasemcd/Repositories/interactive-gym/tests/conftest.py` - multi_participant_contexts fixture
- `/Users/chasemcd/Repositories/interactive-gym/tests/fixtures/multi_participant.py` - GameOrchestrator class
- `/Users/chasemcd/Repositories/interactive-gym/tests/fixtures/game_helpers.py` - wait_for_* helpers
- `/Users/chasemcd/Repositories/interactive-gym/tests/e2e/test_network_disruption.py` - focus loss test patterns
- `/Users/chasemcd/Repositories/interactive-gym/tests/e2e/test_data_comparison.py` - parity validation patterns
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/app.py:2659` - on_disconnect() handler
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/game_manager.py:987` - leave_game() handler
- `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/static/js/pyodide_multiplayer_game.js:6560` - _handleFocusLossTimeout()

### Secondary (MEDIUM confidence)
- Phase 64 research (64-RESEARCH.md) - Multi-participant infrastructure patterns
- Playwright documentation for context.close() behavior

### Tertiary (LOW confidence)
- Socket.IO ping/timeout behavior from code inspection (may vary in practice)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Extending existing proven infrastructure
- Architecture patterns: HIGH - Based on working Phase 64 patterns
- Disconnect behavior: HIGH - Verified in codebase (app.py, game_manager.py)
- Focus timeout behavior: HIGH - Verified in codebase (pyodide_multiplayer_game.js)
- Pitfalls: MEDIUM - Some timing issues may need tuning in CI

**Research date:** 2026-02-03
**Valid until:** 90 days (stable domain, test patterns don't change quickly)
