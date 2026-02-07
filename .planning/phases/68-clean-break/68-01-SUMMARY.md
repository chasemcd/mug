---
phase: 68-clean-break
plan: 01
subsystem: api
tags: [gymscene, builder-methods, api-cleanup, backward-compat-removal]

# Dependency graph
requires:
  - phase: 67-api-method-consolidation
    provides: New builder methods (runtime, multiplayer, content, waitroom, assets)
provides:
  - GymScene with only new API surface (9 old methods deleted)
  - rendering() slimmed to 9 display-only params
affects: [69-example-configs-migration, 70-verification-test-pass]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Clean API surface: only grouped builder methods remain"

key-files:
  created: []
  modified:
    - interactive_gym/scenes/gym_scene.py

key-decisions:
  - "No code changes needed in server/ or tests/ -- only matchmaking() is referenced internally and it was not removed"
  - "E2e tests fail because examples still use old API (expected, Phase 69 fixes examples)"

patterns-established:
  - "GymScene builder API: environment(), rendering(), assets(), policies(), gameplay(), content(), waitroom(), runtime(), multiplayer(), matchmaking()"

# Metrics
duration: 4min
completed: 2026-02-07
---

# Phase 68 Plan 01: Remove Old Methods and Slim rendering() Summary

**Deleted 9 old GymScene builder methods and removed 5 asset params from rendering(), leaving a clean API surface with only the new grouped methods**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-07T23:20:32Z
- **Completed:** 2026-02-07T23:23:59Z
- **Tasks:** 2 (1 code change, 1 verification-only)
- **Files modified:** 1

## Accomplishments
- Removed all 9 old method definitions: pyodide(), user_experience(), player_grouping(), continuous_monitoring(), exclusion_callbacks(), reconnection_config(), partner_disconnect_message_config(), focus_loss_config(), player_pairing()
- Slimmed rendering() from 14 params to 9 by removing 5 asset params (preload_specs, state_init, assets_dir, assets_to_preload, animation_configs) that now live exclusively in assets()
- Verified no internal server or test code references removed methods
- All 27 unit tests pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Remove 9 old method definitions and slim rendering()** - `2f13acd` (feat)
2. **Task 2: Update string references in server code and test file** - No commit (verification-only, no changes needed)

## Files Created/Modified
- `interactive_gym/scenes/gym_scene.py` - Removed 497 lines (9 old methods + 5 asset param handling blocks from rendering())

## Decisions Made
- No code changes needed in server files or test files -- the only externally-referenced method (matchmaking()) was intentionally kept
- E2e test failure is expected: examples still call old API (Phase 69 scope)
- Unit tests are the correctness gate for this plan; e2e depends on example migration

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- GymScene has a clean API surface ready for Phase 69 (example migration)
- Examples in interactive_gym/examples/ still use old method names and will error on import
- Phase 69 should update all 5 example configs to use new methods
- Phase 70 can then run full test suite (including e2e) for final verification

---
*Phase: 68-clean-break*
*Completed: 2026-02-07*
