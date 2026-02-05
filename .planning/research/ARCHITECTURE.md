# Architecture Research: PyodideWorker Integration

**Project:** Interactive Gym - Pyodide Web Worker Integration
**Researched:** 2026-02-04
**Focus:** How to integrate a PyodideWorker into existing game classes

---

## Executive Summary

The existing codebase has two game classes with distinct Pyodide usage patterns:

1. **RemoteGame** - Single-player, simple async step/reset flow
2. **MultiplayerPyodideGame** - Extends RemoteGame, adds GGPO rollback netcode

Moving Pyodide to a Web Worker requires careful architectural decisions because:
- The multiplayer game uses **synchronous rollback** (restore state, replay N frames rapidly)
- Worker communication is inherently **async** (postMessage)
- Both classes share substantial code via inheritance

**Recommended approach:** Composition with a PyodideWorker facade class that both game classes use, with special handling for rollback batching.

---

## Current Architecture

### Class Hierarchy

```
RemoteGame
    |
    +-- constructor(config)
    +-- initialize()              # Creates Pyodide instance, loads env
    +-- reinitialize_environment()
    +-- reset()                   # Calls pyodide.runPythonAsync
    +-- step(actions)             # Calls pyodide.runPythonAsync
    |
    v
MultiplayerPyodideGame extends RemoteGame
    |
    +-- constructor(config)       # Adds GGPO state
    +-- initialize()              # super() + validateStateSync()
    +-- reset()                   # super() + P2P sync
    +-- step(allActionsDict)      # GGPO logic, calls stepWithActions()
    +-- stepWithActions(actions)  # Actual pyodide.runPythonAsync
    +-- performRollback()         # loadStateSnapshot + replay loop
    +-- saveStateSnapshot()       # env.get_state() via Pyodide
    +-- loadStateSnapshot()       # env.set_state() via Pyodide
```

### Pyodide Touchpoint Inventory

| Method | Class | Pyodide Calls | Sync Requirement |
|--------|-------|---------------|------------------|
| `initialize()` | RemoteGame | `loadPyodide()`, `micropip.install()`, `runPythonAsync()` | Async OK |
| `reinitialize_environment()` | RemoteGame | `micropip.install()`, `runPythonAsync()` | Async OK |
| `reset()` | RemoteGame | `runPythonAsync()` (reset + render) | Async OK |
| `step()` | RemoteGame | `runPythonAsync()` (step + render) | Async OK |
| `reset()` | Multiplayer | super() + additional `runPythonAsync()` for P2P | Async OK |
| `stepWithActions()` | Multiplayer | `runPythonAsync()` (step + render) | Async OK |
| `saveStateSnapshot()` | Multiplayer | `runPythonAsync()` (get_state + RNG) | Async OK |
| `loadStateSnapshot()` | Multiplayer | `runPythonAsync()` (set_state + RNG) | **RAPID** |
| `performRollback()` | Multiplayer | load + N x step via Python batch | **BATCHED** |
| `computeQuickStateHash()` | Multiplayer | `runPythonAsync()` (get_state + hash) | Async OK |
| `validateStateSync()` | Multiplayer | `runPythonAsync()` (capability check) | Async OK |
| `seedPythonEnvironment()` | Multiplayer | `runPythonAsync()` (seed RNG) | Async OK |

### Critical Path: Rollback

The `performRollback()` method is the most demanding:

```javascript
// Current implementation (lines 4629-4800 approx)
async performRollback(targetFrame, playerIds) {
    // 1. Load snapshot
    await this.loadStateSnapshot(snapshotFrame);

    // 2. Build all replay actions in JS first
    const replayFrames = [];  // Collects {frame, actions} tuples

    // 3. Execute ALL steps in a single Python batch
    // This is done to prevent event loop yields during replay
    await this.pyodide.runPythonAsync(`
        for _replay_frame, _replay_actions in _replay_sequence:
            env.step(_replay_actions)
    `);
}
```

The existing code already batches Python calls to avoid event loop yields. A worker-based approach must preserve this characteristic.

---

## Integration Approaches

### Option 1: Composition (Recommended)

**Pattern:** Create a `PyodideWorker` class that both game classes use via composition.

```
                     +-------------------+
                     |   PyodideWorker   |
                     | (Web Worker mgmt) |
                     +--------+----------+
                              |
          +-------------------+-------------------+
          |                                       |
+---------v---------+               +-------------v-----------+
|    RemoteGame     |               | MultiplayerPyodideGame  |
| this.pyodideWorker|               | this.pyodideWorker      |
+-------------------+               +-------------------------+
```

**Implementation:**

```javascript
class PyodideWorker {
    constructor() {
        this.worker = new Worker('pyodide_worker.js');
        this.pendingPromises = new Map();  // id -> {resolve, reject}
        this.nextId = 0;
    }

    // Core methods that mirror Pyodide interface
    async runPythonAsync(code) { ... }
    async loadPackage(pkg) { ... }

    // Batch execution for rollback
    async runBatch(operations) {
        // Single postMessage, single response
        // Worker executes all ops synchronously, returns all results
    }

    // State operations
    async getState() { ... }
    async setState(state) { ... }
    async step(actions) { ... }
    async reset(seed) { ... }
}
```

**Pros:**
- Clean separation of concerns
- Worker lifecycle managed in one place
- Both game classes get worker benefits
- Easy to add new operations

**Cons:**
- Requires changes to both game classes
- Need to design batch API carefully

### Option 2: Inheritance (Worker as Base Class)

**Pattern:** Create a `WorkerRemoteGame` that extends or replaces `RemoteGame`.

```
RemoteGame (keeps sync Pyodide)
    |
    v
WorkerRemoteGame (worker-based)
    |
    v
MultiplayerPyodideGame extends WorkerRemoteGame
```

**Pros:**
- Preserves inheritance structure
- Could keep RemoteGame for fallback

**Cons:**
- Tighter coupling
- Harder to share worker between instances
- More complex class hierarchy

### Option 3: Adapter/Facade

**Pattern:** Create a facade that wraps Pyodide with same interface, but uses worker internally.

```javascript
class PyodideFacade {
    // Same interface as raw Pyodide
    async runPythonAsync(code) { ... }
    toPy(obj) { ... }

    // But internally uses worker
    constructor(useWorker = true) {
        if (useWorker) {
            this.impl = new PyodideWorkerImpl();
        } else {
            this.impl = new PyodideDirectImpl();
        }
    }
}
```

**Pros:**
- Minimal changes to game classes (just change Pyodide reference)
- Easy fallback to direct Pyodide

**Cons:**
- May hide worker-specific optimizations (batching)
- Complex to implement full Pyodide interface

---

## Recommended Architecture: Composition with Batched Operations

### Class Diagram

```
+------------------+
| PyodideWorker.js |  (Worker script - runs Pyodide in worker thread)
| - pyodide        |
| - env            |
| - onmessage()    |
+------------------+
        ^
        | postMessage/onmessage
        |
+------------------+
| PyodideWorker    |  (Main thread manager)
| - worker         |
| - messageId      |
| - pendingCalls   |
|                  |
| + init()         |
| + runAsync(code) |
| + step(actions)  |
| + reset(seed)    |
| + getState()     |
| + setState()     |
| + batch([ops])   |  <-- Key for rollback
| + terminate()    |
+------------------+
        ^
        | composition
        |
+------------------+     +---------------------------+
| RemoteGame       |     | MultiplayerPyodideGame    |
| - pyodideWorker  |     | extends RemoteGame        |
|                  |     | - pyodideWorker (shared)  |
| + initialize()   |     |                           |
| + reset()        |     | + performRollback()       |
| + step()         |     |   uses batch() for speed  |
+------------------+     +---------------------------+
```

### Message Protocol

```javascript
// Main thread -> Worker
{
    type: 'init',
    id: 1,
    config: { packages: [...], envCode: '...' }
}

{
    type: 'step',
    id: 2,
    actions: { agent_left: 0, agent_right: 1 }
}

{
    type: 'batch',
    id: 3,
    operations: [
        { type: 'setState', state: {...} },
        { type: 'step', actions: {...} },
        { type: 'step', actions: {...} },
        { type: 'step', actions: {...} },
        { type: 'getState' }  // Get final state after replay
    ]
}

// Worker -> Main thread
{
    type: 'result',
    id: 2,
    success: true,
    data: { obs, rewards, terminateds, truncateds, render_state }
}

{
    type: 'batch_result',
    id: 3,
    success: true,
    results: [null, stepResult1, stepResult2, stepResult3, finalState]
}
```

### Rollback with Worker

```javascript
// MultiplayerPyodideGame.performRollback()
async performRollback(targetFrame, playerIds) {
    // 1. Build all operations in JS
    const ops = [];

    // Load snapshot
    ops.push({ type: 'setState', state: snapshot.env_state });
    ops.push({ type: 'setRngState', npState: snapshot.np_rng_state, pyState: snapshot.py_rng_state });

    // Build replay sequence
    for (let frame = snapshotFrame; frame < currentFrame; frame++) {
        const actions = this.getInputsForFrame(frame, playerIds);
        ops.push({ type: 'step', actions });
    }

    // Get final state
    ops.push({ type: 'getState' });
    ops.push({ type: 'render' });

    // 2. Execute all in single worker call (no event loop yields!)
    const results = await this.pyodideWorker.batch(ops);

    // 3. Process results
    const finalState = results[results.length - 2];
    const renderState = results[results.length - 1];

    return { state: finalState, render: renderState };
}
```

---

## Worker Module Loading

### Option A: Inline Worker (Current Timer Pattern)

The codebase already uses inline workers via Blob URL (see `GameTimerWorker` in multiplayer game):

```javascript
// From pyodide_multiplayer_game.js lines 95-135
const workerCode = `
    self.onmessage = function(e) { ... }
`;
const blob = new Blob([workerCode], { type: 'application/javascript' });
this.workerUrl = URL.createObjectURL(blob);
this.worker = new Worker(this.workerUrl);
```

**Pros:**
- Already proven pattern in codebase
- No module bundling concerns
- Works in all environments

**Cons:**
- Pyodide code is large - inline blob would be unwieldy
- Can't use ES6 imports in worker

### Option B: ES6 Module Worker

```javascript
const worker = new Worker('pyodide_worker.js', { type: 'module' });
```

**Pros:**
- Clean file separation
- Can use imports
- Easier to maintain

**Cons:**
- Requires browser support (modern browsers OK)
- Need to handle Pyodide CDN loading in worker

### Option C: Separate Worker File (Recommended)

Create a standalone worker file that loads Pyodide:

```javascript
// pyodide_worker.js
importScripts('https://cdn.jsdelivr.net/pyodide/v0.24.1/full/pyodide.js');

let pyodide = null;
let env = null;

self.onmessage = async function(e) {
    const { type, id, ...data } = e.data;

    try {
        let result;
        switch(type) {
            case 'init':
                pyodide = await loadPyodide();
                await pyodide.loadPackage('micropip');
                // ... setup env
                result = { ready: true };
                break;
            case 'step':
                result = await stepEnv(data.actions);
                break;
            // ... other cases
        }
        self.postMessage({ type: 'result', id, success: true, data: result });
    } catch (error) {
        self.postMessage({ type: 'result', id, success: false, error: error.message });
    }
};
```

---

## Backward Compatibility

### Strategy: Feature Detection + Fallback

```javascript
class RemoteGame {
    constructor(config) {
        // Feature detection
        this.useWorker = config.use_worker !== false && typeof Worker !== 'undefined';

        if (this.useWorker) {
            this.pyodideWorker = new PyodideWorker();
        } else {
            // Direct Pyodide (fallback)
            this.pyodide = null;  // Loaded in initialize()
        }
    }

    async step(actions) {
        if (this.useWorker) {
            return await this.pyodideWorker.step(actions);
        } else {
            return await this._stepDirect(actions);
        }
    }
}
```

### Configuration Flag

Add to scene metadata:

```python
scene = GymScene(
    use_pyodide_worker=True,  # New option
    # ... existing config
)
```

---

## Migration Path

### Phase 1: PyodideWorker Core (No Changes to Game Classes)

1. Create `pyodide_worker.js` (worker script)
2. Create `PyodideWorker` class (main thread manager)
3. Test in isolation with unit tests
4. Operations: init, step, reset, getState, setState

### Phase 2: RemoteGame Integration

1. Add `useWorker` config option
2. Modify `initialize()` to create worker
3. Modify `step()` and `reset()` to use worker
4. Keep direct Pyodide as fallback
5. Test single-player games

### Phase 3: Multiplayer + Batch Operations

1. Add `batch()` operation to worker
2. Modify `performRollback()` to use batch
3. Modify `saveStateSnapshot()` and `loadStateSnapshot()`
4. Test rollback scenarios extensively
5. Measure performance improvement

### Phase 4: Cleanup

1. Remove fallback code if worker is stable
2. Update documentation
3. Consider deprecating direct Pyodide mode

---

## Performance Considerations

### Worker Thread Benefits

| Scenario | Direct Pyodide | Worker Pyodide | Benefit |
|----------|---------------|----------------|---------|
| Heavy step() | Blocks main thread 10-50ms | Main thread free | UI remains responsive |
| Rollback (10 frames) | 100-500ms blocking | Same total time, non-blocking | No frame drops |
| Background tab | Throttled timer | Worker timers unthrottled | Consistent game loop |

### Worker Overhead

| Operation | Overhead |
|-----------|----------|
| postMessage (small) | ~0.1ms |
| postMessage (state JSON) | 1-5ms depending on size |
| Structured clone (arrays) | Can be significant |

### Mitigation: Transferables

For render state (potentially large):

```javascript
// In worker
const renderBuffer = new Uint8Array(renderData);
self.postMessage({ type: 'step_result', render: renderBuffer }, [renderBuffer.buffer]);

// Main thread receives without copy
```

---

## Async/Sync Considerations for Rollback

### The Challenge

Rollback currently works because:
1. All operations are in one async function
2. No `await` between steps in the Python batch
3. Event loop doesn't yield during replay

With worker:
1. Each `postMessage` could yield the event loop
2. New inputs could arrive between replay steps
3. Race conditions possible

### Solution: Batch API

The `batch()` operation sends ALL replay steps in one message:

```javascript
// ONE postMessage, ONE response
const results = await this.pyodideWorker.batch([
    { type: 'setState', state },
    { type: 'step', actions: frame1Actions },
    { type: 'step', actions: frame2Actions },
    // ...
]);
```

Worker executes all synchronously, returns all results in one message.

### Guard During Replay

```javascript
// In step() method
if (this.rollbackInProgress) {
    // Queue incoming inputs, don't process
    this.pendingInputsDuringReplay.push(input);
    return;
}
```

This pattern already exists in the codebase (`rollbackInProgress` flag).

---

## Open Questions

1. **Shared Worker?** Could multiple game instances share one PyodideWorker? Probably not worth the complexity for typical usage.

2. **Memory Management:** Pyodide in worker has separate memory. How to handle large env states efficiently? Consider Transferables or SharedArrayBuffer.

3. **Error Handling:** Worker crashes need graceful handling. Consider heartbeat/watchdog.

4. **Hot Reload:** Can we update env code without destroying worker? Would need careful state preservation.

---

## Recommendations Summary

1. **Use Composition pattern** - PyodideWorker class used by both game classes
2. **Separate worker file** - Not inline blob, for maintainability
3. **Batch API is critical** - For rollback performance and correctness
4. **Keep fallback** - Direct Pyodide for debugging/compatibility
5. **Incremental migration** - Start with RemoteGame, then multiplayer

---

## Sources

- Codebase analysis:
  - `/interactive_gym/server/static/js/pyodide_remote_game.js` - RemoteGame class
  - `/interactive_gym/server/static/js/pyodide_multiplayer_game.js` - MultiplayerPyodideGame class (7000+ lines)
  - `/interactive_gym/server/static/js/index.js` - Initialization flow
- Existing patterns:
  - `GameTimerWorker` class (lines 78-172) - Inline worker example
  - `performRollback()` method (lines 4629+) - Batch Python execution pattern
