# Pitfalls Research: Pyodide in Web Worker

**Domain:** WebAssembly in Web Workers, Pyodide-specific Worker issues, Playwright Worker testing
**Researched:** 2026-02-04
**Confidence:** MEDIUM (based on existing codebase experience, Phase 24 research, and training data - WebSearch unavailable)

## Executive Summary

Moving Pyodide to a Web Worker introduces several categories of pitfalls:

1. **Memory management** - WASM linear memory is shared differently in Workers, OOM conditions harder to detect
2. **Startup latency** - Worker + Pyodide initialization compounds startup time
3. **Message passing overhead** - All game state must be serialized/deserialized between Worker and main thread
4. **Debugging complexity** - Worker code has different DevTools debugging experience
5. **Error propagation** - Uncaught errors in Workers require explicit handling

The key insight: **Pyodide itself can run in a Worker, but all DOM/rendering must stay on main thread.** The message passing boundary becomes the critical path.

---

## Critical Pitfalls

These cause crashes, data loss, or fundamental architecture problems.

### Pitfall 1: Worker-Main Thread Memory Boundary

**What goes wrong:** Attempting to share complex objects (NumPy arrays, PyProxy objects, Pyodide state) directly between Worker and main thread fails or corrupts data.

**Why it happens:**
- Web Workers run in isolated JavaScript contexts
- Only serializable data can cross the boundary via `postMessage()`
- Pyodide's Python objects (PyProxy) are NOT transferable
- SharedArrayBuffer requires COOP/COEP headers (complex deployment)

**Consequences:**
- TypeError: "Cannot clone non-transferable object"
- Silent data corruption if objects partially serialize
- Memory leaks from dangling PyProxy references

**Prevention:**
```javascript
// WRONG: Sending Pyodide objects directly
worker.postMessage({ obs: pyodide.globals.get('observation') }); // FAILS

// CORRECT: Serialize to plain JS before sending
const obsArray = pyodide.globals.get('observation').toJs({ depth: 2 });
worker.postMessage({ obs: Array.from(obsArray) });
```

**Detection:**
- Chrome DevTools > Console: "DataCloneError"
- Test with `JSON.parse(JSON.stringify(data))` before postMessage

**Warning signs:**
- "Failed to execute 'postMessage' on 'Worker'"
- Objects crossing boundary become undefined or incomplete

---

### Pitfall 2: Pyodide loadPyodide() Memory Spike

**What goes wrong:** Pyodide's WASM compilation consumes significant memory during initialization, potentially causing OOM in constrained environments.

**Why it happens:**
- Pyodide WASM binary is ~10MB compressed, ~50MB uncompressed
- V8 must compile all WASM functions before execution
- Memory peaks during compilation, then drops
- Multiple concurrent initializations compound the problem

**Consequences:**
- Browser tab crashes with "Aw, Snap!" (Chrome) or "Tab crashed" (Firefox)
- Silent failure with no callback (the issue this milestone addresses)
- Mobile devices particularly vulnerable

**Prevention:**
```javascript
// Stagger Pyodide initialization across games
let pyodideInitQueue = Promise.resolve();

function initPyodideStaggered() {
  pyodideInitQueue = pyodideInitQueue.then(async () => {
    const pyodide = await loadPyodide();
    // Wait 1s before next init
    await new Promise(r => setTimeout(r, 1000));
    return pyodide;
  });
  return pyodideInitQueue;
}
```

**Detection:**
- `performance.measureUserAgentSpecificMemory()` (Chrome only)
- DevTools > Performance > Memory timeline

**Warning signs:**
- Tests fail only with 3+ concurrent games
- Works locally, crashes on CI machines with less memory
- Works on desktop, crashes on mobile

---

### Pitfall 3: Worker Error Propagation

**What goes wrong:** Uncaught errors in Worker code don't automatically surface to main thread, causing silent failures.

**Why it happens:**
- Workers are isolated - errors don't bubble to main thread try/catch
- `worker.onerror` only fires for errors BEFORE script execution
- Errors DURING execution require explicit postMessage

**Consequences:**
- Worker silently stops responding
- Main thread waits forever for response
- User sees hung UI with no error message

**Prevention:**
```javascript
// In Worker:
try {
  const result = await pyodide.runPythonAsync(code);
  self.postMessage({ type: 'result', data: result });
} catch (e) {
  self.postMessage({
    type: 'error',
    error: { message: e.message, stack: e.stack, name: e.name }
  });
}

// In main thread:
worker.onmessage = (e) => {
  if (e.data.type === 'error') {
    console.error('[Worker Error]', e.data.error);
    this._handleWorkerError(e.data.error);
  }
};

worker.onerror = (e) => {
  console.error('[Worker Uncaught]', e.message, e.filename, e.lineno);
};
```

**Detection:**
- Add timeout to all Worker requests
- Log at Worker entry/exit points

**Warning signs:**
- Game freezes with no console errors
- "Waiting for X..." messages that never resolve

---

### Pitfall 4: Module Import in Workers

**What goes wrong:** ES6 module imports work differently in Workers, causing "Failed to fetch" or "Unexpected token" errors.

**Why it happens:**
- Workers traditionally use `importScripts()` for synchronous loading
- ES6 modules in Workers require `type: "module"` in Worker constructor
- Mixed module/non-module imports cause issues
- Relative paths resolve differently in Workers

**Consequences:**
- Worker fails to start
- Missing dependencies at runtime
- Works locally but fails when bundled

**Prevention:**
```javascript
// Option 1: Inline Worker with all code (current timer pattern)
const workerCode = `
  // ALL dependencies inline
  importScripts('https://cdn.jsdelivr.net/pyodide/v0.25.0/full/pyodide.js');

  self.onmessage = async function(e) { ... };
`;
const blob = new Blob([workerCode], { type: 'application/javascript' });
const worker = new Worker(URL.createObjectURL(blob));

// Option 2: Separate file with module syntax
const worker = new Worker('/static/js/pyodide_worker.js', { type: 'module' });
// pyodide_worker.js uses: import { ... } from './helper.js';
```

**Detection:**
- Check DevTools > Sources > Workers for loaded scripts
- Watch Network tab for 404s from Worker context

**Warning signs:**
- "SyntaxError: Cannot use import statement outside a module"
- "importScripts failed for ..."

---

## Moderate Pitfalls

These cause delays, degraded performance, or technical debt.

### Pitfall 5: postMessage Serialization Overhead

**What goes wrong:** Large game state transfers (observations, render data) cause frame drops due to serialization time.

**Why it happens:**
- postMessage uses structured clone algorithm
- Each message copies data (no shared memory by default)
- At 30fps with large observations, serialization becomes bottleneck

**Consequences:**
- Frame rate drops when sending state
- Janky rendering during gameplay
- Memory pressure from cloned data

**Prevention:**
```javascript
// 1. Use Transferable objects for ArrayBuffers (zero-copy)
const obsBuffer = new Float32Array(observation).buffer;
worker.postMessage({ obs: obsBuffer }, [obsBuffer]);
// NOTE: obsBuffer is now detached in sender!

// 2. Send only deltas, not full state
worker.postMessage({
  type: 'partial_state',
  changedFields: ['reward', 'terminated']
});

// 3. Reduce transfer frequency (don't need state every tick)
if (frameNumber % 3 === 0) {
  mainThread.postMessage({ renderState: ... });
}
```

**Detection:**
- Performance.measure around postMessage calls
- DevTools > Performance > Main thread flame chart

**Warning signs:**
- Frame time spikes correlate with postMessage calls
- `[Worker -> Main]` messages in timeline show high duration

---

### Pitfall 6: Race Conditions During Initialization

**What goes wrong:** Main thread sends messages to Worker before Pyodide is fully initialized, causing missed commands.

**Why it happens:**
- Worker script loads immediately, but loadPyodide() is async
- Main thread doesn't know when Pyodide is ready
- Messages sent before ready are lost or error

**Consequences:**
- First game command silently fails
- "pyodide is not defined" errors
- Intermittent test failures

**Prevention:**
```javascript
// In Worker:
let pyodideReady = false;
const messageQueue = [];

loadPyodide().then(p => {
  pyodide = p;
  pyodideReady = true;
  self.postMessage({ type: 'ready' });
  // Process queued messages
  messageQueue.forEach(msg => handleMessage(msg));
});

self.onmessage = (e) => {
  if (pyodideReady) {
    handleMessage(e.data);
  } else {
    messageQueue.push(e.data);
  }
};

// In main thread:
await new Promise(resolve => {
  worker.onmessage = (e) => {
    if (e.data.type === 'ready') resolve();
  };
});
// Now safe to send commands
```

**Detection:**
- Add ready-check assertion before first Worker call
- Log Worker message timestamps

**Warning signs:**
- First game sometimes fails, retry works
- `pyodide is undefined` only on first message

---

### Pitfall 7: Package Installation Timing

**What goes wrong:** `micropip.install()` is slow and blocks Worker; main thread assumes packages are ready too early.

**Why it happens:**
- Package installation downloads from PyPI, extracts wheels
- Can take 5-30 seconds depending on packages
- cogrid, numpy, etc. are large packages

**Consequences:**
- ImportError: No module named 'cogrid'
- Main thread shows game UI before environment is ready

**Prevention:**
```javascript
// In Worker:
async function initialize(packages) {
  const pyodide = await loadPyodide();

  for (const pkg of packages) {
    self.postMessage({ type: 'progress', status: `Installing ${pkg}...` });
    await pyodide.loadPackage(pkg.split('@')[0]); // Handle git URLs
  }

  self.postMessage({ type: 'packages_ready' });
  return pyodide;
}

// In main thread:
worker.onmessage = (e) => {
  if (e.data.type === 'progress') {
    updateLoadingUI(e.data.status);
  } else if (e.data.type === 'packages_ready') {
    showGameUI();
  }
};
```

**Detection:**
- Time package installation separately from Pyodide init
- Log which packages take longest

**Warning signs:**
- Long pause after "Loading Pyodide..." before game appears
- ImportError on first environment creation

---

### Pitfall 8: NumPy Array Type Conversion

**What goes wrong:** NumPy arrays require explicit conversion to JavaScript types; default toJs() may produce unexpected results.

**Why it happens:**
- Pyodide's toJs() has configurable depth and converters
- NumPy dtypes don't always map 1:1 to JS TypedArrays
- Nested arrays need recursive conversion

**Consequences:**
- Observations arrive as PyProxy instead of Arrays
- dtype mismatch causes rendering glitches
- Memory leak from unconverted PyProxy

**Prevention:**
```python
# In Worker Python code:
import numpy as np
import json

# Convert NumPy to Python lists (safe for JSON)
def safe_serialize(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: safe_serialize(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [safe_serialize(v) for v in obj]
    else:
        return obj

serialized_obs = safe_serialize(observation)
```

```javascript
// In Worker JS:
const result = await pyodide.runPythonAsync(`
  safe_serialize(env.step(${JSON.stringify(action)}))
`);
// result is now plain JS object
```

**Detection:**
- Check typeof observation in main thread
- Log when PyProxy appears unexpectedly

**Warning signs:**
- Renderer receives `[object Object]` instead of array
- Memory grows over time (PyProxy leak)

---

## Minor Pitfalls

These cause annoyance but are fixable.

### Pitfall 9: Worker DevTools Debugging

**What goes wrong:** Setting breakpoints in Worker code is awkward; console.log output can be missed.

**Why it happens:**
- Workers appear in separate DevTools context
- Need to enable "Workers" in Sources panel
- Console output may go to wrong console

**Prevention:**
```javascript
// 1. Use dedicated logging that prefixes Worker messages
function workerLog(...args) {
  console.log('[Worker]', ...args);
  self.postMessage({ type: 'log', args: args.map(String) });
}

// 2. In Chrome: DevTools > Sources > "Threads" panel > Select Worker
// 3. In Firefox: DevTools > Debugger > Workers section

// 4. Add debug mode that forwards all console methods
if (debugMode) {
  ['log', 'warn', 'error'].forEach(method => {
    const original = console[method];
    console[method] = (...args) => {
      self.postMessage({ type: 'console', method, args: args.map(String) });
      original.apply(console, args);
    };
  });
}
```

**Detection:**
- Check both main and Worker consoles
- Use `debugger;` statement to force breakpoint

---

### Pitfall 10: Worker Termination Cleanup

**What goes wrong:** Terminated Workers leave memory unreleased; Blob URLs accumulate.

**Why it happens:**
- `worker.terminate()` is forceful, doesn't run cleanup
- Blob URLs created with `URL.createObjectURL()` must be explicitly revoked
- Pyodide resources aren't garbage collected immediately

**Prevention:**
```javascript
// Graceful shutdown
async terminateWorker() {
  // 1. Ask Worker to cleanup
  this.worker.postMessage({ type: 'shutdown' });

  // 2. Wait for acknowledgment (with timeout)
  await Promise.race([
    new Promise(r => {
      this.worker.onmessage = (e) => {
        if (e.data.type === 'shutdown_complete') r();
      };
    }),
    new Promise(r => setTimeout(r, 1000)) // 1s timeout
  ]);

  // 3. Terminate and cleanup
  this.worker.terminate();
  URL.revokeObjectURL(this.workerBlobUrl);
  this.worker = null;
}

// In Worker:
self.onmessage = (e) => {
  if (e.data.type === 'shutdown') {
    // Release Pyodide resources
    if (pyodide) {
      pyodide.globals.destroy();
      pyodide = null;
    }
    self.postMessage({ type: 'shutdown_complete' });
  }
};
```

**Detection:**
- Chrome DevTools > Memory > Heap snapshot
- Check for growing number of Workers in Application panel

**Warning signs:**
- Memory grows across multiple games
- DevTools shows many terminated Workers

---

## Pyodide-Specific Worker Issues

### Issue 1: runPythonAsync Interleaving

**Problem:** Multiple concurrent `runPythonAsync()` calls can interleave if not properly awaited.

**Manifestation:**
- Race conditions in environment state
- "Variable X is not defined" errors
- Inconsistent game state

**Solution:**
```javascript
// Use a mutex/queue for Python execution
let pythonLock = Promise.resolve();

async function runPythonSafe(code) {
  const myTurn = pythonLock;
  let resolve;
  pythonLock = new Promise(r => resolve = r);

  await myTurn;
  try {
    return await pyodide.runPythonAsync(code);
  } finally {
    resolve();
  }
}
```

### Issue 2: Keyboard Interrupt Handling

**Problem:** Long-running Python code can't be interrupted from main thread.

**Manifestation:**
- Worker becomes unresponsive during heavy computation
- Can't cancel stuck operations

**Solution:**
```javascript
// Use Pyodide's interrupt mechanism
pyodide.setInterruptBuffer(interruptBuffer);

// In main thread:
function interruptWorker() {
  Atomics.store(interruptBuffer, 0, 2); // 2 = interrupt signal
}

// Note: Requires SharedArrayBuffer and COOP/COEP headers
```

### Issue 3: Stdout/Stderr Capture

**Problem:** Python print() statements disappear in Worker context.

**Manifestation:**
- Debug prints not visible
- Error messages lost

**Solution:**
```python
# In Worker initialization:
import sys
from io import StringIO

class OutputCapture:
    def __init__(self, post_message_fn):
        self.buffer = StringIO()
        self.post_message = post_message_fn

    def write(self, text):
        self.buffer.write(text)
        if text.endswith('\n'):
            self.post_message('stdout', self.buffer.getvalue())
            self.buffer = StringIO()

    def flush(self):
        if self.buffer.getvalue():
            self.post_message('stdout', self.buffer.getvalue())
            self.buffer = StringIO()

sys.stdout = OutputCapture(post_stdout)
sys.stderr = OutputCapture(post_stderr)
```

---

## Playwright Worker Testing

### What Playwright CAN Test

Based on Phase 24 research and Playwright documentation:

1. **Worker creation/termination**
   - Can detect when Workers are created via `page.workers()`
   - Can listen for Worker events: `page.on('worker', ...)`

2. **Worker messages (indirectly)**
   - Can observe main thread effects of Worker messages
   - Can verify game state changes after Worker processing

3. **Worker errors**
   - `page.on('pageerror')` catches Worker errors that propagate
   - Can verify error handling UI appears

4. **Timing behavior**
   - Can test that games progress when tab is backgrounded
   - Can verify Worker maintains timing accuracy

### What Playwright CANNOT Test

1. **Worker internal state**
   - Cannot directly execute code inside Worker
   - Cannot access Worker-scoped variables

2. **Worker-specific breakpoints**
   - Playwright doesn't support Worker debugging

3. **postMessage content directly**
   - Must infer from main thread behavior

### Testing Strategies for Workers

```python
# Test Worker creation
def test_pyodide_worker_created(page, flask_server):
    """Verify Pyodide Worker is created on game start."""
    page.goto(base_url)

    # Wait for Worker to be created
    worker_created = page.evaluate("""
        () => new Promise(resolve => {
            // Either Worker already exists or wait for it
            if (window.pyodideWorker) {
                resolve(true);
            } else {
                const check = setInterval(() => {
                    if (window.pyodideWorker) {
                        clearInterval(check);
                        resolve(true);
                    }
                }, 100);
            }
        })
    """)

    assert worker_created, "Pyodide Worker should be created"

# Test Worker survives main thread blocking
def test_worker_timing_during_block(page, flask_server):
    """Verify Worker maintains timing when main thread is blocked."""
    # Start game
    run_full_episode_flow_until_gameplay(page1, page2, base_url)

    # Get frame count
    frame_before = get_game_state(page1)["frameNumber"]

    # Block main thread briefly (simulate heavy UI work)
    page1.evaluate("() => { const start = Date.now(); while (Date.now() - start < 500) {} }")

    # Verify frames still advanced (Worker drove timing)
    time.sleep(0.1)
    frame_after = get_game_state(page1)["frameNumber"]

    assert frame_after > frame_before, "Game should progress despite main thread block"

# Test Worker error handling
def test_worker_error_surfaces(page, flask_server):
    """Verify Worker errors are reported to user."""
    # ... setup game ...

    # Inject error in Worker (if possible via eval)
    # Or trigger known error condition

    # Verify error overlay appears
    error_visible = page.is_visible("#errorOverlay")
    assert error_visible, "Error overlay should appear on Worker failure"
```

### Testing Multi-Game Concurrent Initialization

The primary use case - remove the 5s stagger delay:

```python
def test_no_socket_disconnect_during_concurrent_init(multi_participant_contexts, flask_server):
    """
    Verify Socket.IO stays connected when 3 games initialize Pyodide simultaneously.

    This is the key test for v1.16 - with Pyodide in Worker, main thread stays
    responsive for Socket.IO ping/pong, eliminating false disconnects.
    """
    pages = multi_participant_contexts
    base_url = flask_server["url"]

    orchestrator = GameOrchestrator(pages, base_url)

    # Start all 3 games with ZERO stagger (previously required 5s)
    orchestrator.start_all_games(stagger_delay_sec=0.0)

    # Verify all games started without disconnection
    for game_idx in range(3):
        page1, page2 = orchestrator.games[game_idx]

        # Socket should still be connected
        assert page1.evaluate("window.socket && window.socket.connected")
        assert page2.evaluate("window.socket && window.socket.connected")

        # Game should be running
        state = get_game_state(page1)
        assert state is not None, f"Game {game_idx} should have started"

    # Wait for completion with parity validation
    results = orchestrator.wait_for_all_episodes_with_parity(episode_num=1)

    for game_idx, status in results.items():
        assert status["success"], f"Game {game_idx} should complete with parity"
```

---

## Debugging Techniques

### Technique 1: Worker Message Logging

```javascript
// Wrap postMessage to log all traffic
const originalPostMessage = worker.postMessage.bind(worker);
worker.postMessage = (data, transfer) => {
  console.log('[Main -> Worker]', data.type, data);
  originalPostMessage(data, transfer);
};

const originalOnMessage = worker.onmessage;
worker.onmessage = (e) => {
  console.log('[Worker -> Main]', e.data.type, e.data);
  originalOnMessage(e);
};
```

### Technique 2: Worker Performance Profiling

```javascript
// In Worker - measure operation times
const perfMark = (name) => {
  performance.mark(name);
  self.postMessage({ type: 'perf_mark', name, time: performance.now() });
};

// Usage:
perfMark('pyodide_init_start');
const pyodide = await loadPyodide();
perfMark('pyodide_init_end');

perfMark('packages_start');
await micropip.install('cogrid');
perfMark('packages_end');
```

### Technique 3: State Snapshots

```javascript
// Periodically dump Worker state for debugging
setInterval(() => {
  self.postMessage({
    type: 'debug_state',
    timestamp: Date.now(),
    state: {
      frameNumber: currentFrame,
      queuedMessages: messageQueue.length,
      memoryUsage: performance.memory?.usedJSHeapSize || 'N/A'
    }
  });
}, 5000);
```

### Technique 4: Error Context Enrichment

```javascript
// Add context to errors before sending to main thread
function enrichError(error, context) {
  return {
    message: error.message,
    stack: error.stack,
    name: error.name,
    context: {
      ...context,
      timestamp: Date.now(),
      frameNumber: currentFrame,
      lastCommand: lastReceivedCommand
    }
  };
}
```

---

## Performance Gotchas

### Gotcha 1: Serialization Cost Grows with State Size

**Impact:** O(n) serialization time where n = observation size
**Mitigation:** Use Transferable objects or reduce transfer frequency

### Gotcha 2: Worker Thread Startup Is Not Free

**Impact:** ~50-100ms to create Worker + additional Pyodide init time
**Mitigation:** Pre-create Worker during loading screen, reuse across games

### Gotcha 3: Memory Duplication

**Impact:** Data exists in both Worker and main thread memory
**Mitigation:** Don't store game state in both places; Worker is authoritative

### Gotcha 4: GC Pauses in Both Contexts

**Impact:** Worker and main thread GC independently, can compound jank
**Mitigation:** Pool objects, avoid allocation during game loop

---

## Integration with Existing Codebase

### Current Architecture (from docs/multiplayer_pyodide_implementation.md)

```
Main Thread:
  - MultiplayerPyodideGame (runs Pyodide, GGPO sync)
  - WebRTCManager (P2P DataChannel)
  - Phaser rendering
  - Socket.IO communication
```

### Target Architecture (v1.16)

```
Main Thread:
  - MultiplayerPyodideGame (orchestrates, no Pyodide)
  - WebRTCManager (P2P DataChannel)
  - Phaser rendering
  - Socket.IO communication (STAYS RESPONSIVE)

Web Worker:
  - PyodideWorker (owns Pyodide instance)
  - Environment execution
  - GGPO state management
  - NumPy/Python computation
```

### Critical Boundary: State Sync

The GGPO state buffer currently lives in main thread. Options:

1. **Move to Worker (recommended):** Worker is authoritative, sends render state to main thread
2. **Keep in main thread:** Worker sends step results, main thread manages GGPO
3. **Split:** Worker handles Python state, main thread handles input history

**Recommendation:** Option 1 - Worker owns all game state, main thread is pure renderer.

---

## Recommendations for v1.16

### Priority 1: Prevent the Original Bug

1. **loadPyodide() in Worker** - Unblocks main thread for Socket.IO
2. **Progress events** - User knows something is happening
3. **Error propagation** - Failures surface to user, don't hang

### Priority 2: Maintain Performance

4. **Efficient state transfer** - Use Transferables for render data
5. **Reduced transfer frequency** - Only send what rendering needs
6. **Pre-warm Worker** - Initialize during loading screen

### Priority 3: Debuggability

7. **Message logging** - All Worker traffic logged in dev mode
8. **Error enrichment** - Context attached to all Worker errors
9. **State snapshots** - Periodic debug dumps

### Priority 4: Testing

10. **Zero-stagger test** - Verify 3 concurrent games without disconnects
11. **Worker health checks** - Verify Worker responds to ping
12. **Memory monitoring** - No leaks across game sessions

---

## Confidence Assessment

| Area | Confidence | Rationale |
|------|------------|-----------|
| Memory boundary pitfalls | HIGH | Well-documented Web Worker limitation |
| Pyodide init memory spike | HIGH | Observed in Phase 64/65 multi-participant tests |
| Error propagation | HIGH | Standard Worker behavior |
| Playwright capabilities | MEDIUM | Based on docs, not hands-on testing |
| Performance tuning | MEDIUM | General patterns, project-specific tuning needed |
| GGPO integration | LOW | Requires implementation exploration |

---

## Sources

- Phase 24 Research (Web Worker Timer Infrastructure) - `/Users/chasemcd/Repositories/interactive-gym/.planning/phases/24-web-worker-timer/24-RESEARCH.md`
- multiplayer_pyodide_implementation.md - `/Users/chasemcd/Repositories/interactive-gym/docs/multiplayer_pyodide_implementation.md`
- Existing codebase analysis - `pyodide_multiplayer_game.js`, `game_manager.py`
- MDN Web Workers API - https://developer.mozilla.org/en-US/docs/Web/API/Worker
- Pyodide Documentation - https://pyodide.org/en/stable/usage/webworker.html (based on training data)
- Playwright Workers documentation - https://playwright.dev/docs/api/class-worker

**Note:** WebSearch was unavailable during this research. Findings are based on existing codebase experience, Phase 24 research, and Claude's training data. Verify with official documentation when implementing.
