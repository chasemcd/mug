# Project Research Summary

**Project:** Interactive Gym P2P Multiplayer
**Domain:** Browser-based P2P GGPO rollback netcode for RL research experiments
**Researched:** 2026-01-16
**Confidence:** MEDIUM-HIGH

## Executive Summary

The interactive-gym codebase already contains a comprehensive GGPO-style rollback netcode implementation (2600+ lines in `pyodide_multiplayer_game.js`) with input delay, state snapshots, rollback/replay, prediction, and state hash verification. The missing piece is **true P2P communication via WebRTC DataChannels** to replace the current SocketIO server relay. This architectural change will reduce input latency from 100-200ms (server round-trip) to direct peer-to-peer latency (typically 20-50ms for geographically close players).

The recommended approach is to use the native WebRTC API directly (no wrapper libraries like simple-peer or PeerJS) with SocketIO remaining as the signaling channel for ICE/SDP exchange. This leverages existing infrastructure while adding near-UDP latency for input exchange. TURN servers (Metered.ca recommended) are necessary for ~15-20% of connections where direct P2P fails due to NAT configurations.

The primary risks are: (1) non-deterministic environment execution causing desyncs that rollback cannot fix, (2) input buffer pruning race conditions during rollback, and (3) DataChannel reliability mode misconfiguration. All critical GGPO features already exist; the work is primarily transport layer replacement and integration testing. For research validity, connection type (direct vs TURN relay) must be recorded in session data.

## Key Findings

### Recommended Stack

The existing stack (Flask, SocketIO, Pyodide, Gymnasium, Phaser.js) remains unchanged. WebRTC DataChannels are added as a new transport layer for game inputs.

**Core technologies:**
- **Native WebRTC API**: P2P DataChannel connections -- browser-native, well-documented, no dependency maintenance
- **SocketIO (existing)**: ICE candidate/SDP signaling -- already in place, proven reliable
- **Metered.ca TURN**: NAT traversal fallback -- pay-as-you-go, ~$5/month for research scale
- **msgpack (existing)**: Binary serialization -- 3x smaller messages than JSON

**DataChannel configuration for GGPO:**
```javascript
{ ordered: false, maxRetransmits: 0 }  // UDP-like behavior
```

### Expected Features

**Must have (table stakes -- all exist):**
- Deterministic simulation via Pyodide + seeded RNG
- Configurable input delay (0-5 frames)
- Frame-indexed input buffer with prediction
- State snapshots with RNG capture
- Rollback/replay mechanism
- State hash verification for desync detection
- Server-authoritative fallback
- Sync epoch for episode boundaries

**Should have (differentiators for P2P milestone):**
- WebRTC DataChannels for input exchange (PENDING)
- TURN server fallback for NAT traversal (PENDING)
- Symmetric peer architecture -- no host concept (PENDING)
- Connection type detection and logging (PENDING)

**Defer (v2+):**
- Adaptive input delay based on RTT
- Frame interpolation for smoother rendering
- Rollback visualization for debugging
- N-player mesh topology (start with 2-player)
- Spectator mode (out of scope per PROJECT.md)

### Architecture Approach

The target architecture separates concerns into: WebRTCManager (connection lifecycle), P2PTransport (message protocol), GGPOManager (input sync/rollback), and PyodideEnv (deterministic simulation). The server role changes from input relay to signaling-only, with optional data logging.

**Major components:**
1. **WebRTCManager (new)** -- establish/manage peer connections, handle ICE negotiation
2. **P2PTransport (new)** -- serialize/deserialize messages, send/receive over DataChannel
3. **GGPOManager (existing)** -- input buffering, prediction, rollback orchestration
4. **PyodideEnv (existing)** -- deterministic game simulation with get_state/set_state
5. **SignalingRelay (modify)** -- server-side forwarding of WebRTC offer/answer/ICE

### Critical Pitfalls

1. **Non-deterministic environment execution** -- Validate environments produce identical states given identical inputs. Test CPython vs Pyodide hash equivalence before any P2P work. Use `sort_keys=True` in JSON, seed all RNG.

2. **Input buffer pruning during rollback** -- Never prune frames >= pending rollback frame. Keep 60+ frames of history. Prune AFTER rollback completion, not before.

3. **RNG state not in snapshots** -- Already implemented but verify completeness. Must capture both NumPy and Python random state. Critical for games with AI/bot players.

4. **DataChannel reliability mode mismatch** -- Use unreliable/unordered for game inputs (UDP-like). Use reliable channel or SocketIO for control messages (episode sync, connection management).

5. **TURN latency hidden in metrics** -- Detect connection type via RTCPeerConnection.getStats(). Record in session data for research validity. Adjust input delay when TURN detected.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: WebRTC Foundation
**Rationale:** Creates the P2P connection infrastructure that all subsequent work depends on. No changes to GGPO logic yet.
**Delivers:** Working P2P DataChannel between two browser clients
**Addresses:** WebRTC signaling, ICE negotiation, connection establishment
**Avoids:** Pitfall #4 by configuring DataChannel correctly from the start
**New files:** `webrtc_manager.js`, signaling handlers in `pyodide_game_coordinator.py`

### Phase 2: P2P Transport Layer
**Rationale:** Builds the message protocol on top of Phase 1 connection. Keeps existing GGPO untouched until transport is proven.
**Delivers:** Bidirectional game input exchange over DataChannel
**Addresses:** Message serialization (msgpack), keepalive/ping, connection health monitoring
**Avoids:** Pitfall #9 by implementing redundant input sending (each message includes last N inputs)
**New files:** `p2p_transport.js`

### Phase 3: GGPO P2P Integration
**Rationale:** Replaces SocketIO relay path with P2P transport. Most impactful change -- requires careful testing.
**Delivers:** Full game playable over P2P with rollback netcode
**Addresses:** Input relay replacement, fallback to SocketIO when P2P fails
**Avoids:** Pitfall #2 by validating rollback still works correctly with new transport
**Modifies:** `pyodide_multiplayer_game.js` to use P2P instead of server relay

### Phase 4: TURN and Resilience
**Rationale:** Handles the ~20% of connections that fail direct P2P. Production-readiness for diverse networks.
**Delivers:** Reliable connections across NAT configurations, graceful degradation
**Addresses:** TURN credential configuration, connection quality metrics, automatic fallback
**Avoids:** Pitfall #11 by detecting and logging TURN usage, adjusting input delay
**Config:** TURN server credentials, ICE timeout settings

### Phase 5: Validation and Polish
**Rationale:** Ensures research data validity and improves developer experience.
**Delivers:** Determinism test suite, connection type logging, performance monitoring
**Addresses:** Research-specific concerns (silent desync detection, rollback event logging)
**Avoids:** Pitfalls #17-19 by recording all sync events and connection metadata

### Phase Ordering Rationale

- **Foundation first:** WebRTC setup is prerequisite for all P2P features; isolated testing possible
- **Transport before integration:** Prove the message protocol works before touching complex GGPO code
- **Integration is the critical path:** Phase 3 is highest risk; earlier phases de-risk it
- **TURN after core works:** Optimization/resilience after basic functionality proven
- **Validation last:** Can only validate after system is functional

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1:** May need research on WebRTC browser quirks (Safari iOS has known issues)
- **Phase 4:** Verify TURN provider pricing and evaluate alternatives to Metered.ca

Phases with standard patterns (skip research-phase):
- **Phase 2:** Message serialization is straightforward, msgpack already in codebase
- **Phase 3:** GGPO integration follows documented patterns; existing code is well-structured
- **Phase 5:** Testing patterns are standard; main work is defining test cases

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | WebRTC is standard browser API; verified via MDN documentation |
| Features | HIGH | Based on direct codebase analysis of 2600+ lines of existing GGPO implementation |
| Architecture | MEDIUM | Target architecture is sound; integration complexity may reveal unknowns |
| Pitfalls | HIGH | Critical pitfalls identified from codebase patterns and domain expertise |

**Overall confidence:** MEDIUM-HIGH

The existing GGPO implementation is mature and well-tested. The primary uncertainty is WebRTC integration complexity and browser-specific edge cases.

### Gaps to Address

- **TURN provider selection:** Verify Metered.ca current pricing; evaluate Twilio as alternative
- **Mobile browser WebRTC:** Safari iOS has WebRTC quirks; test needed if mobile support matters
- **N>2 players:** Current design assumes 2-player; mesh vs relay topology decision needed for N>2
- **Pyodide rollback performance:** Need empirical testing of rapid `set_state` calls under rollback load

## Sources

### Primary (HIGH confidence)
- MDN WebRTC Data Channels documentation
- MDN RTCDataChannel API reference
- Direct codebase analysis: `pyodide_multiplayer_game.js` (2600+ lines)
- Direct codebase analysis: `pyodide_game_coordinator.py`, `server_game_runner.py`

### Secondary (MEDIUM confidence)
- GGPO algorithm specification (well-documented fighting game netcode pattern)
- WebRTC browser compatibility tables (Can I Use)
- Existing project documentation: `multiplayer-sync-optimization.md`, `server-authoritative-architecture.md`

### Tertiary (LOW confidence)
- TURN provider pricing (from training knowledge, verify current rates)
- Mobile browser WebRTC behavior (needs testing)

---
*Research completed: 2026-01-16*
*Ready for roadmap: yes*
