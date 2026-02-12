# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-11)

**Core value:** Researchers can configure and deploy multiplayer browser experiments with minimal code
**Current focus:** v1.28 Configurable Inference -- Phase 91 (Custom Inference Escape Hatch)

## Current Position

Phase: 91 (3 of 4 in v1.28) -- Custom Inference Escape Hatch [COMPLETE]
Plan: 1 of 1 in current phase
Status: Phase Complete
Last activity: 2026-02-12 -- Completed 91-01 (Custom inference escape hatch)

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 4 (v1.28)
- Average duration: 2min
- Total execution time: 0.11 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 89 | 2 | 4min | 2min |
| 90 | 1 | 1min | 1min |
| 91 | 1 | 2min | 2min |

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
- [90-01] agentID used as hidden state key (not policyID) so multiple agents sharing one model maintain independent recurrent states
- [90-01] Legacy output capture uses string replacement (state_out_ -> state_in_) matching existing legacy input detection pattern
- [91-01] AsyncFunction constructor used for custom_inference_fn to support await in function bodies
- [91-01] compiledCustomFns cache keyed by agentID (same agent always has same config)
- [91-01] Custom inference path returns action directly -- no softmax, no sampleAction, full researcher control

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-02-12
Stopped at: Completed 91-01-PLAN.md (Custom inference escape hatch)
Resume file: None
Next action: Phase 91 complete. Next phase: 92 (Integration Testing)
