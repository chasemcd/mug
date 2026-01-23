# Phase 26: Resync & Partner Experience - Research

**Researched:** 2026-01-23
**Domain:** Fast-forward resync patterns, GGPO integration with background state, partner experience during focus loss
**Confidence:** HIGH

## Summary

This research investigates how to implement fast-forward resync when a backgrounded player refocuses, while ensuring the focused partner experiences no interruption. The core challenge is processing multiple queued frames rapidly without blocking the partner's real-time game loop.

Phase 25 already provides the infrastructure:
- `FocusManager` class with `isBackgrounded` state
- `backgroundInputBuffer` storing partner inputs received while backgrounded
- `drainBufferedInputs()` method to retrieve all queued inputs
- Worker-based timing that continues ticking even when backgrounded
- Local player inputs default to `defaultAction` while backgrounded

The existing GGPO `performRollback()` method already implements frame-by-frame replay without rendering - this same pattern applies to fast-forward. The key insight is that fast-forward is conceptually similar to rollback replay: load a known state and step through multiple frames rapidly using queued inputs.

**Primary recommendation:** On refocus, drain the buffered inputs, inject them into the GGPO input buffer at their recorded frame numbers, then process multiple frames per tick (batch stepping) until caught up. The focused partner continues normally because they already received and processed the backgrounded player's `defaultAction` inputs in real-time via the existing P2P input flow.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Page Visibility API | Browser-native | Already used by FocusManager | Detects foreground event |
| Existing GGPO system | In codebase | Frame replay without render | `stepWithActions()` already supports fast stepping |
| Web Worker timer | Phase 24 | Continuous timing | Provides accurate elapsed time during background |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| performance.now() | Browser-native | Timing measurement | Track fast-forward duration |
| requestIdleCallback | Browser-native | Yield to main thread | Optional: spread batch across frames |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Batch step in one tick | Spread across multiple ticks | Batch is simpler but may cause frame spike; spreading is smoother but more complex |
| Skip missed frames | Fast-forward all frames | Skipping loses state; fast-forward maintains determinism |
| Discard buffered inputs | Process all buffered | Discard causes desync; processing ensures correctness |

**Installation:**
```bash
# No new dependencies - uses existing infrastructure
```

## Architecture Patterns

### Recommended Data Flow
```
BACKGROUNDED PLAYER REFOCUSES:
  1. FocusManager._onForegrounded() fires
  2. drainBufferedInputs() retrieves [{playerId, inputs, currentFrame}, ...]
  3. For each buffered packet: inject into GGPO inputBuffer at recorded frame
  4. Determine catchup range: pausedFrame to partner's currentFrame
  5. Fast-forward loop: step each frame without render until caught up
  6. Resume normal tick processing

FOCUSED PARTNER (no change needed):
  - Receives backgrounded player's defaultAction via normal P2P flow
  - Continues stepping normally, sees partner go idle
  - No pause, no stutter, no special handling required
```

### Pattern 1: Refocus Handler with Fast-Forward
**What:** Hook into FocusManager to trigger fast-forward when visibility changes from hidden to visible
**When to use:** When player returns from backgrounded state
**Example:**
```javascript
// In pyodide_multiplayer_game.js - extend _handleWorkerTick or add visibility listener

// Option A: Check on first tick after refocus
_handleWorkerTick(timestamp) {
    // Existing early returns...

    // NEW: Check if we just refocused and need to catch up
    if (this.focusManager && this._needsFastForward) {
        this._needsFastForward = false;
        await this._performFastForward();
        // Continue to normal tick after fast-forward complete
    }

    // Normal tick processing...
}

// Called from FocusManager's _onForegrounded callback
_onRefocus() {
    this._needsFastForward = true;
}
```

### Pattern 2: Batch Frame Processing (Fast-Forward Core)
**What:** Process multiple frames in a single synchronous batch without rendering
**When to use:** During fast-forward after refocus
**Example:**
```javascript
// Source: Adapted from existing performRollback() pattern
async _performFastForward() {
    const bufferedInputs = this.focusManager.drainBufferedInputs();
    if (bufferedInputs.length === 0) {
        p2pLog.debug('Refocus: no buffered inputs to process');
        return;
    }

    p2pLog.info(`Fast-forward: processing ${bufferedInputs.length} buffered inputs`);
    const startTime = performance.now();

    // 1. Inject buffered inputs into GGPO input buffer
    for (const packet of bufferedInputs) {
        // Packets have format: {playerId, inputs, currentFrame}
        // Each 'inputs' array contains [{action, frame}, ...] from redundant sending
        for (const input of packet.inputs) {
            this.storeRemoteInput(packet.playerId, input.action, input.frame);
        }
    }

    // 2. Determine how far behind we are
    // The last buffered packet tells us the partner's frame at time of receipt
    const lastPacket = bufferedInputs[bufferedInputs.length - 1];
    const targetFrame = Math.max(
        lastPacket.currentFrame,
        ...bufferedInputs.flatMap(p => p.inputs.map(i => i.frame))
    );

    const framesToProcess = targetFrame - this.frameNumber;
    if (framesToProcess <= 0) {
        p2pLog.debug('Already caught up or ahead');
        return;
    }

    // 3. Fast-forward: step without rendering
    // Re-use existing rollbackInProgress guard to prevent nested operations
    const wasInRollback = this.rollbackInProgress;
    this.rollbackInProgress = true;

    try {
        for (let f = 0; f < framesToProcess && this.frameNumber < targetFrame; f++) {
            // Build actions for this frame (same as normal step but skip rendering)
            const humanPlayerIds = this._getHumanPlayerIds();
            const inputs = this.getInputsForFrame(this.frameNumber, humanPlayerIds, true);

            const finalActions = this._buildFinalActions(inputs, humanPlayerIds);

            // Step environment without render
            await this.stepWithActions(finalActions);

            // Track in action sequence
            this.actionSequence.push({
                frame: this.frameNumber,
                actions: {...finalActions}
            });

            this.frameNumber++;

            // Prune periodically during fast-forward
            if (f % 10 === 0) {
                this.pruneInputBuffer();
            }
        }
    } finally {
        this.rollbackInProgress = wasInRollback;
    }

    const elapsed = performance.now() - startTime;
    p2pLog.info(`Fast-forward complete: ${framesToProcess} frames in ${elapsed.toFixed(1)}ms`);

    // 4. Now render current state
    // Normal tick will render on next cycle
}
```

### Pattern 3: Partner Experience (No Changes Needed)
**What:** Focused partner continues normally while other player is backgrounded
**When to use:** Default behavior - partner's game loop is unaffected
**Example:**
```javascript
// PARTNER SIDE - No special code needed!
// When backgrounded player tabs away:
// - Backgrounded player sends defaultAction via P2P (or stops sending, uses prediction)
// - Partner receives inputs and steps normally
// - Partner sees backgrounded player "go idle" (defaultAction = no movement/no interaction)
//
// This is already implemented in Phase 25:
// - _handleInputPacket buffers when isBackgrounded
// - Local input in step() uses defaultAction when backgrounded
// - P2P sends continue (partner gets idle inputs)
```

### Pattern 4: Panic/Limit for Long Background Periods
**What:** Cap fast-forward frames to prevent browser freeze on very long absences
**When to use:** When background duration could exceed reasonable limits
**Example:**
```javascript
// Source: Adapted from idle game loop panic pattern (GitHub gist)
const MAX_FAST_FORWARD_FRAMES = 300;  // ~30 seconds at 10fps
const MAX_FAST_FORWARD_MS = 1000;     // Max 1 second of processing

async _performFastForward() {
    // ... input injection ...

    let framesProcessed = 0;
    const startTime = performance.now();

    while (this.frameNumber < targetFrame) {
        // Safety limits
        if (framesProcessed >= MAX_FAST_FORWARD_FRAMES) {
            p2pLog.warn(`Fast-forward limit reached: ${framesProcessed} frames`);
            break;
        }

        if (performance.now() - startTime > MAX_FAST_FORWARD_MS) {
            p2pLog.warn(`Fast-forward time limit reached: ${performance.now() - startTime}ms`);
            break;
        }

        await this._stepOneFrame();
        framesProcessed++;
    }

    // If we didn't fully catch up, remaining frames will be processed
    // in subsequent normal ticks (gradual catch-up)
}
```

### Anti-Patterns to Avoid

- **Pausing partner's game loop:** Partner must never wait for backgrounded player - defeats the purpose
- **Discarding buffered inputs:** Causes state desync between peers
- **Rendering during fast-forward:** Unnecessary overhead, slows catch-up
- **Blocking main thread too long:** Could cause browser "page unresponsive" warning
- **Triggering rollbacks during fast-forward:** Already have correct inputs, no prediction errors
- **Fast-forwarding past partner's current frame:** Can't process frames partner hasn't sent yet

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Frame stepping without render | New step function | Existing `stepWithActions()` | Already works, just don't render result |
| Input buffer injection | Custom storage | Existing `storeRemoteInput()` | Handles deduplication, frame tracking |
| Timing during background | Main thread timer | Existing Web Worker timer | Already tracks elapsed time accurately |
| Visibility detection | Custom events | Existing `FocusManager` | Already has `_onForegrounded` hook |

**Key insight:** Fast-forward is mechanically identical to rollback replay - both step through multiple frames without rendering. The difference is the source of inputs (buffered partner inputs vs corrected inputs in buffer).

## Common Pitfalls

### Pitfall 1: Browser Freeze on Long Fast-Forward
**What goes wrong:** Processing thousands of frames blocks main thread, browser shows "page unresponsive"
**Why it happens:** No limit on frames to process in one batch
**How to avoid:** Cap frames per batch (e.g., 300 frames = 30s at 10fps), cap total time (e.g., 1 second)
**Warning signs:** Browser warning dialogs, frozen UI during fast-forward

### Pitfall 2: Fast-Forwarding Past Partner's Frame
**What goes wrong:** Trying to step to a frame the partner hasn't reached yet
**Why it happens:** Using buffered input's `currentFrame` as target instead of max confirmed frame
**How to avoid:** Target frame should be max of buffered frame numbers, not partner's current frame
**Warning signs:** Predictions needed during fast-forward, rollbacks immediately after

### Pitfall 3: Nested Rollback During Fast-Forward
**What goes wrong:** storeRemoteInput triggers rollback while fast-forwarding
**Why it happens:** Late input detection fires even though we're injecting buffered inputs
**How to avoid:** Set `rollbackInProgress = true` during fast-forward (same as performRollback)
**Warning signs:** Recursive calls to performRollback, stack overflow

### Pitfall 4: Partner Stutter When Other Player Refocuses
**What goes wrong:** Partner experiences frame skip or lag when backgrounded player returns
**Why it happens:** Some code path pauses partner or waits for sync
**How to avoid:** Partner's game loop is completely independent - no synchronization points
**Warning signs:** Partner reports stutter coinciding with other player's tab switch

### Pitfall 5: Input Buffer Overflow During Long Background
**What goes wrong:** Input buffer pruning deletes inputs needed for fast-forward
**Why it happens:** Pruning runs on partner's side, deleting old frames before backgrounded player uses them
**How to avoid:** Keep more history when a player is backgrounded, or disable pruning for backgrounded player's inputs
**Warning signs:** Missing inputs during fast-forward, fallback to prediction

### Pitfall 6: Action Sequence Corruption
**What goes wrong:** actionSequence has gaps or duplicates after fast-forward
**Why it happens:** Fast-forward doesn't record actions the same way as normal stepping
**How to avoid:** Record actions in actionSequence during fast-forward (same as normal step)
**Warning signs:** Desync detection fires incorrectly, action counts don't match

## Code Examples

### Complete Fast-Forward Integration
```javascript
// Source: Synthesized from existing GGPO and FocusManager patterns

// 1. Hook into FocusManager's foregrounded callback
// In MultiplayerPyodideGame constructor or init:
this.focusManager._onForegrounded = () => {
    this._pendingFastForward = true;
    p2pLog.info('Tab foregrounded - scheduling fast-forward');
};

// 2. Check for pending fast-forward at start of each tick
// In _handleWorkerTick:
_handleWorkerTick(timestamp) {
    if (this.state === 'done') return;
    if (this.reconnectionState.isPaused) return;

    // Phase 26: Fast-forward on refocus before normal tick
    if (this._pendingFastForward && !this.focusManager.isBackgrounded) {
        this._pendingFastForward = false;
        this._performFastForward();  // Synchronous or await if needed
        // Continue to normal tick after - don't return
    }

    // Phase 25: Skip when backgrounded (existing code)
    if (this.focusManager && this.focusManager.isBackgrounded) {
        // existing logging...
        return;
    }

    // Normal tick processing...
}

// 3. The fast-forward implementation
async _performFastForward() {
    const buffered = this.focusManager.drainBufferedInputs();
    if (buffered.length === 0) {
        return;
    }

    const startTime = performance.now();
    const startFrame = this.frameNumber;

    // Inject inputs
    let maxFrame = this.frameNumber;
    for (const packet of buffered) {
        for (const input of packet.inputs) {
            this.storeRemoteInput(packet.playerId, input.action, input.frame);
            maxFrame = Math.max(maxFrame, input.frame);
        }
    }

    const framesToProcess = maxFrame - this.frameNumber;
    if (framesToProcess <= 0) {
        return;
    }

    // Guard against nested operations
    this.rollbackInProgress = true;

    // Fast-forward frames
    const MAX_FRAMES = 300;
    const MAX_MS = 1000;
    let framesProcessed = 0;

    try {
        while (this.frameNumber < maxFrame &&
               framesProcessed < MAX_FRAMES &&
               (performance.now() - startTime) < MAX_MS) {

            const humanPlayerIds = this._getHumanPlayerIds();
            const inputs = this.getInputsForFrame(this.frameNumber, humanPlayerIds, true);

            // Build final actions (simplified - adapt from step())
            const finalActions = {};
            for (const [agentId, policy] of Object.entries(this.policyMapping)) {
                if (policy === 'human') {
                    finalActions[agentId] = inputs[String(agentId)] ?? this.defaultAction;
                } else {
                    // Bot: use default or last known action
                    finalActions[agentId] = this.lastExecutedActions[agentId] ?? this.defaultAction;
                }
            }

            // Step without render
            await this.stepWithActions(finalActions);

            // Record in sequence
            this.actionSequence.push({
                frame: this.frameNumber,
                actions: {...finalActions}
            });

            this.frameNumber++;
            framesProcessed++;

            // Periodic cleanup
            if (framesProcessed % 20 === 0) {
                this.pruneInputBuffer();
            }
        }
    } finally {
        this.rollbackInProgress = false;
    }

    const elapsed = performance.now() - startTime;
    p2pLog.warn(
        `FAST-FORWARD: ${startFrame} -> ${this.frameNumber} ` +
        `(${framesProcessed} frames in ${elapsed.toFixed(1)}ms)`
    );
}

// 4. Helper to get human player IDs (may already exist)
_getHumanPlayerIds() {
    return Object.entries(this.policyMapping)
        .filter(([_, policy]) => policy === 'human')
        .map(([id, _]) => String(id));
}
```

### Input Buffer During Background (Already Implemented)
```javascript
// Phase 25 already buffers inputs - just verify format matches expectations

// In _handleInputPacket when backgrounded (existing code):
if (this.focusManager && this.focusManager.isBackgrounded) {
    this.focusManager.bufferInput({
        playerId: playerId,
        inputs: packet.inputs,      // [{action, frame}, ...]
        currentFrame: packet.currentFrame
    });
    p2pLog.debug(`Buffered input from player ${playerId} (backgrounded)`);
    return;
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pause both players on tab switch | Only pause backgrounded player | Best practice for multiplayer | Partner continues playing |
| Discard time when backgrounded | Fast-forward to catch up | Idle game patterns | Maintains simulation consistency |
| Synchronous catch-up | Async with limits | Browser UX requirements | Prevents freeze |
| Full game replay | Incremental fast-forward | GGPO patterns | Uses existing input buffer |

**Current approach for browser multiplayer games:**
- Player who tabs away goes idle (default action)
- Partner continues playing, sees other player idle
- On refocus, backgrounded player catches up via fast-forward
- No mutual pause unless both players are in critical section

## Open Questions

1. **Bot actions during fast-forward**
   - What we know: Bots are deterministic given RNG state
   - What's unclear: Should bots use recorded actions or recompute?
   - Recommendation: Use `defaultAction` for bots during fast-forward (simpler), OR record bot actions in buffered packets (complex)

2. **Snapshot during fast-forward**
   - What we know: Normal step saves snapshot every N frames
   - What's unclear: Should fast-forward save snapshots?
   - Recommendation: Skip snapshots during fast-forward (performance), existing snapshots before background are sufficient

3. **Hash computation during fast-forward**
   - What we know: Hash only computed for confirmed frames
   - What's unclear: Should fast-forward frames be hashed?
   - Recommendation: Skip hashing during fast-forward, hash only on next normal tick after caught up

4. **Gradual vs immediate catch-up**
   - What we know: Batch is simpler but may spike CPU
   - What's unclear: Whether users will notice the spike
   - Recommendation: Start with immediate batch (up to limit), add gradual catch-up if needed

## Sources

### Primary (HIGH confidence)
- Existing codebase: `pyodide_multiplayer_game.js` - FocusManager, performRollback, storeRemoteInput
- [Phase 24 Research](/Users/chasemcd/Repositories/interactive-gym/.planning/phases/24-web-worker-timer/24-RESEARCH.md) - Web Worker timer patterns
- [Phase 3 Research](/Users/chasemcd/Repositories/interactive-gym/.planning/phases/03-ggpo-p2p-integration/03-RESEARCH.md) - GGPO rollback patterns
- [GGPO Developer Guide](https://github.com/pond3r/ggpo/blob/master/doc/DeveloperGuide.md) - Deterministic simulation, rollback

### Secondary (MEDIUM confidence)
- [Idle Game Loop Gist](https://gist.github.com/HipHopHuman/3e9b4a94b30ac9387d9a99ef2d29eb1a) - Catch-up and panic patterns
- [JavaScript Game Loops](https://isaacsukin.com/news/2015/01/detailed-explanation-javascript-game-loops-and-timing) - Batch processing multiple frames
- [Jake Gordon Game Loop](https://jakesgordon.com/writing/javascript-game-foundations-the-game-loop/) - Fixed timestep with catch-up

### Tertiary (LOW confidence)
- WebSearch on multiplayer idle detection - General patterns, not codebase-specific

## Metadata

**Confidence breakdown:**
- Fast-forward mechanism: HIGH - Direct adaptation of existing performRollback pattern
- Input buffering: HIGH - Already implemented in Phase 25
- Partner experience: HIGH - No changes needed, partner already unaffected
- Limits/panic: MEDIUM - Based on idle game patterns, may need tuning

**Research date:** 2026-01-23
**Valid until:** 60 days (patterns are stable, implementation is codebase-specific)
