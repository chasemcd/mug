# Requirements — P2P Multiplayer v1

**Generated:** 2026-01-16
**Milestone:** P2P Multiplayer with GGPO Rollback

## Core Value

Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

---

## v1 Requirements

### WebRTC Transport Layer

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| WEBRTC-01 | WebRTC DataChannel connections | Clients establish DataChannel with `{ ordered: false, maxRetransmits: 0 }` for UDP-like behavior |
| WEBRTC-02 | SocketIO signaling for SDP/ICE | Server relays SDP offers/answers and ICE candidates; clients complete WebRTC handshake |
| WEBRTC-03 | TURN server fallback | When direct P2P fails (symmetric NAT), connection established via TURN relay within 5 seconds |
| WEBRTC-04 | Connection type detection | Log whether connection is direct P2P or TURN-relayed for research analytics |

### GGPO Enhancements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| GGPO-01 | Symmetric peer architecture | No "host" client; both peers run identical simulation, neither has authority over the other |
| GGPO-02 | P2P input exchange over DataChannel | Inputs sent directly between peers (not via server) with frame number and checksum |
| GGPO-03 | Redundant input sending | Each packet includes last N inputs to handle packet loss without retransmission |

### Player Support

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| NPLAY-01 | 2-player P2P support | Two human players connected via single WebRTC DataChannel with GGPO sync |

### Code Cleanup

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| CLEAN-01 | Remove legacy host-based sync | Remove "host client" election and state sync code; P2P mode uses symmetric peers only |

---

## Deferred to Future Milestones

| ID | Feature | Reason |
|----|---------|--------|
| GGPO-04 | Adaptive input delay | Complexity; fixed input delay sufficient for research |
| NPLAY-02 | N-player mesh topology | 2-player covers primary research use case |
| NPLAY-03 | Hybrid relay for large N | Requires NPLAY-02 first |
| MATCH-01 | Ping-based matchmaking | Nice-to-have, not critical for controlled experiments |

---

## Success Criteria

- [ ] Two players can connect via WebRTC DataChannel (direct or TURN)
- [ ] Both players experience identical, local-feeling input responsiveness
- [ ] Rollback/replay occurs correctly on input misprediction
- [ ] Game state remains synchronized (verified by hash comparison)
- [ ] Legacy host-based sync code removed from P2P mode
- [ ] Research experiments can run with valid data collection

---

## Technical Constraints

1. **Determinism**: Environments must remain fully deterministic (same seed + inputs = identical state)
2. **Browser compatibility**: WebRTC DataChannels must work in modern Chrome/Firefox/Safari
3. **Existing stack**: Must integrate with Flask/SocketIO/Pyodide — no major framework changes
4. **Parallel modes**: Server-authoritative mode preserved as separate option

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| WEBRTC-01 | Phase 1 | Complete |
| WEBRTC-02 | Phase 1 | Complete |
| WEBRTC-03 | Phase 4 | Pending |
| WEBRTC-04 | Phase 4 | Pending |
| GGPO-01 | Phase 3 | Pending |
| GGPO-02 | Phase 2 | Complete |
| GGPO-03 | Phase 2 | Complete |
| NPLAY-01 | Phase 3 | Pending |
| CLEAN-01 | Phase 5 | Pending |

---

*Requirements derived from user selections and research findings*
