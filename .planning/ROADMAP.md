# Roadmap

**Project:** Interactive Gym P2P Multiplayer
**Created:** 2026-01-16
**Phases:** 5

## Overview

This roadmap transforms the existing pseudo-P2P multiplayer system into true peer-to-peer with WebRTC DataChannels. The existing GGPO rollback netcode (2600+ lines) remains largely intact; the primary work is adding a P2P transport layer and integrating it with the existing input synchronization logic. The phases follow a foundation-first approach: establish WebRTC connections, build the message protocol, integrate with GGPO, add TURN fallback for NAT traversal, then validate and clean up legacy code.

## Phases

### Phase 1: WebRTC Foundation

**Goal:** Two browser clients can establish a direct WebRTC DataChannel connection via server-mediated signaling.
**Depends on:** Nothing (first phase)
**Requirements:** WEBRTC-01, WEBRTC-02

**Success Criteria:**
1. User A and User B can establish a WebRTC peer connection after server-mediated SDP exchange
2. A DataChannel opens between peers with unreliable/unordered configuration (ordered: false, maxRetransmits: 0)
3. Both peers can send and receive test messages over the DataChannel
4. ICE candidate exchange completes via SocketIO signaling

**Plans:** (created by /gsd:plan-phase)

---

### Phase 2: P2P Transport Layer

**Goal:** Game inputs flow directly between peers over the DataChannel with proper serialization and loss handling.
**Depends on:** Phase 1
**Requirements:** GGPO-02, GGPO-03

**Success Criteria:**
1. Input messages are serialized and sent over DataChannel with frame number and player ID
2. Each input packet includes the last N (3-5) inputs for redundancy against packet loss
3. Peers receive and correctly deserialize input messages from their counterpart
4. Keepalive/ping messages maintain connection awareness and measure RTT
5. Connection health is monitored (packet loss rate, latency)

**Plans:** (created by /gsd:plan-phase)

---

### Phase 3: GGPO P2P Integration

**Goal:** The existing GGPO rollback system uses P2P transport instead of server relay for input exchange.
**Depends on:** Phase 2
**Requirements:** GGPO-01, NPLAY-01

**Success Criteria:**
1. Two players can complete a full game session with inputs exchanged exclusively via P2P DataChannel
2. Neither peer acts as "host" -- both run symmetric simulations with identical input processing
3. Rollback and replay work correctly when remote inputs arrive late
4. State hash verification detects desyncs (if any occur)
5. SocketIO fallback activates if P2P connection fails during gameplay

**Plans:** (created by /gsd:plan-phase)

---

### Phase 4: TURN and Resilience

**Goal:** Connections succeed even when direct P2P fails due to NAT configurations, with proper detection and logging.
**Depends on:** Phase 3
**Requirements:** WEBRTC-03, WEBRTC-04

**Success Criteria:**
1. TURN server credentials are configured and used when ICE direct connection fails
2. Connection type (direct vs relay) is detected via RTCPeerConnection.getStats()
3. Connection type is logged in session data for research analytics
4. Gameplay works correctly over TURN relay with acceptable latency
5. Connection quality degradation triggers appropriate warnings/fallbacks

**Plans:** (created by /gsd:plan-phase)

---

### Phase 5: Validation and Cleanup

**Goal:** Legacy host-based sync code is removed and the system is validated for research use.
**Depends on:** Phase 4
**Requirements:** CLEAN-01

**Success Criteria:**
1. Legacy "host client" election code is removed from P2P mode
2. Legacy server-relay input sync path is disabled when P2P is active
3. Research data collection captures connection type, rollback events, and sync status
4. Multiple game sessions can complete without silent desyncs
5. Documentation updated to reflect P2P architecture

**Plans:** (created by /gsd:plan-phase)

---

## Progress

| Phase | Status | Completed |
|-------|--------|-----------|
| 1 - WebRTC Foundation | Not started | - |
| 2 - P2P Transport Layer | Not started | - |
| 3 - GGPO P2P Integration | Not started | - |
| 4 - TURN and Resilience | Not started | - |
| 5 - Validation and Cleanup | Not started | - |

---

## Requirement Coverage

| Requirement | Phase | Description |
|-------------|-------|-------------|
| WEBRTC-01 | Phase 1 | WebRTC DataChannel connections |
| WEBRTC-02 | Phase 1 | SocketIO signaling for SDP/ICE |
| WEBRTC-03 | Phase 4 | TURN server fallback |
| WEBRTC-04 | Phase 4 | Connection type detection |
| GGPO-01 | Phase 3 | Symmetric peer architecture |
| GGPO-02 | Phase 2 | P2P input exchange over DataChannel |
| GGPO-03 | Phase 2 | Redundant input sending |
| NPLAY-01 | Phase 3 | 2-player P2P support |
| CLEAN-01 | Phase 5 | Remove legacy host-based sync |

**Coverage:** 9/9 requirements mapped

---

*Roadmap for milestone: P2P Multiplayer v1*
