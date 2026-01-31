# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-30)

**Core value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.
**Current focus:** v1.8 Data Export Parity

## Current Position

Phase: 37 of 39 (Fast-Forward Data Recording Fix)
Plan: Not started
Status: Ready to plan
Last activity: 2026-01-30 — Phase 36 verified and complete

Progress: [██░░░░░░░░] 25% (v1.8 - Data Export Parity: 1/4 phases)

## Milestone History

| Milestone | Phases | Status | Shipped |
|-----------|--------|--------|---------|
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

**Dual-Buffer Data Recording (v1.8 Phase 36 - added):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - speculativeFrameData Map, _promoteConfirmedFrames(), extended clearFrameDataFromRollback()

**Session Detail View (v1.7 Phase 34 - added):**
- `interactive_gym/server/admin/aggregator.py` - _session_terminations, record_session_termination(), get_session_detail()
- `interactive_gym/server/admin/static/admin.js` - showSessionDetail(), closeSessionDetail(), renderSessionDetailContent(), renderPlayerHealth()
- `interactive_gym/server/admin/static/admin.css` - Session detail panel styles
- `interactive_gym/server/admin/templates/dashboard.html` - Session detail overlay panel
- `interactive_gym/server/app.py` - Termination recording in p2p_reconnection_timeout, mid_game_exclusion

**Layout Polish (v1.7 Phase 35 - modified):**
- `interactive_gym/server/admin/templates/dashboard.html` - Restructured layout (sessions 8-col, sidebar 4-col), problems indicator
- `interactive_gym/server/admin/static/admin.css` - Problems indicator, expanded session list, compact participant list styles
- `interactive_gym/server/admin/static/admin.js` - updateProblemsIndicator(), scrollToProblems(), compact participant rendering

**Dashboard Summary Stats (v1.7 Phase 32 - added):**
- `interactive_gym/server/admin/aggregator.py` - track_session_start(), record_session_completion(), summary stats in get_experiment_snapshot()
- `interactive_gym/server/admin/templates/dashboard.html` - Completion Rate and Avg Duration stat cards
- `interactive_gym/server/admin/static/admin.js` - updateSummaryStats(), formatDurationLong()

**Session List with P2P Health (v1.7 Phase 33 - added):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - _reportP2PHealth(), _startP2PHealthReporting(), _stopP2PHealthReporting()
- `interactive_gym/server/app.py` - p2p_health_report SocketIO handler
- `interactive_gym/server/admin/aggregator.py` - _p2p_health_cache, receive_p2p_health(), _get_p2p_health_for_game(), _compute_session_health()
- `interactive_gym/server/admin/templates/dashboard.html` - Active Sessions section with health legend
- `interactive_gym/server/admin/static/admin.js` - updateSessionList(), renderSessionCard(), getConnectionTypeLabel()
- `interactive_gym/server/admin/static/admin.css` - Session card styles, health indicators

**Pipeline Instrumentation (v1.6 Phase 28 - added):**
- `interactive_gym/server/static/js/ui_utils.js` - Keypress timestamp capture (DIAG-01)
- `interactive_gym/server/static/js/phaser_gym_graphics.js` - Input queue timestamps, render timestamps, timestamp propagation
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - pipelineMetrics object, setInputTimestamps(), logPipelineLatency()
- `interactive_gym/server/static/js/pyodide_remote_game.js` - Same instrumentation for single-player

### Decisions

See: .planning/PROJECT.md Key Decisions table

**v1.7 Phase 35 decisions:**
- Active sessions promoted to 8-column primary area (was in sidebar)
- Participants demoted to compact sidebar list (was 8-column cards)
- Problems indicator scrolls to console logs and filters to errors
- Session cards use responsive grid (auto-fill, minmax 320px)

**v1.7 Phase 34 decisions:**
- Detail panel slides in from right (standard UI pattern)
- Termination reasons use semantic codes (partner_disconnected, sustained_ping, tab_hidden, exclusion, focus_loss_timeout, normal)
- Console logs filtered to session participants, limited to 20 errors/warnings
- Real-time panel updates when session state changes

**v1.7 Phase 33 decisions:**
- Health status thresholds: latency >150ms or ICE state checking/disconnected = degraded
- Health report interval: 2 seconds to balance responsiveness vs overhead
- Health cache expiry: 10 seconds to auto-clean stale entries
- SocketIO fallback treated as degraded status (not error)

**v1.7 Phase 32 decisions:**
- Completion rate uses processed_subjects list for completed count
- Duration calculated from ParticipantSession.created_at to completion time
- Stats format: "X of Y (Z%)" for completion, human-readable for duration

**v1.5 Phase 27 decisions:**
- Focus loss timeout defaults to 30 seconds, set to 0 to disable
- Timeout only triggers while backgrounded (checked each worker tick)
- Reuses partner disconnect overlay pattern for consistent UX
- All three export methods include focus loss telemetry for research

**v1.5 Phase 26 decisions:**
- Fast-forward is async with error handling to not block tick processing
- Safety limits: MAX_FRAMES=300, MAX_MS=1000 prevent browser freeze
- Bot actions use lastExecutedActions or defaultAction during fast-forward
- Snapshots and hashes skipped during fast-forward for performance

**v1.5 Phase 25 decisions:**
- Worker keeps ticking when backgrounded (for elapsed time tracking), but frames don't advance
- Partner inputs buffered in FocusManager.backgroundInputBuffer for Phase 26 fast-forward
- Periodic logging every ~50 ticks (5s at 10 FPS) during background state

**v1.5 Phase 24 decisions:**
- Inline Blob Worker instead of separate file (simpler deployment)
- Worker ticks trigger game logic; RAF loop only renders
- Processing guard (isProcessingTick) prevents overlapping async operations

**v1.6 Phase 28 decisions:**
- Console log format: `[LATENCY] frame=N total=Xms | queue=Yms step=Zms render=Wms`
- Log every frame for first 50, then every 10th frame (reduce noise)
- Pass timestamps via setInputTimestamps() method rather than step() parameter (backward compatible)
- Skip logging during fast-forward or background states

**v1.8 Phase 36 decisions:**
- Dual-buffer architecture: speculativeFrameData for unconfirmed, frameDataBuffer for confirmed
- Promotion at end of _updateConfirmedFrame() after confirmedFrame advances
- Both buffers cleared on rollback and episode reset

**v1.4 decisions:**
- In-page overlay instead of redirect for partner disconnection (preserves data, better UX)

**v1.3 post-milestone fix:**
- Reduced disconnect grace period from 3s to 500ms for faster connection loss detection
- Added aggressive SocketIO ping settings (2s interval, 2s timeout)

### Pending Todos

(None)

### Blockers/Concerns

**Known issues to address in future milestones:**
- Episode start sync can timeout on slow connections (mitigated with retry + two-way ack)
- Rollback visual corrections cause brief teleporting (smoothing not yet implemented)

**Deferred from v1.6:**
- Input latency root cause fix (tooling now exists via Phase 28 instrumentation)
- Users can use `[LATENCY]` console logs to diagnose specific issues

**v1.8 Focus:**
- Data export parity issues — players' exported data diverges after rollbacks/fast-forward
- Need to ensure only validated (post-rollback, post-fast-forward) state is recorded

## Session Continuity

Last session: 2026-01-30
Stopped at: Phase 36 execution complete
Resume file: None

### Next Steps

Run `/gsd:plan-phase 37` to create detailed plan for Fast-Forward Data Recording Fix.
