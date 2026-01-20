# Interactive Gym — P2P Multiplayer

## What This Is

A framework for running browser-based reinforcement learning experiments with human participants. The P2P multiplayer system implements true peer-to-peer connections with GGPO-style rollback netcode, enabling fighting-game-smooth responsiveness for research experiments where both players experience local-feeling input response regardless of network latency.

## Core Value

Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## Current State (v1.0)

**Shipped:** 2026-01-19

**Tech stack:**
- Pyodide runs Python/Gymnasium in browser via WebAssembly
- WebRTC DataChannels provide near-UDP performance between peers
- Flask/SocketIO handles signaling and fallback
- 3,913 LOC in pyodide_multiplayer_game.js
- 759 LOC in webrtc_manager.js

**Architecture:**
- Symmetric peers (no "host" concept)
- Binary P2P protocol with redundant input packets
- TURN server fallback for NAT-blocked connections
- GGPO-style input queuing with synchronous rollback

## Requirements

### Validated

*Existing capabilities:*
- ✓ Scene-based experiment flow (StartScene → GymScene → EndScene) — existing
- ✓ Single-player Pyodide game execution in browser — existing
- ✓ Server-side experiment orchestration via Flask/SocketIO — existing
- ✓ Phaser.js game rendering — existing
- ✓ Data collection and CSV export — existing
- ✓ Lobby/waitroom system for player matching — existing
- ✓ Session persistence and reconnection support — existing
- ✓ Deterministic Gymnasium environments — existing

*Shipped in v1.0:*
- ✓ WebRTC DataChannel P2P connections — v1.0
- ✓ SocketIO signaling for SDP/ICE — v1.0
- ✓ TURN server fallback — v1.0
- ✓ Connection type detection for research analytics — v1.0
- ✓ Symmetric peer architecture (no "host") — v1.0
- ✓ P2P input exchange over DataChannel — v1.0
- ✓ Redundant input sending for packet loss — v1.0
- ✓ 2-player P2P support — v1.0
- ✓ Legacy host-based sync code removed — v1.0
- ✓ GGPO-style synchronous input processing — v1.0

### Active

- [ ] Rollback visual smoothing (tween objects after corrections)
- [ ] N-player support with hybrid topology (mesh for small N, relay for large N)
- [ ] Adaptive input delay based on RTT

### Out of Scope

- Ping-based matchmaking — deferred to future milestone
- Server-authoritative mode removal — keeping as parallel option
- Mobile/native clients — browser-only for now
- Spectator mode — not needed for research use case

## Context

**Current codebase:**
- P2P multiplayer fully functional for 2-player games
- Tested with SlimeVolleyball and Overcooked environments
- Research metrics export API captures connection type, rollback events, sync status

**Known issues:**
- Episode start sync can timeout on slow connections (mitigated with retry mechanism)
- Rollback visual corrections cause brief teleporting (smoothing not yet implemented)

## Constraints

- **Tech stack**: Must work with existing Flask/SocketIO/Pyodide stack
- **Browser compatibility**: WebRTC DataChannels must work in modern Chrome/Firefox/Safari
- **Determinism**: Environments must remain fully deterministic for replay to work
- **Research validity**: Data collection must capture actual player inputs and game states accurately

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Native WebRTC API (no wrapper libraries) | Full control, no external dependencies | ✓ Good |
| Deterministic initiator (lower player ID) | Prevents race conditions in role assignment | ✓ Good |
| DataChannel unreliable/unordered | GGPO handles packet loss via prediction and rollback | ✓ Good |
| Binary protocol with redundancy | Compact format, handles up to 2 consecutive packet losses | ✓ Good |
| Symmetric state sync (both peers broadcast) | Mutual verification, no single point of authority | ✓ Good |
| P2P-first with SocketIO fallback | Minimizes server bandwidth when P2P healthy | ✓ Good |
| GGPO-style input queuing | Prevents race conditions during rollback replay | ✓ Good |
| Open Relay Project for TURN | Free 20GB/month tier sufficient for research | ✓ Good |

---
*Last updated: 2026-01-19 after v1.0 milestone*
