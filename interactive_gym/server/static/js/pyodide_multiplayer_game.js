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

        // State hash history for frame-aligned comparison
        // Maps frame_number -> state_hash (computed after stepping to that frame)
        this.stateHashHistory = new Map();
        this.stateHashHistoryMaxSize = 60;  // Keep ~6 seconds at 10 FPS

        // Action tracking for sync verification
        this.actionSequence = [];  // [{frame: N, actions: {player: action}}]
        this.actionCounts = {};    // {playerId: {action: count}}

        // Sync epoch - received from server, included in actions to prevent stale action matching.
        // Actions with old epoch are rejected by server after a state broadcast.
        this.syncEpoch = 0;

        // Server step tracking - prevents client from getting too far ahead of server.
        // The server only steps when it receives actions from ALL players, so a fast client
        // can accumulate extra local steps. We track the last known server step count and
        // pause if we get too far ahead.
        this.lastKnownServerStepNum = 0;
        this.maxStepsAheadOfServer = 5;  // Don't get more than 5 steps ahead of server

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

            // Check if env_state is present (needed for actual state sync)
            const hasEnvState = state.env_state !== undefined && state.env_state !== null;

            // Calculate staleness - how old is this state compared to when we received it?
            const receiveTime = Date.now();
            const serverTimestamp = state.server_timestamp || 0;
            const networkLatency = serverTimestamp > 0 ? receiveTime - serverTimestamp : 'N/A';

            // Log comprehensive sync info (matches [Perf] format)
            console.log(
                `[Sync #${this.diagnostics.syncCount}] ` +
                `Server: ${state.frame_number} | Client: ${this.frameNumber} | Drift: ${frameDiff > 0 ? '+' : ''}${frameDiff} | ` +
                `FPS: ${effectiveFPS}/${targetFPS} | ` +
                `Step: ${avgStepTime}ms avg, ${maxStepTime}ms max | ` +
                `Queues: ${totalQueueSize} ${JSON.stringify(queueSizes)} | ` +
                `Fallback: ${fallbackRate}% ${JSON.stringify(fallbackRates)} | ` +
                `EnvState: ${hasEnvState ? 'yes' : 'NO'} | ` +
                `Latency: ${typeof networkLatency === 'number' ? networkLatency.toFixed(0) + 'ms' : networkLatency}`
            );

            if (hasEnvState) {
                // DETERMINISTIC STATE (custom get_state): Use hash comparison
                const serverHash = state.state_hash || null;
                const serverFrame = state.frame_number;
                let clientHash = null;
                let needsCorrection = true;  // Default to correcting if we can't compare
                let comparisonResult = 'no_comparison';

                // Look up client's hash at the SAME frame as server
                if (serverHash && serverFrame !== undefined) {
                    clientHash = this.getStateHashForFrame(serverFrame);

                    if (clientHash !== null) {
                        // We have a hash for this frame - compare them
                        needsCorrection = (clientHash !== serverHash);
                        comparisonResult = needsCorrection ? 'mismatch' : 'match';

                        if (!needsCorrection) {
                            console.log(
                                `[Sync] States match at frame ${serverFrame} (hash=${serverHash.substring(0, 8)}), skipping correction. ` +
                                `Current frame: ${this.frameNumber}, drift: ${frameDiff}`
                            );
                            // States are in sync - just update rewards display (don't reset frame number)
                            if (state.cumulative_rewards) {
                                this.cumulative_rewards = state.cumulative_rewards;
                                ui_utils.updateHUDText(this.getHUDText());
                            }
                            // Update server step tracking (critical for throttling)
                            if (state.step_num !== undefined) {
                                this.lastKnownServerStepNum = state.step_num;
                            }
                        }
                    } else {
                        // Frame too old (not in history) or hash not yet recorded
                        comparisonResult = 'no_history';

                        // Check if history is empty (e.g., at start of episode)
                        if (this.stateHashHistory.size === 0) {
                            console.log(
                                `[Sync] Hash history empty (likely start of episode). ` +
                                `Skipping correction, will compare on next sync.`
                            );
                            // Don't correct - just let the game continue and compare next time
                            needsCorrection = false;
                            // Update rewards display
                            if (state.cumulative_rewards) {
                                this.cumulative_rewards = state.cumulative_rewards;
                                ui_utils.updateHUDText(this.getHUDText());
                            }
                            // Update server step tracking (critical for throttling)
                            if (state.step_num !== undefined) {
                                this.lastKnownServerStepNum = state.step_num;
                            }
                        } else {
                            const historyKeys = Array.from(this.stateHashHistory.keys());
                            const oldestFrame = Math.min(...historyKeys);
                            const newestFrame = Math.max(...historyKeys);

                            if (serverFrame > newestFrame) {
                                // Server is ahead of our history - hash not recorded yet (unlikely but possible)
                                console.log(
                                    `[Sync] Server frame ${serverFrame} ahead of history (newest: ${newestFrame}). ` +
                                    `Hash not recorded yet, skipping correction.`
                                );
                                needsCorrection = false;
                                if (state.cumulative_rewards) {
                                    this.cumulative_rewards = state.cumulative_rewards;
                                    ui_utils.updateHUDText(this.getHUDText());
                                }
                                // Update server step tracking (critical for throttling)
                                if (state.step_num !== undefined) {
                                    this.lastKnownServerStepNum = state.step_num;
                                }
                            } else if (serverFrame < oldestFrame) {
                                // Server frame is older than our history - we're too far ahead
                                console.warn(
                                    `[Sync] Server frame ${serverFrame} older than history (oldest: ${oldestFrame}). ` +
                                    `Client too far ahead, applying correction.`
                                );
                                needsCorrection = true;
                            } else {
                                // Frame is in range but missing - shouldn't happen
                                console.warn(
                                    `[Sync] Hash missing for frame ${serverFrame} (range: ${oldestFrame}-${newestFrame}). ` +
                                    `Forcing correction.`
                                );
                                needsCorrection = true;
                            }
                        }
                    }
                }

                if (needsCorrection) {
                    // ===== ACTION VERIFICATION =====
                    // Compare action tracking to diagnose root cause of divergence
                    const serverActionCounts = state.action_counts || {};
                    const serverSeqHash = state.action_sequence_hash || '';
                    const clientSeqHash = this.computeActionSequenceHash();
                    const serverTotalActions = state.total_actions || 0;
                    const clientTotalActions = this.actionSequence.length;

                    // Check sequence hash (order matters)
                    const sequenceMatches = (serverSeqHash === clientSeqHash);

                    // Check action counts (order doesn't matter)
                    let countsMatch = true;
                    let countDiffs = [];
                    for (const [playerId, serverCounts] of Object.entries(serverActionCounts)) {
                        const clientCounts = this.actionCounts[playerId] || {};
                        for (const [action, serverCount] of Object.entries(serverCounts)) {
                            const clientCount = clientCounts[action] || 0;
                            if (serverCount !== clientCount) {
                                countsMatch = false;
                                countDiffs.push(`P${playerId} action ${action}: server=${serverCount} client=${clientCount}`);
                            }
                        }
                        // Also check for actions client has that server doesn't
                        for (const [action, clientCount] of Object.entries(clientCounts)) {
                            if (!(action in serverCounts)) {
                                countsMatch = false;
                                countDiffs.push(`P${playerId} action ${action}: server=0 client=${clientCount}`);
                            }
                        }
                    }
                    // Check for players client has that server doesn't
                    for (const playerId of Object.keys(this.actionCounts)) {
                        if (!(playerId in serverActionCounts)) {
                            countsMatch = false;
                            countDiffs.push(`P${playerId}: server=missing client=present`);
                        }
                    }

                    console.log(`[Sync Verify] Frame ${serverFrame}:`);
                    console.log(`  Total actions: server=${serverTotalActions} client=${clientTotalActions}`);
                    console.log(`  Sequence hash: ${sequenceMatches ? 'MATCH' : 'DIFFER'} (server=${serverSeqHash.substring(0, 8)} client=${clientSeqHash.substring(0, 8)})`);
                    console.log(`  Action counts: ${countsMatch ? 'MATCH' : 'DIFFER'}`);
                    if (!countsMatch) {
                        console.log(`  Count differences: ${countDiffs.join(', ')}`);
                    }

                    // Diagnostic conclusion and action decision
                    if (countsMatch && sequenceMatches) {
                        console.log(`  → Same actions, same order (non-determinism in env step)`);
                        // True non-determinism - need to correct
                    } else if (countsMatch && !sequenceMatches) {
                        console.log(`  → Same actions executed, different order (timing issue - SKIPPING correction)`);
                        // Same actions in different order due to timing. For deterministic envs,
                        // the final state should be the same. Skip the correction to avoid
                        // constant state resets that cause jittery gameplay.
                        // Just sync the frame number and rewards, but keep local state.
                        if (state.cumulative_rewards) {
                            this.cumulative_rewards = state.cumulative_rewards;
                            ui_utils.updateHUDText(this.getHUDText());
                        }
                        // Sync action counts to prevent accumulating small differences
                        this.actionCounts = JSON.parse(JSON.stringify(serverActionCounts));
                        // Update server step tracking (critical for throttling)
                        if (state.step_num !== undefined) {
                            this.lastKnownServerStepNum = state.step_num;
                        }
                        // Don't apply state correction - continue with local state
                        this.diagnostics.lastSyncFrame = state.frame_number;
                        this.diagnostics.lastSyncTime = Date.now();
                        return;
                    } else {
                        console.log(`  → Different actions executed (action sync issue)`);
                        // Action mismatch - need to correct
                    }
                    // ===== END ACTION VERIFICATION =====

                    // Track pre-sync state for debugging
                    const preSyncFrame = this.frameNumber;

                    // Apply server state to correct divergence
                    const applyStartTime = performance.now();
                    await this.applyServerState(state);
                    const applyTime = performance.now() - applyStartTime;

                    // Clear hash history since we've reset state
                    this.stateHashHistory.clear();

                    // Sync action tracking with server to prevent divergence accumulation
                    // We need to rebuild our action sequence to match server's count
                    // Since we don't have the full sequence, we just sync the counts and total
                    if (state.action_counts) {
                        this.actionCounts = JSON.parse(JSON.stringify(state.action_counts));
                    }
                    // Rebuild action sequence with correct length (details don't matter for count comparison)
                    const serverTotal = state.total_actions || 0;
                    if (this.actionSequence.length !== serverTotal) {
                        // Trim or pad to match server's total
                        if (this.actionSequence.length > serverTotal) {
                            this.actionSequence = this.actionSequence.slice(0, serverTotal);
                        }
                        // Note: If client has fewer, we can't recover the missing entries,
                        // but counts are synced so next comparison will work
                    }

                    // Log detailed sync application info
                    console.log(
                        `[Sync] Applied correction (${comparisonResult}): ` +
                        `frame ${preSyncFrame} → ${this.frameNumber} | ` +
                        `apply=${applyTime.toFixed(1)}ms | ` +
                        `latency=${typeof networkLatency === 'number' ? networkLatency.toFixed(0) + 'ms' : networkLatency} | ` +
                        `serverHash=${serverHash ? serverHash.substring(0, 8) : 'N/A'}, ` +
                        `clientHash@${serverFrame}=${clientHash ? clientHash.substring(0, 8) : 'N/A'}`
                    );

                    if (Math.abs(frameDiff) > 5) {
                        console.warn(
                            `[Sync] ⚠️ Large drift detected (${frameDiff} frames). ` +
                            `Queue pre-sync: ${totalQueueSize}`
                        );
                    }
                }
            } else {
                // No env_state available - just sync rewards/frame number
                console.warn(`[Sync] No env_state in server broadcast - state correction not possible`);
                if (state.cumulative_rewards) {
                    this.cumulative_rewards = state.cumulative_rewards;
                    ui_utils.updateHUDText(this.getHUDText());
                }
            }

            // Always update server step tracking when we receive a sync (critical for throttling)
            // This ensures throttling works even when we skip corrections
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

        // Server-authoritative throttling: Don't get too far ahead of the server.
        // The server only steps when it receives actions from ALL players, so a fast
        // client can accumulate extra local steps. We pause if we're too far ahead.
        if (this.serverAuthoritative && this.lastKnownServerStepNum > 0) {
            const stepsAhead = this.frameNumber - this.lastKnownServerStepNum;
            if (stepsAhead >= this.maxStepsAheadOfServer) {
                // We're too far ahead - wait for server to catch up
                const maxWaitMs = 200;  // Max wait before giving up
                const pollIntervalMs = 10;
                let waited = 0;

                while (waited < maxWaitMs && (this.frameNumber - this.lastKnownServerStepNum) >= this.maxStepsAheadOfServer) {
                    await new Promise(resolve => setTimeout(resolve, pollIntervalMs));
                    waited += pollIntervalMs;
                }

                if (waited >= maxWaitMs) {
                    console.warn(`[Throttle] Waited ${waited}ms but still ${this.frameNumber - this.lastKnownServerStepNum} steps ahead of server (frame ${this.frameNumber}, server at ${this.lastKnownServerStepNum})`);
                }
            }
        }

        // Action synchronization for server-authoritative mode:
        // We check if we have actions from other players. If not, we wait briefly.
        // But we DON'T block indefinitely - that kills FPS.
        //
        // The key insight: The server waits for ALL players before stepping.
        // So if we step with a fallback action, the server will get our real action
        // and step correctly. The only issue is if we use fallback TOO OFTEN,
        // causing action count divergence. But occasional fallback is fine.
        //
        // Strategy: Quick check (no wait) if we have actions. If not, brief wait.
        // If still no actions after brief wait, proceed with fallback.
        if (this.serverAuthoritative) {
            // First, check if we already have all actions (common case - no wait needed)
            let haveAllActions = true;
            for (const [agentId, policy] of Object.entries(this.policyMapping)) {
                const agentIdStr = String(agentId);
                const myPlayerIdStr = String(this.myPlayerId);

                if (agentIdStr === myPlayerIdStr || policy !== 'human') {
                    continue;
                }

                const queue = this.otherPlayerActionQueues[agentIdStr] || [];
                if (queue.length === 0) {
                    haveAllActions = false;
                    break;
                }
            }

            // Only wait if we don't have actions yet
            if (!haveAllActions) {
                const maxWaitMs = 50;  // Brief wait - don't block too long
                const pollIntervalMs = 5;
                let waited = 0;

                while (waited < maxWaitMs) {
                    await new Promise(resolve => setTimeout(resolve, pollIntervalMs));
                    waited += pollIntervalMs;

                    // Re-check if actions arrived
                    haveAllActions = true;
                    for (const [agentId, policy] of Object.entries(this.policyMapping)) {
                        const agentIdStr = String(agentId);
                        const myPlayerIdStr = String(this.myPlayerId);

                        if (agentIdStr === myPlayerIdStr || policy !== 'human') {
                            continue;
                        }

                        const queue = this.otherPlayerActionQueues[agentIdStr] || [];
                        if (queue.length === 0) {
                            haveAllActions = false;
                            break;
                        }
                    }

                    if (haveAllActions) {
                        break;
                    }
                }
            }

            // Throttle if queue is building up (we're faster than partner)
            const totalQueueSize = Object.values(this.otherPlayerActionQueues)
                .reduce((sum, queue) => sum + queue.length, 0);
            if (totalQueueSize > 10) {
                const throttleDelayMs = Math.min((totalQueueSize - 10) * 3, 30);
                await new Promise(resolve => setTimeout(resolve, throttleDelayMs));
            }
        } else if (this.throttle.enabled) {
            // Non-server-authoritative mode: use simpler throttling
            const totalQueueSize = Object.values(this.otherPlayerActionQueues)
                .reduce((sum, queue) => sum + queue.length, 0);

            if (totalQueueSize === 0) {
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
        // Don't send actions during episode transitions to prevent queue buildup
        const inEpisodeTransition = this.episodeComplete || this.waitingForEpisodeStart || this.shouldReset;
        if (!inEpisodeTransition) {
            const myAction = finalActions[this.myPlayerId];
            socket.emit('pyodide_player_action', {
                game_id: this.gameId,
                player_id: this.myPlayerId,
                action: myAction,
                frame_number: this.frameNumber,
                timestamp: Date.now(),
                sync_epoch: this.syncEpoch  // Include epoch to prevent stale action matching
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
        }

        // 4. Increment frame (AFTER recording hash)
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

    async computeStateHash() {
        /**
         * Compute hash of current game state using JavaScript crypto.
         * Uses env.get_state() for the environment state (same data used for full sync).
         *
         * Falls back to a simple hash function if crypto.subtle is unavailable
         * (which happens on non-HTTPS connections).
         *
         * Requires the environment to implement get_state() returning a
         * JSON-serializable dict.
         */
        const envState = await this.pyodide.runPythonAsync(`
import json

if not hasattr(env, 'get_state') or not callable(getattr(env, 'get_state')):
    raise RuntimeError(
        "Environment does not implement get_state(). "
        "State synchronization requires get_state() and set_state() methods "
        "that return/accept JSON-serializable dicts with primitive types only."
    )

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

    /**
     * Compute hash of action sequence for comparison with server.
     */
    computeActionSequenceHash() {
        const str = JSON.stringify(this.actionSequence);
        return this._simpleHash(str);
    }

    async getFullState() {
        /**
         * Serialize complete environment state (host only)
         *
         * Requires the environment to implement get_state() returning a
         * JSON-serializable dict.
         */
        const fullState = await this.pyodide.runPythonAsync(`
import numpy as np
import json

if not hasattr(env, 'get_state') or not callable(getattr(env, 'get_state')):
    raise RuntimeError(
        "Environment does not implement get_state(). "
        "State synchronization requires get_state() and set_state() methods "
        "that return/accept JSON-serializable dicts with primitive types only."
    )

env_state = env.get_state()

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
         * Requires the environment to implement set_state() that accepts a
         * JSON-serializable dict.
         */
        await this.pyodide.runPythonAsync(`
import numpy as np

state_obj = ${this.pyodide.toPy(state)}

# Restore environment state (most important!)
if 'env_state' in state_obj:
    env_state = state_obj['env_state']

    if not hasattr(env, 'set_state') or not callable(getattr(env, 'set_state')):
        raise RuntimeError(
            "Environment does not implement set_state(). "
            "State synchronization requires get_state() and set_state() methods "
            "that return/accept JSON-serializable dicts with primitive types only."
        )

    env.set_state(env_state)
    print("[Python] ✓ Restored environment state via set_state()")
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
