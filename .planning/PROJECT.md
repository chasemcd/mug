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

### Active

- [ ] Remove all dead code — unused functions, classes, imports, vestigial logic from 82+ phases of development
- [ ] Improve naming clarity — rename unclear variables, functions, modules where meaning is obscured
- [ ] Reorganize file/module structure where it aids navigation and readability
- [ ] Zero functionality changes — every refactor verified by tests

### Out of Scope

- New features or capabilities — this milestone is cleanup only
- Functionality changes of any kind — pure readability/structure refactor
- Removing or restructuring `.planning/` directory
- Changes that would require updating external documentation or APIs

## Context

The codebase has been developed over 82+ phases on the `feature/p2p-multiplayer` branch. Rapid iteration over many milestones (v1.0–v1.22) has accumulated dead code, unclear naming, and structural complexity. Before merging to `main`, the codebase needs to be clean and readable enough that someone encountering it for the first time can follow the logic without confusion.

Scope: Full repo — server Python, client JS, scenes, examples, tests, docs.

GymScene builder API was cleaned up in v1.22 (14 → 10 methods). This milestone addresses everything else.

## Current Milestone: v1.23 Pre-Merge Cleanup

**Goal:** Make the entire codebase clean, readable, and coherent before merging `feature/p2p-multiplayer` to `main`. Zero functionality changes.

**Target features:**
- Remove all dead code (unused functions, classes, imports, vestigial logic)
- Rename unclear variables, functions, and modules for readability
- Reorganize file/module structure where it aids navigation
- Aggressive cleanup, every refactor tested
- Full repo scope: server, client JS, scenes, examples, tests, docs

## Constraints

- **No functionality change**: Every refactor must be verified by tests — nothing breaks
- **Full test coverage**: Run tests after every structural change
- **Full repo scope**: Server, client JS, scenes, examples, tests, docs all in scope

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Aggressive method merging (v1.22) | Reduce 14 methods to 10 — less cognitive load for researchers | ✓ Good |
| Clean break — no aliases (v1.22) | Pre-merge feature branch, no external consumers | ✓ Good |
| Rename freely (v1.22) | Pick clearest names regardless of history | ✓ Good |
| Aggressive cleanup, test everything (v1.23) | Codebase must be readable to newcomers before merge | — Pending |
| Keep .planning/ directory (v1.23) | Preserves project history | — Pending |

---
*Last updated: 2026-02-08 after milestone v1.23 initialization*
