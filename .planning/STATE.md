# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-16)

**Core value:** Researchers can deploy interactive simulation experiments to the browser with minimal friction
**Current focus:** v1.2 Test Suite Green -- fix all 7 failing E2E tests across 3 subsystems

## Current Position

Phase: 96 of 98 (Scene Transition on Focus Loss) -- Plan 1 of 2 complete
Plan: 02 (next)
Status: Plan 96-01 complete, ready for Plan 96-02
Last activity: 2026-02-16 -- completed 96-01 (event-driven scene advancement)

Progress: [█░░░░░░░░░] ~17% (v1.2) -- 1 of ~6 plans complete

## Performance Metrics

**Velocity:**
- Total plans completed: 8
- Average duration: ~3 min
- Total execution time: ~8 sessions

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 92 | 1 | 1 session | 1 session |
| 93 | 2 | 9 min | 4.5 min |
| 94 | 2 | 6 min | 3 min |
| 95 | 2 | 6 min | 3 min |
| 96 | 1 | 3 min | 3 min |

**Recent Trend:**
- Last 5 plans: 94-01, 94-02, 95-01, 95-02, 96-01
- Trend: Stable ~3 min/plan

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

### Pending Todos

None.

### Blockers/Concerns

- P2P multiplayer must not regress during any phase
- Tests are correct -- fix root cause bugs, not tests

## Session Continuity

Last session: 2026-02-16
Stopped at: Completed 96-01-PLAN.md (event-driven scene advancement)
Resume file: None
