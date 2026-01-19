/**
 * Multiplayer Pyodide Game
 *
 * Extends RemoteGame to support multiplayer Pyodide games where:
 * - Each client runs their own Pyodide environment
 * - Server coordinates action synchronization
 * - Deterministic execution via seeded RNG
 * - Symmetric P2P architecture (no host)
 * - State verification detects desyncs
 */

import * as pyodide_remote_game from './pyodide_remote_game.js';
import { convertUndefinedToNull } from './pyodide_remote_game.js';
import * as seeded_random from './seeded_random.js';
import * as ui_utils from './ui_utils.js';
import { WebRTCManager } from './webrtc_manager.js';

// ========== Logging Configuration ==========
// Control verbosity via browser console: window.p2pLogLevel = 'debug'
// Levels: 'error' (critical only), 'warn' (+ warnings), 'info' (+ key events), 'debug' (+ verbose)
const LOG_LEVELS = { error: 0, warn: 1, info: 2, debug: 3 };

function getLogLevel() {
    if (typeof window !== 'undefined' && window.p2pLogLevel) {
        return LOG_LEVELS[window.p2pLogLevel] ?? LOG_LEVELS.info;
    }
    return LOG_LEVELS.info;  // Default: show key events but not verbose debug
}

// Logging helpers - use these instead of console.log directly
const p2pLog = {
    error: (...args) => console.error('[P2P]', ...args),
    warn: (...args) => { if (getLogLevel() >= LOG_LEVELS.warn) console.warn('[P2P]', ...args); },
    info: (...args) => { if (getLogLevel() >= LOG_LEVELS.info) console.log('[P2P]', ...args); },
    debug: (...args) => { if (getLogLevel() >= LOG_LEVELS.debug) console.log('[P2P]', ...args); },
};

// ========== P2P Binary Message Protocol ==========
// Message Types
const P2P_MSG_INPUT = 0x01;
const P2P_MSG_PING = 0x02;
const P2P_MSG_PONG = 0x03;
const P2P_MSG_KEEPALIVE = 0x04;
const P2P_MSG_EPISODE_END = 0x05;  // Episode reset synchronization

/**
 * Encode an input packet for P2P transmission.
 * Format: 9 bytes header + 5 bytes per input
 *   Header:
 *     Byte 0: Message type (0x01)
 *     Bytes 1-2: Player ID (uint16)
 *     Bytes 3-6: Current frame (uint32)
 *     Byte 7: Input count (1-5)
 *     Byte 8: Reserved/flags
 *   Each input:
 *     Bytes 0-3: Frame number (uint32)
 *     Byte 4: Action value (uint8)
 *
 * @param {number} playerId - Player ID (0-65535)
 * @param {number} currentFrame - Current simulation frame
 * @param {Array<{frame: number, action: number}>} inputs - Inputs to send (oldest first)
 * @returns {ArrayBuffer} Encoded packet
 */
function encodeInputPacket(playerId, currentFrame, inputs) {
    const inputCount = Math.min(inputs.length, 5);
    const buffer = new ArrayBuffer(9 + inputCount * 5);
    const view = new DataView(buffer);

    view.setUint8(0, P2P_MSG_INPUT);
    view.setUint16(1, playerId, false);  // big-endian
    view.setUint32(3, currentFrame, false);
    view.setUint8(7, inputCount);
    view.setUint8(8, 0);  // reserved

    for (let i = 0; i < inputCount; i++) {
        const offset = 9 + i * 5;
        view.setUint32(offset, inputs[i].frame, false);
        view.setUint8(offset + 4, inputs[i].action);
    }

    return buffer;
}

/**
 * Decode a binary input packet.
 *
 * @param {ArrayBuffer} buffer - Received packet
 * @returns {{playerId: number, currentFrame: number, inputs: Array<{frame: number, action: number}>}|null}
 */
function decodeInputPacket(buffer) {
    const view = new DataView(buffer);

    const type = view.getUint8(0);
    if (type !== P2P_MSG_INPUT) return null;

    const playerId = view.getUint16(1, false);
    const currentFrame = view.getUint32(3, false);
    const inputCount = view.getUint8(7);

    const inputs = [];
    for (let i = 0; i < inputCount; i++) {
        const offset = 9 + i * 5;
        inputs.push({
            frame: view.getUint32(offset, false),
            action: view.getUint8(offset + 4)
        });
    }

    return { playerId, currentFrame, inputs };
}

/**
 * Encode a ping message for RTT measurement.
 * Format: 9 bytes
 *   Byte 0: Message type (0x02)
 *   Bytes 1-8: Timestamp (float64, performance.now())
 *
 * @returns {ArrayBuffer} Encoded ping
 */
function encodePing() {
    const buffer = new ArrayBuffer(9);
    const view = new DataView(buffer);
    view.setUint8(0, P2P_MSG_PING);
    view.setFloat64(1, performance.now(), false);
    return buffer;
}

/**
 * Encode a pong response (echo back the original timestamp).
 *
 * @param {number} originalTimestamp - Timestamp from received ping
 * @returns {ArrayBuffer} Encoded pong
 */
function encodePong(originalTimestamp) {
    const buffer = new ArrayBuffer(9);
    const view = new DataView(buffer);
    view.setUint8(0, P2P_MSG_PONG);
    view.setFloat64(1, originalTimestamp, false);
    return buffer;
}

/**
 * Encode an episode end notification for P2P transmission.
 * Format: 9 bytes
 *   Byte 0: Message type (0x05)
 *   Bytes 1-4: Frame number where episode ended (uint32)
 *   Bytes 5-8: Episode number (uint32)
 *
 * @param {number} frameNumber - Frame where episode ended
 * @param {number} episodeNumber - Current episode number
 * @returns {ArrayBuffer} Encoded packet
 */
function encodeEpisodeEnd(frameNumber, episodeNumber) {
    const buffer = new ArrayBuffer(9);
    const view = new DataView(buffer);
    view.setUint8(0, P2P_MSG_EPISODE_END);
    view.setUint32(1, frameNumber, false);
    view.setUint32(5, episodeNumber, false);
    return buffer;
}

/**
 * Decode an episode end notification.
 *
 * @param {ArrayBuffer} buffer - Received packet
 * @returns {{frameNumber: number, episodeNumber: number}|null}
 */
function decodeEpisodeEnd(buffer) {
    const view = new DataView(buffer);
    const type = view.getUint8(0);
    if (type !== P2P_MSG_EPISODE_END) return null;
    return {
        frameNumber: view.getUint32(1, false),
        episodeNumber: view.getUint32(5, false)
    };
}

/**
 * Get the message type from a binary message.
 *
 * @param {ArrayBuffer} buffer - Received message
 * @returns {number} Message type byte
 */
function getMessageType(buffer) {
    const view = new DataView(buffer);
    return view.getUint8(0);
}

/**
 * Tracks round-trip time measurements from ping/pong exchanges.
 */
class RTTTracker {
    constructor() {
        this.rttSamples = [];
        this.maxSamples = 10;
        this.lastPingTime = 0;
        this.pingInterval = 500;  // ms between pings
    }

    /**
     * Check if enough time has passed to send another ping.
     * @returns {boolean}
     */
    shouldPing() {
        return performance.now() - this.lastPingTime >= this.pingInterval;
    }

    /**
     * Record an RTT sample from a pong response.
     * @param {number} sentTime - The timestamp echoed back in the pong
     */
    recordRTT(sentTime) {
        const rtt = performance.now() - sentTime;
        this.rttSamples.push(rtt);
        if (this.rttSamples.length > this.maxSamples) {
            this.rttSamples.shift();
        }
    }

    /**
     * Get the average RTT across recent samples.
     * @returns {number|null} Average RTT in ms, or null if no samples
     */
    getAverageRTT() {
        if (this.rttSamples.length === 0) return null;
        return this.rttSamples.reduce((a, b) => a + b, 0) / this.rttSamples.length;
    }

    /**
     * Get estimated one-way latency (half of RTT).
     * @returns {number|null} Latency in ms, or null if no samples
     */
    getLatency() {
        const rtt = this.getAverageRTT();
        return rtt !== null ? rtt / 2 : null;
    }
}

/**
 * Monitors P2P connection health based on packet reception patterns and latency.
 */
class ConnectionHealthMonitor {
    constructor() {
        this.rttTracker = new RTTTracker();
        this.lastReceivedFrame = -1;
        this.packetsReceived = 0;
        this.gapCount = 0;  // Count of detected frame gaps

        // Health thresholds
        this.warningLatencyMs = 100;
        this.criticalLatencyMs = 200;
    }

    /**
     * Record that we received an input for a frame.
     * @param {number} frame - The frame number received
     */
    recordReceivedInput(frame) {
        this.packetsReceived++;

        // Detect gaps (indicates packet loss, though redundancy may cover it)
        if (this.lastReceivedFrame >= 0 && frame > this.lastReceivedFrame + 1) {
            this.gapCount++;
        }
        this.lastReceivedFrame = Math.max(this.lastReceivedFrame, frame);
    }

    /**
     * Get current connection health status.
     * @returns {{rtt: number|null, latency: number|null, packetsReceived: number, gapCount: number, status: string}}
     */
    getHealthStatus() {
        const latency = this.rttTracker.getLatency();

        let status = 'good';
        if (latency !== null) {
            if (latency > this.criticalLatencyMs) {
                status = 'critical';
            } else if (latency > this.warningLatencyMs) {
                status = 'warning';
            }
        }

        return {
            rtt: this.rttTracker.getAverageRTT(),
            latency: latency,
            packetsReceived: this.packetsReceived,
            gapCount: this.gapCount,
            status: status
        };
    }
}

/**
 * Manages sending local inputs over P2P DataChannel with redundancy.
 * Each packet includes the last N inputs to handle packet loss.
 */
class P2PInputSender {
    /**
     * @param {WebRTCManager} webrtcManager - The WebRTC connection manager
     * @param {number} myPlayerId - This player's ID
     * @param {number} redundancyCount - Number of inputs to include per packet (default: 3)
     */
    constructor(webrtcManager, myPlayerId, redundancyCount = 3) {
        this.webrtcManager = webrtcManager;
        this.myPlayerId = myPlayerId;
        this.redundancyCount = redundancyCount;

        // Track recent inputs for redundant sending
        // [{frame, action}, ...] - most recent at end
        this.recentInputs = [];
        this.maxRecentInputs = 10;  // Keep larger buffer than redundancy needs

        // Buffer congestion threshold (bytes)
        this.bufferThreshold = 16384;
    }

    /**
     * Record a local input and send it (with redundancy) to peer.
     * @param {number} action - The action taken
     * @param {number} targetFrame - The frame this input is scheduled for
     * @returns {boolean} True if sent, false if skipped (buffer congested or not ready)
     */
    recordAndSend(action, targetFrame) {
        // Record this input
        this.recentInputs.push({ frame: targetFrame, action: action });

        // Trim to max size
        if (this.recentInputs.length > this.maxRecentInputs) {
            this.recentInputs.shift();
        }

        // Check if channel is ready
        if (!this.webrtcManager?.isReady()) {
            return false;
        }

        // Check buffer congestion
        const dc = this.webrtcManager.dataChannel;
        if (dc && dc.bufferedAmount > this.bufferThreshold) {
            p2pLog.debug('Buffer congested, skipping input packet');
            return false;
        }

        // Build redundant input set (current + last N-1)
        const inputsToSend = this.recentInputs.slice(-this.redundancyCount);

        // Encode and send
        const packet = encodeInputPacket(
            this.myPlayerId,
            targetFrame,
            inputsToSend
        );

        return this.webrtcManager.send(packet);
    }

    /**
     * Clear recorded inputs (call on episode reset).
     */
    reset() {
        this.recentInputs = [];
    }
}

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
        this.INPUT_DELAY = config.input_delay ?? 0;  // frames of input delay

        // DEBUG: Artificial delay for remote inputs (in frames) to force rollbacks
        // Set via browser console: window.debugRemoteInputDelay = 5
        // This delays processing of remote inputs to simulate network latency
        this.debugRemoteInputDelay = 0;
        this.debugDelayedInputQueue = [];  // [{playerId, action, frameNumber, processAtFrame}]

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

        // P2P sync state (for non-server-authoritative mode)
        this.p2pSyncInterval = 30;  // Frames between P2P state hash broadcasts
        this.lastP2PSyncFrame = 0;  // Last frame we sent/received P2P sync
        this.p2pHashMismatches = 0;  // Count of hash mismatches detected

        // State sync capability (requires env.get_state() and env.set_state())
        // Set during validateStateSync() - if false, hash comparison and resync are disabled
        this.stateSyncSupported = false;

        // P2P WebRTC connection
        this.webrtcManager = null;
        this.p2pConnected = false;
        this.p2pPeerId = null;  // The other player's ID

        // Player ID mapping for binary protocol (string ID <-> numeric index)
        this.playerIdToIndex = {};  // "agent_left" -> 0, "agent_right" -> 1
        this.indexToPlayerId = {};  // 0 -> "agent_left", 1 -> "agent_right"

        // P2P input sending
        this.p2pInputSender = null;
        this.connectionHealth = null;
        this.pingIntervalId = null;

        // P2P metrics for observability
        this.p2pMetrics = {
            inputsReceivedViaP2P: 0,
            inputsReceivedViaSocketIO: 0,
            inputsSentViaP2P: 0,
            inputsSentViaSocketIO: 0,
            p2pFallbackTriggered: false,
            p2pFallbackFrame: null,
            connectionType: null,
            connectionDetails: null
        };

        // P2P episode synchronization
        // Both peers must agree on episode end before resetting
        this.p2pEpisodeSync = {
            localEpisodeEndDetected: false,   // We detected episode end
            localEpisodeEndFrame: null,       // Frame where we detected it
            remoteEpisodeEndReceived: false,  // Peer sent episode end message
            remoteEpisodeEndFrame: null,      // Frame where peer detected it
            pendingReset: false,              // Waiting for sync before reset
            syncTimeoutId: null               // Timeout to prevent infinite waiting
        };

        // Session metrics for research data export
        this.sessionMetrics = {
            rollbacks: {
                events: [],
                count: 0,
                maxFrames: 0
            }
        };

        // TURN server configuration (populated by pyodide_game_ready)
        this.turnConfig = null;

        // P2P ready gate - prevents game loop from starting until P2P is established
        // This ensures the first frame can use P2P, not just SocketIO fallback
        this.p2pReadyGate = {
            enabled: true,           // Set to false to skip waiting for P2P
            resolved: false,         // True when P2P is ready or timeout
            timeoutMs: 5000,         // Max time to wait for P2P connection
            timeoutId: null          // Timeout handle
        };

        // GGPO-style input queuing: inputs are queued during network reception
        // and processed synchronously at frame start to prevent race conditions
        this.pendingInputPackets = [];     // Queued P2P input packets
        this.pendingSocketIOInputs = [];   // Queued SocketIO inputs
        this.rollbackInProgress = false;   // Guard against nested rollbacks

        this.setupMultiplayerHandlers();
    }

    setupMultiplayerHandlers() {
        /**
         * Set up SocketIO event handlers for multiplayer coordination
         */

        // Player initialization (receive player ID and game seed)
        socket.on('pyodide_player_assigned', (data) => {
            this.myPlayerId = data.player_id;
            this.gameId = data.game_id;
            this.gameSeed = data.game_seed;

            // Initialize seeded RNG for AI policies
            if (this.gameSeed) {
                seeded_random.initMultiplayerRNG(this.gameSeed);
                p2pLog.info(`Player ${this.myPlayerId} assigned to game ${this.gameId} (seed=${this.gameSeed})`);
            }
        });

        // Game ready to start
        socket.on('pyodide_game_ready', (data) => {
            p2pLog.info(`Game ready: ${data.players.length} players, server_auth=${data.server_authoritative || false}`);

            // Build player ID <-> index mapping for binary protocol
            // Sort players to ensure deterministic index assignment across clients
            const sortedPlayers = [...data.players].sort();
            sortedPlayers.forEach((playerId, index) => {
                this.playerIdToIndex[playerId] = index;
                this.indexToPlayerId[index] = playerId;
            });
            p2pLog.debug('Player ID mapping:', this.playerIdToIndex);

            // Store TURN configuration for P2P
            this.turnConfig = data.turn_config || null;
            if (this.turnConfig) {
                p2pLog.debug('TURN config received');
            }

            // Store player-to-subject mapping for data logging
            this.playerSubjects = data.player_subjects || {};

            // Server-authoritative mode
            this.serverAuthoritative = data.server_authoritative || false;

            // Initialize action queues for other players
            for (const playerId of data.players) {
                if (playerId != this.myPlayerId) {
                    this.otherPlayerActionQueues[playerId] = [];
                }
            }

            // Initiate P2P WebRTC connection
            // Find the other player's ID (for 2-player games)
            const otherPlayers = data.players.filter(pid => pid != this.myPlayerId);
            if (otherPlayers.length === 1) {
                this.p2pPeerId = otherPlayers[0];
                this._initP2PConnection();

                // Start P2P ready gate timeout - game will start after P2P connects or timeout
                if (this.p2pReadyGate.enabled) {
                    p2pLog.info(`Waiting for P2P connection (max ${this.p2pReadyGate.timeoutMs}ms)...`);
                    this.p2pReadyGate.timeoutId = setTimeout(() => {
                        if (!this.p2pReadyGate.resolved) {
                            p2pLog.warn(`P2P connection timeout - starting game with SocketIO fallback`);
                            this._resolveP2PReadyGate();
                        }
                    }, this.p2pReadyGate.timeoutMs);
                }
            } else if (otherPlayers.length > 1) {
                p2pLog.warn('P2P only supports 2-player games, using SocketIO only');
                this._resolveP2PReadyGate();  // No P2P for >2 players
            } else {
                // Single player or no other players - no P2P needed
                this._resolveP2PReadyGate();
            }
        });

        // Receive other player's action (GGPO: queue for synchronous processing at frame start)
        socket.on('pyodide_other_player_action', (data) => {
            // Don't queue actions if game is done
            if (this.state === "done") {
                return;
            }

            const { player_id, action, frame_number } = data;

            // Only log late inputs (potential rollback trigger)
            const frameDiff = this.frameNumber - frame_number;
            if (frameDiff > 0) {
                p2pLog.debug(`Late input via SocketIO: player=${player_id}, frame=${frame_number}, late by ${frameDiff}`);
            }

            // GGPO-style: Queue input for synchronous processing at frame start
            // This prevents race conditions during rollback replay
            this.pendingSocketIOInputs.push({
                playerId: player_id,
                action: action,
                frameNumber: frame_number
            });

            // Track SocketIO input reception for metrics
            this.p2pMetrics.inputsReceivedViaSocketIO++;

            // Also update lastConfirmedActions immediately so we always have
            // the latest action for prediction/fallback
            this.lastConfirmedActions[String(player_id)] = action;
        });

        // P2P state hash sync (non-server-authoritative mode)
        // Both peers broadcast state hash for symmetric desync detection
        socket.on('p2p_state_sync', async (data) => {
            // Only process in non-server-authoritative mode
            if (this.serverAuthoritative) {
                return;
            }

            // Skip hash comparison if state sync not supported (no get_state/set_state)
            if (!this.stateSyncSupported) {
                return;
            }

            const { game_id, sender_id, frame_number, state_hash, action_counts } = data;
            if (game_id !== this.gameId || sender_id === this.myPlayerId) {
                return;  // Ignore own messages or wrong game
            }

            // Compute our hash for comparison
            // Use the hash at the same frame if we have it, or compute current
            let ourHash = this.stateHashHistory.get(frame_number);
            if (!ourHash && Math.abs(this.frameNumber - frame_number) <= 5) {
                // We're close enough, compute current hash for comparison
                ourHash = await this.computeQuickStateHash();
            }

            if (ourHash && state_hash) {
                if (ourHash === state_hash) {
                    // States match - only log in debug mode
                    p2pLog.debug(`Sync OK at frame ${frame_number} (hash=${state_hash.substring(0, 8)})`);
                    this.confirmedFrame = Math.max(this.confirmedFrame, frame_number);
                } else {
                    // DESYNC - always log this critical event
                    this.p2pHashMismatches++;
                    p2pLog.warn(
                        `DESYNC at frame ${frame_number}! ` +
                        `Peer: ${state_hash.substring(0, 8)}, Ours: ${ourHash.substring(0, 8)} ` +
                        `(total: ${this.p2pHashMismatches})`
                    );

                    // Log action count mismatches only in debug mode
                    if (action_counts && getLogLevel() >= LOG_LEVELS.debug) {
                        for (const [playerId, peerCounts] of Object.entries(action_counts)) {
                            const ourCounts = this.actionCounts[playerId] || {};
                            for (const [action, peerCount] of Object.entries(peerCounts)) {
                                const ourCount = ourCounts[action] || 0;
                                if (peerCount !== ourCount) {
                                    p2pLog.debug(`  Action diff: player=${playerId} action=${action} peer=${peerCount} ours=${ourCount}`);
                                }
                            }
                        }
                    }

                    // P2P State Resync: Request state from peer if desync detected
                    // Use deterministic tie-breaker: lower player ID defers to higher
                    if (this._shouldRequestStateResync(sender_id)) {
                        p2pLog.info(`Requesting state resync from peer ${sender_id}`);
                        socket.emit('p2p_state_request', {
                            game_id: this.gameId,
                            requester_id: this.myPlayerId,
                            target_id: sender_id,
                            frame_number: frame_number
                        });
                    }
                }
            }

            this.lastP2PSyncFrame = frame_number;
        });

        // P2P state request - peer is asking us to send our state
        socket.on('p2p_state_request', async (data) => {
            const { game_id, requester_id, target_id, frame_number } = data;
            if (game_id !== this.gameId || target_id !== this.myPlayerId) {
                return;
            }

            // Can't respond if state sync not supported
            if (!this.stateSyncSupported) {
                p2pLog.warn('Cannot respond to state request - get_state not available');
                return;
            }

            p2pLog.debug(`Peer ${requester_id} requested our state`);

            // Get current state and send it
            try {
                const envState = await this.pyodide.runPythonAsync(`
import json
env.get_state()
                `);
                const stateDict = envState.toJs({ dict_converter: Object.fromEntries });

                socket.emit('p2p_state_response', {
                    game_id: this.gameId,
                    sender_id: this.myPlayerId,
                    target_id: requester_id,
                    frame_number: this.frameNumber,
                    step_num: this.step_num,
                    env_state: stateDict,
                    cumulative_rewards: this.cumulative_rewards
                });
                p2pLog.debug(`Sent state to peer ${requester_id} (frame=${this.frameNumber})`);
            } catch (err) {
                p2pLog.error('Failed to get/send state:', err);
            }
        });

        // P2P state response - peer is sending us their state
        socket.on('p2p_state_response', async (data) => {
            const { game_id, sender_id, target_id, frame_number, step_num, env_state, cumulative_rewards } = data;
            if (game_id !== this.gameId || target_id !== this.myPlayerId) {
                return;
            }

            // Can't apply if state sync not supported
            if (!this.stateSyncSupported) {
                p2pLog.warn('Cannot apply peer state - set_state not available');
                return;
            }

            p2pLog.info(`Applying peer state from ${sender_id} (frame=${frame_number})`);

            try {
                // Apply the peer's state
                await this._applyP2PState(env_state, frame_number, step_num, cumulative_rewards);
                p2pLog.info(`State resync complete, now at frame ${this.frameNumber}`);
            } catch (err) {
                p2pLog.error('Failed to apply peer state:', err);
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

            // Calculate step time stats
            const stepTimes = this.diagnostics.stepTimes;
            const avgStepTime = stepTimes.length > 0
                ? (stepTimes.reduce((a, b) => a + b, 0) / stepTimes.length).toFixed(1)
                : 'N/A';
            const maxStepTime = stepTimes.length > 0
                ? Math.max(...stepTimes).toFixed(1)
                : 'N/A';

            // Calculate FPS since last sync
            const now = Date.now();
            const targetFPS = this.config.fps || 10;
            const framesSinceLastSync = this.frameNumber - this.diagnostics.lastSyncFrame;
            const timeSinceLastSync = now - this.diagnostics.lastSyncTime;
            const effectiveFPS = framesSinceLastSync > 0 && this.diagnostics.lastSyncTime > 0 && timeSinceLastSync > 0
                ? ((framesSinceLastSync / timeSinceLastSync) * 1000).toFixed(1)
                : 'N/A';

            // Log sync info (verbose - debug only)
            p2pLog.debug(
                `Sync #${this.diagnostics.syncCount}: ` +
                `Server=${state.frame_number} Client=${this.frameNumber} Drift=${frameDiff > 0 ? '+' : ''}${frameDiff} ` +
                `FPS=${effectiveFPS}/${targetFPS} Step=${avgStepTime}/${maxStepTime}ms ` +
                `Buf=${this.inputBuffer.size} Pred=${this.predictedFrames.size}`
            );

            // NOTE: Server reconciliation disabled - GGPO rollback handles sync.
            // Just sync rewards/metadata without state correction.
            if (state.cumulative_rewards) {
                this.cumulative_rewards = state.cumulative_rewards;
                ui_utils.updateHUDText(this.getHUDText());
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

            p2pLog.debug(`Received server_episode_start for episode ${state.episode_num}`);

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

            p2pLog.info(`Server game complete: ${episode_num}/${max_episodes} episodes`);

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
    print(f"[Python] ⚠️ State synchronization (hash comparison, P2P resync) will be DISABLED.")
    print(f"[Python] ⚠️ To enable, implement get_state() and set_state() that return/accept JSON-serializable dicts.")
else:
    print(f"[Python] ✓ Environment {env_type} has get_state() and set_state() methods")

{
    'has_get_state': has_get_state,
    'has_set_state': has_set_state,
    'env_type': env_type,
    'env_module': env_module,
}
        `);

        // Store the capability for later use
        const capabilities = result.toJs({ dict_converter: Object.fromEntries });
        this.stateSyncSupported = capabilities.has_get_state && capabilities.has_set_state;

        if (this.stateSyncSupported) {
            p2pLog.info(`State sync enabled for ${capabilities.env_type}`);
        } else {
            p2pLog.warn(`State sync DISABLED - environment missing get_state/set_state`);
        }
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
        p2pLog.debug(`Episode reset starting: episode=${this.num_episodes + 1} player=${this.myPlayerId}`);

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

        // Clear P2P episode sync state for fresh episode
        this._clearEpisodeSyncState();

        // In server-authoritative mode, wait for server to broadcast episode start state
        if (this.serverAuthoritative) {
            // Check if this is a subsequent episode (not the first one)
            const isSubsequentEpisode = this.num_episodes > 0;

            // Show waiting message for subsequent episodes
            if (isSubsequentEpisode) {
                ui_utils.showEpisodeWaiting("Next round will begin shortly...");
            }

            p2pLog.debug("Waiting for server episode start state...");

            // Check if we already have pending state (server sent it before we called reset)
            let serverState = this.pendingEpisodeState;

            if (!serverState) {
                // Wait for the server to send the episode start state
                serverState = await this.waitForEpisodeStart();
            }

            // Clear pending state
            this.pendingEpisodeState = null;

            if (serverState && serverState.env_state) {
                p2pLog.debug(`Applying server episode state (episode ${serverState.episode_num})`);

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

                p2pLog.debug(`Reset complete from server state (episode ${serverState.episode_num})`);
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
        p2pLog.debug(`Reset took ${(endTime - startTime).toFixed(1)}ms`);

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
                    p2pLog.warn(`Timeout waiting for server episode start`);
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
        p2pLog.debug('Cleared action queues after episode transition');
    }

    async step(allActionsDict) {
        /**
         * Step environment in multiplayer mode (True GGPO)
         *
         * True GGPO: Both local AND remote actions are delayed by INPUT_DELAY frames.
         * This ensures both clients execute the same actions on the same frame.
         *
         * Process:
         * 1. Store current local input for future frame (current + INPUT_DELAY)
         * 2. Send action to server immediately (for relay to other clients)
         * 3. Build final action dict from input buffer (ALL players delayed)
         * 4. Step environment with delayed actions
         * 5. Save snapshots for potential rollback
         */

        // Don't step until multiplayer setup is complete
        if (this.myPlayerId === null || this.myPlayerId === undefined) {
            p2pLog.debug('Waiting for player ID assignment...');
            return null;
        }

        if (this.gameId === null || this.gameId === undefined) {
            p2pLog.debug('Waiting for game ID assignment...');
            return null;
        }

        // Get all human player IDs
        const humanPlayerIds = Object.entries(this.policyMapping)
            .filter(([_, policy]) => policy === 'human')
            .map(([id, _]) => String(id));

        // 1. Store current local input for future execution (INPUT_DELAY frames ahead)
        // This must happen BEFORE we build finalActions so the input is available
        const inEpisodeTransition = this.episodeComplete || this.waitingForEpisodeStart || this.shouldReset;
        if (!inEpisodeTransition) {
            const myCurrentAction = allActionsDict[this.myPlayerId] ?? this.defaultAction;
            const targetFrame = this.frameNumber + this.INPUT_DELAY;

            // Store in our own input buffer for the delayed frame
            this.storeLocalInput(myCurrentAction, this.frameNumber);

            // 2. Send input to other players - P2P first with SocketIO fallback
            const p2pHealthy = this.p2pConnected &&
                               this.p2pInputSender &&
                               !this.p2pMetrics.p2pFallbackTriggered;

            if (p2pHealthy) {
                // Primary: P2P DataChannel
                const sent = this.p2pInputSender.recordAndSend(myCurrentAction, targetFrame);
                if (sent) {
                    this.p2pMetrics.inputsSentViaP2P++;
                    // P2P success - don't use SocketIO
                } else {
                    // P2P send failed (buffer congested) - fall back to SocketIO
                    p2pLog.debug('Send failed (buffer full), using SocketIO');
                    this._sendViaSocketIO(myCurrentAction, targetFrame);
                }
            } else {
                // No healthy P2P connection - use SocketIO
                this._sendViaSocketIO(myCurrentAction, targetFrame);
            }
        }

        // Process any debug-delayed remote inputs that are now ready
        // This enables testing rollback behavior by artificially delaying inputs
        this.processDelayedInputs();

        // 3. Build final action dict - ALL human players use delayed inputs from buffer
        // This is true GGPO: local player also experiences input delay
        const finalActions = {};

        // Get inputs for ALL human players from GGPO buffer (including self)
        const ggpoInputs = this.getInputsForFrame(this.frameNumber, humanPlayerIds);

        // Log which inputs are confirmed vs predicted for debugging
        const confirmedPlayers = [];
        const predictedPlayers = [];
        for (const playerId of humanPlayerIds) {
            const frameInputs = this.inputBuffer.get(this.frameNumber);
            if (frameInputs && frameInputs.has(playerId)) {
                confirmedPlayers.push(playerId);
            } else {
                predictedPlayers.push(playerId);
            }
        }

        // Only log predictions (key event) - confirmed inputs are normal operation
        if (predictedPlayers.length > 0) {
            p2pLog.debug(
                `Frame ${this.frameNumber}: predicted=[${predictedPlayers.join(',')}] ` +
                `confirmed=[${confirmedPlayers.join(',')}]`
            );
        }

        for (const [agentId, policy] of Object.entries(this.policyMapping)) {
            const agentIdStr = String(agentId);

            if (policy === 'human') {
                // ALL human players use delayed input from buffer (true GGPO)
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

        // GGPO: Save state snapshot BEFORE stepping (state that will be input to this frame's step)
        // This is critical: snapshot[N] = state BEFORE stepping frame N
        // So when we rollback to frame N, we load the state and can re-execute frame N
        if (this.frameNumber % this.snapshotInterval === 0) {
            await this.saveStateSnapshot(this.frameNumber);
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

        // NOTE: State hash recording and P2P sync broadcasts disabled.
        // GGPO rollback handles synchronization via input prediction and replay.
        // State sync (hash comparison) is a separate verification layer that's not needed
        // when rollback is working correctly.

        // Check P2P health for fallback awareness
        this._checkP2PHealth();

        // 4. Increment frame (AFTER recording hash)
        this.frameNumber++;

        // GGPO: Check for pending rollback (late input arrived)
        // IMPORTANT: Do this BEFORE pruning to ensure we have inputs for the rollback
        let rollbackOccurred = false;
        if (this.pendingRollbackFrame !== null && this.pendingRollbackFrame !== undefined) {
            const rollbackFrame = this.pendingRollbackFrame;
            this.pendingRollbackFrame = null;

            // Get all player IDs
            const playerIds = Object.keys(this.policyMapping).filter(
                pid => this.policyMapping[pid] === 'human'
            );

            // Perform rollback and replay
            rollbackOccurred = await this.performRollback(rollbackFrame, playerIds);
        }

        // Prune old input buffer entries to prevent unbounded growth
        // IMPORTANT: Do this AFTER rollback to ensure we don't remove inputs we need
        this.pruneInputBuffer();

        // Log diagnostics periodically
        this.logDiagnostics();

        // 5. Check if episode is complete (only trigger once)
        // Episode ends when: environment terminates/truncates OR max_steps reached
        const all_terminated = Array.from(terminateds.values()).every(value => value === true);
        const all_truncated = Array.from(truncateds.values()).every(value => value === true);
        const max_steps_reached = this.step_num >= this.max_steps;

        const episodeEndDetected = all_terminated || all_truncated || max_steps_reached;

        // In P2P mode (non-server-authoritative), use synchronized episode end
        // Both peers must agree before resetting to prevent desync
        if (episodeEndDetected && !this.episodeComplete && !this.p2pEpisodeSync.localEpisodeEndDetected) {
            // Log episode end detection (metrics logged here, actual completion when both peers agree)
            this._logEpisodeEndMetrics();

            if (this.serverAuthoritative) {
                // Server-authoritative mode: immediately complete (server coordinates)
                this.episodeComplete = true;
                this.signalEpisodeComplete();
            } else if (this.webrtcManager?.isReady()) {
                // P2P mode with active connection: broadcast and wait for peer
                p2pLog.debug(`Episode end detected at frame ${this.frameNumber}, broadcasting to peer...`);
                this._broadcastEpisodeEnd();
                // Don't set episodeComplete yet - _checkEpisodeSyncAndReset will do it when both agree
            } else {
                // P2P mode but no WebRTC connection: fallback to immediate completion
                p2pLog.debug(`Episode end at frame ${this.frameNumber}, no P2P - completing immediately`);
                this.episodeComplete = true;
                this.signalEpisodeComplete();
            }
        }

        // If rollback occurred, get fresh render_state from the corrected environment state
        // This ensures the display shows the correct state after rollback+replay
        let finalRenderState = render_state;
        if (rollbackOccurred) {
            try {
                const freshRender = await this.pyodide.runPythonAsync(`env.render()`);
                let freshRenderState = await this.pyodide.toPy(freshRender).toJs();

                // Handle RGB array rendering if needed
                let game_image_base64 = null;
                if (Array.isArray(freshRenderState) && Array.isArray(freshRenderState[0])) {
                    game_image_base64 = this.convertRGBArrayToImage(freshRenderState);
                }

                finalRenderState = {
                    "game_state_objects": game_image_base64 ? null : freshRenderState.map(item => convertUndefinedToNull(item)),
                    "game_image_base64": game_image_base64,
                    "step": this.step_num,
                };
                p2pLog.debug(`Rollback render update: frame=${this.frameNumber}`);
            } catch (e) {
                p2pLog.warn(`Failed to get post-rollback render state: ${e}`);
            }
        }

        // Return finalActions alongside step results so caller can log synchronized actions
        return [obs, rewards, terminateds, truncateds, infos, finalRenderState, finalActions];
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

        // Calculate input buffer size (GGPO)
        const inputBufferSize = this.inputBuffer.size;

        // Calculate step time stats
        const stepTimes = this.diagnostics.stepTimes;
        const avgStepTime = stepTimes.length > 0
            ? (stepTimes.reduce((a, b) => a + b, 0) / stepTimes.length).toFixed(1)
            : 'N/A';
        const maxStepTime = stepTimes.length > 0
            ? Math.max(...stepTimes).toFixed(1)
            : 'N/A';

        // Calculate prediction rate (frames where we used prediction)
        const predictionCount = this.predictedFrames.size;

        // Calculate effective FPS from actual frame delta (more accurate than stepTimes.length)
        const targetFPS = this.config.fps || 10;
        const intervalMs = now - this.diagnostics.lastDiagnosticsLog;
        const framesDelta = this.frameNumber - this.diagnostics.lastDiagnosticsFrame;
        const effectiveFPS = intervalMs > 0 ? ((framesDelta / intervalMs) * 1000).toFixed(1) : 'N/A';

        // P2P input metrics
        const p2pReceived = this.p2pMetrics.inputsReceivedViaP2P;
        const socketReceived = this.p2pMetrics.inputsReceivedViaSocketIO;
        const p2pSent = this.p2pMetrics.inputsSentViaP2P;
        const socketSent = this.p2pMetrics.inputsSentViaSocketIO;

        // Connection health
        const health = this.connectionHealth?.getHealthStatus() || {};
        const rtt = health.rtt?.toFixed(0) || 'N/A';
        const gaps = health.gapCount || 0;

        // Performance summary - only in debug mode (periodic, every 5s)
        p2pLog.debug(
            `[PERF] frame=${this.frameNumber} fps=${effectiveFPS}/${targetFPS} ` +
            `step=${avgStepTime}/${maxStepTime}ms buf=${inputBufferSize} ` +
            `pred=${predictionCount} rb=${this.rollbackCount}`
        );

        // Input metrics summary
        p2pLog.debug(
            `[INPUT] recv: p2p=${p2pReceived} sock=${socketReceived} | ` +
            `sent: p2p=${p2pSent} sock=${socketSent} | ` +
            `rtt=${rtt}ms gaps=${gaps}`
        );

        // Clear rolling windows for next interval
        this.diagnostics.stepTimes = [];
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
     * Broadcast P2P state sync message (symmetric, non-server-authoritative mode).
     * Both peers broadcast their state hash for mutual desync detection.
     */
    async broadcastSymmetricStateSync() {
        // Skip if state sync not supported (no get_state)
        if (!this.stateSyncSupported) {
            return;
        }

        try {
            const stateHash = await this.computeQuickStateHash();

            socket.emit('p2p_state_sync', {
                game_id: this.gameId,
                sender_id: this.myPlayerId,
                frame_number: this.frameNumber,
                state_hash: stateHash,
                action_counts: this.actionCounts
            });

            this.lastP2PSyncFrame = this.frameNumber;

            p2pLog.debug(`State sync broadcast: frame=${this.frameNumber} hash=${stateHash?.substring(0, 8)}`);
        } catch (e) {
            p2pLog.warn(`Failed to broadcast state hash: ${e}`);
        }
    }

    /**
     * Record state hash for a given frame number.
     * Called after each step to build history for frame-aligned comparison.
     * Runs asynchronously to avoid blocking the game loop.
     */
    async recordStateHashForFrame(frameNumber) {
        // Skip if state sync not supported (no get_state)
        if (!this.stateSyncSupported) {
            return;
        }

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
            p2pLog.warn(`Failed to record hash for frame ${frameNumber}: ${e}`);
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
         * JSON-serializable dict. Returns null if not supported.
         */
        // Return null if state sync not supported
        if (!this.stateSyncSupported) {
            return null;
        }

        const hashResult = await this.pyodide.runPythonAsync(`
import json
import hashlib

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
            p2pLog.warn(`applyServerState render failed: ${e}`);
        }

        const totalTime = performance.now() - applyTiming.start;

        p2pLog.debug(`applyServerState: ${totalTime.toFixed(1)}ms, frame ${oldFrame}→${this.frameNumber}`);

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
            p2pLog.debug(`Frame went backwards (${oldFrame}→${this.frameNumber}), clearing action queues`);
            for (const playerId in this.otherPlayerActionQueues) {
                this.otherPlayerActionQueues[playerId] = [];
            }
        }

        // Update HUD
        ui_utils.updateHUDText(this.getHUDText());
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

        // Compare action sequences to find divergence
        this.compareActionSequences(serverState);

        // CASE 1: Both hashes available and they MATCH - confirmed in sync
        if (clientHash && serverHash && clientHash === serverHash) {
            this.confirmedFrame = serverFrame;
            syncMetadata();
            p2pLog.debug(`Reconcile OK: frame=${serverFrame} hash=${serverHash.substring(0, 8)} drift=${drift}`);
            return false;
        }

        // CASE 2: Both hashes available but MISMATCH - proven divergence, must correct
        if (clientHash && serverHash && clientHash !== serverHash) {
            const framesToRollback = this.frameNumber - serverFrame;
            // DESYNC - always log this key event
            p2pLog.warn(
                `HASH MISMATCH: frame=${serverFrame} server=${serverHash.substring(0, 8)} ` +
                `client=${clientHash.substring(0, 8)} rollback=${framesToRollback}frames`
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

        // CASE 3: No client hash available for server's exact frame
        // This happens when:
        // - Client is behind server (drift < 0): hasn't reached that frame yet
        // - Client is ahead but hash was pruned: frame too old
        // - Hash history was recently cleared
        //
        // Since we can't verify sync, we should ALWAYS apply server state.
        // Silent divergence (where states differ but we don't correct) is worse
        // than occasional unnecessary corrections.
        //
        // The only exception: if we recently applied server state (confirmedFrame is close),
        // trust that we're still in sync.

        // CASE 3: No client hash available for server's exact frame
        // We can't verify sync directly. Since we can't compare hashes, apply server
        // state periodically to ensure we don't silently diverge.

        const framesSinceConfirmed = serverFrame - this.confirmedFrame;
        const FORCE_SYNC_INTERVAL = 90;  // Force sync every ~3 seconds at 30fps broadcast

        if (framesSinceConfirmed > FORCE_SYNC_INTERVAL) {
            p2pLog.debug(`No hash for frame ${serverFrame}, forcing sync (${framesSinceConfirmed} frames since confirmed)`);
            await this.applyServerState(serverState);
            this.confirmedFrame = serverFrame;
            this.stateHashHistory.clear();
            return true;
        }

        // Within tolerance - sync metadata only
        syncMetadata();
        return false;
    }

    /**
     * Compare client and server action sequences to identify where divergence occurs.
     * Logs detailed info about first mismatch found.
     */
    compareActionSequences(serverState) {
        if (!serverState.recent_actions || !serverState.recent_actions.length) {
            return;  // No action sequence from server
        }

        const serverActions = serverState.recent_actions;

        // Build client action map for quick lookup
        const clientActionMap = new Map();
        for (const record of this.actionSequence) {
            clientActionMap.set(record.frame, record.actions);
        }

        // Check for mismatches in overlapping frames
        let mismatchFound = false;
        let mismatchDetails = [];

        for (const serverRecord of serverActions) {
            const frame = serverRecord.frame;
            const clientActions = clientActionMap.get(frame);

            if (!clientActions) {
                // Client doesn't have this frame yet (normal if client is behind)
                continue;
            }

            // Compare actions for each player
            for (const [playerId, serverAction] of Object.entries(serverRecord.actions)) {
                const clientAction = clientActions[playerId];
                if (clientAction !== undefined && clientAction !== serverAction) {
                    mismatchFound = true;
                    mismatchDetails.push({
                        frame,
                        playerId,
                        server: serverAction,
                        client: clientAction
                    });
                }
            }
        }

        // ACTION MISMATCH - always log this key event (indicates desync)
        if (mismatchFound) {
            p2pLog.warn(`ACTION MISMATCH: ${mismatchDetails.length} mismatches detected`);
            // Log first mismatch detail for debugging
            const first = mismatchDetails[0];
            p2pLog.warn(`  First: frame=${first.frame} player=${first.playerId} server=${first.server} client=${first.client}`);
        }

        // Action count comparison - only warn if significant divergence
        if (serverState.action_counts) {
            for (const [playerId, serverCounts] of Object.entries(serverState.action_counts)) {
                const clientCounts = this.actionCounts[playerId] || {};
                for (const [action, serverCount] of Object.entries(serverCounts)) {
                    const clientCount = clientCounts[action] || 0;
                    if (Math.abs(serverCount - clientCount) > 5) {  // Only warn on significant divergence
                        p2pLog.warn(`ACTION COUNT DRIFT: player=${playerId} action=${action} server=${serverCount} client=${clientCount}`);
                    }
                }
            }
        }
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
            p2pLog.info(`Game complete (${this.num_episodes}/${this.max_episodes} episodes)`);
        } else {
            this.shouldReset = true;
            p2pLog.debug(`Episode ${this.num_episodes}/${this.max_episodes} complete, will reset`);
        }
    }

    _logEpisodeEndMetrics() {
        /**
         * Log episode end metrics. Called when episode end is first detected,
         * before P2P synchronization completes.
         */
        // Calculate P2P receive ratio
        const totalReceived = this.p2pMetrics.inputsReceivedViaP2P + this.p2pMetrics.inputsReceivedViaSocketIO;
        const p2pReceiveRatio = totalReceived > 0
            ? (this.p2pMetrics.inputsReceivedViaP2P / totalReceived * 100).toFixed(1)
            : 'N/A';
        const p2pType = this.p2pMetrics.connectionType || 'unknown';

        // Log episode summary - always show this key event
        p2pLog.info(
            `EPISODE END: frame=${this.frameNumber} ` +
            `rollbacks=${this.rollbackCount}/${this.sessionMetrics.rollbacks.maxFrames}max ` +
            `p2p=${p2pReceiveRatio}% ` +
            `type=${p2pType}` +
            (this.p2pMetrics.p2pFallbackTriggered ? ` fallback@${this.p2pMetrics.p2pFallbackFrame}` : '')
        );

        // Full session metrics only in debug mode
        if (getLogLevel() >= LOG_LEVELS.debug) {
            const sessionMetrics = this.exportSessionMetrics();
            p2pLog.debug('Session metrics:', JSON.stringify(sessionMetrics, null, 2));
        }
    }

    // ========== P2P State Resync Methods ==========

    /**
     * Determine if we should request state from peer on desync.
     * Uses deterministic tie-breaker: lower player ID defers to higher.
     * This ensures only one peer requests state, not both.
     */
    _shouldRequestStateResync(peerId) {
        // Compare as strings to handle both numeric and string IDs
        const myId = String(this.myPlayerId);
        const theirId = String(peerId);
        // Lower ID defers to higher ID (requests state from them)
        return myId < theirId;
    }

    /**
     * Apply state received from peer during P2P resync.
     * Similar to applyServerState but for peer-to-peer sync.
     */
    async _applyP2PState(envState, frameNumber, stepNum, cumulativeRewards) {
        // P2P RESYNC - key event, always log at info level
        p2pLog.info(`P2P RESYNC: applying peer state frame=${frameNumber} step=${stepNum}`);

        // Apply environment state via set_state
        const envStateJson = JSON.stringify(envState);
        await this.pyodide.runPythonAsync(`
import json

env_state = json.loads('''${envStateJson.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}''')
env.set_state(env_state)
        `);

        // Sync JavaScript-side state
        this.frameNumber = frameNumber;
        this.step_num = stepNum;
        if (cumulativeRewards) {
            this.cumulative_rewards = cumulativeRewards;
        }

        // Clear GGPO state since we're now in sync
        this.clearGGPOState();

        // Update HUD
        ui_utils.updateHUDText(this.getHUDText());

        p2pLog.debug(`P2P resync complete, now at frame ${this.frameNumber}`);
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
        // NOTE: Use >= for late detection because frameNumber == this.frameNumber means we're
        // about to step that frame but haven't yet, so it's not late
        if (frameNumber < this.frameNumber && this.predictedFrames.has(frameNumber)) {
            // Late input! Check what action we ACTUALLY used at that frame
            // by looking at actionSequence, not by calling getPredictedAction()
            const actionRecord = this.actionSequence.find(r => r.frame === frameNumber);
            if (actionRecord) {
                const usedAction = actionRecord.actions[playerIdStr] ?? actionRecord.actions[parseInt(playerIdStr)];
                if (usedAction !== undefined && usedAction !== action) {
                    const rollbackFrames = this.frameNumber - frameNumber;

                    // Record rollback event for research analytics
                    const rollbackEvent = {
                        frame: frameNumber,
                        currentFrame: this.frameNumber,
                        rollbackFrames: rollbackFrames,
                        playerId: playerIdStr,
                        predictedAction: usedAction,
                        actualAction: action,
                        timestamp: Date.now()
                    };

                    // Track in session metrics for export
                    this.sessionMetrics.rollbacks.events.push(rollbackEvent);
                    this.sessionMetrics.rollbacks.count++;
                    this.sessionMetrics.rollbacks.maxFrames = Math.max(
                        this.sessionMetrics.rollbacks.maxFrames,
                        rollbackFrames
                    );

                    // ROLLBACK - always log this key event
                    p2pLog.info(
                        `ROLLBACK: player=${playerIdStr} frame=${frameNumber} depth=${rollbackFrames} ` +
                        `(predicted=${usedAction} actual=${action})`
                    );

                    // Mark for rollback - will be processed in next step()
                    this.pendingRollbackFrame = Math.min(
                        this.pendingRollbackFrame ?? frameNumber,
                        frameNumber
                    );
                }
            } else {
                // No record found - shouldn't happen but trigger rollback to be safe
                p2pLog.warn(`Late input at frame ${frameNumber} but no action record - triggering rollback`);
                this.pendingRollbackFrame = Math.min(
                    this.pendingRollbackFrame ?? frameNumber,
                    frameNumber
                );
            }
        }

        // NOTE: Don't prune here - let step() handle pruning to avoid removing inputs
        // needed for pending rollbacks
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
     * Get predicted action for a player when no confirmed input is available.
     * Uses configurable action_population_method:
     * - 'previous_submitted_action': Use player's last confirmed action
     * - 'default': Use the configured default action
     */
    getPredictedAction(playerId, frameNumber) {
        const playerIdStr = String(playerId);

        if (this.actionPopulationMethod === 'previous_submitted_action') {
            // Use last confirmed action from this player
            return this.lastConfirmedActions[playerIdStr] ?? this.defaultAction;
        } else {
            // Use configured default action
            return this.defaultAction;
        }
    }

    /**
     * Get inputs for a specific frame (pure GGPO).
     * Returns {playerId: action} dict with confirmed inputs where available,
     * predictions where not.
     *
     * GGPO requires EXACT frame matching:
     * - If we have input for exact frame N, use it
     * - Otherwise, use PREDICTION (based on actionPopulationMethod)
     * - Mark the frame as "predicted" so we know to check it when real input arrives
     *
     * This ensures both clients use the same logic: either the confirmed input
     * for that exact frame, or the same prediction algorithm.
     *
     * @param trackPredictions - If true, track predicted frames for rollback detection.
     *                           Set to false during replay to avoid re-marking frames.
     */
    getInputsForFrame(frameNumber, playerIds, trackPredictions = true) {
        const inputs = {};
        let usedPrediction = false;

        for (const playerId of playerIds) {
            const playerIdStr = String(playerId);

            // Check for EXACT frame match only (pure GGPO)
            const frameInputs = this.inputBuffer.get(frameNumber);
            if (frameInputs && frameInputs.has(playerIdStr)) {
                // Have confirmed input for this exact frame
                inputs[playerIdStr] = frameInputs.get(playerIdStr);
                // Update lastConfirmedActions for future predictions
                this.lastConfirmedActions[playerIdStr] = inputs[playerIdStr];
            } else {
                // No input for this exact frame - use prediction
                // This is the key GGPO behavior: predict, then rollback if wrong
                inputs[playerIdStr] = this.getPredictedAction(playerIdStr, frameNumber);
                usedPrediction = true;
            }
        }

        // Track that we used prediction for this frame (for rollback detection)
        // Only track during normal stepping, not during replay
        if (usedPrediction && trackPredictions) {
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
     * Includes environment state AND RNG state for deterministic replay.
     */
    async saveStateSnapshot(frameNumber) {
        // Skip if state sync not supported (env doesn't have get_state/set_state)
        if (!this.stateSyncSupported) {
            return;
        }

        try {
            // Capture both environment state and RNG state
            const stateJson = await this.pyodide.runPythonAsync(`
import json
import numpy as np
import random

# Get environment state
_env_state = env.get_state()

# Capture numpy RNG state (convert to list for JSON serialization)
_np_rng_state = np.random.get_state()
_np_rng_serializable = (
    _np_rng_state[0],  # 'MT19937'
    _np_rng_state[1].tolist(),  # state array as list
    _np_rng_state[2],  # pos
    _np_rng_state[3],  # has_gauss
    _np_rng_state[4]   # cached_gaussian
)

# Capture Python random state
_py_rng_state = random.getstate()

# Combine into snapshot
_snapshot = {
    'env_state': _env_state,
    'np_rng_state': _np_rng_serializable,
    'py_rng_state': _py_rng_state
}

json.dumps(_snapshot)
            `);
            this.stateSnapshots.set(frameNumber, stateJson);

            // Debug: log snapshot saves periodically
            if (this.stateSnapshots.size % 10 === 0) {
                p2pLog.debug(`Snapshot saved: frame=${frameNumber}, total=${this.stateSnapshots.size}`);
            }

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
            p2pLog.warn(`Failed to save snapshot at frame ${frameNumber}: ${e}`);
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
     * Restores both environment state and RNG state for deterministic replay.
     */
    async loadStateSnapshot(frameNumber) {
        const stateJson = this.stateSnapshots.get(frameNumber);
        if (!stateJson) {
            p2pLog.error(`No snapshot found for frame ${frameNumber}`);
            return false;
        }

        try {
            // Escape the JSON string for embedding in Python code
            const escapedJson = stateJson.replace(/\\/g, '\\\\').replace(/'/g, "\\'");

            await this.pyodide.runPythonAsync(`
import json
import numpy as np
import random

_snapshot = json.loads('''${escapedJson}''')

# Restore environment state
env.set_state(_snapshot['env_state'])

# Restore numpy RNG state
if 'np_rng_state' in _snapshot:
    _np_state = _snapshot['np_rng_state']
    # Convert list back to numpy array for the state
    _np_rng_tuple = (
        _np_state[0],  # 'MT19937'
        np.array(_np_state[1], dtype=np.uint32),  # state array
        _np_state[2],  # pos
        _np_state[3],  # has_gauss
        _np_state[4]   # cached_gaussian
    )
    np.random.set_state(_np_rng_tuple)

# Restore Python random state
if 'py_rng_state' in _snapshot:
    # Convert lists back to tuples as needed by setstate
    _py_state = _snapshot['py_rng_state']
    if isinstance(_py_state, list):
        _py_state = (
            _py_state[0],
            tuple(_py_state[1]),
            _py_state[2] if len(_py_state) > 2 else None
        )
    random.setstate(_py_state)
            `);
            return true;
        } catch (e) {
            p2pLog.error(`Failed to load snapshot for frame ${frameNumber}: ${e}`);
            return false;
        }
    }

    /**
     * Perform rollback to a target frame and replay forward.
     * This is the core GGPO operation.
     *
     * Key insight: The late input that triggered the rollback is now in inputBuffer.
     * So when we replay, getInputsForFrame will use the confirmed (correct) inputs.
     *
     * For bot actions: We use the recorded actions from actionSequence since bots
     * need to produce the same actions they did originally.
     * TODO: For full determinism, bot actions should be re-computed with correct RNG state.
     */
    async performRollback(targetFrame, playerIds) {
        const currentFrame = this.frameNumber;
        const rollbackFrames = currentFrame - targetFrame;

        p2pLog.debug(`Performing rollback: ${currentFrame} → ${targetFrame} (${rollbackFrames} frames)`);

        // Skip rollback if state sync not supported - can't restore state
        if (!this.stateSyncSupported) {
            p2pLog.warn(`Cannot rollback - state sync not supported (env missing get_state/set_state)`);
            return false;
        }

        this.rollbackCount++;
        this.maxRollbackFrames = Math.max(this.maxRollbackFrames, rollbackFrames);

        // Find best snapshot to restore (snapshot[N] = state BEFORE stepping frame N)
        const snapshotFrame = this.findBestSnapshot(targetFrame);
        if (snapshotFrame < 0) {
            p2pLog.error(
                `No valid snapshot found for rollback to frame ${targetFrame}. ` +
                `Snapshots available: ${this.stateSnapshots.size}, ` +
                `keys: [${Array.from(this.stateSnapshots.keys()).slice(-5).join(', ')}...]`
            );
            return false;
        }

        // Load snapshot - this restores state BEFORE snapshotFrame was stepped
        const loaded = await this.loadStateSnapshot(snapshotFrame);
        if (!loaded) {
            return false;
        }

        p2pLog.debug(`Loaded snapshot ${snapshotFrame}, replaying ${currentFrame - snapshotFrame} frames`);

        // Build a map of recorded actions for quick lookup (these are actions that were USED, possibly predicted)
        const recordedActionsMap = new Map();
        for (const record of this.actionSequence) {
            recordedActionsMap.set(record.frame, record.actions);
        }

        // Replay from snapshot frame to current frame
        this.frameNumber = snapshotFrame;

        // Clear predicted frames from snapshot onwards (we'll re-simulate with correct inputs)
        for (const frame of this.predictedFrames) {
            if (frame >= snapshotFrame) {
                this.predictedFrames.delete(frame);
            }
        }

        // Recompute action counts from snapshotFrame onwards
        // First, subtract the old counts for frames we're re-doing
        for (const record of this.actionSequence) {
            if (record.frame >= snapshotFrame) {
                for (const [playerId, action] of Object.entries(record.actions)) {
                    const actionKey = String(action);
                    if (this.actionCounts[playerId] && this.actionCounts[playerId][actionKey]) {
                        this.actionCounts[playerId][actionKey]--;
                        if (this.actionCounts[playerId][actionKey] <= 0) {
                            delete this.actionCounts[playerId][actionKey];
                        }
                    }
                }
            }
        }

        // Also remove old action records from snapshotFrame onwards (we'll record new ones)
        this.actionSequence = this.actionSequence.filter(r => r.frame < snapshotFrame);

        // Replay each frame
        for (let frame = snapshotFrame; frame < currentFrame; frame++) {
            // Get human inputs from buffer (now has confirmed inputs including the late one)
            // Note: getInputsForFrame may still use prediction if inputs haven't arrived yet
            // Pass trackPredictions=false during replay to avoid re-marking frames
            const humanInputs = this.getInputsForFrame(frame, playerIds, false);

            // Log what inputs we're using during replay
            const confirmedForFrame = [];
            const predictedForFrame = [];
            const frameInputs = this.inputBuffer.get(frame);
            for (const pid of playerIds) {
                if (frameInputs && frameInputs.has(String(pid))) {
                    confirmedForFrame.push(pid);
                } else {
                    predictedForFrame.push(pid);
                }
            }

            // Warn if we're still using prediction during replay - this means inputs are missing!
            // This is expected with artificial delay - we'll rollback again when those inputs arrive
            if (predictedForFrame.length > 0) {
                p2pLog.debug(`Replay frame ${frame}: still missing inputs for [${predictedForFrame.join(',')}]`);
            }

            // Build complete action dict
            const envActions = {};

            // Add human actions from confirmed inputs
            for (const [pid, action] of Object.entries(humanInputs)) {
                envActions[parseInt(pid) || pid] = action;
            }

            // For non-human agents, use recorded actions from original execution
            // TODO: Ideally re-compute with correct RNG state for full determinism
            const originalActions = recordedActionsMap.get(frame);
            if (originalActions) {
                for (const [agentId, policy] of Object.entries(this.policyMapping)) {
                    if (policy !== 'human') {
                        const agentIdKey = parseInt(agentId) || agentId;
                        if (originalActions[agentId] !== undefined) {
                            envActions[agentIdKey] = originalActions[agentId];
                        } else if (originalActions[String(agentId)] !== undefined) {
                            envActions[agentIdKey] = originalActions[String(agentId)];
                        }
                    }
                }
            }

            // Record the corrected actions
            this.actionSequence.push({
                frame: frame,
                actions: {...envActions}
            });

            // Update action counts with corrected actions
            for (const [playerId, action] of Object.entries(envActions)) {
                if (!this.actionCounts[playerId]) {
                    this.actionCounts[playerId] = {};
                }
                const actionKey = String(action);
                this.actionCounts[playerId][actionKey] = (this.actionCounts[playerId][actionKey] || 0) + 1;
            }

            // Step environment
            await this.pyodide.runPythonAsync(`
_replay_actions = ${JSON.stringify(envActions)}
_replay_actions = {int(k) if str(k).isdigit() else k: v for k, v in _replay_actions.items()}
env.step(_replay_actions)
            `);

            this.frameNumber = frame + 1;
        }

        p2pLog.debug(`Replay complete, now at frame ${this.frameNumber}`);
        return true;
    }

    /**
     * Process any delayed inputs that are ready.
     * Used for debug testing of rollback behavior.
     */
    processDelayedInputs() {
        // Check for debug delay setting from window (allows runtime adjustment)
        if (typeof window !== 'undefined' && window.debugRemoteInputDelay !== undefined) {
            this.debugRemoteInputDelay = window.debugRemoteInputDelay;
        }

        // Process any delayed inputs that are now ready
        const ready = [];
        const stillWaiting = [];

        for (const item of this.debugDelayedInputQueue) {
            if (this.frameNumber >= item.processAtFrame) {
                ready.push(item);
            } else {
                stillWaiting.push(item);
            }
        }

        this.debugDelayedInputQueue = stillWaiting;

        // Actually store the delayed inputs now
        for (const item of ready) {
            p2pLog.debug(`[DEBUG-DELAY] Processing: player=${item.playerId} frame=${item.frameNumber} late_by=${this.frameNumber - item.frameNumber}`);
            this.storeRemoteInput(item.playerId, item.action, item.frameNumber);
        }
    }

    /**
     * Queue a remote input for delayed processing (debug feature).
     * If debugRemoteInputDelay > 0, input is held before being stored.
     */
    queueRemoteInputWithDelay(playerId, action, frameNumber) {
        // Check for debug delay setting from window
        if (typeof window !== 'undefined' && window.debugRemoteInputDelay !== undefined) {
            this.debugRemoteInputDelay = window.debugRemoteInputDelay;
        }

        if (this.debugRemoteInputDelay > 0) {
            const processAtFrame = this.frameNumber + this.debugRemoteInputDelay;
            this.debugDelayedInputQueue.push({
                playerId,
                action,
                frameNumber,
                processAtFrame
            });
            // Debug delay logging - only in debug mode
            p2pLog.debug(`[DEBUG-DELAY] Queued: player=${playerId} frame=${frameNumber} process_at=${processAtFrame}`);
        } else {
            // No delay - process immediately
            this.storeRemoteInput(playerId, action, frameNumber);
        }
    }

    /**
     * Prune old entries from input buffer.
     * Removes frames we've already passed to prevent unbounded growth.
     */
    pruneInputBuffer() {
        // Remove entries for frames we've already simulated
        // Keep a larger buffer behind for potential rollback (must be >= maxSnapshots * snapshotInterval)
        // With snapshotInterval=5 and maxSnapshots=30, we need at least 150 frames of buffer
        const pruneThreshold = this.frameNumber - 60;  // Keep ~2 seconds at 30 FPS
        const keysToDelete = [];

        for (const key of this.inputBuffer.keys()) {
            if (key < pruneThreshold) {
                keysToDelete.push(key);
            }
        }

        for (const key of keysToDelete) {
            this.inputBuffer.delete(key);
            this.predictedFrames.delete(key);
        }

        // Also enforce max size limit
        if (this.inputBuffer.size > this.inputBufferMaxSize) {
            const sortedKeys = Array.from(this.inputBuffer.keys()).sort((a, b) => a - b);
            const toRemove = sortedKeys.slice(0, this.inputBuffer.size - this.inputBufferMaxSize);
            for (const key of toRemove) {
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

        // Clear debug delayed input queue
        this.debugDelayedInputQueue = [];

        // NOTE: Do NOT close WebRTC connection here - it persists across episodes
        // WebRTC is only closed when the game session ends (in destroy/cleanup)

        // Reset P2P input sender for new episode
        if (this.p2pInputSender) {
            this.p2pInputSender.reset();
        }

        p2pLog.debug('GGPO state cleared for new episode');
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

    // ========== P2P WebRTC Methods ==========

    _initP2PConnection() {
        /**
         * Initialize WebRTC P2P connection to peer.
         * Called after pyodide_game_ready when we know the other player's ID.
         */
        p2pLog.debug(`Initiating connection to peer ${this.p2pPeerId}`);

        // Build WebRTC options with TURN config if available
        const webrtcOptions = {};
        if (this.turnConfig) {
            webrtcOptions.turnUsername = this.turnConfig.username;
            webrtcOptions.turnCredential = this.turnConfig.credential;
            webrtcOptions.forceRelay = this.turnConfig.force_relay || false;
            p2pLog.debug('Using TURN configuration');
        }

        this.webrtcManager = new WebRTCManager(socket, this.gameId, this.myPlayerId, webrtcOptions);

        // Set up callbacks
        this.webrtcManager.onDataChannelOpen = () => {
            p2pLog.info('DataChannel OPEN - P2P connection established');
            this.p2pConnected = true;

            // Initialize P2P input sending (use numeric index for binary protocol)
            const myPlayerIndex = this.playerIdToIndex[this.myPlayerId];
            this.p2pInputSender = new P2PInputSender(
                this.webrtcManager,
                myPlayerIndex,
                3  // redundancy count
            );

            // Initialize connection health monitoring
            this.connectionHealth = new ConnectionHealthMonitor();

            // Start periodic ping for RTT measurement
            this._startPingInterval();

            // Send a test message to verify connection
            this._sendP2PTestMessage();

            // Resolve P2P ready gate - game can now start with P2P
            this._resolveP2PReadyGate();
        };

        this.webrtcManager.onDataChannelMessage = (data) => {
            this._handleP2PMessage(data);
        };

        this.webrtcManager.onDataChannelClose = () => {
            p2pLog.warn('DataChannel CLOSED');
            this.p2pConnected = false;
            this._stopPingInterval();

            // Track fallback when DataChannel closes
            if (!this.p2pMetrics.p2pFallbackTriggered) {
                this.p2pMetrics.p2pFallbackTriggered = true;
                this.p2pMetrics.p2pFallbackFrame = this.frameNumber;
                p2pLog.warn(`Fallback to SocketIO at frame ${this.frameNumber}`);
            }
        };

        this.webrtcManager.onConnectionFailed = () => {
            p2pLog.error('Connection FAILED');
            this.p2pConnected = false;
            this._stopPingInterval();

            // Track fallback when connection fails
            if (!this.p2pMetrics.p2pFallbackTriggered) {
                this.p2pMetrics.p2pFallbackTriggered = true;
                this.p2pMetrics.p2pFallbackFrame = this.frameNumber;
                p2pLog.warn(`Fallback to SocketIO at frame ${this.frameNumber}`);
            }
        };

        // Connection type detection callback
        this.webrtcManager.onConnectionTypeDetected = (connInfo) => {
            this._logConnectionType(connInfo);
        };

        // Quality degradation callback
        this.webrtcManager.onQualityDegraded = (info) => {
            p2pLog.warn('Quality degraded:', info.reason);
        };

        // Start the connection (role determined by player ID comparison)
        this.webrtcManager.connectToPeer(this.p2pPeerId);
    }

    /**
     * Log connection type for research analytics.
     * @param {Object} connInfo - Connection type info from WebRTCManager
     */
    _logConnectionType(connInfo) {
        p2pLog.info(`Connection type: ${connInfo.connectionType} (${connInfo.localCandidateType}/${connInfo.remoteCandidateType})`);

        // Store in p2pMetrics for episode summary
        this.p2pMetrics.connectionType = connInfo.connectionType;
        this.p2pMetrics.connectionDetails = {
            localCandidateType: connInfo.localCandidateType,
            remoteCandidateType: connInfo.remoteCandidateType,
            protocol: connInfo.localProtocol || connInfo.protocol,
            relayProtocol: connInfo.relayProtocol,
            detectedAtFrame: this.frameNumber,
            timestamp: Date.now()
        };

        // Emit to server for research data persistence
        socket.emit('p2p_connection_type', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            connection_type: connInfo.connectionType,
            details: this.p2pMetrics.connectionDetails
        });
    }

    /**
     * Resolve the P2P ready gate, allowing the game to start.
     * Called when P2P connection is established or timeout occurs.
     */
    _resolveP2PReadyGate() {
        if (this.p2pReadyGate.resolved) {
            return;  // Already resolved
        }

        this.p2pReadyGate.resolved = true;

        // Clear timeout if still pending
        if (this.p2pReadyGate.timeoutId) {
            clearTimeout(this.p2pReadyGate.timeoutId);
            this.p2pReadyGate.timeoutId = null;
        }

        const status = this.p2pConnected ? 'P2P ready' : 'SocketIO fallback';
        p2pLog.info(`P2P ready gate resolved: ${status}`);
    }

    /**
     * Check if the game is ready to start (P2P established or gate disabled/timeout).
     * Used by the game loop to wait for P2P before processing frames.
     */
    isP2PReady() {
        // If gate is disabled, always ready
        if (!this.p2pReadyGate.enabled) {
            return true;
        }
        return this.p2pReadyGate.resolved;
    }

    /**
     * Send input to other players via SocketIO (fallback path).
     * @param {number} action - The action taken
     * @param {number} targetFrame - The frame this input is scheduled for
     */
    _sendViaSocketIO(action, targetFrame) {
        socket.emit('pyodide_player_action', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            action: action,
            frame_number: targetFrame,
            timestamp: Date.now(),
            sync_epoch: this.syncEpoch
        });
        this.p2pMetrics.inputsSentViaSocketIO++;
    }

    _sendP2PTestMessage() {
        /**
         * Send a test message over the P2P DataChannel to verify connectivity.
         */
        const testMessage = {
            type: 'test',
            from: this.myPlayerId,
            timestamp: Date.now()
        };

        this.webrtcManager.send(JSON.stringify(testMessage));
    }

    _handleP2PMessage(data) {
        /**
         * Handle incoming P2P DataChannel messages.
         * Routes to appropriate handler based on message type.
         */

        // Handle ArrayBuffer (binary protocol)
        if (data instanceof ArrayBuffer) {
            this._handleBinaryMessage(data);
            return;
        }

        // Handle string (JSON - legacy test messages)
        if (typeof data === 'string') {
            try {
                const message = JSON.parse(data);
                this._handleJsonMessage(message);
            } catch (e) {
                p2pLog.error('Failed to parse JSON message:', e);
            }
            return;
        }

        p2pLog.warn('Unknown message data type:', typeof data);
    }

    _handleBinaryMessage(buffer) {
        /**
         * Route binary messages by type byte.
         */
        const messageType = getMessageType(buffer);

        switch (messageType) {
            case P2P_MSG_INPUT:
                this._handleInputPacket(buffer);
                break;
            case P2P_MSG_PING:
                this._handlePing(buffer);
                break;
            case P2P_MSG_PONG:
                this._handlePong(buffer);
                break;
            case P2P_MSG_KEEPALIVE:
                // Just receiving it confirms connection is alive
                break;
            case P2P_MSG_EPISODE_END:
                this._handleEpisodeEnd(buffer);
                break;
            default:
                p2pLog.warn(`Unknown binary message type: ${messageType}`);
        }
    }

    _handleJsonMessage(message) {
        /**
         * Handle JSON messages (test messages from Phase 1).
         */
        if (message.type === 'test') {
            const latency = Date.now() - message.timestamp;
            p2pLog.debug(`Test message from player ${message.from}, latency: ${latency}ms`);
        } else {
            p2pLog.debug(`JSON message type: ${message.type}`);
        }
    }

    _handleInputPacket(buffer) {
        /**
         * GGPO-style: Queue received input packet for synchronous processing at frame start.
         * This prevents race conditions where inputs arrive during rollback replay.
         */
        const packet = decodeInputPacket(buffer);
        if (!packet) {
            p2pLog.warn('Failed to decode input packet');
            return;
        }

        // Convert numeric player index back to player ID
        const playerId = this.indexToPlayerId[packet.playerId];
        if (playerId === undefined) {
            p2pLog.warn(`Unknown player index: ${packet.playerId}`);
            return;
        }

        // Queue the decoded packet for synchronous processing at frame start
        // Processing happens in _processQueuedInputs() called from step()
        this.pendingInputPackets.push({
            playerId: playerId,
            inputs: packet.inputs,
            currentFrame: packet.currentFrame
        });

        // Track P2P input reception for metrics
        this.p2pMetrics.inputsReceivedViaP2P++;

        // Update connection health monitor
        if (this.connectionHealth) {
            this.connectionHealth.recordReceivedInput(packet.currentFrame);
        }
    }

    /**
     * GGPO-style: Process all queued inputs synchronously at frame start.
     * This is called from step() BEFORE checking for rollbacks, ensuring
     * inputs don't arrive during rollback replay.
     *
     * Key insight: By draining all queues at once at a known point in the
     * game loop, we eliminate race conditions where async network events
     * could fire during await calls in rollback replay.
     */
    _processQueuedInputs() {
        // Don't process inputs during rollback - they stay queued
        if (this.rollbackInProgress) {
            return;
        }

        // Drain P2P input packets
        const p2pPackets = this.pendingInputPackets;
        this.pendingInputPackets = [];

        for (const packet of p2pPackets) {
            // Each packet contains multiple inputs (redundancy)
            // Handles redundancy - duplicates are ignored by storeRemoteInput
            for (const input of packet.inputs) {
                this.queueRemoteInputWithDelay(packet.playerId, input.action, input.frame);
            }
        }

        // Drain SocketIO inputs
        const socketInputs = this.pendingSocketIOInputs;
        this.pendingSocketIOInputs = [];

        for (const input of socketInputs) {
            this.queueRemoteInputWithDelay(input.playerId, input.action, input.frameNumber);
        }
    }

    _handlePing(buffer) {
        /**
         * Respond to ping with pong (echo timestamp back).
         */
        const view = new DataView(buffer);
        const timestamp = view.getFloat64(1, false);

        // Echo back as pong
        const pong = encodePong(timestamp);
        if (this.webrtcManager?.isReady()) {
            this.webrtcManager.send(pong);
        }
    }

    _handlePong(buffer) {
        /**
         * Process pong response and update RTT tracking.
         */
        const view = new DataView(buffer);
        const sentTime = view.getFloat64(1, false);

        // Record RTT sample
        if (this.connectionHealth) {
            this.connectionHealth.rttTracker.recordRTT(sentTime);
        }
    }

    _handleEpisodeEnd(buffer) {
        /**
         * Handle episode end notification from peer.
         * In P2P mode, both peers must agree on episode end before resetting.
         * This prevents desync when one client detects episode end slightly before the other.
         */
        const packet = decodeEpisodeEnd(buffer);
        if (!packet) {
            p2pLog.warn('Failed to decode episode end packet');
            return;
        }

        p2pLog.debug(`Received episode end from peer: frame=${packet.frameNumber}`);

        // Record that we received peer's episode end notification
        this.p2pEpisodeSync.remoteEpisodeEndReceived = true;
        this.p2pEpisodeSync.remoteEpisodeEndFrame = packet.frameNumber;

        // Check if we can now trigger the synchronized reset
        this._checkEpisodeSyncAndReset();
    }

    _broadcastEpisodeEnd() {
        /**
         * Send episode end notification to peer.
         * Called when we detect episode end locally (environment terminated/truncated).
         */
        if (!this.webrtcManager?.isReady()) {
            p2pLog.debug('Cannot broadcast episode end - WebRTC not ready');
            return;
        }

        const packet = encodeEpisodeEnd(this.frameNumber, this.num_episodes);
        this.webrtcManager.send(packet);
        p2pLog.debug(`Broadcast episode end: frame=${this.frameNumber}`);

        // Record that we detected episode end locally
        this.p2pEpisodeSync.localEpisodeEndDetected = true;
        this.p2pEpisodeSync.localEpisodeEndFrame = this.frameNumber;
        this.p2pEpisodeSync.pendingReset = true;

        // Start timeout in case peer message is lost (2 seconds)
        // If we don't hear from peer, proceed with reset anyway
        this.p2pEpisodeSync.syncTimeoutId = setTimeout(() => {
            if (this.p2pEpisodeSync.pendingReset && !this.p2pEpisodeSync.remoteEpisodeEndReceived) {
                p2pLog.warn('Episode sync timeout - proceeding with reset');
                this._clearEpisodeSyncState();
                this.episodeComplete = true;
                this.signalEpisodeComplete();
            }
        }, 2000);

        // Check if peer already sent their notification
        this._checkEpisodeSyncAndReset();
    }

    _checkEpisodeSyncAndReset() {
        /**
         * Check if both peers have detected episode end and trigger synchronized reset.
         * This is called:
         * 1. When we detect episode end locally (after broadcasting)
         * 2. When we receive episode end from peer
         */
        const sync = this.p2pEpisodeSync;

        // Both peers must agree before we can reset
        if (!sync.localEpisodeEndDetected || !sync.remoteEpisodeEndReceived) {
            return;  // Still waiting for sync
        }

        // Both peers agree - frames may differ slightly due to network timing, that's OK
        const frameDiff = Math.abs((sync.localEpisodeEndFrame || 0) - (sync.remoteEpisodeEndFrame || 0));
        if (frameDiff > 5) {
            p2pLog.warn(`Large frame difference at episode end: ${frameDiff} frames`);
        }

        // Clear sync state for next episode
        this._clearEpisodeSyncState();

        // Now safe to signal episode complete (which triggers shouldReset)
        this.episodeComplete = true;
        this.signalEpisodeComplete();
    }

    _clearEpisodeSyncState() {
        /**
         * Reset episode sync state for the next episode.
         */
        // Clear timeout if it exists
        if (this.p2pEpisodeSync.syncTimeoutId) {
            clearTimeout(this.p2pEpisodeSync.syncTimeoutId);
        }
        this.p2pEpisodeSync.localEpisodeEndDetected = false;
        this.p2pEpisodeSync.localEpisodeEndFrame = null;
        this.p2pEpisodeSync.remoteEpisodeEndReceived = false;
        this.p2pEpisodeSync.remoteEpisodeEndFrame = null;
        this.p2pEpisodeSync.pendingReset = false;
        this.p2pEpisodeSync.syncTimeoutId = null;
    }

    _startPingInterval() {
        /**
         * Start periodic ping for RTT measurement.
         * Pings every 500ms while P2P connection is active.
         */
        if (this.pingIntervalId) {
            clearInterval(this.pingIntervalId);
        }

        this.pingIntervalId = setInterval(() => {
            if (this.webrtcManager?.isReady() && this.connectionHealth) {
                const ping = encodePing();
                this.webrtcManager.send(ping);
                this.connectionHealth.rttTracker.lastPingTime = performance.now();
            }
        }, 500);  // Every 500ms

        p2pLog.debug('Started ping interval');
    }

    _stopPingInterval() {
        /**
         * Stop the ping interval.
         */
        if (this.pingIntervalId) {
            clearInterval(this.pingIntervalId);
            this.pingIntervalId = null;
            p2pLog.debug('Stopped ping interval');
        }
    }

    /**
     * Export session metrics for research data analysis.
     * Call at episode end to get structured metrics for persistence.
     * @returns {Object} Session metrics including connection info, inputs, rollbacks, etc.
     */
    exportSessionMetrics() {
        return {
            gameId: this.gameId,
            playerId: this.myPlayerId,

            connection: {
                type: this.p2pMetrics.connectionType || 'unknown',
                connectionDetails: this.p2pMetrics.connectionDetails || {}
            },

            inputs: {
                sentViaP2P: this.p2pMetrics.inputsSentViaP2P,
                sentViaSocketIO: this.p2pMetrics.inputsSentViaSocketIO,
                receivedViaP2P: this.p2pMetrics.inputsReceivedViaP2P,
                receivedViaSocketIO: this.p2pMetrics.inputsReceivedViaSocketIO
            },

            rollbacks: this.sessionMetrics.rollbacks,

            sync: {
                p2pHashMismatches: this.p2pHashMismatches || 0
            },

            quality: {
                p2pFallbackTriggered: this.p2pMetrics.p2pFallbackTriggered,
                p2pFallbackFrame: this.p2pMetrics.p2pFallbackFrame
            },

            frames: {
                total: this.frameNumber
            }
        };
    }

    /**
     * Check P2P connection health and trigger fallback awareness if degraded.
     * Note: Actual fallback is implicit (SocketIO always active), this just tracks state.
     */
    _checkP2PHealth() {
        if (!this.connectionHealth || !this.p2pConnected) {
            return;
        }

        const health = this.connectionHealth.getHealthStatus();

        // Criteria for degraded P2P (fallback recommended)
        const isDegraded =
            health.status === 'critical' ||
            (health.latency && health.latency > 300);

        if (isDegraded && !this.p2pMetrics.p2pFallbackTriggered) {
            this.p2pMetrics.p2pFallbackTriggered = true;
            this.p2pMetrics.p2pFallbackFrame = this.frameNumber;
            // P2P FALLBACK - key event, always log
            p2pLog.warn(
                `FALLBACK: P2P degraded at frame=${this.frameNumber} ` +
                `latency=${health.latency?.toFixed(1) ?? 'N/A'}ms status=${health.status}`
            );
        }
    }
}
