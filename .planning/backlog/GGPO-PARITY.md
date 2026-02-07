# GGPO Data Recording Parity Under Packet Loss

**Priority:** Medium
**Discovered:** Phase 74 (Stability Certification), 2026-02-06
**Test:** `tests/e2e/test_network_disruption.py::test_active_input_with_packet_loss`
**Status:** Documented, xfail marker applied, awaiting dedicated milestone

## Problem Statement

Under 15% packet loss with active inputs from both players, the two players' exported data diverges. Row counts and episode completion work correctly, but the content of action, reward, and info columns differs between the two players' exports approximately 40-50% of the time.

## Root Cause Analysis

### The Bug Chain

1. **Packet loss delays inputs:** Player 1's inputs are delayed reaching Player 2 due to 15% packet loss on the P2P DataChannel
2. **GGPO predicts missing inputs:** Player 2 predicts Player 1's action as `lastConfirmedAction` (typically the most recent confirmed input)
3. **Environment steps with wrong input:** Player 2's environment is stepped with the predicted (possibly wrong) action, producing a different game state than Player 1
4. **Rollback triggers on mismatch:** When the real input arrives, if `predictedAction !== realAction`, a rollback is triggered
5. **Rollback replays from snapshot:** The system loads the nearest state snapshot and replays forward with correct inputs
6. **Snapshot coverage is limited:** With `maxSnapshots=30` and `snapshotInterval=5`, only the last 150 frames have snapshots. For a 450-frame episode, the first 300 frames have no snapshot coverage
7. **Cascading state divergence:** If a misprediction at frame 100 is corrected by rollback to snapshot at frame 95, but frame 93 ALSO had a misprediction whose snapshot was already pruned, the replay starts from a tainted snapshot
8. **Prediction-matches-actual edge case:** When the predicted action happens to match the real action (random actions, 7 values, ~14% chance), no rollback triggers even though the game state is wrong (computed from a diverged base state from earlier mispredictions)

### What We Tried (Phase 74)

| Approach | Commit | Result |
|----------|--------|--------|
| Prune fix: only prune confirmed frames | `4238052` | **Kept.** Correct fix — prevents confirmedFrame from getting stuck |
| Boundary fix: preserve syncedTerminationFrame during export | `0cde133` | **Kept.** Correct fix — prevents extra rows in export |
| Corrective rollback at episode end | `5358b69` | **Reverted.** Snapshots too old for early mismatches; action patching fixes action columns but not obs/rewards/infos |

### Why Corrective Rollback Failed

The corrective rollback approach patches frame data at episode end:
- Detects frames where recorded action != confirmed input
- Attempts rollback from earliest mismatch
- **Fails because:** Snapshots for frame 100 are long gone by frame 450. The rollback has no valid snapshot to restore from.
- **Even if snapshot existed:** Action patching only fixes the `actions` column. The `observations`, `rewards`, and `infos` columns are computed from the game state, which diverged when the environment was stepped with wrong inputs.

## Technical Details

### Key Code Locations

- **Input buffer pruning:** `pyodide_multiplayer_game.js:5352` — `pruneInputBuffer()`
- **Input storage + rollback detection:** `pyodide_multiplayer_game.js:4397` — `storeRemoteInput()`
- **Rollback trigger condition:** `pyodide_multiplayer_game.js:4422` — `predictedFrames.has(frameNumber)`
- **Rollback execution:** `pyodide_multiplayer_game.js:4637` — `performRollback()`
- **Snapshot management:** `pyodide_multiplayer_game.js:4450` — `saveStateSnapshot()`
- **Confirmed frame tracking:** `pyodide_multiplayer_game.js:2947` — `_updateConfirmedFrame()`
- **Data promotion:** `pyodide_multiplayer_game.js:2990` — `_promoteConfirmedFrames()`

### Relevant Constants

```javascript
snapshotInterval = 5;     // Save state every 5 frames
maxSnapshots = 30;        // Keep 30 snapshots (150 frames of history)
inputBufferMaxSize = 600; // Max input buffer entries
redundancyCount = 10;     // Send last 10 inputs per packet
```

### Test Configuration

- Player 1: random actions every 150ms, no packet loss
- Player 2: random actions every 200ms, 15% packet loss + 50ms base latency
- Episode: 450 frames at 30fps (15 seconds)

## Potential Fix Approaches

### Approach A: Increase Snapshot Coverage
Increase `maxSnapshots` to cover the full episode (90 snapshots for 450 frames at interval=5). This ensures any misprediction can be corrected via rollback.
- **Pro:** Simple change, no architectural rework
- **Con:** Memory cost (~90 state snapshots per episode), may not fully solve cascading divergence
- **Estimated effort:** Small

### Approach B: Eager Rollback on Any Late Input
Change rollback trigger condition from "prediction was wrong" to "any frame that used prediction gets rolled back when real input arrives." This catches the prediction-matches-actual edge case.
- **Pro:** Catches all mispredictions regardless of action value
- **Con:** Many more rollbacks (every delayed input triggers one); performance impact
- **Estimated effort:** Medium

### Approach C: Full-Episode Corrective Replay
At episode end, when all inputs are confirmed, do a full replay from frame 0 (reset environment, replay entire episode with confirmed inputs). This guarantees identical state.
- **Pro:** Guaranteed correct data
- **Con:** Doubles episode computation time; requires saving initial state; complex to implement
- **Estimated effort:** Large

### Approach D: Server-Authoritative Data Recording
Have the server record canonical data (it sees all confirmed inputs). Peers only record local telemetry.
- **Pro:** Eliminates client-side data divergence entirely
- **Con:** Requires server to run environment; defeats P2P performance benefits
- **Estimated effort:** Large (architectural change)

### Recommended Approach
Start with **A + B combined**: increase snapshot coverage and make rollback trigger on any late input (not just mispredicted ones). This should handle most cases. If content divergence persists, escalate to **C**.

## Test Impact

- **Current:** `test_active_input_with_packet_loss` marked `xfail(strict=False)` — fails ~40-50%, passes when timing avoids rollbacks
- **After fix:** Remove xfail marker, test should pass consistently
- **Other tests:** The 23 other E2E tests are unaffected (they don't combine packet loss with active inputs)

## Fixes Already Applied (Phase 74)

These fixes are in the codebase and should NOT be reverted:

1. **Prune fix (4238052):** `pruneInputBuffer()` only prunes frames where `frame <= confirmedFrame`. Prevents confirmedFrame from getting stuck due to pruned unconfirmed inputs creating gaps in the confirmation chain.

2. **Boundary fix (0cde133):** Reordered `signalEpisodeComplete()` before `_clearEpisodeSyncState()` so that `syncedTerminationFrame` is available during export. Prevents Player 2 from exporting extra rows beyond episode boundary.

---
*Created: 2026-02-06*
*Discovered during: Phase 74 Stability Certification*
*Blocking test: test_active_input_with_packet_loss[chromium]*
