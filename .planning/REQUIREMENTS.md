# Requirements: Interactive Gym — v1.23 Pre-Merge Cleanup

**Defined:** 2026-02-08
**Core Value:** Researchers can configure and deploy multiplayer browser experiments with minimal code — a chained scene config and a Python environment are all that's needed.

## v1 Requirements

Requirements for v1.23 milestone. Each maps to roadmap phases.

### Dead Code Removal

- [ ] **DEAD-01**: All unused Python functions, classes, and methods are removed from server code
- [ ] **DEAD-02**: All unused Python functions, classes, and methods are removed from scene/environment code
- [ ] **DEAD-03**: All unused JavaScript functions and classes are removed from client code
- [ ] **DEAD-04**: All vestigial logic from earlier development phases is removed (unreachable code paths, obsolete feature flags, dead branches)

### Naming Clarity

- [ ] **NAME-01**: Unclear Python variable and function names are renamed to reflect their purpose
- [ ] **NAME-02**: Unclear JavaScript variable and function names are renamed to reflect their purpose
- [ ] **NAME-03**: File and module names that don't reflect their contents are renamed

### Structural Organization

- [ ] **STRUCT-01**: Files are reorganized into logical locations in the directory tree
- [ ] **STRUCT-02**: Unnecessarily split modules are consolidated where it reduces complexity
- [ ] **STRUCT-03**: Misplaced functions and classes are moved to the modules where they logically belong

### Verification

- [ ] **VERIF-01**: All existing tests pass after every refactoring change
- [ ] **VERIF-02**: No functionality changes are introduced (behavior is identical before and after)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Automated Cleanup

- **DEAD-05**: Remove unused imports across Python and JS files

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| New features or capabilities | This milestone is cleanup only |
| Functionality changes of any kind | Pure readability/structure refactor |
| Removing or restructuring `.planning/` directory | Preserves project history |
| Changes that would require updating external documentation or APIs | No breaking changes |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DEAD-01 | — | Pending |
| DEAD-02 | — | Pending |
| DEAD-03 | — | Pending |
| DEAD-04 | — | Pending |
| NAME-01 | — | Pending |
| NAME-02 | — | Pending |
| NAME-03 | — | Pending |
| STRUCT-01 | — | Pending |
| STRUCT-02 | — | Pending |
| STRUCT-03 | — | Pending |
| VERIF-01 | — | Pending |
| VERIF-02 | — | Pending |

**Coverage:**
- v1 requirements: 12 total
- Mapped to phases: 0
- Unmapped: 12 ⚠️

---
*Requirements defined: 2026-02-08*
*Last updated: 2026-02-08 after v1.23 requirements definition*
