import * as ui_utils from './ui_utils.js';
import { emitEpisodeData } from './phaser_gym_graphics.js';
import { PyodideWorker } from './PyodideWorker.js';



export class RemoteGame {
    constructor(config) {
        this.setAttributes(config);
        this.installed_packages = [];
        this.worker = null;
        this.initialize();
    }

    setAttributes(config) {
        this.config = config;
        this.interactive_gym_globals = config.interactive_gym_globals;
        this.sceneId = config.scene_id;  // Store scene ID for incremental data export
        this.pyodideReady = false;
        this.state = null;
        this.objects_to_render = [];
        this.observations = [];
        this.render_state = null;
        this.num_episodes = 0;
        this.max_episodes = config.num_episodes;
        this.step_num = 0;
        this.max_steps = config.max_steps;
        this.cumulative_rewards = {};
        this.shouldReset = true;

        // Pipeline latency metrics (Phase 28 - DIAG-01 to DIAG-07)
        // Tracks timestamps at each stage: keypress -> queue -> step -> render
        this.pipelineMetrics = {
            lastInputTimestamps: null,       // {keypressTimestamp, queueExitTimestamp}
            stepCallTimestamp: null,         // DIAG-03: When step() called
            stepReturnTimestamp: null,       // DIAG-04: When step() returns
            enabled: true,                   // Can be toggled via console: window.pipelineMetricsEnabled = false
            framesSinceLastLog: 0,           // Counter for throttled logging after initial frames
            initialLogFrames: 50             // Log every frame for first N frames
        };
        // Frame counter for single-player (multiplayer has this.frameNumber)
        this.frameNumber = 0;
    }

    isDone(){
        return this.state === "done";
    }

    async initialize() {
        // Create Worker with progress callback
        this.worker = new PyodideWorker({
            onProgress: (stage, message) => {
                console.log(`[RemoteGame:${stage}] ${message}`);
            }
        });

        // Initialize Worker (loads Pyodide in background thread)
        await this.worker.init();

        // Backward-compatibility shim: MultiplayerPyodideGame extends RemoteGame
        // and calls this.pyodide.runPythonAsync() at 30+ sites. PyodideWorker exposes
        // runPythonAsync() which routes through the Worker's postMessage protocol.
        // This shim will be removed in Phase 69 when multiplayer is migrated.
        this.pyodide = this.worker;

        // Install required packages
        if (this.config.packages_to_install?.length > 0) {
            console.log("Installing packages via Worker:", this.config.packages_to_install);
            await this.worker.installPackages(this.config.packages_to_install);
            this.installed_packages.push(...this.config.packages_to_install);
        }

        // Initialize environment with code injection
        // Build envCode that sets up globals and creates env
        const envCode = `
import js
interactive_gym_globals = dict(js.window.interactiveGymGlobals.object_entries())
${this.config.environment_initialization_code}
        `;

        await this.worker.initEnv(envCode, {
            on_game_step_code: this.config.on_game_step_code || ''
        });

        this.state = "ready";
        this.pyodideReady = true;
    }

    async reinitialize_environment(config) {
        this.pyodideReady = false;

        // If we need additional packages, install them via Worker
        if (config.packages_to_install !== undefined) {
            let new_packages = [];
            for (let pkg of config.packages_to_install) {
                if (!this.installed_packages.includes(pkg)) {
                    new_packages.push(pkg);
                }
            }

            if (new_packages.length > 0) {
                await this.worker.installPackages(new_packages);
                this.installed_packages.push(...new_packages);
            }
        }

        // Re-initialize environment via Worker
        const envCode = `
import js
interactive_gym_globals = dict(js.window.interactiveGymGlobals.object_entries())
print("Globals on initialization: ", interactive_gym_globals)
${config.environment_initialization_code}
        `;

        await this.worker.initEnv(envCode, {
            on_game_step_code: config.on_game_step_code || ''
        });

        this.setAttributes(config);
        this.shouldReset = true;
        this.state = "ready";
        this.pyodideReady = true;
    }

    /**
     * Show episode transition UI (waiting message and countdown).
     * Called at the start of reset() for subsequent episodes.
     *
     * @param {string} waitingMessage - Message to show while waiting (optional)
     * @returns {Promise} Resolves when countdown completes
     */
    async showEpisodeTransition(waitingMessage = null) {
        // Check if this is a subsequent episode (not the first one)
        const isSubsequentEpisode = this.num_episodes > 0;

        if (!isSubsequentEpisode) {
            // First episode - just ensure overlay is hidden
            ui_utils.hideEpisodeOverlay();
            return;
        }

        // Show waiting message if provided
        if (waitingMessage) {
            ui_utils.showEpisodeWaiting(waitingMessage);
        }

        // Show countdown before starting
        const episodeNum = this.num_episodes + 1;
        await ui_utils.showEpisodeCountdown(3, `Round ${episodeNum} starting!`);
    }

    async reset() {
        this.shouldReset = false;
        console.log("Resetting the environment");

        // Show episode transition for subsequent episodes
        await this.showEpisodeTransition();

        const startTime = performance.now();
        const result = await this.worker.reset();
        const endTime = performance.now();
        console.log(`Reset operation took ${endTime - startTime} milliseconds`);

        let { obs, infos, render_state } = result;

        // Convert obs to Map for compatibility with existing code
        // Worker returns plain JS objects after normalization
        obs = this._convertToMap(obs);

        // Process render_state (RGB array to binary image) - same as before
        render_state = this._processRenderState(render_state);

        this.step_num = 0;
        this.shouldReset = false;

        // Initialize or reset cumulative rewards based on hud_score_carry_over setting
        // Convert keys to strings for consistent lookup (Python may send int or string keys)
        const carryOver = this.config.hud_score_carry_over || false;
        for (let key of obs.keys()) {
            if (!carryOver || this.cumulative_rewards[key] === undefined) {
                this.cumulative_rewards[key] = 0;
            }
        }

        ui_utils.showHUD();
        ui_utils.updateHUDText(this.getHUDText());


        return [obs, infos, render_state]
    }


    async step(actions) {
        // DIAG-03: Capture timestamp when env.step() is called
        this.pipelineMetrics.stepCallTimestamp = performance.now();

        const result = await this.worker.step(actions);

        // DIAG-04: Capture timestamp when env.step() returns
        this.pipelineMetrics.stepReturnTimestamp = performance.now();

        let { obs, rewards, terminateds, truncateds, infos, render_state } = result;

        // Convert to Maps for consistency with existing code
        obs = this._convertToMap(obs);
        rewards = this._convertToMap(rewards);
        terminateds = this._convertToMap(terminateds);
        truncateds = this._convertToMap(truncateds);

        for (let [key, value] of rewards.entries()) {
            this.cumulative_rewards[key] += value;
        }

        this.step_num = this.step_num + 1;

        // Process render_state (RGB array to binary image)
        render_state = this._processRenderState(render_state);

        ui_utils.updateHUDText(this.getHUDText());

        // Check if the episode is complete
        // Episode ends when: environment terminates/truncates OR max_steps reached
        const all_terminated = Array.from(terminateds.values()).every(value => value === true);
        const all_truncated = Array.from(truncateds.values()).every(value => value === true);
        const max_steps_reached = this.step_num >= this.max_steps;

        if (all_terminated || all_truncated || max_steps_reached) {
            // Emit episode data incrementally to avoid large payloads at scene end
            // This sends the current episode's data and resets the logger
            if (this.sceneId) {
                emitEpisodeData(this.sceneId, this.num_episodes);
            }

            this.num_episodes += 1;

            if (this.num_episodes >= this.max_episodes) {
                this.state = "done";
            } else {
                this.shouldReset = true;
            }
        }

        // Increment frame number for latency logging (multiplayer has its own frameNumber)
        this.frameNumber++;

        return [obs, rewards, terminateds, truncateds, infos, render_state]
    };

    getHUDText() {
        // Calculate score based on hud_display_mode
        let score;

        // For multiplayer, use myPlayerId; for single-player, use first available key or default to 0
        if (this.myPlayerId !== undefined && this.cumulative_rewards[this.myPlayerId] !== undefined) {
            score = this.cumulative_rewards[this.myPlayerId];
        } else {
            // Single-player fallback: use first reward value or 0
            const rewardValues = Object.values(this.cumulative_rewards);
            score = rewardValues.length > 0 ? rewardValues[0] : 0;
        }

        let time_left = (this.max_steps - this.step_num) / this.config.fps;

        let formatted_score = Math.round(score).toString().padStart(2, '0');
        let formatted_time_left = time_left.toFixed(1).toString().padStart(5, '0');

        // Round number is 1-indexed for display
        // Cap at max to avoid showing "Round 3/2" after final episode increments num_episodes
        let current_round = Math.min(this.num_episodes + 1, this.max_episodes);
        let total_rounds = this.max_episodes;

        let hud_text = `Round: ${current_round}/${total_rounds} | Score: ${formatted_score} | Time left: ${formatted_time_left}s`;

        return hud_text
    };

    // ========== Data Conversion Helpers ==========

    /**
     * Convert Worker result (plain object or Map) to Map for compatibility.
     * Worker returns plain JS objects after toJs() conversion, but existing
     * downstream code expects Maps (e.g., rewards.entries(), obs.keys()).
     * @param {Object|Map} obj - Plain object or Map to convert
     * @returns {Map} Map with same key-value pairs
     */
    _convertToMap(obj) {
        if (obj instanceof Map) return obj;
        if (obj === null || obj === undefined) return new Map();
        return new Map(Object.entries(obj));
    }

    /**
     * Process render_state from Worker output to format expected by Phaser renderer.
     * Handles RGB array to base64 image conversion and structured render_state creation.
     * @param {*} render_state - Raw render_state from Worker (array of arrays or object list)
     * @returns {Object} Structured render_state: { game_state_objects, game_image_base64, step }
     */
    _processRenderState(render_state) {
        let game_image_base64 = null;

        if (Array.isArray(render_state) && Array.isArray(render_state[0])
            && Array.isArray(render_state[0][0])) {
            // RGB array: render_state[row][column][RGB values]
            const canvas = document.createElement('canvas');
            const context = canvas.getContext('2d');

            const height = render_state.length;
            const width = render_state[0].length;

            canvas.width = width;
            canvas.height = height;

            const imageData = context.createImageData(width, height);
            const data = imageData.data;

            for (let y = 0; y < height; y++) {
                for (let x = 0; x < width; x++) {
                    const pixelIndex = (y * width + x) * 4;
                    const [r, g, b] = render_state[y][x];

                    data[pixelIndex] = r;
                    data[pixelIndex + 1] = g;
                    data[pixelIndex + 2] = b;
                    data[pixelIndex + 3] = 255;
                }
            }

            context.putImageData(imageData, 0, 0);
            game_image_base64 = canvas.toDataURL('image/png');
        }

        return {
            "game_state_objects": game_image_base64 ? null : (Array.isArray(render_state) ? render_state.map(item => convertUndefinedToNull(item)) : render_state),
            "game_image_base64": game_image_base64,
            "step": this.step_num,
        };
    }

    // ========== Pipeline Latency Instrumentation (Phase 28) ==========

    /**
     * Set input timestamps for pipeline latency tracking (DIAG-01, DIAG-02).
     * Called by phaser_gym_graphics.js before step() with timestamps from keypress.
     * @param {Object} timestamps - {playerId, keypressTimestamp, queueExitTimestamp}
     */
    setInputTimestamps(timestamps) {
        if (!this.pipelineMetrics.enabled) return;
        // Allow console override
        if (typeof window !== 'undefined' && window.pipelineMetricsEnabled === false) return;

        this.pipelineMetrics.lastInputTimestamps = {
            keypressTimestamp: timestamps.keypressTimestamp,
            queueExitTimestamp: timestamps.queueExitTimestamp
        };
    }

    /**
     * Log pipeline latency breakdown (DIAG-07).
     * Called by phaser_gym_graphics.js after rendering completes with render timestamps.
     * @param {number} renderBeginTimestamp - performance.now() when render started (DIAG-05)
     * @param {number} renderCompleteTimestamp - performance.now() when render finished (DIAG-06)
     */
    logPipelineLatency(_renderBeginTimestamp, _renderCompleteTimestamp) {
        // Check if metrics are enabled
        if (!this.pipelineMetrics.enabled) return;
        if (typeof window !== 'undefined' && window.pipelineMetricsEnabled === false) return;

        // Skip if no input timestamps (no real user input this frame)
        if (!this.pipelineMetrics.lastInputTimestamps) return;

        // Throttle logging after initial frames
        this.pipelineMetrics.framesSinceLastLog++;
        const shouldLog = this.frameNumber <= this.pipelineMetrics.initialLogFrames ||
                          this.pipelineMetrics.framesSinceLastLog >= 10;

        if (!shouldLog) {
            // Clear timestamps but don't log
            this.pipelineMetrics.lastInputTimestamps = null;
            return;
        }

        this.pipelineMetrics.framesSinceLastLog = 0;

        // Clear for next input
        this.pipelineMetrics.lastInputTimestamps = null;
    }

    // ========== Cleanup ==========

    /**
     * Clean up Worker resources.
     * Call this when done to prevent memory leaks.
     */
    destroy() {
        if (this.worker) {
            this.worker.destroy();
            this.worker = null;
        }
    }
};



// Helper function to convert all `undefined` values in an object to `null`
export function convertUndefinedToNull(obj) {
    if (typeof obj !== 'object' || obj === null) {
        // Return the value as is if it's not an object or is already null
        return obj;
    }

    for (let key in obj) {
        if (obj[key] === undefined) {
            obj[key] = null; // Convert undefined to null
        } else if (typeof obj[key] === 'object') {
            // Recursively apply the conversion to nested objects
            obj[key] = convertUndefinedToNull(obj[key]);
        }
    }

    return obj;
}
