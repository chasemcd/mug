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

        // Action population settings
        this.actionPopulationMethod = config.action_population_method || 'previous_submitted_action';
        this.defaultAction = config.default_action || 0;

        // Policy mapping (needed to know which agents are human)
        this.policyMapping = config.policy_mapping || {};

        // State broadcast interval (frames between syncs) - used for both server-authoritative and host-based modes
        this.stateBroadcastInterval = config.state_broadcast_interval || 30;
        this.frameNumber = 0;

        // Data logging (only host logs)
        this.shouldLogData = false;

        // Player-to-subject mapping (player_id -> subject_id)
        // Populated when game starts via pyodide_game_ready event
        this.playerSubjects = {};

        // Episode completion tracking
        this.episodeComplete = false;

        // Server-authoritative mode (set when game starts)
        // When true, server broadcasts authoritative state periodically
        this.serverAuthoritative = false;

        // Episode start synchronization (server-authoritative mode)
        // Client waits for server_episode_start before beginning each episode
        this.waitingForEpisodeStart = false;
        this.episodeStartResolve = null;
        this.pendingEpisodeState = null;

        // Diagnostics for lag tracking
        this.diagnostics = {
            lastStepTime: 0,
            stepTimes: [],          // Rolling window of step execution times
            queueSizeHistory: [],   // Track queue sizes over time
            lastDiagnosticsLog: 0,
            lastDiagnosticsFrame: 0,  // Frame number at last diagnostics log
            diagnosticsInterval: 5000,  // Log diagnostics every 5 seconds
            // Track fallback usage per player
            fallbackCount: {},      // player_id -> count of fallback actions used
            queueHitCount: {},      // player_id -> count of actions from queue
            // State sync metrics
            lastSyncFrame: 0,
            lastSyncTime: 0,        // Timestamp of last sync for FPS calculation
            syncCount: 0,
            frameDriftHistory: [],  // Track frame drift at each sync
        };

        // Adaptive throttling to match slower client
        this.throttle = {
            enabled: true,           // Enable adaptive throttling
            queueThreshold: 5,       // Start throttling when queue exceeds this
            maxDelayMs: 50,          // Maximum delay to add per step
            delayPerQueuedAction: 3, // ms delay per queued action above threshold
            skippedFrames: 0,        // Count of frames skipped for throttling
        };

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
            }

            if (!wasHost && this.isHost) {
                console.log(`[MultiplayerPyodide] Promoted to host, now responsible for data logging`);
            }
        });

        // Game ready to start
        socket.on('pyodide_game_ready', (data) => {
            console.log(`[MultiplayerPyodide] Game ${data.game_id} ready with players:`, data.players);
            console.log(`[MultiplayerPyodide] pyodide_game_ready data:`, JSON.stringify(data));

            // Store player-to-subject mapping for data logging
            this.playerSubjects = data.player_subjects || {};
            console.log(`[MultiplayerPyodide] Player-subject mapping:`, this.playerSubjects);

            // Check if server is authoritative
            this.serverAuthoritative = data.server_authoritative || false;
            console.log(`[MultiplayerPyodide] Server-authoritative mode: ${this.serverAuthoritative} (from data: ${data.server_authoritative})`);
            if (this.serverAuthoritative) {
                console.log(`[MultiplayerPyodide] Server-authoritative mode enabled - will receive server_authoritative_state events`);
            } else {
                console.log(`[MultiplayerPyodide] Host-based mode - will send state hashes for verification`);
            }

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
            // Don't queue actions if game is done (prevents queue buildup at game end)
            if (this.state === "done") {
                return;
            }

            const { player_id, action, frame_number } = data;

            // Initialize queue if needed
            if (!this.otherPlayerActionQueues[player_id]) {
                this.otherPlayerActionQueues[player_id] = [];
            }

            // Add to queue (FIFO) - never drop actions to maintain sync
            const queue = this.otherPlayerActionQueues[player_id];
            queue.push({ action, frame_number });

            // Log warning if queue is growing large (client may be running slower)
            // Only warn once every 30 frames to avoid spam
            if (queue.length > 30 && queue.length % 30 === 0) {
                console.warn(`[MultiplayerPyodide] Queue for player ${player_id} is large (${queue.length}), this client may be running slower`);
            }
        });

        // State verification request (host-based mode only)
        // In server-authoritative mode, skip hash computation - server broadcasts state directly
        socket.on('pyodide_verify_state', (data) => {
            if (this.serverAuthoritative) {
                return;  // Server handles state broadcast directly
            }
            this.verifyState(data.frame_number);
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

        // Server-authoritative state broadcast (Option B: Frame-Aligned Stepper)
        // Server periodically broadcasts authoritative state for verification/correction
        socket.on('server_authoritative_state', async (data) => {
            console.log(`[MultiplayerPyodide] Received server_authoritative_state event (serverAuthoritative=${this.serverAuthoritative}, gameId=${this.gameId})`);

            if (!this.serverAuthoritative) {
                console.log(`[MultiplayerPyodide] Ignoring server_authoritative_state - not in server-authoritative mode`);
                return;  // Ignore if not in server-authoritative mode
            }

            const { game_id, state } = data;
            if (game_id !== this.gameId) {
                console.log(`[MultiplayerPyodide] Ignoring server_authoritative_state - game_id mismatch (received: ${game_id}, expected: ${this.gameId})`);
                return;  // Not for this game
            }

            // Calculate sync metrics
            const frameDiff = this.frameNumber - state.frame_number;  // Positive = client ahead
            this.diagnostics.syncCount++;
            this.diagnostics.frameDriftHistory.push(frameDiff);
            if (this.diagnostics.frameDriftHistory.length > 20) {
                this.diagnostics.frameDriftHistory.shift();
            }

            // Gather queue state for logging
            const queueSizes = {};
            let totalQueueSize = 0;
            for (const [playerId, queue] of Object.entries(this.otherPlayerActionQueues)) {
                queueSizes[playerId] = queue.length;
                totalQueueSize += queue.length;
            }

            // Calculate step time stats
            const stepTimes = this.diagnostics.stepTimes;
            const avgStepTime = stepTimes.length > 0
                ? (stepTimes.reduce((a, b) => a + b, 0) / stepTimes.length).toFixed(1)
                : 'N/A';
            const maxStepTime = stepTimes.length > 0
                ? Math.max(...stepTimes).toFixed(1)
                : 'N/A';

            // Calculate fallback rate per player and total
            const fallbackRates = {};
            let totalFallbacks = 0;
            let totalQueueHits = 0;
            for (const [playerId, count] of Object.entries(this.diagnostics.fallbackCount)) {
                const hits = this.diagnostics.queueHitCount[playerId] || 0;
                const total = count + hits;
                fallbackRates[playerId] = total > 0 ? ((count / total) * 100).toFixed(0) + '%' : '0%';
                totalFallbacks += count;
            }
            for (const count of Object.values(this.diagnostics.queueHitCount)) totalQueueHits += count;
            const totalActions = totalFallbacks + totalQueueHits;
            const fallbackRate = totalActions > 0 ? ((totalFallbacks / totalActions) * 100).toFixed(1) : '0.0';

            // Calculate FPS since last sync using actual timestamps
            const now = Date.now();
            const targetFPS = this.config.fps || 10;
            const framesSinceLastSync = this.frameNumber - this.diagnostics.lastSyncFrame;
            const timeSinceLastSync = now - this.diagnostics.lastSyncTime;
            const effectiveFPS = framesSinceLastSync > 0 && this.diagnostics.lastSyncTime > 0 && timeSinceLastSync > 0
                ? ((framesSinceLastSync / timeSinceLastSync) * 1000).toFixed(1)
                : 'N/A';

            // Log comprehensive sync info (matches [Perf] format)
            console.log(
                `[Sync #${this.diagnostics.syncCount}] ` +
                `Server: ${state.frame_number} | Client: ${this.frameNumber} | Drift: ${frameDiff > 0 ? '+' : ''}${frameDiff} | ` +
                `FPS: ${effectiveFPS}/${targetFPS} | ` +
                `Step: ${avgStepTime}ms avg, ${maxStepTime}ms max | ` +
                `Queues: ${totalQueueSize} ${JSON.stringify(queueSizes)} | ` +
                `Fallback: ${fallbackRate}% ${JSON.stringify(fallbackRates)}`
            );

            // Check if we're significantly out of sync
            if (Math.abs(frameDiff) > 5) {
                console.warn(
                    `[Sync] ⚠️ Large drift detected! Applying server state. ` +
                    `Queue pre-sync: ${totalQueueSize}`
                );
                await this.applyServerState(state);
            } else {
                // Small drift is normal - just update cumulative rewards for HUD accuracy
                if (state.cumulative_rewards) {
                    this.cumulative_rewards = state.cumulative_rewards;
                    ui_utils.updateHUDText(this.getHUDText());
                }
            }

            this.diagnostics.lastSyncFrame = state.frame_number;
            this.diagnostics.lastSyncTime = now;
        });

        // Server episode start (server-authoritative mode)
        // Server broadcasts this at the start of each episode so all clients begin from identical state
        socket.on('server_episode_start', async (data) => {
            if (!this.serverAuthoritative) {
                return;  // Ignore if not in server-authoritative mode
            }

            const { game_id, state } = data;
            if (game_id !== this.gameId) {
                return;  // Not for this game
            }

            console.log(`[MultiplayerPyodide] Received server_episode_start for episode ${state.episode_num}`);

            // Store the state for when reset() is called
            this.pendingEpisodeState = state;

            // If we're waiting for the episode start, resolve the promise
            if (this.waitingForEpisodeStart && this.episodeStartResolve) {
                this.episodeStartResolve(state);
                this.episodeStartResolve = null;
                this.waitingForEpisodeStart = false;
            }
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
         * Ensure environment has state sync methods.
         * If the environment doesn't implement get_state/set_state, inject default
         * pickle-based implementations that serialize the entire environment.
         */

        const result = await this.pyodide.runPythonAsync(`
import pickle
import base64

# Check if environment has required methods for state synchronization
has_get_state = hasattr(env, 'get_state') and callable(getattr(env, 'get_state'))
has_set_state = hasattr(env, 'set_state') and callable(getattr(env, 'set_state'))

env_type = type(env).__name__
env_module = type(env).__module__

# If methods are missing, inject default pickle-based implementations
if not has_get_state or not has_set_state:
    print(f"[Python] Environment {env_type} missing state sync methods, injecting defaults...")

    def _default_get_state(self):
        """
        Default pickle-based state serialization.
        Temporarily sets class module to '__main__' for cross-environment compatibility.
        """
        original_module = self.__class__.__module__
        self.__class__.__module__ = '__main__'
        try:
            pickled = pickle.dumps(self)
        finally:
            self.__class__.__module__ = original_module
        encoded = base64.b64encode(pickled).decode('utf-8')
        return {'pickled_state': encoded}

    def _default_set_state(self, state):
        """
        Default pickle-based state deserialization.
        Unpickles and updates this environment's __dict__.
        """
        if 'pickled_state' not in state:
            print("[Python] Warning: No pickled_state in state dict")
            return
        encoded = state['pickled_state']
        pickled = base64.b64decode(encoded.encode('utf-8'))
        restored = pickle.loads(pickled)
        self.__dict__.update(restored.__dict__)

    # Bind methods to the environment instance
    import types
    if not has_get_state:
        env.get_state = types.MethodType(_default_get_state, env)
        print(f"[Python] ✓ Injected default get_state() for {env_type}")

    if not has_set_state:
        env.set_state = types.MethodType(_default_set_state, env)
        print(f"[Python] ✓ Injected default set_state() for {env_type}")

    has_get_state = True
    has_set_state = True

{
    'has_get_state': has_get_state,
    'has_set_state': has_set_state,
    'env_type': env_type,
    'env_module': env_module,
}
        `);

        // State sync validation complete - just need to call toJs() to release the proxy
        void result.toJs();
    }

    async seedPythonEnvironment(seed) {
        /**
         * Seed Python's random number generators for determinism
         */

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
         * Reset environment with re-seeding for episode consistency.
         *
         * In server-authoritative mode:
         * 1. Show "waiting" overlay if this is not the first episode
         * 2. Wait for server_episode_start event with authoritative state
         * 3. Apply the server state to ensure identical starting conditions
         * 4. Show countdown before starting (if not first episode)
         * 5. Then proceed with local reset/render
         *
         * This ensures all clients start each episode from the exact same state.
         */
        this.shouldReset = false;
        console.log(`[Episode] Starting reset for episode ${this.num_episodes + 1}. Player: ${this.myPlayerId}, Game: ${this.gameId}`);

        // Clear action queues at the start of reset to discard stale actions from previous episode
        for (const playerId in this.otherPlayerActionQueues) {
            this.otherPlayerActionQueues[playerId] = [];
        }
        this.lastExecutedActions = {};

        // Reset per-episode diagnostics
        this.diagnostics.syncCount = 0;
        this.diagnostics.frameDriftHistory = [];
        this.diagnostics.fallbackCount = {};
        this.diagnostics.queueHitCount = {};
        this.diagnostics.stepTimes = [];

        // In server-authoritative mode, wait for server to broadcast episode start state
        if (this.serverAuthoritative) {
            // Check if this is a subsequent episode (not the first one)
            const isSubsequentEpisode = this.num_episodes > 0;

            // Show waiting message for subsequent episodes
            if (isSubsequentEpisode) {
                ui_utils.showEpisodeWaiting("Next round will begin shortly...");
            }

            console.log("[MultiplayerPyodide] Waiting for server episode start state...");

            // Check if we already have pending state (server sent it before we called reset)
            let serverState = this.pendingEpisodeState;

            if (!serverState) {
                // Wait for the server to send the episode start state
                serverState = await this.waitForEpisodeStart();
            }

            // Clear pending state
            this.pendingEpisodeState = null;

            if (serverState) {
                console.log(`[MultiplayerPyodide] Applying server episode state (episode ${serverState.episode_num})`);

                // Apply the authoritative state from server
                await this.applyServerState(serverState);

                // Now do local reset to get render state (env state already applied)
                const result = await this.pyodide.runPythonAsync(`
import numpy as np

# Get current obs from environment (state already set by applyServerState)
# Just need to get observations and render without resetting
obs = {}
for agent_id in env.agent_ids if hasattr(env, 'agent_ids') else env.possible_agents if hasattr(env, 'possible_agents') else [0]:
    if hasattr(env, 'observation_space'):
        obs[agent_id] = env.observation_space.sample()  # Placeholder, will be overwritten

# Actually get obs from a step with no-op or from last obs
# Since we set_state, the env should be in correct state
# We need to render to get display state
render_state = env.render()

# Try to get actual observations
if hasattr(env, 'get_obs'):
    obs = env.get_obs()
elif hasattr(env, '_get_obs'):
    obs = env._get_obs()
else:
    # Fallback: do a reset to get obs (state will be overwritten but that's ok for display)
    obs, infos = env.reset(seed=${this.gameSeed || 'None'})

if not isinstance(obs, dict):
    obs = obs.reshape(-1).astype(np.float32)
elif isinstance(obs, dict) and isinstance([*obs.values()][0], dict):
    obs = {k: {kk: vv.reshape(-1).astype(np.float32) for kk, vv in v.items()} for k, v in obs.items()}
elif isinstance(obs, dict):
    obs = {k: v.reshape(-1).astype(np.float32) for k, v in obs.items()}

if not isinstance(obs, dict):
    obs = {"human": obs}

infos = {}
obs, infos, render_state
                `);

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

                // State is already synced from server
                this.step_num = serverState.step_num || 0;
                this.frameNumber = serverState.frame_number || 0;
                this.shouldReset = false;
                this.episodeComplete = false;

                // Use server's cumulative rewards
                if (serverState.cumulative_rewards) {
                    this.cumulative_rewards = serverState.cumulative_rewards;
                }

                // Show and update HUD
                ui_utils.showHUD();
                ui_utils.updateHUDText(this.getHUDText());

                // Show countdown for subsequent episodes before starting
                // Use inherited method (which checks isSubsequentEpisode internally)
                await this.showEpisodeTransition();

                console.log(`[MultiplayerPyodide] Reset complete from server state (episode ${serverState.episode_num})`);
                return [obs, infos, render_state];
            } else {
                // No server state received (timeout or error) - hide overlay and fall through to normal reset
                ui_utils.hideEpisodeOverlay();
            }
        }

        // Non-server-authoritative mode or fallback: do normal reset
        // Show episode transition for subsequent episodes
        await this.showEpisodeTransition();

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

    /**
     * Wait for the server to send the episode start state.
     * Returns a promise that resolves when server_episode_start is received.
     */
    waitForEpisodeStart(timeoutMs = 10000) {
        return new Promise((resolve, reject) => {
            this.waitingForEpisodeStart = true;
            this.episodeStartResolve = resolve;

            // Timeout to prevent hanging forever
            const timeout = setTimeout(() => {
                if (this.waitingForEpisodeStart) {
                    console.warn(`[MultiplayerPyodide] Timeout waiting for server episode start`);
                    this.waitingForEpisodeStart = false;
                    this.episodeStartResolve = null;
                    resolve(null);  // Resolve with null to allow fallback
                }
            }, timeoutMs);

            // Store timeout so we can clear it if resolved
            const originalResolve = this.episodeStartResolve;
            this.episodeStartResolve = (state) => {
                clearTimeout(timeout);
                originalResolve(state);
            };
        });
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

        // Adaptive throttling: slow down if we're the FAST client (partner's actions are accumulating in our queue)
        // Large queue = partner is sending faster than we consume = we're SLOW, don't throttle
        // Empty queue = we're consuming faster than partner sends = we're FAST, should throttle
        //
        // Wait for at least one action in queue before stepping (with timeout)
        // This naturally paces the fast client to match the slow client's action rate
        if (this.throttle.enabled) {
            const totalQueueSize = Object.values(this.otherPlayerActionQueues)
                .reduce((sum, queue) => sum + queue.length, 0);

            // Only throttle if queue is EMPTY or very small (we're faster than partner)
            if (totalQueueSize === 0) {
                // Wait briefly for an action to arrive before using fallback
                await new Promise(resolve => setTimeout(resolve, this.throttle.maxDelayMs));
            }
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
        // Don't send actions during episode transitions to prevent queue buildup
        const inEpisodeTransition = this.episodeComplete || this.waitingForEpisodeStart || this.shouldReset;
        if (!inEpisodeTransition) {
            const myAction = finalActions[this.myPlayerId];
            socket.emit('pyodide_player_action', {
                game_id: this.gameId,
                player_id: this.myPlayerId,
                action: myAction,
                frame_number: this.frameNumber,
                timestamp: Date.now()
            });
        }

        // 3. Step environment immediately with complete actions (no waiting!)
        const stepStartTime = performance.now();
        const stepResult = await this.stepWithActions(finalActions);

        if (!stepResult) {
            return null;
        }

        const [obs, rewards, terminateds, truncateds, infos, render_state] = stepResult;

        // Track step timing for diagnostics
        this.trackStepTime(stepStartTime);

        // 4. Increment frame
        this.frameNumber++;

        // Log diagnostics periodically
        this.logDiagnostics();

        // 5. Trigger periodic state verification (host-based mode only)
        // In server-authoritative mode, the server handles broadcasting
        if (!this.serverAuthoritative && this.stateBroadcastInterval > 0 && this.frameNumber % this.stateBroadcastInterval === 0) {
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

            // Log episode summary
            const queueSizes = {};
            let totalQueueSize = 0;
            for (const [playerId, queue] of Object.entries(this.otherPlayerActionQueues)) {
                queueSizes[playerId] = queue.length;
                totalQueueSize += queue.length;
            }
            console.log(
                `[Episode] Complete at frame ${this.frameNumber} | ` +
                `Rewards: ${JSON.stringify(this.cumulative_rewards)} | ` +
                `Final queues: ${totalQueueSize} ${JSON.stringify(queueSizes)} | ` +
                `Syncs: ${this.diagnostics.syncCount}`
            );

            // Signal scene termination to server
            // Data is saved via remoteGameLogger and sent at scene termination via emit_remote_game_data
            this.signalEpisodeComplete();
        }

        // Return finalActions alongside step results so caller can log synchronized actions
        return [obs, rewards, terminateds, truncateds, infos, render_state, finalActions];
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
            // Track queue hit
            this.diagnostics.queueHitCount[playerIdStr] = (this.diagnostics.queueHitCount[playerIdStr] || 0) + 1;
            return action;
        } else {
            // Queue empty - use fallback based on action_population_method
            // Track fallback usage
            this.diagnostics.fallbackCount[playerIdStr] = (this.diagnostics.fallbackCount[playerIdStr] || 0) + 1;

            if (this.actionPopulationMethod === 'previous_submitted_action') {
                const lastAction = this.lastExecutedActions[playerIdStr];
                return lastAction !== undefined ? lastAction : this.defaultAction;
            } else {
                return this.defaultAction;
            }
        }
    }

    /**
     * Log diagnostics about performance and synchronization.
     * Helps identify lag sources (queue buildup, slow steps, etc.)
     */
    logDiagnostics() {
        const now = Date.now();
        if (now - this.diagnostics.lastDiagnosticsLog < this.diagnostics.diagnosticsInterval) {
            return;  // Not time yet
        }

        // Skip first interval (initialization) - just record baseline
        if (this.diagnostics.lastDiagnosticsLog === 0) {
            this.diagnostics.lastDiagnosticsLog = now;
            this.diagnostics.lastDiagnosticsFrame = this.frameNumber;
            return;
        }

        // Calculate queue sizes
        const queueSizes = {};
        let totalQueueSize = 0;
        for (const [playerId, queue] of Object.entries(this.otherPlayerActionQueues)) {
            queueSizes[playerId] = queue.length;
            totalQueueSize += queue.length;
        }

        // Calculate step time stats
        const stepTimes = this.diagnostics.stepTimes;
        const avgStepTime = stepTimes.length > 0
            ? (stepTimes.reduce((a, b) => a + b, 0) / stepTimes.length).toFixed(1)
            : 'N/A';
        const maxStepTime = stepTimes.length > 0
            ? Math.max(...stepTimes).toFixed(1)
            : 'N/A';

        // Calculate fallback rate per player and total
        const fallbackRates = {};
        let totalFallbacks = 0;
        let totalQueueHits = 0;
        for (const [playerId, count] of Object.entries(this.diagnostics.fallbackCount)) {
            const hits = this.diagnostics.queueHitCount[playerId] || 0;
            const total = count + hits;
            fallbackRates[playerId] = total > 0 ? ((count / total) * 100).toFixed(0) + '%' : '0%';
            totalFallbacks += count;
        }
        for (const count of Object.values(this.diagnostics.queueHitCount)) totalQueueHits += count;
        const totalActions = totalFallbacks + totalQueueHits;
        const overallFallbackRate = totalActions > 0 ? ((totalFallbacks / totalActions) * 100).toFixed(1) : '0.0';

        // Calculate effective FPS from actual frame delta (more accurate than stepTimes.length)
        const targetFPS = this.config.fps || 10;
        const intervalMs = now - this.diagnostics.lastDiagnosticsLog;
        const framesDelta = this.frameNumber - this.diagnostics.lastDiagnosticsFrame;
        const effectiveFPS = intervalMs > 0 ? ((framesDelta / intervalMs) * 1000).toFixed(1) : 'N/A';

        // Log comprehensive summary
        console.log(
            `[Perf] Frame: ${this.frameNumber} | ` +
            `FPS: ${effectiveFPS}/${targetFPS} | ` +
            `Step: ${avgStepTime}ms avg, ${maxStepTime}ms max | ` +
            `Queues: ${totalQueueSize} ${JSON.stringify(queueSizes)} | ` +
            `Fallback: ${overallFallbackRate}% ${JSON.stringify(fallbackRates)}`
        );

        // Warn if queues are growing significantly (indicates throttling may not be keeping up)
        if (totalQueueSize > 15) {
            console.warn(
                `[Perf] ⚠️ Queue buildup: ${totalQueueSize} actions (throttling active). ` +
                `Partner may be significantly slower or network delays occurring.`
            );
        }

        // Warn if fallback rate is high
        if (parseFloat(overallFallbackRate) > 20) {
            console.warn(
                `[Perf] ⚠️ High fallback rate: ${overallFallbackRate}%. ` +
                `Partner actions arriving late - possible network lag or slow partner.`
            );
        }

        // Clear rolling windows for next interval
        this.diagnostics.stepTimes = [];
        // Reset fallback/hit counts for next interval (to see current rate, not cumulative)
        this.diagnostics.fallbackCount = {};
        this.diagnostics.queueHitCount = {};
        // Update tracking for next FPS calculation
        this.diagnostics.lastDiagnosticsLog = now;
        this.diagnostics.lastDiagnosticsFrame = this.frameNumber;
    }

    /**
     * Track step execution time for diagnostics.
     */
    trackStepTime(startTime) {
        const elapsed = performance.now() - startTime;
        this.diagnostics.stepTimes.push(elapsed);

        // Keep only last 100 measurements
        if (this.diagnostics.stepTimes.length > 100) {
            this.diagnostics.stepTimes.shift();
        }
    }

    /**
     * Trigger state verification for hybrid sync.
     * Sends state hash to server for comparison with other clients.
     */
    async triggerStateVerification() {
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
    }

    async computeStateHash() {
        /**
         * Compute hash of current game state using JavaScript crypto.
         * Uses env.get_state() for the environment state (same data used for full sync).
         *
         * Falls back to a simple hash function if crypto.subtle is unavailable
         * (which happens on non-HTTPS connections).
         */
        // Get env state from Python (uses get_state if available, otherwise default pickle method)
        const envState = await this.pyodide.runPythonAsync(`
import json
import pickle
import base64

# Use get_state if available, otherwise use default pickle serialization
if hasattr(env, 'get_state') and callable(getattr(env, 'get_state')):
    _env_state_result = env.get_state()
else:
    # Default pickle-based serialization
    original_module = env.__class__.__module__
    env.__class__.__module__ = '__main__'
    try:
        pickled = pickle.dumps(env)
    finally:
        env.__class__.__module__ = original_module
    _env_state_result = {'pickled_state': base64.b64encode(pickled).decode('utf-8')}

_env_state_result
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

        // Use SubtleCrypto if available (requires HTTPS or localhost)
        // Otherwise fall back to simple hash function
        if (crypto && crypto.subtle) {
            const hashBuffer = await crypto.subtle.digest(
                'SHA-256',
                new TextEncoder().encode(stateStr)
            );
            // Convert to hex string
            return Array.from(new Uint8Array(hashBuffer))
                .map(b => b.toString(16).padStart(2, '0'))
                .join('');
        } else {
            // Fallback: Simple hash function for non-secure contexts (HTTP)
            // This is less secure but functional for sync verification
            return this._simpleHash(stateStr);
        }
    }

    _simpleHash(str) {
        /**
         * Simple string hash function for use when crypto.subtle is unavailable.
         * Based on cyrb53 - a fast, high-quality 53-bit hash.
         * Not cryptographically secure, but sufficient for sync verification.
         */
        let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
        for (let i = 0, ch; i < str.length; i++) {
            ch = str.charCodeAt(i);
            h1 = Math.imul(h1 ^ ch, 2654435761);
            h2 = Math.imul(h2 ^ ch, 1597334677);
        }
        h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507);
        h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909);
        h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507);
        h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909);
        // Return as hex string (similar format to SHA256 output)
        return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16).padStart(16, '0');
    }

    async getFullState() {
        /**
         * Serialize complete environment state (host only)
         *
         * Uses env.get_state() if available, otherwise uses default pickle-based
         * serialization. The result must be JSON-serializable.
         */
        const fullState = await this.pyodide.runPythonAsync(`
import numpy as np
import json
import pickle
import base64

# Get environment state (use get_state if available, otherwise default pickle)
try:
    if hasattr(env, 'get_state') and callable(getattr(env, 'get_state')):
        env_state = env.get_state()
    else:
        # Default pickle-based serialization
        original_module = env.__class__.__module__
        env.__class__.__module__ = '__main__'
        try:
            pickled = pickle.dumps(env)
        finally:
            env.__class__.__module__ = original_module
        env_state = {'pickled_state': base64.b64encode(pickled).decode('utf-8')}
except Exception as e:
    print(f"[Python] Error getting env state: {e}")
    raise RuntimeError(
        f"Failed to get environment state: {e}\\n"
        "Environment must be pickle-serializable or implement get_state() returning JSON-serializable dict."
    )

# Validate that state is JSON-serializable
try:
    json.dumps(env_state)
except (TypeError, ValueError) as e:
    raise ValueError(
        f"Environment state is not JSON-serializable: {e}\\n"
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
         * Uses env.set_state() if available, otherwise uses default pickle-based
         * deserialization if the state contains pickled_state.
         */
        await this.pyodide.runPythonAsync(`
import numpy as np
import pickle
import base64

state_obj = ${this.pyodide.toPy(state)}

# Restore environment state (most important!)
if 'env_state' in state_obj:
    env_state = state_obj['env_state']

    # Use set_state if available, otherwise use default pickle deserialization
    if hasattr(env, 'set_state') and callable(getattr(env, 'set_state')):
        env.set_state(env_state)
        print("[Python] ✓ Restored environment state via set_state()")
    elif 'pickled_state' in env_state:
        # Default pickle-based deserialization
        encoded = env_state['pickled_state']
        pickled = base64.b64decode(encoded.encode('utf-8'))
        restored = pickle.loads(pickled)
        env.__dict__.update(restored.__dict__)
        print("[Python] ✓ Restored environment state via pickle deserialization")
    else:
        print("[Python] Warning: Cannot restore env state - no set_state method and no pickled_state")
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

    async applyServerState(state) {
        /**
         * Apply authoritative state from server (server-authoritative mode).
         *
         * Similar to applyFullState but uses server's state format.
         * Called when client detects significant frame drift from server.
         */
        console.log(`[MultiplayerPyodide] Applying server authoritative state (server frame: ${state.frame_number}, client frame: ${this.frameNumber})`);

        // If server provides env_state, apply it
        if (state.env_state) {
            await this.pyodide.runPythonAsync(`
import numpy as np
import pickle
import base64

env_state = ${this.pyodide.toPy(state.env_state)}

# Use set_state if available, otherwise use default pickle deserialization
if hasattr(env, 'set_state') and callable(getattr(env, 'set_state')):
    env.set_state(env_state)
    print("[Python] ✓ Applied server authoritative state via set_state()")
elif 'pickled_state' in env_state:
    # Default pickle-based deserialization
    encoded = env_state['pickled_state']
    pickled = base64.b64decode(encoded.encode('utf-8'))
    restored = pickle.loads(pickled)
    env.__dict__.update(restored.__dict__)
    print("[Python] ✓ Applied server authoritative state via pickle deserialization")
else:
    print("[Python] Warning: Cannot apply server state - no set_state method and no pickled_state")
            `);
        }

        // Sync JavaScript-side state
        if (state.episode_num !== undefined) {
            this.num_episodes = state.episode_num;
        }
        if (state.step_num !== undefined) {
            this.step_num = state.step_num;
        }
        if (state.frame_number !== undefined) {
            this.frameNumber = state.frame_number;
        }
        if (state.cumulative_rewards) {
            this.cumulative_rewards = state.cumulative_rewards;
        }

        // Clear action queues to start fresh from new state
        for (const playerId in this.otherPlayerActionQueues) {
            this.otherPlayerActionQueues[playerId] = [];
        }
        this.lastExecutedActions = {};

        // Update HUD
        ui_utils.updateHUDText(this.getHUDText());

        console.log(`[MultiplayerPyodide] Server state applied, now at frame ${this.frameNumber}`);
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
