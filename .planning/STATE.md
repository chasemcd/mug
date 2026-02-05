# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-04)

**Core value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.
**Current focus:** v1.16 Pyodide Web Worker - Complete (shipped 2026-02-05)

## Current Position

Milestone: v1.16 Pyodide Web Worker
Phase: 70 of 70 (Validation and Cleanup) — Complete
Plan: 02 of 02 complete
Status: All phases complete. Three critical Worker bugs fixed, multiplayer game verified working.
Last activity: 2026-02-05 — Completed Phase 70 (Validation and Cleanup)

Progress: ██████████ 100%

## Milestone History

| Milestone | Phases | Status | Shipped |
|-----------|--------|--------|---------|
| v1.16 Pyodide Web Worker | 67-70 | Complete | 2026-02-05 |
| v1.15 E2E Test Reliability | - | Root cause found | 2026-02-04 |
| v1.14 Data Parity Fix | 61-65 | Complete | 2026-02-04 |
| v1.13 Matchmaker Hardening | 57-60 | Complete | 2026-02-03 |
| v1.12 Waiting Room Overhaul | 51-56 | Complete | 2026-02-03 |
| v1.11 Data Export Edge Cases | 48-50 | Complete | 2026-02-03 |
| v1.10 E2E Test Fix | 45-47 | Complete | 2026-02-02 |
| v1.9 Data Parity Testing | 40-44 | Complete | 2026-02-01 |
| v1.8 Data Export Parity | 36-39 | Complete | 2026-01-30 |
| v1.7 Admin Console Improvement | 32-35 | Complete | 2026-01-25 |
| v1.6 Input Latency Diagnosis | 28 | Partial | 2026-01-24 |
| v1.5 Focus Loss Handling | 24-27 | Complete | 2026-01-23 |
| v1.4 Partner Disconnection Handling | 23 | Complete | 2026-01-22 |
| v1.3 P2P Connection Validation | 19-22 | Complete | 2026-01-22 |
| v1.2 Participant Exclusion | 15-18 | Complete | 2026-01-22 |
| v1.1 Sync Validation | 11-14 | Complete | - |
| v1.0 P2P Multiplayer | 1-10 | Complete | 2026-01-19 |

## Accumulated Context

### Key Files

**P2P Core (created/heavily modified in v1.0):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` (5,600+ LOC)
- `interactive_gym/server/static/js/webrtc_manager.js` (1,030+ LOC)
- `interactive_gym/server/pyodide_game_coordinator.py`
- `interactive_gym/configurations/remote_config.py`

**Focus Loss Timeout & Telemetry (v1.5 Phase 27 - added):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - FocusManager.setTimeoutConfig(), isTimeoutExceeded(), _handleFocusLossTimeout(), _showFocusLossTimeoutOverlay(), focusLoss telemetry in exports
- `interactive_gym/scenes/gym_scene.py` - focus_loss_config() method, focus_loss_timeout_ms, focus_loss_message attributes

**Fast-Forward Resync (v1.5 Phase 26 - added):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - _performFastForward(), _pendingFastForward flag, FocusManager._onForegrounded hook

**Focus Management (v1.5 Phase 25 - added):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - FocusManager class, focusManager property, background checks in _handleWorkerTick and _handleInputPacket

**Web Worker Timer (v1.5 Phase 24 - modified):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - GameTimerWorker class, _initTimerWorker(), _handleWorkerTick()
- `interactive_gym/server/static/js/phaser_gym_graphics.js` - onWorkerTick(), Worker timing integration in update()

**Partner disconnection handling (v1.4 - modified):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - `_showPartnerDisconnectedOverlay()`, `_handleReconnectionGameEnd()`
- `interactive_gym/server/pyodide_game_coordinator.py` - `get_disconnected_player_id()`, `disconnected_player_id` tracking
- `interactive_gym/server/app.py` - `p2p_game_ended` event includes disconnected_player_id
- `interactive_gym/scenes/gym_scene.py` - `partner_disconnect_message_config()` method

**v1.1 Execution:**
- `.planning/phases/11-hash-infrastructure/11-01-SUMMARY.md`
- `.planning/phases/12-p2p-hash-exchange/12-01-SUMMARY.md`
- `.planning/phases/13-mismatch-detection/13-01-SUMMARY.md`
- `.planning/phases/14-validation-export/14-01-SUMMARY.md`
- `.planning/research/SUMMARY.md`
- `.planning/research/ARCHITECTURE.md`

**v1.2 Execution:**
- `.planning/phases/15-entry-screening-rules/15-01-SUMMARY.md`
- `.planning/phases/16-continuous-monitoring/16-01-SUMMARY.md`
- `.planning/phases/17-multiplayer-exclusion/17-01-SUMMARY.md`
- `.planning/phases/18-custom-callbacks/18-01-SUMMARY.md`

**v1.3 Execution:**
- `.planning/phases/19-waiting-room-validation/19-01-SUMMARY.md`
- `.planning/phases/20-mid-game-reconnection/20-01-SUMMARY.md`
- `.planning/phases/20-mid-game-reconnection/20-02-SUMMARY.md`
- `.planning/phases/21-per-round-health-check/21-01-SUMMARY.md`
- `.planning/phases/22-latency-telemetry/22-01-SUMMARY.md`

**v1.4 Execution:**
- `.planning/phases/23-partner-disconnect-handling/23-01-SUMMARY.md`

**v1.5 Execution:**
- `.planning/phases/24-web-worker-timer/24-01-SUMMARY.md`
- `.planning/phases/25-focus-detection/25-01-SUMMARY.md`
- `.planning/phases/26-resync-partner-ux/26-01-SUMMARY.md`
- `.planning/phases/27-timeout-telemetry/27-01-SUMMARY.md`

**v1.6 Execution:**
- `.planning/phases/28-pipeline-instrumentation/28-01-SUMMARY.md`

**v1.7 Execution:**
- `.planning/phases/32-dashboard-summary/32-01-SUMMARY.md`
- `.planning/phases/33-session-list/33-01-SUMMARY.md`
- `.planning/phases/34-session-detail/34-01-SUMMARY.md`
- `.planning/phases/35-layout-polish/35-01-SUMMARY.md`

**v1.8 Execution:**
- `.planning/phases/36-buffer-split/36-01-SUMMARY.md`
- `.planning/phases/37-fast-forward-fix/37-01-SUMMARY.md`
- `.planning/phases/38-episode-boundary/38-01-SUMMARY.md`
- `.planning/phases/39-verification-metadata/39-01-SUMMARY.md`

**v1.9 Execution:**
- `.planning/phases/40-test-infrastructure/40-01-SUMMARY.md`
- `.planning/phases/40-test-infrastructure/40-02-SUMMARY.md`
- `.planning/phases/41-latency-injection/41-01-SUMMARY.md`
- `.planning/phases/42-network-disruption/42-01-SUMMARY.md`
- `.planning/phases/43-data-comparison/43-01-SUMMARY.md`
- `.planning/phases/44-manual-test-protocol/44-01-SUMMARY.md`

**v1.10 Execution:**
- `.planning/phases/45-episode-completion-fix/45-01-SUMMARY.md`
- `.planning/phases/46-test-suite-verification/46-01-SUMMARY.md`
- `.planning/phases/47-focus-loss-testing/47-01-SUMMARY.md`

**v1.11 Execution:**
- `.planning/phases/48-isfocused-column-consistency/48-01-SUMMARY.md`
- `.planning/phases/49-episode-boundary-row-parity/49-01-SUMMARY.md`
- `.planning/phases/50-stress-test-verification/50-01-SUMMARY.md`

**v1.12 Execution:**
- `.planning/phases/51-diagnostic-logging/51-01-SUMMARY.md`
- `.planning/phases/52-comprehensive-cleanup/52-01-SUMMARY.md`
- `.planning/phases/53-session-lifecycle/53-01-SUMMARY.md`
- `.planning/phases/54-participant-state-tracker/54-01-SUMMARY.md`
- `.planning/phases/55-matchmaker-base-class/55-01-SUMMARY.md`
- `.planning/phases/55-matchmaker-base-class/55-02-SUMMARY.md`
- `.planning/phases/56-custom-attributes-logging/56-01-SUMMARY.md`

**v1.13 Execution:**
- `.planning/phases/57-p2p-probe-infrastructure/57-01-SUMMARY.md`
- `.planning/phases/57-p2p-probe-infrastructure/57-02-SUMMARY.md`
- `.planning/phases/58-rtt-measurement/58-01-SUMMARY.md`
- `.planning/phases/59-matchmaker-rtt-integration/59-01-SUMMARY.md`
- `.planning/phases/60-single-game-creation-path/60-01-SUMMARY.md`

**Single Game Creation Path (v1.13 Phase 60 - simplified):**
- `interactive_gym/server/game_manager.py` - Removed group reunion code (~230 lines), simplified add_subject_to_game() to single path
- `interactive_gym/server/app.py` - Removed remove_from_group_waitroom call
- `interactive_gym/server/admin/aggregator.py` - Removed group_waitrooms references

**Input Confirmation Protocol (v1.14 Phase 61 - added):**
- `interactive_gym/scenes/gym_scene.py` - input_confirmation_timeout_ms attribute (500ms default), pyodide() parameter
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - _waitForInputConfirmation() method, async _checkEpisodeSyncAndReset(), inputConfirmationTimeoutMs config

**P2P Input Redundancy (v1.14 Phase 63 - modified):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - encodeInputPacket limit 5→15, P2PInputSender redundancyCount 3→10, maxRecentInputs 10→20

**v1.14 Execution:**
- `.planning/phases/61-input-confirmation-protocol/61-01-SUMMARY.md`
- `.planning/phases/62-data-parity-validation/62-01-SUMMARY.md`
- `.planning/phases/63-parity-test-stabilization/63-01-SUMMARY.md`
- `.planning/phases/64-multi-participant-test-infrastructure/64-01-SUMMARY.md`
- `.planning/phases/65-multi-episode-lifecycle-stress-tests/65-01-SUMMARY.md`
- `.planning/phases/65-multi-episode-lifecycle-stress-tests/65-02-SUMMARY.md`

**v1.16 Execution:**
- `.planning/phases/67-core-worker-infrastructure/67-01-SUMMARY.md`
- `.planning/phases/68-remotegame-integration/68-01-SUMMARY.md`
- `.planning/phases/69-multiplayer-batch-operations/69-01-SUMMARY.md`
- `.planning/phases/69-multiplayer-batch-operations/69-02-SUMMARY.md`
- `.planning/phases/69-multiplayer-batch-operations/69-03-SUMMARY.md`
- `.planning/phases/70-validation-and-cleanup/70-01-SUMMARY.md`
- `.planning/phases/70-validation-and-cleanup/70-02-SUMMARY.md`

**Worker Bug Fixes (v1.16 Phase 70 Plan 02 - fixed):**
- `interactive_gym/server/static/js/pyodide_remote_game.js` - Pass interactiveGymGlobals via Worker globals (not js.window)
- `interactive_gym/server/static/js/pyodide_worker.js` - toJs({dict_converter: Object.fromEntries}) for postMessage-safe conversion; int key coercion for action dicts

**Stagger Delay Reduction (v1.16 Phase 70 Plan 01 - updated):**
- `tests/fixtures/multi_participant.py` - GameOrchestrator.start_all_games default stagger reduced from 5.0s to 0.5s
- `tests/e2e/test_multi_participant.py` - Both test call sites updated to stagger_delay_sec=0.5
- `tests/e2e/test_lifecycle_stress.py` - Both test call sites updated to stagger_delay_sec=0.5

**Batch Migration + Shim Removal (v1.16 Phase 69 Plan 03 - completed):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - performRollback() and _performFastForward() migrated to this.worker.batch(); zero this.pyodide references remain
- `interactive_gym/server/static/js/PyodideWorker.js` - runPythonAsync(), _wrapResult(), toPy() shims removed
- `interactive_gym/server/static/js/pyodide_worker.js` - handleRunPython removed, case 'runPython' removed from switch
- `interactive_gym/server/static/js/pyodide_remote_game.js` - this.pyodide = this.worker shim removed from initialize()

**Multiplayer Call Site Migration (v1.16 Phase 69 Plan 02 - modified):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - All 18 individual this.pyodide.runPythonAsync() calls replaced with structured this.worker.* commands

**Worker Protocol Extension (v1.16 Phase 69 Plan 01 - added):**
- `interactive_gym/server/static/js/pyodide_worker.js` - handleGetState, handleSetState, handleComputeHash, handleSeedRng, handleRender, handleBatch handlers + Internal variants; handleStep/handleReset refactored to Internal pattern
- `interactive_gym/server/static/js/PyodideWorker.js` - getState(), setState(), computeHash(), seedRng(), render(), batch() public async methods

**PyodideWorker Infrastructure (v1.16 Phase 67 - added):**
- `interactive_gym/server/static/js/pyodide_worker.js` - Worker script with READY gate pattern, typed message handlers
- `interactive_gym/server/static/js/PyodideWorker.js` - Main thread class with async init/step/reset API
- `interactive_gym/server/static/js/test_pyodide_worker.html` - Browser verification test page

**RemoteGame Worker Migration (v1.16 Phase 68 - modified):**
- `interactive_gym/server/static/js/pyodide_remote_game.js` - Uses PyodideWorker for all Pyodide operations, _convertToMap() for backward compat, _processRenderState() helper, destroy() method, this.pyodide = this.worker shim for multiplayer subclass
- `interactive_gym/server/static/js/pyodide_worker.js` - onGameStepCode extraction/storage/injection, obs/rewards normalization in step/reset, handleRunPython for arbitrary Python execution
- `interactive_gym/server/static/js/PyodideWorker.js` - runPythonAsync() shim, toPy() shim with toString()/toJs(), _wrapResult() for PyProxy-like return values
- `interactive_gym/server/static/js/test_pyodide_worker.html` - RemoteGame operations test with CartPole-v1

**Multi-Participant Test Infrastructure (v1.14 Phase 64 - added):**
- `tests/conftest.py` - multi_participant_contexts fixture for 6 browser contexts
- `tests/fixtures/multi_participant.py` - GameOrchestrator class, get_page_state(), log_page_state()
- `tests/e2e/test_multi_participant.py` - test_three_simultaneous_games, test_staggered_participant_arrival

**Participant State Reset (v1.14 Phase 64 - fixed):**
- `interactive_gym/server/app.py` - Reset participant state to IDLE on advance_scene, P2P validation failure, and session registration

**Matchmaker RTT Integration (v1.13 Phase 59 - added):**
- `interactive_gym/server/matchmaker.py` - max_p2p_rtt_ms param, should_reject_for_rtt() method
- `interactive_gym/server/game_manager.py` - probe_coordinator param, _pending_matches, _probe_and_create_game(), _on_probe_complete(), _remove_from_waitroom(), _create_game_for_match_internal()
- `interactive_gym/server/app.py` - probe_coordinator=PROBE_COORDINATOR passed to GameManager

**RTT Ping-Pong Protocol (v1.13 Phase 58 - added):**
- `interactive_gym/server/static/js/probe_connection.js` - pendingPings Map, _handleDataChannelMessage(), measureRTT(), _sendPing()
- `interactive_gym/server/static/js/index.js` - ProbeManager._onProbeConnected uses measureRTT()

**P2P Probe Infrastructure (v1.13 Phase 57 - added):**
- `interactive_gym/server/probe_coordinator.py` - ProbeCoordinator class for server-side probe orchestration
- `interactive_gym/server/app.py` - PROBE_COORDINATOR global, get_socket_for_subject(), probe_ready/probe_signal/probe_result handlers
- `interactive_gym/server/static/js/probe_connection.js` - ProbeConnection class wrapping WebRTCManager for probe-only use
- `interactive_gym/server/static/js/index.js` - ProbeManager object for client-side probe lifecycle handling

**Match Assignment Logging (v1.12 Phase 56 - added):**
- `interactive_gym/server/match_logger.py` - MatchAssignment dataclass, MatchAssignmentLogger class
- `interactive_gym/server/game_manager.py` - match_logger parameter, log_match() calls in _create_game_for_match()
- `interactive_gym/server/app.py` - MATCH_LOGGER global, passed to GameManager

**Matchmaker Base Class (v1.12 Phase 55 - added):**
- `interactive_gym/server/matchmaker.py` - Matchmaker ABC with @abstractmethod find_match(), MatchCandidate dataclass, FIFOMatchmaker implementation
- `interactive_gym/server/game_manager.py` - matchmaker parameter in __init__(), find_match() delegation in _add_to_fifo_queue()
- `interactive_gym/scenes/gym_scene.py` - GymScene.matchmaking() matchmaker parameter, _matchmaker attribute, matchmaker property
- `interactive_gym/server/app.py` - matchmaker=scene.matchmaker passed to GameManager

**ParticipantStateTracker (v1.12 Phase 54 - added):**
- `interactive_gym/server/participant_state.py` - ParticipantState enum (IDLE, IN_WAITROOM, IN_GAME, GAME_ENDED), VALID_TRANSITIONS, ParticipantStateTracker class
- `interactive_gym/server/app.py` - PARTICIPANT_TRACKER global, can_join_waitroom() check in join_game, state transitions at game completion handlers
- `interactive_gym/server/game_manager.py` - participant_state_tracker parameter, IN_GAME/GAME_ENDED transitions

**Session Lifecycle (v1.12 Phase 53 - added):**
- `interactive_gym/server/remote_game.py` - SessionState enum (WAITING, MATCHED, VALIDATING, PLAYING, ENDED), VALID_TRANSITIONS, transition_to() method
- `interactive_gym/server/game_manager.py` - State transitions at MATCHED, PLAYING, ENDED points
- `interactive_gym/server/pyodide_game_coordinator.py` - game_manager_getter callback, VALIDATING/PLAYING transitions

**Comprehensive Cleanup (v1.12 Phase 52 - added):**
- `interactive_gym/server/game_manager.py` - cleanup_game() now idempotent with subject-level cleanup
- `interactive_gym/server/app.py` - All exit paths (reconnection timeout, validation failed, mid-game exclusion) call cleanup_game()

**Diagnostic Logging Infrastructure (v1.12 Phase 51 - added):**
- `interactive_gym/server/app.py` - [JoinGame:Diag] diagnostic logging at join_game entry, state validation integration, waiting_room_error event, post-add state counts
- `interactive_gym/server/game_manager.py` - validate_subject_state() method with [StateValidation] logging and auto-cleanup

### Decisions

See: .planning/PROJECT.md Key Decisions table

**v1.13 Phase 60 decisions:**
- Remove group reunion code entirely (not just disable) - dead code creates maintenance burden
- Log warning when wait_for_known_group=True rather than error - avoids breaking existing configs
- Preserve _add_subject_to_specific_game (shared by matchmaker path via _create_game_for_match_internal)
- Document group reunion as future REUN-01/REUN-02 matchmaker variant

**v1.13 Phase 59 decisions:**
- P2P RTT filtering after matchmaker proposes (not inside find_match)
- Candidates added to waitroom during probe (stay there on rejection)
- None threshold = no probing (default behavior unchanged)
- Measurement failure (None RTT) triggers rejection for safety
- _pending_matches keyed by probe_session_id for async callback lookup

**v1.13 Phase 58 decisions:**
- JSON message format for ping/pong (not binary) - small payload, simplicity over micro-optimization
- 5 pings default, 2s timeout per ping, 100ms interval - balance stability and speed
- Median over mean for RTT aggregation - robust to outliers
- No stabilization delay before ping-pong - getStats() needed it, ping-pong measures directly

**v1.13 Phase 57 decisions:**
- Probes work independently of games (no game_id needed, only subject_ids)
- Two-phase initialization (prepare -> ready -> start) prevents signaling race conditions
- Fresh socket lookup via get_socket_for_subject() avoids stale socket references
- Separate probe_* events from webrtc_signal to avoid collision with game signaling
- 15 second default timeout for entire probe lifecycle
- on_complete callback receives None RTT on failure or timeout
- ProbeConnection wraps WebRTCManager, overrides _sendSignal for probe routing
- 10 second client-side connection timeout for probes

**v1.12 Phase 56 decisions:**
- Synchronous file I/O (no threading) - match rate is low, simplicity preferred
- Shared MATCH_LOGGER instance across all scenes (initialized once)
- Admin activity logged with first participant as subject_id (for timeline)

**v1.12 Phase 55 decisions:**
- FIFOMatchmaker produces identical behavior to original code
- RTT filtering applied before matchmaker (not inside matchmaker)
- matchmaker parameter optional for backward compatibility
- MatchCandidate dataclass extensible for Phase 56 custom attributes
- TYPE_CHECKING import avoids circular dependency (scene imports matchmaker at runtime only when needed)
- scene.matchmaker property returns None for default (GameManager handles None by using FIFO)

**v1.12 Phase 54 decisions:**
- ParticipantState is complementary to SessionState (participant lifecycle vs game lifecycle)
- IDLE is implicit (not tracked) - only tracked when in waitroom/game/ended
- transition_to() returns bool and logs invalid transitions (doesn't throw)
- participant_state_tracker parameter optional in GameManager for backward compatibility

**v1.12 Phase 53 decisions:**
- SessionState is orthogonal to GameStatus (lifecycle vs game-loop phase)
- transition_to() returns bool and logs invalid transitions (doesn't throw)
- VALIDATING state only used for P2P multiplayer games
- game_manager_getter callback pattern for coordinator to access RemoteGameV2

**v1.12 Phase 52 decisions:**
- cleanup_game() checks game_id in self.games and returns early if not found (idempotent)
- cleanup_game() iterates all human_players.values() to clean subject_games and subject_rooms
- All exit paths find GameManager by game_id and call cleanup_game() consistently

**v1.12 Phase 51 decisions:**
- Log full state snapshot at join_game entry (subject_games, active_games, waiting_games)
- Auto-cleanup orphaned entries during validation rather than returning error (self-healing)
- waiting_room_error event includes error_code and details for client debugging
- Consistent log prefixes: [JoinGame:Diag] for diagnostics, [StateValidation] for validation

**v1.14 Phase 61 decisions:**
- 500ms default timeout handles 200ms+ RTT with margin for packet retransmission
- Timeout triggers graceful degradation (warning log, proceed) not crash
- Only P2P mode waits for confirmation (server-authoritative has different sync)
- 10ms polling interval allows event loop to process incoming packets

**v1.14 Phase 62 decisions:**
- No code changes needed - Phase 61 fix validated by existing tests
- Minor row count differences (within 10-row tolerance) are acceptable under high latency
- PARITY-03, PARITY-04, PARITY-05 requirements satisfied

**v1.14 Phase 63 decisions:**
- Root cause: 3 redundant inputs insufficient under 15% packet loss (P(all lost) ≈ 0.34%/input × 450 frames = ~1.5 losses/episode)
- Solution: Increase redundancy from 3 to 10 inputs per packet (P(all lost) ≈ 0.15^10 ≈ 0)
- Packet limit increased from 5 to 15 to accommodate higher redundancy
- Test timeout kept at 2000ms (sufficient with redundancy fix)
- Test packet loss kept at 15% (original specification)
- PARITY-06, PARITY-07 requirements satisfied (10/10 consecutive passes)

**v1.14 Phase 64 decisions:**
- 5 second stagger between games required for P2P connections to establish without competing for resources
- Per-pair orchestration: each game pair completes full startup before next pair begins
- 0.5s delay between partner Start clicks ensures first player enters waitroom before second clicks
- Reset participant state on advance_scene to prevent IN_GAME state from previous scene blocking new games
- Reset participant state after P2P validation failure to allow re-pooling
- STRESS-01 requirement satisfied (6 contexts, 3 concurrent games with data parity)

**v1.14 Phase 65 decisions:**
- Games must NOT be pre-created in waitroom - only created when matchmaker forms complete match (GAME-01 fix)
- Socket.IO emits must occur outside threading.Lock() blocks to avoid eventlet deadlocks
- waitroom_participants list tracks waiting subjects without pre-allocated games
- P2P validation timeout (10s) may cause failures under concurrent load - known infrastructure limitation
- STRESS-02 through STRESS-07 test implementations complete

**v1.16 Phase 67 decisions:**
- Separate .js file for Worker (not inline Blob) for easier debugging
- READY gate pattern with messageQueue prevents race conditions
- toJs({dict_converter: Object.fromEntries}) for PyProxy conversion before postMessage (updated from depth:2 in Phase 70)
- destroy() cleans PyProxy references to prevent memory leaks

**v1.16 Phase 69 Plan 02 decisions:**
- validateStateSync uses getState() probe instead of Python hasattr check
- Server-auth reset path: reset() + setState() + render() sequence replaces monolithic Python block
- loadStateSnapshot drops verification step (before/after state comparison) - setState is tested Worker command
- applyServerState wraps env_state in {env_state: ...} for setState compatibility
- computeHash() now uses SHA-256 (Worker) instead of MD5 (old inline Python) - both peers use same algorithm

**v1.16 Phase 69 Plan 03 decisions:**
- Batch rollback includes computeHash ops for debug logging parity with original Python
- Hash computation uses SHA-256 (Worker) instead of MD5 (original Python) - consistent with Plan 02 migration
- Batch rollback includes trailing getState for post-replay state capture
- Null-safe type conversion: check instanceof Map, typeof object with null guard, fallback to { human: value }

**v1.16 Phase 69 Plan 01 decisions:**
- Internal/External handler split: *Internal does work and returns, * wraps with postMessage for batch reuse
- getState returns raw JSON string (caller parses) for minimal transfer overhead
- computeHash normalizes floats to 10 decimal places for deterministic cross-platform hashing
- Batch error includes failedIndex and partialResults for precise error reporting
- handleRunPython and backward-compat shims preserved for Plan 02/03 migration

**v1.16 Phase 70 Plan 01 decisions:**
- Stagger delay reduced to 0.5s (not 0s) - WebRTC signaling needs inter-pair delay
- Pre-existing Pyodide Worker loading issue prevents E2E test execution - not caused by stagger change
- All E2E tests (including basic 2-player) fail at wait_for_start_button_enabled with 60s timeout
- Root cause: PyodideWorker.init() never resolves (Worker thread fails to complete Pyodide initialization)

**v1.16 Phase 70 Plan 02 decisions:**
- toJs({dict_converter: Object.fromEntries}) without depth limit — unlimited depth ensures all nested PyProxy objects are fully converted for postMessage
- Action key int coercion after json.loads() — JSON serialization turns all keys to strings, but Python envs expect int agent IDs
- interactiveGymGlobals via Worker globals payload — Workers have no window object, so js.window.interactiveGymGlobals fails
- Manual browser verification over automated E2E — bugs had to be fixed before E2E infrastructure could work

**v1.16 Phase 68 decisions:**
- Convert Worker plain-object results to Map for downstream compatibility (obs.keys(), rewards.entries())
- Extract on_game_step_code from globals in Worker JS variable, inject via template literal
- Keep normalization logic in Worker to avoid PyProxy transfer overhead
- Add depth check for RGB array detection (3 nested arrays) vs object list
- Backward-compat shim: this.pyodide = this.worker, so MultiplayerPyodideGame subclass doesn't crash
- runPythonAsync() via Worker for arbitrary Python execution (shim for multiplayer)
- toPy() returns wrapper with toString() for template embedding and toJs() for passthrough
- _wrapResult() adds .toJs({dict_converter}) and .destroy() to runPythonAsync results
- All shims are temporary, will be removed in Phase 69 when multiplayer migrates

### Pending Todos

(None)

### Blockers/Concerns

**Pyodide Worker Loading Issue (RESOLVED in Phase 70 Plan 02):**
- Root cause: js.window access in Worker context (Workers have no window object)
- Fixed by passing interactiveGymGlobals via Worker globals payload (commit 9e733d5)
- Additional fixes: toJs DataCloneError (c9477dc), action key type mismatch (ec0e492)

**Known issues to address in future milestones:**
- Episode start sync can timeout on slow connections (mitigated with retry + two-way ack)
- Rollback visual corrections cause brief teleporting (smoothing not yet implemented)

**Deferred from v1.6:**
- Input latency root cause fix (tooling now exists via Phase 28 instrumentation)
- Users can use `[LATENCY]` console logs to diagnose specific issues

**Deferred from v1.13:**
- Group reunion feature deferred to REUN-01/REUN-02 as future matchmaker variant
- wait_for_known_group=True logs warning but uses FIFO matching

## Session Continuity

Last session: 2026-02-05
Stopped at: Completed v1.16 Pyodide Web Worker milestone (all phases 67-70 done)
Resume file: None

### Next Steps

**v1.16 Pyodide Web Worker milestone complete.** All phases (67-70) shipped.
- Phase 67: Core Worker infrastructure (pyodide_worker.js, PyodideWorker.js)
- Phase 68: RemoteGame integration (single-player via Worker)
- Phase 69: Multiplayer batch operations (GGPO rollback via Worker)
- Phase 70: Validation and cleanup (3 bug fixes, manual multiplayer verification)

**Key commits in Phase 70:**
- `32886a4` — Reduce stagger delay from 5.0s to 0.5s
- `9e733d5` — Fix js.window in Worker context
- `c9477dc` — Fix DataCloneError with dict_converter
- `ec0e492` — Fix action key string-to-int conversion

**Next milestone:** Not yet planned. Consider `/gsd:new-milestone` to define next work.
