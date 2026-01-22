# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-21)

**Core value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.
**Current focus:** v1.3 P2P Connection Validation

## Current Position

Phase: 21 of 22 (Per-Round Health Check)
Plan: Not started
Status: Ready to plan
Last activity: 2026-01-22 — Phase 20 complete (Mid-Game Reconnection)

Progress: [█████░░░░░] 50% (v1.3 - 2/4 phases complete)

## Milestone History

| Milestone | Phases | Status | Shipped |
|-----------|--------|--------|---------|
| v1.3 P2P Connection Validation | 19-22 | In progress | - |
| v1.2 Participant Exclusion | 15-18 | Complete | 2026-01-22 |
| v1.1 Sync Validation | 11-14 | Complete | - |
| v1.0 P2P Multiplayer | 1-10 | Complete | 2026-01-19 |

## Accumulated Context

### Key Files

**P2P Core (created/heavily modified in v1.0):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` (4,800+ LOC)
- `interactive_gym/server/static/js/webrtc_manager.js` (759 LOC)
- `interactive_gym/server/pyodide_game_coordinator.py`
- `interactive_gym/configurations/remote_config.py`

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

**Phase 16 Key Files:**
- `interactive_gym/server/static/js/continuous_monitor.js` (320+ LOC) - Extended with callback support
- `interactive_gym/scenes/gym_scene.py` - continuous_monitoring() and exclusion_callbacks() methods

**Phase 17 Key Files:**
- `interactive_gym/server/app.py` - mid_game_exclusion socket handler
- `interactive_gym/server/pyodide_game_coordinator.py` - handle_player_exclusion() method

**Phase 18 Key Files:**
- `interactive_gym/scenes/gym_scene.py` - exclusion_callbacks() method added
- `interactive_gym/server/app.py` - execute_entry_callback, execute_continuous_callback handlers
- `interactive_gym/server/static/js/index.js` - executeEntryCallback() function
- `interactive_gym/server/static/js/continuous_monitor.js` - shouldExecuteCallback(), setCallbackResult()
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - _executeContinuousCallback()

**Phase 19 Key Files:**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - P2P validation state machine, validation handshake
- `interactive_gym/server/pyodide_game_coordinator.py` - record_validation_success(), handle_validation_failure()
- `interactive_gym/server/app.py` - p2p_validation_* socket handlers
- `interactive_gym/server/static/js/index.js` - p2p_validation_* UI handlers

**Phase 20 Key Files (Plan 01):**
- `interactive_gym/server/static/js/webrtc_manager.js` - onConnectionLost/onConnectionRestored callbacks, 3s grace period
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - reconnectionState object, pause handling
- `interactive_gym/server/pyodide_game_coordinator.py` - handle_connection_lost(), handle_reconnection_success/timeout()
- `interactive_gym/server/app.py` - p2p_connection_lost, p2p_reconnection_* socket handlers

**Phase 20 Key Files (Plan 02):**
- `interactive_gym/server/static/js/webrtc_manager.js` - attemptIceRestart(), isConnectionUsable()
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - overlay UI, reconnection success/resume handlers
- `interactive_gym/scenes/gym_scene.py` - reconnection_config() builder, reconnection_timeout_ms attribute

### Decisions

See: .planning/PROJECT.md Key Decisions table

**v1.1 decisions (Phase 11):**
- SHA-256 (not MD5) for cross-platform hash reliability (HASH-03)
- Float normalization to 10 decimal places before hashing (HASH-02)
- Hash computation only on confirmed frames (not predicted) (HASH-01)
- confirmedHashHistory separate from stateHashHistory (legacy) (HASH-04)
- Hash invalidation >= targetFrame on rollback (not snapshotFrame)
- 16-char truncated SHA-256 for efficient storage/transmission

**v1.1 decisions (Phase 12):**
- Binary hash encoding (8 bytes from 16 hex chars) for compact P2P transmission (EXCH-04)
- Queue-based async exchange to avoid blocking game loop (EXCH-02)
- Re-queue on buffer full instead of dropping hashes
- Skip hash exchange during rollback to avoid invalid state hashes

**v1.1 decisions (Phase 13):**
- Dual-trigger comparison: call _attemptHashComparison from both hash storage paths (DETECT-01)
- Skip comparison during rollback (state is in flux) (DETECT-02)
- Async state dump capture in _handleDesync to avoid blocking game loop (DETECT-05)
- Reset verifiedFrame on rollback to maintain verification invariant (DETECT-04)

**v1.1 decisions (Phase 14):**
- Export only confirmed data (confirmedHashHistory, not stateHashHistory) (EXPORT-02)
- Sort hashes by frame number for consistent output (EXPORT-01)
- Filter actions to verifiedFrame for mutually-confirmed sequences (EXPORT-04)
- Include hasStateDump flag instead of full dump for manageable export size (EXPORT-03)

**v1.2 decisions (Phase 15):**
- ua-parser-js via CDN for browser/device detection (ENTRY-01)
- Browser blocklist takes precedence over requirements for stricter safety (ENTRY-02)
- Default exclusion messages provided, researcher can customize (ENTRY-03)
- Entry screening runs before Pyodide initialization to fail fast (ENTRY-04)

**v1.2 decisions (Phase 16):**
- Frame-throttled checking every 30 frames (~1s) for performance (MONITOR-01)
- Rolling window with N-of-M consecutive violations for ping (MONITOR-02)
- Page Visibility API visibilitychange event for immediate tab detection (MONITOR-03)
- Warning before exclusion with configurable thresholds (MONITOR-04)

**v1.2 decisions (Phase 17):**
- Distinct partner_excluded event (not reuse end_game) for appropriate UI (EXCL-01)
- Neutral gray UI styling for partner notification (less alarming) (EXCL-02)
- eventlet.sleep(0.1) before cleanup ensures message delivery (EXCL-03)
- sessionStatus object in metrics export for partial session analysis (EXCL-04)

**v1.2 decisions (Phase 18):**
- Callbacks execute server-side, not client-side (CALLBACK-01)
- Entry callback runs AFTER built-in checks pass (CALLBACK-02)
- Fail-open on callback errors (CALLBACK-03)
- Async continuous callback with non-blocking game loop (CALLBACK-04)
- 5-second timeout for entry callback (CALLBACK-05)

**v1.3 decisions (Phase 19):**
- Bidirectional validation requiring ping AND pong in both directions (WAIT-01)
- Re-pool both players on any validation failure, no retry (WAIT-02)
- Server coordinates validation complete to ensure both peers agree (WAIT-03)
- 10-second validation timeout separate from 5s P2P ready gate (WAIT-04)

**v1.3 decisions (Phase 20, Plan 01):**
- 3-second grace period before declaring connection lost (RECON-GRACE)
- ICE 'failed' triggers onConnectionLost immediately (terminal state)
- Bilateral pause coordinated via server SocketIO (works when P2P down)
- First player to report triggers pause for both players

**v1.3 decisions (Phase 20, Plan 02):**
- ICE restart with iceRestart flag for proper WebRTC renegotiation (RECON-05)
- Deterministic initiator role (lower player ID) for restart offers
- Server coordinates resume to ensure both clients resume together
- Reconnection data included in both validation and session exports

### Pending Todos

(None)

### Blockers/Concerns

**Known issues to address in future milestones:**
- Episode start sync can timeout on slow connections (mitigated with retry + two-way ack)
- Rollback visual corrections cause brief teleporting (smoothing not yet implemented)

## Session Continuity

Last session: 2026-01-22
Stopped at: Phase 20 verified and complete
Resume file: None

### Next Steps

1. `/gsd:plan-phase 21` — plan Per-Round Health Check phase
