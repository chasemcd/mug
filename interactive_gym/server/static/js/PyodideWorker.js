/**
 * PyodideWorker.js - Main thread class for Worker communication
 *
 * Provides an async interface to the Pyodide Web Worker. Handles:
 * - Worker lifecycle (creation, destruction)
 * - Request/response correlation via IDs
 * - Progress event callbacks
 * - Error propagation as rejected promises
 *
 * Usage:
 *   const worker = new PyodideWorker({
 *       onProgress: (stage, message) => console.log(`[${stage}] ${message}`)
 *   });
 *   await worker.init();
 *   await worker.installPackages(['numpy']);
 *   await worker.initEnv('import gymnasium; env = gymnasium.make("CartPole-v1")');
 *   const { obs, infos, render_state } = await worker.reset();
 *   const { obs, rewards, terminateds, truncateds, infos, render_state } = await worker.step({ 0: 1 });
 *   const stateJson = await worker.getState();       // Capture env + RNG state as JSON
 *   await worker.setState(stateJson);                 // Restore env + RNG state from JSON
 *   const { hash } = await worker.computeHash();      // SHA-256 hash of current env state
 *   await worker.seedRng(42);                          // Seed numpy + Python random
 *   const { render_state } = await worker.render();    // Standalone env.render()
 *   const results = await worker.batch([...]);         // Sequential multi-op execution
 *   worker.destroy();
 *
 * @module PyodideWorker
 * @see pyodide_worker.js for Worker-side implementation
 */

export class PyodideWorker {
    /**
     * Create a new PyodideWorker instance.
     * @param {Object} options - Configuration options
     * @param {Function} [options.onProgress] - Callback for progress events: (stage, message) => void
     */
    constructor(options = {}) {
        this.worker = null;
        this.pendingRequests = new Map();  // id -> { resolve, reject }
        this.requestCounter = 0;
        this.onProgress = options.onProgress || null;
        this.ready = false;

        // For resolving init() promise when ready event received
        this._initResolve = null;
        this._initReject = null;
    }

    /**
     * Initialize the Worker and wait for Pyodide to be ready.
     * @returns {Promise<void>} Resolves when Worker sends 'ready' event
     * @throws {Error} If Worker fails to create or Pyodide fails to load
     */
    async init() {
        return new Promise((resolve, reject) => {
            this._initResolve = resolve;
            this._initReject = reject;

            // Create Worker from separate file
            // Path must match Flask static file serving: /static/js/pyodide_worker.js
            this.worker = new Worker('/static/js/pyodide_worker.js');

            // Set up message handler
            this.worker.onmessage = (event) => this._handleMessage(event);

            // Set up error handler for uncaught Worker errors
            this.worker.onerror = (error) => {
                console.error('[PyodideWorker] Worker error:', error);
                if (this._initReject) {
                    this._initReject(new Error(`Worker creation failed: ${error.message}`));
                    this._initResolve = null;
                    this._initReject = null;
                }
                // Reject all pending requests
                for (const [id, { reject }] of this.pendingRequests) {
                    reject(new Error(`Worker error: ${error.message}`));
                }
                this.pendingRequests.clear();
            };
        });
    }

    /**
     * Install Python packages via micropip.
     * @param {string[]} packages - Package names to install
     * @returns {Promise<void>} Resolves when all packages installed
     * @throws {Error} If Worker not ready or installation fails
     */
    async installPackages(packages) {
        this._assertReady();
        return this._sendRequest('installPackages', { packages });
    }

    /**
     * Initialize the Python environment by running environment code.
     * The code should create an `env` variable in Python globals.
     * @param {string} envCode - Python code to execute
     * @param {Object} [globals] - Optional globals to set before running code
     * @returns {Promise<void>} Resolves when environment is ready
     * @throws {Error} If Worker not ready or code execution fails
     */
    async initEnv(envCode, globals = null) {
        this._assertReady();
        return this._sendRequest('initEnv', { envCode, globals });
    }

    /**
     * Execute one environment step.
     * @param {Object} actions - Actions to apply (agent_id -> action mapping)
     * @returns {Promise<Object>} Step result: { obs, rewards, terminateds, truncateds, infos, render_state }
     * @throws {Error} If Worker not ready or step fails
     */
    async step(actions) {
        this._assertReady();
        return this._sendRequest('step', { actions });
    }

    /**
     * Reset the environment.
     * @param {number|null} [seed=null] - Optional seed for reproducibility
     * @returns {Promise<Object>} Reset result: { obs, infos, render_state }
     * @throws {Error} If Worker not ready or reset fails
     */
    async reset(seed = null) {
        this._assertReady();
        return this._sendRequest('reset', { seed });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // State management and batch methods (Phase 69)
    // ─────────────────────────────────────────────────────────────────────────

    /**
     * Capture the current environment state and RNG states.
     * Returns a JSON string containing env_state, numpy RNG state, and Python random state.
     * The caller can store/parse this string as needed.
     * @returns {Promise<string>} JSON string of { env_state, np_rng_state, py_rng_state }
     * @throws {Error} If Worker not ready or state capture fails
     */
    async getState() {
        this._assertReady();
        return this._sendRequest('getState', {});
    }

    /**
     * Restore environment state and RNG states from a JSON snapshot.
     * @param {string} stateJson - JSON string from getState() (full snapshot)
     * @returns {Promise<Object>} { ok: true }
     * @throws {Error} If Worker not ready or state restoration fails
     */
    async setState(stateJson) {
        this._assertReady();
        return this._sendRequest('setState', { stateJson });
    }

    /**
     * Compute a SHA-256 hash of the environment state.
     * If stateJson is provided, hashes that state. Otherwise hashes the current env state.
     * @param {string|null} [stateJson=null] - Optional JSON state to hash (null = hash current env)
     * @returns {Promise<Object>} { hash: string } - First 16 chars of SHA-256 hex digest
     * @throws {Error} If Worker not ready or hash computation fails
     */
    async computeHash(stateJson = null) {
        this._assertReady();
        return this._sendRequest('computeHash', { stateJson });
    }

    /**
     * Seed numpy and Python random number generators.
     * @param {number} seed - Seed value for both numpy and Python random
     * @returns {Promise<Object>} { ok: true }
     * @throws {Error} If Worker not ready or seeding fails
     */
    async seedRng(seed) {
        this._assertReady();
        return this._sendRequest('seedRng', { seed });
    }

    /**
     * Render the current environment state.
     * Returns raw render_state data; caller is responsible for processing
     * (e.g., via _processRenderState on the game class).
     * @returns {Promise<Object>} { render_state: any }
     * @throws {Error} If Worker not ready or render fails
     */
    async render() {
        this._assertReady();
        return this._sendRequest('render', {});
    }

    /**
     * Execute a batch of operations sequentially in a single Worker round-trip.
     * Operations are executed in order. Stops on first error with partial results.
     * Supported ops: 'setState', 'getState', 'step', 'reset', 'computeHash', 'render', 'seedRng'
     * @param {Array<{op: string, params: Object}>} operations - Array of operations
     * @returns {Promise<Array>} Array of results in same order as operations
     * @throws {Error} If Worker not ready, or a batch operation fails (error includes failedIndex and partialResults)
     */
    async batch(operations) {
        this._assertReady();
        return this._sendRequest('batch', { operations });
    }

    /**
     * Run arbitrary Python code in the Worker.
     * Backward-compatibility shim for MultiplayerPyodideGame which uses
     * this.pyodide.runPythonAsync() directly. Will be removed in Phase 69
     * when multiplayer is migrated to structured Worker commands.
     * @param {string} code - Python code to execute
     * @returns {Promise<any>} Result of the Python expression (converted to JS)
     * @throws {Error} If Worker not ready or code execution fails
     */
    async runPythonAsync(code) {
        this._assertReady();
        const result = await this._sendRequest('runPython', { code });
        return PyodideWorker._wrapResult(result);
    }

    /**
     * Wrap a Worker result in a PyProxy-like object so existing code that calls
     * result.toJs({dict_converter}) or result.destroy() doesn't crash.
     * Worker already converts via toJs({depth:2}), so toJs() is a passthrough.
     * @param {*} value - JS value from Worker
     * @returns {*} Value with .toJs() and .destroy() methods added
     * @private
     * @static
     */
    static _wrapResult(value) {
        if (value === null || value === undefined || typeof value !== 'object') {
            return value;
        }
        // Add PyProxy-compatible methods
        value.toJs = function(options) {
            if (options && options.dict_converter === Object.fromEntries && this instanceof Map) {
                return Object.fromEntries(this);
            }
            return this;
        };
        value.destroy = function() {};  // No-op: no PyProxy to clean up
        return value;
    }

    /**
     * Convert a JS value to a Python-compatible representation.
     * Backward-compatibility shim for MultiplayerPyodideGame which uses
     * this.pyodide.toPy(obj) in two patterns:
     *   1. Template literal embedding: `${this.pyodide.toPy(actions)}` — toString() returns Python expr
     *   2. Result post-processing: `this.pyodide.toPy(result).toJs()` — toJs() returns JS value
     * Will be removed in Phase 69 when multiplayer is migrated.
     * @param {*} value - JS value to convert
     * @returns {Object} Wrapper with toString() for Python embedding and toJs() for passthrough
     */
    toPy(value) {
        const jsonStr = JSON.stringify(value);
        return {
            // For template literal embedding: produces json.loads('...') Python expression
            toString() {
                return `json.loads('${jsonStr.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}')`;
            },
            // For result post-processing: Worker's handleRunPython already called
            // toJs({depth:2}) which converts Python tuples to Arrays and dicts to Maps.
            // Pass through unchanged.
            toJs(_options) {
                return value;
            }
        };
    }

    /**
     * Clean up Worker resources.
     * Call this when done to prevent memory leaks.
     */
    destroy() {
        if (this.worker) {
            this.worker.terminate();
            this.worker = null;
        }
        this.pendingRequests.clear();
        this.ready = false;
    }

    /**
     * Generate next request ID.
     * @returns {number} Unique request ID
     * @private
     */
    _nextId() {
        return ++this.requestCounter;
    }

    /**
     * Assert that Worker is ready for commands.
     * @throws {Error} If Worker not initialized or not ready
     * @private
     */
    _assertReady() {
        if (!this.ready) {
            throw new Error('PyodideWorker not ready. Call init() and await it first.');
        }
    }

    /**
     * Send a request to the Worker and return a Promise for the response.
     * @param {string} type - Request type
     * @param {Object} payload - Request payload
     * @returns {Promise<any>} Resolves with result or rejects with error
     * @private
     */
    _sendRequest(type, payload) {
        return new Promise((resolve, reject) => {
            const id = this._nextId();
            this.pendingRequests.set(id, { resolve, reject });
            this.worker.postMessage({ type, id, payload });
        });
    }

    /**
     * Handle incoming Worker messages.
     * Routes to appropriate handler based on message type.
     * @param {MessageEvent} event - Worker message event
     * @private
     */
    _handleMessage(event) {
        const { type, id, result, error, stage, message, timestamp } = event.data;

        // Handle progress events (no response correlation needed)
        if (type === 'progress') {
            if (this.onProgress) {
                this.onProgress(stage, message, timestamp);
            }
            return;
        }

        // Handle ready event (resolves init() promise)
        if (type === 'ready') {
            this.ready = true;
            if (this._initResolve) {
                this._initResolve();
                this._initResolve = null;
                this._initReject = null;
            }
            return;
        }

        // Handle request/response correlation
        const pending = this.pendingRequests.get(id);
        if (!pending) {
            console.warn('[PyodideWorker] Received response for unknown request ID:', id);
            return;
        }

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
                const err = new Error(error.message);
                err.stack = error.stack;
                err.name = error.name || 'WorkerError';
                pending.reject(err);
                break;
            default:
                console.warn('[PyodideWorker] Unknown message type:', type);
                pending.resolve(result);
        }
    }
}
