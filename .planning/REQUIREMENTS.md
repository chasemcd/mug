# Requirements: Interactive Gym v1.1 Sync Validation

**Defined:** 2026-01-20
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1.1 Requirements

Requirements for sync validation milestone. Each maps to roadmap phases.

### State Hashing

- [x] **HASH-01**: System computes state hash only on confirmed frames (not predicted)
- [x] **HASH-02**: System normalizes floats to 10 decimal places before hashing
- [x] **HASH-03**: System uses SHA-256 (truncated to 16 chars) for deterministic cross-platform hashing
- [x] **HASH-04**: System maintains confirmedHashHistory with frame-to-hash mapping

### Hash Exchange

- [x] **EXCH-01**: System sends state hashes via P2P DataChannel (message type 0x07)
- [x] **EXCH-02**: System exchanges hashes asynchronously without blocking frame advancement
- [x] **EXCH-03**: System invalidates hash history entries when rollback occurs (frames >= target)
- [x] **EXCH-04**: System encodes hash messages in binary format (13 bytes: type + frame + hash)

### Mismatch Detection

- [x] **DETECT-01**: System identifies exact frame number where mismatch occurred
- [x] **DETECT-02**: System buffers peer hashes until local confirmation catches up
- [x] **DETECT-03**: System logs desync events with frame, both hashes, and timestamp
- [x] **DETECT-04**: System tracks verifiedFrame as highest mutually-verified frame
- [x] **DETECT-05**: System captures full state dump when mismatch detected

### Validation Export

- [x] **EXPORT-01**: System exports post-game JSON with frame-by-frame hashes and actions
- [x] **EXPORT-02**: System exports only confirmed-frame data (excludes predictions)
- [x] **EXPORT-03**: System includes desync events in validation export
- [x] **EXPORT-04**: System exports verified action sequences per player

## v2 Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Development Tools

- **TOOL-01**: Sync test mode for single-player determinism validation
- **TOOL-02**: Live sync debug overlay showing validation metrics
- **TOOL-03**: Hierarchical checksums for subsystem-level debugging
- **TOOL-04**: Frame diff logging with side-by-side state comparison

### Advanced Validation

- **ADV-01**: Deterministic replay validation for CI regression tests
- **ADV-02**: Cross-platform determinism validation (Chrome/Firefox/Safari)
- **ADV-03**: Binary search desync localization

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Full state sync every frame | Massive bandwidth; defeats purpose of input-based sync |
| Blocking validation | Kills responsiveness; validation can trail simulation |
| Automated resync on mismatch | Research needs to KNOW about desyncs, not hide them |
| Cryptographic hash for security | Overkill — integrity checking, not security |
| Complex serialization (protobuf) | JSON with deterministic ordering is sufficient |

## Traceability

Which phases cover which requirements.

| Requirement | Phase | Status |
|-------------|-------|--------|
| HASH-01 | Phase 11 | Complete |
| HASH-02 | Phase 11 | Complete |
| HASH-03 | Phase 11 | Complete |
| HASH-04 | Phase 11 | Complete |
| EXCH-01 | Phase 12 | Complete |
| EXCH-02 | Phase 12 | Complete |
| EXCH-03 | Phase 12 | Complete |
| EXCH-04 | Phase 12 | Complete |
| DETECT-01 | Phase 13 | Complete |
| DETECT-02 | Phase 13 | Complete |
| DETECT-03 | Phase 13 | Complete |
| DETECT-04 | Phase 13 | Complete |
| DETECT-05 | Phase 13 | Complete |
| EXPORT-01 | Phase 14 | Complete |
| EXPORT-02 | Phase 14 | Complete |
| EXPORT-03 | Phase 14 | Complete |
| EXPORT-04 | Phase 14 | Complete |

**Coverage:**
- v1.1 requirements: 17 total
- Mapped to phases: 17 ✓
- Unmapped: 0

---
*Requirements defined: 2026-01-20*
*Last updated: 2026-01-21 after Phase 14 execution complete — all v1.1 requirements satisfied*
