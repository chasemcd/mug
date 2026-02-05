# Phase 73: Production Bug Fixes - Research

**Researched:** 2026-02-05
**Domain:** GGPO rollback netcode, dual-buffer data recording, async Worker timing
**Confidence:** MEDIUM

## Summary

All three failing E2E tests share one root cause: **speculative frame data with predicted Noop actions is being exported as canonical data, causing action value divergences between peers.** The divergence pattern is always action value 6 (Noop/default) on one peer vs real action values (0-5) on the other, starting at early frames (rows 3-10) and affecting ~22% of frames (98/450 in the worst case).

The dual-buffer architecture (Phase 36) is sound in design: `storeFrameData()` writes to `speculativeFrameData`, `_promoteConfirmedFrames()` promotes to `frameDataBuffer` only when `confirmedFrame` advances, and `clearFrameDataFromRollback()` clears both buffers. However, the v1.16 Worker migration (Phase 69) changed rollback replay from synchronous inline Python to asynchronous `worker.batch()`, and there are multiple code paths where speculative data with wrong predictions can escape correction.

**Primary recommendation:** Add diagnostic logging to trace frame-by-frame promotion decisions (what actions are being promoted), then implement a post-rollback canonical sweep or lock-promotion-during-rollback guard. The fix is in a single file: `pyodide_multiplayer_game.js`.

## Standard Stack

No new libraries needed. This is a production bug fix in existing JavaScript code.

### Core
| File | LOC | Purpose | Why It's The Fix Target |
|------|-----|---------|------------------------|
| `interactive_gym/server/static/js/pyodide_multiplayer_game.js` | 7785 | Multiplayer GGPO game engine | Contains ALL affected code |

### Supporting
| File | Purpose | Role in Fix |
|------|---------|-------------|
| `scripts/validate_action_sequences.py` | CSV parity comparison | Validation tool (no changes needed) |
| `tests/e2e/test_data_comparison.py` | E2E parity test | Verification test |
| `tests/e2e/test_latency_injection.py` | Latency parity test | Verification test |
| `tests/e2e/test_network_disruption.py` | Packet loss parity test | Verification test |

## Architecture Patterns

### Data Flow (Current - Phase 36 Design)

```
step() with predicted inputs
        |
        v
speculativeFrameData[N] = {actions, rewards, ...}
        |
[input packet arrives]
        |
        v
storeRemoteInput() -> sets pendingRollbackFrame
        |
[next tick]
        |
        v
_processQueuedInputs() -> storeRemoteInput() -> pendingRollbackFrame
        |
performRollback(targetFrame)
  1. clearFrameDataFromRollback(targetFrame) -- clears BOTH buffers >= target
  2. confirmedFrame = min(confirmedFrame, targetFrame - 1)
  3. Replay with correct inputs via worker.batch()  [ASYNC - yields to event loop]
  4. storeFrameData() for each replayed frame -> writes to speculativeFrameData
  5. rollbackInProgress = false
        |
_updateConfirmedFrame()
  1. Advances confirmedFrame for frames where ALL players have inputs
  2. _promoteConfirmedFrames() -> moves speculative to canonical
        |
step current frame
  1. storeFrameData(currentFrame, ...) -> writes to speculativeFrameData
```

### GGPO Step Function Order (within single tick)

```
Line 2145:  pendingRollbackFrame = null  (clear stale flag)
Line 2149:  _processQueuedInputs()       (drain network queues, may set pendingRollbackFrame)
Line 2190:  processDelayedInputs()       (debug feature)
Line 2196:  if (pendingRollbackFrame)     -> performRollback()  [ASYNC]
Line 2206:  _updateConfirmedFrame()       -> _promoteConfirmedFrames()  [ASYNC - hash computation]
Line 2216:  getInputsForFrame()           (build actions for current frame)
Line 2304:  stepWithActions()             [ASYNC - Worker]
Line 2345:  storeFrameData()             (store current frame in speculative buffer)
Line 2359:  frameNumber++
```

### Guard Mechanisms

| Guard | Where Checked | Purpose |
|-------|--------------|---------|
| `rollbackInProgress` | `storeRemoteInput()` (line 4045) | Prevents nested rollback triggers |
| `rollbackInProgress` | `_processQueuedInputs()` (line 6905) | Prevents input processing during rollback |
| `rollbackInProgress` | `_exchangePendingHashes()` (line 3051) | Prevents hash exchange during rollback |
| `rollbackInProgress` | `_attemptHashComparison()` (line 3112) | Prevents hash comparison during rollback |
| `isProcessingTick` | `_handleWorkerTick()` (line 5625) | Prevents overlapping ticks |
| Input queuing | DataChannel/SocketIO handlers | All inputs pushed to queues, not processed inline |

## Root Cause Analysis

### Confidence: MEDIUM - Multiple hypotheses, investigation needed

The 98 divergences (22% of frames) with action value 6 (Noop) suggest a SYSTEMATIC issue, not a rare race condition. Three candidate root causes, ordered by likelihood:

### Hypothesis 1: Episode-End Promotion Without Rollback (MEDIUM confidence)

**Location:** `_waitForInputConfirmation()` (lines 2858-2903)

At episode end, this method calls `_processQueuedInputs()` and `_updateConfirmedFrame()` in a polling loop. However, it does NOT check or execute `pendingRollbackFrame`. This means:

1. Late inputs arrive during the wait loop
2. `_processQueuedInputs()` -> `storeRemoteInput()` stores inputs and sets `pendingRollbackFrame`
3. But `storeRemoteInput` returns early because the input is "late" and sets `pendingRollbackFrame`
4. `_updateConfirmedFrame()` sees the new inputs, advances `confirmedFrame`
5. `_promoteConfirmedFrames()` promotes speculative data with WRONG predicted actions
6. Rollback never executes because the step function's rollback check never runs again

**Why this could cause 98 divergences:** If many inputs are in flight at episode end, all of them get promoted without correction.

**Counter-evidence:** The divergences start at rows 3-10 (early in episode), not at the end. This hypothesis alone cannot explain early-frame divergences.

### Hypothesis 2: Timing Gap During Async Worker Batch (MEDIUM confidence)

**Location:** `performRollback()` line 4543: `await this.worker.batch(batchOps)`

Pre-Worker-migration, rollback was synchronous (inline Python via `runPythonAsync` which was a single postMessage round-trip for the entire batch). Post-migration, it's `await this.worker.batch()` which is also a single round-trip but the await yields to the event loop.

During this yield, new DataChannel/SocketIO messages arrive and get queued in `pendingInputPackets` / `pendingSocketIOInputs`. These are NOT processed during rollback (`_processQueuedInputs` checks `rollbackInProgress`). They wait for the next tick.

However, there's a subtle timing issue: the next tick's `_processQueuedInputs()` runs BEFORE rollback check. If the queued inputs set `pendingRollbackFrame` to a frame that was already replayed and whose data was already promoted, the new rollback would clear and re-replay, but the original promotion may have already been sent to export.

**Why this matters for early frames:** At the start of a game, P2P connection is fresh, RTT is unknown, and input delivery is maximally delayed. Frames 3-10 are likely ALL predicted, and corrections arrive in a burst when the first batch of inputs gets through.

### Hypothesis 3: Prediction Re-marking Gap After Rollback (LOW confidence)

**Location:** `performRollback()` lines 4458-4464

During replay, frames that still need prediction are re-added to `predictedFrames`. But `_updateConfirmedFrame()` (called at line 2206 after rollback) removes frames from `predictedFrames` when confirming them (line 2811). If inputs for these frames arrive in a LATER tick, the `storeRemoteInput` check `this.predictedFrames.has(frameNumber)` (line 4050) would be FALSE, so no rollback would be triggered despite the prediction being wrong.

**Why this could be the bug:** If frames are confirmed and promoted with wrong data, and then when the CORRECT input arrives, no rollback is triggered because the frame is no longer in `predictedFrames`, the wrong data persists in the canonical buffer.

**Counter-evidence:** `_hasAllInputsForFrame()` should prevent `confirmedFrame` from advancing past a frame where inputs are missing. If the frame's input is missing, it can't be confirmed. But if the input IS present (because `storeRemoteInput` already stored it) then the frame IS correctly confirmed... except the speculative data was recorded with prediction, not the confirmed input.

**CRITICAL INSIGHT:** This IS the mechanism. When `storeRemoteInput` runs:
1. It stores the input in `inputBuffer` (line 4035) - the frame is now "confirmed" from an input perspective
2. It checks for rollback (line 4050) - if prediction was wrong, sets `pendingRollbackFrame`
3. Later, `performRollback()` clears and replays with correct data
4. Then `_updateConfirmedFrame()` promotes the corrected data

The sequence works IF rollback precedes promotion. But the question is whether ALL paths guarantee this ordering.

### Hypothesis 4: Combined Mechanism (HIGH confidence)

The most likely explanation combines elements of hypotheses 1-3:

**During normal gameplay (mid-episode):**
- The step function's ordering (process inputs -> rollback -> promote) is correct
- Divergences here should be zero, and indeed idle tests pass

**During active input gameplay:**
- With 150ms/200ms input intervals at 10 FPS (100ms tick), inputs arrive asynchronously
- The `_updateConfirmedFrame()` call inside `_waitForInputConfirmation()` at episode end promotes remaining speculative frames WITHOUT checking for pending rollbacks
- Additionally, the `_promoteRemainingAtBoundary()` (line 2916) force-promotes ALL remaining speculative data at episode end, regardless of whether rollback is needed

**At episode start:**
- Early frames (3-10) are stepped before any remote inputs arrive
- When the burst of remote inputs arrives, rollback corrects some frames but the correction window may miss frames that were promoted between rollback and the next input arrival

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rollback correction | New buffer architecture | Fix timing in existing dual-buffer | Architecture is sound; only timing/ordering needs fixing |
| Parity verification | Custom diff tool | Existing `validate_action_sequences.py` | Already works correctly |
| Test infrastructure | New test framework | Existing E2E test suite | Tests correctly detect the bug |

## Common Pitfalls

### Pitfall 1: Modifying Promotion Logic Without Understanding Confirmation
**What goes wrong:** Changing `_promoteConfirmedFrames()` without understanding that `confirmedFrame` gates promotion
**Why it happens:** The promotion gate relies on `confirmedFrame` being set correctly, which depends on `inputBuffer` state
**How to avoid:** Trace the full data flow: input arrival -> inputBuffer -> _hasAllInputsForFrame -> confirmedFrame -> promotion
**Warning signs:** Tests pass without latency but fail with latency (timing-dependent)

### Pitfall 2: Forgetting Episode-End Paths
**What goes wrong:** Fixing the step function's promotion path but missing `_waitForInputConfirmation()` and `_promoteRemainingAtBoundary()`
**Why it happens:** These are called from episode-end handlers, not from the step function
**How to avoid:** Search for ALL callers of `_promoteConfirmedFrames()` and `_updateConfirmedFrame()` and ensure each path handles pending rollbacks
**Warning signs:** Tests pass intermittently (depends on whether episode end aligns with pending rollbacks)

### Pitfall 3: Breaking the isProcessingTick Guard
**What goes wrong:** Adding async operations that break the tick guard's protection against overlapping ticks
**Why it happens:** Adding rollback handling in new locations introduces new async code paths
**How to avoid:** Keep the single-tick flow: process inputs -> rollback -> promote -> step. Don't add new tick entry points.
**Warning signs:** Random crashes, state corruption, duplicate frame data

### Pitfall 4: Assuming String/Number Key Consistency
**What goes wrong:** Player ID keys differ between code paths (string "0" vs number 0)
**Why it happens:** JavaScript's loose typing, JSON serialization, binary protocol encoding
**How to avoid:** Always use `String(playerId)` for Map lookups, `parseInt()` only for binary encoding
**Warning signs:** `usedAction === undefined` in storeRemoteInput, rollback not triggering

## Code Examples

### Current Step Function Flow (Reference)
```javascript
// Source: pyodide_multiplayer_game.js lines 2135-2359
// GGPO Order of Operations:
// 1. Clear stale rollback flag
this.pendingRollbackFrame = null;
// 2. Process queued inputs synchronously
this._processQueuedInputs();
// 3. Process debug-delayed inputs
this.processDelayedInputs();
// 4. Execute pending rollback
if (this.pendingRollbackFrame !== null) {
    await this.performRollback(rollbackFrame, humanPlayerIds);
}
// 5. Update confirmed frame + promote
await this._updateConfirmedFrame();
// 6. Build actions, step, store frame data
```

### Current _waitForInputConfirmation (BUG LOCATION)
```javascript
// Source: pyodide_multiplayer_game.js lines 2883-2896
while (performance.now() - startTime < timeoutMs) {
    this._processQueuedInputs();  // May set pendingRollbackFrame
    if (this._hasAllInputsForFrame(targetFrame, humanPlayerIds)) {
        await this._updateConfirmedFrame();  // Promotes WITHOUT rollback check!
        return true;
    }
    await new Promise(resolve => setTimeout(resolve, 10));
}
```

### Current clearFrameDataFromRollback (Reference)
```javascript
// Source: pyodide_multiplayer_game.js lines 3490-3504
clearFrameDataFromRollback(targetFrame) {
    // Clears BOTH canonical and speculative buffers >= targetFrame
    for (const frame of this.frameDataBuffer.keys()) {
        if (frame >= targetFrame) this.frameDataBuffer.delete(frame);
    }
    for (const frame of this.speculativeFrameData.keys()) {
        if (frame >= targetFrame) this.speculativeFrameData.delete(frame);
    }
}
```

### Current storeRemoteInput Rollback Detection (Reference)
```javascript
// Source: pyodide_multiplayer_game.js lines 4050-4088
if (frameNumber < this.frameNumber && this.predictedFrames.has(frameNumber)) {
    const actionRecord = this.actionSequence.find(r => r.frame === frameNumber);
    if (actionRecord) {
        const usedAction = actionRecord.actions[playerIdStr]
            ?? actionRecord.actions[parseInt(playerIdStr)];
        if (usedAction !== undefined && usedAction !== action) {
            this.pendingRollbackFrame = Math.min(
                this.pendingRollbackFrame ?? frameNumber,
                frameNumber
            );
        }
    }
}
```

## Investigation Plan

### Step 1: Add Diagnostic Logging (HIGH priority)

Add logging to `_promoteConfirmedFrames()` that traces the ACTIONS being promoted:

```javascript
_promoteConfirmedFrames() {
    const promoted = [];
    for (const [frame, data] of this.speculativeFrameData.entries()) {
        if (frame <= this.confirmedFrame) {
            // LOG: What actions are being promoted
            const actionsStr = Object.entries(data.actions)
                .map(([k,v]) => `${k}:${v}`).join(',');
            p2pLog.debug(`PROMOTE: frame=${frame} actions={${actionsStr}} ` +
                `pendingRollback=${this.pendingRollbackFrame}`);
            this.frameDataBuffer.set(frame, { ...data, wasSpeculative: true });
            promoted.push(frame);
        }
    }
    // ... rest unchanged
}
```

This will reveal whether promotions contain Noop (6) when they should contain real actions.

### Step 2: Check _waitForInputConfirmation Rollback Gap (HIGH priority)

The `_waitForInputConfirmation()` method at episode end calls `_processQueuedInputs()` + `_updateConfirmedFrame()` but never checks or executes `pendingRollbackFrame`. Add rollback execution to this loop.

### Step 3: Check _promoteRemainingAtBoundary (HIGH priority)

The `_promoteRemainingAtBoundary()` method force-promotes ALL remaining speculative data. If any of this data has wrong predictions, it gets exported. Consider executing any pending rollback before this promotion.

### Step 4: Verify storeRemoteInput rollback detection (MEDIUM priority)

Confirm that `usedAction` lookup never returns `undefined` due to key type mismatches. Add logging for the `usedAction === undefined` case.

### Step 5: Test with controlled scenarios (MEDIUM priority)

Run `test_active_input_parity` with enhanced logging. Examine which frames diverge and whether they were promoted without rollback correction.

## Potential Fixes (Priority Order)

### Fix 1: Execute Pending Rollback Before Promotion (Everywhere)

Ensure EVERY code path that calls `_updateConfirmedFrame()` or `_promoteConfirmedFrames()` first checks and executes any pending rollback. This is the most targeted fix.

**Locations to check:**
1. Step function (line 2206) - ALREADY CORRECT (rollback precedes)
2. `_waitForInputConfirmation()` (line 2889) - MISSING rollback check
3. `_performFastForward()` (line 4896) - Sets confirmedFrame directly, may need rollback
4. Any other callers of `_updateConfirmedFrame()` or `_promoteConfirmedFrames()`

### Fix 2: Guard Promotion Against Pending Rollback

Add a check to `_promoteConfirmedFrames()` itself:

```javascript
_promoteConfirmedFrames() {
    if (this.pendingRollbackFrame !== null) {
        p2pLog.debug('Skipping promotion - rollback pending');
        return;
    }
    // ... existing promotion logic
}
```

This is a safety net that prevents wrong data from ever being promoted.

### Fix 3: Post-Rollback Canonical Sweep

After rollback replay stores corrected data in `speculativeFrameData`, sweep `frameDataBuffer` for any entries that were promoted with old data and overwrite them:

```javascript
// After storeFrameData in replay loop (line 4631-4639):
// Also overwrite canonical buffer if frame was already promoted
for (const entry of replayLog) {
    this.storeFrameData(entry.frame, { ... }); // writes to speculative
    if (this.frameDataBuffer.has(entry.frame)) {
        // Frame was previously promoted with wrong data - overwrite
        this.frameDataBuffer.set(entry.frame, { ...entry, wasSpeculative: true });
    }
}
```

### Fix 4: Defer confirmedFrame During Rollback

Prevent `confirmedFrame` from advancing while `rollbackInProgress` is true:

```javascript
async _updateConfirmedFrame() {
    if (this.rollbackInProgress) return;  // Defer until rollback complete
    // ... existing logic
}
```

This prevents mid-rollback promotion. Already partially implemented via `_processQueuedInputs` guard but `_updateConfirmedFrame` itself doesn't check.

### Recommended Fix Strategy

Apply Fix 2 (guard promotion) + Fix 1 (execute rollback before promotion in `_waitForInputConfirmation`). This provides:
- **Correctness:** No promotion of uncorrected data
- **Safety:** Guard in `_promoteConfirmedFrames` catches any future bugs
- **Completeness:** Episode-end path also handles rollbacks

Consider adding Fix 3 (canonical sweep) as additional safety.

## State of the Art

| Old Approach (pre-Phase 69) | Current Approach (post-Phase 69) | When Changed | Impact |
|----------------------------|----------------------------------|--------------|--------|
| Synchronous inline Python rollback | Async Worker batch rollback | 2026-02-05 (Phase 69) | Introduced event loop yields during rollback |
| Single `runPythonAsync` for all replay | `worker.batch()` single round-trip | 2026-02-05 (Phase 69) | Batch is single round-trip but async |
| `this.pyodide` direct access | `this.worker.*` structured commands | 2026-02-05 (Phase 69) | All Pyodide ops go through Worker |

**Key insight:** The v1.16 Worker migration (Phase 69) was completed the same day as the test audit (Phase 71). The migration made the system correct in terms of API but introduced timing changes. The dual-buffer architecture (Phase 36) was designed for synchronous operation and its ordering assumptions may not hold under async Worker operations.

## Open Questions

1. **Are early-frame (3-10) divergences from mid-episode or episode-end?**
   - What we know: Divergences start at rows 3-10
   - What's unclear: Whether these are promoted at episode end by `_promoteRemainingAtBoundary()` or during mid-episode `_updateConfirmedFrame()` calls
   - Recommendation: Add logging to trace when each divergent frame is promoted

2. **Does the async Worker batch introduce NEW event loop yields?**
   - What we know: `worker.batch()` is a single `postMessage` round-trip
   - What's unclear: Whether the pre-migration `runPythonAsync` was also a single round-trip or multiple
   - Recommendation: Compare Worker postMessage patterns to determine if timing differs

3. **Why does packet loss cause FEWER divergences (18 vs 98)?**
   - What we know: More rollbacks = more corrections
   - What's unclear: Whether the causality is purely "more rollbacks fix more frames" or if timing changes
   - Recommendation: This will likely be resolved by the fix - if the fix works, the "why" becomes academic

## Affected Tests

| Test | File | Expected Result After Fix |
|------|------|--------------------------|
| `test_active_input_parity` | `tests/e2e/test_data_comparison.py` | PASS (0 divergences) |
| `test_active_input_with_latency[100]` | `tests/e2e/test_latency_injection.py` | PASS (0 divergences) |
| `test_active_input_with_packet_loss` | `tests/e2e/test_network_disruption.py` | PASS (0 divergences) |

### Regression Tests (Must Continue Passing)
| Test | File | Why |
|------|------|-----|
| `test_export_parity_basic` | `test_data_comparison.py` | Baseline idle parity |
| `test_export_parity_with_latency` | `test_data_comparison.py` | Idle parity with latency |
| `test_focus_loss_mid_episode_parity` | `test_data_comparison.py` | Focus loss parity |
| `test_episode_completion_under_fixed_latency[100]` | `test_latency_injection.py` | Episode completion |
| `test_packet_loss_triggers_rollback` | `test_network_disruption.py` | Rollback mechanism |

## Sources

### Primary (HIGH confidence)
- `pyodide_multiplayer_game.js` - Direct code analysis of all 7785 lines
- `.planning/phases/36-buffer-split/36-01-SUMMARY.md` - Original dual-buffer design
- `.planning/phases/71-test-audit/71-AUDIT.md` - Bug identification and evidence
- `.planning/phases/69-multiplayer-batch-operations/69-03-SUMMARY.md` - Worker migration details

### Secondary (MEDIUM confidence)
- `scripts/validate_action_sequences.py` - Parity comparison tool
- `tests/e2e/test_data_comparison.py` - Test implementation details
- `tests/e2e/test_latency_injection.py` - Latency test implementation
- `tests/e2e/test_network_disruption.py` - Packet loss test implementation

## Metadata

**Confidence breakdown:**
- Root cause mechanism: MEDIUM - Multiple hypotheses identified, investigation needed to confirm which dominates
- Fix locations: HIGH - All relevant code paths identified and traced
- Fix strategy: MEDIUM - Recommended approach is sound but untested

**Research date:** 2026-02-05
**Valid until:** N/A (this is a bug fix, not a library/framework research)
