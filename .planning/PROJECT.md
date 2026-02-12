# Multi-User Gymnasium (MUG)

## What This Is

A framework for running interactive behavioral experiments in the browser, supporting single-player (human vs AI) and multiplayer (human vs human) real-time games. Environments run client-side via Pyodide with WebRTC P2P synchronization, GGPO-style rollback, latency-aware matchmaking, and comprehensive data collection for research. The package is `mug` (PyPI: `mug-py`).

## Core Value

Researchers can configure and deploy multiplayer browser experiments with minimal code — a chained scene config and a Python environment are all that's needed.

## Requirements

### Validated

- ✓ P2P WebRTC multiplayer with GGPO-style input sync and rollback
- ✓ Pyodide client-side environment execution (single and multiplayer)
- ✓ Latency-aware matchmaking (server RTT pre-filter + P2P probe post-filter)
- ✓ Waitroom with configurable timeout, reconnection handling, partner disconnect
- ✓ Focus/tab-away detection with configurable warnings and exclusion
- ✓ Continuous monitoring (ping, tab visibility) with custom callback hooks
- ✓ Admin dashboard with session list, detail views, telemetry
- ✓ Data export: actions, states, telemetry, custom attributes
- ✓ Scene stager with static scenes, gym scenes, and feedback scenes
- ✓ Group history tracking for cross-scene re-pairing
- ✓ GymScene chaining API consolidated (14 → 10 methods, clean break) — v1.22
- ✓ Dead code removal, naming cleanup, module reorganization — v1.23
- ✓ All 52 existing tests pass — no exceptions, no loosened criteria (27 unit + 25 E2E) — v1.24
- ✓ Every data-producing test validates export parity (both players' CSVs match) — v1.24
- ✓ All examples run end-to-end with refactored code — v1.24
- ✓ Documentation reflects renamed APIs, module paths from v1.23 refactor — v1.24
- ✓ All exported data lands under data/{experiment_id}/ — v1.25
- ✓ Package renamed from interactive_gym to mug (PyPI: mug-py) — v1.26
- ✓ All imports updated from interactive_gym to mug — v1.26
- ✓ Environment classes renamed: MountainCarEnv, OvercookedEnv (no InteractiveGym prefix) — v1.26
- ✓ All documentation and frontend updated with "Multi-User Gymnasium (MUG)" branding — v1.26
- ✓ Zero stale references to interactive_gym in source code — v1.26

### Active

(None — fresh milestone needed)

### Out of Scope

- GitHub repository rename — deferred, keep current URL for now
- Mobile app — web-first approach, PWA works well
- Video chat — use external tools
- Offline mode — real-time is core value
- New logo design — just renamed existing file

## Context

Shipped v1.26 with 34,311 LOC Python across 86 phases on the `refactor/mug` branch. The codebase has been developed across 6 milestones (v1.0–v1.21 feature development, v1.22 API cleanup, v1.23 code cleanup, v1.24 test fix & hardening, v1.25 data export fix, v1.26 project rename).

**Tech stack:** Python, Flask, Socket.IO, Pyodide, WebRTC, GGPO, Playwright (E2E tests).

**Current state (post v1.26):**
- Package: `mug` (import) / `mug-py` (PyPI)
- All 27 unit tests and 25 E2E tests pass
- Zero stale `interactive_gym` references in source code
- All examples verified with `mug` imports
- `interactive_gym_globals` preserved as Pyodide runtime variable (intentional)

## Shipped Milestones

| Milestone | Phases | Shipped |
|-----------|--------|---------|
| v1.0–v1.21 Feature Branch | 1-66 | - |
| v1.22 GymScene Config Cleanup | 67-71 | 2026-02-08 |
| v1.23 Pre-Merge Cleanup | 72-78 | 2026-02-08 |
| v1.24 Test Fix & Hardening | 79-82 | 2026-02-09 |
| v1.25 Data Export Path Fix | 83 | 2026-02-09 |
| v1.26 Project Rename | 84-86 | 2026-02-10 |

## Constraints

- **No loosening test criteria**: All 52 tests must continue passing
- **GitHub URLs unchanged**: Repo name stays `interactive-gym` for now

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Package name `mug` | Short, memorable, matches acronym | ✓ Good |
| PyPI name `mug-py` | `mug` is taken on PyPI | ✓ Good |
| Drop InteractiveGym class prefix | Environment classes don't need framework prefix (MountainCarEnv, OvercookedEnv) | ✓ Good |
| Keep GitHub repo name | Avoid URL breakage, rename later | ✓ Good (deferred) |
| Trailing-dot pattern for import rename | `from interactive_gym.` → `from mug.` avoids mangling interactive_gym_globals | ✓ Good (lesson from v1.23 corruption) |
| _BaseMountainCarEnv alias | Resolves name collision with gymnasium parent class MountainCarEnv | ✓ Good |
| Exclude build artifacts from verification | build/, docs/_build/, __pycache__/ regenerate from source | ✓ Good |

---
*Last updated: 2026-02-11 after v1.26 milestone*
