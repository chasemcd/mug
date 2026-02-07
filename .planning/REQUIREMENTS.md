# Requirements: Interactive Gym v1.21 Latency-Aware Matchmaking

**Defined:** 2026-02-07
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1 Requirements

Requirements for v1.21 Latency-Aware Matchmaking. Each maps to roadmap phases.

### Matchmaking

- [ ] **MATCH-01**: LatencyFIFOMatchmaker class extends Matchmaker base with server RTT pre-filtering in `find_match()`
- [ ] **MATCH-02**: Researcher can configure `max_server_rtt_ms` threshold for estimated P2P RTT filtering (estimated P2P RTT = sum of server RTTs)
- [x] **MATCH-03**: LatencyFIFOMatchmaker integrates with existing `max_p2p_rtt_ms` for post-match P2P probe verification
- [ ] **MATCH-04**: LatencyFIFOMatchmaker falls back gracefully when server RTT data is unavailable for a candidate
- [x] **MATCH-05**: Researcher can configure LatencyFIFOMatchmaker via `scene.matchmaking(matchmaker=LatencyFIFOMatchmaker(...))`

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Matchmaking Enhancements

- **MATCH-D1**: Adaptive RTT thresholds that relax over wait time
- **MATCH-D2**: Geographic region-based pre-filtering
- **MATCH-D3**: Skill-based matchmaking with latency constraints
- **MATCH-D4**: Priority queuing for dropout recovery
- **MATCH-D5**: Pre-match validation hook (beyond RTT, e.g., custom compatibility checks)

### GGPO Parity

- **GGPO-01**: Fix content divergence under packet loss + active inputs (increase snapshot coverage + eager rollback)

### CI Integration

- **CI-01**: E2E tests run in CI/CD pipeline (headless mode or headed with Xvfb)
- **CI-02**: Test results reported in PR checks

### Full Off-Main-Thread

- **WORKER-01**: Move per-frame `runPythonAsync()` to a Web Worker
- **WORKER-02**: Batch rollback operations in single Worker round-trip

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Custom matchmaking UI | Researcher-facing API only, no player-visible matchmaking UI changes |
| Server-authoritative latency measurement | P2P probe already exists; server RTT is a heuristic pre-filter |
| N-player latency-aware matchmaking | Current scope is 2-player pairs only |
| Adaptive threshold relaxation | Deferred to v2 (MATCH-D1) |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| MATCH-01 | Phase 81 | Complete |
| MATCH-02 | Phase 81 | Complete |
| MATCH-03 | Phase 82 | Complete |
| MATCH-04 | Phase 81 | Complete |
| MATCH-05 | Phase 82 | Complete |

**Coverage:**
- v1 requirements: 5 total
- Mapped to phases: 5
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-07*
*Last updated: 2026-02-07 after Phase 82 execution*
