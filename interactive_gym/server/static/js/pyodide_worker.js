/**
 * pyodide_worker.js - Web Worker script for Pyodide execution
 *
 * This Worker loads Pyodide in an isolated thread, preventing WASM compilation
 * from blocking the main thread. This allows Socket.IO to respond to ping messages
 * during initialization, preventing false disconnects.
 *
 * Message Protocol:
 *   Incoming: { type, id, payload }
 *     - type: 'installPackages' | 'initEnv' | 'step' | 'reset'
 *              | 'getState' | 'setState' | 'computeHash' | 'seedRng' | 'render' | 'batch'
 *     - id: request ID for response correlation
 *     - payload: type-specific data
 *
 *   Outgoing: { type, id?, result?, error?, stage?, message? }
 *     - type: 'progress' | 'ready' | 'installed' | 'envReady' | 'result' | 'error'
 *
 * @module pyodide_worker
 * @see PyodideWorker.js for main thread counterpart
 */

// Load Pyodide from CDN using importScripts (required for Workers, not ES6 import)
importScripts('https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.js');

// READY gate pattern - prevents race conditions
let pyodide = null;
let pyodideReady = false;
const messageQueue = [];
let onGameStepCode = '';  // Stores code to run before each step (e.g., policy calls)

/**
 * Initialize Pyodide immediately on Worker start.
 * Queues any messages received before Pyodide is ready.
 */
const initPromise = (async () => {
    try {
        self.postMessage({
            type: 'progress',
            stage: 'loading',
            message: 'Loading Pyodide...',
            timestamp: Date.now()
        });

        pyodide = await loadPyodide();

        self.postMessage({
            type: 'progress',
            stage: 'micropip',
            message: 'Loading micropip...',
            timestamp: Date.now()
        });

        await pyodide.loadPackage('micropip');

        pyodideReady = true;
        self.postMessage({ type: 'ready', timestamp: Date.now() });

        // Process any messages that arrived before we were ready
        while (messageQueue.length > 0) {
            await handleMessage(messageQueue.shift());
        }
    } catch (error) {
        self.postMessage({
            type: 'error',
            error: {
                message: error.message,
                stack: error.stack,
                name: error.name
            }
        });
    }
})();

/**
 * Message handler - queues messages if Pyodide not ready, otherwise processes immediately.
 */
self.onmessage = async function(event) {
    if (!pyodideReady) {
        messageQueue.push(event.data);
        return;
    }
    await handleMessage(event.data);
};

/**
 * Route message to appropriate handler based on type.
 * @param {Object} msg - Message with type, id, and payload
 */
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
            case 'getState':
                await handleGetState(id, payload);
                break;
            case 'setState':
                await handleSetState(id, payload);
                break;
            case 'computeHash':
                await handleComputeHash(id, payload);
                break;
            case 'seedRng':
                await handleSeedRng(id, payload);
                break;
            case 'render':
                await handleRender(id, payload);
                break;
            case 'batch':
                await handleBatch(id, payload);
                break;
            default:
                self.postMessage({
                    type: 'error',
                    id,
                    error: {
                        message: `Unknown message type: ${type}`,
                        stack: null
                    }
                });
        }
    } catch (error) {
        self.postMessage({
            type: 'error',
            id,
            error: {
                message: error.message,
                stack: error.stack,
                name: error.name
            }
        });
    }
}

/**
 * Install Python packages via micropip.
 * Sends progress messages for each package.
 * @param {number} id - Request ID
 * @param {Object} payload - { packages: string[] }
 */
async function handleInstallPackages(id, payload) {
    const micropip = pyodide.pyimport('micropip');

    for (const pkg of payload.packages) {
        self.postMessage({
            type: 'progress',
            id,
            stage: 'install',
            message: `Installing ${pkg}...`,
            timestamp: Date.now()
        });
        await micropip.install(pkg);
    }

    self.postMessage({ type: 'installed', id });
}

/**
 * Initialize Python environment by running environment code.
 * The code should create an `env` variable in Python globals.
 * @param {number} id - Request ID
 * @param {Object} payload - { envCode: string, globals?: Object }
 */
async function handleInitEnv(id, payload) {
    // Extract on_game_step_code if present, store in Worker-level variable
    // Remove it from globals before setting Python globals
    if (payload.globals) {
        if (payload.globals.on_game_step_code !== undefined) {
            onGameStepCode = payload.globals.on_game_step_code || '';
            delete payload.globals.on_game_step_code;  // Don't set as Python global
        }
        for (const [key, value] of Object.entries(payload.globals)) {
            pyodide.globals.set(key, pyodide.toPy(value));
        }
    }

    // Run environment initialization code
    await pyodide.runPythonAsync(payload.envCode);

    self.postMessage({ type: 'envReady', id });
}

/**
 * Execute one environment step with provided actions (internal, no postMessage).
 * Used by handleStep and handleBatch.
 * @param {Object} payload - { actions: Object }
 * @returns {Object} Step result: { obs, rewards, terminateds, truncateds, infos, render_state }
 */
async function handleStepInternal(payload) {
    // Convert actions to Python-compatible format
    const pyActions = JSON.stringify(payload.actions);

    // Build Python code: on_game_step_code first, then step, then normalize
    const result = await pyodide.runPythonAsync(`
import json
import numpy as np

# Run any environment-specific pre-step code (e.g., policy calls)
${onGameStepCode}

agent_actions = json.loads('''${pyActions}''')
obs, rewards, terminateds, truncateds, infos = env.step(agent_actions)
render_state = env.render()

# Normalize obs to dict with numpy arrays flattened
if not isinstance(obs, dict):
    obs = obs.reshape(-1).astype(np.float32)
elif isinstance(obs, dict) and len(obs) > 0 and isinstance([*obs.values()][0], dict):
    obs = {k: {kk: vv.reshape(-1).astype(np.float32) for kk, vv in v.items()} for k, v in obs.items()}
elif isinstance(obs, dict):
    obs = {k: v.reshape(-1).astype(np.float32) if hasattr(v, 'reshape') else v for k, v in obs.items()}

if not isinstance(obs, dict):
    obs = {"human": obs}

# Normalize rewards to dict
if isinstance(rewards, (float, int)):
    rewards = {"human": rewards}

# Normalize terminateds/truncateds to dict
if not isinstance(terminateds, dict):
    terminateds = {"human": terminateds}
if not isinstance(truncateds, dict):
    truncateds = {"human": truncateds}

(obs, rewards, terminateds, truncateds, infos, render_state)
    `);

    // Convert PyProxy to JS objects for transfer across Worker boundary
    const jsResult = result.toJs({ depth: 2 });
    result.destroy();  // Prevent memory leak

    const [obs, rewards, terminateds, truncateds, infos, render_state] = jsResult;

    return { obs, rewards, terminateds, truncateds, infos, render_state };
}

/**
 * Execute one environment step with provided actions.
 * Converts Python objects to JS before sending via postMessage.
 * @param {number} id - Request ID
 * @param {Object} payload - { actions: Object }
 */
async function handleStep(id, payload) {
    const result = await handleStepInternal(payload);
    self.postMessage({ type: 'result', id, result });
}

/**
 * Reset the environment with optional seed (internal, no postMessage).
 * Used by handleReset and handleBatch.
 * @param {Object} payload - { seed?: number }
 * @returns {Object} Reset result: { obs, infos, render_state }
 */
async function handleResetInternal(payload) {
    const seedValue = payload.seed !== null && payload.seed !== undefined
        ? payload.seed
        : 'None';

    const result = await pyodide.runPythonAsync(`
import numpy as np
obs, infos = env.reset(seed=${seedValue})
render_state = env.render()

# Normalize obs to dict with numpy arrays flattened
if not isinstance(obs, dict):
    obs = obs.reshape(-1).astype(np.float32)
elif isinstance(obs, dict) and len(obs) > 0 and isinstance([*obs.values()][0], dict):
    obs = {k: {kk: vv.reshape(-1).astype(np.float32) for kk, vv in v.items()} for k, v in obs.items()}
elif isinstance(obs, dict):
    obs = {k: v.reshape(-1).astype(np.float32) if hasattr(v, 'reshape') else v for k, v in obs.items()}

if not isinstance(obs, dict):
    obs = {"human": obs}

(obs, infos, render_state)
    `);

    // Convert PyProxy to JS objects for transfer
    const jsResult = result.toJs({ depth: 2 });
    result.destroy();  // Prevent memory leak

    const [obs, infos, render_state] = jsResult;

    return { obs, infos, render_state };
}

/**
 * Reset the environment with optional seed.
 * @param {number} id - Request ID
 * @param {Object} payload - { seed?: number }
 */
async function handleReset(id, payload) {
    const result = await handleResetInternal(payload);
    self.postMessage({ type: 'result', id, result });
}

// ─────────────────────────────────────────────────────────────────────────────
// State management and batch handlers (Phase 69)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Capture the current environment state and RNG states (internal, no postMessage).
 * Returns a JSON string containing env_state, numpy RNG state, and Python random state.
 * Used by handleGetState and handleBatch.
 * @param {Object} payload - {} (empty)
 * @returns {string} JSON string of { env_state, np_rng_state, py_rng_state }
 */
async function handleGetStateInternal(payload) {
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

    return result;
}

/**
 * Capture the current environment state and RNG states.
 * @param {number} id - Request ID
 * @param {Object} payload - {} (empty)
 */
async function handleGetState(id, payload) {
    const result = await handleGetStateInternal(payload);
    self.postMessage({ type: 'result', id, result });
}

/**
 * Restore environment state and RNG states from a JSON snapshot (internal, no postMessage).
 * Used by handleSetState and handleBatch.
 * @param {Object} payload - { stateJson: string }
 * @returns {Object} { ok: true }
 */
async function handleSetStateInternal(payload) {
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

    return { ok: true };
}

/**
 * Restore environment state and RNG states from a JSON snapshot.
 * @param {number} id - Request ID
 * @param {Object} payload - { stateJson: string }
 */
async function handleSetState(id, payload) {
    const result = await handleSetStateInternal(payload);
    self.postMessage({ type: 'result', id, result });
}

/**
 * Compute a SHA-256 hash of the current environment state or a provided state (internal, no postMessage).
 * Normalizes floats to 10 decimal places for deterministic hashing.
 * Used by handleComputeHash and handleBatch.
 * @param {Object} payload - {} to hash current env state, or { stateJson: string } to hash provided state
 * @returns {Object} { hash: string } - First 16 chars of SHA-256 hex digest
 */
async function handleComputeHashInternal(payload) {
    let pythonCode;
    if (payload.stateJson) {
        const escapedJson = payload.stateJson.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        pythonCode = `
import json
import hashlib

_state_to_hash = json.loads('''${escapedJson}''')
`;
    } else {
        pythonCode = `
import json
import hashlib

_state_to_hash = env.get_state()
`;
    }

    pythonCode += `
def _normalize_for_hash(obj):
    if isinstance(obj, float):
        return round(obj, 10)
    elif isinstance(obj, dict):
        return {k: _normalize_for_hash(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_normalize_for_hash(v) for v in obj]
    return obj

_normalized = _normalize_for_hash(_state_to_hash)
_json_str = json.dumps(_normalized, sort_keys=True, separators=(',', ':'))
hashlib.sha256(_json_str.encode()).hexdigest()[:16]
`;

    const result = await pyodide.runPythonAsync(pythonCode);
    return { hash: result };
}

/**
 * Compute a SHA-256 hash of the current environment state or a provided state.
 * @param {number} id - Request ID
 * @param {Object} payload - {} to hash current env state, or { stateJson: string } to hash provided state
 */
async function handleComputeHash(id, payload) {
    const result = await handleComputeHashInternal(payload);
    self.postMessage({ type: 'result', id, result });
}

/**
 * Seed numpy and Python random number generators (internal, no postMessage).
 * Used by handleSeedRng and handleBatch.
 * @param {Object} payload - { seed: number }
 * @returns {Object} { ok: true }
 */
async function handleSeedRngInternal(payload) {
    await pyodide.runPythonAsync(`
import numpy as np
import random

np.random.seed(${payload.seed})
random.seed(${payload.seed})
    `);

    return { ok: true };
}

/**
 * Seed numpy and Python random number generators.
 * @param {number} id - Request ID
 * @param {Object} payload - { seed: number }
 */
async function handleSeedRng(id, payload) {
    const result = await handleSeedRngInternal(payload);
    self.postMessage({ type: 'result', id, result });
}

/**
 * Render the current environment state (internal, no postMessage).
 * Returns raw render_state data; caller is responsible for processing.
 * Used by handleRender and handleBatch.
 * @param {Object} payload - {} (empty)
 * @returns {Object} { render_state: any }
 */
async function handleRenderInternal(payload) {
    const result = await pyodide.runPythonAsync(`
render_state = env.render()
render_state
    `);

    // Convert PyProxy to JS if needed
    let jsResult;
    if (result && typeof result.toJs === 'function') {
        jsResult = result.toJs({ depth: 2 });
        result.destroy();
    } else {
        jsResult = result;
    }

    return { render_state: jsResult };
}

/**
 * Render the current environment state.
 * @param {number} id - Request ID
 * @param {Object} payload - {} (empty)
 */
async function handleRender(id, payload) {
    const result = await handleRenderInternal(payload);
    self.postMessage({ type: 'result', id, result });
}

/**
 * Execute a batch of operations sequentially in a single round-trip.
 * Stops on first error, returning partial results.
 * @param {number} id - Request ID
 * @param {Object} payload - { operations: [{ op: string, params: object }] }
 */
async function handleBatch(id, payload) {
    const results = [];

    for (let i = 0; i < payload.operations.length; i++) {
        const { op, params } = payload.operations[i];
        try {
            switch (op) {
                case 'setState':
                    results.push(await handleSetStateInternal(params));
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
                case 'seedRng':
                    results.push(await handleSeedRngInternal(params));
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

