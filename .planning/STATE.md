# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-16)

**Core value:** Researchers can deploy interactive simulation experiments to the browser with minimal friction
**Current focus:** v1.2 Test Suite Green -- fix all 7 failing E2E tests across 3 subsystems

## Current Position

Phase: 96 of 98 (Scene Transition on Focus Loss) -- Plan 2 of 2 complete (PHASE COMPLETE)
Plan: Complete
Status: Phase 96 complete, ready for Phase 97
Last activity: 2026-02-16 -- completed 96-02 (test validation and bug fix)

Progress: [███░░░░░░░] ~33% (v1.2) -- 3 of ~6 plans complete (Phase 96 done)

## Performance Metrics

**Velocity:**
- Total plans completed: 9
- Average duration: ~13 min
- Total execution time: ~9 sessions

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 92 | 1 | 1 session | 1 session |
| 93 | 2 | 9 min | 4.5 min |
| 94 | 2 | 6 min | 3 min |
| 95 | 2 | 6 min | 3 min |
| 96 | 2 | 94 min | 47 min |

**Recent Trend:**
- Last 5 plans: 94-02, 95-01, 95-02, 96-01, 96-02
- Trend: 96-02 was 91 min (deep debugging of silent data loss)

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Server-auth episode completion detected via serverAuthoritative flag clearing (end_game handler)
- Server-auth disconnect: skip remove_subject, start configurable timeout (reconnection_timeout_ms)
- Reconnection: rejoin socket room, cancel timeout, resume from current state (no history burst)
- onGameDone callback pattern for event-driven game completion notification (bypasses setInterval throttling)
- MessageChannel watchdog for background-tab-safe countdown timing (setTimeout fallback with forced advance)
- Fast-forward episode end: check both max_steps AND terminated/truncated environment flags
- SocketIO ack-based retry (3 attempts, 2s interval) for reliable episode data delivery
- Backwards-compatible parameter extraction: data.get('sync_epoch') or data.get('client_timestamp')
- Pre-existing server-auth failure deferred to Phase 98 (not a regression)

### Pending Todos

None.

### Blockers/Concerns

- P2P multiplayer must not regress during any phase
- Tests are correct -- fix root cause bugs, not tests

## Session Continuity

Last session: 2026-02-16
Stopped at: Completed 96-02-PLAN.md (test validation and bug fix -- Phase 96 complete)
Resume file: None
