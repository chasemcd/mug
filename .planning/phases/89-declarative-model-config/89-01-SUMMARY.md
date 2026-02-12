---
phase: 89-declarative-model-config
plan: 01
subsystem: api
tags: [dataclass, onnx, builder-pattern, serialization, validation]

# Dependency graph
requires: []
provides:
  - "ModelConfig dataclass in configuration_constants.py"
  - "policy_configs parameter on GymScene.policies() with cross-validation"
  - "policy_configs parameter on RemoteConfig.policies() for legacy parity"
  - "Automatic transport of policy_configs through scene_metadata"
affects:
  - "90-js-inference-pipeline"
  - "91-custom-inference-escape-hatch"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ModelConfig.to_dict() for dataclass-to-dict serialization through scene_metadata"
    - "Cross-validation between policy_mapping and policy_configs in _validate_policy_configs()"

key-files:
  created: []
  modified:
    - "mug/configurations/configuration_constants.py"
    - "mug/scenes/gym_scene.py"
    - "mug/configurations/remote_config.py"

key-decisions:
  - "ModelConfig uses dataclasses.asdict() via to_dict() for scene_metadata transport"
  - "Validation runs when either policy_mapping or policy_configs is provided and the other is already set"
  - "RemoteConfig stores raw policy_configs without conversion or validation (legacy path)"

patterns-established:
  - "ModelConfig to_dict() pattern: dataclass -> plain dict for JSON serialization through scene_metadata"
  - "Cross-validation pattern: _validate_policy_configs() checks bidirectional consistency between two related dicts"

# Metrics
duration: 2min
completed: 2026-02-12
---

# Phase 89 Plan 01: Declarative Model Config Summary

**ModelConfig dataclass with obs/logit/state tensor fields, wired into GymScene.policies() builder with bidirectional cross-validation and automatic scene_metadata transport**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-12T04:35:50Z
- **Completed:** 2026-02-12T04:38:00Z
- **Tasks:** 1
- **Files modified:** 3

## Accomplishments
- ModelConfig dataclass with 5 fields (obs_input, logit_output, state_inputs, state_outputs, state_shape) and comprehensive __post_init__ validation
- GymScene.policies() accepts policy_configs, converts ModelConfig values to dicts, and cross-validates against policy_mapping with 3 error cases
- RemoteConfig.policies() accepts policy_configs for legacy path parity
- Serialized config flows through scene_metadata automatically via existing serialize_dict path

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ModelConfig dataclass and wire policies() builder with validation** - `d3814e1` (feat)

## Files Created/Modified
- `mug/configurations/configuration_constants.py` - Added ModelConfig dataclass with to_dict() and __post_init__ validation
- `mug/scenes/gym_scene.py` - Added policy_configs param to policies(), _validate_policy_configs() method, ModelConfig import
- `mug/configurations/remote_config.py` - Added policy_configs param to policies() for legacy parity

## Decisions Made
- ModelConfig uses `dataclasses.asdict()` for serialization (produces clean nested dicts that pass through `serialize_dict`/`is_json_serializable` without modification)
- Validation triggers when either `policy_mapping` or `policy_configs` is explicitly provided in a call and the counterpart is already set -- avoids false negatives with empty dicts
- RemoteConfig stores raw values without to_dict() conversion since it's the legacy path and doesn't go through scene_metadata serialization

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed validation trigger condition for empty policy_configs**
- **Found during:** Task 1 (verification step 3)
- **Issue:** Validation condition `if self.policy_mapping and self.policy_configs` was falsy when policy_configs was an empty dict `{}`, causing ONNX-without-config errors to go undetected
- **Fix:** Changed to track whether either parameter was explicitly provided in the current call, then validate whenever at least one was provided and either dict is non-empty
- **Files modified:** mug/scenes/gym_scene.py
- **Verification:** `GymScene().policies(policy_mapping={'a': 'x.onnx'}, policy_configs={})` now correctly raises ValueError
- **Committed in:** d3814e1 (part of Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential bug fix caught during verification. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ModelConfig dataclass and GymScene wiring complete
- JS client can now receive policy_configs through scene_metadata
- Ready for Phase 90 (JS Inference Pipeline) to consume these configs client-side

---
*Phase: 89-declarative-model-config*
*Completed: 2026-02-12*
