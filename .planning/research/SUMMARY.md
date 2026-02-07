# Project Research Summary

**Project:** Interactive Gym — P2P Multiplayer
**Domain:** Rollback netcode data collection for research export parity
**Researched:** 2026-01-30
**Confidence:** HIGH

## Executive Summary

The data export parity problem has a clear root cause: **data is recorded speculatively during frame execution, before inputs are confirmed**. While the existing GGPO-style rollback system correctly clears and re-records data during rollbacks, two critical gaps remain:

1. **Fast-forward path**: When a tab is backgrounded and refocused, the fast-forward bulk processing may not follow the same confirmation-gated recording path
2. **Export timing**: Episode end exports from `frameDataBuffer` without verifying that all frames are confirmed

The fix is architecturally straightforward: **separate speculative data storage from canonical (confirmed) data storage**, and only export from the canonical buffer. The existing `confirmedFrame` tracking and `_hasAllInputsForFrame()` infrastructure already provides the confirmation mechanism — it just needs to gate data promotion.

## Key Findings

### Recommended Stack/Patterns

The codebase already implements GGPO patterns correctly. The gap is at the export boundary.

**Core concepts already in place:**
- `confirmedFrame` — highest consecutive frame with all inputs received
- `inputBuffer` — stores received inputs indexed by frame
- `stateSnapshots` — enables rollback to any recent frame
- `clearFrameDataFromRollback()` — clears speculative data on rollback

**Missing piece:**
- `speculativeFrameData` buffer — temporary storage before confirmation
- Promotion logic in `_updateConfirmedFrame()` — move data to canonical buffer only when confirmed

### Expected Features (Data Recording Rules)

**Must have (table stakes):**
- Record only CONFIRMED frames — speculative frames may use wrong inputs
- Clear speculative data on rollback — already implemented
- Re-record during replay — already implemented
- Buffer until confirmation — NEW: separate speculative from confirmed buffer
- Export from confirmed buffer only — NEW: modify export logic

**Should have (research value-add):**
- Track `wasSpeculative` per frame — understand prediction accuracy
- Include `rollbackCount` metadata — correlate with network conditions
- Hash verification status — know which frames were cryptographically verified

### Architecture Approach

**Two-buffer pattern:**

```
Frame executed → speculativeFrameData[N]
                        ↓
        _updateConfirmedFrame() promotes
                        ↓
              frameDataBuffer[N] (canonical)
                        ↓
               Episode end export
```

**Key changes needed:**
1. `storeFrameData()` writes to `speculativeFrameData` instead of `frameDataBuffer`
2. `_updateConfirmedFrame()` promotes confirmed frames to `frameDataBuffer`
3. `_performFastForward()` uses same confirmation-gated storage
4. Episode end force-confirms remaining frames before export

### Critical Pitfalls

1. **Recording speculative data as ground truth** — data recorded before confirmation may use predicted (wrong) inputs
   - *Prevention:* Only promote to export buffer after confirmation

2. **Fast-forward bulk processing without re-recording** — fast-forward may skip data recording or bypass confirmation
   - *Prevention:* Fast-forward path must mirror normal step() data recording

3. **Episode boundary masking** — desync happens late, episode ends before detection
   - *Prevention:* Final hash validation before clearing buffers

4. **Input delay temporal mismatch** — with INPUT_DELAY > 0, actions paired with wrong observations
   - *Prevention:* Record action at execution frame, not input frame

5. **Cumulative reward divergence** — rewards incremented speculatively, not restored on rollback
   - *Prevention:* Include cumulative_rewards in state snapshot (verify this)

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 36: Speculative/Canonical Buffer Split

**Rationale:** This is the core architectural fix that enables all other changes
**Delivers:** Separate `speculativeFrameData` buffer, promotion logic in `_updateConfirmedFrame()`
**Addresses:** Pitfall #1 (speculative as ground truth)
**Risk:** LOW — additive change, doesn't break existing logic

**Tasks:**
1. Add `speculativeFrameData` Map
2. Modify `storeFrameData()` to write to speculative buffer
3. Add `_promoteConfirmedFrames()` method
4. Call promotion in `_updateConfirmedFrame()`

### Phase 37: Fast-Forward Data Recording Fix

**Rationale:** Fast-forward is the main divergence source identified in research
**Delivers:** Confirmation-gated recording in `_performFastForward()`
**Addresses:** Pitfall #2 (fast-forward bulk processing)
**Uses:** Buffer split from Phase 36
**Risk:** MEDIUM — must audit fast-forward code path carefully

**Tasks:**
1. Audit `_performFastForward()` data recording
2. Ensure fast-forward writes to speculative buffer
3. Call `_updateConfirmedFrame()` after fast-forward completes
4. Verify no frame gaps in export after tab refocus

### Phase 38: Episode Boundary Confirmation

**Rationale:** Episode end is the export trigger — must ensure all data confirmed
**Delivers:** Force-confirm logic at episode end, export only from canonical buffer
**Addresses:** Pitfall #3 (episode boundary masking)
**Risk:** LOW — focused change at episode boundary

**Tasks:**
1. Add force-confirm at episode end (promote remaining speculative)
2. Wait for peer sync before exporting
3. Log warning if promoting unconfirmed frames
4. Verify both players export identical frame counts

### Phase 39: Verification & Metadata (Optional)

**Rationale:** Research value-add for understanding data quality
**Delivers:** Per-frame metadata (`wasSpeculative`, `rollbackCount`), offline validation tool
**Addresses:** "Looks synchronized but isn't" scenarios
**Risk:** LOW — additive metadata, no core logic changes

**Tasks:**
1. Add `wasSpeculative` field to frame data
2. Track rollback count per frame
3. Include hash verification status from Phase 11-14
4. Create export comparison script for validation

### Phase Ordering Rationale

- **Phase 36 first:** Buffer split is prerequisite for all other changes
- **Phase 37 second:** Fast-forward fix depends on buffer split
- **Phase 38 third:** Episode boundary depends on both being correct
- **Phase 39 optional:** Metadata adds value but not required for parity

### Research Flags

**Phases with standard patterns (minimal research needed):**
- Phase 36: Well-documented pattern from GGPO/NetplayJS
- Phase 38: Standard boundary handling

**Phases likely needing deeper review during planning:**
- Phase 37: Fast-forward code path is complex, needs careful audit

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Patterns directly from GGPO, NetplayJS, existing codebase |
| Features | HIGH | Frame state lifecycle clearly defined |
| Architecture | HIGH | Two-buffer pattern is standard, codebase analysis confirms gaps |
| Pitfalls | HIGH | All pitfalls verified against codebase implementation |

**Overall confidence:** HIGH

### Gaps to Address

- **Fast-forward code audit:** Need to trace exact data recording in `_performFastForward()` during planning
- **Episode-end sync timing:** Verify `p2pEpisodeSync` waits for confirmation, not just peer agreement

## Sources

### Primary (HIGH confidence)
- `pyodide_multiplayer_game.js` — existing GGPO implementation analysis
- [GGPO Developer Guide](https://github.com/pond3r/ggpo/blob/master/doc/DeveloperGuide.md) — canonical patterns
- [NetplayJS](https://github.com/rameshvarun/netplayjs) — TypeScript rollback reference

### Secondary (HIGH confidence)
- [SnapNet: Rollback Netcode](https://www.snapnet.dev/blog/netcode-architectures-part-2-rollback/) — confirmed vs speculative frames
- [INVERSUS Rollback Networking](https://www.gamedeveloper.com/design/rollback-networking-in-inversus) — symmetric P2P patterns

### Tertiary (MEDIUM confidence)
- [Jimmy's Blog: GGPO-style rollback](https://outof.pizza/posts/rollback/) — fixed-point arithmetic
- [Gaffer on Games: Deterministic Lockstep](https://gafferongames.com/post/deterministic_lockstep/) — input confirmation protocol

---
*Research completed: 2026-01-30*
*Ready for roadmap: yes*
