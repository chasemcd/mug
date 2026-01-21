# Roadmap: Interactive Gym P2P Multiplayer

## Milestones

- **v1.0 P2P Multiplayer** - Phases 1-10 (shipped 2026-01-19)
- **v1.1 Sync Validation** - Phases 11-14 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

<details>
<summary>v1.0 P2P Multiplayer (Phases 1-10) - SHIPPED 2026-01-19</summary>

See `.planning/archive/v1.0/` for completed phase details.

Key deliverables:
- WebRTC DataChannel P2P connections
- GGPO-style rollback netcode
- Binary P2P protocol with redundancy
- TURN server fallback
- Symmetric peer architecture

</details>

### v1.1 Sync Validation (In Progress)

**Milestone Goal:** Build a validation system that confirms verified action sequences and state hashes are identical across all peers, enabling debugging of non-deterministic environments and networking issues.

- [x] **Phase 11: Hash Infrastructure** - Deterministic state hashing with confirmed frame tracking
- [x] **Phase 12: P2P Hash Exchange** - Binary hash message protocol over DataChannel
- [ ] **Phase 13: Mismatch Detection** - Comparison logic, peer buffering, desync logging
- [ ] **Phase 14: Validation Export** - Post-game JSON export with frame-by-frame data

## Phase Details

### Phase 11: Hash Infrastructure
**Goal:** Deterministic state hashing with float normalization, confirmed frame tracking
**Depends on:** v1.0 complete (existing P2P infrastructure)
**Requirements:** HASH-01, HASH-02, HASH-03, HASH-04
**Success Criteria** (what must be TRUE):
  1. State hash computed only after all inputs confirmed for a frame
  2. Floats normalized to 10 decimal places before serialization
  3. SHA-256 hash produces identical results across browsers
  4. confirmedHashHistory tracks frame-to-hash mapping
**Research flag:** Unlikely (standard patterns)
**Plans:** 1 plan
Plans:
- [x] 11-01-PLAN.md — SHA-256 hashing, float normalization, confirmedHashHistory, rollback invalidation

### Phase 12: P2P Hash Exchange
**Goal:** Binary hash message protocol over DataChannel
**Depends on:** Phase 11
**Requirements:** EXCH-01, EXCH-02, EXCH-03, EXCH-04
**Success Criteria** (what must be TRUE):
  1. Hashes exchanged via P2P DataChannel (not SocketIO)
  2. Hash exchange doesn't block frame advancement
  3. Hash history cleared when rollback invalidates frames
  4. Binary message format (13 bytes) works correctly
**Research flag:** Unlikely (extension of existing protocol)
**Plans:** 1 plan
Plans:
- [x] 12-01-PLAN.md — P2P_MSG_STATE_HASH protocol, encode/decode, exchange queue, rollback invalidation

### Phase 13: Mismatch Detection
**Goal:** Comparison logic, peer buffering, desync event logging
**Depends on:** Phase 12
**Requirements:** DETECT-01, DETECT-02, DETECT-03, DETECT-04, DETECT-05
**Success Criteria** (what must be TRUE):
  1. Exact frame number identified when mismatch occurs
  2. Peer hashes buffered until local confirmation catches up
  3. Desync events logged with frame, both hashes, timestamp
  4. verifiedFrame tracks highest mutually-verified frame
  5. Full state dump captured on mismatch
**Research flag:** Unlikely (architecture documented, patterns from prior phases)
**Plans:** 1 plan
Plans:
- [ ] 13-01-PLAN.md — verifiedFrame tracking, desyncEvents logging, comparison logic, rollback integration (planned)

### Phase 14: Validation Export
**Goal:** Post-game JSON export with frame-by-frame validation data
**Depends on:** Phase 13
**Requirements:** EXPORT-01, EXPORT-02, EXPORT-03, EXPORT-04
**Success Criteria** (what must be TRUE):
  1. JSON export available after game ends
  2. Export contains only confirmed-frame data (no predictions)
  3. Desync events included in export
  4. Verified action sequences exported per player
**Research flag:** Unlikely (straightforward JSON export)
**Plans:** TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 11 -> 12 -> 13 -> 14

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 11. Hash Infrastructure | v1.1 | 1/1 | Complete | 2026-01-21 |
| 12. P2P Hash Exchange | v1.1 | 1/1 | Complete | 2026-01-21 |
| 13. Mismatch Detection | v1.1 | 0/1 | Planning complete | - |
| 14. Validation Export | v1.1 | 0/TBD | Not started | - |

---
*Roadmap created: 2026-01-20*
*Last updated: 2026-01-21 after Phase 13 planning complete*
