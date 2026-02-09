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

### Active

- [ ] Fix rename corruption from v1.23 bulk `sio` → `socketio` rename (72 occurrences in 3 files)
- [ ] All 46 existing tests pass — no exceptions, no loosened criteria
- [ ] Every test producing episode data validates export parity (both players' CSVs match)
- [ ] All examples run end-to-end with refactored code
- [ ] Documentation reflects renamed APIs, module paths from v1.23 refactor

### Out of Scope

- New features or capabilities — this milestone is fix + harden only
- New test infrastructure or frameworks — use existing pytest + Playwright setup
- Performance optimization — focus is correctness
- Removing or restructuring `.planning/` directory

## Context

The codebase has been developed over 82+ phases on the `feature/p2p-multiplayer` branch. v1.22 cleaned up the GymScene API (14 → 10 methods). v1.23 removed dead code, renamed unclear identifiers, and reorganized modules — but introduced a bulk rename bug: `sio` → `socketio` corrupted words containing "sio" (e.g., `Session` → `Sessocketion`). 72 occurrences across 3 server files.

All 46 tests are currently failing. The test suite covers: infrastructure (2), multiplayer (2), data parity (4+7 indirect), network stress (7), multi-participant (5), scene isolation (1), and unit tests (27).

## Current Milestone: v1.24 Test Fix & Hardening

**Goal:** Fix refactor-introduced bugs, get all tests passing, harden data export parity validation, ensure examples work and docs are accurate.

**Target features:**
- Fix rename corruption (`Sessocketion` → `Session`, etc.) in 3 files
- All 46 tests passing — zero exceptions, zero loosened criteria
- Every data-producing test validates export parity
- All examples run end-to-end
- Docs reflect post-refactor API names and module paths

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
| Keep .planning/ directory (v1.23) | Preserves project history | — Pending |
| Fix code, not tests (v1.24) | Tests define correctness — code must conform | — Pending |

---
*Last updated: 2026-02-08 after milestone v1.24 initialization*
