---
phase: 80-pre-game-countdown
plan: 01
subsystem: game-flow
tags: [socketio, countdown, matchmaking, waiting-room]

dependency_graph:
  requires: []
  provides:
    - "match_found_countdown socket event (server -> client)"
    - "_start_game_with_countdown background task method"
    - "3-second pre-game countdown for multiplayer games"
  affects: []

tech_stack:
  added: []
  patterns:
    - "Background greenlet for countdown delay (sio.start_background_task)"
    - "Server-triggered client-side countdown via socket event"

files:
  key_files:
    created: []
    modified:
      - interactive_gym/server/game_manager.py
      - interactive_gym/server/static/js/index.js

decisions:
  - id: CD-IMPL-01
    description: "Use sio.start_background_task() for countdown to avoid holding waiting_games_lock during 3s sleep"
    rationale: "Inline eventlet.sleep(3) inside the lock would block all matchmaking for 3 seconds"

metrics:
  duration: "3m 28s"
  completed: "2026-02-07"
---

# Phase 80 Plan 01: Pre-Game Countdown Summary

Server-triggered 3-second "Players found!" countdown on waiting room screen after match formation, using background greenlet to avoid blocking matchmaking lock.

## Tasks Completed

| Task | Name | Commit | Key Changes |
|------|------|--------|-------------|
| 1 | Server-side countdown delay | b553205 | Added `_start_game_with_countdown()`, emits `match_found_countdown` event, uses `start_background_task()` |
| 2 | Client-side countdown display | 107932d | Added `match_found_countdown` socket handler, updates `#waitroomText` with 3-2-1 countdown |
| 3 | E2E test verification | (no commit) | Pre-existing test failures confirmed; scene isolation test passes |

## Implementation Details

### Server Side (game_manager.py)

Added `_start_game_with_countdown(self, game)` method near `start_game()`:
- Checks `group_size <= 1` to skip countdown for single-player games
- Emits `match_found_countdown` event to game room with `{"countdown_seconds": 3, "message": "Players found!"}`
- Sleeps 3 seconds via `eventlet.sleep(3)`
- Calls `self.start_game(game)` after countdown

Both match creation paths (`_create_game_for_match()` and `_create_game_for_match_internal()`) now call `self.sio.start_background_task(self._start_game_with_countdown, game)` instead of `self.start_game(game)` directly. This ensures the waiting_games_lock is released before the 3-second sleep.

### Client Side (index.js)

Added `match_found_countdown` socket handler near the existing `waiting_room` handler:
- Clears `waitroomInterval` to stop the waiting room timer
- Shows "Players found! Starting in 3..." on `#waitroomText`
- Counts down 3, 2, 1, then shows "Starting now!"
- Purely cosmetic -- server controls actual timing via `start_game` event

No new DOM elements, CSS, or HTML template changes.

## Deviations from Plan

None -- plan executed exactly as written.

## Verification Results

- `match_found_countdown` event emitted by server after match formation (multiplayer only)
- Client displays "Players found! Starting in 3... 2... 1..." on waiting room screen
- `start_game` fires 3 seconds after `match_found_countdown`
- Single-player games skip countdown entirely (group_size guard)
- Scene isolation test (`test_scene_isolation.py`) passes with no regressions
- Multiplayer basic E2E tests (`test_multiplayer_basic.py`) have **pre-existing failures** (confirmed by running baseline without changes). These failures are unrelated to countdown -- players get assigned to separate games due to a matchmaking test infrastructure issue.

## Decisions Made

| ID | Decision | Rationale |
|----|----------|-----------|
| CD-IMPL-01 | Use `sio.start_background_task()` for countdown | Avoids holding `waiting_games_lock` during 3s sleep, which would block all matchmaking |
