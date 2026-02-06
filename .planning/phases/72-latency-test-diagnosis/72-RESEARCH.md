# Phase 72: Latency Test Diagnosis - Research

**Researched:** 2026-02-06
**Domain:** E2E test reliability under CDP latency injection; root cause investigation
**Confidence:** HIGH (code analysis) / MEDIUM (root cause hypotheses -- need empirical validation)

## Summary

The `test_episode_completion_under_fixed_latency[chromium-200]` test times out at its 300s pytest timeout. The 100ms variant passes. The test applies Chrome DevTools Protocol (CDP) latency via `Network.emulateNetworkConditions` to both players BEFORE navigation, then runs through the full game flow expecting the first episode to complete.

The most critical discovery from this research is that **CDP's `latency` parameter does NOT affect WebRTC DataChannel traffic** (Chromium issue 41215664). It only affects HTTP request/response headers and WebSocket frames. Since the game uses P2P DataChannel for input exchange, the actual game inputs are NOT delayed by the test's latency injection. This means the test is NOT testing what it claims -- it tests setup/signaling latency, not gameplay latency.

However, the practical consequence is that the 200ms latency significantly slows down (a) page loading (every HTTP request), (b) Pyodide/WASM loading from CDN, (c) SocketIO WebSocket messages including WebRTC signaling, and (d) server events like `pyodide_game_ready` and `p2p_validation_complete`. The interaction of these delays with Phase 19 (P2P validation), Phase 67 (Pyodide preload), Phase 69 (server init grace), or Phase 60 (single game creation path) may cause a timing-dependent failure that prevents the game from reaching gameplay, or causes it to stall during gameplay.

**Primary recommendation:** The investigation plan should instrument the test to capture where it stalls (setup phase vs gameplay phase), then narrow to specific timing interactions. The most likely root cause is a SocketIO-dependent operation timing out or entering a re-pool loop under 200ms WebSocket latency.

## Critical Discovery: CDP Latency Does Not Affect WebRTC DataChannel

### Evidence

| Finding | Source | Confidence |
|---------|--------|------------|
| CDP `Network.emulateNetworkConditions` latency does NOT affect WebRTC | [Chromium issue 41215664](https://issues.chromium.org/issues/41215664) | HIGH |
| CDP latency = "Minimum latency from request sent to response headers received" | [CDP Network domain docs](https://chromedevtools.github.io/devtools-protocol/tot/Network/) | HIGH |
| CDP has separate WebRTC-specific params: `packetLoss`, `packetQueueLength`, `packetReordering` -- but no WebRTC latency param | CDP Network domain docs | HIGH |
| Chrome throttles WebSocket frames since Chrome 99 | [Chrome DevTools blog](https://developer.chrome.com/blog/new-in-devtools-99) | HIGH |
| CDP throttling is request-level, not packet-level | [DebugBear analysis](https://www.debugbear.com/blog/chrome-devtools-network-throttling) | MEDIUM |

### Implications for the Test

The `apply_latency(page, 200)` call adds 200ms latency to:
- **HTTP requests/responses**: Page load, CDN fetches (Phaser, Pyodide WASM, packages)
- **WebSocket frames**: SocketIO messages (signaling, game events, fallback inputs)
- **NOT**: WebRTC DataChannel messages (P2P game inputs, validation pings, episode sync)

This means the game's P2P input exchange operates at zero artificial latency, while all server-mediated operations (matchmaking, signaling, validation confirmation) operate under 200ms latency.

## Standard Stack

### Test Infrastructure (Existing)

| Component | Location | Purpose |
|-----------|----------|---------|
| `apply_latency()` | `tests/fixtures/network_helpers.py` | CDP latency injection |
| `run_full_episode_flow()` | `tests/e2e/test_latency_injection.py:50` | Full game flow helper |
| `wait_for_episode_complete()` | `tests/fixtures/game_helpers.py:36` | Polls `window.game.num_episodes` |
| `flask_server` fixture | `tests/conftest.py:189` | Module-scoped server on port 5702 |

### Game Configuration (Test)

| Setting | Value | Location |
|---------|-------|----------|
| FPS | 30 | `scenes/scenes.py:431` |
| max_steps | 450 | `overcooked_human_human_multiplayer_test.py:61` |
| Episode duration | ~15 seconds (450/30) | Computed |
| INPUT_DELAY | 3 frames | `scenes/scenes.py:479` |
| input_confirmation_timeout_ms | 2000ms | `overcooked_human_human_multiplayer_test.py:64` |
| P2P ready gate timeout | 5000ms | `pyodide_multiplayer_game.js:1133` |
| P2P validation timeout | 10000ms | `pyodide_multiplayer_game.js:1142` |
| Episode sync timeout | 2000ms | `pyodide_multiplayer_game.js:7312` |
| Snapshot interval | 5 frames | `pyodide_multiplayer_game.js:935` |
| DataChannel | unordered, maxRetransmits=0 | `webrtc_manager.js:237-239` |
| P2P input redundancy | 10 per packet | `pyodide_multiplayer_game.js:5596` |

### Test Timeouts

| Timeout | Value | What it guards |
|---------|-------|----------------|
| pytest.mark.timeout | 300s (5 min) | Entire test |
| setup_timeout | 120000ms (2 min) | Pre-gameplay (buttons, matchmaking, P2P) |
| episode_timeout | 180000ms (3 min) | wait_for_episode_complete |
| socket connect | 30000ms | wait_for_socket_connected |

## Architecture Patterns

### Test Flow Under 200ms Latency

```
1. apply_latency(page1, 200) + apply_latency(page2, 200)
   -- CDP sessions created, Network.emulateNetworkConditions applied

2. page1.goto(base_url) + page2.goto(base_url)
   -- HTML load: +200ms per request
   -- CDN scripts (Phaser, Pyodide, Socket.IO, etc.): +200ms each
   -- Total extra load time: ~1-3 seconds per page

3. wait_for_socket_connected (timeout=30s)
   -- SocketIO WebSocket upgrade: +200ms
   -- register_subject event: +200ms round trip

4. click_advance_button + click_start_button
   -- Browser-local, no latency
   -- But Pyodide preload starts (Phase 67): CDN WASM fetch +200ms
   -- Package installation: multiple CDN fetches +200ms each

5. wait_for_game_canvas (timeout=120s)
   -- Matchmaking: ready_for_game -> pyodide_game_ready via SocketIO (+400ms round trip)
   -- WebRTC signaling: SDP offer/answer/ICE via SocketIO (~800-1200ms total)
   -- DataChannel opens -> validation ping/pong via DataChannel (no extra latency)
   -- p2p_validation_success via SocketIO (+200ms)
   -- Server confirms both -> p2p_validation_complete via SocketIO (+200ms)
   -- TOTAL P2P setup: ~2-4 seconds with 200ms latency (vs ~0.5-1s without)

6. wait_for_game_object + set_tab_visibility
   -- Should be immediate once game starts

7. wait_for_episode_complete(page1, episode_num=1, timeout=180000)
   -- Game runs at 30 FPS via WebWorker timer (NOT affected by CDP)
   -- P2P inputs via DataChannel (NOT affected by CDP)
   -- Episode should complete in ~15 seconds
```

### Potential Stall Points

#### Stall Point A: Pyodide Loading Under Latency (Phase 67/68)

Pyodide WASM (~8MB) is loaded from CDN during the preload phase. With 200ms latency, the initial request gets 200ms added. Package installation (numpy, cogrid, opencv-python) involves multiple CDN requests, each with 200ms added. The `pyodide_loading_start` signal goes through SocketIO (+200ms).

Phase 69 introduced a server-side grace period (`ping_timeout=30`) to handle slow Pyodide loads. This should accommodate 200ms latency. But if the preload races with matchmaking events, the timing could be wrong.

#### Stall Point B: P2P Validation Under Latency (Phase 19)

P2P ready gate timeout is 5000ms. Under 200ms latency, WebRTC signaling takes ~2-4 seconds. The validation itself (ping/pong on DataChannel) is fast. But `p2p_validation_complete` from server goes through SocketIO (+400ms round trip). Total time could approach or exceed 5000ms.

If the P2P ready gate times out BEFORE `p2p_validation_complete` arrives:
- With validation enabled: emits `p2p_validation_failed`
- Server re-pools both players
- Players get `p2p_validation_repool` event
- Test flow would see the game canvas appear and disappear
- `wait_for_game_canvas` would need to detect the second game instance

**This is a strong hypothesis**: The P2P ready gate at 5000ms races against the validation confirmation that takes ~4-5 seconds under 200ms symmetric latency. The 100ms test takes ~2-3 seconds total, well within the gate.

#### Stall Point C: Game Loop Stalled by Rollback Cascades

If the game falls back to SocketIO for inputs (after P2P validation failure and re-pool), every input has 400ms round-trip latency. At 30 FPS:
- Input sent for frame N arrives at peer ~12 frames later
- Peer predicts, then rolls back 12 frames when real input arrives
- Each rollback replays 12 frames through Pyodide Python (expensive)
- If replay takes longer than frame budget (33ms), game falls behind
- This creates a cascade: more frames to replay, each replay takes longer

Even if the game runs, it could be running at effectively 1-3 FPS, making 450 steps take 150-450 seconds. The 180s episode timeout would be exceeded.

#### Stall Point D: Episode End Sync Under Latency

When episode end is detected, `_broadcastEpisodeEnd()` sends via DataChannel (fast). But `_checkEpisodeSyncAndReset()` then calls `_waitForInputConfirmation(2000ms)`. If inputs are flowing through SocketIO (delayed), the confirmation might time out. The episode sync timeout is 2000ms. This shouldn't prevent completion -- it would just add 2 seconds.

### Regression Analysis

Phase 41 verification (2026-01-31) reports the 200ms test as VERIFIED passing. By Phase 70 (2026-02-06), it times out. Changes between these phases that could affect timing:

| Phase | Date | Change | Latency Impact |
|-------|------|--------|----------------|
| 45 | Feb 2 | Episode completion fix | Potential episode end logic change |
| 57 | Feb 3 | P2P probe infrastructure | New WebRTC connection during setup |
| 60 | Feb 3 | Single game creation path | Matchmaking/game creation flow change |
| 61 | Feb 3 | Input confirmation protocol | Added _waitForInputConfirmation at episode end |
| 67 | Feb 6 | Pyodide preload infrastructure | CDN loading during compat check (before startButton) |
| 68 | Feb 6 | Shared instance integration | Pyodide instance reuse |
| 69 | Feb 6 | Server init grace | Changed ping_timeout, added pyodide_loading_start signal |

**High-probability suspects:**
1. **Phase 67/68 (Pyodide preload)**: CDN loading now happens earlier, potentially racing with matchmaking under latency
2. **Phase 60 (Single game creation path)**: Matchmaking flow changes could alter timing
3. **Phase 57 (P2P probe)**: Additional WebRTC connection attempt adds more signaling through latency-delayed SocketIO

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Real WebRTC DataChannel latency testing | CDP Network.emulateNetworkConditions | `tc` (traffic control) on Linux, or Playwright's `route()` to delay DataChannel messages at application level | CDP latency does not affect WebRTC DataChannel |
| Timing instrumentation | Custom logging framework | `page.evaluate()` to read `window.game` state + `console.log` interception | Playwright already provides these |
| Test timeout diagnosis | Manual reproduction | Playwright's `page.on('console')` to capture all console output during test | Shows exactly where game stalls |

## Common Pitfalls

### Pitfall 1: Assuming CDP Latency Affects All Traffic

**What goes wrong:** Test assumes 200ms latency on game inputs, but inputs travel via unaffected DataChannel.
**Why it happens:** CDP documentation describes latency as "request sent to response headers received" -- HTTP semantics. WebRTC DataChannel uses SCTP over DTLS, not HTTP.
**How to avoid:** For true input latency testing, either (a) use OS-level `tc` commands to add latency on loopback, (b) delay inputs at application level via `window.debugRemoteInputDelay`, or (c) use CDP `packetLoss` (the only WebRTC-affecting parameter).
**Warning signs:** Test passes despite "high latency" because game inputs are unaffected.

### Pitfall 2: P2P Ready Gate Race Under Latency

**What goes wrong:** P2P ready gate (5000ms) times out before validation confirmation arrives through latency-delayed SocketIO.
**Why it happens:** Validation succeeds on DataChannel (no latency), but the server confirmation (`p2p_validation_complete`) travels through SocketIO (200ms latency on each hop).
**How to avoid:** Either (a) increase P2P ready gate timeout for latency tests, or (b) separate P2P DataChannel readiness from server validation confirmation.
**Warning signs:** Game appears to start (canvas visible) then re-pools.

### Pitfall 3: SocketIO Fallback Causing Rollback Cascade

**What goes wrong:** After P2P validation failure, game falls back to SocketIO for inputs. Every input has 400ms RTT, causing deep rollbacks at 30 FPS.
**Why it happens:** SocketIO input relay goes through server, incurring 200ms latency each way. 12-frame rollbacks at 30 FPS require replaying through Pyodide Python -- expensive.
**How to avoid:** Ensure P2P establishes successfully so game uses DataChannel for inputs.
**Warning signs:** Console logs show heavy rollback activity, low effective FPS, SocketIO input counters high.

### Pitfall 4: Re-pool Loop Under Latency

**What goes wrong:** Validation fails -> re-pool -> match again -> validation fails again -> infinite loop.
**Why it happens:** Only 2 players in test, so re-pooled players always match together. If the timing issue is deterministic, they'll fail every time.
**How to avoid:** Instrument the test to detect re-pooling events. Add logging for matchmaking flow.
**Warning signs:** Multiple `pyodide_game_ready` events in console, game ID changes.

### Pitfall 5: Pyodide CDN Loading Race with Matchmaking

**What goes wrong:** Pyodide preload (Phase 67) starts CDN downloads. With 200ms latency, downloads take longer. If matchmaking completes before Pyodide is ready, the game start is delayed.
**Why it happens:** Phase 67 moved Pyodide loading earlier but the downstream timing assumptions may not account for 200ms-per-request CDN delays.
**How to avoid:** Check `pyodidePreloadStatus` timing relative to matchmaking events.
**Warning signs:** `startButton` stays disabled longer than expected.

## Investigation Strategy

### Step 1: Determine WHERE the test stalls

Add timing instrumentation to identify which phase of the test is timing out:

```python
# In the test or a diagnostic wrapper
import time

t0 = time.monotonic()
page1.goto(base_url)
page2.goto(base_url)
print(f"[DIAG] Navigation: {time.monotonic() - t0:.1f}s")

t1 = time.monotonic()
wait_for_socket_connected(page1, timeout=30000)
wait_for_socket_connected(page2, timeout=30000)
print(f"[DIAG] Socket connected: {time.monotonic() - t1:.1f}s")

# ... continue timing each phase ...
```

### Step 2: Capture browser console output

```python
# Enable console output capture
def log_handler(msg):
    print(f"[BROWSER-P{player}] {msg.text}")
page1.on("console", lambda msg: print(f"[P1] {msg.text}"))
page2.on("console", lambda msg: print(f"[P2] {msg.text}"))
```

Key console messages to look for:
- `[P2P] Game ready` -- game matched
- `[WebRTC] DataChannel open` -- P2P established
- `P2P validation successful` -- validation passed
- `P2P validation timeout` -- validation FAILED
- `P2P connection timeout` -- ready gate FAILED
- `Web Worker timer started at 30 FPS` -- game loop started
- `[DIAG] frame=...` -- frame progression (every 50 ticks)
- `ROLLBACK:` -- rollback events (indicates late inputs)

### Step 3: Test specific hypotheses

**Hypothesis A (P2P gate race):** Run test with P2P ready gate timeout increased to 15000ms.
**Hypothesis B (SocketIO fallback):** Run test and check `game.p2pMetrics.p2pFallbackTriggered` after game starts.
**Hypothesis C (Pyodide loading):** Check timing of `pyodidePreloadStatus` transitions.
**Hypothesis D (Episode not completing):** If game reaches gameplay, check `game.frameNumber` and `game.step_num` periodically.

### Step 4: Reproduce with reduced timeout

Run with `@pytest.mark.timeout(120)` to get faster feedback. If it hangs, the console output from Step 2 reveals exactly where.

## Code Examples

### Checking P2P vs SocketIO Input Path

```javascript
// In browser console after game starts
console.log({
    p2pConnected: window.game.p2pConnected,
    fallbackTriggered: window.game.p2pMetrics.p2pFallbackTriggered,
    inputsSentViaP2P: window.game.p2pMetrics.inputsSentViaP2P,
    inputsSentViaSocketIO: window.game.p2pMetrics.inputsSentViaSocketIO,
    inputsReceivedViaP2P: window.game.p2pMetrics.inputsReceivedViaP2P,
    inputsReceivedViaSocketIO: window.game.p2pMetrics.inputsReceivedViaSocketIO
});
```

### Checking Frame Progression

```javascript
// Periodically check if game is advancing
console.log({
    frameNumber: window.game.frameNumber,
    step_num: window.game.step_num,
    max_steps: window.game.max_steps,
    num_episodes: window.game.num_episodes,
    state: window.game.state,
    rollbackCount: window.game.rollbackCount,
    confirmedFrame: window.game.confirmedFrame
});
```

### Checking P2P Validation State

```javascript
console.log({
    validationState: window.game.p2pValidation.state,
    gateResolved: window.game.p2pReadyGate.resolved,
    timerWorkerActive: !!window.game.timerWorker
});
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No P2P validation | P2P validation with re-pool on failure | Phase 19 (Jan 22) | Validation failure = game doesn't start |
| Pyodide loaded on game start | Pyodide preloaded during compat check | Phase 67 (Feb 6) | CDN loading moved earlier |
| Direct Pyodide load | Shared Pyodide instance reuse | Phase 68 (Feb 6) | Different initialization timing |
| Fixed ping_timeout | Configurable ping_timeout=30 with grace | Phase 69 (Feb 6) | Longer SocketIO tolerance |
| P2P ready gate = fallback | P2P ready gate = fail if validation enabled | Phase 19 (Jan 22) | No SocketIO fallback, must validate |
| No input confirmation wait | 2000ms input confirmation wait | Phase 61 (Feb 3) | Extra delay at episode boundary |

## Open Questions

1. **Where does the test actually stall?**
   - What we know: The test times out at 300s (the entire pytest timeout)
   - What's unclear: Does it hang during setup (pre-gameplay) or during the episode?
   - Recommendation: Add timing instrumentation per Step 1 above

2. **Is P2P successfully established or does it fallback?**
   - What we know: P2P validation enabled, gate timeout is 5000ms, 200ms latency adds ~2-4s to signaling
   - What's unclear: Whether the race is actually lost under 200ms symmetric latency
   - Recommendation: Capture console output per Step 2, check for validation failure messages

3. **Has the regression been bisected?**
   - What we know: Phase 41 (Jan 31) says 200ms passed. Phase 70 (Feb 6) says it fails.
   - What's unclear: Which specific phase(s) broke it
   - Recommendation: After identifying stall point, review specific phase changes

4. **Does the test need to be redesigned?**
   - What we know: CDP latency does NOT affect WebRTC DataChannel
   - What's unclear: Whether the test should use a different latency injection method
   - Recommendation: After fixing the timeout, consider whether the test actually validates gameplay latency (it doesn't currently)

## Hypothesis Rankings

| # | Hypothesis | Likelihood | Evidence | Test Strategy |
|---|-----------|-----------|----------|---------------|
| 1 | P2P ready gate race: 5s timeout insufficient under 200ms symmetric latency | HIGH | Gate=5s, signaling takes ~2-4s, validation round-trip through SocketIO adds ~1-2s more | Increase gate to 15s and re-run |
| 2 | SocketIO fallback + rollback cascade: if P2P fails, SocketIO inputs at 400ms RTT cause unbounded rollbacks at 30 FPS | MEDIUM | Known that 500ms symmetric latency causes WebRTC signaling timeout. 200ms is borderline. | Check p2pMetrics after game start |
| 3 | Re-pool infinite loop: validation fails -> re-pool -> match -> fail -> re-pool | MEDIUM | Only 2 players, deterministic timing | Look for multiple `pyodide_game_ready` events |
| 4 | Pyodide CDN loading race: preload takes longer under latency, races with matchmaking | LOW | Phase 69 grace period should handle this | Check pyodidePreloadStatus timing |
| 5 | Game loop never starts: timerWorker not initialized due to P2P gate never resolving | MEDIUM | Gate non-resolution = no game loop = no frames | Check timerWorker existence |

## Sources

### Primary (HIGH confidence)
- `tests/e2e/test_latency_injection.py` - Test code, flow, timeouts
- `tests/fixtures/network_helpers.py` - CDP latency injection implementation
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Game loop, GGPO, P2P, validation
- `interactive_gym/server/static/js/webrtc_manager.js` - WebRTC signaling, DataChannel config
- `tests/conftest.py` - Server fixtures, player contexts
- `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer_test.py` - Test config
- `interactive_gym/examples/cogrid/scenes/scenes.py` - FPS, max_steps, input_delay

### Secondary (MEDIUM confidence)
- [Chromium issue 41215664](https://issues.chromium.org/issues/41215664) - CDP throttling does not affect WebRTC
- [CDP Network domain docs](https://chromedevtools.github.io/devtools-protocol/tot/Network/) - latency parameter semantics
- [Chrome DevTools blog - Chrome 99](https://developer.chrome.com/blog/new-in-devtools-99) - WebSocket throttling support
- [DebugBear throttling analysis](https://www.debugbear.com/blog/chrome-devtools-network-throttling) - Request-level vs packet-level

### Tertiary (LOW confidence)
- `.planning/phases/41-latency-injection/41-VERIFICATION.md` - Claims 200ms test passed (Jan 31)
- `.planning/phases/70-validation-test-stabilization/70-01-SUMMARY.md` - Reports 200ms test times out (Feb 6)

## Metadata

**Confidence breakdown:**
- CDP behavior: HIGH - verified with Chromium issue tracker and official docs
- Game architecture: HIGH - direct code analysis of all relevant files
- Root cause hypotheses: MEDIUM - educated analysis but NOT empirically validated
- Regression timing: LOW - based on planning docs, not git bisect

**Research date:** 2026-02-06
**Valid until:** 14 days (fast-moving investigation, findings need empirical validation)
