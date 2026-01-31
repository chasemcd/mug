# Requirements: Interactive Gym v1.8 Data Export Parity

**Defined:** 2026-01-30
**Core Value:** Both players in a multiplayer game export identical game state data (actions, observations, rewards, infos) regardless of rollbacks, fast-forwards, or latency — ensuring research data validity.

## v1.8 Requirements

Requirements for v1.8 Data Export Parity milestone. Each maps to roadmap phases.

### Data Recording

- [x] **REC-01**: Data is stored in a speculative buffer during frame execution
- [x] **REC-02**: Data is promoted to confirmed buffer only when all players' inputs for that frame are received
- [x] **REC-03**: Export reads only from confirmed buffer, never from speculative buffer
- [ ] **REC-04**: Each frame includes `wasSpeculative` metadata indicating if it was ever predicted

### Edge Case Handling

- [x] **EDGE-01**: Fast-forward (tab refocus) uses the same confirmation-gated recording path as normal execution
- [ ] **EDGE-02**: Episode end waits for all frames to be confirmed before triggering export
- [ ] **EDGE-03**: Export includes rollback event metadata (frame ranges, count per frame)

### Verification

- [ ] **VERIFY-01**: Offline validation script can compare two player export files and report divergences

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Data Recording

- **REC-05**: Include input delay metrics per frame
- **REC-06**: Include confirmation timing metrics per frame

### Verification

- **VERIFY-02**: Per-frame hash verification status from Phase 11-14 infrastructure
- **VERIFY-03**: Real-time divergence detection alert

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Server-authoritative data source | P2P architecture has no server running the game |
| Real-time data streaming to server | Network overhead; batch export at episode end sufficient |
| Waiting for confirmation before stepping | Would transform rollback into lockstep, killing responsiveness |
| Single global "authoritative" export | No single authority in P2P; both peers export, verify equivalence offline |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| REC-01 | Phase 36 | Complete |
| REC-02 | Phase 36 | Complete |
| REC-03 | Phase 36 | Complete |
| REC-04 | Phase 39 | Pending |
| EDGE-01 | Phase 37 | Complete |
| EDGE-02 | Phase 38 | Pending |
| EDGE-03 | Phase 39 | Pending |
| VERIFY-01 | Phase 39 | Pending |

**Coverage:**
- v1.8 requirements: 8 total
- Mapped to phases: 8 ✓
- Unmapped: 0

---
*Requirements defined: 2026-01-30*
*Last updated: 2026-01-30 after roadmap creation*
