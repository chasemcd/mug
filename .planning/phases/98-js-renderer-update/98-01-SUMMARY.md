---
phase: 98-js-renderer-update
plan: 01
subsystem: rendering
tags: [deprecation, stubs, migration, object-contexts]

# Dependency graph
requires:
  - phase: 97-python-surface-core
    provides: Surface draw-call API that replaces ObjectContext classes
provides:
  - Stub classes for all 8 legacy ObjectContext types that raise NotImplementedError
  - Import-compatible deprecation path directing users to Surface API
affects: [99-examples-migration]

# Tech tracking
tech-stack:
  added: []
  patterns: [dynamic-class-stubs-via-type, deprecation-via-NotImplementedError]

key-files:
  created: []
  modified:
    - mug/configurations/object_contexts.py

key-decisions:
  - "Used type() dynamic class creation for stubs to preserve __name__ attribute"
  - "Error message includes both class name and migration target (mug.rendering.Surface)"

patterns-established:
  - "Deprecation stubs: _DeprecatedBase with __init__ raising NotImplementedError, child classes via type()"

requirements-completed: [RENDER-03]

# Metrics
duration: 1min
completed: 2026-02-20
---

# Phase 98 Plan 01: Legacy ObjectContext Deprecation Stubs Summary

**Replaced 8 ObjectContext dataclasses with NotImplementedError stubs preserving import compatibility and directing to Surface API**

## Performance

- **Duration:** 1 min
- **Started:** 2026-02-20T20:01:00Z
- **Completed:** 2026-02-20T20:02:23Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Replaced 351-line dataclass module with 35-line stub module
- All 8 class names (Sprite, Circle, Line, Polygon, Text, AtlasSpec, MultiAtlasSpec, ImgSpec) remain importable
- Instantiation of any class raises NotImplementedError with clear migration message
- as_dict() method also raises NotImplementedError for completeness
- 124 unit tests continue to pass; E2E failures are expected (downstream code uses deprecated classes, deferred to Phase 99)

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace object_contexts.py with stub module** - `5e41e5f` (feat)

## Files Created/Modified
- `mug/configurations/object_contexts.py` - Replaced dataclass definitions with _DeprecatedObjectContext base and 8 dynamic stub classes

## Decisions Made
- Used `type("ClassName", (_DeprecatedObjectContext,), {})` pattern to create stubs dynamically, keeping `__name__` correct for clear error messages
- Included `as_dict()` on the base class since all original classes had it; raises same NotImplementedError
- Error message format: `"{ClassName} is removed. Migrate to Surface API (see mug.rendering.Surface)."`
- isort pre-commit hook added `from __future__ import annotations` import; accepted as standard project convention

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Legacy ObjectContext module is now a clean deprecation layer
- Phase 98 plans 02-03 can proceed with JS renderer updates
- Phase 99 will migrate downstream example code that currently instantiates these stubs

## Self-Check: PASSED

- FOUND: mug/configurations/object_contexts.py
- FOUND: .planning/phases/98-js-renderer-update/98-01-SUMMARY.md
- FOUND: commit 5e41e5f

---
*Phase: 98-js-renderer-update*
*Completed: 2026-02-20*
