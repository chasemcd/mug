/**
 * Multiplayer Pyodide Game
 *
 * Extends RemoteGame to support multiplayer Pyodide games where:
 * - Each client runs their own Pyodide environment
 * - Server coordinates action synchronization
 * - Deterministic execution via seeded RNG
 * - Only host logs data (avoids duplicates)
 * - State verification detects desyncs
 */

import * as pyodide_remote_game from './pyodide_remote_game.js';
import { convertUndefinedToNull } from './pyodide_remote_game.js';
import * as seeded_random from './seeded_random.js';

export class MultiplayerPyodideGame extends pyodide_remote_game.RemoteGame {
    constructor(config) {
        super(config);

        // Multiplayer state
        this.isHost = false;
        this.hostPlayerId = null;
        this.myPlayerId = config.player_id;
        this.otherPlayerIds = config.other_player_ids || [];
        this.gameId = config.game_id;
        this.gameSeed = null;

        // Action synchronization
        this.pendingMyAction = null;
        this.allActionsReady = false;
        this.allActions = null;
        this.actionPromiseResolve = null;

        // State verification
        this.verificationFrequency = 30;
        this.frameNumber = 0;

        // Data logging (only host logs)
        this.shouldLogData = false;

        // Game state tracking
        this.isPaused = false;

        this.setupMultiplayerHandlers();
    }

    setupMultiplayerHandlers() {
        /**
         * Set up SocketIO event handlers for multiplayer coordination
         */

        // Host election
        socket.on('pyodide_host_elected', (data) => {
            this.myPlayerId = data.player_id;  // Set from server-assigned player ID
            this.gameId = data.game_id;  // Set game ID
            this.isHost = data.is_host;
            this.shouldLogData = data.is_host;
            this.hostPlayerId = data.is_host ? this.myPlayerId : data.host_id;
            this.gameSeed = data.game_seed;

            // Initialize seeded RNG for AI policies
            if (this.gameSeed) {
                seeded_random.initMultiplayerRNG(this.gameSeed);
                console.log(`[MultiplayerPyodide] Player ${this.myPlayerId} in game ${this.gameId} initialized with seed ${this.gameSeed}`);
                console.log(`[MultiplayerPyodide] Host status: ${this.isHost}`);
            }
        });

        // Host changed (after disconnection)
        socket.on('pyodide_host_changed', (data) => {
            const wasHost = this.isHost;
            this.hostPlayerId = data.new_host_id;

            if (this.myPlayerId === data.new_host_id) {
                this.isHost = true;
                this.shouldLogData = true;
                console.log(`[MultiplayerPyodide] Promoted to host!`);
            }

            if (!wasHost && this.isHost) {
                console.warn(`[MultiplayerPyodide] Now responsible for data logging`);
            }
        });

        // Game ready to start
        socket.on('pyodide_game_ready', (data) => {
            console.log(`[MultiplayerPyodide] Game ${data.game_id} ready with players:`, data.players);
            this.isPaused = false;
        });

        // Actions ready from server
        socket.on('pyodide_actions_ready', (data) => {
            this.allActions = data.actions;
            this.allActionsReady = true;

            // Verify we're on the expected frame (should match what we sent)
            if (this.frameNumber !== data.frame_number) {
                console.warn(
                    `[MultiplayerPyodide] Frame mismatch: Client at ${this.frameNumber}, ` +
                    `server broadcast for ${data.frame_number}. This may indicate timing issues.`
                );
            }

            console.debug(`[MultiplayerPyodide] Frame ${data.frame_number}: Actions ready`, data.actions);

            if (this.actionPromiseResolve) {
                this.actionPromiseResolve(data.actions);
                this.actionPromiseResolve = null;
            }
        });

        // State verification request
        socket.on('pyodide_verify_state', (data) => {
            this.verifyState(data.frame_number);
        });

        // Pause for resync
        socket.on('pyodide_pause_for_resync', (data) => {
            console.warn(`[MultiplayerPyodide] Desync detected at frame ${data.frame_number}, pausing for resync...`);
            this.isPaused = true;
            this.state = "paused";
            // Clear any pending action promises to prevent deadlock
            if (this.actionPromiseResolve) {
                this.actionPromiseResolve(null);
                this.actionPromiseResolve = null;
            }
        });

        // Apply full state (non-host only)
        socket.on('pyodide_apply_full_state', async (data) => {
            if (!this.isHost) {
                console.log(`[MultiplayerPyodide] Applying full state from host...`);
                await this.applyFullState(data.state);

                // Clear action buffers
                this.allActionsReady = false;
                this.allActions = null;
                this.actionPromiseResolve = null;

                this.isPaused = false;
                this.state = "ready";
                console.log(`[MultiplayerPyodide] State resynced from host, now at frame ${this.frameNumber}`);
            }
        });

        // Request full state (host only)
        socket.on('pyodide_request_full_state', async (data) => {
            if (this.isHost) {
                console.log(`[MultiplayerPyodide] Providing full state for resync at frame ${data.frame_number}`);
                const fullState = await this.getFullState();
                socket.emit('pyodide_send_full_state', {
                    game_id: this.gameId,
                    state: fullState
                });

                // Host can also resume after sending state
                this.isPaused = false;
                this.state = "ready";
                // Clear action buffers for fresh start
                this.allActionsReady = false;
                this.allActions = null;
                this.actionPromiseResolve = null;
                console.log(`[MultiplayerPyodide] Host resuming at frame ${this.frameNumber}`);
            }
        });
    }

    async initialize() {
        /**
         * Initialize Pyodide and environment with seeded RNG
         */
        await super.initialize();

        // Validate that environment supports multiplayer state synchronization
        await this.validateStateSync();

        // Seed Python environment if seed available
        if (this.gameSeed !== null) {
            await this.seedPythonEnvironment(this.gameSeed);
        }
    }

    async validateStateSync() {
        /**
         * Verify that the environment implements required state sync methods
         */
        console.log("[MultiplayerPyodide] Validating environment state sync API...");

        const validationResult = await this.pyodide.runPythonAsync(`
# Check if environment has required methods for state synchronization
has_get_state = hasattr(env, 'get_state') and callable(getattr(env, 'get_state'))
has_set_state = hasattr(env, 'set_state') and callable(getattr(env, 'set_state'))

result = {
    'has_get_state': has_get_state,
    'has_set_state': has_set_state,
    'env_type': type(env).__name__,
    'env_module': type(env).__module__,
}

result
        `);

        const result = await this.pyodide.toPy(validationResult).toJs();
        const hasGetState = result.get('has_get_state');
        const hasSetState = result.get('has_set_state');
        const envType = result.get('env_type');
        const envModule = result.get('env_module');

        if (!hasGetState || !hasSetState) {
            const missingMethods = [];
            if (!hasGetState) missingMethods.push('get_state()');
            if (!hasSetState) missingMethods.push('set_state()');

            const errorMsg =
                `\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n` +
                `❌ Multiplayer State Sync API Error\n` +
                `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n` +
                `Environment: ${envType} (${envModule})\n\n` +
                `Missing required methods: ${missingMethods.join(', ')}\n\n` +
                `For multiplayer synchronization, environments must implement:\n\n` +
                `  def get_state(self) -> dict:\n` +
                `      \"\"\"Return JSON-serializable state dict\"\"\"\n` +
                `      return {...}  # Complete environment state\n\n` +
                `  def set_state(self, state: dict) -> None:\n` +
                `      \"\"\"Restore environment from state dict\"\"\"\n` +
                `      # Restore all environment variables from state\n\n` +
                `See documentation: docs/multiplayer_state_sync_api.md\n` +
                `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`;

            console.error(errorMsg);
            throw new Error(
                `Environment ${envType} is missing required methods for multiplayer: ` +
                `${missingMethods.join(', ')}. See console for details.`
            );
        }

        console.log(`[MultiplayerPyodide] ✓ Environment ${envType} supports state synchronization`);
    }

    async seedPythonEnvironment(seed) {
        /**
         * Seed Python's random number generators for determinism
         */
        console.log(`[MultiplayerPyodide] Seeding Python environment with seed: ${seed}`);

        await this.pyodide.runPythonAsync(`
import numpy as np
import random

# Seed both numpy and Python's random module
np.random.seed(${seed})
random.seed(${seed})

print(f"[Python] Seeded RNG with {${seed}}")
        `);
    }

    async reset() {
        /**
         * Reset environment with re-seeding for episode consistency
         */
        this.shouldReset = false;
        console.log("[MultiplayerPyodide] Resetting environment. Player:", this.myPlayerId, "Game:", this.gameId);

        // Re-seed for deterministic resets
        if (this.gameSeed !== null) {
            await this.seedPythonEnvironment(this.gameSeed);
            seeded_random.resetMultiplayerRNG();
        }

        const startTime = performance.now();
        const result = await this.pyodide.runPythonAsync(`
import numpy as np
obs, infos = env.reset(seed=${this.gameSeed || 'None'})
render_state = env.render()

if not isinstance(obs, dict):
    obs = obs.reshape(-1).astype(np.float32)
elif isinstance(obs, dict) and isinstance([*obs.values()][0], dict):
    obs = {k: {kk: vv.reshape(-1).astype(np.float32) for kk, vv in v.items()} for k, v in obs.items()}
elif isinstance(obs, dict):
    obs = {k: v.reshape(-1).astype(np.float32) for k, v in obs.items()}
else:
    raise ValueError(f"obs is not a valid type, got {type(obs)} but need array, dict, or dict of dicts.")

if not isinstance(obs, dict):
    obs = {"human": obs}

obs, infos, render_state
        `);

        const endTime = performance.now();
        console.log(`[MultiplayerPyodide] Reset took ${endTime - startTime}ms`);

        let [obs, infos, render_state] = await this.pyodide.toPy(result).toJs();

        // Handle RGB array rendering if needed
        let game_image_binary = null;
        if (Array.isArray(render_state) && Array.isArray(render_state[0])) {
            game_image_binary = this.convertRGBArrayToImage(render_state);
        }

        render_state = {
            "game_state_objects": game_image_binary ? null : render_state.map(item => convertUndefinedToNull(item)),
            "game_image_base64": game_image_binary,
            "step": this.step_num,
        };

        this.step_num = 0;
        this.frameNumber = 0;
        this.shouldReset = false;

        // Initialize cumulative rewards
        for (let key of obs.keys()) {
            this.cumulative_rewards[key] = 0;
        }

        return [obs, infos, render_state];
    }

    async step(allActionsDict) {
        /**
         * Step environment in multiplayer mode
         *
         * Process:
         * 1. Extract and send MY action to server
         * 2. Wait for all player actions
         * 3. Step environment with all actions
         * 4. Verify state if needed
         * 5. Log data if host
         */

        if (this.isPaused) {
            console.warn('[MultiplayerPyodide] Game paused, waiting for resync...');
            return null;
        }

        // Don't step until multiplayer setup is complete
        if (this.myPlayerId === null || this.myPlayerId === undefined) {
            console.warn('[MultiplayerPyodide] Waiting for player ID assignment...');
            return null;
        }

        if (this.gameId === null || this.gameId === undefined) {
            console.warn('[MultiplayerPyodide] Waiting for game ID assignment...');
            return null;
        }

        // Extract only MY action from the dict (key should match myPlayerId)
        let myAction = allActionsDict[this.myPlayerId];

        if (myAction === undefined) {
            console.error(`[MultiplayerPyodide] No action found for player ${this.myPlayerId} in actions:`, allActionsDict);
            myAction = 0;  // Default action
        }

        // 1. Send my action to server
        socket.emit('pyodide_player_action', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            action: myAction,
            frame_number: this.frameNumber,
            timestamp: Date.now()
        });

        console.debug(`[MultiplayerPyodide] Frame ${this.frameNumber}: Sent my action (player ${this.myPlayerId}): ${myAction}`);

        // 2. Wait for all player actions from server
        const allActions = await this.waitForAllActions();

        // Handle timeout
        if (allActions === null) {
            console.error('[MultiplayerPyodide] Failed to receive coordinated actions, skipping frame');
            return null;
        }

        // 3. Step environment with all actions (deterministic)
        const stepResult = await this.stepWithActions(allActions);

        if (!stepResult) {
            return null;
        }

        const [obs, rewards, terminateds, truncateds, infos, render_state] = stepResult;

        // 4. Increment frame
        this.frameNumber++;

        // 5. If host, log data
        if (this.shouldLogData) {
            this.logFrameData({
                frame: this.frameNumber,
                observations: obs,
                actions: allActions,
                rewards: rewards,
                terminateds: terminateds,
                truncateds: truncateds,
                infos: infos
            });
        }

        // 6. Check if episode is complete
        const all_terminated = Array.from(terminateds.values()).every(value => value === true);
        const all_truncated = Array.from(truncateds.values()).every(value => value === true);

        if ((all_terminated || all_truncated) && this.shouldLogData) {
            console.log('[MultiplayerPyodide] Episode complete, saving accumulated data');
            this.saveEpisodeData();
        }

        return [obs, rewards, terminateds, truncateds, infos, render_state];
    }

    waitForAllActions() {
        /**
         * Wait for server to broadcast all player actions
         * with a timeout to prevent deadlock
         */
        return new Promise((resolve, reject) => {
            if (this.allActionsReady) {
                const actions = this.allActions;
                this.allActionsReady = false;
                this.allActions = null;
                resolve(actions);
            } else {
                this.actionPromiseResolve = resolve;

                // Add timeout to prevent hanging forever (10 seconds)
                setTimeout(() => {
                    if (this.actionPromiseResolve === resolve) {
                        console.error(
                            `[MultiplayerPyodide] Timeout waiting for actions at frame ${this.frameNumber}. ` +
                            `This may indicate a desync or network issue.`
                        );
                        this.actionPromiseResolve = null;
                        // Resolve with null to allow game to continue
                        resolve(null);
                    }
                }, 10000);
            }
        });
    }

    async stepWithActions(actions) {
        /**
         * Step environment with collected actions from all players
         */
        const pyActions = this.pyodide.toPy(actions);

        const result = await this.pyodide.runPythonAsync(`
${this.config.on_game_step_code || ''}
import numpy as np

# Convert action keys to proper types
agent_actions = {int(k) if k.isnumeric() or isinstance(k, (float, int)) else k: v for k, v in ${pyActions}.items()}

obs, rewards, terminateds, truncateds, infos = env.step(agent_actions)
render_state = env.render()

# Flatten observations for consistency
if not isinstance(obs, dict):
    obs = obs.reshape(-1).astype(np.float32)
elif isinstance(obs, dict) and isinstance([*obs.values()][0], dict):
    obs = {k: {kk: vv.reshape(-1).astype(np.float32) for kk, vv in v.items()} for k, v in obs.items()}
elif isinstance(obs, dict):
    obs = {k: v.reshape(-1).astype(np.float32) for k, v in obs.items()}

if isinstance(rewards, (float, int)):
    rewards = {"human": rewards}

if not isinstance(obs, dict):
    obs = {"human": obs}

if not isinstance(terminateds, dict):
    terminateds = {"human": terminateds}

if not isinstance(truncateds, dict):
    truncateds = {"human": truncateds}

obs, rewards, terminateds, truncateds, infos, render_state
        `);

        let [obs, rewards, terminateds, truncateds, infos, render_state] =
            await this.pyodide.toPy(result).toJs();

        // Update cumulative rewards
        for (let [key, value] of rewards.entries()) {
            this.cumulative_rewards[key] = (this.cumulative_rewards[key] || 0) + value;
        }

        this.step_num++;

        // Handle RGB array rendering if needed
        let game_image_base64 = null;
        if (Array.isArray(render_state) && Array.isArray(render_state[0])) {
            game_image_base64 = this.convertRGBArrayToImage(render_state);
        }

        render_state = {
            "game_state_objects": game_image_base64 ? null : render_state.map(item => convertUndefinedToNull(item)),
            "game_image_base64": game_image_base64,
            "step": this.step_num,
        };

        return [obs, rewards, terminateds, truncateds, infos, render_state];
    }

    async verifyState(frameNumber) {
        /**
         * Compute and send state hash for verification
         */
        const stateHash = await this.computeStateHash();

        socket.emit('pyodide_state_hash', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            hash: stateHash,
            frame_number: frameNumber
        });

        console.debug(`[MultiplayerPyodide] Frame ${frameNumber}: Sent state hash ${stateHash.slice(0, 8)}...`);
    }

    async computeStateHash() {
        /**
         * Compute SHA256 hash of current game state
         */
        const hashData = await this.pyodide.runPythonAsync(`
import hashlib
import json
import numpy as np

# Get current state information
state_dict = {
    'step': env.t if hasattr(env, 't') else ${this.step_num},
    'frame': ${this.frameNumber},
    'cumulative_rewards': {k: float(v) for k, v in ${this.pyodide.toPy(this.cumulative_rewards)}.items()},
    'rng_state': str(np.random.get_state()[1][:5].tolist()),  # Include RNG state
}

# Create deterministic string
state_str = json.dumps(state_dict, sort_keys=True)
hash_val = hashlib.sha256(state_str.encode()).hexdigest()
hash_val
        `);

        return hashData;
    }

    async getFullState() {
        /**
         * Serialize complete environment state (host only)
         *
         * Requires environment to implement get_state() method that returns
         * a JSON-serializable dict containing complete state.
         */
        const fullState = await this.pyodide.runPythonAsync(`
import numpy as np

# Get environment state (must be JSON-serializable)
# This call will raise an error if get_state() is not implemented properly
try:
    env_state = env.get_state()
except Exception as e:
    print(f"[Python] Error calling env.get_state(): {e}")
    raise RuntimeError(
        f"env.get_state() failed: {e}\\n"
        "Environment must return a JSON-serializable dict containing complete state."
    )

# Validate that state is JSON-serializable
import json
try:
    json.dumps(env_state)
except (TypeError, ValueError) as e:
    raise ValueError(
        f"env.get_state() returned non-JSON-serializable data: {e}\\n"
        "State must contain only primitive types (int, float, str, bool, list, dict)"
    )

state_dict = {
    'episode_num': ${this.num_episodes},
    'step_num': ${this.step_num},
    'frame_number': ${this.frameNumber},
    'cumulative_rewards': ${this.pyodide.toPy(this.cumulative_rewards)},
    'numpy_rng_state': np.random.get_state()[1].tolist(),
    'env_state': env_state,
}

state_dict
        `);

        const state = await this.pyodide.toPy(fullState).toJs();

        // Convert to plain object
        const plainState = {};
        for (let [key, value] of state.entries()) {
            plainState[key] = value;
        }

        return plainState;
    }

    async applyFullState(state) {
        /**
         * Restore state from host's serialized data (non-host only)
         *
         * Requires environment to implement set_state() method that accepts
         * the dict returned by get_state() and fully restores the environment.
         */
        await this.pyodide.runPythonAsync(`
import numpy as np

state_obj = ${this.pyodide.toPy(state)}

# Restore environment state (most important!)
if 'env_state' in state_obj:
    try:
        env.set_state(state_obj['env_state'])
        print("[Python] ✓ Restored environment state via set_state()")
    except Exception as e:
        print(f"[Python] Error calling env.set_state(): {e}")
        raise RuntimeError(
            f"env.set_state() failed: {e}\\n"
            "Environment must accept the dict from get_state() and fully restore state."
        )
else:
    print("[Python] Warning: No env_state in sync data")

# Restore RNG state
if 'numpy_rng_state' in state_obj:
    rng_state_list = state_obj['numpy_rng_state']
    rng_state_array = np.array(rng_state_list, dtype=np.uint32)

    # Create full RNG state tuple (for numpy's set_state)
    full_state = ('MT19937', rng_state_array, 0, 0, 0.0)
    np.random.set_state(full_state)

    print("[Python] ✓ Restored RNG state")
        `);

        // Restore JavaScript-side state
        this.num_episodes = state.episode_num;
        this.step_num = state.step_num;
        this.frameNumber = state.frame_number;
        this.cumulative_rewards = state.cumulative_rewards;

        // Reset JavaScript RNG
        if (this.gameSeed) {
            seeded_random.resetMultiplayerRNG();
        }

        console.log('[MultiplayerPyodide] Applied full state from host');
    }

    logFrameData(data) {
        /**
         * Send data to server for logging (host only)
         */
        if (!this.shouldLogData) {
            return;
        }

        socket.emit('pyodide_log_data', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            data: data,
            frame_number: this.frameNumber
        });
    }

    saveEpisodeData() {
        /**
         * Trigger server to save accumulated episode data (host only)
         *
         * Called when episode completes to save all accumulated frame
         * data to CSV file.
         */
        if (!this.shouldLogData) {
            return;
        }

        // Get scene_id and subject_id from config
        const scene_id = this.config.scene_id || 'unknown_scene';
        const subject_id = window.subjectId || 'unknown_subject';

        socket.emit('pyodide_save_episode_data', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            scene_id: scene_id,
            subject_id: subject_id,
            interactiveGymGlobals: this.interactive_gym_globals || {}
        });

        console.log(
            `[MultiplayerPyodide] Requested save for episode in scene ${scene_id}, ` +
            `subject ${subject_id}`
        );
    }

    convertRGBArrayToImage(rgbArray) {
        /**
         * Convert RGB array to base64 image (from parent class logic)
         */
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');

        const height = rgbArray.length;
        const width = rgbArray[0].length;

        canvas.width = width;
        canvas.height = height;

        const imageData = context.createImageData(width, height);
        const data = imageData.data;

        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                const pixelIndex = (y * width + x) * 4;
                const [r, g, b] = rgbArray[y][x];

                data[pixelIndex] = r;
                data[pixelIndex + 1] = g;
                data[pixelIndex + 2] = b;
                data[pixelIndex + 3] = 255;
            }
        }

        context.putImageData(imageData, 0, 0);
        return canvas.toDataURL('image/png');
    }
}
