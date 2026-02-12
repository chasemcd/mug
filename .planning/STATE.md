# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-11)

**Core value:** Researchers can configure and deploy multiplayer browser experiments with minimal code
**Current focus:** v1.28 Configurable Inference -- Phase 89 (Declarative Model Config)

## Current Position

Phase: 89 (1 of 4 in v1.28) -- Declarative Model Config
Plan: 1 of 2 in current phase
Status: Executing
Last activity: 2026-02-12 -- Completed 89-01 (ModelConfig dataclass + policies() wiring)

Progress: [█████░░░░░] 50%

## Performance Metrics

**Velocity:**
- Total plans completed: 1 (v1.28)
- Average duration: 2min
- Total execution time: 0.03 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 89 | 1 | 2min | 2min |

## Accumulated Context

### Decisions

- [87-01] Anchor-based snapshot pruning: highest snapshot <= confirmedFrame retained, all before deleted
- [87-01] Input buffer prunes at confirmedFrame boundary only, no hardcoded frame offset
- [89-01] ModelConfig uses dataclasses.asdict() via to_dict() for scene_metadata transport
- [89-01] Validation triggers when either policy_mapping or policy_configs explicitly provided
- [89-01] RemoteConfig stores raw policy_configs without conversion (legacy path)

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-02-12
Stopped at: Completed 89-01-PLAN.md (ModelConfig dataclass + policies() builder wiring)
Resume file: None
Next action: Execute 89-02-PLAN.md
