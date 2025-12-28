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
import * as ui_utils from './ui_utils.js';

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

        // Action queue synchronization (Option B)
        this.otherPlayerActionQueues = {};  // { player_id: [{action, frame_number}, ...] }
        this.lastExecutedActions = {};      // { player_id: last_action } for fallback
        // Note: No queue size limit - we never drop actions to maintain sync

        // Queue-based resync threshold (triggers state sync if queue grows too large)
        this.queueResyncThreshold = config.queue_resync_threshold || 50;  // Trigger resync if queue > 50
        this.resyncRequested = false;  // Prevent multiple resync requests

        // Action population settings
        this.actionPopulationMethod = config.action_population_method || 'previous_submitted_action';
        this.defaultAction = config.default_action || 0;

        // Policy mapping (needed to know which agents are human)
        this.policyMapping = config.policy_mapping || {};

        // Periodic state sync (null = disabled, number = frames between syncs)
        this.stateSyncFrequencyFrames = config.state_sync_frequency_frames;  // null to disable, or number of frames
        this.frameNumber = 0;

        // Data logging (only host logs)
        this.shouldLogData = false;

        // Player-to-subject mapping (player_id -> subject_id)
        // Populated when game starts via pyodide_game_ready event
        this.playerSubjects = {};

        // Episode completion tracking
        this.episodeComplete = false;

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
                console.debug(`[MultiplayerPyodide] Promoted to host!`);
            }

            if (!wasHost && this.isHost) {
                console.warn(`[MultiplayerPyodide] Now responsible for data logging`);
            }
        });

        // Game ready to start
        socket.on('pyodide_game_ready', (data) => {
            console.log(`[MultiplayerPyodide] Game ${data.game_id} ready with players:`, data.players);

            // Store player-to-subject mapping for data logging
            this.playerSubjects = data.player_subjects || {};
            console.log(`[MultiplayerPyodide] Player-subject mapping:`, this.playerSubjects);

            // Initialize action queues for other players
            for (const playerId of data.players) {
                if (playerId != this.myPlayerId) {
                    this.otherPlayerActionQueues[playerId] = [];
                    console.log(`[MultiplayerPyodide] Initialized action queue for player ${playerId}`);
                }
            }
        });

        // Receive other player's action (Action Queue - Option B)
        socket.on('pyodide_other_player_action', (data) => {
            const { player_id, action, frame_number } = data;

            // Initialize queue if needed
            if (!this.otherPlayerActionQueues[player_id]) {
                this.otherPlayerActionQueues[player_id] = [];
            }

            // Add to queue (FIFO) - never drop actions to maintain sync
            const queue = this.otherPlayerActionQueues[player_id];
            queue.push({ action, frame_number });

            // Check if queue exceeds threshold - trigger resync if so
            if (queue.length > this.queueResyncThreshold && !this.resyncRequested) {
                console.warn(`[MultiplayerPyodide] Queue for player ${player_id} exceeded threshold (${queue.length} > ${this.queueResyncThreshold}), requesting state resync`);
                this.resyncRequested = true;
                this.requestStateResync();
            } else if (queue.length > 30) {
                console.warn(`[MultiplayerPyodide] Queue for player ${player_id} is large (${queue.length}), this client may be running slower`);
            }

            console.debug(`[MultiplayerPyodide] Queued action ${action} from player ${player_id} for frame ${frame_number} (queue size: ${queue.length})`);
        });

        // State verification request (hybrid fallback)
        socket.on('pyodide_verify_state', (data) => {
            if (this.stateSyncFrequencyFrames !== null) {
                this.verifyState(data.frame_number);
            }
        });

        // Apply full state (non-host only)
        socket.on('pyodide_apply_full_state', async (data) => {
            if (!this.isHost) {
                console.log(`[MultiplayerPyodide] Applying full state from host...`);
                await this.applyFullState(data.state);

                // Clear action queues for fresh start
                for (const playerId in this.otherPlayerActionQueues) {
                    this.otherPlayerActionQueues[playerId] = [];
                }
                this.lastExecutedActions = {};
                this.resyncRequested = false;  // Allow future resyncs
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

                // Broadcast HUD to ensure it's synced after state resync
                this.broadcastHUD();

                this.resyncRequested = false;  // Allow future resyncs
                // Clear action queues for fresh start
                for (const playerId in this.otherPlayerActionQueues) {
                    this.otherPlayerActionQueues[playerId] = [];
                }
                this.lastExecutedActions = {};
                console.log(`[MultiplayerPyodide] Host sent state at frame ${this.frameNumber}`);
            }
        });

        // Receive synchronized HUD text from host (via server broadcast)
        socket.on('pyodide_hud_sync', (data) => {
            ui_utils.updateHUDText(data.hud_text);
        });
    }

    /**
     * Broadcast HUD text to all players (host only).
     * Called after reset and each step to keep HUD synchronized.
     */
    broadcastHUD() {
        if (!this.isHost) {
            return;
        }

        const hudText = this.getHUDText();
        socket.emit('pyodide_hud_update', {
            game_id: this.gameId,
            hud_text: hudText
        });
    }

    /**
     * Request a state resync from the host when queue grows too large.
     * This client is falling behind and needs to catch up via full state transfer.
     * Client continues running and will snap to correct state when it arrives.
     */
    requestStateResync() {
        console.warn(`[MultiplayerPyodide] Requesting state resync - this client is behind`);

        // Request resync from server (which will ask host for state)
        socket.emit('pyodide_request_resync', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            frame_number: this.frameNumber,
            reason: 'queue_overflow'
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
        console.log("[MultiplayerPyodide] Resetting environment. Player:", this.myPlayerId, "Game:", this.gameId, "Seed:", this.gameSeed);

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
        this.episodeComplete = false;  // Reset episode completion flag

        // Initialize or reset cumulative rewards based on hud_score_carry_over setting
        // Convert keys to strings for consistent lookup (Python may send int or string keys)
        const carryOver = this.config.hud_score_carry_over || false;
        for (let key of obs.keys()) {
            if (!carryOver || this.cumulative_rewards[key] === undefined) {
                this.cumulative_rewards[key] = 0;
            }
        }

        // Show and update HUD locally (stays in sync when environments are in sync)
        ui_utils.showHUD();
        ui_utils.updateHUDText(this.getHUDText());

        return [obs, infos, render_state];
    }

    async step(allActionsDict) {
        /**
         * Step environment in multiplayer mode (Action Queue approach)
         *
         * Process:
         * 1. Build final action dict (my action + queue actions for others)
         * 2. Send MY action to server (for other clients' queues)
         * 3. Step environment immediately (no waiting!)
         * 4. Optionally verify state (hybrid fallback)
         * 5. Log data if host
         */

        // Don't step until multiplayer setup is complete
        if (this.myPlayerId === null || this.myPlayerId === undefined) {
            console.warn('[MultiplayerPyodide] Waiting for player ID assignment...');
            return null;
        }

        if (this.gameId === null || this.gameId === undefined) {
            console.warn('[MultiplayerPyodide] Waiting for game ID assignment...');
            return null;
        }

        // 1. Build final action dict with queue lookups for other players
        const finalActions = {};

        for (const [agentId, policy] of Object.entries(this.policyMapping)) {
            const agentIdStr = String(agentId);
            const myPlayerIdStr = String(this.myPlayerId);

            if (agentIdStr === myPlayerIdStr) {
                // My action - from input
                finalActions[agentId] = allActionsDict[agentId];
                if (finalActions[agentId] === undefined || finalActions[agentId] === null) {
                    finalActions[agentId] = this.defaultAction;
                }
            } else if (policy === 'human') {
                // Other human player - pop from queue
                finalActions[agentId] = this.getOtherPlayerAction(agentId);
            } else {
                // Bot - from allActionsDict (already computed by phaser_gym_graphics)
                finalActions[agentId] = allActionsDict[agentId];
                if (finalActions[agentId] === undefined || finalActions[agentId] === null) {
                    finalActions[agentId] = this.defaultAction;
                }
            }
        }

        // Track last executed actions for fallback
        for (const [agentId, action] of Object.entries(finalActions)) {
            this.lastExecutedActions[agentId] = action;
        }

        // 2. Send MY action to server (for other clients to queue)
        const myAction = finalActions[this.myPlayerId];
        socket.emit('pyodide_player_action', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            action: myAction,
            frame_number: this.frameNumber,
            timestamp: Date.now()
        });

        console.debug(`[MultiplayerPyodide] Frame ${this.frameNumber}: Stepping with actions`, finalActions);

        // 3. Step environment immediately with complete actions (no waiting!)
        const stepResult = await this.stepWithActions(finalActions);

        if (!stepResult) {
            return null;
        }

        const [obs, rewards, terminateds, truncateds, infos, render_state] = stepResult;

        // 4. Increment frame
        this.frameNumber++;

        // 5. Optionally trigger periodic state sync
        if (this.stateSyncFrequencyFrames !== null && this.frameNumber % this.stateSyncFrequencyFrames === 0) {
            this.triggerStateVerification();
        }

        // 6. If host, log data
        if (this.shouldLogData) {
            this.logFrameData({
                frame: this.frameNumber,
                observations: obs,
                actions: finalActions,
                rewards: rewards,
                terminateds: terminateds,
                truncateds: truncateds,
                infos: infos,
                player_subjects: this.playerSubjects  // Include player->subject mapping in every frame
            });
        }

        // 7. Check if episode is complete (only trigger once)
        const all_terminated = Array.from(terminateds.values()).every(value => value === true);
        const all_truncated = Array.from(truncateds.values()).every(value => value === true);

        if ((all_terminated || all_truncated) && !this.episodeComplete) {
            this.episodeComplete = true;
            console.log('[MultiplayerPyodide] Episode complete');

            // Signal scene termination to server
            // Data is saved via remoteGameLogger and sent at scene termination via emit_remote_game_data
            this.signalEpisodeComplete();
        }

        return [obs, rewards, terminateds, truncateds, infos, render_state];
    }

    /**
     * Get action for another player from their action queue.
     * Falls back to action_population_method if queue is empty.
     */
    getOtherPlayerAction(playerId) {
        const playerIdStr = String(playerId);
        const queue = this.otherPlayerActionQueues[playerIdStr];

        if (queue && queue.length > 0) {
            // Pop oldest action from queue (FIFO)
            const { action } = queue.shift();
            console.debug(`[MultiplayerPyodide] Popped action ${action} from player ${playerId}'s queue (remaining: ${queue.length})`);
            return action;
        } else {
            // Queue empty - use fallback based on action_population_method
            console.debug(`[MultiplayerPyodide] Queue empty for player ${playerId}, using fallback (${this.actionPopulationMethod})`);

            if (this.actionPopulationMethod === 'previous_submitted_action') {
                const lastAction = this.lastExecutedActions[playerIdStr];
                return lastAction !== undefined ? lastAction : this.defaultAction;
            } else {
                return this.defaultAction;
            }
        }
    }

    /**
     * Trigger state verification for hybrid sync.
     * Sends state hash to server for comparison with other clients.
     */
    async triggerStateVerification() {
        console.log(`[MultiplayerPyodide] Triggering state verification at frame ${this.frameNumber}`);
        const stateHash = await this.computeStateHash();
        socket.emit('pyodide_state_hash', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            hash: stateHash,
            frame_number: this.frameNumber
        });
    }

    // Keep waitForAllActions for backwards compatibility but it's no longer used
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

        // Update cumulative rewards (convert keys to strings for consistency)
        for (let [key, value] of rewards.entries()) {
            this.cumulative_rewards[key] += value;
        }

        this.step_num++;

        // Update HUD
        ui_utils.updateHUDText(this.getHUDText());

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
         * Compute SHA256 hash of current game state using JavaScript crypto.
         * Uses env.get_state() for the environment state (same data used for full sync).
         */
        // Get env state from Python (reuses the get_state() method)
        const envState = await this.pyodide.runPythonAsync(`
import json
env.get_state()
        `);

        // Build state dict in JavaScript
        const stateDict = {
            env_state: envState.toJs({ dict_converter: Object.fromEntries }),
            frame: this.frameNumber,
            step: this.step_num,
            cumulative_rewards: this.cumulative_rewards,
        };

        // Create deterministic JSON string (sort keys for consistency)
        const stateStr = JSON.stringify(stateDict, Object.keys(stateDict).sort());

        // Hash in JavaScript using SubtleCrypto (hardware-accelerated)
        const hashBuffer = await crypto.subtle.digest(
            'SHA-256',
            new TextEncoder().encode(stateStr)
        );

        // Convert to hex string
        return Array.from(new Uint8Array(hashBuffer))
            .map(b => b.toString(16).padStart(2, '0'))
            .join('');
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

    logFrameData(_data) {
        /**
         * No-op: Data logging is handled by remoteGameLogger in processPyodideGame().
         * Data is accumulated locally and sent to server at scene termination
         * via emit_remote_game_data.
         */
    }

    signalEpisodeComplete() {
        /**
         * Mark the game as done when episode completes.
         *
         * This sets state to "done" which causes isDone() to return true.
         * The existing checkPyodideDone interval in index.js will pick this up
         * and trigger the advance_scene flow, which properly calls deactivate()
         * on the scene and emits terminate_scene with full metadata.
         * That in turn calls terminateGymScene() which saves data via emit_remote_game_data.
         */
        this.num_episodes += 1;

        if (this.num_episodes >= this.max_episodes) {
            this.state = "done";
            console.log(`[MultiplayerPyodide] Game complete (${this.num_episodes}/${this.max_episodes} episodes)`);
        } else {
            this.shouldReset = true;
            console.log(`[MultiplayerPyodide] Episode ${this.num_episodes}/${this.max_episodes} complete, will reset`);
        }
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
