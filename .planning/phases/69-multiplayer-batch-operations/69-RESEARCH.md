# Phase 69: Multiplayer Batch Operations - Research

**Researched:** 2026-02-04
**Domain:** Pyodide Web Worker migration for GGPO rollback netcode
**Confidence:** HIGH

## Summary

This phase migrates MultiplayerPyodideGame from direct `this.pyodide.runPythonAsync()` calls (routed through backward-compat shims) to structured PyodideWorker commands. The critical deliverable is a **batch API** that allows rollback operations (setState + N steps + getState) to execute in a **single postMessage round-trip**, eliminating N+2 round-trips per rollback.

The multiplayer game file (`pyodide_multiplayer_game.js`, ~5,600+ LOC) currently makes ~25 distinct `this.pyodide.runPythonAsync()` calls across rollback, hashing, state management, reset, and step operations. The existing `performRollback()` method already batches replay steps into a single Python call (lines 4827-4891), proving the pattern works. The primary work is: (1) adding new Worker message types for state operations, (2) adding a `batch` command to the Worker protocol, (3) migrating each call site, and (4) removing the backward-compat shims from Phase 68.

**Primary recommendation:** Add `getState`, `setState`, `computeHash`, and `batch` message types to the Worker protocol. The `batch` command accepts an array of operations and returns an array of results in a single postMessage round-trip. Migrate all `runPythonAsync` call sites to use structured commands or batch. Remove `runPythonAsync`/`toPy`/`_wrapResult` shims entirely.

## Standard Stack

No new libraries needed. This phase works entirely within the existing codebase:

### Core
| Component | Location | Purpose | Status |
|-----------|----------|---------|--------|
| PyodideWorker.js | `/static/js/PyodideWorker.js` | Main-thread Worker wrapper | Extend with new commands |
| pyodide_worker.js | `/static/js/pyodide_worker.js` | Worker script (Pyodide execution) | Add new handlers |
| pyodide_multiplayer_game.js | `/static/js/pyodide_multiplayer_game.js` | Multiplayer game class | Migrate all Pyodide calls |
| pyodide_remote_game.js | `/static/js/pyodide_remote_game.js` | Base class with shims | Remove shims |

### Existing Patterns to Follow
| Pattern | Source | How It Works |
|---------|--------|--------------|
| Request/response correlation | PyodideWorker._sendRequest | Each postMessage gets unique ID, response matched via pendingRequests Map |
| Worker message routing | pyodide_worker.handleMessage | switch(type) dispatches to handler functions |
| Result normalization | pyodide_worker.handleStep | Python results converted to JS via toJs({depth:2}), PyProxy destroyed |
| Batch Python execution | performRollback (line 4827) | Multiple env.step() calls in single runPythonAsync with JSON round-trip |

## Architecture Patterns

### New Worker Message Types

The Worker protocol currently supports: `installPackages`, `initEnv`, `step`, `reset`, `runPython`.

Add these new types:

```
New message types:
  getState     -> Returns env state + RNG state as JSON
  setState     -> Restores env state + RNG state from JSON
  computeHash  -> Returns SHA-256 hash of current env state
  batch        -> Executes array of operations, returns array of results
```

### Pattern 1: Batch Command Protocol

**What:** A single postMessage containing an ordered array of operations, executed sequentially in the Worker, returning all results in one response.

**When to use:** Rollback (setState + N steps + getState), fast-forward (N steps), any sequence of operations that must execute atomically.

**Message format:**
```javascript
// Main thread sends:
{
  type: 'batch',
  id: 42,
  payload: {
    operations: [
      { op: 'setState', params: { stateJson: '...' } },
      { op: 'step', params: { actions: {...} } },
      { op: 'step', params: { actions: {...} } },
      { op: 'getState', params: {} },
      { op: 'computeHash', params: {} }
    ]
  }
}

// Worker responds:
{
  type: 'result',
  id: 42,
  result: [
    { ok: true },                          // setState result
    { obs, rewards, terminateds, ... },    // step result
    { obs, rewards, terminateds, ... },    // step result
    { stateJson: '...' },                 // getState result
    { hash: 'abc123...' }                 // computeHash result
  ]
}
```

### Pattern 2: Rollback Batch (Critical Path)

**What:** The rollback sequence currently in performRollback() (lines 4550-4891) becomes a single batch command.

**Current flow (multiple round-trips):**
1. `loadStateSnapshot()` -> runPythonAsync (set_state + set RNG) -- 1 round-trip
2. Replay loop in single runPythonAsync (already batched!) -- 1 round-trip
3. Post-rollback render -> runPythonAsync(`env.render()`) -- 1 round-trip

**New flow (single round-trip):**
```javascript
const batchOps = [
  { op: 'setState', params: { stateJson, rngState } },
  ...replayFrames.map(rf => ({ op: 'step', params: { actions: rf.actions } })),
  { op: 'getState', params: {} },  // For updated snapshots
  { op: 'render', params: {} }     // For post-rollback display
];
const results = await this.worker.batch(batchOps);
```

**Key insight:** The replay loop inside performRollback (lines 4827-4891) already executes all steps in a single Python call. The improvement is eliminating the separate loadStateSnapshot and post-rollback render round-trips, AND moving from `runPythonAsync` (arbitrary code) to structured commands.

### Pattern 3: State Snapshot Operations

**What:** `saveStateSnapshot()` and `loadStateSnapshot()` become structured Worker commands instead of arbitrary Python code.

**Current saveStateSnapshot (line 4450):** Runs ~20 lines of Python to capture env_state + numpy RNG + Python RNG, JSON-serializes, returns string.

**New:** `getState` Worker command that captures the same data, returns JSON. The snapshot storage (Map<frame, JSON>) stays on the main thread since it's used for finding best snapshot to rollback to.

**Decision: State buffer stays on main thread.** Rationale:
- Main thread needs to inspect snapshot keys for `findBestSnapshot()` (line 4516)
- Main thread adds JS-side data to snapshots (`cumulative_rewards`, `step_num`)
- Moving to Worker would require additional round-trips for snapshot queries
- JSON strings are already structured data, safe for postMessage

### Pattern 4: Migrating stepWithActions

**What:** `stepWithActions()` (line 2706) currently uses `runPythonAsync` with inline Python. It should use `this.worker.step()` like the base class.

**Current code (line 2710-2746):**
```javascript
const pyActions = this.pyodide.toPy(actions);
const result = await this.pyodide.runPythonAsync(`
${this.config.on_game_step_code || ''}
import numpy as np
agent_actions = {int(k) if k.isnumeric()...}
obs, rewards, terminateds, truncateds, infos = env.step(agent_actions)
...
`);
let [obs, rewards, terminateds, truncateds, infos, render_state] =
    await this.pyodide.toPy(result).toJs();
```

**New code:** Simply call `this.worker.step(actions)` and convert results. The Worker already handles `on_game_step_code` injection and obs/rewards normalization. The `toPy` shim and manual normalization become unnecessary.

### Recommended Project Structure (Changes)

```
interactive_gym/server/static/js/
  PyodideWorker.js         # ADD: getState(), setState(), computeHash(), batch() methods
                           # REMOVE: runPythonAsync(), toPy(), _wrapResult()
  pyodide_worker.js        # ADD: handleGetState, handleSetState, handleComputeHash, handleBatch
                           # REMOVE: handleRunPython (after all callers migrated)
  pyodide_remote_game.js   # REMOVE: this.pyodide = this.worker shim line
  pyodide_multiplayer_game.js  # MIGRATE: all this.pyodide.* calls to this.worker.*
```

### Anti-Patterns to Avoid
- **Keeping runPythonAsync as escape hatch:** Every call site must use structured commands. Leaving runPythonAsync available invites future technical debt.
- **Separate round-trips for rollback sub-operations:** The whole point of the batch API is to combine setState + steps + getState into one trip.
- **Moving state snapshots to Worker:** This creates coupling and requires extra round-trips for snapshot management that's currently free on the main thread.
- **Changing GGPO logic in this phase:** Only change the execution mechanism (Worker commands vs direct Pyodide). Do not alter rollback detection, input buffering, or episode sync logic.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON serialization of state | Custom serializer | `json.dumps/loads` in Python | Already proven in existing code, handles all state types |
| Request/response correlation | New ID system | Existing `_sendRequest` with `pendingRequests` Map | Already handles concurrent requests correctly |
| Obs/rewards normalization | New normalization in multiplayer | Worker's existing handleStep normalization | DRY - Worker already does this correctly |
| RNG state capture/restore | Custom RNG handling | Existing Python snippet from saveStateSnapshot | Already proven, captures numpy + Python random |

## Common Pitfalls

### Pitfall 1: Breaking the Event Loop Atomicity of Rollback
**What goes wrong:** Rollback replay currently works because all steps execute in a single `runPythonAsync` call, which yields the event loop only once (at await). If migrated to N separate `worker.step()` calls, each one yields, allowing network input handlers to fire mid-rollback.
**Why it happens:** The `rollbackInProgress` guard prevents nested rollbacks but doesn't prevent input queueing that could cause issues.
**How to avoid:** Use the batch API for rollback replay. All replay steps MUST execute in a single postMessage round-trip, just like the current single `runPythonAsync` call.
**Warning signs:** Inputs arriving during rollback replay, nested rollback warnings, state corruption after rollback.

### Pitfall 2: Forgetting to Migrate Debug/Diagnostic runPythonAsync Calls
**What goes wrong:** The step() function has debug hash computation calls at lines 2400 and 2430 that only run for the first 100 frames. These also use `this.pyodide.runPythonAsync` and would break if shims are removed before migration.
**Why it happens:** They're inside `if (this.frameNumber < 100)` blocks, so they're easy to miss in testing.
**How to avoid:** Catalog ALL call sites (there are ~25) and migrate each one. Use `computeHash` Worker command for hash operations.
**Warning signs:** Errors only in the first 100 frames of a game, broken debug logging.

### Pitfall 3: Result Format Changes Breaking Downstream Code
**What goes wrong:** `stepWithActions()` currently returns results through `this.pyodide.toPy(result).toJs()` which produces Maps. The Worker's `step()` returns plain objects that need `_convertToMap()`.
**Why it happens:** The shim's `toPy().toJs()` chain has subtle conversion behavior that differs from Worker output.
**How to avoid:** After migrating stepWithActions to use `this.worker.step()`, ensure all downstream code (cumulative_rewards updates, episode end detection) gets Maps where expected. Apply `_convertToMap()` to obs, rewards, terminateds, truncateds.
**Warning signs:** `rewards.entries is not a function`, `obs.keys is not a function` errors.

### Pitfall 4: Losing on_game_step_code Execution in Multiplayer Step
**What goes wrong:** `stepWithActions()` currently injects `this.config.on_game_step_code` inline in Python code. The Worker already handles this via the `onGameStepCode` variable set during `initEnv`.
**Why it happens:** Developer forgets that the Worker already has this code and tries to pass it again, or removes it without verifying Worker has it.
**How to avoid:** Verify that `on_game_step_code` is passed via `initEnv` globals during initialization. The Worker's `handleStep` already injects it before `env.step()`.
**Warning signs:** Policy/bot actions not computed correctly, different behavior between single-player and multiplayer.

### Pitfall 5: State Snapshot JSON Escaping
**What goes wrong:** Current `loadStateSnapshot()` escapes JSON for embedding in Python template literals. The new `setState` command should pass state as a structured object via postMessage, not as an embedded string.
**Why it happens:** Copy-paste from existing code that embeds JSON in Python strings.
**How to avoid:** Pass the state JSON string directly in the message payload. The Worker handler parses it with `json.loads()` rather than string interpolation. This eliminates escaping bugs entirely.
**Warning signs:** Python `json.loads` failures, backslash-related parsing errors in state restoration.

### Pitfall 6: Batch Operation Ordering and Error Handling
**What goes wrong:** If one operation in a batch fails (e.g., setState with corrupted data), all subsequent operations should not execute, but the caller doesn't know which operation failed.
**Why it happens:** Naive batch implementation catches errors globally rather than per-operation.
**How to avoid:** Batch handler should execute operations sequentially, stop on first error, and return partial results with error information: `{ results: [...], error: { index: N, message: '...' } }`.
**Warning signs:** Corrupted state after partial batch execution, silent swallowed errors.

## Code Examples

### Example 1: Worker-side getState Handler
```javascript
// In pyodide_worker.js
async function handleGetState(id, payload) {
    const result = await pyodide.runPythonAsync(`
import json
import numpy as np
import random

_env_state = env.get_state()

_np_rng_state = np.random.get_state()
_np_rng_serializable = (
    _np_rng_state[0],
    _np_rng_state[1].tolist(),
    _np_rng_state[2],
    _np_rng_state[3],
    _np_rng_state[4]
)
_py_rng_state = random.getstate()

json.dumps({
    'env_state': _env_state,
    'np_rng_state': _np_rng_serializable,
    'py_rng_state': _py_rng_state
})
    `);

    self.postMessage({ type: 'result', id, result: result });
}
```

### Example 2: Worker-side setState Handler
```javascript
// In pyodide_worker.js
async function handleSetState(id, payload) {
    // payload.stateJson is the full snapshot JSON string
    const escapedJson = payload.stateJson.replace(/\\/g, '\\\\').replace(/'/g, "\\'");

    await pyodide.runPythonAsync(`
import json
import numpy as np
import random

_snapshot = json.loads('''${escapedJson}''')

env.set_state(_snapshot['env_state'])

if 'np_rng_state' in _snapshot:
    _np_state = _snapshot['np_rng_state']
    _np_rng_tuple = (
        _np_state[0],
        np.array(_np_state[1], dtype=np.uint32),
        _np_state[2],
        _np_state[3],
        _np_state[4]
    )
    np.random.set_state(_np_rng_tuple)

if 'py_rng_state' in _snapshot:
    _py_state = _snapshot['py_rng_state']
    if isinstance(_py_state, list):
        _py_state = (_py_state[0], tuple(_py_state[1]),
                     _py_state[2] if len(_py_state) > 2 else None)
    random.setstate(_py_state)
    `);

    self.postMessage({ type: 'result', id, result: { ok: true } });
}
```

### Example 3: Worker-side Batch Handler
```javascript
// In pyodide_worker.js
async function handleBatch(id, payload) {
    const results = [];

    for (let i = 0; i < payload.operations.length; i++) {
        const { op, params } = payload.operations[i];
        try {
            switch (op) {
                case 'setState':
                    await handleSetStateInternal(params);
                    results.push({ ok: true });
                    break;
                case 'getState':
                    results.push(await handleGetStateInternal(params));
                    break;
                case 'step':
                    results.push(await handleStepInternal(params));
                    break;
                case 'reset':
                    results.push(await handleResetInternal(params));
                    break;
                case 'computeHash':
                    results.push(await handleComputeHashInternal(params));
                    break;
                case 'render':
                    results.push(await handleRenderInternal(params));
                    break;
                default:
                    throw new Error(`Unknown batch operation: ${op}`);
            }
        } catch (error) {
            self.postMessage({
                type: 'error', id,
                error: {
                    message: `Batch operation ${i} (${op}) failed: ${error.message}`,
                    stack: error.stack,
                    failedIndex: i,
                    partialResults: results
                }
            });
            return;
        }
    }

    self.postMessage({ type: 'result', id, result: results });
}
```

### Example 4: Main-thread Batch Method
```javascript
// In PyodideWorker.js
async batch(operations) {
    this._assertReady();
    return this._sendRequest('batch', { operations });
}
```

### Example 5: Migrated stepWithActions
```javascript
// In pyodide_multiplayer_game.js - replaces lines 2706-2771
async stepWithActions(actions) {
    const result = await this.worker.step(actions);

    let { obs, rewards, terminateds, truncateds, infos, render_state } = result;

    // Convert to Maps for downstream compatibility
    obs = this._convertToMap(obs);
    rewards = this._convertToMap(rewards);
    terminateds = this._convertToMap(terminateds);
    truncateds = this._convertToMap(truncateds);

    // Update cumulative rewards
    for (let [key, value] of rewards.entries()) {
        this.cumulative_rewards[key] += value;
    }
    this.step_num++;
    ui_utils.updateHUDText(this.getHUDText());

    // Process render_state
    render_state = this._processRenderState(render_state);

    return [obs, rewards, terminateds, truncateds, infos, render_state];
}
```

### Example 6: Migrated performRollback Using Batch
```javascript
// Simplified rollback using batch API
const batchOps = [];

// 1. Restore state from snapshot
batchOps.push({ op: 'setState', params: { stateJson: snapshotJson } });

// 2. Replay all frames
for (const rf of replayFrames) {
    batchOps.push({ op: 'step', params: { actions: rf.actions } });
}

// 3. Get state for snapshot updates and hash
batchOps.push({ op: 'getState', params: {} });
batchOps.push({ op: 'render', params: {} });

// Single round-trip!
const results = await this.worker.batch(batchOps);

// Process results: [setStateResult, ...stepResults, getStateResult, renderResult]
const stepResults = results.slice(1, 1 + replayFrames.length);
const newState = results[results.length - 2];
const renderState = results[results.length - 1];
```

## Comprehensive Call Site Catalog

All `this.pyodide.runPythonAsync()` / `this.pyodide.toPy()` calls in pyodide_multiplayer_game.js:

| Line | Method | What It Does | Migration Target |
|------|--------|-------------|-----------------|
| 1489 | Socket handler (state request) | `env.get_state()` | `this.worker.getState()` |
| 1763 | `validateStateSync()` | Check hasattr(env, 'get_state/set_state') | New `validateStateSync` Worker command OR keep runPython (one-time setup) |
| 1807 | `seedPythonEnvironment()` | `np.random.seed() + random.seed()` | New `seedRng` Worker command |
| 1901+1934 | `reset()` server-auth path | `env.reset() + set_state() + get_obs()` | `this.worker.reset()` + `this.worker.setState()` |
| 1999+2022 | `reset()` P2P path | `env.reset() + normalize obs` | `this.worker.reset()` |
| 2072 | `reset()` P2P hash check | `env.get_state() + md5 hash` | `this.worker.computeHash()` |
| 2400 | `step()` debug pre-hash | `env.get_state() + md5 hash` | `this.worker.computeHash()` |
| 2430 | `step()` debug post-hash | `env.get_state() + md5 hash` | `this.worker.computeHash()` |
| 2549+2550 | `step()` post-rollback render | `env.render() + toPy().toJs()` | Already included in rollback batch |
| 2710-2746 | `stepWithActions()` | `env.step() + normalize` | `this.worker.step()` |
| 3169 | `_computeHashFromState()` | Hash from state object (not env) | Pure JS hash (state is already JSON) or Worker command |
| 3333 | `_handleDesync()` | `env.get_state()` dump | `this.worker.getState()` |
| 3380 | `computeQuickStateHash()` | `env.get_state() + sha256` | `this.worker.computeHash()` |
| 3427+3433 | `applyServerState()` | `set_state(env_state)` | `this.worker.setState()` |
| 3478 | `applyServerState()` render | `env.render()` | `this.worker.render()` or include in batch |
| 4211 | `_applyP2PState()` | `set_state(env_state)` | `this.worker.setState()` |
| 4450 | `saveStateSnapshot()` | `get_state() + RNG capture` | `this.worker.getState()` |
| 4550 | `loadStateSnapshot()` | `set_state() + RNG restore + verify` | `this.worker.setState()` |
| 4827 | `performRollback()` replay | Batch N steps + snapshots + rewards | `this.worker.batch([setState, ...steps, getState])` |
| 5111 | `_performFastForward()` | Batch N steps | `this.worker.batch([...steps])` |

**Total: ~25 call sites using 7 distinct operation types.**

## State of the Art

| Old Approach (Current) | New Approach (Phase 69) | Impact |
|------------------------|-------------------------|--------|
| `this.pyodide = this.worker` shim | Direct `this.worker.*` calls | Removes 3 shim methods, cleaner API |
| `runPythonAsync()` for all operations | Structured commands: step, getState, setState, computeHash, batch | Type-safe, optimizable, no code injection |
| `toPy()` wrapper with toString/toJs | Direct JSON in Worker messages | Eliminates conversion overhead and fragile string interpolation |
| Multiple round-trips per rollback | Single batch round-trip | Reduces rollback latency by ~60-80% (saves 2+ postMessage round-trips) |
| State JSON embedded in Python template literals | State passed as structured message payload | Eliminates escaping bugs |
| Obs normalization duplicated in multiplayer stepWithActions | Worker handles normalization (DRY) | One normalization path for all game modes |

**Deprecated/outdated after this phase:**
- `PyodideWorker.runPythonAsync()` - remove entirely
- `PyodideWorker.toPy()` - remove entirely
- `PyodideWorker._wrapResult()` - remove entirely
- `pyodide_worker.handleRunPython()` - remove entirely
- `this.pyodide = this.worker` shim in RemoteGame.initialize() - remove entirely

## GGPO State Buffer Decision

**Decision: State snapshots remain on main thread, stored as JSON strings.**

**Analysis:**

Option A: State buffers on main thread (RECOMMENDED)
- Pros: No changes to snapshot management, findBestSnapshot is synchronous, JS-side state (cumulative_rewards, step_num) added without round-trip
- Cons: State JSON crosses Worker boundary on every save/load

Option B: State buffers inside Worker
- Pros: getState/setState never crosses Worker boundary
- Cons: findBestSnapshot needs a round-trip, adding JS-side state needs a round-trip, pruning logic must be in Worker or communicated

**Why Option A wins:** The snapshot Map is queried synchronously for `findBestSnapshot()` during rollback. Moving it to the Worker would make rollback setup require an extra round-trip just to find the right snapshot. The JSON transfer cost is low (states are typically small dicts) compared to the complexity of managing snapshot lifecycle across the boundary.

## Batch API Design Decision

**Decision: Array-of-operations with sequential execution, stop-on-error.**

The batch API should:
1. Accept an array of `{ op, params }` objects
2. Execute them sequentially in the Worker (order matters for setState-then-step)
3. Return an array of results in the same order
4. Stop on first error, returning partial results + error info
5. Support all operation types: `setState`, `getState`, `step`, `reset`, `computeHash`, `render`, `seedRng`

**Why not a dedicated rollback command?** A generic batch command is more flexible. It supports rollback, fast-forward, and any future batched operation without adding rollback-specific knowledge to the Worker.

## Shim Removal Checklist

Phase 68 shims to remove in this phase:

| Shim | Location | Line | What It Does | Remove When |
|------|----------|------|-------------|-------------|
| `this.pyodide = this.worker` | pyodide_remote_game.js | 64 | Redirects `this.pyodide.*` to Worker | All multiplayer `this.pyodide.*` migrated |
| `runPythonAsync()` | PyodideWorker.js | 132-136 | Sends runPython to Worker | All callers use structured commands |
| `_wrapResult()` | PyodideWorker.js | 147-160 | Adds fake toJs/destroy to Worker results | No callers use toJs/destroy on Worker results |
| `toPy()` | PyodideWorker.js | 172-186 | Wraps JS values for Python embedding | No callers use toPy for template embedding |
| `handleRunPython()` | pyodide_worker.js | 288-305 | Executes arbitrary Python in Worker | No incoming runPython messages |

## Open Questions

1. **Should `validateStateSync()` use a structured command or remain as runPython?**
   - What we know: It runs once during initialization, checks hasattr(env, 'get_state')
   - What's unclear: Is it worth a dedicated Worker command for a one-time check?
   - Recommendation: Create a lightweight `validateCapabilities` Worker command. It's cleaner than keeping runPython as an escape hatch, and it's simple to implement.

2. **Should `_computeHashFromState()` run in Worker or be pure JS?**
   - What we know: It hashes a state object that's already in JS (not current env state). Currently sends JSON to Python for hashing.
   - What's unclear: Can we compute SHA-256 purely in JS with identical output?
   - Recommendation: Use the Web Crypto API (`crypto.subtle.digest('SHA-256', ...)`) for JS-side hashing. The state is already a JS object. This eliminates a Python round-trip. Ensure identical JSON serialization (sort_keys, separators) and float normalization.

3. **How should `render` be exposed in the batch API?**
   - What we know: Several call sites do `env.render()` separately. The `step` and `reset` commands already include render.
   - What's unclear: Is a standalone `render` command needed, or can all post-render needs be folded into step/batch?
   - Recommendation: Add a `render` operation to the batch API. It's needed for post-rollback display and `applyServerState` render.

## Sources

### Primary (HIGH confidence)
- Direct code analysis of:
  - `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/static/js/pyodide_multiplayer_game.js` (lines 900-5500)
  - `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/static/js/PyodideWorker.js` (full file, 293 lines)
  - `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/static/js/pyodide_worker.js` (full file, 306 lines)
  - `/Users/chasemcd/Repositories/interactive-gym/interactive_gym/server/static/js/pyodide_remote_game.js` (full file, 422 lines)

### Secondary (MEDIUM confidence)
- Web Worker postMessage performance: postMessage overhead is ~0.1-0.5ms per call for structured cloneable data. Batching N operations saves N * (0.1-0.5ms + scheduling overhead). For a 5-frame rollback, this is 3-6ms saved.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Direct code analysis of all relevant files
- Architecture (batch API design): HIGH - Pattern proven by existing performRollback batch (line 4827)
- Architecture (state buffer location): HIGH - Clear analysis of access patterns
- Call site catalog: HIGH - Exhaustive grep of all this.pyodide.* usage
- Pitfalls: HIGH - Based on direct code analysis of existing patterns and shim behavior
- Performance claims: MEDIUM - postMessage overhead estimates from general knowledge

**Research date:** 2026-02-04
**Valid until:** 2026-03-06 (30 days - stable codebase, no external dependencies changing)
