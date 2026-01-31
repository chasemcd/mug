# Architecture Research: Rollback Netcode Data Collection

**Domain:** P2P rollback netcode data collection for research export
**Researched:** 2026-01-30
**Confidence:** HIGH (based on codebase analysis + GGPO principles)

## Executive Summary

The current implementation has a well-structured `frameDataBuffer` mechanism that correctly handles rollback data correction. However, analysis reveals the **fast-forward path bypasses the confirmation check**, and data is recorded based on **frame execution** rather than **frame confirmation**. This creates the divergence problem: both peers record the same frames but potentially with different speculative values before correction propagates.

The key architectural insight: **Data should only be exported for confirmed frames** - frames where ALL players' inputs have been received and the state is deterministically identical on both peers.

## Data Collection Architecture

### Current Flow (Problematic)

```
                         PEER A                                    PEER B
                           |                                          |
  Frame N tick  ------>  step()                                    step()  <------ Frame N tick
                           |                                          |
                     [speculative]                               [speculative]
                      local input                                 local input
                      predicted partner                           predicted partner
                           |                                          |
                     storeFrameData(N)  <--- PROBLEM --->   storeFrameData(N)
                     (may use prediction)                   (may use prediction)
                           |                                          |
                       frameNumber++                              frameNumber++
                           |                                          |
               [late input arrives]                       [late input arrives]
                           |                                          |
                     performRollback()                          performRollback()
                           |                                          |
                     clearFrameData(N)                          clearFrameData(N)
                     replay + re-store                          replay + re-store
                           |                                          |
                    Episode ends -----> EXPORT <--------- Episode ends
                                        (both export corrected data)

  PROBLEM: Fast-forward path does NOT use confirmation check
           Background player exports frames with isFocused=false
           but data may still diverge due to timing
```

### The Core Issue

1. **Speculative Storage**: `storeFrameData()` is called in `step()` BEFORE confirmation is verified
2. **Rollback Corrects It**: `performRollback()` properly clears and re-stores data
3. **Fast-Forward Gap**: `_performFastForward()` stores data without rollback-style correction
4. **Export Timing**: Episode ends export from `frameDataBuffer` - but timing determines what's "final"

### Recommended Flow

```
                         PEER A                                    PEER B
                           |                                          |
  Frame N tick  ------>  step()                                    step()  <------ Frame N tick
                           |                                          |
                     [speculative step]                         [speculative step]
                           |                                          |
                     speculativeBuffer[N]                       speculativeBuffer[N]
                     (temporary storage)                        (temporary storage)
                           |                                          |
               [inputs exchange + confirm]               [inputs exchange + confirm]
                           |                                          |
                     _updateConfirmedFrame()                    _updateConfirmedFrame()
                           |                                          |
              confirmedFrame >= N?  ----------------------> confirmedFrame >= N?
                     YES                                           YES
                           |                                          |
                     promoteToCanonical(N)                     promoteToCanonical(N)
                     frameDataBuffer[N] =                      frameDataBuffer[N] =
                       speculativeBuffer[N]                      speculativeBuffer[N]
                           |                                          |
                    Episode ends -----> EXPORT <--------- Episode ends
                         (only confirmed data)              (only confirmed data)
                         GUARANTEED PARITY                  GUARANTEED PARITY
```

### Key Insight

**The architectural change needed:** Separate "speculative recording" from "canonical history."

Current code conflates these - `frameDataBuffer` holds both speculative and confirmed data, relying on rollback to correct errors. This works for rollback scenarios but fails for:

1. Fast-forward (bulk processing without rollback correction)
2. Episode boundaries (export happens at arbitrary confirmation points)
3. Focus divergence (one peer backgrounds, their data differs until sync)

## Component Responsibilities

| Component | Current Responsibility | Recommended Change |
|-----------|------------------------|-------------------|
| `frameDataBuffer` | Stores all frame data, corrected on rollback | Store ONLY confirmed frames |
| `storeFrameData()` | Called after every step | Call only when frame confirmed |
| `clearFrameDataFromRollback()` | Clears frames >= target | Keep as safety valve |
| `_updateConfirmedFrame()` | Tracks confirmation, triggers hash | ALSO trigger data promotion |
| `exportEpisodeDataFromBuffer()` | Exports frameDataBuffer contents | No change (buffer now clean) |
| NEW: `speculativeData` | N/A | Temporary storage for unconfirmed frames |

### Component Ownership

```
                    +------------------+
                    |  Game Loop       |
                    |  (step())        |
                    +--------+---------+
                             |
             +---------------+---------------+
             |                               |
    +--------v---------+          +----------v----------+
    | Speculative      |          | Confirmation        |
    | Layer            |          | Layer               |
    +------------------+          +---------------------+
    | - speculativeData|          | - confirmedFrame    |
    | - predictions    |          | - inputBuffer       |
    | - temp rewards   |          | - hashHistory       |
    +--------+---------+          +----------+----------+
             |                               |
             |    Frame confirmed?           |
             +----------+--------------------+
                        |
               +--------v--------+
               | Canonical       |
               | History         |
               +-----------------+
               | - frameDataBuffer|  <-- Only confirmed
               | - actionSequence|
               | - cumulativeValid|
               +-----------------+
                        |
               +--------v--------+
               | Export Layer    |
               +-----------------+
               | - emitEpisodeData|
               | - validation data|
               +-----------------+
```

## Recording Points

### When to Record

| Event | Record to Speculative? | Promote to Canonical? | Rationale |
|-------|------------------------|----------------------|-----------|
| Speculative step | YES | NO | Need data for potential rollback replay |
| Post-rollback step | YES (replaces) | NO | Corrected data, but may rollback again |
| Frame confirmed | N/A | YES | All inputs received, state is final |
| Fast-forward step | YES | NO | Bulk processing, needs confirmation check |
| Episode end | N/A | Promote remaining | Force-confirm at boundary |

### Frame Confirmation Logic

A frame N is "confirmed" when:
1. ALL human players have inputs in `inputBuffer.get(N)`
2. Frame N <= `confirmedFrame` (monotonically increasing)
3. No rollback is in progress (`!rollbackInProgress`)

Current code in `_hasAllInputsForFrame()` and `_updateConfirmedFrame()` correctly implements this.

### Canonical History Buffer Structure

```javascript
// NEW: Speculative buffer (temporary, may be overwritten)
this.speculativeFrameData = new Map();  // frameNumber -> {actions, rewards, ...}

// EXISTING: Canonical buffer (only confirmed, exported)
this.frameDataBuffer = new Map();  // frameNumber -> {actions, rewards, ...}

// Promotion happens in _updateConfirmedFrame():
async _updateConfirmedFrame() {
    // ... existing confirmation logic ...

    for (let frame = startFrame; frame < this.frameNumber; frame++) {
        if (this._hasAllInputsForFrame(frame, humanPlayerIds)) {
            this.confirmedFrame = frame;

            // NEW: Promote speculative data to canonical
            if (this.speculativeFrameData.has(frame)) {
                this.frameDataBuffer.set(frame, this.speculativeFrameData.get(frame));
                this.speculativeFrameData.delete(frame);
            }

            // Existing: hash computation
            await this._computeAndStoreConfirmedHash(frame);
        } else {
            break;
        }
    }
}
```

## Data Flow Patterns

### Pattern 1: Speculative-Then-Confirm

**What:** Store data speculatively on step, promote to canonical on confirmation.

**When to use:** Normal gameplay flow where inputs arrive within a few frames.

**Trade-offs:**
- (+) Simple mental model
- (+) Works with existing rollback flow
- (-) Requires two buffers
- (-) Must handle promotion timing carefully

```javascript
// In step():
this.speculativeFrameData.set(this.frameNumber, {
    actions: finalActions,
    rewards: Object.fromEntries(rewards),
    // ...
});

// In _updateConfirmedFrame():
if (this._hasAllInputsForFrame(frame, humanPlayerIds)) {
    // Promote to canonical
    this.frameDataBuffer.set(frame, this.speculativeFrameData.get(frame));
}
```

### Pattern 2: Delayed Recording

**What:** Don't record at step time. Record only when confirmed.

**When to use:** When memory is tight and most frames confirm quickly.

**Trade-offs:**
- (+) Single buffer, simpler
- (-) Must re-extract data from actionSequence/rewards on confirmation
- (-) Loses per-frame timing information

```javascript
// In step(): Don't store to frameDataBuffer

// In _updateConfirmedFrame():
if (this._hasAllInputsForFrame(frame, humanPlayerIds)) {
    // Reconstruct data from actionSequence
    const record = this.actionSequence.find(r => r.frame === frame);
    this.frameDataBuffer.set(frame, {
        actions: record.actions,
        // Must track rewards separately...
    });
}
```

### Pattern 3: Force-Confirm at Boundaries

**What:** At episode end, force all remaining speculative frames to confirmed.

**When to use:** Episode boundaries where determinism is guaranteed by sync.

**Trade-offs:**
- (+) Ensures complete data export
- (+) Handles edge cases at boundaries
- (-) May include frames with prediction (though rare at boundary)

```javascript
// In signalEpisodeComplete():
// Force-promote any remaining speculative data
for (const [frame, data] of this.speculativeFrameData) {
    if (!this.frameDataBuffer.has(frame)) {
        this.frameDataBuffer.set(frame, data);
    }
}
this.speculativeFrameData.clear();

// Then export
this._emitEpisodeDataFromBuffer();
```

### Recommended Pattern: Hybrid

Use Pattern 1 (Speculative-Then-Confirm) for normal flow, with Pattern 3 (Force-Confirm at Boundaries) for episode endings:

```
Normal tick: step() -> speculativeFrameData -> _updateConfirmedFrame() -> frameDataBuffer
Episode end: force promote remaining -> export -> clear
```

## Anti-Patterns

### Anti-Pattern 1: Recording Before Inputs Are Known

**What it does:** Stores data immediately after `step()` without checking confirmation.

**Why it causes divergence:**
- Peer A may have all inputs (confirmed)
- Peer B may be using prediction (speculative)
- Both store to `frameDataBuffer`
- If no rollback occurs before export, data differs

**Current code doing this:**
```javascript
// In step(), line ~2441:
this.storeFrameData(this.frameNumber, {
    actions: finalActions,  // May include predictions!
    rewards: Object.fromEntries(rewards),
    // ...
});
```

### Anti-Pattern 2: Fast-Forward Without Confirmation Check

**What it does:** Bulk-processes frames and stores data without verifying confirmation.

**Why it causes divergence:**
- Fast-forward happens when one peer backgrounds
- That peer bulk-processes frames using buffered inputs
- No rollback correction happens (it's not a rollback, it's catch-up)
- Data may include prediction if inputs were lost

**Current code doing this:**
```javascript
// In _performFastForward(), line ~4965:
for (const frameData of ffResult.per_frame_data) {
    this.storeFrameData(frameData.frame, {
        actions: frameData.actions,
        // No confirmation check!
    });
}
```

### Anti-Pattern 3: Exporting at Episode End Without Confirmation Sync

**What it does:** Exports `frameDataBuffer` at episode end without ensuring both peers are at same confirmation point.

**Why it causes divergence:**
- Episode end is detected locally
- P2P sync ensures both peers agree on END frame
- But confirmation may lag behind current frame
- Peer A: confirmed=N-5, Peer B: confirmed=N-2
- Both export, but with different "final" data

**Mitigation in current code:** Episode sync waits for peer agreement. But this doesn't wait for confirmation to catch up.

### Anti-Pattern 4: Clearing Buffer Before Export

**What it does:** Clears `frameDataBuffer` immediately after emit, before confirmation of receipt.

**Why it causes issues:**
- If emit fails, data is lost
- No retry mechanism
- Current code does this (line ~3726)

**Better:** Mark as "pending export" and clear only after server ACK.

## Implementation Recommendations

### Phase 1: Add Speculative Buffer (Low Risk)

1. Add `speculativeFrameData` Map
2. Change `storeFrameData()` to write to speculative buffer
3. Add `promoteToCanonical()` call in `_updateConfirmedFrame()`
4. No changes to export logic (it reads from frameDataBuffer which now only has confirmed)

### Phase 2: Fix Fast-Forward Path (Medium Risk)

1. After fast-forward batch processing, call `_updateConfirmedFrame()`
2. Only promote frames that are actually confirmed
3. Handle remaining speculative frames appropriately

### Phase 3: Add Force-Confirm at Boundaries (Low Risk)

1. Before `_emitEpisodeDataFromBuffer()`, promote remaining speculative
2. Log warning if promoting unconfirmed frames (indicates sync issue)

### Phase 4: Add Export Confirmation (Optional)

1. Don't clear buffer immediately on emit
2. Wait for server ACK before clearing
3. Retry on failure

## Verification

To verify the fix works:

1. **Action Parity Test:**
   - Run two peers through episode with artificial rollbacks
   - Export data from both
   - Run `validate_action_sequences.py`
   - Should show 0 mismatches

2. **Fast-Forward Test:**
   - One peer backgrounds for 5+ seconds
   - Refocuses and fast-forwards
   - Compare exported data
   - Should show identical actions/rewards for all frames

3. **Boundary Test:**
   - Episode ends while frames still unconfirmed
   - Both peers should export identical data
   - Verify no prediction-based differences

## Sources

- [GGPO Official Documentation](https://www.ggpo.net/) - Rollback networking fundamentals
- [SnapNet: Netcode Architectures Part 2 - Rollback](https://www.snapnet.dev/blog/netcode-architectures-part-2-rollback/) - Confirmed vs speculative frames
- [Gaffer On Games: Deterministic Lockstep](https://gafferongames.com/post/deterministic_lockstep/) - Frame confirmation concepts
- [GitHub: WillKirkmanM/rollback-netcode](https://github.com/WillKirkmanM/rollback-netcode) - Confirmed frame cleanup patterns
- [GitHub: Corrade/netcode-lockstep](https://github.com/Corrade/netcode-lockstep) - P2P lockstep reference implementation
- Codebase analysis: `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/static/js/pyodide_multiplayer_game.js`
