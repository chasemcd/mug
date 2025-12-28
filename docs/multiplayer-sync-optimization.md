# Multiplayer Synchronization: Current Architecture & Optimization Plan

## Overview

This document analyzes the current multiplayer Pyodide game synchronization architecture and proposes optimizations to improve the player experience without major architectural changes.

---

## Code Review Findings

### What's Already Implemented Well

1. **Action Queue Approach** (`pyodide_multiplayer_game.js:118-140`)
   - Actions are queued immediately when received
   - No blocking wait for other players
   - Queue size monitoring with threshold-based resync

2. **Immediate Action Relay** (`pyodide_game_coordinator.py:250-258`)
   - Server relays actions immediately to other players
   - No batching or waiting - minimal added latency

3. **Timestamps Already Included** (`pyodide_multiplayer_game.js:451`)
   - Actions already include `timestamp: Date.now()`
   - Server adds its own timestamp on relay

4. **Hash-Based Sync Verification** (`pyodide_multiplayer_game.js:533-541`)
   - Periodic hash comparison (configurable frequency)
   - Only triggers full sync when hashes mismatch

5. **Configurable Sync Frequency** (`pyodide_multiplayer_game.js:469-471`)
   - `state_sync_frequency_frames` parameter
   - Can be adjusted per-game

### Potential Issues Identified

1. **State Hash Computation is Expensive** (`pyodide_multiplayer_game.js:662-679`)
   - Runs Python code in Pyodide for every hash
   - JSON serialization + SHA256 for every verification
   - Could be optimized with incremental hashing

2. **Full State Transfer is Large** (`pyodide_multiplayer_game.js:684-735`)
   - Includes full `env_state`, `cumulative_rewards`, `numpy_rng_state`
   - Runs Python serialization code
   - No compression or delta encoding

3. **Console Logging in Hot Path** (`pyodide_multiplayer_game.js:454, 139`)
   - `console.debug` calls on every action
   - May cause GC pressure in tight loops

4. **Queue Never Drops Actions** (`pyodide_multiplayer_game.js:126`)
   - Comment says "never drop actions to maintain sync"
   - But if client is slow, queue grows unbounded until threshold
   - Could use smarter queue management

5. **Socket.IO Transport Not Explicitly Set**
   - May be using polling fallback
   - Should force WebSocket transport

---

## Current Architecture

### Components

```
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│    Client A     │         │     Server      │         │    Client B     │
│   (Host)        │         │  (Relay Only)   │         │   (Non-Host)    │
│                 │         │                 │         │                 │
│  ┌───────────┐  │         │  ┌───────────┐  │         │  ┌───────────┐  │
│  │  Pyodide  │  │ actions │  │  Pyodide  │  │ actions │  │  Pyodide  │  │
│  │   Env     │──┼────────►│  │Coordinator│──┼────────►│  │   Env     │  │
│  │           │  │         │  │           │  │         │  │           │  │
│  └───────────┘  │         │  └───────────┘  │         │  └───────────┘  │
│        │        │         │                 │         │        │        │
│   Render Loop   │         │                 │         │   Render Loop   │
│        │        │         │                 │         │        │        │
│        ▼        │         │                 │         │        ▼        │
│  ┌───────────┐  │         │                 │         │  ┌───────────┐  │
│  │  Phaser   │  │         │                 │         │  │  Phaser   │  │
│  │  Canvas   │  │         │                 │         │  │  Canvas   │  │
│  └───────────┘  │         │                 │         │  └───────────┘  │
└─────────────────┘         └─────────────────┘         └─────────────────┘
```

### Message Types

| Message | Direction | Purpose |
|---------|-----------|---------|
| `pyodide_player_action` | Client → Server | Send player's action |
| `pyodide_other_player_action` | Server → Clients | Relay action to other players |
| `pyodide_state_hash` | Client → Server | Send state hash for verification |
| `pyodide_request_resync` | Client → Server | Request full state from host |
| `pyodide_request_full_state` | Server → Host | Ask host to provide state |
| `pyodide_send_full_state` | Host → Server | Host sends full state |
| `pyodide_apply_full_state` | Server → Client | Apply host's state |
| `pyodide_hud_update` | Host → Server | Host sends HUD text |
| `pyodide_hud_sync` | Server → Clients | Broadcast HUD to all |

### Current Synchronization Strategy

1. **Action Queue Approach**: Each client maintains queues of other players' actions
2. **Immediate Relay**: Actions are relayed immediately (no waiting for all players)
3. **Periodic State Verification**: Hash comparison every N frames
4. **Full State Resync**: When desync detected or queue grows too large

### Current Configuration Options

```python
.pyodide(
    state_sync_frequency_frames=20,  # Hash verification every N frames
    queue_resync_threshold=50,       # Trigger resync if queue > threshold
    action_population_method='previous_submitted_action',  # Fallback for missing actions
)
```

---

## Current Pain Points

### 1. Latency in Action Relay
- Path: Client A → Server → Client B
- Adds ~50-200ms depending on network conditions
- Player B sees Player A's actions delayed

### 2. State Sync Overhead
- Full state includes: env_state, cumulative_rewards, RNG state, frame numbers
- Serialization via Pyodide adds overhead
- Large state objects increase transfer time

### 3. Desync Accumulation
- Small timing differences compound over time
- Different frame rates between clients
- Network jitter causes action ordering issues

### 4. Queue Management
- Empty queues use fallback actions (may not match intent)
- Large queues indicate client falling behind
- No prioritization of recent vs old actions

---

## Optimization Opportunities

### Category A: Reduce Message Size

#### A1. Delta State Compression
Instead of sending full state, send only what changed:
```javascript
// Current: Full state every sync
{ env_state: { /* 50+ fields */ }, cumulative_rewards: {...}, ... }

// Optimized: Delta from last sync
{ delta: { ball_x: 150, ball_y: 200 }, frame: 100 }
```

**Implementation complexity**: Medium
**Impact**: High for large states

#### A2. Binary Message Encoding
Replace JSON with binary format (MessagePack already used for some messages):
```javascript
// Ensure all sync messages use msgpack
const binaryState = msgpack.encode(state);
socket.emit('pyodide_state_sync', binaryState);
```

**Implementation complexity**: Low
**Impact**: Medium (10-30% size reduction)

#### A3. Action Batching
Batch multiple actions into single message:
```javascript
// Instead of sending each action immediately
// Batch actions within a small window (e.g., 16ms)
this.actionBatch.push({ player_id, action, frame });
if (Date.now() - this.lastBatchSend > 16) {
    socket.emit('pyodide_action_batch', this.actionBatch);
    this.actionBatch = [];
}
```

**Implementation complexity**: Low
**Impact**: Low-Medium (reduces message count)

---

### Category B: Reduce Sync Frequency

#### B1. Adaptive Sync Frequency
Sync more often when desync detected, less often when stable:
```javascript
// Start with low frequency
this.syncFrequency = 30; // frames

// After desync, increase temporarily
if (desyncDetected) {
    this.syncFrequency = 5;
    setTimeout(() => this.syncFrequency = 30, 5000);
}
```

**Implementation complexity**: Low
**Impact**: Medium

#### B2. Hash-Only Verification (Current)
Only send full state when hash mismatch:
- ✅ Already implemented
- Could optimize hash computation

#### B3. Predictive Sync
Predict when desync likely based on:
- Network latency spikes
- Missed actions
- Frame rate drops

**Implementation complexity**: Medium
**Impact**: Medium

---

### Category C: Improve Action Handling

#### C1. Action Timestamps for Ordering
Include high-resolution timestamps to order actions correctly:
```javascript
socket.emit('pyodide_player_action', {
    action: action,
    timestamp: performance.now(),  // Sub-millisecond precision
    frame_number: this.frameNumber
});
```

**Implementation complexity**: Low
**Impact**: Medium

#### C2. Input Delay (Rollback Alternative)
Add small fixed delay to all inputs for synchronization:
```javascript
// All players delay their own inputs by N frames
const INPUT_DELAY_FRAMES = 3;
this.inputBuffer.push({ action, targetFrame: this.frameNumber + INPUT_DELAY_FRAMES });
```

**Implementation complexity**: Medium
**Impact**: High (but adds input lag)

#### C3. Smarter Action Fallback
Improve fallback when action queue empty:
```javascript
// Current: Use previous action or default
// Improved: Use predicted action based on input pattern
if (queue.empty()) {
    return this.predictAction(playerId);  // ML or heuristic
}
```

**Implementation complexity**: High
**Impact**: Low-Medium

---

### Category D: Frame Rate & Timing

#### D1. Fixed Timestep Simulation
Decouple simulation from render rate:
```javascript
const FIXED_DT = 1000 / 30;  // 30 FPS simulation
let accumulator = 0;

function gameLoop(timestamp) {
    accumulator += timestamp - lastTime;

    while (accumulator >= FIXED_DT) {
        stepSimulation();
        accumulator -= FIXED_DT;
    }

    render(accumulator / FIXED_DT);  // Interpolate
    requestAnimationFrame(gameLoop);
}
```

**Implementation complexity**: Medium
**Impact**: High (consistent simulation across clients)

#### D2. Frame Number Synchronization
Periodically sync frame numbers without full state:
```javascript
// Lightweight frame sync message
socket.emit('pyodide_frame_sync', {
    frame_number: this.frameNumber,
    timestamp: Date.now()
});
```

**Implementation complexity**: Low
**Impact**: Medium

---

### Category E: Network Optimization

#### E1. Socket.IO Configuration Tuning
```javascript
const socket = io({
    transports: ['websocket'],  // Skip polling
    upgrade: false,
    pingTimeout: 5000,
    pingInterval: 2000,
});
```

**Implementation complexity**: Low
**Impact**: Low-Medium

#### E2. Message Priority Queue
Prioritize time-sensitive messages:
```javascript
// Actions are high priority
socket.emit('pyodide_player_action', data, { priority: 'high' });

// State sync is lower priority
socket.emit('pyodide_state_sync', data, { priority: 'low' });
```

**Implementation complexity**: Medium (may need custom transport)
**Impact**: Medium

---

## Recommended Optimization Order

### Phase 1: Quick Wins (1-2 hours each)

1. **E1: Socket.IO tuning** - Ensure websocket transport
2. **A2: Binary encoding** - Use msgpack for all sync messages
3. **D2: Lightweight frame sync** - Add simple frame number sync
4. **C1: Action timestamps** - Improve action ordering

### Phase 2: Medium Effort (2-4 hours each)

5. **B1: Adaptive sync frequency** - Reduce unnecessary syncs
6. **D1: Fixed timestep** - Consistent simulation rate
7. **A3: Action batching** - Reduce message count

### Phase 3: Larger Changes (4+ hours each)

8. **A1: Delta compression** - Only send state changes
9. **C2: Input delay** - Trade latency for consistency
10. **Future: Server authority** - Server runs authoritative game

---

## Metrics to Track

Before optimizing, establish baselines:

1. **Sync frequency**: How often full syncs occur
2. **Desync rate**: % of hash mismatches
3. **Action latency**: Time from input to execution on other client
4. **Message size**: Average bytes per message type
5. **Queue depth**: Average/max action queue size
6. **Frame rate stability**: Variance in client frame rates

Add logging:
```javascript
console.log(`[Sync] Frame ${this.frameNumber}: Queue depths: ${JSON.stringify(queueDepths)}`);
console.log(`[Sync] State size: ${JSON.stringify(state).length} bytes`);
console.log(`[Sync] Action latency: ${Date.now() - action.timestamp}ms`);
```

---

## Next Steps

1. Review current implementation against this document
2. Add metrics logging to establish baselines
3. Implement Phase 1 optimizations
4. Measure impact
5. Proceed to Phase 2 if needed

---

## Future Consideration: Server-Authoritative Mode

If optimizations aren't sufficient, consider hybrid architecture:
- Clients simulate locally for responsiveness
- Server runs authoritative Python environment
- Server broadcasts authoritative state periodically
- Clients reconcile to server state

This provides:
- Ground truth for state
- Reduced client-to-client desync
- Path to anti-cheat if needed

See separate document: `server-authoritative-architecture.md` (to be created)

---

## Prioritized Quick Wins

Based on code review, here are the highest-impact, lowest-effort changes:

### 1. Force WebSocket Transport (5 minutes)
**File:** `interactive_gym/server/static/js/index.js` or where socket is initialized

```javascript
const socket = io({
    transports: ['websocket'],
    upgrade: false
});
```

### 2. Remove Debug Logging from Hot Path (10 minutes)
**File:** `interactive_gym/server/static/js/pyodide_multiplayer_game.js`

Change `console.debug` to conditional or remove entirely in:
- Line 139: Action queue logging
- Line 454: Frame step logging

```javascript
// Option A: Remove
// console.debug(`[MultiplayerPyodide] Queued action...`);

// Option B: Make conditional
if (this.debugMode) {
    console.debug(`[MultiplayerPyodide] Queued action...`);
}
```

### 3. Optimize Hash Computation (30 minutes)
**File:** `interactive_gym/server/static/js/pyodide_multiplayer_game.js`

Current: Full Python execution for every hash
```javascript
const hashData = await this.pyodide.runPythonAsync(`
import hashlib
import json
...
`);
```

Optimized: Use JavaScript for hashing, only get minimal state from Python
```javascript
async computeStateHash() {
    // Get only the minimal state needed for hash
    const minimalState = await this.pyodide.runPythonAsync(`
env.t if hasattr(env, 't') else 0
    `);

    // Hash in JavaScript (much faster)
    const stateStr = JSON.stringify({
        step: minimalState,
        frame: this.frameNumber,
        rewards: this.cumulative_rewards
    });

    // Use SubtleCrypto API
    const hashBuffer = await crypto.subtle.digest('SHA-256',
        new TextEncoder().encode(stateStr));
    return Array.from(new Uint8Array(hashBuffer))
        .map(b => b.toString(16).padStart(2, '0')).join('');
}
```

### 4. Reduce Sync Frequency for Stable Games (5 minutes)
**File:** Scene configuration

If games are staying in sync, increase `state_sync_frequency_frames`:
```python
.pyodide(
    state_sync_frequency_frames=60,  # Was 20, now every 2 seconds at 30fps
)
```

### 5. Add Frame Rate Independence (1 hour)
**File:** `interactive_gym/server/static/js/phaser_gym_graphics.js`

Ensure simulation runs at fixed timestep regardless of render rate:
```javascript
const FIXED_DT = 1000 / 30;  // 30 FPS simulation
let accumulator = 0;
let lastTime = 0;

function update(time) {
    const dt = time - lastTime;
    lastTime = time;
    accumulator += dt;

    while (accumulator >= FIXED_DT) {
        await this.processPyodideGame();  // Step simulation
        accumulator -= FIXED_DT;
    }

    // Render at whatever rate browser supports
    this.renderGame();
}
```

---

## Implementation Checklist

- [ ] Force WebSocket transport
- [ ] Remove/conditionally disable debug logging
- [ ] Optimize hash computation to use JavaScript crypto
- [ ] Tune sync frequency based on testing
- [ ] Add fixed timestep simulation
- [ ] Add metrics logging to measure improvements
- [ ] Test with varying network conditions
