# Milestones

## v1.0 — Foundation Cleanup (Phases 67-91)

**Completed:** 2026-02-12

**Goal:** Clean up, restructure, and modernize the MUG codebase after initial development.

**What shipped:**
- API method consolidation (phase 67)
- Clean break refactoring (phase 68)
- Server Python dead code removal (phase 72)
- Scene/environment dead code removal (phase 73)
- Client JS dead code removal (phase 74)
- Python naming clarity (phase 75)
- JS naming clarity (phase 76)
- Structural organization (phase 77)
- Final verification (phase 78)
- Rename corruption fix (phase 79)
- Test suite restoration (phase 80)
- Data parity hardening (phase 81)
- Examples/documentation (phase 82)
- Export path consolidation (phase 83)
- Package code rename to `mug` (phase 84)
- Documentation frontend (phase 85)
- Final verification (phase 86)
- ConfirmedFrame resource management (phase 87)
- Verification (phase 88)
- Declarative model config (phase 89)
- LSTM state persistence (phase 90)
- Custom inference escape hatch (phase 91)

**Last phase number:** 91

## v1.1 — Server-Authoritative Cleanup (Phases 92-95)

**Completed:** 2026-02-16

**Goal:** Clean up, simplify, and fix server-authoritative mode so it works correctly alongside P2P multiplayer with rollback.

**What shipped:**
- Remove obsolete ServerGameRunner and Pyodide server-auth sync code (phase 92)
- Server pipeline: max-speed env stepping, env.render() broadcast, action receiving, episode transitions (phase 93)
- Client pipeline: state buffer, FPS gating, immediate action sending, reconnection with disconnect timeout (phase 94)
- CoGrid Overcooked server-auth example, unit/integration tests, E2E Playwright tests (phase 95)

**Last phase number:** 95

## v1.2 — Test Suite Green (In Progress)

**Started:** 2026-02-16

**Goal:** Every test passes — 39 unit tests and 33 E2E tests, zero failures. Fix root cause bugs in the codebase, not the tests.

**Phases:** 96-98
