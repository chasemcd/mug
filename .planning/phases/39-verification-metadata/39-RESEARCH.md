# Phase 39: Verification & Metadata - Research

**Researched:** 2026-01-30
**Domain:** Per-frame metadata tracking and offline validation tooling
**Confidence:** HIGH

## Summary

Phase 39 adds metadata to track which frames were speculative and provides tooling to compare player exports. The research confirms this is additive metadata work building directly on Phase 36-38 infrastructure.

The codebase already has:
1. Rollback event tracking (`sessionMetrics.rollbacks.events`) with frame ranges
2. A validation script (`scripts/validate_action_sequences.py`) that compares paired player CSVs
3. Dual-buffer architecture where frames move from speculative to canonical

The phase requires:
1. Adding `wasSpeculative` flag to frame data when frames are promoted from speculative buffer
2. Including rollback metadata in exports (already partially exists in `sessionMetrics`)
3. Extending the existing validation script to compare two specific export files

**Primary recommendation:** Extend existing `_promoteConfirmedFrames()` to mark promoted frames as `wasSpeculative: true`, include `sessionMetrics.rollbacks` in export data, and add a compare mode to the existing validation script.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | 2.x | DataFrame comparison | Already used in validation script |
| argparse | stdlib | CLI argument parsing | Already used in validation script |
| csv | stdlib | CSV parsing | Already used in validation script |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| msgpack | existing | Binary data encoding | Already used for episode export |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom comparison | datacompy | Overkill for row-by-row CSV comparison |
| JSON diff libraries | pandas.compare | Already have pandas-based script |

**Installation:**
```bash
# No new dependencies needed - all libraries already in use
```

## Architecture Patterns

### Existing Data Flow
```
storeFrameData(frame, data)
        |
        v
speculativeFrameData.set(frame, data)
        |
[confirmedFrame advances]
        |
        v
_promoteConfirmedFrames():
  frameDataBuffer.set(frame, data)  // <-- Add wasSpeculative flag here
  delete speculativeFrameData
        |
[episode ends]
        |
        v
exportEpisodeDataFromBuffer()
        |
        v
_emitEpisodeDataFromBuffer() -> emit_episode_data
```

### Pattern 1: Metadata Propagation at Promotion
**What:** Add metadata when moving frames from speculative to canonical buffer
**When to use:** When data needs to carry provenance information
**Example:**
```javascript
// In _promoteConfirmedFrames()
for (const [frame, data] of this.speculativeFrameData.entries()) {
    if (frame <= this.confirmedFrame) {
        // Mark as was-speculative when promoting
        this.frameDataBuffer.set(frame, {
            ...data,
            wasSpeculative: true  // This frame was predicted before confirmation
        });
        promoted.push(frame);
    }
}
```

### Pattern 2: Rollback Metadata per Frame
**What:** Track which frames were affected by each rollback event
**When to use:** When researchers need to know rollback impact per frame
**Example:**
```javascript
// Existing rollback event structure in sessionMetrics.rollbacks.events:
{
    frame: 150,           // Frame where misprediction occurred
    currentFrame: 157,    // Frame when rollback triggered
    rollbackFrames: 7,    // Depth of rollback
    playerId: "1",
    predictedAction: 3,
    actualAction: 2,
    timestamp: 1706631234567
}

// Export includes per-frame rollback count derived from events:
// Frame N's rollbackCount = count of events where frame >= event.frame && frame < event.currentFrame
```

### Pattern 3: Offline Comparison Script
**What:** CLI tool that takes two export files and reports differences
**When to use:** Post-experiment validation of data parity
**Example:**
```bash
# Usage pattern matching existing script
python scripts/compare_player_exports.py file1.csv file2.csv --verbose
```

### Anti-Patterns to Avoid
- **Modifying storeFrameData():** Don't add wasSpeculative at store time - it's always speculative then
- **Creating new export format:** Extend existing CSV format, don't create parallel format
- **Duplicating validation logic:** Extend existing script, don't create second validation tool

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSV comparison | Custom diff logic | Existing validate_action_sequences.py | Already handles paired files, row comparison |
| Rollback event tracking | New tracking system | sessionMetrics.rollbacks.events | Already captures frame, depth, timestamp |
| Per-frame metadata | Complex state machine | Promotion-time flagging | Simple flag at existing promotion point |

**Key insight:** The infrastructure for all three requirements already exists. REC-04 adds a flag during promotion, EDGE-03 exports existing sessionMetrics, VERIFY-01 extends an existing script.

## Common Pitfalls

### Pitfall 1: Overcomplicating wasSpeculative Tracking
**What goes wrong:** Trying to track "was ever predicted" requires historical state
**Why it happens:** Frames can be predicted, confirmed, rolled back, replayed
**How to avoid:** Simply mark ALL frames promoted from speculative buffer as wasSpeculative=true. Direct execution (no prediction) stores directly to frameDataBuffer via boundary promotion.
**Warning signs:** Code that checks predictedFrames history or action sequence

### Pitfall 2: Per-Frame Rollback Count Calculation Overhead
**What goes wrong:** Calculating rollback count per frame during step() adds overhead
**Why it happens:** Desire for real-time metadata
**How to avoid:** Calculate per-frame rollback counts at export time from rollback events. Events already have frame ranges.
**Warning signs:** Adding rollbackCount field to storeFrameData() calls

### Pitfall 3: Validation Script Scope Creep
**What goes wrong:** Building complex statistical analysis instead of simple divergence detection
**Why it happens:** Existing script has plotting and reward analysis
**How to avoid:** VERIFY-01 needs simple comparison: "are these two files identical?" Create focused compare function.
**Warning signs:** Adding matplotlib, statistics beyond simple counts

### Pitfall 4: Forgetting Episode Boundary Promotion
**What goes wrong:** Frames promoted via _promoteRemainingAtBoundary() don't get wasSpeculative flag
**Why it happens:** Different promotion path (boundary vs normal)
**How to avoid:** Both promotion methods must set wasSpeculative: true for frames from speculativeFrameData
**Warning signs:** Episodes ending with rollback lag show wasSpeculative=false for late frames

## Code Examples

### Current Frame Data Storage (storeFrameData)
```javascript
// Source: pyodide_multiplayer_game.js lines 3603-3612
storeFrameData(frameNumber, data) {
    this.speculativeFrameData.set(frameNumber, {
        actions: data.actions,
        rewards: data.rewards,
        terminateds: data.terminateds,
        truncateds: data.truncateds,
        infos: data.infos,
        isFocused: data.isFocused,
        timestamp: Date.now()
    });
}
```

### Current Promotion (no wasSpeculative yet)
```javascript
// Source: pyodide_multiplayer_game.js lines 2966-2981
_promoteConfirmedFrames() {
    const promoted = [];
    for (const [frame, data] of this.speculativeFrameData.entries()) {
        if (frame <= this.confirmedFrame) {
            this.frameDataBuffer.set(frame, data);
            promoted.push(frame);
        }
    }
    for (const frame of promoted) {
        this.speculativeFrameData.delete(frame);
    }
}
```

### Current Rollback Event Structure
```javascript
// Source: pyodide_multiplayer_game.js lines 4169-4185
const rollbackEvent = {
    frame: frameNumber,
    currentFrame: this.frameNumber,
    rollbackFrames: rollbackFrames,
    playerId: playerIdStr,
    predictedAction: usedAction,
    actualAction: action,
    timestamp: Date.now()
};
this.sessionMetrics.rollbacks.events.push(rollbackEvent);
```

### Existing Validation Script Structure
```python
# Source: scripts/validate_action_sequences.py lines 177-227
def validate_pair(
    subject_a: str, rows_a: list[dict], file_a: str,
    subject_b: str, rows_b: list[dict], file_b: str,
    verbose: bool = False
) -> tuple[bool, list[str], dict]:
    """Validate that two paired players have identical action sequences."""
    errors = []
    # Compare columns: actions, rewards, terminateds, truncateds, t
    # Returns (is_valid, errors, mismatch_counts)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single frameDataBuffer | Dual-buffer (speculative + canonical) | Phase 36 | Enables wasSpeculative tracking |
| No rollback telemetry | sessionMetrics.rollbacks.events | Pre-existing | Rollback metadata already captured |
| Manual file comparison | validate_action_sequences.py | Pre-existing | Foundation for VERIFY-01 |

**No deprecated patterns apply** - this phase is purely additive metadata.

## Open Questions

1. **Export Format for wasSpeculative**
   - What we know: Need to add wasSpeculative to export
   - What's unclear: Should it be per-frame column in CSV or in metadata JSON?
   - Recommendation: Add as column `wasSpeculative.{agentId}` to match existing pattern

2. **Rollback Count Per Frame Granularity**
   - What we know: sessionMetrics.rollbacks.events has frame ranges
   - What's unclear: Does EDGE-03 want total rollbacks affecting each frame, or just presence?
   - Recommendation: Compute per-frame rollback count from events at export time

3. **Validation Script Mode**
   - What we know: Existing script validates all pairs in directory
   - What's unclear: Should VERIFY-01 mode be same script with flag or separate script?
   - Recommendation: Add `--compare file1 file2` mode to existing script

## Implementation Approach

### REC-04: wasSpeculative Metadata
1. Modify `_promoteConfirmedFrames()` to add `wasSpeculative: true` to promoted frames
2. Modify `_promoteRemainingAtBoundary()` to add `wasSpeculative: true` to boundary-promoted frames
3. Modify `exportEpisodeDataFromBuffer()` to include wasSpeculative in output

### EDGE-03: Rollback Event Metadata
1. `sessionMetrics.rollbacks` already exists with events array
2. Add to export: either include raw events or compute per-frame count
3. Per-frame count: for each frame in episode, count events where `event.frame <= frame < event.currentFrame`

### VERIFY-01: Offline Validation Script
1. Add compare mode to `scripts/validate_action_sequences.py`
2. Accept two file paths directly (not directory scan)
3. Report: row count, column-by-column differences, first N divergent rows
4. Return exit code: 0 if identical, 1 if different

## Sources

### Primary (HIGH confidence)
- Codebase: `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - storeFrameData(), _promoteConfirmedFrames(), _promoteRemainingAtBoundary(), sessionMetrics.rollbacks
- Codebase: `scripts/validate_action_sequences.py` - existing validation script structure
- Codebase: `.planning/phases/36-buffer-split/36-01-SUMMARY.md` - dual-buffer architecture decisions
- Codebase: `.planning/phases/37-fast-forward-fix/37-01-SUMMARY.md` - promotion flow
- Codebase: `.planning/phases/38-episode-boundary/38-01-SUMMARY.md` - boundary promotion

### Secondary (MEDIUM confidence)
- [pandas.DataFrame.compare](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.compare.html) - DataFrame comparison method
- [DataComPy documentation](https://capitalone.github.io/datacompy/) - Alternative DataFrame comparison library

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already in use
- Architecture: HIGH - extends existing patterns from Phase 36-38
- Pitfalls: HIGH - based on code review of existing implementation

**Research date:** 2026-01-30
**Valid until:** 2026-03-01 (stable - no external dependencies)
