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
    // Set globals from main thread if provided
    if (payload.globals) {
        for (const [key, value] of Object.entries(payload.globals)) {
            pyodide.globals.set(key, pyodide.toPy(value));
        }
    }

    // Run environment initialization code
    await pyodide.runPythonAsync(payload.envCode);

    self.postMessage({ type: 'envReady', id });
}

/**
 * Execute one environment step with provided actions.
 * Converts Python objects to JS before sending via postMessage.
 * @param {number} id - Request ID
 * @param {Object} payload - { actions: Object }
 */
async function handleStep(id, payload) {
    // Convert actions to Python-compatible format
    const pyActions = JSON.stringify(payload.actions);

    const result = await pyodide.runPythonAsync(`
import json
agent_actions = json.loads('''${pyActions}''')
obs, rewards, terminateds, truncateds, infos = env.step(agent_actions)
render_state = env.render()
(obs, rewards, terminateds, truncateds, infos, render_state)
    `);

    // Convert PyProxy to JS objects for transfer across Worker boundary
    // Use depth: 2 to handle nested structures (dicts with lists, etc.)
    const jsResult = result.toJs({ depth: 2 });
    result.destroy();  // Prevent memory leak

    const [obs, rewards, terminateds, truncateds, infos, render_state] = jsResult;

    self.postMessage({
        type: 'result',
        id,
        result: { obs, rewards, terminateds, truncateds, infos, render_state }
    });
}

/**
 * Reset the environment with optional seed.
 * @param {number} id - Request ID
 * @param {Object} payload - { seed?: number }
 */
async function handleReset(id, payload) {
    const seedValue = payload.seed !== null && payload.seed !== undefined
        ? payload.seed
        : 'None';

    const result = await pyodide.runPythonAsync(`
obs, infos = env.reset(seed=${seedValue})
render_state = env.render()
(obs, infos, render_state)
    `);

    // Convert PyProxy to JS objects for transfer
    const jsResult = result.toJs({ depth: 2 });
    result.destroy();  // Prevent memory leak

    const [obs, infos, render_state] = jsResult;

    self.postMessage({
        type: 'result',
        id,
        result: { obs, infos, render_state }
    });
}
