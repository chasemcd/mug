---
phase: 90-lstm-state-persistence
plan: 01
subsystem: js-inference
tags: [onnx, javascript, lstm, hidden-state, recurrent, browser]

# Dependency graph
requires:
  - "89-02: Config-driven JS ONNX inference with dual-path feed construction"
provides:
  - "Per-agent hidden state isolation using agentID keys instead of policyID"
  - "Legacy path output state capture (state_out_N -> state_in_N mapping)"
affects:
  - "91-custom-inference-escape-hatch"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-agent hidden state keying: hiddenStates[agentID] isolates recurrent state per agent, while loadedModels[policyID] shares ONNX sessions"
    - "Legacy output state capture: state_out_ outputs mapped to state_in_ inputs following RLlib naming convention"

key-files:
  created: []
  modified:
    - "mug/server/static/js/onnx_inference.js"

key-decisions:
  - "agentID used as hidden state key (not policyID) so multiple agents sharing one model maintain independent recurrent states"
  - "Legacy output capture uses string replacement (state_out_ -> state_in_) matching the existing legacy input detection pattern"

patterns-established:
  - "Per-agent state isolation: ONNX sessions shared by policyID, hidden states isolated by agentID"

# Metrics
duration: 1min
completed: 2026-02-12
---

# Phase 90 Plan 01: LSTM State Persistence Summary

**Per-agent hidden state keying via agentID and legacy path output state capture for correct LSTM/GRU recurrent inference across multi-agent scenarios**

## Performance

- **Duration:** 1 min
- **Started:** 2026-02-12T04:56:28Z
- **Completed:** 2026-02-12T04:57:21Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- All hiddenStates reads/writes re-keyed from policyID to agentID, enabling multiple agents sharing one ONNX model to maintain independent hidden states
- agentID parameter added to inferenceONNXPolicy function signature and passed from actionFromONNX call site
- Legacy path now captures state_out_N outputs and stores them as state_in_N for next inference step, fixing LSTM states always being zeros in legacy mode
- Model session loading (loadedModels) preserved using policyID to avoid unnecessary model duplication

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix hidden state keying to agentID and add legacy output state capture** - `9cf5799` (feat)

## Files Created/Modified
- `mug/server/static/js/onnx_inference.js` - Re-keyed all hiddenStates from policyID to agentID, added agentID to inferenceONNXPolicy signature, added legacy output state capture block

## Decisions Made
- **agentID as hidden state key:** policyID identifies the shared ONNX session (model file), but multiple agents can share one policy. Using agentID prevents hidden state corruption when two agents use the same recurrent model.
- **Legacy output capture via string replacement:** `state_out_` prefix replaced with `state_in_` mirrors the existing legacy input detection pattern (`name.startsWith('state_in_')`), maintaining consistency with the RLlib naming convention already established in the codebase.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 90 (LSTM State Persistence) complete: both declarative and legacy paths now correctly persist and feed back hidden states per-agent
- Ready for Phase 91 (Custom Inference Escape Hatch) or further inference pipeline work

## Self-Check: PASSED

- FOUND: mug/server/static/js/onnx_inference.js
- FOUND: 90-01-SUMMARY.md
- FOUND: commit 9cf5799

---
*Phase: 90-lstm-state-persistence*
*Completed: 2026-02-12*
