# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-11)

**Core value:** Researchers can configure and deploy multiplayer browser experiments with minimal code
**Current focus:** v1.28 Configurable Inference -- Phase 89 (Declarative Model Config)

## Current Position

Phase: 89 (1 of 4 in v1.28) -- Declarative Model Config [COMPLETE]
Plan: 2 of 2 in current phase
Status: Phase Complete
Last activity: 2026-02-12 -- Completed 89-02 (JS ONNX inference config consumption)

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 2 (v1.28)
- Average duration: 2min
- Total execution time: 0.07 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 89 | 2 | 4min | 2min |

## Accumulated Context

### Decisions

- [87-01] Anchor-based snapshot pruning: highest snapshot <= confirmedFrame retained, all before deleted
- [87-01] Input buffer prunes at confirmedFrame boundary only, no hardcoded frame offset
- [89-01] ModelConfig uses dataclasses.asdict() via to_dict() for scene_metadata transport
- [89-01] Validation triggers when either policy_mapping or policy_configs explicitly provided
- [89-01] RemoteConfig stores raw policy_configs without conversion (legacy path)
- [89-02] agentID passed through call chain for config lookup rather than ONNX path reverse-lookup
- [89-02] Hidden state output-to-input mapping by paired index (state_outputs[i] -> state_inputs[i])
- [89-02] seq_lens excluded from declarative path (RLlib convention, legacy only)

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-02-12
Stopped at: Completed 89-02-PLAN.md (JS ONNX inference config consumption)
Resume file: None
Next action: Phase 89 complete. Next phase: 90 (JS Inference Pipeline)
