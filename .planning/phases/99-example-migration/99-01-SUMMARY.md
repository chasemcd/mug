---
phase: 99-example-migration
plan: 01
subsystem: rendering
tags: [surface-api, slime-volleyball, asset-registration, migration]

# Dependency graph
requires:
  - phase: 97-python-surface-core
    provides: Surface class with draw methods, commit(), reset()
  - phase: 98-js-renderer-update
    provides: JS renderer handles delta wire format, ObjectContext stubs raise NotImplementedError
provides:
  - Surface asset registration API (register_atlas, register_image, get_asset_specs)
  - Slime Volleyball fully migrated to Surface draw-call API
  - Migration pattern validated for simpler example (geometric primitives + relative coords)
affects: [99-02-overcooked-migration]

# Tech tracking
tech-stack:
  added: []
  patterns: [surface-based-env-render, asset-registration-on-surface]

key-files:
  created: []
  modified:
    - mug/rendering/surface.py
    - mug/examples/slime_volleyball/slimevb_env.py
    - mug/examples/slime_volleyball/slime_volleyball_utils.py

key-decisions:
  - "Asset specs stored as list of dicts on Surface._asset_specs, not cleared on reset()"
  - "All Slime VB draw calls use relative=True to match old ObjectContext coordinate convention"
  - "Agent drawing logic moved to _draw_agent() private method on env class"

patterns-established:
  - "Surface env render: __init__ creates self.surface, reset() calls self.surface.reset(), render() draws + commits"
  - "Asset registration: register_atlas/register_image in __init__, get_asset_specs() for config"
  - "Persistent objects: draw every frame with persistent=True, Surface handles delta compression"

requirements-completed: [MIGR-01]

# Metrics
duration: 3min
completed: 2026-02-20
---

# Phase 99 Plan 01: Surface Asset Registration + Slime Volleyball Migration Summary

**Surface asset registration API (register_atlas, register_image, get_asset_specs) added and Slime Volleyball fully migrated from ObjectContext to Surface draw-call API with relative coordinates and persistent object delta compression**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-20T22:13:02Z
- **Completed:** 2026-02-20T22:15:42Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added asset registration methods to Surface class (register_atlas, register_image, get_asset_specs) with specs surviving reset()
- Migrated SlimeVBEnvIG to own its Surface, draw via self.surface calls, return self.surface.commit().to_dict()
- Deleted all standalone render functions (slime_volleyball_env_to_rendering, generate_slime_agent_objects) from both env and utils files
- Cleaned slime_volleyball_utils.py to contain only hud_text_fn and page_header_fn helpers
- Zero ObjectContext imports remain in slime_volleyball directory

## Task Commits

Each task was committed atomically:

1. **Task 1: Add asset registration methods to Surface class** - `34578f0` (feat)
2. **Task 2: Migrate Slime Volleyball to Surface API and clean up configs** - `99a0797` (feat)

## Files Created/Modified
- `mug/rendering/surface.py` - Added register_atlas(), register_image(), get_asset_specs() methods and _asset_specs storage
- `mug/examples/slime_volleyball/slimevb_env.py` - Rewrote with Surface API: __init__, reset(), _draw_agent(), render() returning packet.to_dict()
- `mug/examples/slime_volleyball/slime_volleyball_utils.py` - Removed all render functions, asset specs, ObjectContext imports; kept hud_text_fn and page_header_fn

## Decisions Made
- Asset specs stored as plain dicts in a list on Surface._asset_specs, deliberately not cleared on reset() since registrations are permanent for the Surface lifetime
- All Slime VB draw calls use relative=True to match the old ObjectContext coordinate convention where positions are 0-1 normalized
- Agent drawing extracted to _draw_agent() private method for clarity, drawing body polygon + eye white + eye pupil directly onto self.surface

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Surface asset registration API is ready for Overcooked migration (register_atlas for terrain/chefs/objects atlases)
- Migration pattern proven: env owns Surface, draws every frame, persistent objects + delta compression works correctly
- Plan 99-02 (Overcooked migration) can proceed

## Self-Check: PASSED

- All 3 modified files exist on disk
- Commit 34578f0 (Task 1) verified in git log
- Commit 99a0797 (Task 2) verified in git log
- 124 unit tests passing

---
*Phase: 99-example-migration*
*Completed: 2026-02-20*
