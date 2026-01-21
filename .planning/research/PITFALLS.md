# Domain Pitfalls: GGPO Rollback Netcode in Browser/WebRTC/Pyodide

**Domain:** P2P multiplayer with GGPO-style rollback netcode
**Research focus:** Pitfalls specific to browser, WebRTC, and Pyodide contexts
**Researched:** 2026-01-16 (updated 2026-01-20 for v1.1 sync validation)
**Confidence:** HIGH (based on existing codebase implementation + domain expertise)

---

## Critical Pitfalls

Mistakes that cause major desyncs, data corruption, or require architectural rewrites.

### Pitfall 1: Non-Deterministic Environment Execution

**What goes wrong:** Two clients run the "same" Gymnasium environment with identical inputs but end up in different states because the environment uses non-deterministic operations (unsorted dict iteration, random without seeding, floating-point accumulation differences).

**Why it happens:**
- Python dict iteration order is deterministic per-process but not cross-process
- Random number generation not seeded consistently
- Floating-point math can differ between CPython (server) and Pyodide (WASM)
- NumPy operations may use different SIMD paths

**Consequences:**
- State hashes mismatch even with identical action sequences
- Constant rollbacks that never converge
- Research data becomes invalid (clients experienced different games)

**Warning signs:**
- `[P2P DESYNC]` or `[ACTION MISMATCH]` logs appearing consistently
- `p2pHashMismatches` counter increasing steadily
- Action counts match but state hashes don't

**Prevention:**
1. Implement `get_state()` and `set_state()` that capture ALL mutable state
2. Seed all RNG sources (NumPy, Python random) identically - codebase already does this via `seedPythonEnvironment()`
3. Use integer arithmetic where possible; round floats deterministically
4. Validate determinism by running same seed+inputs on CPython vs Pyodide and comparing state hashes
5. Sort any dict/set iterations that affect game state

**Phase to address:** Foundation (Phase 1) - must be validated before any P2P work
**Severity:** CRITICAL - causes complete sync failure

**Codebase reference:** The existing implementation validates this via `validateStateSync()` in `pyodide_multiplayer_game.js:421-463` but only checks method existence, not actual determinism.

---

### Pitfall 2: Input Buffer Pruning Race Conditions

**What goes wrong:** Input buffer is pruned before rollback completes, losing inputs needed for replay. Or inputs are pruned while still needed for a pending rollback triggered by late-arriving input.

**Why it happens:**
- Pruning runs on every step without coordination with rollback
- `pendingRollbackFrame` may be set but rollback hasn't executed yet
- Race between receiving late input and pruning the frame's data

**Consequences:**
- Rollback fails to restore correct state
- `[GGPO] WARNING: Still using prediction during replay` errors
- Silent desync that doesn't self-correct

**Warning signs:**
- Rollback logs showing prediction during replay
- Input buffer size dropping to 0 during active game
- Desync after high-latency spikes

**Prevention:**
1. Never prune frames >= `pendingRollbackFrame`
2. Keep buffer large enough for max expected rollback depth (currently 60 frames)
3. Prune AFTER rollback completion, not before
4. Log when pruning removes inputs that were recently added

**Phase to address:** GGPO core implementation
**Severity:** CRITICAL - causes unrecoverable desync

**Codebase reference:** `pruneInputBuffer()` in `pyodide_multiplayer_game.js:2050-2076` - the current implementation prunes to `frameNumber - 60` which may be too aggressive if snapshot interval is 5 frames and max snapshots is 30 (150 frames of potential rollback).

---

### Pitfall 3: RNG State Not Captured in Snapshots

**What goes wrong:** Rollback restores environment state but not RNG state, so replayed frames produce different random outcomes than original execution.

**Why it happens:**
- Environment `get_state()` doesn't include RNG state
- Python's `random` and NumPy RNG states are global, not per-environment
- Snapshot only captures what `get_state()` returns

**Consequences:**
- Bot actions differ on replay (if they use RNG)
- Environment transitions differ if environment uses randomness
- Subtle desyncs that only appear with bot players

**Warning signs:**
- Desync only in games with AI/bot players
- Replayed frames have different action sequences
- Action counts for bots diverge between clients

**Prevention:**
1. Capture both NumPy and Python RNG state in snapshots (already done in `saveStateSnapshot()`)
2. Restore RNG state before replay (already done in `loadStateSnapshot()`)
3. Verify bot produces identical actions after rollback
4. Consider per-environment RNG instances instead of global

**Phase to address:** GGPO core implementation
**Severity:** CRITICAL - causes desync with AI players

**Codebase reference:** Already implemented in `saveStateSnapshot()` (lines 1762-1813) and `loadStateSnapshot()` (lines 1832-1883). Verify completeness for environments that use RNG.

---

### Pitfall 4: WebRTC DataChannel Reliability Mode Mismatch

**What goes wrong:** DataChannel configured for reliable delivery (TCP-like) when GGPO needs unreliable (UDP-like) delivery, or vice versa.

**Why it happens:**
- WebRTC DataChannel defaults to reliable ordered delivery
- GGPO is designed for unreliable transport where old inputs are safely dropped
- Developers assume "reliable" is better without understanding tradeoffs

**Consequences:**
- Reliable mode: Head-of-line blocking causes input spikes when packets delayed
- Unreliable mode: Critical control messages (sync, reset) may be lost
- High latency under packet loss

**Warning signs:**
- Sudden lag spikes followed by burst of inputs
- Inputs arriving out of order in reliable mode (shouldn't happen)
- Control messages like `server_episode_start` occasionally lost

**Prevention:**
1. Use unreliable unordered DataChannel for input streaming
2. Use reliable ordered DataChannel (or SocketIO fallback) for control messages
3. Implement sequence numbers in unreliable channel to detect and drop old inputs
4. Configure appropriate max retransmit/lifetime for semi-reliable use cases

**Phase to address:** WebRTC implementation
**Severity:** CRITICAL - severely impacts responsiveness

**Codebase reference:** WebRTC not yet implemented - currently uses SocketIO (`socket.emit('pyodide_player_action', ...)` in step() around line 795).

---

### Pitfall 5: State Hash Algorithm Mismatch Between Client and Server

**What goes wrong:** Client (Pyodide) and server (CPython) compute different hashes for identical state because JSON serialization differs or hash algorithm implementation differs.

**Why it happens:**
- `json.dumps()` output can differ between Python versions
- Dictionary key ordering may differ (pre-3.7)
- Floating-point representation in JSON may round differently
- Hash functions may have platform-specific behavior

**Consequences:**
- False desync detection triggers unnecessary rollbacks
- Constant state corrections even when states are identical
- Performance degradation from continuous reconciliation

**Warning signs:**
- `[Reconcile] HASH MISMATCH` appearing frequently
- States match when manually compared but hashes don't
- Rollback count extremely high relative to network quality

**Prevention:**
1. Use `sort_keys=True` in `json.dumps()` (already done in `computeQuickStateHash()`)
2. Round floats to fixed precision before hashing
3. Use identical hash algorithm (MD5 is fine for checksums)
4. Test hash equivalence: dump state on server, send to client, verify hash matches
5. Consider binary serialization (msgpack) for exact byte-level reproducibility

**Phase to address:** State synchronization
**Severity:** CRITICAL - causes constant false positive desyncs

**Codebase reference:** Hash computation in `computeQuickStateHash()` at line 1185-1213 uses `json.dumps(..., sort_keys=True)` and MD5[:16].

---

## Moderate Pitfalls

Mistakes that cause noticeable issues, degraded experience, or technical debt.

### Pitfall 6: Snapshot Interval vs Rollback Depth Mismatch

**What goes wrong:** Snapshot interval is too large relative to typical rollback depth, requiring replay of many frames. Or snapshots aren't available for the target rollback frame.

**Why it happens:**
- Snapshot interval chosen for storage efficiency without considering latency
- `findBestSnapshot()` returns frame much earlier than target
- Max snapshots limit causes old snapshots to be pruned too aggressively

**Consequences:**
- Rollbacks replay 20+ frames instead of 5
- Visible stutter during rollback (especially at low FPS targets)
- Performance degradation under latency spikes

**Warning signs:**
- `[GGPO] Loaded snapshot from frame X, replaying to Y` where Y - X > expected
- Rollback execution time significantly longer than single frame
- User complaints of "hitching" or "freezing"

**Prevention:**
1. Set snapshot interval based on expected RTT: `interval = RTT / (2 * frame_duration)`
2. For 100ms RTT at 30 FPS (33ms/frame): interval = 100 / (2 * 33) = 1.5, so use interval=2
3. Current default of 5 frames is reasonable for ~160ms RTT
4. Monitor rollback replay frame counts and tune accordingly
5. Consider adaptive snapshot frequency based on observed latency

**Phase to address:** Performance tuning
**Severity:** MODERATE - causes perceivable stutter

**Codebase reference:** `snapshotInterval = 5` and `maxSnapshots = 30` at lines 45-46. With 30 FPS, this gives 5 seconds of rollback history.

---

### Pitfall 7: Input Delay Not Tuned for Network Conditions

**What goes wrong:** Fixed input delay that's too low for actual network latency (causing constant rollbacks) or too high (causing unnecessary input lag).

**Why it happens:**
- Input delay hardcoded or set at game start
- Network conditions change during session
- Different player pairs have different RTTs

**Consequences:**
- Too low: Near-constant rollbacks, jittery experience
- Too high: Both players feel sluggish even on good connections
- Asymmetric experience if one player on WiFi, one on ethernet

**Warning signs:**
- `Predicted: [playerX]` appearing on most frames
- `rollbackCount` increasing steadily throughout session
- Player complaints about input responsiveness

**Prevention:**
1. Measure RTT during matchmaking, set initial delay = RTT / (2 * frame_time)
2. For research: log actual vs predicted input usage ratio
3. Allow per-session configuration of input delay
4. Consider adaptive delay (more complex, may affect research validity)

**Phase to address:** Network layer
**Severity:** MODERATE - affects player experience

**Codebase reference:** `this.INPUT_DELAY = config.input_delay ?? 0` at line 29. Default of 0 means no input delay, relying entirely on rollback.

---

### Pitfall 8: Pyodide Step Performance Variability

**What goes wrong:** Pyodide environment step() takes variable time (10ms-100ms+), causing frame timing jitter that looks like network issues.

**Why it happens:**
- WASM JIT compilation during gameplay
- Garbage collection pauses
- Complex environment step logic
- Browser throttling in background tabs

**Consequences:**
- Frame rate drops cause input buffer to grow
- Other player's inputs arrive "late" relative to local frame
- Rollbacks triggered by local slowness, not network

**Warning signs:**
- `Step: Xms avg, Yms max` showing high variance in diagnostics
- Rollbacks increase when client has other browser activity
- Desync correlates with slow step times, not network latency

**Prevention:**
1. Profile environment step() and optimize hot paths
2. Pre-warm Pyodide by running a few dummy steps before game starts
3. Detect background tab and pause game or warn user
4. Track step time in diagnostics (already done via `trackStepTime()`)
5. Consider worker thread for Pyodide to avoid main thread blocking

**Phase to address:** Performance optimization
**Severity:** MODERATE - causes false desyncs and jitter

**Codebase reference:** Step timing tracked in `diagnostics.stepTimes` and logged in `logDiagnostics()` at line 1006-1031.

---

### Pitfall 9: Action Queue Starvation from Lost Messages

**What goes wrong:** WebRTC DataChannel drops packets, causing input gaps. GGPO predicts using last action but prediction keeps being wrong.

**Why it happens:**
- Unreliable DataChannel drops packets under congestion
- Packet loss + high latency = multiple consecutive inputs lost
- No acknowledgment/retransmit for input messages

**Consequences:**
- Extended prediction periods with wrong inputs
- Large rollbacks when real inputs finally arrive
- Player feels like inputs are being ignored

**Warning signs:**
- Multiple consecutive frames showing `Predicted: [playerX]`
- Sudden large rollbacks (10+ frames)
- Input buffer has gaps (frame 100, 105, 106 but no 101-104)

**Prevention:**
1. Implement redundant input sending: each message includes last N inputs
2. Use sequence numbers to detect gaps and request retransmit
3. Consider semi-reliable DataChannel (max-retransmits: 2)
4. Track input arrival rate per player for diagnostics

**Phase to address:** Network reliability
**Severity:** MODERATE - causes extended prediction periods

**Codebase reference:** No redundancy currently - each action sent once via `socket.emit('pyodide_player_action', ...)`.

---

### Pitfall 10: Episode Boundary Synchronization Failures

**What goes wrong:** Players start new episodes at slightly different times, causing one player to process old actions as if they're for the new episode.

**Why it happens:**
- Episode reset triggered locally before sync message arrives
- Stale actions from old episode queued and not cleared
- Clock drift between clients

**Consequences:**
- First few frames of new episode have wrong inputs
- Immediate desync at episode start
- Research data contaminated with cross-episode actions

**Warning signs:**
- Desync immediately after episode reset
- Action counts diverge in first few frames of episode
- `syncEpoch` mismatch errors

**Prevention:**
1. Use server-provided `syncEpoch` to tag actions (already implemented)
2. Clear all action queues at episode boundary (already in `clearGGPOState()`)
3. Wait for all clients to acknowledge episode start before processing inputs
4. Discard actions with old `syncEpoch` even if frame number matches

**Phase to address:** Episode management
**Severity:** MODERATE - causes data integrity issues

**Codebase reference:** Episode handling in `reset()` method, `syncEpoch` tracking at line 109-110, cleared in `clearGGPOState()` at line 2082-2093.

---

### Pitfall 11: TURN Server Latency Hidden in P2P Metrics

**What goes wrong:** Connection falls back to TURN relay but code assumes direct P2P, causing input delay to be misconfigured.

**Why it happens:**
- WebRTC silently falls back to TURN when direct connection fails
- RTT measurements reflect TURN relay latency (often 100-300ms+)
- Input delay tuned for direct P2P doesn't account for relay

**Consequences:**
- Constant rollbacks when TURN is in use
- Player experience significantly worse than expected
- Research data may be invalid if TURN vs direct not tracked

**Warning signs:**
- RTT measurements much higher than expected for geography
- ICE candidate type is "relay" in connection stats
- Performance varies dramatically between player pairs

**Prevention:**
1. Detect connection type via `RTCPeerConnection.getStats()` ICE candidate type
2. Track and log whether connection uses relay or host/srflx candidates
3. Adjust input delay when TURN detected
4. Consider displaying connection quality indicator to users
5. For research: record connection type in data

**Phase to address:** WebRTC implementation
**Severity:** MODERATE - causes degraded experience for NAT-blocked users

**Codebase reference:** Not yet implemented - WebRTC is in PROJECT.md as pending.

---

## Minor Pitfalls

Mistakes that cause annoyance, debugging difficulty, or minor issues.

### Pitfall 12: Console Logging Overwhelming Browser

**What goes wrong:** GGPO debug logging on every frame causes browser developer tools to become unresponsive.

**Why it happens:**
- Verbose logging intended for debugging left enabled
- `console.log()` on every frame at 30+ FPS
- DevTools tries to render thousands of log entries

**Consequences:**
- Can't debug other issues because console is flooded
- Browser performance degrades with DevTools open
- Actual errors buried in noise

**Warning signs:**
- DevTools console becoming sluggish
- Log messages appearing at 30+ per second
- Memory usage increasing from log retention

**Prevention:**
1. Use conditional logging: `if (this.frameNumber % 30 === 0)`
2. Use log levels (debug vs info vs warn)
3. Make verbose logging configurable via config flag
4. Aggregate stats instead of per-frame logs

**Phase to address:** Developer experience
**Severity:** MINOR - debugging annoyance

**Codebase reference:** Conditional logging already implemented, e.g., line 824 `if (this.frameNumber % 30 === 0 || predictedPlayers.length > 0)`.

---

### Pitfall 13: Memory Leaks from Unbounded History Tracking

**What goes wrong:** Action sequence history, state hash history, or diagnostic arrays grow without bound during long sessions.

**Why it happens:**
- Arrays/Maps used for debugging never pruned
- Long research sessions (60+ minutes)
- Multiple episodes accumulate history

**Consequences:**
- Browser memory usage grows steadily
- Eventually causes tab crash or severe slowdown
- History becomes too large to usefully inspect

**Warning signs:**
- Browser memory usage increasing over session
- DevTools showing large arrays in heap snapshot
- Tab becoming sluggish after 30+ minutes

**Prevention:**
1. Limit `actionSequence` length (currently unbounded)
2. Prune `stateHashHistory` (already done, max 60 entries)
3. Clear per-episode tracking in `clearGGPOState()` (already done for most)
4. Periodically summarize old history instead of keeping raw entries

**Phase to address:** Performance optimization
**Severity:** MINOR - only affects long sessions

**Codebase reference:** `actionSequence` at line 106 has no pruning; should be pruned to match snapshot history.

---

### Pitfall 14: Time Zone / Clock Skew in Timestamp Comparisons

**What goes wrong:** Network latency calculations using `Date.now()` timestamps from different machines produce nonsense values.

**Why it happens:**
- Client clocks not synchronized with server
- Timestamps compared across machines without offset correction
- NTP skew can be seconds, not milliseconds

**Consequences:**
- Latency appears negative or impossibly large
- Diagnostic logs misleading
- Any clock-based logic fails

**Warning signs:**
- Latency showing negative values
- Latency values varying by hundreds of ms between checks
- Server and client timestamps wildly different

**Prevention:**
1. Only use timestamps for relative measurements on same machine
2. For cross-machine latency: use round-trip measurement (RTT/2)
3. Store server timestamp offset and apply it consistently
4. Don't make game logic decisions based on wall-clock time

**Phase to address:** Network diagnostics
**Severity:** MINOR - affects diagnostics accuracy

**Codebase reference:** Latency calculation at line 320 `networkLatency = serverTimestamp > 0 ? now - serverTimestamp : 'N/A'` assumes synchronized clocks.

---

## Pyodide-Specific Pitfalls

Issues unique to running Python in WebAssembly in the browser.

### Pitfall 15: Pyodide Package Installation During Gameplay

**What goes wrong:** Environment import triggers micropip install mid-game, causing multi-second freeze.

**Why it happens:**
- Environment code uses optional dependency not pre-installed
- Micropip fetches and installs package synchronously
- No way to know what packages environment will need

**Consequences:**
- Game freezes for 5-30 seconds
- Other player experiences massive desync
- Likely causes disconnect timeout

**Warning signs:**
- `micropip.install()` in console during gameplay
- Network requests for `.whl` files during game
- Single frame taking 10+ seconds

**Prevention:**
1. Pre-install all required packages in `initialize()` before game starts
2. Validate environment works offline before adding to experiment
3. Monitor for new network requests during gameplay
4. Use `packages_to_install` config to declare dependencies explicitly

**Phase to address:** Environment setup
**Severity:** MODERATE for Pyodide - causes major disruption

**Codebase reference:** Package installation in `initialize()` at line 36-44 of `pyodide_remote_game.js`.

---

### Pitfall 16: Pyodide Memory Limits and GC Pauses

**What goes wrong:** Environment allocates large arrays (images, observations), exceeding WASM memory limit or triggering long GC pauses.

**Why it happens:**
- WASM has limited heap size (typically 2-4GB max)
- Pyodide GC can pause for 50-200ms
- Large NumPy arrays persist longer than needed
- Python-JS boundary creates duplicate data

**Consequences:**
- Out of memory crash
- Long GC pauses cause frame drops
- Desync from timing inconsistencies

**Warning signs:**
- Browser memory warnings
- Periodic frame time spikes with no network cause
- `MemoryError` in Python exceptions

**Prevention:**
1. Profile memory usage in Pyodide environments
2. Explicitly delete large arrays when done: `del large_array`
3. Use smaller observation representations
4. Monitor `performance.memory` in browser (Chrome only)
5. Consider streaming observations instead of full state

**Phase to address:** Performance optimization
**Severity:** MODERATE - can crash long sessions

**Codebase reference:** Large array conversion in `step()` and `reset()` for RGB rendering could be memory-intensive.

---

## Sync Validation Pitfalls (v1.1)

**Added:** 2026-01-20 for v1.1 Sync Validation milestone

These pitfalls are specific to implementing desync detection and validation systems. They focus on false positives (incorrectly detecting desyncs that didn't happen) and subtle bugs in validation logic.

### Pitfall 20: Frame Alignment Mismatch in Hash Comparison

**What goes wrong:** Peers compare state hashes at different simulation frames, producing false positive desync detection. Peer A computes hash at frame 100, peer B receives it but is now at frame 105, and computes current hash to compare - hashes differ due to 5 frames of evolution, not desync.

**Why it happens:**
- WebRTC message delivery has variable latency (10-200ms)
- Peers advance frames independently between message exchanges
- Comparing "current hash" to received hash ignores frame number
- State hash history might not contain the exact frame needed for comparison

**Consequences:**
- Constant false positive desync warnings that obscure real issues
- Unnecessary rollback or correction attempts
- Invalid metrics (p2pHashMismatches inflated)
- Research data flagged as "desynced" when actually synchronized

**Warning signs:**
- High mismatch count but states converge when manually compared at same frame
- Mismatches correlate with high RTT, not actual divergence
- Mismatches disappear when both peers are idle (same frame)

**Prevention:**
1. Always compare hashes for the SAME frame number
2. Store hash history keyed by frame number (already in `stateHashHistory`)
3. Skip comparison if local hash for that exact frame isn't available - don't compute current and compare
4. Consider: only compare hashes for frames where BOTH peers have confirmed (non-predicted) inputs
5. Log frame numbers alongside hashes in all desync warnings

**Detection before shipping:**
- Unit test: simulate 50ms delivery delay, verify no false positives
- Log `comparing_frame=X local_hash=Y remote_hash=Z local_frame=W` to verify alignment
- If `local_frame != comparing_frame`, the comparison is invalid

**Phase to address:** Sync validation core implementation
**Severity:** CRITICAL for validation - defeats the purpose of detection

**Codebase reference:** Current logic in `socket.on('p2p_state_sync')` at lines 721-757 attempts frame alignment via `stateHashHistory.get(frame_number)` but falls back to computing current hash if not found, which is incorrect.

---

### Pitfall 21: Rollback Invalidates Pre-Computed Hashes

**What goes wrong:** State hash was computed and stored for frame N, but then a rollback occurred that changed frame N's state. The stored hash is now stale and will cause false positive mismatches.

**Why it happens:**
- Hash recorded immediately after stepping to frame N
- Rollback later corrects a predicted input for frame N-5
- Replay to current frame changes what frame N looked like
- Old hash for frame N still in history, now incorrect

**Consequences:**
- False desync detection when peer sends correct hash
- Stored validation data contains incorrect hashes
- Post-game analysis shows "desyncs" that were actually rollback corrections

**Warning signs:**
- Mismatches appear after rollbacks complete
- Re-comparing states manually shows they match
- Mismatch count correlates with rollback count

**Prevention:**
1. Clear or update hash history after rollback completes
2. Only compare hashes for frames AFTER confirmed frame (no outstanding predictions)
3. Track `confirmedFrame` and reject hash comparisons for frames < confirmedFrame that have pending rollbacks
4. Alternatively: recompute hashes for replayed frames during rollback (expensive)
5. For validation export: only include hashes for confirmed-input frames

**Detection before shipping:**
- Intentionally trigger rollback, verify hash history updated
- Compare hash at frame N before and after rollback that affects N
- Add assertion: if rollback touched frame N, hash for N must be invalidated

**Phase to address:** Sync validation, integrate with rollback system
**Severity:** HIGH - causes systematic false positives after every rollback

**Codebase reference:** `stateHashHistory` is not cleared in rollback path. Need to invalidate entries >= rollback target frame. See `performGGPORollback()` implementation.

---

### Pitfall 22: JSON Serialization Non-Determinism for State Hashing

**What goes wrong:** Identical logical states produce different JSON strings (and thus different hashes) due to:
- Floating-point representation differences (`0.30000000000000004` vs `0.3`)
- Object key insertion order after dynamic updates
- Set/dict iteration order in Python state
- NumPy array dtype or shape representation

**Why it happens:**
- `json.dumps()` represents floats with full precision, and IEEE 754 has platform-specific rounding
- Python 3.7+ dicts are insertion-ordered, but that order can differ if code paths differ
- Pyodide (WASM) and CPython may format floats slightly differently
- NumPy array serialization may include metadata that varies

**Consequences:**
- Hashes differ between Pyodide peers or between Pyodide and CPython
- States are semantically identical but byte-level different
- Constant false positives between browser types (Chrome vs Firefox) or Python versions

**Warning signs:**
- Mismatches from first frame even with identical seeds
- Dumping state JSON shows subtle differences in float formatting
- Hash matches in same browser, fails cross-browser

**Prevention:**
1. Round floats to fixed precision before hashing: `round(x, 6)`
2. Sort dict keys explicitly before serialization (already using `sort_keys=True`)
3. For NumPy arrays: `.tolist()` before serialization, avoid raw array serialization
4. Convert sets to sorted lists before hashing
5. Use custom JSON encoder that normalizes types
6. Test hash equivalence: same state, Pyodide vs Pyodide in different browsers

**Detection before shipping:**
- Cross-browser test: Chrome peer vs Firefox peer, verify hash match on frame 0
- Dump raw JSON on hash mismatch to inspect exact differences
- Add environment test: `get_state()` -> `json.dumps()` -> compare byte-for-byte across platforms

**Phase to address:** State hashing implementation
**Severity:** HIGH - systematic false positives for certain environments

**Codebase reference:** `computeQuickStateHash()` uses `json.dumps(_state, sort_keys=True)` but no float rounding. Environment-specific; some environments may have problematic state shapes.

---

### Pitfall 23: WebAssembly Floating-Point NaN Non-Determinism

**What goes wrong:** WebAssembly floating-point operations produce NaN values with non-deterministic bit patterns. If environment state includes NaN (from division by zero, invalid operations), hash differs between peers even for "same" NaN.

**Why it happens:**
- WASM spec allows non-deterministic NaN payloads and sign bits
- Different browser engines (V8 vs SpiderMonkey) may produce different NaN bit patterns
- NaN != NaN in IEEE 754, so comparison fails
- JSON.stringify(NaN) produces "null" which loses information

**Consequences:**
- Rare but catastrophic: random false positives when NaN appears in state
- Debugging nightmare - state "looks" identical but hashes differ
- Browser-specific failures that don't reproduce in same browser

**Warning signs:**
- Intermittent mismatches with no clear pattern
- Mismatch occurs after specific game events (physics collision, etc.)
- State inspection shows `NaN` or `null` in unexpected places

**Prevention:**
1. Environments should avoid producing NaN in state (validate inputs, use defaults)
2. Before hashing: detect and normalize NaN values to a consistent representation
3. Consider: skip hash comparison if state contains NaN (log warning instead)
4. Use fixed-point arithmetic for critical calculations
5. Test environments for NaN production under edge cases

**Detection before shipping:**
- Search environment code for operations that could produce NaN: `/0`, `sqrt(-1)`, `log(0)`, etc.
- Add state validation: flag if any state value is NaN before hashing
- Cross-browser smoke test with physics-heavy environments

**Phase to address:** State hashing robustness
**Severity:** MEDIUM - rare but hard to debug when it occurs

**Codebase reference:** Python `json.dumps()` turns NaN to `null`, losing the value. This masks the problem but can cause subtle state corruption.

**Sources:**
- [WebAssembly Determinism with NaN](https://github.com/WebAssembly/design/issues/619)
- [WebAssembly Numerics Specification](https://webassembly.github.io/spec/core/exec/numerics.html)

---

### Pitfall 24: Python Set Iteration Order in Environment State

**What goes wrong:** Environment `get_state()` returns a set (or dict created from set-like iteration), and iteration order differs between invocations or peers, causing hash difference for identical logical state.

**Why it happens:**
- Python sets have no guaranteed iteration order
- With PYTHONHASHSEED randomization, order changes between processes
- Even without randomization, order depends on insertion history
- Common pattern: `{entity.id for entity in entities}` captures correct data but wrong order

**Consequences:**
- False positive desync detection for environments with set-based state
- Intermittent: sometimes orders happen to match, sometimes don't
- Hard to reproduce because order is "random" per-process

**Warning signs:**
- Mismatches appear randomly even with identical inputs
- JSON diff shows same elements but different array order
- Setting `PYTHONHASHSEED=0` fixes the issue (confirms cause)

**Prevention:**
1. Convert sets to sorted lists before returning from `get_state()`: `sorted(my_set)`
2. Use lists instead of sets for state that needs determinism
3. Environment review: grep for `set(` and `{...}` in state-related code
4. Validate environments: call `get_state()` twice with same state, verify JSON identical

**Detection before shipping:**
- Add to environment test suite: `get_state()` must produce identical JSON when called twice
- Log warning if environment state contains set types (detect via `isinstance()` before serialization)
- Flag in environment documentation that `get_state()` must be deterministic

**Phase to address:** Environment validation / state hashing
**Severity:** HIGH - common mistake, causes intermittent false positives

**Codebase reference:** Environment-dependent. Affects any environment where `get_state()` includes set iteration.

**Sources:**
- [Python Set Ordering](https://praful932.dev/blog-1-ordered-sets/)
- [PYTHONHASHSEED](http://jimmycallin.com/2016/01/03/make-your-python3-code-reproducible/)

---

### Pitfall 25: Timing-Based Comparison Race (TOCTOU)

**What goes wrong:** Time-of-check to time-of-use race: hash is computed, then state changes before comparison completes or message is sent, so the hash sent doesn't match current state.

**Why it happens:**
- `computeQuickStateHash()` is async - state can change during execution
- Peer sends hash for frame N, but continues stepping to frame N+1 before send completes
- Message queue delays between computing hash and receiving comparison

**Consequences:**
- Rare false positives when hash computation races with state changes
- Hard to reproduce: depends on exact timing of async operations
- More common under high CPU load or with slow environments

**Warning signs:**
- Sporadic mismatches that don't reproduce consistently
- Mismatch logs show frame numbers that don't align with expectations
- Issue appears more frequently under load

**Prevention:**
1. Capture state atomically: compute hash synchronously or lock state during computation
2. Associate frame number with hash at computation time, not send time
3. Don't compare hash if local frame has advanced past the frame being compared
4. Serialize validation operations: don't start new step while hash comparison pending
5. For async hash computation: save frame number at start, validate still at that frame at end

**Detection before shipping:**
- Stress test: high step rate (60+ FPS) with validation enabled
- Log timing: `hash_compute_start`, `hash_compute_end`, `frame_at_send`
- Add assertion: frame at hash compute end == frame at hash compute start

**Phase to address:** Sync validation implementation
**Severity:** MEDIUM - rare but real

**Codebase reference:** `computeQuickStateHash()` is async (`runPythonAsync`). Frame can advance during execution. Need to record frameNumber at call start.

---

### Pitfall 26: NumPy Random Generator State Platform Differences

**What goes wrong:** NumPy random state captured on one peer doesn't restore identically on another peer due to:
- Different NumPy versions (API changes)
- Different underlying PRNG implementations
- Platform-specific bit representations in state arrays

**Why it happens:**
- NumPy doesn't guarantee RNG stream compatibility across versions
- Pyodide may use different NumPy version than expected
- `RandomState` vs `Generator` API differences
- Internal state arrays may have platform-specific padding or ordering

**Consequences:**
- RNG-dependent environments produce different random sequences after restore
- Bot actions diverge after rollback
- False "desync" that's actually RNG desync

**Warning signs:**
- Desync only after rollback in environments with randomness
- Bot-vs-bot games desync while human-vs-human games don't
- RNG state looks different when logged on each peer

**Prevention:**
1. Pin NumPy version exactly in Pyodide packages
2. Use `np.random.default_rng(seed)` instead of `np.random.seed()` for reproducibility
3. Capture and restore using `generator.bit_generator.state` (new API)
4. Test RNG restore: capture state, step, compare sequence on both peers
5. Consider: use Python `random` module only (simpler, more portable)

**Detection before shipping:**
- Unit test: save RNG state, restore, generate 1000 numbers, verify identical
- Cross-version test: Pyodide NumPy vs CPython NumPy state compatibility
- Add RNG sequence logging for first 10 numbers after restore

**Phase to address:** Snapshot/restore implementation, environment validation
**Severity:** MEDIUM - affects RNG-heavy environments

**Codebase reference:** RNG state capture in `saveStateSnapshot()` uses both `numpy.random.get_state()` and `random.getstate()`. Verify restoration produces identical sequences.

**Sources:**
- [NumPy RNG Policy NEP-19](https://numpy.org/neps/nep-0019-rng-policy.html)

---

### Pitfall 27: Action Sequence Comparison Off-By-One Errors

**What goes wrong:** Action sequence verification fails due to off-by-one errors in frame numbering:
- Actions recorded at frame N-1 vs frame N
- Input for frame N recorded before vs after step
- Frame 0 vs frame 1 indexing confusion

**Why it happens:**
- GGPO uses "input for frame N is collected during frame N-1"
- Different conventions for when frame number increments (before/after step)
- Episode boundaries reset frame numbers inconsistently

**Consequences:**
- Action sequences appear to differ by one frame offset
- "Desync" detection triggers for perfectly synchronized peers
- Debugging shows all actions present, just misaligned

**Warning signs:**
- Action sequence mismatch logs show same actions, different frame numbers
- Mismatch is always by 1 frame (or consistent N frames)
- Actions match when manually shifted

**Prevention:**
1. Define clear convention: "action for frame N" means action applied during step N
2. Record action WITH its frame number, not position in array
3. Compare by frame number, not by array index
4. Add frame number to every action record: `{frame: N, player: P, action: A}`
5. Validate: local action sequence for frames 0-100 should match remote for frames 0-100

**Detection before shipping:**
- Unit test: two peers, compare action sequences after 100 frames
- Log format: `FRAME=N PLAYER=P ACTION=A` - easy to diff between peers
- Assertion: action at frame N exists in both sequences with same value

**Phase to address:** Action sequence verification implementation
**Severity:** MEDIUM - confusing but fixable once identified

**Codebase reference:** `actionSequence` array at line 511. Need to verify frame numbering convention is consistent with GGPO input queue.

---

### Pitfall 28: Validation Data Export Contains Uncommitted/Predicted State

**What goes wrong:** Post-game validation JSON export includes hashes and actions from frames that were predicted and later rolled back. This makes analysis appear to show desyncs that were actually corrected.

**Why it happens:**
- Hash recorded immediately after step, before knowing if rollback will occur
- Export doesn't distinguish confirmed vs predicted frames
- Rollback doesn't update already-recorded validation data

**Consequences:**
- Research analysis shows false "desync" rates
- Post-hoc validation appears to find issues that weren't there
- Confusing data where "desync" corrected itself

**Warning signs:**
- Exported data shows hash mismatch at frame N, but game continued successfully
- Mismatch followed by match at frame N+k after rollback
- More "desyncs" in export than `p2pHashMismatches` counter showed live

**Prevention:**
1. Only export hashes for confirmed frames (all inputs verified, no pending rollback)
2. Mark each record with `confirmed: true/false` status
3. Update or remove records during rollback
4. Alternative: export raw data including predictions, but clearly label it
5. Include rollback events in export so analysis can filter

**Detection before shipping:**
- Compare live mismatch count to exported mismatch count - should match
- Verify export only contains frames <= confirmedFrame
- Add test: trigger rollback, verify rolled-back frame's hash updated in export

**Phase to address:** Validation data export
**Severity:** MEDIUM - affects research data quality

**Codebase reference:** Validation export structure TBD. Will need `confirmedFrame` tracking integration.

---

## Phase-Specific Risk Matrix

| Phase | Likely Pitfalls | Mitigation Strategy |
|-------|-----------------|---------------------|
| WebRTC Integration | #4 (DataChannel mode), #11 (TURN detection) | Test both reliable/unreliable channels; implement connection type detection early |
| GGPO Core | #2 (buffer pruning), #3 (RNG in snapshots), #6 (snapshot interval) | Comprehensive rollback testing; verify RNG determinism |
| State Sync | #1 (non-determinism), #5 (hash mismatch) | Determinism test suite; hash equivalence validation |
| Performance | #8 (Pyodide step), #13 (memory leaks), #16 (WASM limits) | Profiling; long-session testing |
| Episode Management | #10 (boundary sync) | Server-authoritative episode transitions |
| Network Reliability | #9 (lost messages), #7 (input delay tuning) | Redundant input sending; per-connection RTT |
| **Sync Validation (v1.1)** | #20 (frame alignment), #21 (rollback invalidates hash), #22 (JSON non-determinism), #24 (set iteration) | Frame-aligned comparison only; clear hash history on rollback; normalize floats; sort sets |
| **Validation Export (v1.1)** | #28 (predicted state in export), #27 (off-by-one) | Confirmed-only export; clear frame numbering convention |

---

## Research-Specific Pitfalls

Since this is a research platform where data validity is critical:

### Pitfall 17: Silent Desync Not Detected

**What goes wrong:** Clients desync but continue playing, producing invalid paired data.

**Prevention:**
- Aggressive hash verification (every N frames)
- Log all reconciliation events for post-hoc analysis
- Flag sessions with high rollback counts in data

### Pitfall 18: Rollback Affects Measured Behavior

**What goes wrong:** Player's behavior includes reactions to predicted states that were rolled back, but data only captures confirmed inputs.

**Prevention:**
- Log predicted vs confirmed inputs separately
- Track rollback events with timestamps
- Consider whether rollback artifacts are valid data or noise

### Pitfall 19: Connection Type Not Recorded

**What goes wrong:** Some sessions use TURN relay with 200ms+ latency, others use direct P2P with 20ms latency, but data doesn't distinguish them.

**Prevention:**
- Record ICE connection type in session metadata
- Track RTT throughout session
- Consider stratifying analysis by connection quality

---

## v1.1 Validation Pitfalls Summary

For the v1.1 Sync Validation milestone, the highest-priority pitfalls to address are:

| Priority | Pitfall | Why Critical |
|----------|---------|--------------|
| P0 | #20 Frame Alignment | Comparing hashes at different frames defeats entire validation purpose |
| P0 | #21 Rollback Invalidation | Every rollback produces false positive if hash history not updated |
| P1 | #22 JSON Non-Determinism | Will cause cross-browser false positives |
| P1 | #24 Set Iteration Order | Common environment mistake, intermittent false positives |
| P2 | #28 Predicted State Export | Affects research data quality |
| P2 | #27 Off-By-One | Confusing but easy to fix once found |
| P3 | #23 NaN Non-Determinism | Rare edge case |
| P3 | #25 TOCTOU Race | Rare timing issue |
| P3 | #26 NumPy RNG State | Affects rollback in RNG-heavy envs |

**Recommended Implementation Order:**
1. Ensure frame-aligned comparison (#20)
2. Clear hash history on rollback (#21)
3. Add float normalization to hash (#22)
4. Document environment requirements re: sets (#24)
5. Implement confirmed-only export (#28)

---

## Sources

- Existing codebase implementation in `pyodide_multiplayer_game.js` (~3900 lines)
- CONCERNS.md analysis (2026-01-16)
- ARCHITECTURE.md patterns
- Domain expertise on GGPO/rollback netcode (verified against implementation)
- WebRTC specification behavior (DataChannel reliability modes)

**v1.1 research sources:**
- [Gaffer on Games: Floating Point Determinism](https://gafferongames.com/post/floating_point_determinism/)
- [ForrestTheWoods: Synchronous RTS Engines and Desyncs](https://www.forrestthewoods.com/blog/synchronous_rts_engines_and_a_tale_of_desyncs/)
- [yal.cc: Preparing for Deterministic Netcode](https://yal.cc/preparing-your-game-for-deterministic-netcode/)
- [Deterministic.js](https://deterministic.js.org/)
- [WebAssembly NaN Determinism](https://github.com/WebAssembly/design/issues/619)
- [NumPy NEP-19: RNG Policy](https://numpy.org/neps/nep-0019-rng-policy.html)
- [Python Hash Randomization](http://jimmycallin.com/2016/01/03/make-your-python3-code-reproducible/)
- [Godot Rollback Netcode: State Hashing](https://github.com/maximkulkin/godot-rollback-netcode)
- [INVERSUS Rollback Networking Post-Mortem](https://www.gamedeveloper.com/design/rollback-networking-in-inversus)

**Confidence levels:**
- Pitfalls #1-3, #5-6, #10, #12-13: HIGH (directly observed in codebase)
- Pitfalls #4, #9, #11: MEDIUM (WebRTC implemented, based on spec)
- Pitfalls #7-8, #14-19: MEDIUM (inferred from architecture and domain knowledge)
- Pitfalls #20-28: HIGH (domain expertise + web search verification + codebase analysis)

---

*Pitfalls research: 2026-01-16, updated 2026-01-20 for v1.1 Sync Validation*
