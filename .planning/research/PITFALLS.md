# Pitfalls Research

**Domain:** Rollback netcode data collection for P2P multiplayer research
**Researched:** 2026-01-30
**Confidence:** HIGH (verified against GGPO docs, project implementation, and established netcode literature)

## Executive Summary

Data divergence in P2P rollback systems stems from a fundamental tension: **speculative execution optimizes player experience but corrupts research data**. The core issue is that each client runs its own simulation, making predictions that may be wrong, and correcting them via rollback. If data collection doesn't account for this, the exported data contains a mix of speculative (wrong) and corrected (right) outcomes.

The project's current `frameDataBuffer` architecture addresses this by clearing and re-recording on rollback, but several edge cases and pitfalls remain.

---

## Critical Pitfalls

### Pitfall 1: Recording Speculative Data as Ground Truth

**What goes wrong:**
Data collection records outcomes from frames simulated with *predicted* inputs. When a rollback occurs, the game state is corrected, but previously recorded data for those frames persists. The final export contains a mix of speculated and corrected data that never represented the actual game.

**Why it happens:**
GGPO-style rollback predicts remote player inputs when packets haven't arrived. If prediction is wrong, the game rolls back and replays with correct inputs. If data recording doesn't clear and re-record during rollback, the speculative data remains.

**How to avoid:**
```javascript
// On rollback to targetFrame:
// 1. Clear all frame data from targetFrame onwards
clearFrameDataFromRollback(targetFrame) {
    for (const frame of this.frameDataBuffer.keys()) {
        if (frame >= targetFrame) {
            this.frameDataBuffer.delete(frame);
        }
    }
}

// 2. Re-record data during replay (not just during initial simulation)
// The current implementation does this in executeGGPORollback()
```

**Warning signs:**
- Frame counts differ between players' exports
- Actions for a frame differ between players
- Reward totals don't match between players
- Infos contain physically impossible states (e.g., player at two positions)

**Phase to address:**
Phase 1 (Isolation) - Verify rollback clears frame data buffer before replay

---

### Pitfall 2: Fast-Forward Bulk Processing Without Re-Recording

**What goes wrong:**
When a tab is backgrounded and refocused, the system fast-forwards through missed frames using buffered partner inputs. If this bulk processing uses a different code path than normal step processing, data may not be recorded for fast-forwarded frames, creating gaps in the export.

**Why it happens:**
Fast-forward is an optimization to catch up quickly. It may skip certain callbacks or use simplified logic that doesn't include data recording. The project's `FocusManager.drainBufferedInputs()` returns buffered packets, but the fast-forward loop must explicitly call `storeFrameData()` for each frame.

**How to avoid:**
```javascript
// Fast-forward loop MUST mirror normal step() data recording:
for (const packet of bufferedInputs) {
    // 1. Apply the input
    storeRemoteInput(packet.playerId, packet.action, packet.frame);

    // 2. Step the environment (same as normal loop)
    const result = await stepEnvironment(inputs);

    // 3. Record frame data (CRITICAL - don't skip this)
    storeFrameData(frameNumber, {
        actions: inputs,
        rewards: result.rewards,
        terminateds: result.terminateds,
        truncateds: result.truncateds,
        infos: result.infos
    });
}
```

**Warning signs:**
- Frame numbers have gaps in export (e.g., 1, 2, 3, 57, 58, 59)
- Total frame count is less than expected episode length
- Focus loss events correlate with missing data ranges
- `focusManager.getTelemetry().backgroundPeriods` non-empty but corresponding frames missing

**Phase to address:**
Phase 2 (Fast-Forward) - Audit fast-forward code path for data recording parity

---

### Pitfall 3: RNG State Not Included in Snapshots

**What goes wrong:**
Rollback restores environment state but not random number generator state. If the environment uses RNG during simulation, replayed frames produce different random outcomes than the original, causing state divergence even with identical inputs.

**Why it happens:**
Developers focus on obvious game state (positions, inventories) and forget that RNG is hidden state that affects determinism. Python's `random` module and NumPy's RNG have global state that must be captured.

**How to avoid:**
```javascript
// The project correctly captures RNG state:
async saveStateSnapshot(frameNumber) {
    const stateJson = await this.pyodide.runPythonAsync(`
        import numpy as np
        import random

        _np_rng_state = np.random.get_state()
        _py_rng_state = random.getstate()

        _snapshot = {
            'env_state': env.get_state(),
            'np_rng_state': _np_rng_serializable,
            'py_rng_state': _py_rng_state
        }
    `);
}
```

**Warning signs:**
- Determinism test fails (same inputs produce different outputs)
- GGPO `ggpo_start_synctest` equivalent detects divergence
- Hash comparison between clients fails despite identical input sequences
- Random events (drops, spawns) differ between players

**Phase to address:**
Phase 1 (Isolation) - Verify RNG state is captured and restored correctly

---

### Pitfall 4: Frame Number Disagreement Between Clients

**What goes wrong:**
Each client maintains its own frame counter. If they start on different frames or one client skips/repeats frames due to timing, their exports will have different frame numbers for the same game events, making correlation impossible.

**Why it happens:**
- Episode reset doesn't synchronize frame counters
- One client counts from 1, another from 0
- Network latency causes one client to run faster
- Pause/unpause handling differs

**How to avoid:**
```javascript
// Ensure deterministic frame numbering:
// 1. Both clients start episode at frame 0
this.frameNumber = 0;

// 2. Frame advances exactly once per step
this.frameNumber++;  // Only in step(), never in render

// 3. Rollback resets frame to snapshot frame, then replays
async loadStateSnapshot(frameNumber) {
    this.frameNumber = frameNumber;  // Restore frame counter
}
```

**Warning signs:**
- Export from Player A has 100 frames, Player B has 98 frames
- Same action appears at frame 50 for Player A, frame 52 for Player B
- Episode rewards match but frame-by-frame rewards don't align

**Phase to address:**
Phase 1 (Isolation) - Add frame counter validation to hash comparison

---

### Pitfall 5: Desync Detection Without Data Correction

**What goes wrong:**
System detects desync (via hash comparison) but only logs it without correcting exported data. The desync is known but the export still contains diverged data from different game realities.

**Why it happens:**
Desync detection is implemented for debugging visibility, but the remediation (state resync, data clearing) is either incomplete or not triggered.

**How to avoid:**
```javascript
// Desync detection MUST trigger data remediation:
async onDesyncDetected(frame, localHash, remoteHash) {
    // 1. Log for debugging
    this.desyncEvents.push({frame, localHash, remoteHash, timestamp: Date.now()});

    // 2. Trigger state resync (one client defers to other)
    if (this._shouldRequestStateResync(peerId)) {
        await this.requestStateFromPeer(peerId);
    }

    // 3. Clear frame data buffer from desync point
    this.clearFrameDataFromRollback(frame);

    // 4. Mark data after desync as UNVERIFIED in export
    this.verifiedFrame = Math.min(this.verifiedFrame, frame - 1);
}
```

**Warning signs:**
- `desyncEvents` array is non-empty in export
- `verifiedFrame` is less than `currentFrame`
- Hash comparison shows divergence but exports still differ

**Phase to address:**
Phase 3 (Verification) - Ensure desync detection triggers data correction

---

### Pitfall 6: Input Delay Creates Observation/Action Temporal Mismatch

**What goes wrong:**
With input delay (e.g., 2 frames), a player's input at frame N executes at frame N+2. If data recording associates the input with frame N (when pressed) instead of frame N+2 (when executed), the observation-action pairs are misaligned.

**Why it happens:**
Input delay is a UX optimization to reduce rollbacks by giving time for inputs to arrive. But it creates temporal displacement that data recording must account for.

**How to avoid:**
```javascript
// Record actions at EXECUTION frame, not INPUT frame:
storeLocalInput(action, currentFrame) {
    const targetFrame = currentFrame + this.INPUT_DELAY;
    // Input is stored for targetFrame, not currentFrame
    this.inputBuffer.get(targetFrame).set(myPlayerId, action);
    return targetFrame;
}

// When recording frame data, use the actual action executed at that frame:
storeFrameData(frameNumber, {
    actions: this.getInputsForFrame(frameNumber),  // Gets action FOR this frame
    // ...
});
```

**Warning signs:**
- Observation at frame N paired with action that makes no sense for that observation
- "Impossible" action sequences (e.g., moving into wall that wasn't there 2 frames ago)
- Behavioral cloning agent learns delayed/incorrect associations

**Phase to address:**
Phase 2 (Fast-Forward) - Verify input delay handling in data recording

---

### Pitfall 7: Cumulative Reward Divergence After Rollback

**What goes wrong:**
Cumulative rewards are incremented speculatively during prediction, then not corrected when rollback occurs. Export shows different total rewards between players, or reward totals that don't match the sum of per-frame rewards.

**Why it happens:**
Cumulative rewards are often stored in a simple counter that gets incremented in step(). If rollback restores environment state but not the reward counter, the counter retains speculative values.

**How to avoid:**
```javascript
// Include cumulative_rewards in state snapshot:
saveStateSnapshot(frameNumber) {
    snapshotData.cumulative_rewards = {...this.cumulative_rewards};
    snapshotData.step_num = this.step_num;
}

// Restore cumulative_rewards on snapshot load:
loadStateSnapshot(frameNumber) {
    this.cumulative_rewards = {...snapshotData.cumulative_rewards};
    this.step_num = snapshotData.step_num;
}
```

**Warning signs:**
- `cumulative_rewards` in export doesn't match sum of per-frame rewards
- Episode end rewards differ between players
- Reward totals diverge increasingly over episode length

**Phase to address:**
Phase 1 (Isolation) - Verify cumulative rewards are included in snapshot

---

### Pitfall 8: Floating-Point Non-Determinism in Browser

**What goes wrong:**
JavaScript floating-point operations can produce slightly different results between browsers, machines, or even runs. In a P2P system, tiny differences compound over time into complete state divergence.

**Why it happens:**
Floating-point arithmetic is not associative: `(a + b) + c` may differ from `a + (b + c)` by small epsilon. Different JavaScript engines may optimize differently, and FPU state can affect results.

**How to avoid:**
```javascript
// Use fixed-point arithmetic for deterministic simulation:
// From Jimmy's Blog rollback tutorial:
const FIXED_SCALE = 1000;

function toFixed(float) {
    return Math.round(float * FIXED_SCALE);
}

function fromFixed(fixed) {
    return fixed / FIXED_SCALE;
}

function mulFixed(a, b) {
    return Math.round((a * b) / FIXED_SCALE);
}
```

Alternatively, ensure all physics/math happens in Python (Pyodide) where NumPy provides consistent behavior.

**Warning signs:**
- Hash divergence after many frames despite identical inputs
- Slow drift that accelerates over time
- Desync happens more in long episodes
- Different browsers produce different results

**Phase to address:**
Phase 1 (Isolation) - Verify all deterministic logic uses consistent arithmetic

---

## Data Divergence Causes

| Cause | Symptom | Fix |
|-------|---------|-----|
| Speculative data not cleared on rollback | Actions differ for same frame between players | Clear `frameDataBuffer` from rollback target frame |
| Fast-forward skips data recording | Gaps in frame numbers in export | Mirror normal step() recording in fast-forward loop |
| RNG state not in snapshot | Different random events between players | Include numpy/Python RNG state in snapshot |
| Frame counter mismatch | Different frame counts in exports | Synchronize frame counter on episode reset, include in hash |
| Desync without data correction | Hash divergence but exports still differ | Desync detection must trigger data clearing/resync |
| Input delay temporal mismatch | Observation/action pairs misaligned | Record action at execution frame, not input frame |
| Cumulative rewards not in snapshot | Reward totals diverge | Include cumulative_rewards in state snapshot |
| Floating-point non-determinism | Slow drift, eventual divergence | Use fixed-point or consistent math library |
| Web Worker timing drift | One client runs faster | Use deterministic tick timing, not wall clock |
| Tab backgrounding | requestAnimationFrame paused | Use Web Worker for timing, buffer inputs |

---

## Fast-Forward Specific Issues

### Issue 1: requestAnimationFrame Throttling

**Problem:** Browsers throttle `requestAnimationFrame` to 1/second (or stop entirely) when tab is backgrounded. This pauses the game loop, causing massive frame drift.

**Solution:** Use Web Worker for timing (not affected by throttling) and buffer partner inputs during background period.

```javascript
// Web Worker keeps timing alive:
// worker.js
setInterval(() => {
    postMessage({ type: 'tick' });
}, 1000 / 60);

// Main thread:
worker.onmessage = (e) => {
    if (e.data.type === 'tick' && !document.hidden) {
        gameLoop();
    }
};
```

### Issue 2: Bulk Input Application Order

**Problem:** When refocusing, many buffered inputs must be applied. If applied in wrong order (e.g., sorted by arrival time instead of frame number), simulation diverges.

**Solution:** Always sort buffered inputs by frame number before applying:

```javascript
const bufferedInputs = focusManager.drainBufferedInputs();
bufferedInputs.sort((a, b) => a.frame - b.frame);
for (const input of bufferedInputs) {
    // Apply in frame order
}
```

### Issue 3: Rendering During Fast-Forward

**Problem:** Rendering every fast-forward frame is slow and unnecessary. But if render callback records data, skipping render skips data.

**Solution:** Decouple data recording from rendering:

```javascript
// During fast-forward:
while (currentFrame < targetFrame) {
    stepEnvironment();           // MUST run
    storeFrameData();            // MUST run
    // Skip rendering - only visual
}
// Render only final frame
renderFrame();
```

### Issue 4: Partner Input Request Timeout

**Problem:** After refocus, we may need to request missed inputs from partner. If partner doesn't respond, we're stuck.

**Solution:** Request with timeout and fallback to prediction:

```javascript
async requestMissingInputs(startFrame, endFrame) {
    const response = await this.sendWithTimeout(
        { type: 'input_request', startFrame, endFrame },
        TIMEOUT_MS
    );

    if (!response) {
        // Fallback: use predictions and mark as unverified
        this.verifiedFrame = Math.min(this.verifiedFrame, startFrame - 1);
    }
}
```

---

## "Looks Synchronized But Isn't" Scenarios

### Scenario 1: Symmetric Divergence

**Description:** Both players have identical frame counts and similar-looking data, but the actions/states are for different game realities that happened to have similar structures.

**Detection:** Compare per-frame hashes between exports. Identical frame counts but different hashes = diverged.

**Prevention:** Continuous hash exchange and comparison (already implemented via `confirmedHashHistory`).

---

### Scenario 2: Delayed Desync Manifestation

**Description:** A desync at frame 50 doesn't produce visible effects until frame 200 when the diverged state paths finally manifest differently. By then, 150 frames of diverged data have been recorded.

**Detection:** Full hash comparison on every frame, not just when "something looks wrong."

**Prevention:** Early, frequent hash comparison. Don't wait for visible divergence.

---

### Scenario 3: Episode Boundary Masking

**Description:** Desync happens late in episode, but episode ends before it's detected. New episode resets state, so desync appears resolved. But the previous episode's exported data is corrupted.

**Detection:** Final episode validation hash comparison before clearing buffers.

**Prevention:**
```javascript
// On episode end, before clearing:
await validateEpisodeData();
if (desyncDetected) {
    // Mark episode as unverified in export
    this.cumulativeValidation.episodes[this.num_episodes].verified = false;
}
```

---

### Scenario 4: Prediction Always Correct (By Chance)

**Description:** Predictions happen to be correct (e.g., player held same button for 50 frames), so no rollback occurs. But the data recording system was never exercised through rollback, and latent bugs exist.

**Detection:** Force synthetic rollbacks in testing (artificial input delay).

**Prevention:** Use `debugRemoteInputDelay` to simulate latency and verify rollback data correction.

---

### Scenario 5: One-Sided Rollback

**Description:** Only one player experiences rollbacks (asymmetric latency). Their data is corrected, but the other player's data (which never rolled back) may differ due to timing differences in when inputs were applied.

**Detection:** Compare rollback counts between players. Asymmetric rollbacks = higher desync risk.

**Prevention:** Ensure both clients apply identical input-to-frame mappings regardless of when inputs arrived.

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Speculative data as ground truth | Phase 1 (Isolation) | Force rollback, verify data buffer cleared and re-recorded |
| Fast-forward bulk processing | Phase 2 (Fast-Forward) | Background tab, refocus, verify no frame gaps in export |
| RNG state not in snapshot | Phase 1 (Isolation) | Rollback, verify RNG produces same sequence |
| Frame number disagreement | Phase 1 (Isolation) | Compare frame counts in exports, must match exactly |
| Desync without data correction | Phase 3 (Verification) | Inject artificial desync, verify data corrected |
| Input delay temporal mismatch | Phase 2 (Fast-Forward) | With INPUT_DELAY > 0, verify observation/action alignment |
| Cumulative reward divergence | Phase 1 (Isolation) | Rollback after reward, verify cumulative resets |
| Floating-point non-determinism | Phase 1 (Isolation) | Run identical inputs, compare state hashes |
| Tab backgrounding issues | Phase 2 (Fast-Forward) | 10s background, verify continuity on refocus |
| Symmetric divergence | Phase 3 (Verification) | Export both players, compare per-frame hashes |

---

## Testing Checklist

### Phase 1: Isolation Tests
- [ ] Single-client determinism: Same inputs always produce same state hash
- [ ] Forced rollback: Clear and re-record frame data correctly
- [ ] RNG snapshot: Random sequence identical after rollback
- [ ] Cumulative rewards: Restored correctly on snapshot load
- [ ] Frame counter: Both clients agree on frame numbers

### Phase 2: Fast-Forward Tests
- [ ] Tab background: No frame gaps after refocus
- [ ] Buffered input ordering: Applied in frame order
- [ ] Input delay: Actions paired with correct observations
- [ ] Web Worker timing: Game progresses during background

### Phase 3: Verification Tests
- [ ] Hash comparison: Both clients agree on every frame's hash
- [ ] Desync recovery: Data corrected after desync detection
- [ ] Episode boundary: Final hash verified before clearing
- [ ] Export parity: Both players' exports have identical data (modulo player ID perspective)

---

## Sources

- [GGPO Official Documentation](https://www.ggpo.net/) - Rollback netcode fundamentals
- [GGPO Developer Guide](https://github.com/pond3r/ggpo/blob/master/doc/DeveloperGuide.md) - Save/load state, sync testing, determinism requirements
- [SnapNet: Netcode Architectures Part 2 - Rollback](https://www.snapnet.dev/blog/netcode-architectures-part-2-rollback/) - Performance constraints, spiral of death
- [Jimmy's Blog: Making a GGPO-style rollback game](https://outof.pizza/posts/rollback/) - Fixed-point arithmetic for JavaScript
- [Gaffer on Games: Floating Point Determinism](https://gafferongames.com/post/floating_point_determinism/) - Cross-platform floating point issues
- [coherence Documentation: Determinism, Prediction and Rollback](https://docs.coherence.io/manual/advanced-topics/competitive-games/determinism-prediction-rollback) - Common determinism pitfalls
- [NetplayJS](https://github.com/rameshvarun/netplayjs) - WebRTC P2P rollback implementation
- [MDN: Page Visibility API](https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API) - Browser tab backgrounding behavior
- [MDN: requestAnimationFrame](https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame) - Throttling in background tabs
- [GameDev.net: Rollbacks and Simulation Replay](https://www.gamedev.net/forums/topic/713082-rollbacks-and-simulation-replay-performance/) - Performance optimization for rollback
- [GameMaker: rollback_confirmed_frame](https://manual.gamemaker.io/beta/en/GameMaker_Language/GML_Reference/Rollback/Rollback_Variables/rollback_confirmed_frame.htm) - Confirmed vs predicted frames
- [Understanding Fighting Game Networking](https://supercombo.gg/2021/10/13/archive-understanding-fighting-game-networking-by-mauve/) - GGPO frame delay and timing
