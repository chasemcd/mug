# Interactive Gym — P2P Multiplayer

## What This Is

A framework for running browser-based reinforcement learning experiments with human participants. This milestone focuses on implementing true peer-to-peer multiplayer with GGPO-style rollback netcode, replacing the current pseudo-P2P "host client" architecture to achieve fighting-game-smooth responsiveness for research experiments.

## Core Value

Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## Requirements

### Validated

*Existing capabilities from current codebase:*

- ✓ Scene-based experiment flow (StartScene → GymScene → EndScene) — existing
- ✓ Single-player Pyodide game execution in browser — existing
- ✓ Server-side experiment orchestration via Flask/SocketIO — existing
- ✓ Phaser.js game rendering — existing
- ✓ Data collection and CSV export — existing
- ✓ Lobby/waitroom system for player matching — existing
- ✓ Session persistence and reconnection support — existing
- ✓ Deterministic Gymnasium environments — existing

### Active

- [ ] WebRTC DataChannel P2P connections between clients
- [ ] TURN server fallback when direct P2P fails
- [ ] GGPO-style input delay and rollback in Pyodide
- [ ] Deterministic replay from confirmed frame on misprediction
- [ ] Symmetric peer architecture (no "host" client)
- [ ] N-player support with hybrid topology (mesh for small N, relay for large N)
- [ ] Clean separation between P2P and server-authoritative multiplayer modes
- [ ] Remove legacy host-based sync code

### Out of Scope

- Ping-based matchmaking — deferred to future milestone
- Server-authoritative mode removal — keeping as parallel option
- Mobile/native clients — browser-only for now
- Spectator mode — not needed for research use case

## Context

**Current state:** The codebase has multiplayer support via `PyodideGameCoordinator` and `ServerGameRunner`, but uses a pseudo-P2P model where one client is elected "host" and their state is synced to others. This creates asymmetric latency — the host feels responsive while other players experience delay.

**Target state:** True P2P where every client runs their own simulation, exchanges inputs directly via WebRTC, and uses GGPO rollback when predictions are wrong. Both players feel local responsiveness.

**Technical environment:**
- Pyodide runs Python/Gymnasium in browser via WebAssembly
- Environments are fully deterministic (same seed + inputs = identical state)
- WebRTC DataChannels provide near-UDP performance in browsers
- Existing SocketIO infrastructure handles signaling and fallback

**Key files to modify:**
- `interactive_gym/server/pyodide_game_coordinator.py` — add WebRTC signaling
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` — implement GGPO client
- `interactive_gym/scenes/gym_scene.py` — add P2P mode configuration

## Constraints

- **Tech stack**: Must work with existing Flask/SocketIO/Pyodide stack — no major framework changes
- **Browser compatibility**: WebRTC DataChannels must work in modern Chrome/Firefox/Safari
- **Determinism**: Environments must remain fully deterministic for replay to work
- **Research validity**: Data collection must capture actual player inputs and game states accurately

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| WebRTC with TURN fallback | Near-UDP latency when NAT allows, guaranteed connectivity via relay | — Pending |
| Deterministic replay over state snapshots | Classic GGPO approach, environments already deterministic | — Pending |
| Hybrid topology for N>2 players | Mesh is optimal for small N, relay scales better | — Pending |
| Keep server-authoritative as parallel mode | Research flexibility, different use cases | — Pending |

---
*Last updated: 2026-01-16 after initialization*
