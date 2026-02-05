# Phase 67: Core Worker Infrastructure - Research

**Researched:** 2026-02-04
**Domain:** Web Workers, Pyodide WASM, postMessage API
**Confidence:** HIGH

## Summary

Phase 67 creates the foundational PyodideWorker infrastructure that Phase 68-70 will build upon. This is a well-understood domain with existing patterns in the codebase (GameTimerWorker from Phase 24) and comprehensive project research (STACK.md, PITFALLS.md, ARCHITECTURE.md).

The core task is straightforward: create `pyodide_worker.js` (runs in Worker thread) and `PyodideWorker` class (main thread manager) with typed message protocol. The existing project research already defines the exact patterns to use.

**Primary recommendation:** Follow the postMessage pattern from STACK.md with typed messages (init, step, reset, ready, result, error). Use separate worker file (not inline Blob) for easier debugging. Implement READY gate pattern from PITFALLS.md to prevent race conditions.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Web Worker (native) | N/A | Isolate Pyodide from main thread | Native API, no dependencies |
| Pyodide | 0.26.2 | Python in WASM | Already in use, CDN-hosted |
| postMessage API | N/A | Main <-> Worker communication | Native, full control |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Transferable Objects | N/A | Zero-copy ArrayBuffer transfer | Large data (render_state) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| postMessage | Comlink | RPC abstraction doesn't fit async WASM with progress events |
| Separate file | Inline Blob | Blob harder to debug, current GameTimerWorker uses inline but Pyodide is more complex |
| SharedArrayBuffer | postMessage | Requires COOP/COEP headers, overkill for this use case |

**Installation:**
```bash
# No new packages needed - all native APIs and existing Pyodide CDN
```

## Architecture Patterns

### Recommended Project Structure
```
interactive_gym/server/static/js/
├── pyodide_worker.js        # Worker script (NEW - Phase 67)
├── PyodideWorker.js         # Main thread class (NEW - Phase 67)
├── pyodide_remote_game.js   # RemoteGame (MODIFIED - Phase 68)
├── pyodide_multiplayer_game.js  # MultiplayerPyodideGame (MODIFIED - Phase 69)
├── phaser_gym_graphics.js   # Unchanged
└── index.html               # Add pyodide_worker.js script tag
```

### Pattern 1: Typed Message Protocol
**What:** All Worker messages include `type` and `id` fields for routing and correlation
**When to use:** Always - this enables reliable request/response tracking
**Example:**
```javascript
// Source: .planning/research/STACK.md lines 256-267
// Main -> Worker
{ type: 'init', id: 1, payload: { indexURL: '...', packages: [...] } }
{ type: 'step', id: 2, payload: { actions: {...} } }
{ type: 'reset', id: 3, payload: { seed: 12345 } }

// Worker -> Main
{ type: 'progress', id: 1, stage: 'loading', message: '...' }
{ type: 'ready', id: 1 }
{ type: 'result', id: 2, result: {...} }
{ type: 'error', id: 3, error: { message: '...', stack: '...' } }
```

### Pattern 2: READY Gate (Prevents Race Conditions)
**What:** Worker queues messages until Pyodide fully loaded, sends READY event, main thread awaits READY before sending commands
**When to use:** Always - prevents "pyodide is undefined" errors
**Example:**
```javascript
// Source: .planning/research/PITFALLS.md lines 255-283
// In Worker:
let pyodideReady = false;
const messageQueue = [];

loadPyodide().then(p => {
  pyodide = p;
  pyodideReady = true;
  self.postMessage({ type: 'ready' });
  messageQueue.forEach(msg => handleMessage(msg));
});

self.onmessage = (e) => {
  if (pyodideReady) {
    handleMessage(e.data);
  } else {
    messageQueue.push(e.data);
  }
};

// In main thread (PyodideWorker.init()):
await new Promise(resolve => {
  const handler = (e) => {
    if (e.data.type === 'ready') {
      this.ready = true;
      resolve();
    }
  };
  this.worker.addEventListener('message', handler);
});
```

### Pattern 3: Request/Response Correlation via ID
**What:** Each request gets unique ID, responses include same ID, Map tracks pending promises
**When to use:** Any async Worker call that expects a result
**Example:**
```javascript
// Source: .planning/research/STACK.md lines 184-194
_sendRequest(type, payload) {
    return new Promise((resolve, reject) => {
        const id = this._nextId();
        this.pendingRequests.set(id, { resolve, reject });
        this.worker.postMessage({ type, id, payload });
    });
}

_handleMessage(event) {
    const { type, id, result, error } = event.data;
    const pending = this.pendingRequests.get(id);
    if (!pending) return;
    this.pendingRequests.delete(id);
    if (type === 'error') {
        pending.reject(new Error(error.message));
    } else {
        pending.resolve(result);
    }
}
```

### Pattern 4: Error Propagation
**What:** Worker catches all errors, sends error message with stack trace, main thread rejects corresponding promise
**When to use:** Always - prevents silent failures
**Example:**
```javascript
// Source: .planning/research/PITFALLS.md lines 117-139
// In Worker:
try {
  const result = await pyodide.runPythonAsync(code);
  self.postMessage({ type: 'result', id, data: result });
} catch (e) {
  self.postMessage({
    type: 'error',
    id,
    error: { message: e.message, stack: e.stack, name: e.name }
  });
}

// In main thread:
worker.onerror = (e) => {
  console.error('[Worker Uncaught]', e.message, e.filename, e.lineno);
};
```

### Anti-Patterns to Avoid
- **Sending PyProxy objects via postMessage:** TypeError, must convert to JS first with `.toJs()`
- **Calling Worker before READY:** Undefined pyodide, intermittent failures
- **Missing error handler:** Silent worker failures, hung UI
- **Concurrent runPythonAsync without mutex:** Race conditions in Python state

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Request/Response tracking | Simple callback system | Map<id, {resolve, reject}> with auto-incrementing IDs | Handles out-of-order responses, timeouts |
| Worker creation | Inline eval | Separate .js file loaded via `new Worker()` | Easier debugging, source maps work |
| Pyodide type conversion | Manual JSON.stringify | `pyodide.toPy()` and `.toJs()` methods | Handles NumPy, dicts, nested structures |
| Progress events | Polling | Worker posts progress messages during init | Real-time UI updates, no polling overhead |

**Key insight:** The project research (STACK.md, PITFALLS.md, ARCHITECTURE.md) already provides battle-tested patterns. Phase 67 should implement these patterns exactly, not innovate.

## Common Pitfalls

### Pitfall 1: Worker-Main Thread Memory Boundary
**What goes wrong:** Attempting to share PyProxy objects or Pyodide state directly via postMessage
**Why it happens:** Workers have isolated JavaScript contexts, only serializable data transfers
**How to avoid:** Always convert Python objects to JS before postMessage: `result.toJs({ depth: 2 })`
**Warning signs:** "DataCloneError", "Cannot clone non-transferable object"

### Pitfall 2: Race Conditions During Initialization
**What goes wrong:** Main thread sends step/reset before Pyodide loaded
**Why it happens:** Worker script loads immediately, loadPyodide() is async
**How to avoid:** READY gate pattern - await ready event before sending commands
**Warning signs:** "pyodide is not defined", first game fails but retry works

### Pitfall 3: Uncaught Worker Errors
**What goes wrong:** Errors during Python execution silently swallow
**Why it happens:** Worker errors don't bubble to main thread try/catch
**How to avoid:** Wrap all Worker async code in try/catch, post error messages explicitly
**Warning signs:** Worker stops responding, no console errors, hung UI

### Pitfall 4: Module Import in Workers
**What goes wrong:** "Failed to fetch" or "Unexpected token" when loading Worker
**Why it happens:** Workers use `importScripts()` not ES6 imports by default
**How to avoid:** Use `importScripts()` for Pyodide CDN, or `type: "module"` if using ES6
**Warning signs:** "Cannot use import statement outside a module"

### Pitfall 5: Worker Console Logs Hidden
**What goes wrong:** console.log in Worker not visible in main DevTools console
**Why it happens:** Workers run in separate context
**How to avoid:** Post log messages to main thread, or check Worker-specific console in DevTools
**Warning signs:** Debug logs don't appear, hard to diagnose issues

## Code Examples

Verified patterns from project research:

### Worker Script (pyodide_worker.js)
```javascript
// Source: .planning/research/STACK.md lines 44-106
importScripts('https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.js');

let pyodide = null;
let pyodideReady = false;
const messageQueue = [];

// Load Pyodide immediately on Worker start
const initPromise = (async () => {
    self.postMessage({ type: 'progress', stage: 'loading', message: 'Loading Pyodide...' });
    pyodide = await loadPyodide();

    self.postMessage({ type: 'progress', stage: 'micropip', message: 'Loading micropip...' });
    await pyodide.loadPackage('micropip');

    pyodideReady = true;
    self.postMessage({ type: 'ready' });

    // Process any queued messages
    while (messageQueue.length > 0) {
        await handleMessage(messageQueue.shift());
    }
})();

self.onmessage = async function(event) {
    if (!pyodideReady) {
        messageQueue.push(event.data);
        return;
    }
    await handleMessage(event.data);
};

async function handleMessage(msg) {
    const { type, id, payload } = msg;

    try {
        switch (type) {
            case 'installPackages':
                await handleInstallPackages(id, payload);
                break;
            case 'initEnv':
                await handleInitEnv(id, payload);
                break;
            case 'step':
                await handleStep(id, payload);
                break;
            case 'reset':
                await handleReset(id, payload);
                break;
        }
    } catch (error) {
        self.postMessage({
            type: 'error',
            id,
            error: { message: error.message, stack: error.stack }
        });
    }
}

async function handleInstallPackages(id, payload) {
    const micropip = pyodide.pyimport('micropip');
    for (const pkg of payload.packages) {
        self.postMessage({ type: 'progress', id, stage: 'install', message: `Installing ${pkg}...` });
        await micropip.install(pkg);
    }
    self.postMessage({ type: 'installed', id });
}

async function handleInitEnv(id, payload) {
    // Run environment initialization code
    await pyodide.runPythonAsync(payload.envCode);
    self.postMessage({ type: 'envReady', id });
}

async function handleStep(id, payload) {
    // Step the environment
    const result = await pyodide.runPythonAsync(`
import numpy as np
agent_actions = ${JSON.stringify(payload.actions)}
obs, rewards, terminateds, truncateds, infos = env.step(agent_actions)
render_state = env.render()
(obs, rewards, terminateds, truncateds, infos, render_state)
    `);

    // Convert to JS for transfer
    const [obs, rewards, terminateds, truncateds, infos, render_state] = result.toJs();

    self.postMessage({
        type: 'result',
        id,
        result: { obs, rewards, terminateds, truncateds, infos, render_state }
    });
}

async function handleReset(id, payload) {
    const result = await pyodide.runPythonAsync(`
import numpy as np
obs, infos = env.reset(seed=${payload.seed || 'None'})
render_state = env.render()
(obs, infos, render_state)
    `);

    const [obs, infos, render_state] = result.toJs();

    self.postMessage({
        type: 'result',
        id,
        result: { obs, infos, render_state }
    });
}
```

### Main Thread Class (PyodideWorker.js)
```javascript
// Source: .planning/research/STACK.md lines 117-234
export class PyodideWorker {
    constructor(options = {}) {
        this.worker = null;
        this.pendingRequests = new Map();
        this.requestCounter = 0;
        this.onProgress = options.onProgress || null;
        this.ready = false;
    }

    async init() {
        return new Promise((resolve, reject) => {
            this.worker = new Worker('/static/js/pyodide_worker.js');

            this.worker.onmessage = (event) => this._handleMessage(event);
            this.worker.onerror = (error) => {
                console.error('[PyodideWorker] Uncaught error:', error);
                reject(error);
            };

            // Wait for READY event
            const readyHandler = (event) => {
                if (event.data.type === 'ready') {
                    this.ready = true;
                    resolve();
                }
            };
            this.worker.addEventListener('message', readyHandler, { once: false });
        });
    }

    async installPackages(packages) {
        return this._sendRequest('installPackages', { packages });
    }

    async initEnv(envCode) {
        return this._sendRequest('initEnv', { envCode });
    }

    async step(actions) {
        return this._sendRequest('step', { actions });
    }

    async reset(seed = null) {
        return this._sendRequest('reset', { seed });
    }

    destroy() {
        if (this.worker) {
            this.worker.terminate();
            this.worker = null;
        }
        this.pendingRequests.clear();
    }

    _nextId() {
        return ++this.requestCounter;
    }

    _sendRequest(type, payload) {
        return new Promise((resolve, reject) => {
            if (!this.ready && type !== 'init') {
                reject(new Error('PyodideWorker not ready'));
                return;
            }
            const id = this._nextId();
            this.pendingRequests.set(id, { resolve, reject });
            this.worker.postMessage({ type, id, payload });
        });
    }

    _handleMessage(event) {
        const { type, id, result, error, stage, message } = event.data;

        // Handle progress events
        if (type === 'progress') {
            if (this.onProgress) {
                this.onProgress(stage, message);
            }
            return;
        }

        // Handle ready event (init resolves elsewhere)
        if (type === 'ready') {
            return;
        }

        // Handle request/response
        const pending = this.pendingRequests.get(id);
        if (!pending) return;

        this.pendingRequests.delete(id);

        switch (type) {
            case 'installed':
            case 'envReady':
                pending.resolve();
                break;
            case 'result':
                pending.resolve(result);
                break;
            case 'error':
                pending.reject(new Error(error.message));
                break;
        }
    }
}
```

### Non-Blocking Verification Test
```javascript
// Source: Phase 67 success criteria #3
// Main thread can run console.log('ping') every 500ms during Pyodide init without interruption
async function testNonBlocking() {
    let pings = 0;
    const pingInterval = setInterval(() => {
        console.log('ping', ++pings);
    }, 500);

    const worker = new PyodideWorker({
        onProgress: (stage, msg) => console.log(`[Progress] ${stage}: ${msg}`)
    });

    await worker.init();  // This should NOT block the pings

    clearInterval(pingInterval);
    console.log(`Non-blocking verified: ${pings} pings during init`);
    // Expect 10-30 pings during typical 5-15 second init
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Main thread Pyodide | Worker thread Pyodide | This milestone | Non-blocking init |
| Inline Blob workers | Separate .js file | This phase | Better debugging |
| No progress events | Progress callbacks | This phase | Better UX during load |

**Deprecated/outdated:**
- Direct `loadPyodide()` on main thread: Still works, but blocks Socket.IO pings

## Open Questions

Things that couldn't be fully resolved:

1. **Python stdout/stderr capture**
   - What we know: print() in Worker doesn't appear in main console
   - What's unclear: Best approach for debug logging from Python
   - Recommendation: Implement OutputCapture class from PITFALLS.md if needed, but defer to Phase 68+

2. **NumPy array transfer optimization**
   - What we know: Transferable objects enable zero-copy for ArrayBuffer
   - What's unclear: Whether render_state benefits significantly
   - Recommendation: Use standard postMessage for Phase 67, optimize in Phase 68 if profiling shows bottleneck

3. **Worker file location**
   - What we know: Must be accessible as URL for `new Worker()`
   - What's unclear: Whether `/static/js/` is correct path
   - Recommendation: Match existing pattern from index.html script tags

## Sources

### Primary (HIGH confidence)
- `.planning/research/STACK.md` - Complete stack recommendation with code examples
- `.planning/research/PITFALLS.md` - 10 documented pitfalls with prevention strategies
- `.planning/research/ARCHITECTURE.md` - Integration approach (composition recommended)
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - GameTimerWorker pattern (lines 57-172)
- `interactive_gym/server/static/js/pyodide_remote_game.js` - Current Pyodide usage to replicate

### Secondary (MEDIUM confidence)
- [Pyodide Web Worker Documentation v0.29.0](https://pyodide.org/en/stable/usage/webworker.html) - Official pattern
- [Pyodide Web Worker Documentation v0.30.0.dev0](https://pyodide.org/en/latest/usage/webworker.html) - Latest updates

### Tertiary (LOW confidence)
- Web search results for patterns - validated against official docs

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Native APIs, existing Pyodide CDN, project research
- Architecture: HIGH - Composition pattern already documented in ARCHITECTURE.md
- Pitfalls: HIGH - 10 pitfalls documented in PITFALLS.md from Phase 24 research

**Research date:** 2026-02-04
**Valid until:** 2026-03-04 (30 days - stable domain)

---

## Phase 67 Specific Deliverables

Based on requirements WORKER-01, WORKER-02, WORKER-03 and success criteria:

### Files to Create
1. `interactive_gym/server/static/js/pyodide_worker.js` - Worker script
2. `interactive_gym/server/static/js/PyodideWorker.js` - Main thread class

### Key Implementation Points
1. **WORKER-01**: Worker loads Pyodide via `importScripts()` from CDN
2. **WORKER-02**: Main thread remains responsive (test with ping interval)
3. **WORKER-03**: READY event sent before accepting commands (messageQueue pattern)

### Not in Phase 67 Scope
- Modifying RemoteGame (Phase 68)
- Modifying MultiplayerPyodideGame (Phase 69)
- Batch operations for rollback (Phase 69)
- Validation testing (Phase 70)

Phase 67 creates the foundation. It should be testable standalone with a simple HTML test page.
