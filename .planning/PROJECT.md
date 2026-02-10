# Interactive Gym

## What This Is

A framework for running interactive behavioral experiments in the browser, supporting single-player (human vs AI) and multiplayer (human vs human) real-time games. Environments run client-side via Pyodide with WebRTC P2P synchronization, GGPO-style rollback, latency-aware matchmaking, and comprehensive data collection for research.

## Core Value

Researchers can configure and deploy multiplayer browser experiments with minimal code — a chained scene config and a Python environment are all that's needed.

## Requirements

### Validated

- P2P WebRTC multiplayer with GGPO-style input sync and rollback
- Pyodide client-side environment execution (single and multiplayer)
- Latency-aware matchmaking (server RTT pre-filter + P2P probe post-filter)
- Waitroom with configurable timeout, reconnection handling, partner disconnect
- Focus/tab-away detection with configurable warnings and exclusion
- Continuous monitoring (ping, tab visibility) with custom callback hooks
- Admin dashboard with session list, detail views, telemetry
- Data export: actions, states, telemetry, custom attributes
- Scene stager with static scenes, gym scenes, and feedback scenes
- Group history tracking for cross-scene re-pairing
- ✓ GymScene chaining API consolidated (14 → 10 methods, clean break) — v1.22
- ✓ Dead code removal, naming cleanup, module reorganization — v1.23
- ✓ All 52 existing tests pass — no exceptions, no loosened criteria (27 unit + 25 E2E) — v1.24
- ✓ Every data-producing test validates export parity (both players' CSVs match) — v1.24
- ✓ All examples run end-to-end with refactored code — v1.24
- ✓ Documentation reflects renamed APIs, module paths from v1.23 refactor — v1.24

### Active

## Current Milestone: v1.25 Data Export Path Fix

**Goal:** Ensure all exported data (scene metadata, match logs) lands under `data/<experiment-id>/` — not scattered in `data/`.

**Target features:**
- Scene metadata exports use experiment_id subdirectory
- Match logs export uses experiment_id subdirectory

### Out of Scope

- Removing or restructuring `.planning/` directory

## Context

The codebase has been developed over 82 phases on the `refactor/p2pcleanup` branch across 4 milestones (v1.0–v1.21 feature development, v1.22 API cleanup, v1.23 code cleanup, v1.24 test fix & hardening).

**Current state (post v1.24):**
- All 52 tests pass (27 unit + 25 E2E) in a single pytest invocation
- All 7 episode-producing E2E tests validate export parity between both players
- All 12 example files import successfully, 2 representative examples smoke-tested via HTTP
- All documentation reflects post-v1.23 module paths (`utils/sentinels`, `server/thread_safe_collections`) and parameter names (`socketio` not `sio`)
- GymScene API: 10 builder methods (environment, rendering, assets, policies, gameplay, content, waitroom, matchmaking, runtime, multiplayer)

## Shipped Milestones

| Milestone | Phases | Shipped |
|-----------|--------|---------|
| v1.0–v1.21 Feature Branch | 1-66 | - |
| v1.22 GymScene Config Cleanup | 67-71 | 2026-02-08 |
| v1.23 Pre-Merge Cleanup | 72-78 | 2026-02-08 |
| v1.24 Test Fix & Hardening | 79-82 | 2026-02-09 |

## Constraints

- **No loosening test criteria**: Fix the code, not the tests
- **Parity validation required**: Every test producing episode data must assert both players' exports match
- **Examples must run**: Not just compile — full end-to-end execution
- **Docs must be accurate**: Reflect all v1.23 renames and module moves

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Aggressive method merging (v1.22) | Reduce 14 methods to 10 — less cognitive load for researchers | ✓ Good |
| Clean break — no aliases (v1.22) | Pre-merge feature branch, no external consumers | ✓ Good |
| Rename freely (v1.22) | Pick clearest names regardless of history | ✓ Good |
| Aggressive cleanup, test everything (v1.23) | Codebase must be readable to newcomers before merge | ⚠️ Revisit — bulk rename introduced corruption |
| Use word-boundary patterns for bulk renames | Lesson learned from v1.23 — avoid mangling words containing target string | ✓ Good |
| Fix code, not tests (v1.24) | Tests define correctness — code must conform | ✓ Good — all 52 tests pass without criteria loosening |
| Only modify code examples in docs, not prose (v1.24) | Prose references to "SocketIO" library are conceptual, not API calls | ✓ Good |
| Keep .planning/ directory | Preserves project history across milestones | — Pending |

---
*Last updated: 2026-02-09 after v1.25 milestone started*
