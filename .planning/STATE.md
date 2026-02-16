# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-13)

**Core value:** Researchers can deploy interactive simulation experiments to the browser with minimal friction
**Current focus:** Phase 95 in progress -- example and verification

## Current Position

Phase: 95 of 95 (Example and Verification)
Plan: 1 of 2 in current phase
Status: Phase 95 in progress -- plan 01 complete
Last activity: 2026-02-16 -- Phase 95-01 executed (2 tasks, 2 commits)

Progress: [█████████░] 90% (Phase 95)

## Performance Metrics

**Velocity:**
- Total plans completed: 6
- Average duration: ~3 min
- Total execution time: ~6 sessions

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 92 | 1 | 1 session | 1 session |
| 93 | 2 | 9 min | 4.5 min |
| 94 | 2 | 6 min | 3 min |
| 95 | 1 | 3 min | 3 min |

**Recent Trend:**
- Last 5 plans: 93-01, 93-02, 94-01, 94-02, 95-01
- Trend: Server-auth example and unit/integration tests added

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Treat phases 67-91 as v1.0 (Foundation Cleanup milestone)
- Remove ServerGameRunner -- P2P rollback handles sync
- Server steps at max speed, client gates FPS
- Use env.render(render_mode="interactive_gym") for state output
- ServerGame retains only socket/room plumbing (connection, room, player tracking)
- Server game loop runs at max speed with eventlet.sleep(0) -- no FPS cap
- render_server_game uses env.render() exclusively -- no env_to_state_fn or cv2 fallback
- Socket event is server_render_state (not environment_state)
- Removed cv2/base64 from game_manager -- no longer needed
- server_authoritative attribute on GymScene with mode param on multiplayer() builder
- player_action handler maps client keys to actions via scene.action_mapping
- Server-auth games skip Pyodide coordinator in all game creation paths
- Server-auth disconnect continues game with default actions (no end_game to remaining players)
- Unbounded FIFO buffer: play every frame in order, no dropping (client rendering)
- Freeze on last rendered frame when buffer empty (no jitter indicator)
- Send actions immediately on keypress, no batching at render tick intervals
- render_state normalized to game_state_objects in addStateToBuffer for shared drawState path
- Server-auth episode reset flushes buffer but does NOT destroy/recreate Phaser (continuous rendering)
- Server-auth disconnect: skip remove_subject, start configurable timeout (reconnection_timeout_ms)
- Reconnection: rejoin socket room, cancel timeout, resume from current state (no history burst)
- Lazy env_creator defers cogrid import to runtime -- server-auth example imports cleanly without cogrid
- Mock scene/env pattern for testing ServerGame without running server (patched eventlet)

### Pending Todos

None.

### Blockers/Concerns

- P2P multiplayer must not regress during any phase

## Session Continuity

Last session: 2026-02-16
Stopped at: Completed 95-01-PLAN.md (example and server game tests). Phase 95 plan 01 done, plan 02 remaining.
Resume file: None
