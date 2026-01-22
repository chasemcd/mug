# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-21)

**Core value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.
**Current focus:** v1.2 Participant Exclusion

## Current Position

Phase: 17 of 18 (Multiplayer Exclusion Handling)
Plan: Not started
Status: Ready to plan
Last activity: 2026-01-21 — Phase 16 verified complete

Progress: [####......] 50% (v1.2 - 2/4 phases complete)

## Milestone History

| Milestone | Phases | Status | Shipped |
|-----------|--------|--------|---------|
| v1.2 Participant Exclusion | 15-18 | In progress | - |
| v1.1 Sync Validation | 11-14 | Complete | - |
| v1.0 P2P Multiplayer | 1-10 | Complete | 2026-01-19 |

## Accumulated Context

### Key Files

**P2P Core (created/heavily modified in v1.0):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` (4,600+ LOC)
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

**Phase 16 Key Files:**
- `interactive_gym/server/static/js/continuous_monitor.js` (277 LOC) - New module
- `interactive_gym/scenes/gym_scene.py` - continuous_monitoring() method added

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

### Pending Todos

(None)

### Blockers/Concerns

**Known issues to address in future milestones:**
- Episode start sync can timeout on slow connections (mitigated with retry + two-way ack)
- Rollback visual corrections cause brief teleporting (smoothing not yet implemented)

## Session Continuity

Last session: 2026-01-21
Stopped at: Phase 16 verified complete
Resume file: None

### Next Steps

1. `/gsd:plan-phase 17` — plan Multiplayer Exclusion Handling phase
