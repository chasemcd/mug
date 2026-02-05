# Technology Stack: Pyodide Web Worker Architecture

**Project:** Interactive Gym v1.16 - Pyodide Web Worker
**Researched:** 2026-02-04
**Overall confidence:** MEDIUM (based on training data, web verification unavailable)

## Executive Summary

Moving Pyodide to a Web Worker is a well-documented, officially supported pattern. The key decision is communication approach: raw postMessage is simpler and sufficient for this use case; Comlink adds abstraction overhead without significant benefit for the structured message protocol needed here.

**Recommendation:** Use raw postMessage with a typed message protocol. Comlink's RPC abstraction doesn't fit well with Pyodide's async nature and the need for progress events during initialization.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Confidence |
|------------|---------|---------|------------|
| Web Worker (native) | N/A | Isolate Pyodide from main thread | HIGH |
| Pyodide | 0.26.x | Python in WASM | HIGH |
| postMessage API | N/A | Main ↔ Worker communication | HIGH |
| Transferable Objects | N/A | Efficient array buffer transfer | HIGH |

### Communication Approach

| Approach | Recommendation | Rationale |
|----------|---------------|-----------|
| Raw postMessage | **RECOMMENDED** | Full control, progress events, no dependencies |
| Comlink | NOT RECOMMENDED | Abstraction mismatch with async WASM operations |
| SharedArrayBuffer | OPTIONAL | Only if sub-ms latency required (not our case) |

---

## Loading Pyodide in a Web Worker

### Official Pattern (HIGH confidence)

Pyodide officially supports Web Worker usage. The pattern is to import Pyodide inside the worker and call `loadPyodide()` there.

**Worker file (pyodide_worker.js):**

```javascript
// Import Pyodide in the worker context
importScripts('https://cdn.jsdelivr.net/pyodide/v0.26.0/full/pyodide.js');

let pyodide = null;

self.onmessage = async function(event) {
    const { type, id, payload } = event.data;

    try {
        switch (type) {
            case 'init':
                await handleInit(id, payload);
                break;
            case 'runPython':
                await handleRunPython(id, payload);
                break;
            case 'installPackages':
                await handleInstallPackages(id, payload);
                break;
        }
    } catch (error) {
        self.postMessage({
            type: 'error',
            id,
            error: { message: error.message, stack: error.stack }
        });
    }
};

async function handleInit(id, payload) {
    // Send progress updates during initialization
    self.postMessage({ type: 'progress', id, stage: 'loading', message: 'Loading Pyodide...' });

    pyodide = await loadPyodide({
        indexURL: payload.indexURL || 'https://cdn.jsdelivr.net/pyodide/v0.26.0/full/'
    });

    self.postMessage({ type: 'progress', id, stage: 'micropip', message: 'Loading micropip...' });
    await pyodide.loadPackage('micropip');

    self.postMessage({ type: 'ready', id });
}

async function handleRunPython(id, payload) {
    const result = await pyodide.runPythonAsync(payload.code);

    // Convert Python objects to JS for transfer
    const jsResult = result?.toJs ? result.toJs() : result;

    self.postMessage({ type: 'result', id, result: jsResult });
}

async function handleInstallPackages(id, payload) {
    const micropip = pyodide.pyimport('micropip');

    for (const pkg of payload.packages) {
        self.postMessage({ type: 'progress', id, stage: 'install', message: `Installing ${pkg}...` });
        await micropip.install(pkg);
    }

    self.postMessage({ type: 'installed', id });
}
```

### Main Thread Wrapper Class

```javascript
/**
 * PyodideWorker - Manages Pyodide execution in a dedicated Web Worker.
 *
 * Prevents main thread blocking during WASM compilation, allowing
 * Socket.IO ping/pong to continue uninterrupted.
 */
class PyodideWorker {
    constructor(options = {}) {
        this.worker = null;
        this.workerUrl = null;
        this.pendingRequests = new Map(); // id -> {resolve, reject}
        this.requestCounter = 0;
        this.onProgress = options.onProgress || null;
        this.ready = false;
    }

    /**
     * Initialize the worker and load Pyodide.
     * @param {Object} options - {indexURL, packages}
     * @returns {Promise<void>} Resolves when Pyodide is ready
     */
    async init(options = {}) {
        return new Promise((resolve, reject) => {
            // Create worker from separate file or inline blob
            this.worker = new Worker('/static/js/pyodide_worker.js');

            const initId = this._nextId();
            this.pendingRequests.set(initId, { resolve, reject });

            this.worker.onmessage = (event) => this._handleMessage(event);
            this.worker.onerror = (error) => this._handleError(error);

            this.worker.postMessage({
                type: 'init',
                id: initId,
                payload: { indexURL: options.indexURL }
            });
        });
    }

    /**
     * Run Python code asynchronously in the worker.
     * @param {string} code - Python code to execute
     * @returns {Promise<any>} Result of Python execution
     */
    async runPython(code) {
        return this._sendRequest('runPython', { code });
    }

    /**
     * Install packages via micropip.
     * @param {string[]} packages - Package names to install
     * @returns {Promise<void>}
     */
    async installPackages(packages) {
        return this._sendRequest('installPackages', { packages });
    }

    /**
     * Clean up worker resources.
     */
    destroy() {
        if (this.worker) {
            this.worker.terminate();
            this.worker = null;
        }
        if (this.workerUrl) {
            URL.revokeObjectURL(this.workerUrl);
            this.workerUrl = null;
        }
    }

    _nextId() {
        return ++this.requestCounter;
    }

    _sendRequest(type, payload) {
        return new Promise((resolve, reject) => {
            const id = this._nextId();
            this.pendingRequests.set(id, { resolve, reject });
            this.worker.postMessage({ type, id, payload });
        });
    }

    _handleMessage(event) {
        const { type, id, result, error, stage, message } = event.data;

        if (type === 'progress') {
            if (this.onProgress) {
                this.onProgress(stage, message);
            }
            return;
        }

        const pending = this.pendingRequests.get(id);
        if (!pending) return;

        this.pendingRequests.delete(id);

        switch (type) {
            case 'ready':
                this.ready = true;
                pending.resolve();
                break;
            case 'result':
            case 'installed':
                pending.resolve(result);
                break;
            case 'error':
                pending.reject(new Error(error.message));
                break;
        }
    }

    _handleError(error) {
        console.error('[PyodideWorker] Worker error:', error);
        // Reject all pending requests
        for (const [id, { reject }] of this.pendingRequests) {
            reject(new Error(`Worker error: ${error.message}`));
        }
        this.pendingRequests.clear();
    }
}
```

---

## Communication Patterns: postMessage vs Comlink

### Raw postMessage (RECOMMENDED)

**Pros:**
- No external dependencies
- Full control over message protocol
- Native progress events during long operations
- Matches existing GameTimerWorker pattern in codebase
- Simpler debugging (messages visible in DevTools)

**Cons:**
- More boilerplate for request/response tracking
- Manual serialization handling

**Example message protocol:**

```javascript
// Main → Worker
{ type: 'init', id: 1, payload: { indexURL: '...' } }
{ type: 'runPython', id: 2, payload: { code: '...' } }
{ type: 'step', id: 3, payload: { actions: {...} } }

// Worker → Main
{ type: 'progress', id: 1, stage: 'loading', message: '...' }
{ type: 'ready', id: 1 }
{ type: 'result', id: 2, result: {...} }
{ type: 'error', id: 3, error: { message: '...', stack: '...' } }
```

### Comlink (NOT RECOMMENDED for this use case)

**What it is:** Google's library that makes Web Worker functions appear as async functions on the main thread via Proxy/postMessage.

**Why not recommended:**

1. **Progress events don't fit RPC model**: Comlink excels at simple request/response, but Pyodide init needs progress callbacks during the operation
2. **Transferable object handling**: Requires manual `Comlink.transfer()` calls anyway
3. **Extra dependency**: Adds 4KB to bundle for marginal benefit
4. **Existing pattern**: Codebase already uses raw postMessage for GameTimerWorker

**When Comlink would make sense:**
- Many different functions being called from worker
- Pure request/response pattern without progress events
- Team unfamiliar with postMessage patterns

---

## Transferable Objects for Efficient Data Passing

### What Are Transferable Objects (HIGH confidence)

Transferable objects move memory ownership between threads instead of copying. This is zero-copy for ArrayBuffers, critical for large data like observations or images.

**Transferable types:**
- `ArrayBuffer`
- `MessagePort`
- `ImageBitmap`
- `OffscreenCanvas`

**NOT transferable (must be copied):**
- Plain objects/arrays (structured clone)
- TypedArrays without detaching underlying buffer
- Python proxy objects (must convert to JS first)

### Pattern for Observations (MEDIUM confidence)

```javascript
// In worker: Convert numpy array to transferable ArrayBuffer
async function handleStep(id, payload) {
    const result = await pyodide.runPythonAsync(`
        obs, rewards, terminateds, truncateds, infos = env.step(actions)
        render_state = env.render()
        obs, rewards, terminateds, truncateds, infos, render_state
    `);

    let [obs, rewards, terminateds, truncateds, infos, render_state] = result.toJs();

    // If obs is a numpy array, get the underlying buffer
    let obsBuffer = null;
    let obsTransferable = [];

    if (obs.buffer instanceof ArrayBuffer) {
        obsBuffer = obs.buffer;
        obsTransferable = [obsBuffer];
    }

    self.postMessage(
        {
            type: 'stepResult',
            id,
            result: { obs, rewards, terminateds, truncateds, infos, render_state },
            obsBuffer  // Reference to transferable
        },
        obsTransferable  // Second argument: list of transferables
    );
}
```

### Render State Transfer (MEDIUM confidence)

For RGB array render states, convert to ImageData or transfer raw buffer:

```javascript
// In worker: Transfer render state efficiently
function transferRenderState(renderState) {
    if (Array.isArray(renderState) && Array.isArray(renderState[0])) {
        // Convert to flat Uint8Array for transfer
        const height = renderState.length;
        const width = renderState[0].length;
        const buffer = new Uint8Array(height * width * 4);

        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const idx = (y * width + x) * 4;
                const [r, g, b] = renderState[y][x];
                buffer[idx] = r;
                buffer[idx + 1] = g;
                buffer[idx + 2] = b;
                buffer[idx + 3] = 255;
            }
        }

        return {
            type: 'rgba',
            width,
            height,
            buffer: buffer.buffer  // ArrayBuffer is transferable
        };
    }
    return { type: 'objects', data: renderState };
}
```

---

## Memory and Performance Considerations

### WASM Memory in Workers (MEDIUM confidence)

1. **Memory is isolated**: Worker's WASM memory is separate from main thread
2. **No shared memory by default**: Each postMessage clones data (except transferables)
3. **Pyodide memory usage**: ~50-100MB baseline, increases with packages

### Performance Characteristics

| Operation | Main Thread Impact | Typical Duration |
|-----------|-------------------|------------------|
| `loadPyodide()` | NONE (in worker) | 3-8 seconds |
| `loadPackage('micropip')` | NONE (in worker) | 0.5-2 seconds |
| `micropip.install()` | NONE (in worker) | 1-5 seconds per package |
| `runPythonAsync()` | NONE (in worker) | Varies |
| `postMessage` (small) | ~0.1ms | Negligible |
| `postMessage` (1MB buffer) | ~1-5ms | Structured clone |
| `postMessage` (transferable) | ~0.1ms | Zero-copy |

### Memory Leak Prevention

```javascript
// CRITICAL: Destroy Python objects after converting to JS
async function handleStep(id, payload) {
    const result = await pyodide.runPythonAsync(`...`);

    // Convert to JS FIRST
    const jsResult = result.toJs();

    // THEN destroy Python reference to prevent memory leak
    result.destroy();

    self.postMessage({ type: 'result', id, result: jsResult });
}
```

---

## Error Handling Patterns

### Worker Initialization Errors

```javascript
// In main thread wrapper
async init(options = {}) {
    return new Promise((resolve, reject) => {
        // Timeout for worker creation failures
        const timeout = setTimeout(() => {
            reject(new Error('PyodideWorker init timeout (30s)'));
        }, 30000);

        this.worker = new Worker('/static/js/pyodide_worker.js');

        this.worker.onerror = (error) => {
            clearTimeout(timeout);
            reject(new Error(`Worker creation failed: ${error.message}`));
        };

        // ... rest of init
    });
}
```

### Python Execution Errors

```javascript
// In worker
async function handleRunPython(id, payload) {
    try {
        const result = await pyodide.runPythonAsync(payload.code);
        const jsResult = result?.toJs ? result.toJs() : result;
        result?.destroy?.();
        self.postMessage({ type: 'result', id, result: jsResult });
    } catch (error) {
        // Pyodide wraps Python exceptions
        self.postMessage({
            type: 'error',
            id,
            error: {
                message: error.message,
                stack: error.stack,
                // Include Python traceback if available
                pythonTraceback: error.message.includes('Traceback')
                    ? error.message
                    : null
            }
        });
    }
}
```

### Worker Crash Recovery

```javascript
// In main thread wrapper
class PyodideWorker {
    _handleError(error) {
        console.error('[PyodideWorker] Worker crashed:', error);

        // Reject all pending requests
        for (const [id, { reject }] of this.pendingRequests) {
            reject(new Error('Worker crashed'));
        }
        this.pendingRequests.clear();

        // Clean up
        this.worker = null;
        this.ready = false;

        // Emit event for game to handle (show error overlay, etc.)
        if (this.onCrash) {
            this.onCrash(error);
        }
    }
}
```

---

## Worker Lifecycle Management

### Recommended Lifecycle

```
1. Page Load
   └── DO NOT create worker yet

2. Scene Activation (GymScene starts)
   └── Create PyodideWorker
   └── Begin init() (non-blocking)
   └── Show loading overlay with progress

3. Pyodide Ready
   └── Run environment_initialization_code
   └── Hide loading overlay
   └── Start game loop

4. Game Loop
   └── Main thread: collect inputs, send to worker
   └── Worker: step(actions), return result
   └── Main thread: render result

5. Scene End / Episode Complete
   └── Export data from main thread
   └── Worker state persists for next episode

6. All Episodes Complete / Navigation Away
   └── worker.destroy()
   └── Clean up Blob URL
```

### Singleton vs Per-Scene Worker

**Recommendation:** Singleton worker per page, re-used across scenes.

**Rationale:**
- Pyodide init is expensive (3-8 seconds)
- Packages stay loaded across `runPythonAsync` calls
- Only re-initialize environment code, not Pyodide itself

```javascript
// Singleton pattern
let globalPyodideWorker = null;

async function getPyodideWorker(options) {
    if (!globalPyodideWorker) {
        globalPyodideWorker = new PyodideWorker(options);
        await globalPyodideWorker.init();
    }
    return globalPyodideWorker;
}
```

---

## Integration with Existing Code

### Changes to RemoteGame

```javascript
// BEFORE (main thread Pyodide)
async initialize() {
    this.pyodide = await loadPyodide();  // BLOCKS MAIN THREAD
    await this.pyodide.loadPackage("micropip");
    // ...
}

// AFTER (worker Pyodide)
async initialize() {
    this.pyodideWorker = await getPyodideWorker({
        onProgress: (stage, message) => {
            ui_utils.updateLoadingProgress(message);
        }
    });

    await this.pyodideWorker.installPackages(this.config.packages_to_install);
    await this.pyodideWorker.runPython(this.config.environment_initialization_code);
    // ...
}
```

### Changes to step()

```javascript
// BEFORE
async step(actions) {
    const result = await this.pyodide.runPythonAsync(`
        obs, rewards, terminateds, truncateds, infos = env.step(${pyActions})
        render_state = env.render()
        obs, rewards, terminateds, truncateds, infos, render_state
    `);
    // ...
}

// AFTER
async step(actions) {
    const result = await this.pyodideWorker.step(actions);
    // result already converted to JS in worker
    // ...
}
```

---

## Gotchas and Limitations

### 1. No DOM Access in Worker (HIGH confidence)

Workers cannot access:
- `document`
- `window` (except `self`)
- Canvas/WebGL
- LocalStorage

**Implication:** Image conversion (render_state to base64) must happen in main thread OR use OffscreenCanvas in worker.

### 2. Pyodide Globals Not Shared (HIGH confidence)

`pyodide.globals` in worker is separate from main thread. Cannot directly share `interactiveGymGlobals`.

**Solution:** Pass globals via postMessage during init.

```javascript
// Worker
async function handleInit(id, payload) {
    pyodide = await loadPyodide();

    // Set globals from main thread
    if (payload.globals) {
        for (const [key, value] of Object.entries(payload.globals)) {
            pyodide.globals.set(key, pyodide.toPy(value));
        }
    }
}
```

### 3. Proxy Objects Not Transferable (HIGH confidence)

Pyodide proxy objects (Python objects wrapped for JS) cannot be postMessage'd.

**Solution:** Always call `.toJs()` before sending, then `.destroy()` the proxy.

### 4. Error Serialization (MEDIUM confidence)

Python exceptions with complex tracebacks may not serialize cleanly.

**Solution:** Extract string representations in worker before sending.

### 5. Worker File Path (HIGH confidence)

Worker script must be served from same origin (or use Blob URL).

**For Interactive Gym:** Place worker file at `/static/js/pyodide_worker.js`.

---

## Sources and Confidence

| Topic | Confidence | Basis |
|-------|------------|-------|
| Web Worker basic patterns | HIGH | Fundamental browser API, stable for years |
| Pyodide in Web Worker | MEDIUM | Based on training data (May 2025), official docs likely unchanged |
| Transferable objects | HIGH | Fundamental browser API |
| Comlink comparison | MEDIUM | Based on training data, library may have updated |
| Memory management | MEDIUM | Based on training data, Pyodide may have updates |
| Error handling | MEDIUM | Common patterns, may need testing |

**Note:** Web access was unavailable during this research. Recommend verifying Pyodide version and any API changes at https://pyodide.org/en/stable/usage/webworker.html before implementation.

---

## Recommended Next Steps

1. **Verify Pyodide Web Worker docs** - Check current official documentation
2. **Create minimal PoC** - Test loadPyodide in worker with progress events
3. **Measure actual timings** - Confirm WASM compile time unblocks main thread
4. **Design message protocol** - Finalize message types for step/reset/init
5. **Implement PyodideWorker class** - Start with init and runPython
6. **Update RemoteGame** - Migrate to use PyodideWorker
7. **Test Socket.IO stability** - Verify no disconnects during Pyodide init

---

*Stack research: 2026-02-04*
*Confidence: MEDIUM (training data only, web verification unavailable)*
