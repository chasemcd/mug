# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-06)

**Core value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.
**Current focus:** v1.17 E2E Test Reliability — Phase 72 (Latency Test Diagnosis)

## Current Position

Milestone: v1.17 E2E Test Reliability
Phase: 72 of 74 (Latency Test Diagnosis)
Plan: 01 of 2 complete
Status: In progress
Last activity: 2026-02-06 — Completed 72-01-PLAN.md (root cause identified)

Progress: ███▓░░░░░░ 37%

## Milestone History

| Milestone | Phases | Status | Shipped |
|-----------|--------|--------|---------|
| v1.17 E2E Test Reliability | 71-74 | In progress | - |
| v1.16 Pyodide Pre-loading | 67-70 | Complete | 2026-02-06 |
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
- `.planning/phases/67-pyodide-preload-infrastructure/67-01-SUMMARY.md`
- `.planning/phases/68-shared-instance-integration/68-01-SUMMARY.md`
- `.planning/phases/69-server-init-grace/69-01-SUMMARY.md`
- `.planning/phases/70-validation-test-stabilization/70-01-SUMMARY.md`

**v1.17 Execution:**
- `.planning/phases/71-test-infrastructure-fix/71-01-SUMMARY.md`
- `.planning/phases/71-test-infrastructure-fix/71-02-SUMMARY.md`
- `.planning/phases/72-latency-test-diagnosis/72-01-SUMMARY.md`

**Robust Server Fixture Lifecycle (v1.17 Phase 71 - added):**
- `tests/conftest.py` - _is_port_free(), _ensure_port_available(), _wait_for_port_free(), _teardown_server() shared helpers; all 5 server fixtures refactored to use them; start_new_session=True on all Popen; stdout=DEVNULL

**Focus Loss Boundary Test Isolation (v1.17 Phase 71-02 - extracted):**
- `tests/e2e/test_focus_loss_data_parity.py` - Extracted test_focus_loss_episode_boundary_parity from test_data_comparison.py into its own module for fresh flask_server instance
- `tests/e2e/test_data_comparison.py` - Removed test_focus_loss_episode_boundary_parity (4 tests remain)

**Validation & Test Stabilization (v1.16 Phase 70 - validated):**
- `tests/fixtures/multi_participant.py` - GameOrchestrator.start_all_games() default stagger_delay_sec changed from 5.0 to 0.5
- `tests/e2e/test_multi_participant.py` - Both test call sites updated from stagger_delay_sec=5.0 to 0.5
- `tests/e2e/test_lifecycle_stress.py` - Both test call sites updated from stagger_delay_sec=5.0 to 0.5
- `.planning/phases/70-validation-test-stabilization/70-01-SUMMARY.md`

**Server-Side Init Grace (v1.16 Phase 69 - added):**
- `interactive_gym/server/app.py` - ping_timeout increased 8→30, LOADING_CLIENTS dict, LOADING_TIMEOUT_S=60, is_client_in_loading_grace(), pyodide_loading_start/complete handlers, grace check early return in on_disconnect()
- `interactive_gym/server/static/js/index.js` - preloadPyodide() emits loading_start before loadPyodide() with 50ms yield, loading_complete on success/error
- `interactive_gym/server/static/js/pyodide_remote_game.js` - fallback path emits loading_start/complete with 50ms yield
- `.planning/phases/69-server-init-grace/69-01-SUMMARY.md`

**Server-side Init Grace (v1.16 Phase 69 - added):**
- `interactive_gym/server/app.py` - LOADING_CLIENTS dict, LOADING_TIMEOUT_S=60, is_client_in_loading_grace(), pyodide_loading_start/complete handlers, grace check in on_disconnect(), ping_timeout=30
- `interactive_gym/server/static/js/index.js` - preloadPyodide() emits pyodide_loading_start/complete with 50ms yield
- `interactive_gym/server/static/js/pyodide_remote_game.js` - RemoteGame.initialize() fallback emits pyodide_loading_start/complete with 50ms yield

**Shared Instance Integration (v1.16 Phase 68 - modified):**
- `interactive_gym/server/static/js/pyodide_remote_game.js` - RemoteGame.initialize() checks window.pyodidePreloadStatus/pyodideInstance, reuses preloaded instance with package dedup fallback
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - MultiplayerPyodideGame.initialize() logs which init path will be used

**Pyodide Pre-load Infrastructure (v1.16 Phase 67 - added):**
- `interactive_gym/configurations/experiment_config.py` - get_pyodide_config() scans stager scenes for Pyodide requirements
- `interactive_gym/configurations/remote_config.py` - get_pyodide_config() returns own settings, get_entry_screening_config() safe defaults
- `interactive_gym/server/app.py` - pyodide_config included in experiment_config socket event
- `interactive_gym/server/static/templates/index.html` - #pyodideLoader element (spinner + status text)
- `interactive_gym/server/static/js/index.js` - preloadPyodide(), window.pyodideInstance/pyodideMicropip/pyodidePreloadStatus, advancement gating

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

**v1.17 Phase 72-01 decisions:**
- 200ms latency test timeout is intermittent, not deterministic (P2P ready gate race at 5000ms boundary)
- P2P validation takes ~4-5s under 200ms symmetric CDP latency, right at the 5000ms gate timeout
- When race is lost: p2p_validation_failed -> re-pool -> re-match -> infinite loop with 2 test players
- CDP latency does NOT affect WebRTC DataChannel (Chromium issue 41215664) -- test validates setup/signaling, not gameplay
- 95% of inputs route through SocketIO relay, 5% via P2P DataChannel; zero rollbacks despite relay mode
- Fix direction: increase P2P ready gate timeout from 5000ms to 15000ms (Plan 02)
- Diagnostic instrumentation left in place behind diagnostics= flag for future use

**v1.17 Phase 71 decisions:**
- socket.bind() for port checks (not connect-based, which can succeed during TIME_WAIT)
- lsof for stale PID discovery as last-resort cleanup in _ensure_port_available
- stdout=DEVNULL for all fixtures (stderr kept as PIPE for crash diagnostics only)
- flask_server_multi_episode: read stderr before teardown, write empty bytes for stdout debug file
- test_focus_loss_episode_boundary_parity within-module failure is server state accumulation, not port teardown
- Module isolation fix: extract test to own module for fresh flask_server rather than changing fixture scope or adding server state cleanup

**v1.16 approach decision:**
- Pre-load over Web Worker: per-frame runPythonAsync (10-100ms) doesn't cause disconnects; only loadPyodide (5-15s) does
- Pre-loading during compat check eliminates concurrent init at game start
- Web Worker deferred until per-frame blocking becomes a problem
- Preserves synchronous rollback path (no async Worker message overhead)

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

**v1.16 Phase 70 decisions:**
- 0.5s stagger sufficient for concurrent game starts with Pyodide pre-loading (down from 5.0s)
- Pre-existing E2E test flakiness (Page.goto timeout, 200ms latency test timeout) deferred to future milestone
- Network disruption tests skipped during validation; not related to stagger change

**v1.16 Phase 69 decisions:**
- ping_timeout=30 (not 20) for generous margin (38s total vs 15s worst-case Pyodide load)
- Dict with timestamps (not set) enables 60s safety timeout preventing unbounded LOADING_CLIENTS growth
- Grace check before admin logging -- early return preserves session but skips ALL destructive actions
- 50ms yield before loadPyodide() ensures socket.emit is sent before main thread blocks
- Error path sends loading_complete to prevent ghost entries in LOADING_CLIENTS

**v1.16 Phase 69 decisions:**
- ping_timeout increased from 8 to 30 (total grace: 8+30=38s, well beyond 15s worst-case Pyodide load)
- P2P WebRTC disconnect detection at 500ms makes weakened server-level detection acceptable
- LOADING_CLIENTS keyed by subject_id with time.time() timestamp for per-client tracking
- 60s safety timeout prevents unbounded LOADING_CLIENTS growth from stuck clients
- Grace check is an early return in on_disconnect() that preserves session state but skips all destructive actions
- 50ms yield (setTimeout) before loadPyodide() ensures socket emit is sent before main thread blocks
- Both paths (preload in index.js, fallback in RemoteGame) send loading signals
- Error path in preload also sends loading_complete with { error: true } to clear server grace state

**v1.16 Phase 68 decisions:**
- Check both window.pyodidePreloadStatus === 'ready' AND window.pyodideInstance truthy before reuse
- Fallback else branch runs original loadPyodide() path unchanged for backward compatibility
- Package dedup: filter packages_to_install against installed_packages before micropip.install()
- MultiplayerPyodideGame gets only a log line; inherits all changes via super.initialize()

**v1.16 Phase 67 decisions:**
- Scan GENERIC_STAGER scenes via unpack() to detect Pyodide need at experiment level
- preloadPyodide() called without await (fire-and-forget, concurrent with entry screening)
- Preload failure sets status to 'error' but does NOT block advancement (graceful fallback)
- Phase 67 intentionally does NOT modify RemoteGame/MultiplayerPyodideGame (that's Phase 68)
- Double loadPyodide() is expected until Phase 68 wires game classes to reuse window.pyodideInstance

**v1.14 Phase 65 decisions:**
- Games must NOT be pre-created in waitroom - only created when matchmaker forms complete match (GAME-01 fix)
- Socket.IO emits must occur outside threading.Lock() blocks to avoid eventlet deadlocks
- waitroom_participants list tracks waiting subjects without pre-allocated games
- P2P validation timeout (10s) may cause failures under concurrent load - known infrastructure limitation
- STRESS-02 through STRESS-07 test implementations complete

### Pending Todos

(None)

### Blockers/Concerns

**Known issues to address in future milestones:**
- Episode start sync can timeout on slow connections (mitigated with retry + two-way ack)
- Rollback visual corrections cause brief teleporting (smoothing not yet implemented)

**Deferred from v1.6:**
- Input latency root cause fix (tooling now exists via Phase 28 instrumentation)
- Users can use `[LATENCY]` console logs to diagnose specific issues

**Deferred from v1.13:**
- Group reunion feature deferred to REUN-01/REUN-02 as future matchmaker variant
- wait_for_known_group=True logs warning but uses FIFO matching

**Known E2E test failures (v1.17 targets):**
- test_focus_loss_episode_boundary_parity: FIXED (71-02 extracted to own module; passes back-to-back with test_data_comparison.py)
- test_episode_completion_under_fixed_latency[chromium-200]: DIAGNOSED (72-01) -- intermittent P2P ready gate race at 5000ms boundary; fix: increase gate timeout to 15000ms (Plan 72-02)
- test_network_disruption suite: not validated -- needs full run and any failures addressed

## Session Continuity

Last session: 2026-02-06
Stopped at: Completed 72-01-PLAN.md (root cause identified)
Resume file: None

### Next Steps

**Phase 72 Plan 01 (Latency Test Diagnosis) complete.**

Root cause identified: intermittent P2P ready gate race at 5000ms boundary under 200ms CDP latency.

Next action: Execute Plan 72-02 (apply fix: increase P2P ready gate timeout)
