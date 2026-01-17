# Feature Landscape: GGPO-Style Rollback Netcode

**Domain:** P2P multiplayer with GGPO rollback netcode for browser-based RL experiments
**Researched:** 2026-01-16
**Confidence:** HIGH (based on GGPO specifications, existing implementation analysis, and fighting game netcode patterns)

## Context

GGPO (Good Game Peace Out) is a rollback netcode library originally designed for fighting games. The core philosophy: **predict inputs locally, execute immediately, then rollback and replay if predictions are wrong**. This creates local-feeling responsiveness regardless of network latency.

For research experiments studying human behavior in multiplayer games, GGPO provides:
1. Equal experience for all players (no "host advantage")
2. Valid behavioral data (no latency-induced artifacts)
3. Smooth gameplay that feels responsive

---

## Table Stakes

Features users expect. Missing = sync breaks or experience is unacceptable.

| Feature | Why Expected | Complexity | Dependencies | Notes |
|---------|--------------|------------|--------------|-------|
| **Deterministic Simulation** | GGPO requires identical state on all clients given same inputs | Medium | Environment implementation | Existing: Pyodide runs Python in browser, environments seeded with shared RNG |
| **Input Delay (Configurable)** | Trades latency for reduced rollbacks; INPUT_DELAY frames gives network time to deliver inputs | Low | None | Existing: `INPUT_DELAY` config (0-5 frames typical) |
| **Frame-Indexed Input Buffer** | Store inputs by target frame number, not arrival order | Low | None | Existing: `inputBuffer: Map<frameNumber, Map<playerId, action>>` |
| **Input Prediction** | When remote input hasn't arrived, use predicted action (typically last action) | Low | Input buffer | Existing: `getPredictedAction()` with `action_population_method` |
| **Late Input Detection** | Know when confirmed input differs from prediction used | Low | Input buffer, prediction tracking | Existing: Compare `predictedFrames` with arriving inputs |
| **State Snapshots** | Save state periodically for rollback restoration | Medium | `get_state()`/`set_state()` on env | Existing: `stateSnapshots: Map<frameNumber, stateJson>` every 5 frames |
| **Rollback Mechanism** | Load snapshot, replay frames with corrected inputs | High | Snapshots, input buffer, determinism | Existing: `performRollback()` - load snapshot, replay frames |
| **State Hash Verification** | Detect when clients have diverged (hash mismatch = desync) | Medium | `get_state()` with JSON-serializable output | Existing: MD5 hash of `env.get_state()` |
| **Server-Authoritative Fallback** | When P2P sync fails, server provides ground truth | High | Server-side env runner | Existing: `ServerGameRunner` with periodic `server_authoritative_state` broadcasts |
| **Sync Epoch** | Prevent stale actions from previous episodes affecting new ones | Low | Episode lifecycle | Existing: `syncEpoch` incremented on episode start |
| **Episode Synchronization** | All clients start each episode from identical state | Medium | Server coordination | Existing: `server_episode_start` event with authoritative initial state |

---

## Differentiators

Features that set the product apart. Not expected, but add significant value for research use case.

| Feature | Value Proposition | Complexity | Dependencies | Notes |
|---------|-------------------|------------|--------------|-------|
| **True P2P via WebRTC** | Near-UDP latency, bypasses server relay (currently via SocketIO) | High | WebRTC DataChannels, TURN fallback | Pending: Current uses server relay |
| **Adaptive Input Delay** | Dynamically adjust INPUT_DELAY based on measured RTT | Medium | RTT measurement | Not implemented: Would reduce rollbacks without fixed overhead |
| **Frame Interpolation** | Smooth rendering between simulation steps | Medium | Render/simulation separation | Partial: Fixed timestep exists, interpolation partial |
| **Rollback Visualization** | Show when rollbacks occur (research debugging) | Low | Rollback events | Not implemented: Would help researchers understand sync quality |
| **Per-Session Latency Metrics** | Log RTT, rollback frequency, prediction accuracy per game | Low | Existing diagnostics | Partial: `diagnostics` object tracks some metrics |
| **Input Delay Recommendation** | Suggest optimal INPUT_DELAY based on measured network conditions | Medium | RTT measurement | Not implemented |
| **Spectator Mode** | Watch games without affecting sync | Medium | Read-only client mode | Out of scope per PROJECT.md |
| **Replay Recording** | Full deterministic replay from inputs only | Medium | Complete input history | Partial: `actionSequence` logged but not exportable for replay |
| **N-Player Mesh Topology** | Direct P2P between all N players (optimal for small N) | High | WebRTC mesh | Pending: Currently server-relayed |
| **Hybrid Topology (N>4)** | Switch from mesh to relay for large player counts | High | Player count detection | Pending: Designed but not implemented |
| **Time Synchronization** | NTP-style clock sync between clients for frame alignment | Medium | Server time broadcasts | Partial: Server timestamp in state broadcasts |
| **Configurable Prediction Strategy** | Choose prediction algorithm (last action, neutral, ML-based) | Medium | Plugin system | Partial: `action_population_method` supports 'previous_submitted_action' or 'default' |
| **Network Condition Simulation** | Add artificial latency/jitter for testing | Low | Developer tooling | Not implemented: Would help validate GGPO behavior |
| **Automatic Desync Recovery** | Detect and auto-correct drift without user intervention | Medium | State hash comparison | Existing: `reconcileWithServer()` handles this |

---

## Anti-Features

Features to explicitly NOT build. Common mistakes in this domain.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Lockstep Networking** | Blocks on slowest player, creates stuttering; antithetical to GGPO philosophy | Use rollback with prediction |
| **Unlimited Rollback Depth** | Memory explosion; replaying 100+ frames causes visual stutter | Cap rollback at ~15 frames (0.5s at 30fps), force resync beyond |
| **State Sync Every Frame** | Massive bandwidth; hash comparison is cheaper | Hash-based verification, full state only on mismatch |
| **Floating Point Determinism** | Browser JS float behavior varies; causes subtle desyncs | Use integer math or fixed-point where possible; Python/Pyodide is safer |
| **Complex State Serialization** | Pickle/msgpack with custom objects causes deserialization failures cross-platform | JSON-serializable primitives only in `get_state()`/`set_state()` |
| **Host Advantage** | One player feels responsive, others feel lag; invalid research data | Symmetric architecture: all clients run same simulation |
| **Blocking Rollback** | Synchronous rollback freezes game during replay | Keep rollback fast (< 16ms); cap depth; async if needed |
| **Action Buffering Without Frame Tags** | Lose temporal information; can't match input to frame | Always tag actions with target frame number |
| **Per-Action Round Trip** | Wait for server confirmation before executing; adds full RTT to every input | Execute immediately with prediction; correct via rollback |
| **Render-Coupled Simulation** | Variable frame rate causes timing drift between clients | Fixed timestep simulation decoupled from render rate |
| **Global State Mutations** | Hidden state (globals, singletons) not captured in snapshots; causes unreproducible desyncs | All state in `env.get_state()`; explicit, captured, restorable |
| **Aggressive Input Buffer Pruning** | Deleting inputs too early removes data needed for rollback | Keep inputs for at least rollback window + safety margin |
| **Over-Engineering for Edge Cases** | Complex reconnection, migration logic for rare scenarios | Keep it simple: disconnect = forfeit for now (research context) |

---

## Feature Dependencies

```
                    ┌─────────────────────┐
                    │ Deterministic       │
                    │ Simulation          │
                    └──────────┬──────────┘
                               │
                               ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ Input Delay     │──►│ Frame-Indexed   │◄──│ Input           │
│ (Configurable)  │   │ Input Buffer    │   │ Prediction      │
└─────────────────┘   └────────┬────────┘   └─────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Late Input          │
                    │ Detection           │
                    └──────────┬──────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ State           │   │ Rollback        │   │ State Hash      │
│ Snapshots       │──►│ Mechanism       │◄──│ Verification    │
└─────────────────┘   └────────┬────────┘   └─────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │ Server-Authoritative│
                    │ Fallback            │
                    └─────────────────────┘
```

**Critical Path (must build in order):**
1. Deterministic Simulation (environment property)
2. Frame-Indexed Input Buffer (data structure)
3. Input Delay + Prediction (local responsiveness)
4. Late Input Detection (trigger for rollback)
5. State Snapshots (rollback prerequisite)
6. Rollback Mechanism (core GGPO feature)
7. State Hash Verification (desync detection)
8. Server-Authoritative Fallback (safety net)

---

## MVP Recommendation

For MVP, prioritize these table stakes (most already exist):

### Must Have (Table Stakes)
1. **Deterministic Simulation** - Already exists via Pyodide + seeded RNG
2. **Input Delay** - Already exists (`INPUT_DELAY` config)
3. **Frame-Indexed Input Buffer** - Already exists
4. **Input Prediction** - Already exists
5. **Late Input Detection** - Already exists
6. **State Snapshots** - Already exists
7. **Rollback Mechanism** - Already exists
8. **State Hash Verification** - Already exists
9. **Server-Authoritative Fallback** - Already exists
10. **Sync Epoch** - Already exists
11. **Episode Synchronization** - Already exists

### Implement for P2P Milestone
1. **WebRTC DataChannels** - Replace SocketIO relay with direct P2P
2. **TURN Server Fallback** - When direct P2P fails (NAT issues)
3. **Symmetric Peer Architecture** - Remove "host" concept from P2P mode

### Defer to Post-MVP
- **Adaptive Input Delay** - Optimization, not required for correctness
- **Frame Interpolation** - Visual polish
- **Rollback Visualization** - Research debugging tool
- **N-Player Mesh Topology** - Start with 2-player, extend later
- **Spectator Mode** - Out of scope per PROJECT.md

---

## Research-Specific Considerations

Features important for valid research data collection:

| Consideration | Why Important | Implementation |
|---------------|---------------|----------------|
| **Input-to-Frame Mapping** | Know exactly what action executed on what frame | `actionSequence` array with frame + actions |
| **Rollback Logging** | Know when rollbacks occurred, how many frames | `rollbackCount`, `maxRollbackFrames` metrics |
| **Prediction Tracking** | Know which frames used prediction vs confirmed input | `predictedFrames` set |
| **Sync Quality Metrics** | Assess whether participants had equivalent experience | `diagnostics` object: frame drift, sync count |
| **Per-Player Latency** | Detect if one player had network disadvantage | Server timestamp vs client timestamp delta |
| **Deterministic Replay** | Reproduce exact game from inputs for analysis | Requires complete input log + initial seed |

---

## Complexity Estimates

| Feature Category | Complexity | Rationale |
|------------------|------------|-----------|
| Input Handling (delay, buffer, prediction) | **Low** | Already implemented; tuning only |
| Rollback Mechanism | **High** | Implemented but needs testing; edge cases in replay |
| State Synchronization | **Medium** | Hash verification works; full sync is heavy |
| WebRTC P2P | **High** | New transport layer; NAT traversal; TURN setup |
| Server-Authoritative | **Medium** | Implemented; needs optimization for scale |
| N-Player Support | **High** | Topology decisions; exponential connection growth |

---

## Sources

- **Codebase Analysis:** `pyodide_multiplayer_game.js` (2600+ lines of GGPO implementation)
- **Codebase Analysis:** `server_game_runner.py` (real-time authoritative server)
- **Codebase Documentation:** `multiplayer-sync-optimization.md`, `server-authoritative-architecture.md`
- **PROJECT.md:** Requirements and scope definition
- **ARCHITECTURE.md:** Current system structure
- **GGPO Specification:** Training knowledge (rollback netcode patterns from fighting games)

**Confidence Notes:**
- HIGH confidence on table stakes: These are well-established GGPO patterns
- HIGH confidence on anti-features: These are documented failure modes in netcode implementations
- MEDIUM confidence on differentiators: Specific implementation effort varies based on WebRTC complexity
- HIGH confidence on existing implementation: Direct code analysis of 2000+ lines of GGPO code
