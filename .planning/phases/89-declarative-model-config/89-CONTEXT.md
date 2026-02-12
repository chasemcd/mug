# Phase 89: Declarative Model Config - Context

**Gathered:** 2026-02-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Python builder API for ONNX tensor config (names, shapes) per policy, with automatic transport to the JS client. Users can configure observation input, logit output, and hidden state tensor names/shapes per policy via `policy_configs` on the existing `.policies()` builder method. Config arrives in the JS client without manual JSON passing.

Action processing (softmax, sampling strategy) is NOT in scope — that's Phase 91.

</domain>

<decisions>
## Implementation Decisions

### Builder API shape
- Use the existing `policy_configs` parameter on `.policies()` builder method — keeps policy_mapping clean (just paths) and config separate
- Introduce a `ModelConfig` dataclass for the config values — gives researchers IDE autocomplete and validation
- Use ONNX-oriented parameter names: `obs_input`, `logit_output`, `state_inputs`, `state_outputs`, `state_shape`
- Support multiple hidden state tensor pairs (e.g., LSTM h and c states): `state_inputs=['state_in_0', 'state_in_1']`, `state_outputs=['state_out_0', 'state_out_1']`, each with its own shape
- No factory methods or presets — every config is fully explicit, no `ModelConfig.rllib_lstm()` shortcuts

### Default behavior
- Explicit config required — every ONNX policy in `policy_mapping` must have a corresponding `policy_configs` entry, no implicit defaults
- Validation happens Python-side during scene setup — fail fast with a clear error message before anything reaches the JS client
- State fields (`state_inputs`, `state_outputs`, `state_shape`) are optional — omitting them means non-recurrent model. Only `obs_input` and `logit_output` are required

### Per-policy config
- `policy_configs` keys must exactly match `policy_mapping` keys — same policy ID string
- Sharing a single `ModelConfig` instance across multiple policy IDs is allowed
- Bidirectional validation: error if ONNX policy has no config, AND error if config references a nonexistent policy
- Error if a human policy (`PolicyTypes.Human`) has a `policy_config` entry — catch researcher mistakes early

### Action processing scope
- Softmax + categorical sampling code in JS stays as-is for Phase 89 — no refactoring
- Action processing configurability deferred to Phase 91 (Custom Inference Escape Hatch)
- `logit_output` is a tensor name string (e.g., `'output'`), not an index — researcher must know the exact ONNX tensor name
- Single observation tensor only (`obs_input='obs'`) — multi-input models use Phase 91 escape hatch

### Claude's Discretion
- Exact dataclass field types and validation logic
- How ModelConfig serializes for transport to JS client
- JS-side deserialization and config consumption pattern
- Error message wording

</decisions>

<specifics>
## Specific Ideas

- `policy_configs` attribute already exists on `GymScene` but is unused — wire it up rather than adding new attributes
- Config transport should flow through the existing `scene_metadata` path that already carries `policy_mapping` to the JS client
- Example usage pattern:
  ```python
  scene = (
      GymScene()
      .policies(
          policy_mapping={
              "agent_right": PolicyTypes.Human,
              "agent_left": "static/assets/models/model.onnx",
          },
          policy_configs={
              "agent_left": ModelConfig(
                  obs_input="obs",
                  logit_output="output",
                  state_inputs=["state_in_0", "state_in_1"],
                  state_outputs=["state_out_0", "state_out_1"],
                  state_shape=[1, 256],
              ),
          },
      )
  )
  ```

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 89-declarative-model-config*
*Context gathered: 2026-02-11*
