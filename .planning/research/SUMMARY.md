# Research Summary: v1.1 Sync Validation

**Project:** Interactive Gym P2P Multiplayer
**Milestone:** v1.1 Sync Validation
**Researched:** 2026-01-20
**Confidence:** HIGH

## Executive Summary

Adding sync validation to an existing GGPO-style rollback system requires careful integration with the confirmation flow. The key insight: **compute hashes only on confirmed frames** (not predicted) and **exchange via P2P DataChannel** (not SocketIO).

The existing codebase has partial infrastructure (`computeQuickStateHash()`, `stateHashHistory`) but it operates on potentially-predicted frames. v1.1 needs to tighten the integration so validation happens at the right time in the frame lifecycle.

**Critical finding:** Production netcode systems use fast checksums (CRC32), not cryptographic hashes (MD5). However, for this research use case with small state objects, SHA-256 (truncated) provides better cross-platform consistency and sufficient performance.

---

## Key Findings by Dimension

### Stack

| Choice | Recommendation | Rationale |
|--------|----------------|-----------|
| Hash algorithm | SHA-256 (truncated to 16 chars) | More reliable in Pyodide than MD5; guaranteed available |
| Serialization | `json.dumps(state, sort_keys=True, separators=(',', ':'))` | Already in use, deterministic with sort_keys |
| Float normalization | Round to 10 decimal places | Prevents cross-platform float representation differences |
| Hash location | Compute in Python/Pyodide | Ensures consistency with any server-side validation |

### Features

| Category | Features |
|----------|----------|
| **Table Stakes** | Per-frame state checksum, checksum exchange protocol, mismatch frame identification, state dump on mismatch, sync test mode |
| **Should Have** | Live sync debug overlay, deterministic replay validation |
| **Anti-Features** | Full state sync every frame, blocking validation, automated resync on every mismatch |

### Architecture

**Integration point:** Hash computation should occur in `processConfirmedFrame()` or equivalent, AFTER:
1. All players' inputs are confirmed for that frame
2. Rollback (if any) has completed
3. State has been stepped

**Hash exchange:** Add new binary message type `P2P_MSG_STATE_HASH` (0x07, 13 bytes) to existing DataChannel protocol.

**Mismatch handling:** Log and continue for research (need to KNOW about desyncs, not hide them).

### Pitfalls

| Priority | Pitfall | Prevention |
|----------|---------|------------|
| P0 | Frame alignment mismatch | Compare hashes only for exact same frame number |
| P0 | Rollback invalidates hashes | Clear hash history entries >= rollback target frame |
| P1 | JSON serialization non-determinism | Round floats, sort sets, use compact separators |
| P1 | Python set iteration order | Convert to sorted lists in `get_state()` |
| P2 | Validation export includes predictions | Export only confirmed-frame data |

---

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Hash Infrastructure

**Build:** Deterministic state hashing with float normalization, confirmed frame tracking.

- Addresses: Pitfalls #22 (JSON non-determinism), #24 (set iteration)
- Uses: SHA-256 via Python hashlib, `round(x, 10)` normalization
- Deliverable: `_computeConfirmedHash()` function, `confirmedHashHistory` data structure

### Phase 2: P2P Hash Exchange

**Build:** Binary hash message protocol, exchange over DataChannel.

- Implements: New message type 0x07, encoder/decoder
- Addresses: Moving from SocketIO to P2P for hash exchange
- Deliverable: `encodeStateHash()`, `decodeStateHash()`, message handler

### Phase 3: Mismatch Detection

**Build:** Comparison logic, peer hash buffering, desync event logging.

- Addresses: Pitfall #20 (frame alignment), #21 (rollback invalidation)
- Integrates with: Rollback system (clear hashes on rollback)
- Deliverable: `_handleReceivedHash()`, `desyncEvents` array, `verifiedFrame` tracking

### Phase 4: Validation Export

**Build:** Post-game JSON export with frame-by-frame validation data.

- Addresses: Pitfall #28 (predicted state in export)
- Deliverable: Export function producing `{frames: [{frame, localHash, peerHash, status}]}`

**Phase ordering rationale:**
- Phase 1 is foundation: can't exchange hashes until we can compute them correctly
- Phase 2 before 3: need transport before comparison logic
- Phase 3 before 4: need detection before export
- Each phase is independently testable

**Research flags:**
- Phase 1: Standard patterns, low risk
- Phase 2: Extension of existing P2P protocol, low risk
- Phase 3: Integration with rollback requires careful testing
- Phase 4: Straightforward JSON export

---

## Success Criteria

- [ ] Hashes computed only on confirmed frames (not predicted)
- [ ] Hash exchange uses P2P DataChannel (not SocketIO for this)
- [ ] Rollback invalidates affected hashes correctly
- [ ] Peer hash buffering handles async confirmation
- [ ] Desync detection logs frame, both hashes, and timestamp
- [ ] verifiedFrame tracks highest mutually-verified frame
- [ ] Post-game JSON export available for analysis
- [ ] No false positives from frame misalignment or float precision

---

## Open Questions (Resolved)

| Question | Resolution |
|----------|------------|
| Hash algorithm? | SHA-256 truncated to 16 chars |
| Where to compute? | In Python/Pyodide via `env.get_state()` |
| Exchange transport? | P2P DataChannel with new message type |
| Mismatch response? | Log and continue (research needs data, not recovery) |
| Export format? | JSON with frame-by-frame hashes and actions |

---

## Files Created

| File | Purpose |
|------|---------|
| [STACK.md](STACK.md) | Hashing technology choices, serialization patterns |
| [FEATURES.md](FEATURES.md) | Feature landscape with table stakes, differentiators, anti-features |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Integration with GGPO confirmation flow, data structures |
| [PITFALLS.md](PITFALLS.md) | Updated with 9 v1.1-specific validation pitfalls (#20-#28) |

---

*Research complete: 2026-01-20*
