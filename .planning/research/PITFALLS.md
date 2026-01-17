# Domain Pitfalls: GGPO Rollback Netcode in Browser/WebRTC/Pyodide

**Domain:** P2P multiplayer with GGPO-style rollback netcode
**Research focus:** Pitfalls specific to browser, WebRTC, and Pyodide contexts
**Researched:** 2026-01-16
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

## Phase-Specific Risk Matrix

| Phase | Likely Pitfalls | Mitigation Strategy |
|-------|-----------------|---------------------|
| WebRTC Integration | #4 (DataChannel mode), #11 (TURN detection) | Test both reliable/unreliable channels; implement connection type detection early |
| GGPO Core | #2 (buffer pruning), #3 (RNG in snapshots), #6 (snapshot interval) | Comprehensive rollback testing; verify RNG determinism |
| State Sync | #1 (non-determinism), #5 (hash mismatch) | Determinism test suite; hash equivalence validation |
| Performance | #8 (Pyodide step), #13 (memory leaks), #16 (WASM limits) | Profiling; long-session testing |
| Episode Management | #10 (boundary sync) | Server-authoritative episode transitions |
| Network Reliability | #9 (lost messages), #7 (input delay tuning) | Redundant input sending; per-connection RTT |

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

## Sources

- Existing codebase implementation in `pyodide_multiplayer_game.js` (~2100 lines)
- CONCERNS.md analysis (2026-01-16)
- ARCHITECTURE.md patterns
- Domain expertise on GGPO/rollback netcode (verified against implementation)
- WebRTC specification behavior (DataChannel reliability modes)

**Confidence levels:**
- Pitfalls #1-3, #5-6, #10, #12-13: HIGH (directly observed in codebase)
- Pitfalls #4, #9, #11: MEDIUM (WebRTC not yet implemented, based on spec)
- Pitfalls #7-8, #14-19: MEDIUM (inferred from architecture and domain knowledge)

---

*Pitfalls research: 2026-01-16*
