# Roadmap: Multi-User Gymnasium (MUG)

## Milestones

- v1.0-v1.21 Feature Branch: P2P Multiplayer (Phases 1-66) -- shipped
- v1.22 GymScene Config Cleanup (Phases 67-71) -- shipped 2026-02-08
- v1.23 Pre-Merge Cleanup (Phases 72-78) -- shipped 2026-02-08
- v1.24 Test Fix & Hardening (Phases 79-82) -- shipped 2026-02-09
- v1.25 Data Export Path Fix (Phase 83) -- shipped 2026-02-09
- **v1.26 Project Rename (Phases 84-86) -- shipped 2026-02-10**

## Overview

Rename the project from "Interactive Gym" to "Multi-User Gymnasium" (MUG) across the entire codebase. The package directory moves from `interactive_gym/` to `mug/`, all Python imports update, environment class prefixes drop, and documentation/frontend branding updates follow. The v1.23 lesson (word-boundary-aware patterns to avoid substring mangling) applies throughout.

## Phases

- [x] **Phase 84: Package & Code Rename** - Rename package directory, update all Python imports and class names ✓ 2026-02-10
- [x] **Phase 85: Documentation & Frontend** - Update all docs, templates, and frontend branding ✓ 2026-02-10
- [x] **Phase 86: Final Verification** - Confirm zero stale references, all tests pass, all examples import ✓ 2026-02-10

## Phase Details

### Phase 84: Package & Code Rename
**Goal**: All Python code runs under the `mug` package name with updated class names
**Depends on**: Nothing (first phase of v1.26)
**Requirements**: PKG-01, PKG-02, PKG-03, PKG-04, PKG-05, IMP-01, IMP-02, IMP-03, IMP-04, CLS-01, CLS-02, CLS-03
**Success Criteria** (what must be TRUE):
  1. `import mug` succeeds and `import interactive_gym` fails (package directory is `mug/`)
  2. All library modules import with `from mug.X` paths (zero `interactive_gym` imports in library code)
  3. All test files and example files use `from mug.X` imports
  4. `MountainCarEnv` and `OvercookedEnv` class names work in all environment initialization and scene config references (no `InteractiveGym` prefix classes exist)
  5. `pip install -e .` installs the `mug-py` package and `setup.py`/`MANIFEST.in` reference `mug/`
**Plans**: 2 plans

Plans:
- [x] 84-01-PLAN.md — Rename package directory, update library imports, setup.py/MANIFEST.in
- [x] 84-02-PLAN.md — Update example/test imports, rename environment classes, run unit tests

### Phase 85: Documentation & Frontend
**Goal**: All user-facing documentation and frontend templates say "Multi-User Gymnasium" / "MUG" with correct import examples
**Depends on**: Phase 84
**Requirements**: DOC-01, DOC-02, DOC-03, DOC-04, DOC-05, DOC-06, FE-01, FE-02, FE-03
**Success Criteria** (what must be TRUE):
  1. README.rst title, install commands, and import examples all reference `mug-py` / `mug`
  2. All `.rst` and `.md` doc files use "Multi-User Gymnasium" in prose and `mug` in code examples
  3. Admin HTML templates display "MUG" branding (not "Interactive Gym")
  4. CSS logo selector references `mug_logo.png` and JS comments use updated name
**Plans**: 3 plans

Plans:
- [x] 85-01-PLAN.md — Update README.rst, docs/conf.py, CSS, and all RST documentation source files
- [x] 85-02-PLAN.md — Update admin templates, JS comments, HTML template prose, and example READMEs
- [x] 85-03-PLAN.md — Update docs/ .md files and mountain_car_experiment.py with MUG branding

### Phase 86: Final Verification
**Goal**: Zero stale references remain and the full test suite confirms no functional regressions
**Depends on**: Phase 85
**Requirements**: VER-01, VER-02, VER-03, VER-04
**Success Criteria** (what must be TRUE):
  1. All 52 tests pass (27 unit + 25 E2E) with zero failures
  2. `grep -r "interactive_gym" --include="*.py"` returns zero hits (excluding .planning/, .git/)
  3. `grep -r "Interactive Gym"` returns zero hits (excluding .planning/, .git/, PLAN_multiplayer_refactor.md)
  4. Every example file imports successfully under the `mug` package name
**Plans**: 2 plans

Plans:
- [x] 86-01-PLAN.md — Fix 7 stale docstring module paths, verify zero stale references (VER-02, VER-03)
- [x] 86-02-PLAN.md — Run full test suite, verify example imports (VER-01, VER-04)

## Progress

**Execution Order:** 84 -> 85 -> 86

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 84. Package & Code Rename | v1.26 | 2/2 | ✓ Complete | 2026-02-10 |
| 85. Documentation & Frontend | v1.26 | 3/3 | ✓ Complete | 2026-02-10 |
| 86. Final Verification | v1.26 | 2/2 | ✓ Complete | 2026-02-10 |
