# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-13)

**Core value:** Researchers can deploy interactive simulation experiments to the browser with minimal friction
**Current focus:** Phase 94 in progress -- client rendering and input

## Current Position

Phase: 94 of 95 (Client Rendering and Input)
Plan: 1 of 2 in current phase -- DONE
Status: Phase 94 Plan 01 complete, Plan 02 remaining
Last activity: 2026-02-16 -- Phase 94-01 executed (2 tasks, 2 commits)

Progress: [█████████░] 50% (Phase 94)

## Performance Metrics

**Velocity:**
- Total plans completed: 4
- Average duration: ~4 min
- Total execution time: ~4 sessions

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 92 | 1 | 1 session | 1 session |
| 93 | 2 | 9 min | 4.5 min |
| 94 | 1 (of 2) | 2 min | 2 min |

**Recent Trend:**
- Last 5 plans: 92-01, 93-01, 93-02, 94-01
- Trend: Client rendering pipeline wired, input sending operational

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

### Pending Todos

None.

### Blockers/Concerns

- P2P multiplayer must not regress during any phase

## Session Continuity

Last session: 2026-02-16
Stopped at: Completed 94-01-PLAN.md (client state buffer and input sending). Phase 94 Plan 02 remaining.
Resume file: None
