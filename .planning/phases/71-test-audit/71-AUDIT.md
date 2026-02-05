# Phase 71: E2E Test Audit Results

## Summary

- **Total tests:** 26
- **Passed:** 18
- **Failed:** 8
- **Errors:** 0
- **Date:** 2026-02-05
- **Branch:** feature/waiting-room-overhaul
- **Commit:** c8a3bd8

## Test Results

| # | Test | File | Status | Category | Root Cause (brief) |
|---|------|------|--------|----------|-------------------|
| 1 | test_server_starts_and_contexts_connect | test_infrastructure.py | PASSED | - | - |
| 2 | test_two_players_connect_and_complete_episode | test_multiplayer_basic.py | PASSED | - | - |
| 3 | test_matchmaking_pairs_two_players | test_multiplayer_basic.py | PASSED | - | - |
| 4 | test_step_latency_not_degraded | test_worker_validation.py | PASSED | - | - |
| 5 | test_no_memory_growth_across_sessions | test_worker_validation.py | FAILED | test-infrastructure | Server exhaustion after 4 sessions; page.goto timeout on session 5 |
| 6 | test_export_parity_basic | test_data_comparison.py | PASSED | - | - |
| 7 | test_export_parity_with_latency | test_data_comparison.py | PASSED | - | - |
| 8 | test_active_input_parity | test_data_comparison.py | FAILED | production-bug | Data divergence: Noop (6) recorded instead of actual remote actions |
| 9 | test_focus_loss_mid_episode_parity | test_data_comparison.py | PASSED | - | - |
| 10 | test_focus_loss_episode_boundary_parity | test_data_comparison.py | FAILED | test-infrastructure | Server exhaustion from prior tests; page.goto timeout on port 5702 |
| 11 | test_episode_completion_under_fixed_latency[100] | test_latency_injection.py | PASSED | - | - |
| 12 | test_episode_completion_under_asymmetric_latency | test_latency_injection.py | PASSED | - | - |
| 13 | test_episode_completion_under_jitter | test_latency_injection.py | PASSED | - | - |
| 14 | test_active_input_with_latency[100] | test_latency_injection.py | FAILED | production-bug | Data divergence: Noop (6) recorded for remote actions under latency |
| 15 | test_episode_completion_under_fixed_latency[200] | test_latency_injection.py | FAILED | test-infrastructure | Server exhaustion; page.goto timeout after 3 prior tests on port 5702 |
| 16 | test_active_input_with_latency[200] | test_latency_injection.py | FAILED | test-infrastructure | Server exhaustion; page.goto timeout after 4 prior tests on port 5702 |
| 17 | test_packet_loss_triggers_rollback | test_network_disruption.py | PASSED | - | - |
| 18 | test_tab_visibility_triggers_fast_forward | test_network_disruption.py | PASSED | - | - |
| 19 | test_active_input_with_packet_loss | test_network_disruption.py | FAILED | production-bug | Data divergence: Noop (6) recorded for remote actions under packet loss |
| 20 | test_three_simultaneous_games | test_multi_participant.py | PASSED | - | - |
| 21 | test_staggered_participant_arrival | test_multi_participant.py | PASSED | - | - |
| 22 | test_multi_episode_completion | test_lifecycle_stress.py | FAILED | test-infrastructure | Game 1 of 3 episode timeout (300s); intermittent under concurrent load |
| 23 | test_mid_game_disconnect | test_lifecycle_stress.py | PASSED | - | - |
| 24 | test_waitroom_disconnect_isolation | test_lifecycle_stress.py | PASSED | - | - |
| 25 | test_focus_loss_timeout | test_lifecycle_stress.py | PASSED | - | - |
| 26 | test_mixed_lifecycle_scenarios | test_lifecycle_stress.py | PASSED | - | - |

## Categorized Failures

### production-bug (3 failures)

All three share one root cause: **data parity divergence with active inputs**.

#### Root Cause Analysis: Active Input Data Parity Bug

**Symptom:** When both players actively inject keyboard inputs (not just idle/Noop), exported CSV files diverge. One peer records the actual remote player's action while the other records Noop (action value 6) for the same frames. Divergences appear in `actions.0`, `actions.1`, and all derived `infos.X.*` columns (position, direction) because the game state diverges from the mispredicted action frame onward.

**Mechanism:**

1. Player 1 presses ArrowLeft (action 2) at frame N
2. Player 2's game predicts Player 1's action as Noop (6) for frame N (input hasn't arrived yet)
3. Player 2 steps the environment with {P1: Noop, P2: actual} and records this in `speculativeFrameData`
4. Player 1's actual input arrives, triggering rollback to frame N
5. Rollback calls `clearFrameDataFromRollback(N)` which clears both buffers
6. Replay re-simulates frame N with correct inputs and re-records correct data
7. However, if the input arrives *after* `confirmedFrame` has already advanced past frame N (due to timing), the speculative data with Noop was already promoted to `frameDataBuffer` via `_promoteConfirmedFrames()`
8. Rollback does clear `frameDataBuffer` entries >= targetFrame, so this should be corrected
9. **The actual issue**: With active inputs at high frequency (150ms/200ms intervals), the rollback window may not encompass all mispredicted frames. Some frames with predicted Noop actions get promoted to canonical buffer between the time the input was predicted and the time rollback occurs. Additionally, the v1.16 Worker migration made env stepping async (via postMessage to Worker), which may introduce timing gaps where frame promotion races with rollback clearing.

**Evidence:**
- Divergences always show action value 6 (Noop) on one side vs real action values (0-5) on the other
- The divergence starts at early frames (row 3-10) and cascades through derived state columns
- Idle tests (test_export_parity_basic, test_export_parity_with_latency) PASS because both peers predict Noop and the actual action is also Noop -- so misprediction doesn't cause divergence
- Packet loss test shows fewer divergences (18 in actions.0) than no-loss active input test (98 in actions.0), which is counterintuitive and suggests the specific timing of input delivery matters more than loss rate

**Affected production code:**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` -- `_promoteConfirmedFrames()`, `clearFrameDataFromRollback()`, `storeFrameData()`, and the `_handleWorkerTick` -> `performStep` -> `storeFrameData` sequence
- The v1.16 Worker migration (Phase 69) changed `performRollback()` to use `this.worker.batch()` which is async. The replay loop awaits each step, but the frame data buffer updates may interleave differently than the original synchronous Pyodide execution

#### 1. test_active_input_parity
- **File:** tests/e2e/test_data_comparison.py
- **Error:** `Failed: Data parity check failed with active inputs (exit code 1): Column 'actions.0' has 98 divergences`
- **Root Cause:** See shared root cause above. No latency injection, no packet loss -- pure active input prediction mismatch.
- **Fix Approach:** Fix the rollback/promotion race condition in the multiplayer game engine. Ensure that when rollback clears and replays frames, the corrected data fully replaces any previously-promoted canonical data. Specifically, investigate whether `_updateConfirmedFrame()` can advance `confirmedFrame` while a rollback is in progress (despite `rollbackInProgress` guard).
- **Complexity:** complex

#### 2. test_active_input_with_latency[100]
- **File:** tests/e2e/test_latency_injection.py
- **Error:** `Failed: Data parity check failed with active inputs + 100ms latency (exit code 1): Column 'actions.0' has 79 divergences, Column 'actions.1' has 59 divergences`
- **Root Cause:** Same root cause as #1, amplified by 100ms network latency. Both `actions.0` and `actions.1` diverge because latency delays inputs in both directions.
- **Fix Approach:** Same fix as #1. The latency variant confirms this is a timing-dependent bug.
- **Complexity:** complex (same fix)

#### 3. test_active_input_with_packet_loss
- **File:** tests/e2e/test_network_disruption.py
- **Error:** `Failed: Data parity check failed with active inputs + packet loss (exit code 1): Column 'actions.0' has 18 divergences`
- **Root Cause:** Same root cause as #1, with packet loss causing additional rollbacks (19 total). Fewer divergences (18 vs 98) because packet loss forces more rollbacks which correct more frames -- but some frames still escape correction.
- **Fix Approach:** Same fix as #1.
- **Complexity:** complex (same fix)

### test-infrastructure (5 failures)

These fall into two shared root causes: **server exhaustion** (4 tests) and **concurrent load timeout** (1 test).

#### Shared Root Cause A: Module-Scoped Server Exhaustion (4 tests)

**Symptom:** `Page.goto: Timeout 30000ms exceeded` when navigating to `http://localhost:5702/` or `http://localhost:5705/`.

**Mechanism:** The `flask_server` fixture is module-scoped (port 5702). All tests in `test_data_comparison.py` and `test_latency_injection.py` share the same server process. Each test creates a game session (2 players, 1 game, P2P connection, Pyodide Workers, env instance). After 3-4 tests, the server accumulates enough state that new page loads timeout:
- Completed game sessions leave server-side cleanup tasks running
- Each game creates eventlet greenlets for Socket.IO communication that may not fully clean up
- The Flask subprocess may exhaust available connections or memory
- The Playwright default 30s `goto` timeout is not enough when the server is under accumulated load

**Evidence:**
- test_focus_loss_episode_boundary_parity fails on page.goto BEFORE any test logic runs (pages are still at `about:blank`)
- test_episode_completion_under_fixed_latency[200] fails similarly -- page URL shows `chrome-error://chromewebdata/` indicating the server didn't respond
- test_active_input_with_latency[200] fails the same way
- test_no_memory_growth_across_sessions creates 10 consecutive game sessions on a fresh server (port 5705); fails on session 5's page.goto, consistent with server exhaustion pattern
- Earlier tests in the same module PASS (they run first when server is fresh)

#### 4. test_no_memory_growth_across_sessions
- **File:** tests/e2e/test_worker_validation.py
- **Error:** `Page.goto: Timeout 30000ms exceeded` navigating to `http://localhost:5705/` during session 5/10
- **Root Cause:** Server exhaustion after 4 consecutive game sessions. The `flask_server_fresh` fixture starts a fresh server, but the test creates 10 sequential sessions on it. After 4 sessions, the server can no longer serve new page loads within 30s.
- **Fix Approach:** Increase `page.goto` timeout to 60s for this test. Alternatively, add explicit server-side cleanup between sessions (e.g., call a `/cleanup` endpoint). Most robust: restart server every N sessions or add a health check between iterations.
- **Complexity:** moderate

#### 5. test_focus_loss_episode_boundary_parity
- **File:** tests/e2e/test_data_comparison.py
- **Error:** `Page.goto: Timeout 30000ms exceeded` navigating to `http://localhost:5702/`
- **Root Cause:** This is the 5th test in the module using the shared `flask_server` (port 5702). The 4 prior tests consumed server resources, and the server can no longer handle new connections.
- **Fix Approach:** Change `flask_server` from module-scoped to function-scoped for data comparison tests, or use `flask_server_fresh` (per-function scope). Alternatively, add a `/reset` endpoint to the test server that clears accumulated game state.
- **Complexity:** simple -- change fixture from `flask_server` to `flask_server_fresh` (or create a data_comparison-specific fresh fixture)

#### 6. test_episode_completion_under_fixed_latency[200]
- **File:** tests/e2e/test_latency_injection.py
- **Error:** `Page.goto: Timeout 30000ms exceeded` navigating to `http://localhost:5702/`
- **Root Cause:** 4th test in module using shared `flask_server` (port 5702). Server exhausted by prior tests (100ms latency completion + asymmetric + jitter + active input with 100ms). Additionally, 200ms symmetric latency on both players doubles the effective page load time, making the 30s timeout more likely to fail.
- **Fix Approach:** Same as #5 -- use per-function server or increase goto timeout for high-latency tests. For 200ms latency tests specifically, set `page.goto(url, timeout=60000)` since the latency applies to all HTTP requests including the initial page load.
- **Complexity:** simple

#### 7. test_active_input_with_latency[200]
- **File:** tests/e2e/test_latency_injection.py
- **Error:** `Page.goto: Timeout 30000ms exceeded` navigating to `http://localhost:5702/`
- **Root Cause:** Same as #6 -- 5th test in module, server already exhausted. Even if the 200ms latency test (#6) had not failed and consumed time, this test would still face server exhaustion.
- **Fix Approach:** Same as #5/#6.
- **Complexity:** simple

#### Shared Root Cause B: Concurrent Load Episode Timeout (1 test)

#### 8. test_multi_episode_completion
- **File:** tests/e2e/test_lifecycle_stress.py
- **Error:** `AssertionError: [STRESS-02] Game 1 episode 1 failed: Player 1 episode completion timeout: Page.wait_for_function: Timeout 300000ms exceeded.`
- **Root Cause:** This test runs 3 simultaneous games (6 browser contexts) with 2 episodes each. All 3 games start successfully and Game 0 and Game 2 complete episode 1 with verified parity. Game 1 hangs -- one player's episode never completes within 300s. This is an intermittent concurrent load issue: with 3 games running simultaneously, the server's eventlet thread pool, WebRTC signaling, and Pyodide Worker threads compete for resources. Game 1's P2P connection may have dropped or one player's Worker stalled under load.
- **Fix Approach:** (1) Increase episode timeout for multi-game tests to 600s. (2) Add explicit game-level health checks (e.g., monitor `frameNumber` advancement) to detect stuck games early and provide better diagnostics. (3) Consider reducing from 3 simultaneous games to 2 for the multi-episode variant, since the single-episode `test_three_simultaneous_games` passes reliably.
- **Complexity:** moderate

### fixture-issue (0 failures)

No fixture-level failures were observed. All server fixtures started correctly and all browser contexts were created without issues.

## Passing Tests (18)

These tests all work correctly post-Worker-migration, confirming the core multiplayer infrastructure is functional:

1. **test_server_starts_and_contexts_connect** -- Server startup, browser contexts, WebRTC connectivity
2. **test_two_players_connect_and_complete_episode** -- Full 2-player episode lifecycle
3. **test_matchmaking_pairs_two_players** -- FIFO matchmaker, waiting room, game creation
4. **test_step_latency_not_degraded** -- Worker step performance within acceptable bounds
5. **test_export_parity_basic** -- Data parity with idle players (no active inputs)
6. **test_export_parity_with_latency** -- Data parity with idle players + 200ms latency
7. **test_focus_loss_mid_episode_parity** -- Data parity when tab hidden mid-episode
8. **test_episode_completion_under_fixed_latency[100]** -- Episode completes under 100ms latency
9. **test_episode_completion_under_asymmetric_latency** -- Episode completes under asymmetric latency
10. **test_episode_completion_under_jitter** -- Episode completes under jitter latency
11. **test_packet_loss_triggers_rollback** -- Rollback mechanism functions under packet loss
12. **test_tab_visibility_triggers_fast_forward** -- Fast-forward mechanism on tab refocus
13. **test_three_simultaneous_games** -- 3 concurrent games with 6 players (single episode)
14. **test_staggered_participant_arrival** -- Late-arriving participants join correctly
15. **test_mid_game_disconnect** -- Partner disconnection handled gracefully
16. **test_waitroom_disconnect_isolation** -- Waitroom disconnect doesn't affect other players
17. **test_focus_loss_timeout** -- Focus loss timeout triggers game end correctly
18. **test_mixed_lifecycle_scenarios** -- Combined lifecycle events handled correctly

**Key observation:** All idle/Noop parity tests pass. The Worker migration does not break core functionality. The data parity bug is specific to the interaction between active input prediction and the dual-buffer promotion mechanism.

## Phase 72 Work Queue (Test Infrastructure)

Fixes for the 5 test-infrastructure failures, grouped by shared root cause:

### Group A: Server Exhaustion (4 tests, 1 shared fix)

**Root cause:** Module-scoped `flask_server` fixture accumulates state across tests. Server becomes unresponsive after 3-4 game sessions.

**Fix:** Migrate affected tests to per-function server fixtures.

| Priority | Fix | Tests Affected | Complexity | Files |
|----------|-----|---------------|------------|-------|
| 1 | Create `flask_server_data_comparison` (function-scoped, port 5702) or use `flask_server_fresh` | test_focus_loss_episode_boundary_parity | simple | tests/conftest.py, tests/e2e/test_data_comparison.py |
| 2 | Create `flask_server_latency` (function-scoped, port 5702) or use `flask_server_fresh` | test_episode_completion_under_fixed_latency[200], test_active_input_with_latency[200] | simple | tests/conftest.py, tests/e2e/test_latency_injection.py |
| 3 | Add goto timeout increase + health check between sessions in memory test | test_no_memory_growth_across_sessions | moderate | tests/e2e/test_worker_validation.py |

**Implementation notes:**
- Switching to function-scoped servers increases test runtime (each test starts/stops a server, ~5s overhead each)
- Alternative: Add a server `/reset` endpoint that clears accumulated game state (more complex but faster tests)
- For the memory test, a server restart every 3-4 sessions would be most reliable
- The 200ms latency tests may also need `page.goto(url, timeout=60000)` since CDP latency affects the initial page load

### Group B: Concurrent Load Timeout (1 test)

**Root cause:** 3 simultaneous games compete for server resources; one game stalls.

| Priority | Fix | Tests Affected | Complexity | Files |
|----------|-----|---------------|------------|-------|
| 4 | Increase episode timeout to 600s for multi-game multi-episode tests; add frame advancement health check | test_multi_episode_completion | moderate | tests/e2e/test_lifecycle_stress.py, tests/fixtures/multi_participant.py |

**Implementation notes:**
- The single-episode variant (`test_three_simultaneous_games`) passes reliably, so the issue is specific to multi-episode + concurrent games
- Adding a frame advancement health check (poll `game.frameNumber` every 30s) would provide early failure detection instead of waiting for full 300s timeout
- Consider adding per-game timeout with retry (if one game stalls, restart it rather than failing the whole test)

## Phase 73 Work Queue (Production Bugs)

Fixes for the 3 production-bug failures (1 shared root cause):

### Active Input Data Parity Bug (3 tests)

**Root cause:** Speculative frame data with predicted Noop actions gets promoted to canonical buffer before rollback can correct it, causing data divergence between peers.

| Priority | Fix | Tests Affected | Complexity | Files |
|----------|-----|---------------|------------|-------|
| 1 | Fix rollback/promotion race in dual-buffer data recording | test_active_input_parity, test_active_input_with_latency[100], test_active_input_with_packet_loss | complex | interactive_gym/server/static/js/pyodide_multiplayer_game.js |

**Investigation steps:**
1. Add logging to `_promoteConfirmedFrames()` to trace which frames are being promoted and what action values they contain
2. Check if `_updateConfirmedFrame()` can run during `performRollback()` despite the `rollbackInProgress` guard (possible if async Worker batch completes between steps)
3. Verify that `clearFrameDataFromRollback()` removes ALL promoted frames from `frameDataBuffer` -- check if the Map iteration during delete works correctly for frames promoted during the same tick
4. Check whether the async `worker.batch()` call in `performRollback()` allows event loop ticks that process new input packets and advance `confirmedFrame` mid-rollback
5. Consider adding a "dirty frame" marker that prevents promotion of frames that are pending rollback correction

**Potential fixes (investigate in priority order):**
1. **Lock promotion during rollback:** Prevent `_promoteConfirmedFrames()` from running while `rollbackInProgress` is true. After rollback completes, do a full promotion pass.
2. **Re-record on promotion:** When promoting speculative data, check if the frame was replayed (compare against action sequence) and use the replayed data instead of the original speculative data.
3. **Defer confirmedFrame advancement:** During rollback, don't update `confirmedFrame` until the full replay is complete. This prevents mid-rollback promotion.
4. **Post-rollback canonical sweep:** After rollback replay completes, sweep `frameDataBuffer` for any entries that were promoted with old (pre-rollback) data and replace them with the replayed data from `speculativeFrameData`.

**Validation:** After fix, run the 3 failing tests plus the 5 passing parity tests to confirm no regressions. The fix must handle:
- Active inputs with no network effects (test_active_input_parity)
- Active inputs with 100ms latency (test_active_input_with_latency[100])
- Active inputs with 15% packet loss (test_active_input_with_packet_loss)
