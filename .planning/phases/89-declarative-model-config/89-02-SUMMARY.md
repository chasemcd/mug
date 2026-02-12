---
phase: 89-declarative-model-config
plan: 02
subsystem: js-inference
tags: [onnx, javascript, tensor-config, inference, browser]

# Dependency graph
requires:
  - "89-01: ModelConfig dataclass and policy_configs transport via scene_metadata"
provides:
  - "Config-driven JS ONNX inference reading tensor names/shapes from policy_configs"
  - "initModelConfigs() export for scene initialization"
  - "Legacy fallback path for existing examples without policy_configs"
affects:
  - "91-custom-inference-escape-hatch"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Config-driven feed construction: modelConfig fields drive ONNX tensor names instead of hardcoded strings"
    - "Dual-path inference: declarative (config-driven) vs legacy (hardcoded) selected by config presence"

key-files:
  created: []
  modified:
    - "mug/server/static/js/onnx_inference.js"
    - "mug/server/static/js/phaser_gym_graphics.js"

key-decisions:
  - "agentID passed through call chain (queryBotPolicy -> actionFromONNX -> getModelConfig) rather than ONNX path lookup"
  - "Hidden state outputs stored against corresponding input names for next-step feed reuse"
  - "seq_lens feed only in legacy path -- not needed in declarative path since it is an RLlib convention"

patterns-established:
  - "Config-driven inference: check modelConfig presence to choose declarative vs legacy path"
  - "State output mapping: state_outputs[i] result stored under state_inputs[i] key for next inference step"

# Metrics
duration: 2min
completed: 2026-02-12
---

# Phase 89 Plan 02: JS ONNX Inference Config Consumption Summary

**Config-driven ONNX inference in JS consuming obs_input, logit_output, state_inputs/outputs, and state_shape from scene_metadata policy_configs with full legacy fallback**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-12T04:39:53Z
- **Completed:** 2026-02-12T04:41:27Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- onnx_inference.js reads all 5 ModelConfig fields (obs_input, logit_output, state_inputs, state_outputs, state_shape) from policy_configs when available
- Dual-path inference: declarative path uses config-driven tensor names, legacy path preserves all hardcoded behavior (obs, state_in_*, [1,256], session.outputNames[0], state_ins, seq_lens)
- Hidden state output capture: state_outputs results stored against corresponding state_inputs names for correct next-step feeding
- phaser_gym_graphics.js initializes config store on scene creation and passes agentID through to inference

## Task Commits

Each task was committed atomically:

1. **Task 1: Update onnx_inference.js to use declarative model config** - `606af14` (feat)

## Files Created/Modified
- `mug/server/static/js/onnx_inference.js` - Added policyConfigs store, initModelConfigs() export, getModelConfig() helper, dual-path feed construction, config-driven output extraction, hidden state output capture
- `mug/server/static/js/phaser_gym_graphics.js` - Updated import to include initModelConfigs, added init call in GymScene constructor, passes agentID to actionFromONNX

## Decisions Made
- **agentID routing over ONNX path lookup:** policy_configs is keyed by agent ID (matching policy_mapping keys), so agentID is passed through the call chain rather than trying to reverse-lookup from the ONNX model path
- **Hidden state output-to-input mapping by index:** state_outputs[i] result is stored under state_inputs[i] for the next inference step, assuming paired ordering
- **seq_lens excluded from declarative path:** seq_lens is an RLlib-specific convention only needed in the legacy fallback, not in the general declarative path

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 89 (Declarative Model Config) is now complete: Python-side ModelConfig + validation (Plan 01) and JS-side config consumption (Plan 02)
- All 5 config fields flow end-to-end: Python dataclass -> scene_metadata transport -> JS inference consumption
- Ready for Phase 90 (JS Inference Pipeline) or Phase 91 (Custom Inference Escape Hatch)

## Self-Check: PASSED

- FOUND: mug/server/static/js/onnx_inference.js
- FOUND: mug/server/static/js/phaser_gym_graphics.js
- FOUND: 89-02-SUMMARY.md
- FOUND: commit 606af14

---
*Phase: 89-declarative-model-config*
*Completed: 2026-02-12*
