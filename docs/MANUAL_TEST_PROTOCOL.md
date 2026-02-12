# Manual Data Parity Test Protocol

A step-by-step protocol for manually verifying that both players in a P2P multiplayer game export identical game data regardless of network conditions.

## Overview

### Purpose

The dual-buffer data recording architecture ensures that both players export identical game data, even when network conditions cause rollbacks, mispredictions, or fast-forward resync events. This protocol validates that the system is working correctly.

### When to Use

- **Pre-deployment validation**: Before deploying to production
- **After code changes**: After modifying data recording, rollback handling, or export logic
- **After library updates**: After updating Pyodide, GGPO, or WebRTC libraries
- **Debugging divergences**: When automated tests fail or research data shows unexpected differences

### What This Tests

| Component | What's Validated |
|-----------|-----------------|
| Dual-buffer recording | Speculative frames don't pollute exports |
| Rollback handling | Mispredictions are corrected before export |
| Fast-forward resync | Tab focus loss recovery preserves data parity |
| Episode boundary | All frames promoted correctly at episode end |

## Prerequisites

### Software Requirements

- Two browser windows (Chrome recommended for DevTools)
- Server running locally (`python -m mug.server.app`)
- Chrome DevTools (F12 on Windows/Linux, Cmd+Option+I on macOS)

### Directory Structure

Export files are stored in the following structure:

```
data/
  {scene_id}/
    {subject_id_1}_ep{episode_num}.csv
    {subject_id_2}_ep{episode_num}.csv
```

For example:
```
data/
  cramped_room_hh/
    abc123_ep1.csv
    def456_ep1.csv
```

### Identifying Your Export Files

1. After completing a game, check the browser console for export messages
2. Look for: `[EXPORT] Saved episode {N} data to server`
3. The subject ID is visible in the URL or console logs
4. Files appear in `data/{scene_id}/` within a few seconds of episode completion

## Test Scenarios

### Scenario 1: Baseline (No Network Stress)

**Purpose:** Confirm data parity under ideal network conditions.

**Steps:**

1. Start the server:
   ```bash
   python -m mug.server.app
   ```

2. Open two browser windows to the experiment URL (e.g., `http://localhost:5001`)

3. Complete matchmaking:
   - Both windows should match and show "Partner found"

4. Complete the tutorial in both windows

5. Play through one full episode

6. Wait for episode completion:
   - Look for "Episode Complete" or similar message
   - Console should show `[EXPORT] Saved episode 1 data`

7. Locate export files:
   ```bash
   ls -la data/cramped_room_hh/
   ```

8. Run comparison:
   ```bash
   python scripts/validate_action_sequences.py --compare \
     data/cramped_room_hh/{subject1}_ep1.csv \
     data/cramped_room_hh/{subject2}_ep1.csv
   ```

**Expected Result:** `FILES ARE IDENTICAL`

---

### Scenario 2: Fixed Latency (100ms symmetric)

**Purpose:** Confirm data parity under moderate latency conditions.

**Steps:**

1. Open two browser windows to the experiment URL

2. In BOTH windows, open DevTools:
   - Press F12 or Cmd+Option+I
   - Go to Network tab
   - Click on "No throttling" dropdown

3. Apply latency to both windows:
   - Select "Slow 3G" (if available), OR
   - Click "Add..." to create custom profile:
     - Name: "100ms Latency"
     - Download: 50000 Kbps
     - Upload: 50000 Kbps
     - Latency: 100 ms

4. Complete matchmaking and tutorial

5. Play through one full episode

6. After episode completes, run comparison:
   ```bash
   python scripts/validate_action_sequences.py --compare \
     data/cramped_room_hh/{subject1}_ep1.csv \
     data/cramped_room_hh/{subject2}_ep1.csv
   ```

**Expected Result:** `FILES ARE IDENTICAL`

**Note:** The dual-buffer architecture handles the confirmation delay caused by latency. Frames are recorded speculatively and only promoted to the export buffer when confirmed.

---

### Scenario 3: Asymmetric Latency (50ms vs 200ms)

**Purpose:** Confirm data parity when players have different network latencies.

**Steps:**

1. Open two browser windows to the experiment URL

2. In Player 1 window, apply 50ms latency:
   - DevTools > Network > Custom profile with 50ms latency

3. In Player 2 window, apply 200ms latency:
   - DevTools > Network > Custom profile with 200ms latency

4. Complete matchmaking and tutorial

5. Play through one full episode

6. Run comparison:
   ```bash
   python scripts/validate_action_sequences.py --compare \
     data/cramped_room_hh/{player1}_ep1.csv \
     data/cramped_room_hh/{player2}_ep1.csv
   ```

**Expected Result:** `FILES ARE IDENTICAL`

**Why This Works:** The GGPO rollback system predicts inputs and corrects mispredictions. The dual-buffer ensures that only confirmed (post-correction) frames are exported.

---

### Scenario 4: Variable Latency (Jitter)

**Purpose:** Confirm data parity under fluctuating network latency.

**Steps:**

1. Open two browser windows to the experiment URL

2. Complete matchmaking and tutorial

3. During gameplay, manually toggle network conditions:
   - In one window's DevTools > Network:
     - Switch between "Fast 3G" and "Slow 3G" every 5-10 seconds
     - OR briefly enable "Offline" for 1 second, then restore

4. Complete the episode

5. Run comparison:
   ```bash
   python scripts/validate_action_sequences.py --compare \
     data/cramped_room_hh/{subject1}_ep1.csv \
     data/cramped_room_hh/{subject2}_ep1.csv
   ```

**Expected Result:** `FILES ARE IDENTICAL`

**Note:** Variable latency is normal in real-world conditions. The system handles it gracefully.

---

### Scenario 5: Packet Loss (Rollback Trigger)

**Purpose:** Confirm data parity after rollback scenarios.

**Steps:**

1. Open two browser windows to the experiment URL

2. Complete matchmaking and tutorial

3. During gameplay, simulate packet loss:
   - In one window's DevTools > Network:
   - Enable "Offline" for 1-2 seconds
   - Then disable "Offline" to restore connection

4. Observe rollback behavior:
   - Characters may "teleport" briefly (visual rollback correction)
   - Console may show `[ROLLBACK]` messages

5. Complete the episode

6. Run comparison with verbose output:
   ```bash
   python scripts/validate_action_sequences.py --compare \
     data/cramped_room_hh/{subject1}_ep1.csv \
     data/cramped_room_hh/{subject2}_ep1.csv \
     --verbose
   ```

**Expected Result:** `FILES ARE IDENTICAL`

**Verification Details:**
- Check the `wasSpeculative` column in the export files
- Rows that were rolled back and re-recorded will have `wasSpeculative: true`
- Both files should have the same `wasSpeculative` values

---

### Scenario 6: Tab Focus Loss (Fast-Forward Trigger)

**Purpose:** Confirm data parity after fast-forward resync.

**Steps:**

1. Open two browser windows SIDE BY SIDE (so you can see both)

2. Complete matchmaking and tutorial

3. During gameplay:
   - Click outside the Player 1 browser window (defocus it)
   - The game should show a focus loss indicator
   - Wait 5 seconds while Player 2 continues playing

4. Click back into the Player 1 browser window
   - Player 1 should "fast-forward" to catch up
   - Frame numbers may jump significantly

5. Complete the episode

6. Run comparison:
   ```bash
   python scripts/validate_action_sequences.py --compare \
     data/cramped_room_hh/{subject1}_ep1.csv \
     data/cramped_room_hh/{subject2}_ep1.csv
   ```

**Expected Result:** `FILES ARE IDENTICAL`

**Why This Works:** Fast-forward processes buffered partner inputs and advances the simulation. The dual-buffer records all frames during fast-forward, maintaining parity.

---

## Running Comparisons

### Using validate_action_sequences.py

The validation script compares two export files and reports any divergences.

#### Basic Comparison

```bash
python scripts/validate_action_sequences.py --compare file1.csv file2.csv
```

Output on success:
```
Comparing: abc123_ep1.csv vs def456_ep1.csv
======================================================================
Rows: 1800 vs 1800
Columns: 42 vs 42

FILES ARE IDENTICAL
```

#### Verbose Mode (Show Divergence Details)

```bash
python scripts/validate_action_sequences.py --compare file1.csv file2.csv --verbose
```

Output on failure:
```
Comparing: abc123_ep1.csv vs def456_ep1.csv
======================================================================
Rows: 1800 vs 1800
Columns: 42 vs 42

DIVERGENCES FOUND:
  Column 'actions.0' has 3 divergences
    Row 150: abc123_ep1.csv=2, def456_ep1.csv=0
    Row 151: abc123_ep1.csv=2, def456_ep1.csv=0
    Row 152: abc123_ep1.csv=2, def456_ep1.csv=0
```

#### Batch Comparison (Entire Directory)

To validate all pairs in a scene directory:

```bash
python scripts/validate_action_sequences.py data/cramped_room_hh
```

This automatically finds paired files and validates all episodes.

### Interpreting Results

| Exit Code | Meaning | Action |
|-----------|---------|--------|
| 0 | `FILES ARE IDENTICAL` | Pass - data parity confirmed |
| 1 | `DIVERGENCES FOUND` | Fail - investigate the issue |

### Columns Compared

The following columns are validated for exact equality:

| Column Group | Columns |
|--------------|---------|
| Actions | `actions.0`, `actions.1` |
| Rewards | `rewards.0`, `rewards.1` |
| Terminated | `terminateds.0`, `terminateds.1`, `terminateds.__all__` |
| Truncated | `truncateds.0`, `truncateds.1`, `truncateds.__all__` |
| Time | `t`, `episode_num` |

### Understanding the wasSpeculative Column

The `wasSpeculative` column indicates whether a frame was recorded from the speculative buffer before confirmation:

| Value | Meaning |
|-------|---------|
| `false` | Frame was recorded after confirmation (normal path) |
| `true` | Frame was initially speculative, then promoted after confirmation |

Both files should have identical `wasSpeculative` values. If they differ, it indicates a bug in the dual-buffer synchronization.

### Understanding rollbackEvents

The `rollbackEvents` column contains an array of rollback events that occurred before the frame was confirmed:

```json
[{"fromFrame": 150, "toFrame": 147, "mispredictedInputs": 3}]
```

This is diagnostic information. Both files should show identical rollback events.

---

## Expected Outcomes Summary

| Scenario | Expected Result | What's Being Validated |
|----------|----------------|----------------------|
| Baseline | IDENTICAL | Basic recording works correctly |
| 100ms Latency | IDENTICAL | Dual-buffer handles confirmation delay |
| Asymmetric (50ms/200ms) | IDENTICAL | GGPO rollback handles mispredictions |
| Jitter | IDENTICAL | Variable latency is handled correctly |
| Packet Loss | IDENTICAL | Rollbacks are corrected before export |
| Tab Focus Loss | IDENTICAL | Fast-forward resync preserves parity |

**Critical:** ALL scenarios should result in `FILES ARE IDENTICAL`. Any divergence indicates a bug in the data recording system.

---

## Troubleshooting

### Common Issues

#### "Files not found"

**Symptoms:**
```
Error: File not found: data/cramped_room_hh/abc123_ep1.csv
```

**Solutions:**
1. Wait longer - export files are written asynchronously after episode completion
2. Check the data directory path matches your scene
3. Verify the episode completed (look for export message in console)
4. Check server logs for export errors

#### "Row count mismatch"

**Symptoms:**
```
DIVERGENCES FOUND:
  Row count mismatch: abc123_ep1.csv has 1800 rows, def456_ep1.csv has 1795 rows
```

**Causes:**
1. One player's episode didn't complete properly
2. Network disconnection before episode boundary promotion
3. Browser tab was closed before export finished

**Solutions:**
1. Re-run the test scenario
2. Ensure both players wait for "Episode Complete" message
3. Check for error messages in browser consoles

#### "Column divergences in actions"

**Symptoms:**
```
DIVERGENCES FOUND:
  Column 'actions.0' has 15 divergences
```

**Potential Causes:**
1. **Bug in dual-buffer promotion** - speculative frames exported without confirmation
2. **Bug in rollback handling** - mispredictions not corrected
3. **Bug in fast-forward** - frames skipped or duplicated
4. **Race condition** - export triggered before final confirmation

**Investigation Steps:**
1. Run with `--verbose` to see which rows diverge
2. Check the frame numbers where divergences occur
3. Look for patterns (e.g., all divergences near a rollback event)
4. Check browser console logs for relevant events

### Collecting Debug Information

When reporting a divergence bug, collect:

1. **Both export files** - the CSV files that show divergences

2. **Browser console logs** - filter for these keywords:
   - `[ROLLBACK]` - rollback events
   - `[FAST_FORWARD]` - fast-forward events
   - `[CONFIRMED]` - frame confirmation
   - `[EXPORT]` - export events

3. **Comparison output** - full verbose output:
   ```bash
   python scripts/validate_action_sequences.py --compare file1.csv file2.csv --verbose > comparison_report.txt 2>&1
   ```

4. **Test scenario description** - which scenario was being tested and any deviations from the protocol

### Console Log Reference

| Log Pattern | Meaning |
|-------------|---------|
| `[ROLLBACK] fromFrame=X toFrame=Y` | Rollback occurred, simulation rewound |
| `[CONFIRMED] frame=X` | Frame X confirmed by both players |
| `[FAST_FORWARD] start=X end=Y` | Fast-forward processed frames X to Y |
| `[EXPORT] episode=N rows=M` | Export completed with M rows |

---

## Known Limitations

### 500ms Symmetric Latency

Latency above 500ms on BOTH players can cause WebRTC signaling timeouts. This is a known limitation of browser-based P2P connections, not a bug in the data recording system.

**Workaround:** Test with asymmetric high latency (e.g., one player at 500ms) or use realistic latency values (typically under 300ms for most internet connections).

### CDP Network Throttling

Chrome DevTools Protocol network throttling primarily affects HTTP traffic. WebRTC data channels may not be fully affected. The DevTools Network tab throttling works for testing purposes but may not perfectly simulate all network conditions.

### Focus Loss Timeout

If a player is backgrounded for longer than the configured timeout (default: 30 seconds), the game will end. This is intentional behavior, not a bug.

---

## Appendix: Quick Reference

### File Locations

| Item | Path |
|------|------|
| Export files | `data/{scene_id}/{subject_id}_ep{N}.csv` |
| Validation script | `scripts/validate_action_sequences.py` |
| Server entry point | `mug/server/app.py` |

### Key Commands

```bash
# Start server
python -m mug.server.app

# Compare two files
python scripts/validate_action_sequences.py --compare file1.csv file2.csv

# Compare with details
python scripts/validate_action_sequences.py --compare file1.csv file2.csv --verbose

# Validate entire scene
python scripts/validate_action_sequences.py data/cramped_room_hh
```

### Validation Checklist

- [ ] Server running
- [ ] Two browser windows open
- [ ] Both players matched
- [ ] Tutorial completed in both
- [ ] Episode completed (check console for export message)
- [ ] Export files present in data directory
- [ ] Comparison returns exit code 0

---

*Last updated: 2026-02-01*
*Related: Phase 39 (Verification Metadata), Phase 43 (Data Comparison Pipeline)*
