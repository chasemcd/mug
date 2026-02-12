# Requirements: Multi-User Gymnasium (MUG)

**Defined:** 2026-02-11
**Core Value:** Researchers can configure and deploy multiplayer browser experiments with minimal code

## v1.28 Requirements

Requirements for configurable client-side ONNX inference -- replacing hardcoded RLlib LSTM assumptions with flexible, user-specified model config.

### Declarative Config

- [ ] **DECL-01**: User can specify observation input tensor name per policy via Python builder API
- [ ] **DECL-02**: User can specify logit output tensor name per policy via Python builder API
- [ ] **DECL-03**: User can specify hidden state input/output tensor names per policy (not locked to `state_in_*`/`state_out_*`)
- [ ] **DECL-04**: User can specify hidden state tensor shapes per policy (not locked to `[1, 256]`)
- [ ] **DECL-05**: Declarative inference config flows from Python scene_metadata to JS client automatically

### State Persistence

- [ ] **STATE-01**: After ONNX inference, output state tensors are captured and cached for the next step
- [ ] **STATE-02**: On next inference step, cached output state tensors are fed as input state tensors
- [ ] **STATE-03**: Hidden states are initialized to zeros with the configured shape on first inference call

### Custom Inference

- [ ] **CUST-01**: User can provide an inline JS function string via Python builder API that handles inference
- [ ] **CUST-02**: Custom inference function receives the ONNX session, observation, and model config as arguments
- [ ] **CUST-03**: When custom inference function is specified, it takes precedence over the declarative path

### Verification

- [ ] **VER-01**: All existing tests pass with no regressions

## v1.27 Requirements (Shipped)

<details>
<summary>Principled Rollback Management (10 requirements)</summary>

### Snapshot Management

- [x] **SNAP-01**: Snapshot pruning tied to `confirmedFrame`
- [x] **SNAP-02**: `maxSnapshots` parameter removed
- [x] **SNAP-03**: Anchor snapshot always retained

### Input Buffer Management

- [x] **IBUF-01**: Input buffer pruning tied to `confirmedFrame`
- [x] **IBUF-02**: Hardcoded `pruneThreshold` removed
- [x] **IBUF-03**: `inputBufferMaxSize` removed

### Configuration

- [x] **CONF-01**: `snapshot_interval` added to `GymScene.multiplayer()`
- [x] **CONF-02**: JS constructor reads `config.snapshot_interval`

### Verification

- [x] **VER-01**: All existing tests pass
- [x] **VER-02**: Rollback correctness preserved

</details>

## Out of Scope

| Feature | Reason |
|---------|--------|
| Softmax temperature / sampling params | Not needed for this milestone; can add later |
| Observation preprocessing (normalization, reshaping) | Users can handle in custom function if needed |
| Action masking | Separate concern, different milestone |
| Non-ONNX model formats (TensorFlow.js, etc.) | ONNX is the only client-side format for now |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DECL-01 | Phase 89 | Pending |
| DECL-02 | Phase 89 | Pending |
| DECL-03 | Phase 89 | Pending |
| DECL-04 | Phase 89 | Pending |
| DECL-05 | Phase 89 | Pending |
| STATE-01 | Phase 90 | Pending |
| STATE-02 | Phase 90 | Pending |
| STATE-03 | Phase 90 | Pending |
| CUST-01 | Phase 91 | Pending |
| CUST-02 | Phase 91 | Pending |
| CUST-03 | Phase 91 | Pending |
| VER-01 | Phase 92 | Pending |

**Coverage:**
- v1.28 requirements: 12 total
- Mapped to phases: 12
- Unmapped: 0

---
*Requirements defined: 2026-02-11*
*Last updated: 2026-02-11 after roadmap creation*
