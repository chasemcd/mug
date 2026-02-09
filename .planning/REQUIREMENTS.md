# Requirements: Interactive Gym

**Defined:** 2026-02-09
**Core Value:** Researchers can configure and deploy multiplayer browser experiments with minimal code — a chained scene config and a Python environment are all that's needed.

## v1.25 Requirements

### Data Export

- [ ] **DEXP-01**: Scene metadata exports to `data/{experiment_id}/{scene_id}/` instead of `data/{scene_id}/`
- [ ] **DEXP-02**: Match logs export to `data/{experiment_id}/match_logs/` instead of `data/match_logs/`
- [ ] **DEXP-03**: Existing tests pass with updated export paths
- [ ] **DEXP-04**: All data produced by an experiment resides under `data/{experiment_id}/`

## Future Requirements

(None)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Retroactive migration of old data | Not needed — this is a pre-merge fix |
| Configurable data directory root | Adds complexity for no current need |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DEXP-01 | — | Pending |
| DEXP-02 | — | Pending |
| DEXP-03 | — | Pending |
| DEXP-04 | — | Pending |

**Coverage:**
- v1.25 requirements: 4 total
- Mapped to phases: 0
- Unmapped: 4 ⚠️

---
*Requirements defined: 2026-02-09*
*Last updated: 2026-02-09 after initial definition*
