# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-08)

**Core value:** Researchers can configure and deploy multiplayer browser experiments with minimal code — a chained scene config and a Python environment are all that's needed.
**Current focus:** Milestone v1.24 — Test Fix & Hardening

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-02-08 — Milestone v1.24 started

## Performance Metrics

**Velocity (v1.22):**
- Total plans completed: 10
- Average duration: 3.0 min
- Total execution time: 0.52 hours

**Velocity (v1.23):**
- Total plans completed: 13
- Average duration: 4.2 min
- Total execution time: 1.09 hours

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.

- Aggressive cleanup scope: full repo (server, client JS, scenes, examples, tests, docs)
- Zero functionality changes — every refactor verified by tests
- Keep .planning/ directory as project history
- Dead code removal first (3 phases by layer), then naming (2 phases), then structure (1 phase), then final verification
- Removed ConnectionQualityMonitor from exports but kept class internally - used within webrtc_manager.js
- EmitUnityEpisodeResults and UnityConnectSocketIO removed as unreachable (ES6 module scope prevents Unity SendMessage from calling them)
- Unity callbacks must be on window object to be reachable from SendMessage
- Renamed all sio to socketio for clarity (93 occurrences across 10 files)
- Kept local variable name game_manager in app.py (widely used), only expanded import alias
- Use word-boundary patterns for bulk renames to avoid unintended replacements
- Renamed server/utils.py → server/thread_utils.py to reflect actual content (thread-safe collections)
- Renamed scenes/utils.py → scenes/sentinels.py to reflect actual content (sentinel values)
- Renamed Available sentinel → AvailableSlot for clarity
- Expanded WebRTC abbreviations: this.pc → this.peerConnection, dc → dataChannel in webrtc_manager.js
- Renamed pgg import alias → phaserGraphics in ui_utils.js for clarity
- Renamed generic 'data' parameters to context-specific names in all 26 socket event handlers in index.js
- Moved NotProvided sentinel from scenes/sentinels.py to utils/sentinels.py (proper leaf-module location, eliminates cross-boundary import)
- Consolidated game state types (GameExitStatus, AvailableSlot) into remote_game.py alongside SessionState and GameStatus
- Consolidated callback interface (GameCallback, MultiCallback) from dead callback.py into remote_game.py
- Renamed thread_utils.py → thread_safe_collections.py to accurately describe remaining content (ThreadSafeSet, ThreadSafeDict)

### Pending Todos

None.

### Blockers/Concerns

- v1.23 bulk `sio` → `socketio` rename corrupted 72 occurrences of "session", "exclusion", "transmission" across 3 server Python files
- All 46 tests currently failing due to this corruption

## Session Continuity

Last session: 2026-02-08
Stopped at: Milestone v1.24 initialization — defining requirements
Resume file: —
