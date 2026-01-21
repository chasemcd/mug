# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-01-20)

**Core value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.
**Current focus:** v1.1 Sync Validation

## Current Position

Phase: 13 of 14 (Mismatch Detection)
Plan: 13-01 complete
Status: Phase 13 complete - ready for Phase 14
Last activity: 2026-01-21 - Completed 13-01-PLAN.md

Progress: [=======   ] 75% (v1.1 - Phase 13 complete)

## Milestone History

| Milestone | Phases | Status | Shipped |
|-----------|--------|--------|---------|
| v1.1 Sync Validation | 11-14 | In Progress | - |
| v1.0 P2P Multiplayer | 1-10 | Complete | 2026-01-19 |

## Accumulated Context

### Key Files

**P2P Core (created/heavily modified in v1.0):**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` (4,300+ LOC)
- `interactive_gym/server/static/js/webrtc_manager.js` (759 LOC)
- `interactive_gym/server/pyodide_game_coordinator.py`
- `interactive_gym/configurations/remote_config.py`

**v1.1 Execution:**
- `.planning/phases/11-hash-infrastructure/11-01-SUMMARY.md`
- `.planning/phases/12-p2p-hash-exchange/12-01-SUMMARY.md`
- `.planning/phases/13-mismatch-detection/13-01-SUMMARY.md`
- `.planning/research/SUMMARY.md`
- `.planning/research/ARCHITECTURE.md`

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

### Pending Todos

(None)

### Blockers/Concerns

**Known issues to address in future milestones:**
- Episode start sync can timeout on slow connections (mitigated with retry + two-way ack)
- Rollback visual corrections cause brief teleporting (smoothing not yet implemented)

## Session Continuity

Last session: 2026-01-21
Stopped at: Completed 13-01-PLAN.md
Resume file: None

### Next Steps

1. `/gsd:plan-phase 14` - plan Validation Export phase
2. After Phase 14 complete: v1.1 Sync Validation milestone complete
