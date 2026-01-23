# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-23)

**Core value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.
**Current focus:** v1.6 Input Latency Diagnosis & Fix

## Current Position

Phase: 28 of 31 (Pipeline Instrumentation)
Plan: 01 of 01 (Complete)
Status: Phase complete
Last activity: 2026-01-23 — Completed 28-01-PLAN.md

Progress: [===-------] 25% (v1.6 - 1/4 phases)

## Milestone History

| Milestone | Phases | Status | Shipped |
|-----------|--------|--------|---------|
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

**Pipeline Instrumentation (v1.6 Phase 28 - added):**
- `interactive_gym/server/static/js/ui_utils.js` - Keypress timestamp capture (DIAG-01)
- `interactive_gym/server/static/js/phaser_gym_graphics.js` - Input queue timestamps, render timestamps, timestamp propagation
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - pipelineMetrics object, setInputTimestamps(), logPipelineLatency()
- `interactive_gym/server/static/js/pyodide_remote_game.js` - Same instrumentation for single-player

### Decisions

See: .planning/PROJECT.md Key Decisions table

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

**[CRITICAL] v1.6 focus:**
- Users report 1-2 second local input lag in Overcooked
- Unknown if single-player, multiplayer, or both affected
- Unknown if consistent or intermittent

## Session Continuity

Last session: 2026-01-23
Stopped at: Completed 28-01-PLAN.md (Pipeline Instrumentation)
Resume file: None

### Next Steps

Phase 29 (Diagnosis) can now analyze latency logs to identify the root cause of reported 1-2 second input lag.

Expected workflow:
1. Start game, open browser console
2. Observe `[LATENCY]` logs with breakdown
3. Identify which pipeline stage(s) contribute to lag:
   - High queue time = input buffering issue
   - High step time = Pyodide execution bottleneck
   - High render time = Phaser rendering issue
   - Total >> sum = frame timing/throttling issue
