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
        this.myPlayerId = config.player_id;
        this.gameId = config.game_id;
        this.gameSeed = null;

        // ========== GGPO Rollback Netcode ==========
        // Input delay: local inputs are scheduled for frame N + INPUT_DELAY
        // This gives time for inputs to reach the other player before they're needed
        this.INPUT_DELAY = config.input_delay ?? 2;  // frames of input delay

        // Frame tracking
        this.frameNumber = 0;           // Current simulation frame
        this.confirmedFrame = -1;       // Last frame with confirmed inputs from ALL players

        // Input buffers: store inputs by frame number
        // inputBuffer[frame][playerId] = action
        this.inputBuffer = new Map();   // Map<frameNumber, Map<playerId, action>>
        this.inputBufferMaxSize = 120;  // Keep ~4 seconds at 30 FPS

        // Local input queue: inputs scheduled for future frames due to input delay
        this.localInputQueue = [];      // [{frame, action}] - sorted by frame

        // State snapshots for rollback (stored periodically)
        this.stateSnapshots = new Map();  // Map<frameNumber, envState>
        this.snapshotInterval = 5;        // Save snapshot every N frames
        this.maxSnapshots = 30;           // Keep ~5 seconds of snapshots

        // Prediction tracking
        this.lastConfirmedActions = {};   // {playerId: lastAction} - for prediction
        this.predictedFrames = new Set(); // Frames where we used prediction

        // Rollback stats
        this.rollbackCount = 0;
        this.maxRollbackFrames = 0;

        // Legacy compatibility (kept for now, will phase out)
        this.otherPlayerActionQueues = {};  // { player_id: [{action, frame_number}, ...] }
        this.lastExecutedActions = {};      // { player_id: last_action } for fallback

        // Action population settings
        this.actionPopulationMethod = config.action_population_method || 'previous_submitted_action';
        this.defaultAction = config.default_action || 0;

        // Policy mapping (needed to know which agents are human)
        this.policyMapping = config.policy_mapping || {};

        // Player-to-subject mapping (player_id -> subject_id)
        // Populated when game starts via pyodide_game_ready event
        this.playerSubjects = {};

        // Episode completion tracking
        this.episodeComplete = false;

        // Server-authoritative mode (always true in current implementation)
        this.serverAuthoritative = false;

        // Episode start synchronization
        // Client waits for server_episode_start before beginning each episode
        this.waitingForEpisodeStart = false;
        this.episodeStartResolve = null;
        this.pendingEpisodeState = null;

        // Diagnostics for lag tracking
        this.diagnostics = {
            lastStepTime: 0,
            stepTimes: [],          // Rolling window of step execution times
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

        // State hash history for frame-aligned comparison
        // Maps frame_number -> state_hash (computed after stepping to that frame)
        this.stateHashHistory = new Map();
        this.stateHashHistoryMaxSize = 60;  // Keep ~6 seconds at 10 FPS

        // Action tracking for sync verification
        this.actionSequence = [];  // [{frame: N, actions: {player: action}}]
        this.actionCounts = {};    // {playerId: {action: count}}

        // Sync epoch - received from server, included in actions to prevent stale action matching
        this.syncEpoch = 0;

        // Server step tracking - prevents client from getting too far ahead of server
        this.lastKnownServerStepNum = 0;
        this.maxStepsAheadOfServer = 5;

        // Confirmed state (last server-verified state)
        this.confirmedFrame = 0;

        // Partner action tracking for prediction
        this.partnerLastActions = {};  // {player_id: last_action}

        this.setupMultiplayerHandlers();
    }

    setupMultiplayerHandlers() {
        /**
         * Set up SocketIO event handlers for multiplayer coordination
         */

        // Player initialization (receive player ID and game seed)
        socket.on('pyodide_host_elected', (data) => {
            this.myPlayerId = data.player_id;
            this.gameId = data.game_id;
            this.gameSeed = data.game_seed;

            // Initialize seeded RNG for AI policies
            if (this.gameSeed) {
                seeded_random.initMultiplayerRNG(this.gameSeed);
                console.log(`[MultiplayerPyodide] Player ${this.myPlayerId} in game ${this.gameId} initialized with seed ${this.gameSeed}`);
            }
        });

        // Game ready to start
        socket.on('pyodide_game_ready', (data) => {
            console.log(`[MultiplayerPyodide] Game ${data.game_id} ready with players:`, data.players);

            // Store player-to-subject mapping for data logging
            this.playerSubjects = data.player_subjects || {};

            // Server-authoritative mode is always enabled
            this.serverAuthoritative = data.server_authoritative || false;
            console.log(`[MultiplayerPyodide] Server-authoritative mode: ${this.serverAuthoritative}`);

            // Initialize action queues for other players
            for (const playerId of data.players) {
                if (playerId != this.myPlayerId) {
                    this.otherPlayerActionQueues[playerId] = [];
                    console.log(`[MultiplayerPyodide] Initialized action queue for player ${playerId}`);
                }
            }
        });

        // Receive other player's action (GGPO: store by frame for rollback)
        socket.on('pyodide_other_player_action', (data) => {
            // Don't queue actions if game is done
            if (this.state === "done") {
                return;
            }

            const { player_id, action, frame_number } = data;

            // Store in frame-indexed input buffer for GGPO
            this.storeRemoteInput(player_id, action, frame_number);

            // Legacy: also add to queue for compatibility during transition
            if (!this.otherPlayerActionQueues[player_id]) {
                this.otherPlayerActionQueues[player_id] = [];
            }
            const queue = this.otherPlayerActionQueues[player_id];
            queue.push({ action, frame_number });

            // Log warning if queue is growing large
            if (queue.length > 30 && queue.length % 30 === 0) {
                console.warn(`[MultiplayerPyodide] Queue for player ${player_id} is large (${queue.length})`);
            }
        });

        // Server-authoritative state broadcast
        // Server periodically broadcasts authoritative state for verification/correction
        socket.on('server_authoritative_state', async (data) => {
            if (!this.serverAuthoritative) {
                return;
            }

            const { game_id, state } = data;
            if (game_id !== this.gameId) {
                return;
            }

            // Calculate sync metrics
            const frameDiff = this.frameNumber - state.frame_number;
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

            // Calculate fallback rate
            let totalFallbacks = 0;
            let totalQueueHits = 0;
            for (const count of Object.values(this.diagnostics.fallbackCount)) totalFallbacks += count;
            for (const count of Object.values(this.diagnostics.queueHitCount)) totalQueueHits += count;
            const totalActions = totalFallbacks + totalQueueHits;
            const fallbackRate = totalActions > 0 ? ((totalFallbacks / totalActions) * 100).toFixed(1) : '0.0';

            // Calculate FPS since last sync
            const now = Date.now();
            const targetFPS = this.config.fps || 10;
            const framesSinceLastSync = this.frameNumber - this.diagnostics.lastSyncFrame;
            const timeSinceLastSync = now - this.diagnostics.lastSyncTime;
            const effectiveFPS = framesSinceLastSync > 0 && this.diagnostics.lastSyncTime > 0 && timeSinceLastSync > 0
                ? ((framesSinceLastSync / timeSinceLastSync) * 1000).toFixed(1)
                : 'N/A';

            const hasEnvState = state.env_state !== undefined && state.env_state !== null;
            const serverTimestamp = state.server_timestamp || 0;
            const networkLatency = serverTimestamp > 0 ? now - serverTimestamp : 'N/A';

            // Log sync info
            console.log(
                `[Sync #${this.diagnostics.syncCount}] ` +
                `Server: ${state.frame_number} | Client: ${this.frameNumber} | Drift: ${frameDiff > 0 ? '+' : ''}${frameDiff} | ` +
                `FPS: ${effectiveFPS}/${targetFPS} | ` +
                `Step: ${avgStepTime}ms avg, ${maxStepTime}ms max | ` +
                `Queues: ${totalQueueSize} | ` +
                `Fallback: ${fallbackRate}% | ` +
                `Latency: ${typeof networkLatency === 'number' ? networkLatency.toFixed(0) + 'ms' : networkLatency}`
            );

            // Reconcile with server state
            if (hasEnvState) {
                await this.reconcileWithServer(state);
            } else {
                // No env_state - just sync rewards
                if (state.cumulative_rewards) {
                    this.cumulative_rewards = state.cumulative_rewards;
                    ui_utils.updateHUDText(this.getHUDText());
                }
            }

            // Update tracking
            if (state.step_num !== undefined) {
                this.lastKnownServerStepNum = state.step_num;
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

        // Server game complete (server-authoritative mode)
        // Server broadcasts this when all configured episodes have been completed
        socket.on('server_game_complete', (data) => {
            if (!this.serverAuthoritative) {
                return;
            }

            const { game_id, episode_num, max_episodes } = data;
            if (game_id !== this.gameId) {
                return;
            }

            console.log(
                `[MultiplayerPyodide] Server game complete: ` +
                `${episode_num}/${max_episodes} episodes`
            );

            // Mark game as complete - this stops the game loop
            this.state = "done";
            this.episodeComplete = true;
            this.num_episodes = episode_num;

            // Sync final rewards if provided
            if (data.cumulative_rewards) {
                this.cumulative_rewards = data.cumulative_rewards;
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
         * Validate that the environment implements required state sync methods.
         *
         * For multiplayer synchronization, environments MUST implement:
         * - get_state(): Returns a JSON-serializable dict with primitive types
         * - set_state(state): Restores environment from a state dict
         *
         * This enables deterministic hash comparison between server (CPython)
         * and client (Pyodide) for detecting state divergence.
         */

        const result = await this.pyodide.runPythonAsync(`
# Check if environment has required methods for state synchronization
has_get_state = hasattr(env, 'get_state') and callable(getattr(env, 'get_state'))
has_set_state = hasattr(env, 'set_state') and callable(getattr(env, 'set_state'))

env_type = type(env).__name__
env_module = type(env).__module__

if not has_get_state or not has_set_state:
    missing = []
    if not has_get_state:
        missing.append("get_state()")
    if not has_set_state:
        missing.append("set_state()")
    print(f"[Python] ⚠️ Environment {env_type} is missing required methods: {', '.join(missing)}")
    print(f"[Python] ⚠️ State synchronization will NOT work without these methods.")
    print(f"[Python] ⚠️ Please implement get_state() and set_state() that return/accept JSON-serializable dicts.")
else:
    print(f"[Python] ✓ Environment {env_type} has get_state() and set_state() methods")

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

        // Clear GGPO state for new episode
        this.clearGGPOState();

        // Clear action tracking for sync verification
        this.actionSequence = [];
        this.actionCounts = {};

        // Reset per-episode diagnostics
        this.diagnostics.syncCount = 0;
        this.diagnostics.frameDriftHistory = [];
        this.diagnostics.fallbackCount = {};
        this.diagnostics.queueHitCount = {};
        this.diagnostics.stepTimes = [];

        // Clear state hash history for fresh episode
        this.stateHashHistory.clear();

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

            if (serverState && serverState.env_state) {
                console.log(`[MultiplayerPyodide] Applying server episode state (episode ${serverState.episode_num})`);

                // Do a local reset FIRST to initialize internal structures (like env_agents),
                // THEN apply set_state() to sync with server's state.
                // This ensures env.get_obs() works correctly (relies on env_agents being populated).
                // NOTE: We do NOT call applyServerState() here because it would try to call
                // set_state() on an uninitialized env, causing errors in environments like cogrid
                // where get_obs() relies on env_agents being set up during reset().

                // Convert env_state to JSON string for safe passing to Python
                const envStateJson = JSON.stringify(serverState.env_state);

                const result = await this.pyodide.runPythonAsync(`
import numpy as np
import json

# First reset to initialize internal structures (env_agents, etc.)
obs, infos = env.reset(seed=${this.gameSeed || 'None'})

# Now apply server state to overwrite with authoritative values
env_state = json.loads('''${envStateJson.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}''')
env.set_state(env_state)

# Re-get observations after state is applied (internal structures now initialized)
if hasattr(env, 'get_obs'):
    obs = env.get_obs()
elif hasattr(env, '_get_obs'):
    obs = env._get_obs()

# Render with the correct state
render_state = env.render()

if not isinstance(obs, dict):
    obs = obs.reshape(-1).astype(np.float32)
elif isinstance(obs, dict) and isinstance([*obs.values()][0], dict):
    obs = {k: {kk: vv.reshape(-1).astype(np.float32) for kk, vv in v.items()} for k, v in obs.items()}
elif isinstance(obs, dict):
    obs = {k: v.reshape(-1).astype(np.float32) for k, v in obs.items()}

if not isinstance(obs, dict):
    obs = {"human": obs}

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
                this.lastKnownServerStepNum = serverState.step_num || 0;  // Track server step count
                this.shouldReset = false;
                this.episodeComplete = false;

                // Use server's cumulative rewards
                if (serverState.cumulative_rewards) {
                    this.cumulative_rewards = serverState.cumulative_rewards;
                }

                // Sync epoch is critical for preventing stale action matching
                if (serverState.sync_epoch !== undefined) {
                    this.syncEpoch = serverState.sync_epoch;
                }

                // Show and update HUD
                ui_utils.showHUD();
                ui_utils.updateHUDText(this.getHUDText());

                // Show countdown for subsequent episodes before starting
                // Use inherited method (which checks isSubsequentEpisode internally)
                await this.showEpisodeTransition();

                // Clear action queues AFTER countdown to discard any actions received during transition
                // This prevents stale actions from the previous episode or countdown from executing
                this.clearActionQueues();

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

        // Clear action queues AFTER countdown to discard any actions received during transition
        this.clearActionQueues();

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

    /**
     * Clear all action queues and last executed actions.
     * Called after episode transitions to prevent stale actions from executing.
     */
    clearActionQueues() {
        for (const playerId in this.otherPlayerActionQueues) {
            this.otherPlayerActionQueues[playerId] = [];
        }
        this.lastExecutedActions = {};
        console.log('[MultiplayerPyodide] Cleared action queues after episode transition');
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

        // GGPO Input Synchronization:
        // With input delay, actions for frame N should arrive before we need to step frame N.
        // We briefly wait for inputs, then proceed with predictions if needed.
        // The key is: INPUT_DELAY gives actions time to propagate before we need them.

        // Get all human player IDs
        const humanPlayerIds = Object.entries(this.policyMapping)
            .filter(([_, policy]) => policy === 'human')
            .map(([id, _]) => String(id));

        if (this.serverAuthoritative) {
            // Check if we have confirmed inputs for this frame from all players
            const haveAllInputs = this.hasConfirmedInputsForFrame(this.frameNumber, humanPlayerIds);

            // If we don't have all inputs, wait briefly (input delay should have provided buffer)
            if (!haveAllInputs) {
                const maxWaitMs = 30;  // Brief wait - input delay should handle most cases
                const pollIntervalMs = 5;
                let waited = 0;

                while (waited < maxWaitMs) {
                    await new Promise(resolve => setTimeout(resolve, pollIntervalMs));
                    waited += pollIntervalMs;

                    if (this.hasConfirmedInputsForFrame(this.frameNumber, humanPlayerIds)) {
                        break;
                    }
                }
            }

            // Log if we're about to use prediction
            if (!this.hasConfirmedInputsForFrame(this.frameNumber, humanPlayerIds)) {
                // Only log occasionally to avoid spam
                if (this.frameNumber % 30 === 0) {
                    const missingPlayers = humanPlayerIds.filter(pid => {
                        const frameInputs = this.inputBuffer.get(this.frameNumber);
                        return !frameInputs || !frameInputs.has(pid);
                    });
                    console.log(
                        `[GGPO] Frame ${this.frameNumber}: Missing inputs from ${missingPlayers.join(', ')}, using prediction`
                    );
                }
            }

            // Legacy throttle: if queue is building up, slow down
            const totalQueueSize = Object.values(this.otherPlayerActionQueues)
                .reduce((sum, queue) => sum + queue.length, 0);
            if (totalQueueSize > 10) {
                const throttleDelayMs = Math.min((totalQueueSize - 10) * 3, 30);
                await new Promise(resolve => setTimeout(resolve, throttleDelayMs));
            }
        }

        // 1. Build final action dict using GGPO input buffer
        // Use frame-indexed inputs for human players (confirmed or predicted)
        const finalActions = {};

        // Get inputs for all human players from GGPO buffer
        const ggpoInputs = this.getInputsForFrame(this.frameNumber, humanPlayerIds);

        for (const [agentId, policy] of Object.entries(this.policyMapping)) {
            const agentIdStr = String(agentId);
            const myPlayerIdStr = String(this.myPlayerId);

            if (agentIdStr === myPlayerIdStr) {
                // My action - from current input (not from buffer, we execute immediately)
                finalActions[agentId] = allActionsDict[agentId];
                if (finalActions[agentId] === undefined || finalActions[agentId] === null) {
                    finalActions[agentId] = this.defaultAction;
                }
            } else if (policy === 'human') {
                // Other human player - use GGPO buffer (confirmed or predicted)
                finalActions[agentId] = ggpoInputs[agentIdStr] ?? this.defaultAction;
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

        // Store in input buffer for potential rollback/replay (real-time mode)
        // Track action sequence and counts for sync verification
        this.actionSequence.push({
            frame: this.frameNumber,
            actions: {...finalActions}  // Clone to avoid mutation
        });

        // Update action counts
        for (const [playerId, action] of Object.entries(finalActions)) {
            if (!this.actionCounts[playerId]) {
                this.actionCounts[playerId] = {};
            }
            const actionKey = String(action);
            this.actionCounts[playerId][actionKey] = (this.actionCounts[playerId][actionKey] || 0) + 1;
        }

        // 2. Send MY action to server (for other clients to queue)
        // With GGPO: include the target frame (current + INPUT_DELAY) so other clients
        // know exactly when this action should execute
        const inEpisodeTransition = this.episodeComplete || this.waitingForEpisodeStart || this.shouldReset;
        if (!inEpisodeTransition) {
            const myAction = finalActions[this.myPlayerId];
            const targetFrame = this.frameNumber + this.INPUT_DELAY;

            // Store in our own input buffer for the delayed frame
            this.storeLocalInput(myAction, this.frameNumber);

            socket.emit('pyodide_player_action', {
                game_id: this.gameId,
                player_id: this.myPlayerId,
                action: myAction,
                frame_number: targetFrame,  // GGPO: target frame with delay applied
                timestamp: Date.now(),
                sync_epoch: this.syncEpoch
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

        // Record state hash for this frame SYNCHRONOUSLY (must complete before next step)
        // IMPORTANT: Record BEFORE incrementing frameNumber to match server's frame numbering.
        // Server sets frame_number = N after stepping with frame N actions.
        // Client should also associate the post-step state with frame N (not N+1).
        if (this.serverAuthoritative) {
            await this.recordStateHashForFrame(this.frameNumber);

            // GGPO: Save state snapshot periodically for rollback
            if (this.frameNumber % this.snapshotInterval === 0) {
                await this.saveStateSnapshot(this.frameNumber);
            }
        }

        // 4. Increment frame (AFTER recording hash)
        this.frameNumber++;

        // GGPO: Check for pending rollback (late input arrived)
        if (this.pendingRollbackFrame !== null && this.pendingRollbackFrame !== undefined) {
            const rollbackFrame = this.pendingRollbackFrame;
            this.pendingRollbackFrame = null;

            // Get all player IDs
            const playerIds = Object.keys(this.policyMapping).filter(
                pid => this.policyMapping[pid] === 'human'
            );

            // Perform rollback and replay
            await this.performRollback(rollbackFrame, playerIds);
        }

        // Log diagnostics periodically
        this.logDiagnostics();

        // 5. Check if episode is complete (only trigger once)
        // Episode ends when: environment terminates/truncates OR max_steps reached
        const all_terminated = Array.from(terminateds.values()).every(value => value === true);
        const all_truncated = Array.from(truncateds.values()).every(value => value === true);
        const max_steps_reached = this.step_num >= this.max_steps;

        if ((all_terminated || all_truncated || max_steps_reached) && !this.episodeComplete) {
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
            // Update partner last action for prediction
            this.partnerLastActions[playerIdStr] = action;
            return action;
        } else {
            // Queue empty - use fallback based on action_population_method
            // Track fallback usage
            this.diagnostics.fallbackCount[playerIdStr] = (this.diagnostics.fallbackCount[playerIdStr] || 0) + 1;

            if (this.actionPopulationMethod === 'previous_submitted_action') {
                // Use partner's last known action if available
                const lastAction = this.partnerLastActions[playerIdStr]
                    ?? this.lastExecutedActions[playerIdStr];
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

    /**
     * Record state hash for a given frame number.
     * Called after each step to build history for frame-aligned comparison.
     * Runs asynchronously to avoid blocking the game loop.
     */
    async recordStateHashForFrame(frameNumber) {
        try {
            const hash = await this.computeQuickStateHash();
            this.stateHashHistory.set(frameNumber, hash);

            // Prune old entries to prevent unbounded growth
            if (this.stateHashHistory.size > this.stateHashHistoryMaxSize) {
                // Delete oldest entries (Map maintains insertion order)
                const keysToDelete = [];
                for (const key of this.stateHashHistory.keys()) {
                    if (this.stateHashHistory.size - keysToDelete.length <= this.stateHashHistoryMaxSize) {
                        break;
                    }
                    keysToDelete.push(key);
                }
                for (const key of keysToDelete) {
                    this.stateHashHistory.delete(key);
                }
            }
        } catch (e) {
            // Don't let hash computation errors break the game
            console.warn(`[StateHash] Failed to record hash for frame ${frameNumber}: ${e}`);
        }
    }

    /**
     * Get the state hash that was recorded for a specific frame.
     * Returns null if hash for that frame is not in history (too old or not yet recorded).
     */
    getStateHashForFrame(frameNumber) {
        return this.stateHashHistory.get(frameNumber) || null;
    }

    async computeQuickStateHash() {
        /**
         * Compute MD5 hash of env_state only (matches server's state_hash).
         * This is used for quick comparison to avoid unnecessary state corrections.
         * Returns first 16 chars of MD5 hash to match server format.
         *
         * Requires the environment to implement get_state() returning a
         * JSON-serializable dict.
         */
        const hashResult = await this.pyodide.runPythonAsync(`
import json
import hashlib

if not hasattr(env, 'get_state') or not callable(getattr(env, 'get_state')):
    raise RuntimeError(
        "Environment does not implement get_state(). "
        "State synchronization requires get_state() and set_state() methods "
        "that return/accept JSON-serializable dicts with primitive types only."
    )

_env_state_for_hash = env.get_state()

# Compute MD5 hash matching server's format (sort_keys=True for consistency)
_json_str = json.dumps(_env_state_for_hash, sort_keys=True)
_hash = hashlib.md5(_json_str.encode()).hexdigest()[:16]
_hash
        `);
        return hashResult;
    }

    async applyServerState(state) {
        /**
         * Apply authoritative state from server (server-authoritative mode).
         *
         * Similar to applyFullState but uses server's state format.
         * Called when client detects significant frame drift from server.
         *
         * Requires the environment to implement set_state() that accepts a
         * JSON-serializable dict.
         */
        const applyTiming = {
            start: performance.now(),
            pythonStart: 0,
            pythonEnd: 0,
            renderStart: 0,
            renderEnd: 0,
        };

        // If server provides env_state, apply it
        if (state.env_state) {
            applyTiming.pythonStart = performance.now();
            await this.pyodide.runPythonAsync(`
import numpy as np
import time

_apply_start = time.time()

env_state = ${this.pyodide.toPy(state.env_state)}

_convert_time = (time.time() - _apply_start) * 1000

if not hasattr(env, 'set_state') or not callable(getattr(env, 'set_state')):
    raise RuntimeError(
        "Environment does not implement set_state(). "
        "State synchronization requires get_state() and set_state() methods "
        "that return/accept JSON-serializable dicts with primitive types only."
    )

_deser_start = time.time()
env.set_state(env_state)
_deser_time = (time.time() - _deser_start) * 1000

_total_time = (time.time() - _apply_start) * 1000
print(f"[Python] State applied via set_state: convert={_convert_time:.1f}ms, deserialize={_deser_time:.1f}ms, total={_total_time:.1f}ms")
            `);
            applyTiming.pythonEnd = performance.now();
        }

        // Sync JavaScript-side state
        const oldFrame = this.frameNumber;
        if (state.episode_num !== undefined) {
            this.num_episodes = state.episode_num;
        }
        if (state.step_num !== undefined) {
            this.step_num = state.step_num;
            // Track server step count to prevent client from getting too far ahead
            this.lastKnownServerStepNum = state.step_num;
        }
        if (state.frame_number !== undefined) {
            this.frameNumber = state.frame_number;
        }
        if (state.cumulative_rewards) {
            this.cumulative_rewards = state.cumulative_rewards;
        }
        // Update sync epoch - critical for preventing stale action matching
        if (state.sync_epoch !== undefined) {
            this.syncEpoch = state.sync_epoch;
        }

        // Trigger a re-render to show the corrected state
        applyTiming.renderStart = performance.now();
        try {
            await this.pyodide.runPythonAsync(`env.render()`);
            // The render state will be picked up on the next frame
            applyTiming.renderEnd = performance.now();
        } catch (e) {
            applyTiming.renderEnd = performance.now();
            console.warn(`[applyServerState] Render failed: ${e}`);
        }

        const totalTime = performance.now() - applyTiming.start;
        const pythonTime = applyTiming.pythonEnd - applyTiming.pythonStart;
        const renderTime = applyTiming.renderEnd - applyTiming.renderStart;

        console.log(
            `[applyServerState] Timing: total=${totalTime.toFixed(1)}ms, ` +
            `python=${pythonTime.toFixed(1)}ms, render=${renderTime.toFixed(1)}ms, ` +
            `frame: ${oldFrame} → ${this.frameNumber}`
        );

        // Handle action queues after state correction.
        // If we went BACKWARDS in frame number, the actions in our queue are for
        // "future" frames that we'll re-execute. But the other player will ALSO
        // re-send actions for those frames after they receive this same sync.
        // This causes duplicate actions in the queue → unbounded growth.
        //
        // Solution: When going backwards, clear the queue. The other player will
        // re-send actions after they also receive the sync and reset.
        //
        // When going forwards or staying same, keep the queue - those actions
        // are still valid and needed.
        if (this.frameNumber < oldFrame) {
            console.log(
                `[applyServerState] Frame went backwards (${oldFrame} → ${this.frameNumber}), ` +
                `clearing action queues to prevent duplicates`
            );
            for (const playerId in this.otherPlayerActionQueues) {
                const oldQueueSize = this.otherPlayerActionQueues[playerId].length;
                this.otherPlayerActionQueues[playerId] = [];
                if (oldQueueSize > 0) {
                    console.log(`  Cleared ${oldQueueSize} actions from player ${playerId}'s queue`);
                }
            }
        }

        // Update HUD
        ui_utils.updateHUDText(this.getHUDText());

        console.log(`[MultiplayerPyodide] Server state applied, now at frame ${this.frameNumber}`);
    }

    async reconcileWithServer(serverState) {
        /**
         * Reconcile client state with server's authoritative state.
         *
         * Server is always authoritative. We apply server state when:
         * 1. Hashes mismatch (real divergence detected)
         * 2. Large frame drift (client got too far ahead/behind)
         *
         * We skip correction only when:
         * - Hashes match (confirmed in sync)
         * - No client hash available AND small drift (can't verify, trust timing)
         *
         * Returns true if state correction was applied, false if skipped.
         */
        const serverFrame = serverState.frame_number;
        const serverHash = serverState.state_hash;
        const clientHash = this.getStateHashForFrame(serverFrame);
        const drift = this.frameNumber - serverFrame;  // Positive = client ahead, negative = client behind

        // Helper to sync metadata from server without applying full state
        const syncMetadata = () => {
            if (serverState.step_num !== undefined) {
                this.lastKnownServerStepNum = serverState.step_num;
            }
            if (serverState.cumulative_rewards) {
                this.cumulative_rewards = serverState.cumulative_rewards;
                ui_utils.updateHUDText(this.getHUDText());
            }
        };

        // CASE 1: Both hashes available and they MATCH - confirmed in sync
        if (clientHash && serverHash && clientHash === serverHash) {
            this.confirmedFrame = serverFrame;
            syncMetadata();
            console.log(
                `[Reconcile] States match at frame ${serverFrame} ` +
                `(hash=${serverHash.substring(0, 8)}), drift: ${drift}`
            );
            return false;
        }

        // CASE 2: Both hashes available but MISMATCH - proven divergence, must correct
        if (clientHash && serverHash && clientHash !== serverHash) {
            const framesToRollback = this.frameNumber - serverFrame;
            console.log(
                `[Reconcile] HASH MISMATCH at frame ${serverFrame}. ` +
                `Server: ${serverHash.substring(0, 8)}, Client: ${clientHash.substring(0, 8)}. ` +
                `Rolling back ${framesToRollback} frames. (Rollbacks so far: ${this.rollbackCount})`
            );

            // Apply server state and clear GGPO predictions from that point forward
            await this.applyServerState(serverState);
            this.confirmedFrame = serverFrame;
            this.stateHashHistory.clear();

            // Clear predictions for frames we've now corrected
            for (const frame of this.predictedFrames) {
                if (frame >= serverFrame) {
                    this.predictedFrames.delete(frame);
                }
            }

            // Save a fresh snapshot at this corrected frame
            await this.saveStateSnapshot(serverFrame);

            this.rollbackCount++;
            return true;
        }

        // CASE 3: No client hash available - can't verify sync
        // This happens when:
        // - Client is behind server (drift < 0): hasn't reached that frame yet
        // - Client is ahead but hash was pruned: frame too old
        // - Hash history was recently cleared
        //
        // For small drift, trust that we're in sync and just update metadata.
        // For large drift, apply server state to catch up / correct.
        const DRIFT_TOLERANCE = 5;  // Allow up to 5 frames of drift without correction

        if (Math.abs(drift) <= DRIFT_TOLERANCE) {
            // Small drift - likely just timing difference, trust local state
            syncMetadata();
            console.log(
                `[Reconcile] No hash for frame ${serverFrame}, drift=${drift} within tolerance. ` +
                `Syncing metadata only.`
            );
            return false;
        }

        // Large drift - apply server state to get back in sync
        console.log(
            `[Reconcile] No hash for frame ${serverFrame}, drift=${drift} exceeds tolerance. ` +
            `Applying server state.`
        );
        await this.applyServerState(serverState);
        this.confirmedFrame = serverFrame;
        // Don't clear hash history - we couldn't verify divergence
        return true;
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

    // ========== GGPO Rollback Netcode Methods ==========

    /**
     * Store a remote player's input for a specific frame.
     * If we've already simulated past this frame with a prediction, trigger rollback.
     */
    storeRemoteInput(playerId, action, frameNumber) {
        const playerIdStr = String(playerId);

        // Ensure input buffer exists for this frame
        if (!this.inputBuffer.has(frameNumber)) {
            this.inputBuffer.set(frameNumber, new Map());
        }

        const frameInputs = this.inputBuffer.get(frameNumber);

        // Check if we already have an input for this player at this frame
        if (frameInputs.has(playerIdStr)) {
            // Already have confirmed input, ignore duplicate
            return;
        }

        // Store the confirmed input
        frameInputs.set(playerIdStr, action);

        // Update last confirmed action for this player (used for prediction)
        this.lastConfirmedActions[playerIdStr] = action;

        // Check if this input arrived late (we already simulated past this frame)
        // and we used a prediction that might be wrong
        if (frameNumber <= this.frameNumber && this.predictedFrames.has(frameNumber)) {
            // Late input! We need to check if our prediction was wrong
            const predictedAction = this.getPredictedAction(playerIdStr, frameNumber);
            if (predictedAction !== action) {
                console.log(
                    `[GGPO] Late input from player ${playerIdStr} at frame ${frameNumber} ` +
                    `(current: ${this.frameNumber}). Predicted: ${predictedAction}, Actual: ${action}. ` +
                    `Triggering rollback.`
                );
                // Mark for rollback - will be processed in next step()
                this.pendingRollbackFrame = Math.min(
                    this.pendingRollbackFrame ?? frameNumber,
                    frameNumber
                );
            }
        }

        // Prune old input buffer entries
        this.pruneInputBuffer();
    }

    /**
     * Store local player's input with input delay applied.
     * Input pressed at frame N is scheduled for frame N + INPUT_DELAY.
     */
    storeLocalInput(action, currentFrame) {
        const targetFrame = currentFrame + this.INPUT_DELAY;
        const myPlayerIdStr = String(this.myPlayerId);

        // Ensure input buffer exists for target frame
        if (!this.inputBuffer.has(targetFrame)) {
            this.inputBuffer.set(targetFrame, new Map());
        }

        const frameInputs = this.inputBuffer.get(targetFrame);
        frameInputs.set(myPlayerIdStr, action);

        // Also update last confirmed action for self
        this.lastConfirmedActions[myPlayerIdStr] = action;

        // Return the target frame so caller knows when this input will execute
        return targetFrame;
    }

    /**
     * Get predicted action for a player.
     * Uses their last confirmed action, or default if none.
     */
    getPredictedAction(playerId, frameNumber) {
        const playerIdStr = String(playerId);
        return this.lastConfirmedActions[playerIdStr] ?? this.defaultAction;
    }

    /**
     * Get inputs for a specific frame.
     * Returns {playerId: action} dict with confirmed inputs where available,
     * predictions where not.
     */
    getInputsForFrame(frameNumber, playerIds) {
        const inputs = {};
        const frameInputs = this.inputBuffer.get(frameNumber);
        let usedPrediction = false;

        for (const playerId of playerIds) {
            const playerIdStr = String(playerId);

            if (frameInputs && frameInputs.has(playerIdStr)) {
                // Have confirmed input
                inputs[playerIdStr] = frameInputs.get(playerIdStr);
            } else {
                // Need to predict
                inputs[playerIdStr] = this.getPredictedAction(playerIdStr, frameNumber);
                usedPrediction = true;
            }
        }

        // Track that we used prediction for this frame
        if (usedPrediction) {
            this.predictedFrames.add(frameNumber);
        }

        return inputs;
    }

    /**
     * Check if we have confirmed inputs from all players for a frame.
     */
    hasConfirmedInputsForFrame(frameNumber, playerIds) {
        const frameInputs = this.inputBuffer.get(frameNumber);
        if (!frameInputs) return false;

        for (const playerId of playerIds) {
            if (!frameInputs.has(String(playerId))) {
                return false;
            }
        }
        return true;
    }

    /**
     * Save a state snapshot for potential rollback.
     */
    async saveStateSnapshot(frameNumber) {
        try {
            const stateJson = await this.pyodide.runPythonAsync(`
import json
_state = env.get_state()
json.dumps(_state)
            `);
            this.stateSnapshots.set(frameNumber, stateJson);

            // Prune old snapshots
            if (this.stateSnapshots.size > this.maxSnapshots) {
                const keysToDelete = [];
                for (const key of this.stateSnapshots.keys()) {
                    if (this.stateSnapshots.size - keysToDelete.length <= this.maxSnapshots) {
                        break;
                    }
                    keysToDelete.push(key);
                }
                for (const key of keysToDelete) {
                    this.stateSnapshots.delete(key);
                }
            }
        } catch (e) {
            console.warn(`[GGPO] Failed to save snapshot at frame ${frameNumber}: ${e}`);
        }
    }

    /**
     * Find the best snapshot to rollback to (closest to but not after targetFrame).
     */
    findBestSnapshot(targetFrame) {
        let bestFrame = -1;
        for (const frame of this.stateSnapshots.keys()) {
            if (frame <= targetFrame && frame > bestFrame) {
                bestFrame = frame;
            }
        }
        return bestFrame;
    }

    /**
     * Load a state snapshot and reset to that frame.
     */
    async loadStateSnapshot(frameNumber) {
        const stateJson = this.stateSnapshots.get(frameNumber);
        if (!stateJson) {
            console.error(`[GGPO] No snapshot found for frame ${frameNumber}`);
            return false;
        }

        try {
            await this.pyodide.runPythonAsync(`
import json
_state = json.loads('''${stateJson.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}''')
env.set_state(_state)
            `);
            return true;
        } catch (e) {
            console.error(`[GGPO] Failed to load snapshot for frame ${frameNumber}: ${e}`);
            return false;
        }
    }

    /**
     * Perform rollback to a target frame and replay forward.
     * This is the core GGPO operation.
     */
    async performRollback(targetFrame, playerIds) {
        const currentFrame = this.frameNumber;
        const rollbackFrames = currentFrame - targetFrame;

        console.log(
            `[GGPO] Rolling back ${rollbackFrames} frames ` +
            `(${currentFrame} → ${targetFrame})`
        );

        this.rollbackCount++;
        this.maxRollbackFrames = Math.max(this.maxRollbackFrames, rollbackFrames);

        // Find best snapshot to restore
        const snapshotFrame = this.findBestSnapshot(targetFrame);
        if (snapshotFrame < 0) {
            console.error(`[GGPO] No valid snapshot found for rollback to frame ${targetFrame}`);
            return false;
        }

        // Load snapshot
        const loaded = await this.loadStateSnapshot(snapshotFrame);
        if (!loaded) {
            return false;
        }

        console.log(`[GGPO] Loaded snapshot from frame ${snapshotFrame}, replaying to ${currentFrame}`);

        // Replay from snapshot frame to current frame
        this.frameNumber = snapshotFrame;

        // Clear predicted frames from snapshot onwards (we'll re-simulate)
        for (const frame of this.predictedFrames) {
            if (frame >= snapshotFrame) {
                this.predictedFrames.delete(frame);
            }
        }

        // Replay each frame
        for (let frame = snapshotFrame; frame < currentFrame; frame++) {
            const inputs = this.getInputsForFrame(frame, playerIds);

            // Step environment with these inputs
            const envActions = {};
            for (const [pid, action] of Object.entries(inputs)) {
                envActions[parseInt(pid) || pid] = action;
            }

            await this.pyodide.runPythonAsync(`
_replay_actions = ${JSON.stringify(envActions)}
_replay_actions = {int(k) if str(k).isdigit() else k: v for k, v in _replay_actions.items()}
env.step(_replay_actions)
            `);

            this.frameNumber = frame + 1;
        }

        console.log(`[GGPO] Replay complete, now at frame ${this.frameNumber}`);
        return true;
    }

    /**
     * Prune old entries from input buffer.
     */
    pruneInputBuffer() {
        if (this.inputBuffer.size > this.inputBufferMaxSize) {
            const keysToDelete = [];
            for (const key of this.inputBuffer.keys()) {
                if (this.inputBuffer.size - keysToDelete.length <= this.inputBufferMaxSize) {
                    break;
                }
                keysToDelete.push(key);
            }
            for (const key of keysToDelete) {
                this.inputBuffer.delete(key);
                this.predictedFrames.delete(key);
            }
        }
    }

    /**
     * Clear GGPO state for episode reset.
     */
    clearGGPOState() {
        this.inputBuffer.clear();
        this.localInputQueue = [];
        this.stateSnapshots.clear();
        this.lastConfirmedActions = {};
        this.predictedFrames.clear();
        this.confirmedFrame = -1;
        this.pendingRollbackFrame = null;
        this.rollbackCount = 0;
        this.maxRollbackFrames = 0;
        console.log('[GGPO] State cleared for new episode');
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
