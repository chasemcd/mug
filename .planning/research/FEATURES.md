# Feature Landscape: P2P Sync Validation & Desync Detection

**Domain:** Sync validation for GGPO-style rollback netcode in research experiments
**Researched:** 2026-01-20
**Milestone:** v1.1 (subsequent to P2P multiplayer foundation)
**Confidence:** HIGH (based on GGPO SDK documentation, fighting game implementations, RTS lockstep patterns, and community tooling)

## Context

Sync validation ensures both peers in a P2P rollback system maintain identical simulations. In research contexts, this is critical: desync means invalid experimental data. Production netcode systems have evolved sophisticated desync detection and debugging capabilities that can inform this implementation.

**Current State (v1.0):**
- MD5 hash of `env.get_state()` for state comparison
- Server-authoritative fallback for recovery
- Basic `diagnostics` object tracking rollback metrics

**Goal (v1.1):**
- Detect desync immediately when it occurs
- Provide actionable debugging information for researchers
- Enable determinism verification during development

---

## Table Stakes

Features that are essential for any production-quality desync detection system. Missing = desyncs go undetected or are undiagnosable.

| Feature | Why Essential | Complexity | Real-World Example | Notes |
|---------|---------------|------------|-------------------|-------|
| **Per-Frame State Checksum** | Detect exact frame where divergence began | Low | GGPO `save_game_state` checksum param; SupCom once-per-second hash | Upgrade from periodic to every frame (or every N frames) |
| **Checksum Exchange Protocol** | Compare checksums between peers to detect mismatch | Low | Spring RTS: each player sends checksum to server; majority determines "correct" | Need efficient wire format for checksums |
| **Mismatch Frame Identification** | Know which frame first diverged (not just "desync occurred") | Medium | GeneralsGameCode: CRC per frame with player/frame logging | Critical for debugging - "desync on frame 83, detected frame 93" |
| **Sync Test Mode (Single-Player)** | Run simulation twice per frame, verify determinism without network | Medium | GGPO `ggpo_start_synctest`: execute frame, rollback, re-execute, compare | Development-time determinism validation |
| **State Dump on Mismatch** | Capture full state when checksum differs for post-mortem analysis | Medium | Godot Rollback: log inspector captures state at mismatch | Essential for debugging - "what was different?" |
| **Deterministic RNG Seeding** | Ensure random operations produce identical results on both peers | Low | All lockstep engines: shared seed communicated at session start | Existing in v1.0 but needs verification tooling |

---

## Differentiators

Advanced capabilities that distinguish production-quality debugging tools. Not required for basic detection but dramatically improve debugging efficiency.

| Feature | Value Proposition | Complexity | Real-World Example | Notes |
|---------|-------------------|------------|-------------------|-------|
| **Hierarchical/Incremental Checksums** | Narrow down which subsystem diverged (positions? health? inventory?) | Medium | GeneralsGameCode: separate CRCs for unit positions, health, locomotive forces | "Entity positions match, but entity health diverged" |
| **Frame Diff Logging** | Side-by-side comparison of states at divergent frame | High | Godot Rollback Log Inspector: replay client shows state visually | Log format: `{frame: N, peer1: {...}, peer2: {...}, diff: [...]}` |
| **Deterministic Replay Validation** | Re-run recorded inputs offline, verify same outcome | Medium | UFE Playback Tool: record what player saw vs post-rollback truth | Enables CI-based determinism regression tests |
| **Binary Search Desync Localization** | Automated narrowing of which code path caused divergence | High | Demigod desync debugging: "binary search of printf-ing the hash" | Expensive but invaluable for rare desyncs |
| **Per-Entity State Tracking** | Track each game entity's state separately for granular comparison | Medium | Bevy Turborand: per-entity RNG components for determinism | Helps identify "which entity went wrong" |
| **Live Sync Debug Overlay** | Runtime visualization showing sync status, checksum matches, rollback frequency | Low | Godot Rollback: F11 overlay showing sync metrics | Developer tool for manual testing |
| **Post-Rollback Frame Recording** | Record both predicted frame AND corrected frame after rollback | Medium | UFE: "Record Post-Rollback Frames" toggle | Helps understand what changed during rollback |
| **Automated Desync Reproduction** | Given inputs + seed, reproduce the exact desync scenario | Medium | Logic frame dump: "re-run game inputs several times, assert identical" | Critical for fixing intermittent desyncs |
| **Cross-Platform Determinism Validation** | Verify same inputs produce same state on different browser/OS | High | Box2D: 3 levels of determinism (algorithmic, multithreaded, cross-platform) | Browser differences can cause subtle desyncs |

---

## Anti-Features

Things that would hurt performance, add complexity without value, or are inappropriate for this use case.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Full State Sync Every Frame** | Massive bandwidth; defeats purpose of input-based sync | Checksum comparison only; full state only on mismatch |
| **Cryptographic Hash Functions for Checksums** | Overkill security; slow; MD5/SHA unnecessary for integrity checking | Simple XOR hash, CRC32, or FNV-1a (fast, sufficient collision resistance) |
| **Blocking Validation** | Stalling game loop for checksum comparison kills responsiveness | Async comparison; validation can trail simulation by frames |
| **Automated Resync on Every Mismatch** | Hides bugs; research needs to KNOW when desyncs occurred | Log and alert; manual recovery decision or configurable policy |
| **Unlimited State History** | Memory explosion storing every frame's state | Rolling window (e.g., last 60 frames); configurable retention |
| **Complex Serialization Formats** | Protobuf/MessagePack add complexity; JSON variants across browsers | JSON with deterministic key ordering; or raw binary with spec |
| **Attempting to "Merge" Divergent States** | No meaningful merge; both states are wrong from divergence point | Authoritative resync from server or match restart |
| **Over-Detailed Logging in Production** | Performance overhead; storage costs | Verbose logging only in debug/development mode; metrics only in production |
| **Synchronous Network Validation** | Waiting for peer checksum before advancing frame | Fire-and-forget checksum exchange; detect mismatch async |

---

## Feature Dependencies

```
                    ┌─────────────────────────┐
                    │ Deterministic RNG       │
                    │ Seeding (existing)      │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │ Per-Frame State         │
                    │ Checksum                │
                    └───────────┬─────────────┘
                                │
            ┌───────────────────┼───────────────────┐
            ▼                   ▼                   ▼
┌───────────────────┐ ┌─────────────────┐ ┌───────────────────┐
│ Sync Test Mode    │ │ Checksum        │ │ State Dump on     │
│ (Single-Player)   │ │ Exchange Proto  │ │ Mismatch          │
└───────────────────┘ └────────┬────────┘ └─────────┬─────────┘
                               │                    │
                               ▼                    │
                    ┌─────────────────────┐         │
                    │ Mismatch Frame      │◄────────┘
                    │ Identification      │
                    └───────────┬─────────┘
                                │
            ┌───────────────────┼───────────────────┐
            ▼                   ▼                   ▼
┌───────────────────┐ ┌─────────────────┐ ┌───────────────────┐
│ Hierarchical      │ │ Frame Diff      │ │ Live Sync Debug   │
│ Checksums         │ │ Logging         │ │ Overlay           │
└───────────────────┘ └─────────────────┘ └───────────────────┘
            │                   │
            └─────────┬─────────┘
                      ▼
            ┌─────────────────────────┐
            │ Deterministic Replay    │
            │ Validation              │
            └─────────────────────────┘
```

**Critical Path (build in order):**
1. Per-Frame State Checksum (foundation)
2. Checksum Exchange Protocol (peer communication)
3. Mismatch Frame Identification (know when)
4. State Dump on Mismatch (know what)
5. Sync Test Mode (development validation)

**Parallel Development (can build independently):**
- Live Sync Debug Overlay (visual tooling)
- Hierarchical Checksums (enhanced diagnostics)
- Frame Diff Logging (debugging enhancement)

---

## Implementation Patterns from Production Systems

### GGPO Sync Test Pattern

From the [GGPO Developer Guide](https://github.com/pond3r/ggpo/blob/master/doc/DeveloperGuide.md):

```
Sync Test Session Flow:
1. Execute frame normally
2. Save state with checksum
3. Force 1-frame rollback
4. Re-execute same frame
5. Save state with checksum
6. Compare checksums
7. If mismatch: desync bug exists
```

**Key insight:** Run this in development continuously. Catch determinism bugs immediately after introduction.

### RTS Checksum Pattern

From [Synchronous RTS Engines and a Tale of Desyncs](https://www.forrestthewoods.com/blog/synchronous_rts_engines_and_a_tale_of_desyncs/):

```
Supreme Commander approach:
- Hash entire game state once per second
- If any client disagrees: game over (disconnect)
- No recovery mechanism
- Debugging: "binary search of printf-ing the current memory hash"
```

**Key insight:** Simple detection is better than complex recovery. In research, we want to KNOW about desyncs, not hide them.

### GeneralsGameCode CRC Pattern

From [GeneralsGameCode Issue #289](https://github.com/TheSuperHackers/GeneralsGameCode/issues/289):

```
CRC logging strategy:
- Log CRC evolution every logic frame
- Collect logs from 2+ clients that mismatched
- Compare logs to find divergence frame
- Works for replays too: run twice, compare logs
```

**Key insight:** Aggressive frame-by-frame logging enables post-mortem analysis.

### Godot Rollback Log Inspector

From [Godot Rollback Netcode Addon](https://www.snopekgames.com/project/godot-rollback-netcode-addon/):

```
Features:
- SyncReplay.gd singleton for replay from logs
- Log Inspector in Godot editor
- Replay client connects via TCP for live debugging
- Visual state inspection at mismatch frame
```

**Key insight:** Tooling matters as much as detection. Being able to visually inspect divergent state accelerates debugging.

### Universal Fighting Engine (UFE) Pattern

From [UFE Network Options](http://www.ufe3d.com/doku.php/global:network):

```
Desync Detection Options:
- Float Desync Threshold: compare values within tolerance
- Log Sync Messages: report every successful sync check
- Record Post-Rollback Frames: see what changed during rollback
- Playback Tool: pause both players, enable replay comparison
```

**Key insight:** Configurable verbosity levels. Development needs detail; production needs minimal overhead.

---

## Checksum Algorithm Recommendations

| Algorithm | Speed | Collision Resistance | Use Case |
|-----------|-------|---------------------|----------|
| **XOR-based** | Fastest | Weak | Large state, performance-critical |
| **CRC32** | Fast | Good | Balanced choice for game state |
| **FNV-1a** | Fast | Good | Alternative to CRC32 |
| **xxHash** | Very Fast | Very Good | If available, best overall |
| **MD5** | Slow | Overkill | Current implementation; replace |
| **SHA-256** | Slowest | Massive overkill | Never use for sync validation |

**Recommendation:** Replace MD5 with CRC32 or FNV-1a. Existing MD5 is ~10x slower than needed.

---

## MVP Recommendation for v1.1

### Must Have (Table Stakes)

1. **Per-Frame State Checksum** - Replace periodic MD5 with per-frame CRC32
2. **Checksum Exchange Protocol** - Piggyback on existing input messages
3. **Mismatch Frame Identification** - Log exact frame number of divergence
4. **State Dump on Mismatch** - Capture both peer states when checksum differs
5. **Sync Test Mode** - Single-player determinism validation

### Should Have (Differentiators with High ROI)

1. **Live Sync Debug Overlay** - Low complexity, high visibility during development
2. **Deterministic Replay Validation** - Enable CI regression tests for determinism

### Defer to v1.2+

- **Hierarchical Checksums** - Optimization for complex state
- **Frame Diff Logging** - Nice to have, complex to implement
- **Binary Search Localization** - Rare desync edge case handling
- **Cross-Platform Validation** - Verify need first with actual browser testing

---

## Research-Specific Considerations

| Consideration | Why Important for Research | Implementation |
|---------------|---------------------------|----------------|
| **Desync Logging to Server** | Researchers need to know which sessions had sync issues | Send desync event to server with frame, checksums, session ID |
| **Session Validity Flag** | Mark sessions that experienced desync as potentially invalid data | Automatic flag in session metadata |
| **Desync Frequency Metrics** | Aggregate statistics across experiments | Track desyncs per session, recovery rate, frames to detect |
| **Post-Hoc Replay Validation** | Verify recorded data was deterministic | Replay inputs offline, compare to recorded outcomes |
| **Determinism Test Suite** | Automated verification before experiments run | CI job: same seed + inputs = same final state |

---

## Complexity Estimates

| Feature | Complexity | Rationale |
|---------|------------|-----------|
| Per-Frame Checksum | **Low** | Replace hash function, call more frequently |
| Checksum Exchange | **Low** | Add field to existing messages |
| Mismatch Frame ID | **Low** | Logging enhancement |
| State Dump on Mismatch | **Medium** | Need structured capture, storage strategy |
| Sync Test Mode | **Medium** | New entry point, modified game loop |
| Live Debug Overlay | **Low** | UI component with existing metrics |
| Hierarchical Checksums | **Medium** | Requires state decomposition |
| Replay Validation | **Medium** | Requires complete input capture, offline runner |
| Frame Diff Logging | **High** | Complex state comparison, visualization |
| Binary Search Localization | **High** | Automated instrumentation, iterative execution |

---

## Sources

### HIGH Confidence (Official Documentation / Source Code)

- [GGPO Developer Guide](https://github.com/pond3r/ggpo/blob/master/doc/DeveloperGuide.md) - Sync test mode, checksum in save_game_state callback
- [GGPO GitHub Repository](https://github.com/pond3r/ggpo) - Reference implementation
- [GeneralsGameCode Issue #289](https://github.com/TheSuperHackers/GeneralsGameCode/issues/289) - CRC-based desync detection proposal

### MEDIUM Confidence (Industry Practice / Multiple Sources)

- [Synchronous RTS Engines and a Tale of Desyncs](https://www.forrestthewoods.com/blog/synchronous_rts_engines_and_a_tale_of_desyncs/) - SupCom/Demigod desync debugging
- [Godot Rollback Netcode Addon](https://www.snopekgames.com/project/godot-rollback-netcode-addon/) - Log Inspector tooling
- [UFE Network Options](http://www.ufe3d.com/doku.php/global:network) - Float threshold, playback tool
- [Preparing Your Game for Deterministic Netcode](https://yal.cc/preparing-your-game-for-deterministic-netcode/) - Debugging strategies
- [Game Networking Demystified Part II](https://ruoyusun.com/2019/03/29/game-networking-2.html) - Frame dump tools

### LOW Confidence (Community Wisdom / Single Source)

- [Deterministic Simulation for Lockstep Multiplayer](https://www.daydreamsoft.com/blog/deterministic-simulation-for-lockstep-multiplayer-engines) - General patterns
- [Hacker News Discussion on Lockstep](https://news.ycombinator.com/item?id=8802461) - Checksum strategies

---

## Summary

Production netcode systems consistently implement these patterns for desync detection:

1. **Checksum every frame** (or regularly) - CRC32/XOR, not MD5
2. **Exchange checksums between peers** - Async, non-blocking
3. **Identify exact divergence frame** - Frame number logging
4. **Dump state on mismatch** - For post-mortem analysis
5. **Sync test mode for development** - Catch determinism bugs early

The most valuable insight from this research: **detection is cheap; debugging is expensive**. Invest in tooling that helps pinpoint WHY desyncs occur, not just that they occurred.

For v1.1, focus on table stakes (detection + identification) and one differentiator (sync test mode for development). Advanced debugging tools can come in v1.2 as needed.
