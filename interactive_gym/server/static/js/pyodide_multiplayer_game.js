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
import { WebRTCManager, LatencyTelemetry } from './webrtc_manager.js';
import { ContinuousMonitor } from './continuous_monitor.js';
import { clearHumanInputBuffers } from './phaser_gym_graphics.js';

// ========== Logging Configuration ==========
// Control verbosity via browser console: window.p2pLogLevel = 'info' or 'debug'
// Levels: 'error' (critical only), 'warn' (+ important events), 'info' (+ status), 'debug' (+ verbose)
const LOG_LEVELS = { error: 0, warn: 1, info: 2, debug: 3 };

function getLogLevel() {
    if (typeof window !== 'undefined' && window.p2pLogLevel) {
        return LOG_LEVELS[window.p2pLogLevel] ?? LOG_LEVELS.warn;
    }
    return LOG_LEVELS.warn;  // Default: only important events (rollbacks, episodes, errors)
}

// Logging helpers - use these instead of console.log directly
const p2pLog = {
    error: (...args) => console.error('[P2P]', ...args),
    warn: (...args) => { if (getLogLevel() >= LOG_LEVELS.warn) console.warn('[P2P]', ...args); },
    info: (...args) => { if (getLogLevel() >= LOG_LEVELS.info) console.log('[P2P]', ...args); },
    debug: (...args) => { if (getLogLevel() >= LOG_LEVELS.debug) console.log('[P2P]', ...args); },
};

// ========== Completion Code Generation ==========
/**
 * Generate a UUID v4 for completion codes.
 * Uses crypto.randomUUID if available, otherwise falls back to manual generation.
 */
function generateCompletionCode() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        return crypto.randomUUID();
    }
    // Fallback for older browsers
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

// ========== Web Worker Timer (Phase 24) ==========
// Browsers throttle main-thread timers when tabs are backgrounded.
// Web Workers are exempt from throttling, providing reliable timing.

/**
 * GameTimerWorker - Runs game timing in a dedicated Web Worker.
 *
 * Browsers (Chrome 88+) throttle setInterval/setTimeout in background tabs:
 * - After 5 minutes: once per minute
 * - Workers are exempt from this throttling
 *
 * This class creates an inline Worker via Blob URL that sends tick messages
 * at the target frame rate. The main thread receives ticks via onTick callback.
 *
 * Usage:
 *   const timer = new GameTimerWorker(10);  // 10 FPS
 *   timer.onTick = (timestamp) => { ... };
 *   timer.start();
 *   // later:
 *   timer.destroy();
 */
class GameTimerWorker {
    /**
     * @param {number} targetFps - Target frames per second (default: 10)
     */
    constructor(targetFps = 10) {
        this.worker = null;
        this.workerUrl = null;
        this.targetInterval = 1000 / targetFps;  // ms between ticks
        this.onTick = null;  // Callback: (timestamp: number) => void
        this._createWorker();
    }

    /**
     * Create the inline Worker from a Blob URL.
     * Worker code runs setInterval and posts tick messages.
     * @private
     */
    _createWorker() {
        const workerCode = `
            let intervalId = null;

            self.onmessage = function(e) {
                const { command, interval } = e.data;

                if (command === 'start') {
                    if (intervalId) clearInterval(intervalId);
                    intervalId = setInterval(() => {
                        self.postMessage({ type: 'tick', timestamp: performance.now() });
                    }, interval);
                } else if (command === 'stop') {
                    if (intervalId) {
                        clearInterval(intervalId);
                        intervalId = null;
                    }
                } else if (command === 'setInterval') {
                    if (intervalId) {
                        clearInterval(intervalId);
                        intervalId = setInterval(() => {
                            self.postMessage({ type: 'tick', timestamp: performance.now() });
                        }, interval);
                    }
                }
            };
        `;

        const blob = new Blob([workerCode], { type: 'application/javascript' });
        this.workerUrl = URL.createObjectURL(blob);
        this.worker = new Worker(this.workerUrl);

        this.worker.onmessage = (e) => {
            if (e.data.type === 'tick' && this.onTick) {
                this.onTick(e.data.timestamp);
            }
        };

        this.worker.onerror = (err) => {
            console.error('[GameTimerWorker] Error:', err.message);
        };
    }

    /**
     * Start the timer. Ticks will be sent at targetInterval rate.
     */
    start() {
        this.worker.postMessage({ command: 'start', interval: this.targetInterval });
    }

    /**
     * Stop the timer. No more ticks will be sent.
     */
    stop() {
        this.worker.postMessage({ command: 'stop' });
    }

    /**
     * Update the target FPS. Takes effect immediately if running.
     * @param {number} fps - New target frames per second
     */
    setFps(fps) {
        this.targetInterval = 1000 / fps;
        this.worker.postMessage({ command: 'setInterval', interval: this.targetInterval });
    }

    /**
     * Clean up the Worker and revoke the Blob URL.
     * Call this when the game ends to prevent memory leaks.
     */
    destroy() {
        this.stop();
        this.worker.terminate();
        URL.revokeObjectURL(this.workerUrl);
        this.worker = null;
        this.workerUrl = null;
    }
}

// ========== Focus Management (Phase 25) ==========
// Detects tab visibility changes and manages background state for multiplayer sync.

/**
 * FocusManager - Detects tab visibility changes and manages background state.
 *
 * When tab is backgrounded:
 * - Local player's actions default to idle/no-op (defaultAction)
 * - Partner inputs are buffered for fast-forward on refocus (Phase 26)
 * - Game loop continues via Web Worker (Phase 24)
 *
 * Different from ContinuousMonitor which handles exclusion. FocusManager
 * handles graceful background operation for multiplayer sync.
 */
class FocusManager {
    constructor() {
        this.isBackgrounded = document.hidden;
        this.backgroundStartTime = document.hidden ? performance.now() : null;
        this.backgroundPeriods = [];  // [{start: number, end: number, durationMs: number}]
        this.backgroundInputBuffer = [];  // Inputs received while backgrounded
        this.timeoutMs = 30000;  // Default 30s, overridden by config (Phase 27)

        this._setupVisibilityListener();
    }

    _setupVisibilityListener() {
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this._onBackgrounded();
            } else {
                this._onForegrounded();
            }
        });
    }

    _onBackgrounded() {
        this.isBackgrounded = true;
        this.backgroundStartTime = performance.now();
        p2pLog.info('Tab backgrounded - local inputs will use defaultAction');
    }

    _onForegrounded() {
        if (this.backgroundStartTime !== null) {
            const end = performance.now();
            const durationMs = end - this.backgroundStartTime;
            this.backgroundPeriods.push({
                start: this.backgroundStartTime,
                end: end,
                durationMs: durationMs
            });
            const totalPeriods = this.backgroundPeriods.length;
            const totalDuration = this.backgroundPeriods.reduce((sum, p) => sum + p.durationMs, 0);
            p2pLog.info(`Tab foregrounded after ${durationMs.toFixed(0)}ms - buffered ${this.backgroundInputBuffer.length} inputs (${totalPeriods} periods, ${(totalDuration/1000).toFixed(1)}s total)`);
        }
        this.isBackgrounded = false;
        this.backgroundStartTime = null;
    }

    /**
     * Set timeout configuration from scene config (Phase 27).
     * @param {number} timeoutMs - Timeout in milliseconds (0 to disable)
     */
    setTimeoutConfig(timeoutMs) {
        this.timeoutMs = timeoutMs;
    }

    /**
     * Check if timeout has been exceeded (Phase 27).
     * @returns {boolean} True if backgrounded longer than timeout
     */
    isTimeoutExceeded() {
        if (!this.timeoutMs || this.timeoutMs === 0) return false;
        return this.getCurrentBackgroundDuration() > this.timeoutMs;
    }

    /**
     * Get current background duration in ms, or 0 if not backgrounded.
     */
    getCurrentBackgroundDuration() {
        if (!this.isBackgrounded || this.backgroundStartTime === null) {
            return 0;
        }
        return performance.now() - this.backgroundStartTime;
    }

    /**
     * Buffer a partner input packet received while backgrounded.
     * @param {Object} packet - Decoded input packet {playerId, inputs, currentFrame}
     */
    bufferInput(packet) {
        this.backgroundInputBuffer.push(packet);
    }

    /**
     * Drain all buffered inputs (for fast-forward on refocus).
     * @returns {Array} Array of buffered packets
     */
    drainBufferedInputs() {
        const buffered = this.backgroundInputBuffer;
        this.backgroundInputBuffer = [];
        return buffered;
    }

    /**
     * Get background periods for telemetry export.
     * @returns {Array} Array of {start, end, durationMs}
     */
    getBackgroundPeriods() {
        return [...this.backgroundPeriods];
    }

    /**
     * Get focus telemetry for session export.
     * @returns {Object} {backgroundPeriods: Array, totalBackgroundMs: number, periodCount: number}
     */
    getTelemetry() {
        const periods = this.getBackgroundPeriods();
        const totalMs = periods.reduce((sum, p) => sum + p.durationMs, 0);
        return {
            backgroundPeriods: periods,
            totalBackgroundMs: totalMs,
            periodCount: periods.length,
            currentlyBackgrounded: this.isBackgrounded,
            bufferedInputCount: this.backgroundInputBuffer.length
        };
    }

    /**
     * Reset state (e.g., on new episode).
     */
    reset() {
        this.backgroundPeriods = [];
        this.backgroundInputBuffer = [];
        // Don't reset isBackgrounded or backgroundStartTime - those reflect current state
    }

    /**
     * Destroy the manager (cleanup).
     */
    destroy() {
        // Listener cleanup not strictly needed since page will unload,
        // but good practice for testing scenarios
        this.backgroundInputBuffer = [];
    }
}

// ========== P2P Binary Message Protocol ==========
// Message Types
const P2P_MSG_INPUT = 0x01;
const P2P_MSG_PING = 0x02;
const P2P_MSG_PONG = 0x03;
const P2P_MSG_KEEPALIVE = 0x04;
const P2P_MSG_EPISODE_END = 0x05;  // Episode reset synchronization
const P2P_MSG_EPISODE_READY = 0x06;  // Episode start synchronization
const P2P_MSG_STATE_HASH = 0x07;  // State hash for sync validation
const P2P_MSG_VALIDATION_PING = 0x10;  // Validation request (Phase 19)
const P2P_MSG_VALIDATION_PONG = 0x11;  // Validation response (Phase 19)
const P2P_MSG_INPUT_REQUEST = 0x12;  // Request missing inputs for frame range
const P2P_MSG_INPUT_RESPONSE = 0x13;  // Response with requested inputs
const P2P_MSG_FOCUS_STATE = 0x14;  // Focus state notification (focused/backgrounded)

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
 * Encode an episode ready notification for P2P transmission.
 * Sent after local reset completes to synchronize episode start.
 * Format: 13 bytes
 *   Byte 0: Message type (0x06)
 *   Bytes 1-4: Episode number (uint32)
 *   Bytes 5-12: State hash for verification (8 chars as bytes)
 *
 * @param {number} episodeNumber - Episode number we're ready for
 * @param {string} stateHash - 8-char hex hash of initial state
 * @returns {ArrayBuffer} Encoded packet
 */
function encodeEpisodeReady(episodeNumber, stateHash) {
    const buffer = new ArrayBuffer(13);
    const view = new DataView(buffer);
    view.setUint8(0, P2P_MSG_EPISODE_READY);
    view.setUint32(1, episodeNumber, false);
    // Write 8-char hash as bytes
    for (let i = 0; i < 8; i++) {
        view.setUint8(5 + i, stateHash.charCodeAt(i) || 0);
    }
    return buffer;
}

/**
 * Decode an episode ready notification.
 *
 * @param {ArrayBuffer} buffer - Received packet
 * @returns {{episodeNumber: number, stateHash: string}|null}
 */
function decodeEpisodeReady(buffer) {
    const view = new DataView(buffer);
    const type = view.getUint8(0);
    if (type !== P2P_MSG_EPISODE_READY) return null;
    // Read 8-char hash from bytes
    let stateHash = '';
    for (let i = 0; i < 8; i++) {
        stateHash += String.fromCharCode(view.getUint8(5 + i));
    }
    return {
        episodeNumber: view.getUint32(1, false),
        stateHash: stateHash
    };
}

/**
 * Encode a state hash message for P2P transmission.
 * Used for sync validation - peers exchange hashes of confirmed frames.
 * Format: 13 bytes
 *   Byte 0: Message type (0x07)
 *   Bytes 1-4: Frame number (uint32, big-endian)
 *   Bytes 5-12: Hash value (8 bytes from 16 hex chars)
 *
 * @param {number} frameNumber - Frame this hash corresponds to
 * @param {string} hash - 16-char hex hash (SHA-256 truncated)
 * @returns {ArrayBuffer} Encoded packet (13 bytes)
 */
function encodeStateHash(frameNumber, hash) {
    const buffer = new ArrayBuffer(13);
    const view = new DataView(buffer);
    view.setUint8(0, P2P_MSG_STATE_HASH);
    view.setUint32(1, frameNumber, false);  // big-endian
    // Write 8 bytes of hash (16 hex chars = 8 bytes)
    for (let i = 0; i < 8; i++) {
        const hexPair = hash.substring(i * 2, i * 2 + 2);
        view.setUint8(5 + i, parseInt(hexPair, 16));
    }
    return buffer;
}

/**
 * Decode a state hash message from P2P transmission.
 *
 * @param {ArrayBuffer} buffer - Received packet
 * @returns {{frameNumber: number, hash: string}|null} Decoded data or null if wrong type
 */
function decodeStateHash(buffer) {
    const view = new DataView(buffer);
    const type = view.getUint8(0);
    if (type !== P2P_MSG_STATE_HASH) return null;

    const frameNumber = view.getUint32(1, false);
    // Read 8 bytes and convert back to 16-char hex string
    let hash = '';
    for (let i = 0; i < 8; i++) {
        const byte = view.getUint8(5 + i);
        hash += byte.toString(16).padStart(2, '0');
    }
    return { frameNumber, hash };
}

/**
 * Encode a validation ping message (Phase 19).
 * Format: 9 bytes
 *   Byte 0: Message type (0x10)
 *   Bytes 1-8: Timestamp (float64)
 *
 * @returns {ArrayBuffer} Encoded ping
 */
function encodeValidationPing() {
    const buffer = new ArrayBuffer(9);
    const view = new DataView(buffer);
    view.setUint8(0, P2P_MSG_VALIDATION_PING);
    view.setFloat64(1, performance.now(), false);
    return buffer;
}

/**
 * Encode a validation pong response (Phase 19).
 * Echoes back the original timestamp.
 *
 * @param {number} originalTimestamp - Timestamp from received ping
 * @returns {ArrayBuffer} Encoded pong
 */
function encodeValidationPong(originalTimestamp) {
    const buffer = new ArrayBuffer(9);
    const view = new DataView(buffer);
    view.setUint8(0, P2P_MSG_VALIDATION_PONG);
    view.setFloat64(1, originalTimestamp, false);
    return buffer;
}

/**
 * Encode an input request message.
 * Used when fast-forwarding after refocus to request missing inputs from partner.
 * Format:
 *   Byte 0: Message type (0x12)
 *   Bytes 1-4: Start frame (uint32)
 *   Bytes 5-8: End frame (uint32)
 *
 * @param {number} startFrame - First frame to request inputs for
 * @param {number} endFrame - Last frame to request inputs for (inclusive)
 * @returns {ArrayBuffer} Encoded request
 */
function encodeInputRequest(startFrame, endFrame) {
    const buffer = new ArrayBuffer(9);
    const view = new DataView(buffer);
    view.setUint8(0, P2P_MSG_INPUT_REQUEST);
    view.setUint32(1, startFrame, false);
    view.setUint32(5, endFrame, false);
    return buffer;
}

/**
 * Decode an input request message.
 * @param {ArrayBuffer} buffer - Received message
 * @returns {{startFrame: number, endFrame: number}|null}
 */
function decodeInputRequest(buffer) {
    const view = new DataView(buffer);
    if (view.getUint8(0) !== P2P_MSG_INPUT_REQUEST) return null;
    return {
        startFrame: view.getUint32(1, false),
        endFrame: view.getUint32(5, false)
    };
}

/**
 * Encode an input response message.
 * Contains inputs for a range of frames requested by partner.
 * Format:
 *   Byte 0: Message type (0x13)
 *   Bytes 1-2: Player ID (uint16)
 *   Bytes 3-4: Input count (uint16)
 *   Each input (5 bytes):
 *     Bytes 0-3: Frame number (uint32)
 *     Byte 4: Action value (uint8)
 *
 * @param {number} playerId - The player whose inputs these are
 * @param {Array<{frame: number, action: number}>} inputs - Inputs to send
 * @returns {ArrayBuffer} Encoded response
 */
function encodeInputResponse(playerId, inputs) {
    const inputCount = inputs.length;
    const buffer = new ArrayBuffer(5 + inputCount * 5);
    const view = new DataView(buffer);
    view.setUint8(0, P2P_MSG_INPUT_RESPONSE);
    view.setUint16(1, playerId, false);
    view.setUint16(3, inputCount, false);

    for (let i = 0; i < inputCount; i++) {
        const offset = 5 + i * 5;
        view.setUint32(offset, inputs[i].frame, false);
        view.setUint8(offset + 4, inputs[i].action);
    }
    return buffer;
}

/**
 * Decode an input response message.
 * @param {ArrayBuffer} buffer - Received message
 * @returns {{playerId: number, inputs: Array<{frame: number, action: number}>}|null}
 */
function decodeInputResponse(buffer) {
    const view = new DataView(buffer);
    if (view.getUint8(0) !== P2P_MSG_INPUT_RESPONSE) return null;

    const playerId = view.getUint16(1, false);
    const inputCount = view.getUint16(3, false);
    const inputs = [];

    for (let i = 0; i < inputCount; i++) {
        const offset = 5 + i * 5;
        inputs.push({
            frame: view.getUint32(offset, false),
            action: view.getUint8(offset + 4)
        });
    }
    return { playerId, inputs };
}

/**
 * Encode a focus state message.
 * Used to notify partner when focus state changes (for episode sync).
 * Format:
 *   Byte 0: Message type (0x14)
 *   Byte 1: Focus state (1 = focused, 0 = backgrounded)
 *   Bytes 2-5: Current frame number (uint32)
 *
 * @param {boolean} isFocused - Whether the tab is focused
 * @param {number} frameNumber - Current frame number
 * @returns {ArrayBuffer} Encoded message
 */
function encodeFocusState(isFocused, frameNumber) {
    const buffer = new ArrayBuffer(6);
    const view = new DataView(buffer);
    view.setUint8(0, P2P_MSG_FOCUS_STATE);
    view.setUint8(1, isFocused ? 1 : 0);
    view.setUint32(2, frameNumber, false);
    return buffer;
}

/**
 * Decode a focus state message.
 * @param {ArrayBuffer} buffer - Received message
 * @returns {{isFocused: boolean, frameNumber: number}|null}
 */
function decodeFocusState(buffer) {
    const view = new DataView(buffer);
    if (view.getUint8(0) !== P2P_MSG_FOCUS_STATE) return null;
    return {
        isFocused: view.getUint8(1) === 1,
        frameNumber: view.getUint32(2, false)
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

        // Rollback smoothing settings (for visual stability after corrections)
        // null/undefined disables smoothing, positive integer enables with that duration (ms)
        this.rollbackSmoothingDuration = config.rollback_smoothing_duration ?? 100;

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

        // Confirmed hash history: hashes for frames where ALL players' inputs are confirmed
        // This is separate from stateHashHistory which may include predicted frames
        // Uses SHA-256 (truncated to 16 chars) with float normalization for cross-platform reliability
        this.confirmedHashHistory = new Map();  // frameNumber -> hash (SHA-256 truncated)
        this.confirmedHashHistoryMaxSize = 120;  // Keep ~4 seconds at 30fps

        // Pending hash exchange: hashes computed but not yet sent to peer
        // [{frame: number, hash: string}, ...]
        this.pendingHashExchange = [];

        // Pending peer hashes: hashes received from peer awaiting comparison (Phase 13)
        // Map<frameNumber, hash>
        this.pendingPeerHashes = new Map();

        // Mismatch detection state (Phase 13: DETECT-04, DETECT-03)
        this.verifiedFrame = -1;  // Highest frame mutually verified by both peers
        this.desyncEvents = [];   // [{frame, ourHash, peerHash, timestamp, stateDump}, ...]

        // Action tracking for sync verification
        this.actionSequence = [];  // [{frame: N, actions: {player: action}}]
        this.actionCounts = {};    // {playerId: {action: count}}

        // Frame-indexed data buffer for rollback-safe data logging
        // Maps frame -> {actions, rewards, terminateds, truncateds, isFocused}
        // This buffer is cleared/updated on rollback to ensure only correct data is exported
        this.frameDataBuffer = new Map();

        // Cumulative validation data - persists across episodes for full session export
        // This data is NOT cleared on episode reset, only when scene ends
        this.cumulativeValidation = {
            episodes: [],           // Per-episode summaries
            allHashes: [],          // All confirmed hashes across all episodes
            allActions: [],         // All verified actions across all episodes
            allDesyncEvents: [],    // All desync events across all episodes
            allRollbacks: [],       // All rollback events across all episodes
            sessionStartTime: Date.now()
        };

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
        this.latencyTelemetry = null;  // Phase 22 - Latency telemetry

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
        // AND both peers must agree on episode start before beginning
        // AND both peers must be focused before starting new episode
        this.p2pEpisodeSync = {
            // Episode END sync
            localEpisodeEndDetected: false,   // We detected episode end
            localEpisodeEndFrame: null,       // Frame where we detected it
            remoteEpisodeEndReceived: false,  // Peer sent episode end message
            remoteEpisodeEndFrame: null,      // Frame where peer detected it
            pendingReset: false,              // Waiting for sync before reset
            syncTimeoutId: null,              // Timeout to prevent infinite waiting
            // Episode START sync
            localResetComplete: false,        // We completed our reset
            remoteResetComplete: false,       // Peer completed their reset
            localStateHash: null,             // Our initial state hash
            remoteStateHash: null,            // Peer's initial state hash
            startResolve: null,               // Promise resolve for start sync
            startTimeoutId: null,             // Timeout for start sync
            // Partner focus tracking (for episode sync)
            partnerFocused: true,             // Assume focused until told otherwise
            waitingForPartnerFocus: false,    // True when waiting for partner to refocus
            retryTimeoutId: null              // Retry timeout for episode ready
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

        // P2P validation state machine (Phase 19)
        // States: 'idle' -> 'connecting' -> 'validating' -> 'validated' | 'failed'
        this.p2pValidation = {
            enabled: true,                  // Can be disabled via config
            state: 'idle',
            timeoutMs: 10000,               // Default 10 seconds for validation
            timeoutId: null,
            pingSentAt: null,               // Timestamp when ping sent
            pongReceived: false,
            peerPingSeen: false
        };

        // Mid-game reconnection state (Phase 20)
        // States: 'connected' -> 'pausing' -> 'paused' -> 'reconnecting' -> 'connected' | 'terminated'
        this.reconnectionState = {
            state: 'connected',              // Current reconnection state
            isPaused: false,                 // Game loop paused?
            pauseStartTime: null,            // When pause started
            pauseFrame: null,                // Frame number when paused
            timeoutMs: 30000,                // Configurable timeout (RECON-04)
            timeoutId: null,                 // Timeout handle

            // Event logging (LOG-01, LOG-02, LOG-03)
            disconnections: [],              // [{timestamp, frame, detectingPeer, iceState, dcState}]
            reconnectionAttempts: [],        // [{timestamp, duration, outcome, attempts}]
            totalPauseDuration: 0            // Cumulative ms paused (LOG-03)
        };

        // GGPO-style input queuing: inputs are queued during network reception
        // and processed synchronously at frame start to prevent race conditions
        this.pendingInputPackets = [];     // Queued P2P input packets
        this.pendingSocketIOInputs = [];   // Queued SocketIO inputs
        this.rollbackInProgress = false;   // Guard against nested rollbacks

        // Continuous monitoring (Phase 16)
        this.continuousMonitor = null;  // Initialized in pyodide_game_ready when config available
        this.monitorCheckCounter = 0;   // Check every N frames to reduce overhead
        this.monitorCheckInterval = 30; // Check once per second at 30fps

        // Partial session tracking (Phase 17)
        // Set when session ends due to exclusion (self or partner)
        this.sessionPartialInfo = null;

        // Partner disconnection terminal state (Phase 23)
        // When true, prevents scene advancement - the overlay is the final state
        this.partnerDisconnectedTerminal = false;

        // Focus loss timeout terminal state (Phase 27)
        // When true, prevents scene advancement - the overlay is the final state
        this.focusLossTimeoutTerminal = false;

        // Web Worker Timer (Phase 24)
        // Worker runs setInterval exempt from browser throttling
        this.timerWorker = null;           // GameTimerWorker instance
        this.isProcessingTick = false;     // Guard against overlapping tick processing
        this.tickCallback = null;          // Callback to trigger game step from external code

        // Pipeline latency metrics (Phase 28 - DIAG-01 to DIAG-07)
        // Tracks timestamps at each stage: keypress -> queue -> step -> render
        this.pipelineMetrics = {
            lastInputTimestamps: null,       // {keypressTimestamp, queueExitTimestamp}
            stepCallTimestamp: null,         // DIAG-03: When stepWithActions() called
            stepReturnTimestamp: null,       // DIAG-04: When stepWithActions() returns
            enabled: true,                   // Can be toggled via console: window.pipelineMetricsEnabled = false
            framesSinceLastLog: 0,           // Counter for throttled logging after initial frames
            initialLogFrames: 50             // Log every frame for first N frames
        };

        // Focus management (Phase 25)
        this.focusManager = new FocusManager();

        // Phase 26: Fast-forward on refocus
        this._pendingFastForward = false;
        // Pending input request state for fast-forward resync
        this._pendingInputRequest = null;  // {resolve, reject, startFrame, endFrame}

        // Phase 27: Waiting for partner to refocus (game paused)
        this._waitingForPartnerFocus = false;

        // Phase 33: P2P health reporting interval ID (for cleanup)
        this._p2pHealthReportIntervalId = null;

        // Hook into FocusManager's foregrounded event to trigger fast-forward and broadcast state
        const originalOnForegrounded = this.focusManager._onForegrounded.bind(this.focusManager);
        this.focusManager._onForegrounded = () => {
            originalOnForegrounded();
            this._pendingFastForward = true;
            p2pLog.info('Tab foregrounded - scheduling fast-forward');
            // Notify partner we're back
            this._broadcastFocusState(true);
        };

        // Hook into FocusManager's backgrounded event to notify partner
        const originalOnBackgrounded = this.focusManager._onBackgrounded.bind(this.focusManager);
        this.focusManager._onBackgrounded = () => {
            originalOnBackgrounded();
            // Notify partner we're leaving
            this._broadcastFocusState(false);
        };

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
                p2pLog.debug(`Player ${this.myPlayerId} assigned to game ${this.gameId} (seed=${this.gameSeed})`);
            }
        });

        // Game ready to start
        socket.on('pyodide_game_ready', (data) => {
            console.log('[DEBUG] pyodide_game_ready event received:', data);
            p2pLog.debug(`Game ready: ${data.players.length} players, server_auth=${data.server_authoritative || false}`);

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

            // Initialize continuous monitoring if configured (Phase 16)
            if (data.scene_metadata?.continuous_monitoring_enabled) {
                this.continuousMonitor = new ContinuousMonitor(data.scene_metadata);
                p2pLog.info('Continuous monitoring enabled');
            }

            // Reconnection timeout config (Phase 20 - RECON-04)
            if (data.scene_metadata?.reconnection_timeout_ms) {
                this.reconnectionState.timeoutMs = data.scene_metadata.reconnection_timeout_ms;
                p2pLog.info(`Reconnection timeout: ${this.reconnectionState.timeoutMs}ms`);
            }

            // Store partner disconnect message config (Phase 23 - CFG-01, CFG-02)
            if (data.scene_metadata?.partner_disconnect_message !== undefined) {
                this.config.partner_disconnect_message = data.scene_metadata.partner_disconnect_message;
            }

            // Configure focus loss timeout from scene config (Phase 27)
            if (data.scene_metadata?.focus_loss_timeout_ms !== undefined) {
                this.focusManager.setTimeoutConfig(data.scene_metadata.focus_loss_timeout_ms);
                p2pLog.info(`Focus loss timeout: ${data.scene_metadata.focus_loss_timeout_ms}ms`);
            }
            if (data.scene_metadata?.focus_loss_message !== undefined) {
                this.config.focus_loss_message = data.scene_metadata.focus_loss_message;
            }
            // Configure whether to pause game when partner backgrounds
            if (data.scene_metadata?.pause_on_partner_background !== undefined) {
                this.config.pause_on_partner_background = data.scene_metadata.pause_on_partner_background;
            }

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
                    p2pLog.debug(`Waiting for P2P connection (max ${this.p2pReadyGate.timeoutMs}ms)...`);
                    this.p2pReadyGate.timeoutId = setTimeout(() => {
                        if (!this.p2pReadyGate.resolved) {
                            // Phase 19: On timeout without validation, emit failure instead of fallback
                            if (this.p2pValidation.enabled && this.p2pValidation.state !== 'validated') {
                                p2pLog.error('P2P connection timeout - validation not complete');
                                socket.emit('p2p_validation_failed', {
                                    game_id: this.gameId,
                                    player_id: this.myPlayerId,
                                    reason: 'connection_timeout'
                                });
                            } else {
                                // Validation disabled - allow SocketIO fallback (legacy behavior)
                                p2pLog.warn('P2P connection timeout - starting with SocketIO fallback');
                                this._resolveP2PReadyGate();
                            }
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
                        p2pLog.debug(`Requesting state resync from peer ${sender_id}`);
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

            p2pLog.debug(`Applying peer state from ${sender_id} (frame=${frame_number})`);

            try {
                // Apply the peer's state
                await this._applyP2PState(env_state, frame_number, step_num, cumulative_rewards);
                p2pLog.debug(`State resync complete, now at frame ${this.frameNumber}`);
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

            p2pLog.debug(`Server game complete: ${episode_num}/${max_episodes} episodes`);

            // Mark game as complete - this stops the game loop
            this.state = "done";
            this.episodeComplete = true;
            this.num_episodes = episode_num;

            // Clean up Web Worker timer (Phase 24)
            this._destroyTimerWorker();

            // Sync final rewards if provided
            if (data.cumulative_rewards) {
                this.cumulative_rewards = data.cumulative_rewards;
            }
        });

        // P2P validation complete (Phase 19)
        // Both peers validated - proceed to game
        socket.on('p2p_validation_complete', (data) => {
            p2pLog.warn('P2P validation complete - proceeding to game');
            this._resolveP2PReadyGate();
        });

        // Partner excluded (Phase 17)
        // Received when the other player was excluded by continuous monitoring
        socket.on('partner_excluded', (data) => {
            p2pLog.warn(`Partner excluded: ${data.message}`);

            // Stop game loop
            this.state = "done";
            this.episodeComplete = true;

            // Pause monitoring
            if (this.continuousMonitor) {
                this.continuousMonitor.pause();
            }

            // Show notification (neutral, not alarming like own exclusion)
            this._showPartnerExcludedUI(data.message);

            // Clean up Web Worker timer (Phase 24)
            this._destroyTimerWorker();

            // Stop latency telemetry (Phase 22) - keep data for export
            if (this.latencyTelemetry) {
                this.latencyTelemetry.stop();
            }

            // Clean up WebRTC
            if (this.webrtcManager) {
                this.webrtcManager.close();
            }
        });

        // Trigger data export (Phase 17)
        // Received when partner is excluded - export our data before redirect
        socket.on('trigger_data_export', (data) => {
            // Mark session as partial in our metrics
            this.sessionPartialInfo = {
                isPartial: true,
                terminationReason: data.termination_reason,
                terminationFrame: data.termination_frame
            };

            // Export metrics immediately (before redirect)
            if (this.gameId) {
                this.emitMultiplayerMetrics(this.sceneId);
            }

            // Now request redirect
            socket.emit('end_game_request_redirect', {
                partner_exclusion: true
            });
        });

        // Continuous callback result (Phase 18)
        // Received when server executes researcher-defined callback
        socket.on('continuous_callback_result', (data) => {
            if (this.continuousMonitor) {
                this.continuousMonitor.setCallbackPending(false);
                this.continuousMonitor.setCallbackResult(data);
            }
        });

        // P2P reconnection handlers (Phase 20)
        socket.on('p2p_pause', (data) => {
            if (data.game_id === this.gameId) {
                this._handleServerPause(data);
            }
        });

        socket.on('p2p_resume', (data) => {
            if (data.game_id === this.gameId) {
                this._handleServerResume(data);
            }
        });

        socket.on('p2p_game_ended', (data) => {
            if (data.game_id === this.gameId) {
                this._handleReconnectionGameEnd(data);
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
            p2pLog.debug(`State sync enabled for ${capabilities.env_type}`);
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

        // Clear frame data buffer for new episode
        this.frameDataBuffer.clear();

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

        // P2P per-round health check (Phase 21 - ROUND-01, ROUND-02)
        // Verify DataChannel connection is healthy before starting round
        if (!this.serverAuthoritative && this.webrtcManager) {
            try {
                await this._waitForHealthyConnection(10000);  // 10 second timeout
            } catch (e) {
                p2pLog.error(`Per-round health check failed: ${e.message}`);
                // Don't proceed with round - reconnection handler will end game if terminated
                // Or timeout will have elapsed - let the game end naturally via existing flow
                return [obs, infos, render_state];  // Return early, let caller handle state
            }
        }

        // P2P episode start synchronization
        // Compute state hash and wait for peer to be ready before starting
        if (!this.serverAuthoritative && this.webrtcManager?.isReady()) {
            try {
                // Compute state hash for verification
                const stateHash = await this.pyodide.runPythonAsync(`
import json
import hashlib
_state = env.get_state()
hashlib.md5(json.dumps(_state, sort_keys=True).encode()).hexdigest()[:8]
                `);

                // Broadcast that we're ready and wait for peer
                this._broadcastEpisodeReady(stateHash);

                p2pLog.debug(`Waiting for peer to be ready for episode ${this.num_episodes + 1}...`);
                await this.waitForP2PEpisodeStart(5000);  // 5 second timeout
                p2pLog.debug(`Episode start synchronized - both peers ready`);
            } catch (e) {
                p2pLog.warn(`Episode start sync error: ${e.message}`);
                // Continue anyway - deterministic reset should keep clients in sync
            }
        }

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

        // Also clear global pressed keys to prevent stale inputs from previous episode
        clearHumanInputBuffers();

        p2pLog.debug('Cleared action queues and human input buffers after episode transition');
    }

    /**
     * Override showEpisodeTransition to wait for partner focus before countdown.
     * In multiplayer P2P mode, we need both players focused before starting
     * the next episode countdown.
     */
    async showEpisodeTransition(waitingMessage = null) {
        // Check if this is a subsequent episode (not the first one)
        const isSubsequentEpisode = this.num_episodes > 0;
        p2pLog.info(`showEpisodeTransition called: num_episodes=${this.num_episodes}, isSubsequentEpisode=${isSubsequentEpisode}`);

        if (!isSubsequentEpisode) {
            // First episode - just ensure overlay is hidden
            p2pLog.info('First episode - skipping countdown');
            ui_utils.hideEpisodeOverlay();
            return;
        }

        // For P2P multiplayer, wait for partner to be focused before showing countdown
        // Only do this if WebRTC is ready and we have a focus manager
        if (!this.serverAuthoritative && this.webrtcManager?.isReady() && this.focusManager) {
            const localFocused = !this.focusManager.isBackgrounded;
            const partnerFocused = this.p2pEpisodeSync.partnerFocused;

            if (!localFocused || !partnerFocused) {
                // Show waiting overlay
                const waitingFor = !localFocused ? 'you to return' : 'partner';
                this._waitingForPartnerFocus = true;
                this._showWaitingForPartnerOverlay(!partnerFocused);
                p2pLog.info(`Waiting for ${waitingFor} to focus before episode countdown`);

                // Wait for focus to be restored (with timeout to prevent infinite wait)
                const focusWaitTimeout = 10000;  // 10 second timeout
                const startWaitTime = performance.now();

                await new Promise((resolve) => {
                    const checkFocus = () => {
                        const nowLocalFocused = !this.focusManager.isBackgrounded;
                        const nowPartnerFocused = this.p2pEpisodeSync.partnerFocused;
                        const elapsed = performance.now() - startWaitTime;

                        if (nowLocalFocused && nowPartnerFocused) {
                            this._waitingForPartnerFocus = false;
                            this._hideWaitingForPartnerOverlay();
                            resolve();
                        } else if (elapsed > focusWaitTimeout) {
                            // Timeout - proceed anyway to prevent stuck state
                            p2pLog.warn(`Focus wait timeout (${(elapsed/1000).toFixed(1)}s) - proceeding with countdown`);
                            this._waitingForPartnerFocus = false;
                            this._hideWaitingForPartnerOverlay();
                            resolve();
                        } else {
                            // Check again on next tick
                            setTimeout(checkFocus, 100);
                        }
                    };
                    checkFocus();
                });
            }
        }

        // Show waiting message if provided
        if (waitingMessage) {
            ui_utils.showEpisodeWaiting(waitingMessage);
        }

        // Show countdown before starting
        const episodeNum = this.num_episodes + 1;
        p2pLog.info(`Showing episode countdown for round ${episodeNum}`);
        await ui_utils.showEpisodeCountdown(3, `Round ${episodeNum} starting!`);
        p2pLog.info('Episode countdown completed');
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
        const _stepStartTime = performance.now();

        // Don't step until multiplayer setup is complete
        if (this.myPlayerId === null || this.myPlayerId === undefined) {
            p2pLog.debug('Waiting for player ID assignment...');
            return null;
        }

        if (this.gameId === null || this.gameId === undefined) {
            p2pLog.debug('Waiting for game ID assignment...');
            return null;
        }

        // Don't step while paused for reconnection (Phase 20)
        if (this.reconnectionState.isPaused) {
            return null;
        }

        // GGPO Order of Operations:
        // 1. Clear stale rollback flag (prevents stale rollbacks from previous frames)
        // 2. Process queued inputs synchronously (drains network buffers)
        // 3. Process debug-delayed inputs
        // 4. Check for and execute pending rollback BEFORE stepping current frame
        // 5. Store local input and send to peer
        // 6. Build final action dict from confirmed/predicted inputs
        // 7. Step environment

        // Clear stale rollback flag at frame start - rollback detection happens fresh
        this.pendingRollbackFrame = null;

        // GGPO-style: Process all queued network inputs synchronously
        // This ensures inputs don't arrive during rollback replay (race condition prevention)
        this._processQueuedInputs();

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

        // GGPO: Check for and execute pending rollback BEFORE stepping current frame
        // Rollback may have been triggered by storeRemoteInput when processing queued inputs
        // IMPORTANT: Execute rollback BEFORE building finalActions so we use corrected state
        let rollbackOccurred = false;
        if (this.pendingRollbackFrame !== null && this.pendingRollbackFrame !== undefined) {
            const rollbackFrame = this.pendingRollbackFrame;
            this.pendingRollbackFrame = null;

            // Perform rollback and replay synchronously
            rollbackOccurred = await this.performRollback(rollbackFrame, humanPlayerIds);
        }

        // After rollback completes (or if no rollback), update confirmed frame tracking
        // This triggers hash computation for any newly confirmed frames (HASH-01)
        await this._updateConfirmedFrame();

        // Exchange any pending hashes with peer (EXCH-01, EXCH-02)
        this._exchangePendingHashes();

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
        // DEBUG: Log executed actions when prediction is used (use info level)
        if (predictedPlayers.length > 0) {
            const actionsStr = Object.entries(finalActions).map(([p, a]) => `${p}:${a}`).join(' ');
            p2pLog.debug(`EXECUTE: frame=${this.frameNumber} actions={${actionsStr}} predicted=[${predictedPlayers.join(',')}]`);
        }
        this.actionSequence.push({
            frame: this.frameNumber,
            actions: {...finalActions},  // Clone to avoid mutation
            isFocused: this.focusManager ? !this.focusManager.isBackgrounded : true
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

        // DEBUG: Log state and actions for sync verification
        // This helps trace divergence by comparing exact states/actions between clients
        if (this.frameNumber < 100) {
            try {
                const preHashResult = await this.pyodide.runPythonAsync(`
import json
import hashlib
_st = env.get_state()
hashlib.md5(json.dumps(_st, sort_keys=True).encode()).hexdigest()[:8]
                `);
                const actionsStr = Object.entries(finalActions).map(([p, a]) => `${p}:${a}`).join(',');
                p2pLog.debug(`FRAME: ${this.frameNumber} pre_hash=${preHashResult} actions={${actionsStr}} rollback=${rollbackOccurred}`);
            } catch (e) {
                p2pLog.debug(`Could not compute pre-step hash: ${e}`);
            }
        }

        // DIAG-03: Capture timestamp when env.step() is called
        this.pipelineMetrics.stepCallTimestamp = performance.now();

        const stepResult = await this.stepWithActions(finalActions);

        // DIAG-04: Capture timestamp when env.step() returns
        this.pipelineMetrics.stepReturnTimestamp = performance.now();

        if (!stepResult) {
            return null;
        }

        const [obs, rewards, terminateds, truncateds, infos, render_state] = stepResult;

        // DEBUG: Log state hash after step for sync verification
        if (this.frameNumber < 100) {
            try {
                const hashResult = await this.pyodide.runPythonAsync(`
import json
import hashlib
_st = env.get_state()
hashlib.md5(json.dumps(_st, sort_keys=True).encode()).hexdigest()[:8]
                `);
                p2pLog.debug(`FRAME: ${this.frameNumber} post_hash=${hashResult}`);
            } catch (e) {
                p2pLog.debug(`Could not compute post-step hash: ${e}`);
            }
        }

        // Track step timing for diagnostics
        this.trackStepTime(stepStartTime);

        // NOTE: State hash recording and P2P sync broadcasts disabled.
        // GGPO rollback handles synchronization via input prediction and replay.
        // State sync (hash comparison) is a separate verification layer that's not needed
        // when rollback is working correctly.

        // Store frame data in the rollback-safe buffer BEFORE incrementing frameNumber
        // This ensures we use the correct frame number for data storage
        // Data will be cleared and re-stored on rollback via clearFrameDataFromRollback + replay
        // IMPORTANT: Don't store data if we've already detected episode end locally
        // (we may still be executing frames while waiting for peer sync)
        if (!this.p2pEpisodeSync.localEpisodeEndDetected) {
            this.storeFrameData(this.frameNumber, {
                actions: finalActions,
                rewards: Object.fromEntries(rewards),
                terminateds: Object.fromEntries(terminateds),
                truncateds: Object.fromEntries(truncateds),
                infos: infos instanceof Map ? Object.fromEntries(infos) : infos,
                isFocused: this.focusManager ? !this.focusManager.isBackgrounded : true
            });
        }

        // Check P2P health for fallback awareness
        this._checkP2PHealth();

        // 4. Increment frame (AFTER recording data and hash)
        this.frameNumber++;

        // Prune old input buffer entries to prevent unbounded growth
        this.pruneInputBuffer();

        // Log diagnostics periodically
        this.logDiagnostics();

        // Continuous monitoring check (Phase 16)
        // Check less frequently than every frame to reduce overhead
        if (this.continuousMonitor && !inEpisodeTransition) {
            // Record ping for continuous monitoring
            if (window.currentPing !== undefined) {
                this.continuousMonitor.recordPing(window.currentPing);
            }

            this.monitorCheckCounter++;
            if (this.monitorCheckCounter >= this.monitorCheckInterval) {
                this.monitorCheckCounter = 0;
                const monitorResult = this.continuousMonitor.check();

                if (monitorResult.exclude) {
                    await this._handleMidGameExclusion(monitorResult.reason, monitorResult.message);
                    return null;  // Stop game loop
                }

                if (monitorResult.warn) {
                    this._showMonitorWarning(monitorResult.message);
                }
            }

            // Check if we should execute continuous callback (Phase 18)
            if (this.continuousMonitor.shouldExecuteCallback()) {
                this._executeContinuousCallback();
            }
        }

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

                // Apply tween flags for rollback smoothing (smooth position transitions)
                // Enabled when rollbackSmoothingDuration is a positive number
                let gameStateObjects = game_image_base64 ? null : freshRenderState.map(item => convertUndefinedToNull(item));
                const smoothingEnabled = this.rollbackSmoothingDuration != null && this.rollbackSmoothingDuration > 0;
                if (smoothingEnabled && gameStateObjects) {
                    gameStateObjects = gameStateObjects.map(obj => ({
                        ...obj,
                        tween: true,
                        tween_duration: this.rollbackSmoothingDuration
                    }));
                }

                finalRenderState = {
                    "game_state_objects": gameStateObjects,
                    "game_image_base64": game_image_base64,
                    "step": this.step_num,
                };
                p2pLog.debug(`Rollback render update: frame=${this.frameNumber}, smoothing=${smoothingEnabled}`);
            } catch (e) {
                p2pLog.warn(`Failed to get post-rollback render state: ${e}`);
            }
        }

        // Log step timing periodically (every 50 frames)
        if (this.frameNumber % 50 === 0) {
            const stepDuration = performance.now() - _stepStartTime;
            console.log(`[TIMING] frame=${this.frameNumber} stepMs=${stepDuration.toFixed(1)}`);
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

        // Skip during fast-forward (not real-time input)
        if (this._pendingFastForward) return;

        // Skip if backgrounded (not real-time)
        if (this.focusManager?.isBackgrounded) return;

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

    // ========== Confirmed Hash Infrastructure (HASH-01 through HASH-04) ==========

    /**
     * Get list of human player IDs from policy mapping.
     * @returns {Array<string>} Array of player IDs where policy is 'human'
     */
    _getHumanPlayerIds() {
        const humanIds = [];
        for (const [agentId, policy] of Object.entries(this.policyMapping)) {
            if (policy === 'human') {
                humanIds.push(String(agentId));
            }
        }
        return humanIds;
    }

    /**
     * Check if all specified players have confirmed inputs for a frame.
     * @param {number} frameNumber - Frame to check
     * @param {Array<string>} playerIds - Player IDs to check
     * @returns {boolean} True if all players have inputs for this frame
     */
    _hasAllInputsForFrame(frameNumber, playerIds) {
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
     * Update confirmedFrame to the highest frame where ALL players have confirmed inputs.
     * Called after processing inputs and after rollback completion.
     * Triggers hash computation for newly confirmed frames (HASH-01).
     */
    async _updateConfirmedFrame() {
        const humanPlayerIds = this._getHumanPlayerIds();
        if (humanPlayerIds.length === 0) return;

        // Determine starting frame for confirmation scan
        let startFrame = this.confirmedFrame + 1;

        // If confirmedFrame is behind the oldest frame in inputBuffer (due to pruning),
        // skip ahead to the earliest available frame to avoid scanning empty range
        if (this.inputBuffer.size > 0) {
            const oldestBufferedFrame = Math.min(...this.inputBuffer.keys());
            if (startFrame < oldestBufferedFrame) {
                // Jump to oldest available frame - we can't confirm frames we don't have
                startFrame = oldestBufferedFrame;
            }
        }

        // Find highest consecutive confirmed frame
        for (let frame = startFrame; frame < this.frameNumber; frame++) {
            if (this._hasAllInputsForFrame(frame, humanPlayerIds)) {
                // This frame is now confirmed (all inputs received)
                this.confirmedFrame = frame;

                // Remove from predictedFrames if it was there
                this.predictedFrames.delete(frame);

                // Compute and store hash for this confirmed frame
                await this._computeAndStoreConfirmedHash(frame);
            } else {
                // Gap in confirmation - stop here
                break;
            }
        }
    }

    /**
     * Compute and store hash for a confirmed frame.
     * Only called when frame is fully confirmed (all inputs received, no rollback pending).
     * IMPORTANT: Uses the snapshot for that frame, not current state, to ensure
     * both peers hash the same state even if they confirm at different times.
     * @param {number} frameNumber - The confirmed frame to hash
     */
    async _computeAndStoreConfirmedHash(frameNumber) {
        // Skip if hash already exists (e.g., from prior confirmation)
        if (this.confirmedHashHistory.has(frameNumber)) {
            return;
        }

        // Skip if state sync not supported
        if (!this.stateSyncSupported) {
            return;
        }

        // Get the snapshot for this frame - we MUST hash the state from that frame,
        // not the current state, to ensure deterministic comparison between peers
        const snapshotJson = this.stateSnapshots.get(frameNumber);
        if (!snapshotJson) {
            // No snapshot available for this frame - can happen if:
            // - Frame is older than maxSnapshots
            // - Snapshot was never saved (shouldn't happen in normal flow)
            p2pLog.debug(`No snapshot for confirmed frame ${frameNumber}, skipping hash`);
            return;
        }

        try {
            // Parse snapshot and hash only the env_state portion
            const snapshot = JSON.parse(snapshotJson);
            const hash = await this._computeHashFromState(snapshot.env_state);

            if (!hash) {
                p2pLog.warn(`Failed to compute hash from snapshot for frame ${frameNumber}`);
                return;
            }

            this.confirmedHashHistory.set(frameNumber, hash);

            // Queue hash for P2P exchange (EXCH-02: async, non-blocking)
            this.pendingHashExchange.push({ frame: frameNumber, hash: hash });

            p2pLog.debug(`Confirmed hash for frame ${frameNumber}: ${hash}`);

            // Attempt comparison - will succeed if we have peer hash (DETECT-01)
            this._attemptHashComparison(frameNumber);

            // Prune old entries to prevent unbounded growth
            this._pruneConfirmedHashHistory();
        } catch (e) {
            p2pLog.warn(`Failed to compute confirmed hash for frame ${frameNumber}: ${e}`);
        }
    }

    /**
     * Compute SHA-256 hash from a given state object (not current env state).
     * Used for hashing snapshots of past frames.
     * @param {Object} envState - The environment state to hash
     * @returns {string|null} 16-char truncated SHA-256 hash, or null on failure
     * @private
     */
    async _computeHashFromState(envState) {
        if (!envState) {
            return null;
        }

        const stateJson = JSON.stringify(envState);
        const hashResult = await this.pyodide.runPythonAsync(`
import json
import hashlib

def _normalize_floats(obj, precision=10):
    """Recursively normalize floats to fixed precision for deterministic hashing."""
    if isinstance(obj, float):
        return round(obj, precision)
    elif isinstance(obj, dict):
        return {k: _normalize_floats(v, precision) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_normalize_floats(item, precision) for item in obj]
    return obj

_state_to_hash = json.loads('''${stateJson.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}''')
_normalized_state = _normalize_floats(_state_to_hash)

# SHA-256 hash with deterministic JSON serialization (HASH-03)
_json_str = json.dumps(_normalized_state, sort_keys=True, separators=(',', ':'))
_hash = hashlib.sha256(_json_str.encode()).hexdigest()[:16]
_hash
        `);
        return hashResult;
    }

    /**
     * Remove old entries from confirmedHashHistory to prevent memory growth.
     * Keeps most recent confirmedHashHistoryMaxSize entries.
     */
    _pruneConfirmedHashHistory() {
        if (this.confirmedHashHistory.size <= this.confirmedHashHistoryMaxSize) {
            return;
        }

        // Map maintains insertion order - delete oldest entries
        const keysToDelete = [];
        for (const key of this.confirmedHashHistory.keys()) {
            if (this.confirmedHashHistory.size - keysToDelete.length <= this.confirmedHashHistoryMaxSize) {
                break;
            }
            keysToDelete.push(key);
        }
        for (const key of keysToDelete) {
            this.confirmedHashHistory.delete(key);
        }
    }

    /**
     * Send pending state hashes to peer via P2P DataChannel.
     * Called from step loop after _updateConfirmedFrame completes.
     * Skipped during rollback to avoid sending hashes from mid-replay state.
     * (EXCH-01: P2P DataChannel, EXCH-02: non-blocking, EXCH-04: binary format)
     */
    _exchangePendingHashes() {
        // Skip if rollback in progress (hash would be from mid-replay state)
        if (this.rollbackInProgress) {
            return;
        }

        // Skip if no P2P connection ready
        if (!this.webrtcManager?.isReady()) {
            // Keep hashes queued - will send when connection recovers
            return;
        }

        // Drain pending hash queue
        while (this.pendingHashExchange.length > 0) {
            const { frame, hash } = this.pendingHashExchange.shift();

            // Encode and send via P2P
            const packet = encodeStateHash(frame, hash);
            const sent = this.webrtcManager.send(packet);

            if (sent) {
                p2pLog.debug(`Sent hash for frame ${frame}: ${hash}`);
            } else {
                // Send failed (buffer full) - re-queue at front and stop
                // Better to delay than to lose hash data
                this.pendingHashExchange.unshift({ frame, hash });
                p2pLog.debug(`Hash send buffer full, re-queued frame ${frame}`);
                break;
            }
        }
    }

    /**
     * Handle received state hash from peer.
     * Stores hash in pendingPeerHashes for later comparison (Phase 13: DETECT-02).
     * @param {ArrayBuffer} buffer - Received P2P message
     */
    _handleStateHash(buffer) {
        const decoded = decodeStateHash(buffer);
        if (!decoded) {
            p2pLog.warn('Failed to decode state hash message');
            return;
        }

        const { frameNumber, hash } = decoded;

        // Store for comparison (DETECT-02: buffer until local catches up)
        this.pendingPeerHashes.set(frameNumber, hash);

        p2pLog.debug(`Received peer hash for frame ${frameNumber}: ${hash}`);

        // Attempt comparison - will succeed if we have local hash (DETECT-01)
        this._attemptHashComparison(frameNumber);
    }

    /**
     * Attempt to compare hashes for a given frame.
     * Called when either local hash is stored or peer hash is received.
     * Requires both hashes to exist for comparison. (DETECT-01, DETECT-02)
     * @param {number} frameNumber - Frame to compare
     */
    _attemptHashComparison(frameNumber) {
        // Skip during rollback - state is in flux
        if (this.rollbackInProgress) {
            return;
        }

        const ourHash = this.confirmedHashHistory.get(frameNumber);
        const peerHash = this.pendingPeerHashes.get(frameNumber);

        // Need both hashes to compare (DETECT-02: peer hash buffered until we catch up)
        if (!ourHash || !peerHash) {
            return;
        }

        // Remove from pending - we're about to process it
        this.pendingPeerHashes.delete(frameNumber);

        // Compare hashes
        if (ourHash === peerHash) {
            this._markFrameVerified(frameNumber);
        } else {
            this._handleDesync(frameNumber, ourHash, peerHash);
        }
    }

    /**
     * Mark a frame as mutually verified (both peers agree on hash).
     * Updates verifiedFrame to track highest verified frame. (DETECT-04)
     * @param {number} frameNumber - Frame that was verified
     */
    _markFrameVerified(frameNumber) {
        // Only update if this is a new high-water mark
        if (frameNumber > this.verifiedFrame) {
            this.verifiedFrame = frameNumber;
            p2pLog.debug(`Frame ${frameNumber} verified - hashes match`);
        }
    }

    /**
     * Handle a desync (hash mismatch) event.
     * Logs detailed event with frame, both hashes, timestamp, and state dump. (DETECT-01, DETECT-03, DETECT-05)
     * @param {number} frameNumber - Frame where mismatch occurred
     * @param {string} ourHash - Our computed hash for this frame
     * @param {string} peerHash - Peer's hash for this frame
     */
    async _handleDesync(frameNumber, ourHash, peerHash) {
        // Capture current state for debugging (DETECT-05)
        let stateDump = null;
        try {
            if (this.stateSyncSupported) {
                const stateJson = await this.pyodide.runPythonAsync(`
import json
_env_state_dump = env.get_state()
json.dumps(_env_state_dump, sort_keys=True, default=str)
`);
                stateDump = JSON.parse(stateJson);
            }
        } catch (e) {
            p2pLog.warn(`Failed to capture state dump for desync: ${e.message}`);
        }

        // Create desync event (DETECT-03)
        const desyncEvent = {
            frame: frameNumber,
            ourHash: ourHash,
            peerHash: peerHash,
            timestamp: Date.now(),
            stateDump: stateDump,
            currentFrame: this.frameNumber,
            verifiedFrameAtDesync: this.verifiedFrame
        };

        this.desyncEvents.push(desyncEvent);

        // Log with high visibility (DETECT-01: exact frame identified)
        p2pLog.warn(
            `DESYNC DETECTED at frame ${frameNumber}: ` +
            `ourHash=${ourHash}, peerHash=${peerHash}, ` +
            `currentFrame=${this.frameNumber}, lastVerified=${this.verifiedFrame}`
        );
    }

    async computeQuickStateHash() {
        /**
         * Compute SHA-256 hash of env_state with float normalization.
         * Uses SHA-256 for cross-platform reliability (HASH-03).
         * Normalizes floats to 10 decimal places before hashing for determinism (HASH-02).
         * Returns first 16 chars of SHA-256 hash for efficient storage/transmission.
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

def _normalize_floats(obj, precision=10):
    """Recursively normalize floats to fixed precision for deterministic hashing."""
    if isinstance(obj, float):
        return round(obj, precision)
    elif isinstance(obj, dict):
        return {k: _normalize_floats(v, precision) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_normalize_floats(item, precision) for item in obj]
    return obj

_env_state_for_hash = env.get_state()
_normalized_state = _normalize_floats(_env_state_for_hash)

# SHA-256 hash with deterministic JSON serialization (HASH-03)
# Using separators=(',', ':') for compact, consistent JSON output
_json_str = json.dumps(_normalized_state, sort_keys=True, separators=(',', ':'))
_hash = hashlib.sha256(_json_str.encode()).hexdigest()[:16]
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

    /**
     * Store frame data in the rollback-safe buffer.
     * Called after each step to record the frame's data.
     * On rollback, frames >= target are deleted and re-recorded with correct data.
     */
    storeFrameData(frameNumber, data) {
        this.frameDataBuffer.set(frameNumber, {
            actions: data.actions,
            rewards: data.rewards,
            terminateds: data.terminateds,
            truncateds: data.truncateds,
            infos: data.infos,
            isFocused: data.isFocused,
            timestamp: Date.now()
        });
    }

    /**
     * Clear frame data buffer entries from rollback target onwards.
     * Called at the start of rollback to remove predicted/incorrect data.
     */
    clearFrameDataFromRollback(targetFrame) {
        for (const frame of this.frameDataBuffer.keys()) {
            if (frame >= targetFrame) {
                this.frameDataBuffer.delete(frame);
            }
        }
        p2pLog.debug(`Cleared frame data buffer from frame ${targetFrame} onwards`);
    }

    /**
     * Export episode data from frameDataBuffer in the format expected by remoteGameLogger.
     * Called at episode end to build the correct, rollback-corrected data.
     * @returns {Object} Episode data in remoteGameLogger format
     */
    exportEpisodeDataFromBuffer() {
        const data = {
            actions: {},
            rewards: {},
            terminateds: {},
            truncateds: {},
            infos: {},
            isFocused: {},
            episode_num: [],
            t: [],
            timestamp: [],
            player_subjects: this.playerSubjects
        };

        // Get sorted frame numbers
        const sortedFrames = Array.from(this.frameDataBuffer.keys()).sort((a, b) => a - b);

        for (const frame of sortedFrames) {
            const frameData = this.frameDataBuffer.get(frame);
            if (!frameData) continue;

            // Add step number
            data.t.push(frame);
            data.episode_num.push(this.num_episodes);
            data.timestamp.push(frameData.timestamp);

            // Add per-agent data
            const addAgentData = (field, agentData) => {
                if (!agentData) return;
                for (const [agentId, value] of Object.entries(agentData)) {
                    if (!data[field][agentId]) {
                        data[field][agentId] = [];
                    }
                    data[field][agentId].push(value);
                }
            };

            // Add per-agent infos with flattening (infos.agentId.key instead of infos.agentId = {...})
            const addFlattenedInfos = (infosData) => {
                if (!infosData) return;
                for (const [agentId, infoDict] of Object.entries(infosData)) {
                    if (!infoDict || typeof infoDict !== 'object') {
                        // If infoDict is not an object, store it directly
                        if (!data.infos[agentId]) {
                            data.infos[agentId] = [];
                        }
                        data.infos[agentId].push(infoDict);
                        continue;
                    }
                    // Flatten the info dict: infos.agentId.key = value
                    for (const [key, value] of Object.entries(infoDict)) {
                        const flatKey = `${agentId}.${key}`;
                        if (!data.infos[flatKey]) {
                            data.infos[flatKey] = [];
                        }
                        data.infos[flatKey].push(value);
                    }
                }
            };

            addAgentData('actions', frameData.actions);
            addAgentData('rewards', frameData.rewards);
            addAgentData('terminateds', frameData.terminateds);
            addAgentData('truncateds', frameData.truncateds);
            addFlattenedInfos(frameData.infos);
            addAgentData('isFocused', frameData.isFocused);
        }

        return data;
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

        // Export episode data from the rollback-safe buffer
        // This ensures only correct, validated data is emitted
        if (this.sceneId) {
            this._emitEpisodeDataFromBuffer();
        }

        this.num_episodes += 1;

        if (this.num_episodes >= this.max_episodes) {
            this.state = "done";
            this._destroyTimerWorker();  // Clean up Web Worker timer (Phase 24)
            p2pLog.warn(`Game complete (${this.num_episodes}/${this.max_episodes} episodes)`);
        } else {
            this.shouldReset = true;
            p2pLog.debug(`Episode ${this.num_episodes}/${this.max_episodes} complete, will reset`);
        }
    }

    /**
     * Emit episode data from the rollback-safe frame buffer.
     * Uses msgpack encoding for efficient transmission.
     */
    _emitEpisodeDataFromBuffer() {
        if (!window.socket) {
            console.error('[_emitEpisodeDataFromBuffer] Socket not available');
            return;
        }

        const episodeData = this.exportEpisodeDataFromBuffer();

        // Skip if no data to send
        if (!episodeData || episodeData.t.length === 0) {
            console.log(`[_emitEpisodeDataFromBuffer] No data to emit for episode ${this.num_episodes}`);
            return;
        }

        // Encode to msgpack for efficient transmission
        const binaryData = msgpack.encode(episodeData);

        console.log(`[_emitEpisodeDataFromBuffer] Emitting episode ${this.num_episodes} data: ${episodeData.t.length} frames, ${binaryData.byteLength} bytes`);

        window.socket.emit("emit_episode_data", {
            data: binaryData,
            scene_id: this.sceneId,
            episode_num: this.num_episodes,
            session_id: window.sessionId,
            interactiveGymGlobals: window.interactiveGymGlobals
        });

        // Clear the buffer after emitting
        this.frameDataBuffer.clear();
    }

    /**
     * Override isDone() to prevent scene advancement when partner disconnects or focus loss timeout.
     * When partnerDisconnectedTerminal or focusLossTimeoutTerminal is true, the overlay is the final state -
     * the participant should NOT be advanced to the next scene.
     * @returns {boolean} True if game is done AND we should advance to next scene
     */
    isDone() {
        // Partner disconnection is a terminal state - don't trigger scene advancement
        if (this.partnerDisconnectedTerminal) {
            return false;
        }
        // Focus loss timeout is a terminal state - don't trigger scene advancement (Phase 27)
        if (this.focusLossTimeoutTerminal) {
            return false;
        }
        // Normal game completion - allow scene advancement
        return this.state === "done";
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
        p2pLog.warn(
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

        // Validation data export for sync analysis
        if (getLogLevel() >= LOG_LEVELS.debug) {
            const validationData = this.exportValidationData();
            p2pLog.debug('Validation export:', JSON.stringify(validationData, null, 2));

            // Log summary at info level always
            p2pLog.info(
                `Sync validation: ${validationData.summary.verifiedFrame}/${validationData.summary.totalFrames} frames verified, ` +
                `${validationData.summary.desyncCount} desyncs, ${validationData.summary.hashesComputed} hashes`
            );
        }
    }

    // ========== Continuous Monitoring Methods (Phase 16) ==========

    /**
     * Handle mid-game exclusion from continuous monitoring.
     * Stops game, shows message, notifies server.
     *
     * @param {string} reason - Exclusion reason ('sustained_ping', 'tab_hidden')
     * @param {string} message - Message to display to participant
     */
    async _handleMidGameExclusion(reason, message) {
        p2pLog.warn(`Mid-game exclusion: ${reason}`);

        // Stop game loop
        this.state = "done";
        this.episodeComplete = true;

        // Pause monitoring
        if (this.continuousMonitor) {
            this.continuousMonitor.pause();
        }

        // Show exclusion message
        this._showMidGameExclusionUI(message);

        // Clean up Web Worker timer (Phase 24)
        this._destroyTimerWorker();

        // Notify server (which will notify partner in Phase 17)
        socket.emit('mid_game_exclusion', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            reason: reason,
            frame_number: this.frameNumber,
            timestamp: Date.now()
        });

        // Stop latency telemetry (Phase 22) - keep data for export
        if (this.latencyTelemetry) {
            this.latencyTelemetry.stop();
        }

        // Clean up WebRTC
        if (this.webrtcManager) {
            this.webrtcManager.close();
        }

        // Mark own session as partial before export
        this.sessionPartialInfo = {
            isPartial: true,
            terminationReason: reason,  // 'sustained_ping' or 'tab_hidden'
            terminationFrame: this.frameNumber
        };

        // Export metrics before leaving game
        if (this.gameId && this.sceneId) {
            this.emitMultiplayerMetrics(this.sceneId);
        }

        // Trigger end game redirect
        socket.emit('leave_game', { session_id: window.sessionId });
        socket.emit('end_game_request_redirect', {
            mid_game_exclusion: true,
            reason: reason
        });
    }

    /**
     * Execute continuous callback by sending context to server (Phase 18).
     * Async - sends request and continues game loop. Result handled by socket listener.
     */
    _executeContinuousCallback() {
        if (!this.continuousMonitor) return;

        this.continuousMonitor.setCallbackPending(true);

        const context = {
            ping: window.currentPing || 0,
            is_tab_hidden: document.hidden,
            tab_hidden_duration_ms: this.continuousMonitor.tabHiddenAt
                ? Date.now() - this.continuousMonitor.tabHiddenAt
                : 0,
            frame_number: this.frameNumber,
            episode_number: this.currentEpisode || 0
        };

        socket.emit('execute_continuous_callback', {
            session_id: window.sessionId,
            scene_id: this.sceneId,
            context: context
        });
    }

    /**
     * Show mid-game exclusion UI overlay.
     * @param {string} message - Exclusion message
     */
    _showMidGameExclusionUI(message) {
        // Create overlay if it doesn't exist
        let overlay = document.getElementById('monitorExclusionOverlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'monitorExclusionOverlay';
            overlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.85);
                display: flex;
                justify-content: center;
                align-items: center;
                z-index: 10000;
            `;
            document.body.appendChild(overlay);
        }

        overlay.innerHTML = `
            <div style="
                background: white;
                padding: 40px;
                border-radius: 8px;
                max-width: 500px;
                text-align: center;
            ">
                <h2 style="color: #c00; margin-bottom: 20px;">Game Ended</h2>
                <p style="font-size: 16px; margin-bottom: 20px;">${message}</p>
                <p style="color: #666; font-size: 14px;">You will be redirected shortly...</p>
            </div>
        `;
        overlay.style.display = 'flex';
    }

    /**
     * Show partner excluded notification (less alarming than own exclusion).
     * Uses neutral styling - gray header instead of red.
     * @param {string} message - Notification message
     */
    _showPartnerExcludedUI(message) {
        let overlay = document.getElementById('partnerExcludedOverlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.id = 'partnerExcludedOverlay';
            overlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.75);
                display: flex;
                justify-content: center;
                align-items: center;
                z-index: 10000;
            `;
            document.body.appendChild(overlay);
        }

        // Use neutral styling (not red like exclusion)
        overlay.innerHTML = `
            <div style="
                background: white;
                padding: 40px;
                border-radius: 8px;
                max-width: 500px;
                text-align: center;
            ">
                <h2 style="color: #333; margin-bottom: 20px;">Game Ended</h2>
                <p style="font-size: 16px; margin-bottom: 20px;">${message}</p>
                <p style="color: #666; font-size: 14px;">Your game data has been saved. You will be redirected shortly...</p>
            </div>
        `;
        overlay.style.display = 'flex';
    }

    /**
     * Show warning overlay (semi-transparent, doesn't block game).
     * @param {string} message - Warning message
     */
    _showMonitorWarning(message) {
        // Create warning banner if it doesn't exist
        let banner = document.getElementById('monitorWarningBanner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'monitorWarningBanner';
            banner.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                padding: 15px;
                background: rgba(255, 200, 0, 0.95);
                color: #000;
                text-align: center;
                font-weight: bold;
                z-index: 9999;
                box-shadow: 0 2px 10px rgba(0,0,0,0.3);
            `;
            document.body.appendChild(banner);
        }

        banner.textContent = message;
        banner.style.display = 'block';

        // Auto-hide after 5 seconds
        setTimeout(() => {
            if (banner) {
                banner.style.display = 'none';
            }
        }, 5000);
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
        p2pLog.debug(`P2P RESYNC: applying peer state frame=${frameNumber} step=${stepNum}`);

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

        // DEBUG: Log all remote inputs received (use info level to ensure visibility)
        p2pLog.debug(`STORE_INPUT: player=${playerIdStr} frame=${frameNumber} action=${action} myFrame=${this.frameNumber}`);

        // Ensure input buffer exists for this frame
        if (!this.inputBuffer.has(frameNumber)) {
            this.inputBuffer.set(frameNumber, new Map());
        }

        const frameInputs = this.inputBuffer.get(frameNumber);

        // Check if we already have an input for this player at this frame
        if (frameInputs.has(playerIdStr)) {
            // Already have confirmed input, ignore duplicate
            p2pLog.debug(`STORE_INPUT: DUPLICATE player=${playerIdStr} frame=${frameNumber} (existing=${frameInputs.get(playerIdStr)})`);
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
        // GGPO: Skip rollback detection if we're already in a rollback (prevents nested rollbacks)
        if (this.rollbackInProgress) {
            // Input is stored above, but don't trigger new rollback during replay
            return;
        }

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
                    p2pLog.warn(
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

        // DEBUG: Log local input storage
        if (targetFrame < 50) {
            p2pLog.debug(`LOCAL_INPUT: player=${myPlayerIdStr} currentFrame=${currentFrame} targetFrame=${targetFrame} action=${action}`);
        }

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

            // Parse the Python snapshot and add JavaScript-side state
            const snapshotData = JSON.parse(stateJson);
            snapshotData.cumulative_rewards = {...this.cumulative_rewards};  // Clone rewards
            snapshotData.step_num = this.step_num;

            this.stateSnapshots.set(frameNumber, JSON.stringify(snapshotData));

            // Log snapshot save with agent state summary for debugging
            const agentStates = snapshotData.env_state?.agents || {};
            const agentSummary = Object.entries(agentStates).map(([id, a]) =>
                `${id}:pos=${a.pos},inv=${a.inventory?.length || 0}`
            ).join(' ');
            p2pLog.debug(`SAVE_SNAPSHOT: frame=${frameNumber} agents=[${agentSummary}]`);

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

            // Log what we're restoring for debugging
            const snapshotData = JSON.parse(stateJson);
            const agentStates = snapshotData.env_state?.agents || {};
            const agentSummary = Object.entries(agentStates).map(([id, a]) =>
                `${id}:pos=${a.pos},inv=${a.inventory?.length || 0}`
            ).join(' ');
            p2pLog.debug(`LOAD_SNAPSHOT: frame=${frameNumber} agents=[${agentSummary}]`);

            // Verify state restoration with Python-side logging
            const verifyResult = await this.pyodide.runPythonAsync(`
import json
import numpy as np
import random

_snapshot = json.loads('''${escapedJson}''')

# Get state BEFORE restore for comparison
_before_state = env.get_state()

# Restore environment state
env.set_state(_snapshot['env_state'])

# Get state AFTER restore to verify
_after_state = env.get_state()

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

# Return verification info
json.dumps({
    'snapshot_t': _snapshot['env_state'].get('t', 'N/A'),
    'before_t': _before_state.get('t', 'N/A'),
    'after_t': _after_state.get('t', 'N/A'),
    'match': _snapshot['env_state'] == _after_state
})
            `);
            const verify = JSON.parse(verifyResult);
            p2pLog.debug(`VERIFY_RESTORE: snapshot_t=${verify.snapshot_t} before_t=${verify.before_t} after_t=${verify.after_t} match=${verify.match}`);

            // Restore JavaScript-side state (cumulative_rewards, step_num)
            if (snapshotData.cumulative_rewards) {
                this.cumulative_rewards = {...snapshotData.cumulative_rewards};
                p2pLog.debug(`RESTORE_REWARDS: frame=${frameNumber} rewards=${JSON.stringify(this.cumulative_rewards)}`);
            }
            if (snapshotData.step_num !== undefined) {
                this.step_num = snapshotData.step_num;
            }

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
        const rollbackStartTime = performance.now();
        const currentFrame = this.frameNumber;
        const rollbackFrames = currentFrame - targetFrame;

        // Always log rollbacks - they're expensive and directly cause perceived lag
        console.warn(`[ROLLBACK-START] frame=${currentFrame} → ${targetFrame} (${rollbackFrames} frames to replay)`);
        p2pLog.debug(`Performing rollback: ${currentFrame} → ${targetFrame} (${rollbackFrames} frames)`);

        // Skip rollback if state sync not supported - can't restore state
        if (!this.stateSyncSupported) {
            p2pLog.warn(`Cannot rollback - state sync not supported (env missing get_state/set_state)`);
            return false;
        }

        // Set rollback guard to prevent nested rollbacks
        this.rollbackInProgress = true;

        // Invalidate confirmed hashes from rollback point onward
        // These hashes are for states that are about to be overwritten
        for (const frame of this.confirmedHashHistory.keys()) {
            if (frame >= targetFrame) {
                this.confirmedHashHistory.delete(frame);
            }
        }
        p2pLog.debug(`Invalidated confirmed hashes >= frame ${targetFrame}`);

        // Invalidate pending peer hashes from rollback point onward (EXCH-03)
        // These will be re-received when peer re-confirms after their rollback
        for (const frame of this.pendingPeerHashes.keys()) {
            if (frame >= targetFrame) {
                this.pendingPeerHashes.delete(frame);
            }
        }

        // Clear outbound queue - these hashes are for states being overwritten
        this.pendingHashExchange = this.pendingHashExchange.filter(h => h.frame < targetFrame);

        // Clear frame data buffer from rollback point onwards
        // This ensures predicted/incorrect data is replaced with correct data during replay
        this.clearFrameDataFromRollback(targetFrame);

        // Also reset confirmedFrame to before rollback point
        // (it will be recalculated after replay completes via _updateConfirmedFrame)
        this.confirmedFrame = Math.min(this.confirmedFrame, targetFrame - 1);

        // Reset verifiedFrame - cannot verify frames that are being replayed (DETECT-04)
        this.verifiedFrame = Math.min(this.verifiedFrame, targetFrame - 1);

        try {
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

            // GGPO-style: Build all replay frame actions FIRST (in JavaScript)
            // Then execute ALL env.step() calls in a single Python batch
            // This prevents event loop yields during replay that could allow new inputs
            const replayFrames = [];

            for (let frame = snapshotFrame; frame < currentFrame; frame++) {
                // Get human inputs from buffer (now has confirmed inputs including the late one)
                // Note: getInputsForFrame may still use prediction if inputs haven't arrived yet
                // Pass trackPredictions=false during replay to avoid re-marking frames
                const humanInputs = this.getInputsForFrame(frame, playerIds, false);

                // Log what inputs we're using during replay
                const confirmedForFrame = [];
                const predictedForFrame = [];
                const frameInputs = this.inputBuffer.get(frame);

                // DEBUG: Log input buffer contents for this frame
                if (frameInputs) {
                    const bufferContents = Array.from(frameInputs.entries()).map(([k, v]) => `${k}:${v}`).join(',');
                    p2pLog.debug(`REPLAY_BUFFER: frame=${frame} buffer={${bufferContents}} playerIds=[${playerIds.join(',')}]`);
                } else {
                    p2pLog.debug(`REPLAY_BUFFER: frame=${frame} buffer=EMPTY playerIds=[${playerIds.join(',')}]`);
                }

                for (const pid of playerIds) {
                    if (frameInputs && frameInputs.has(String(pid))) {
                        confirmedForFrame.push(pid);
                    } else {
                        predictedForFrame.push(pid);
                    }
                }

                // If we're still using prediction during replay, RE-ADD to predictedFrames
                // This is critical: when the real input arrives later, we need to know
                // this frame still needs rollback correction
                if (predictedForFrame.length > 0) {
                    this.predictedFrames.add(frame);
                    p2pLog.debug(`Replay frame ${frame}: still missing inputs for [${predictedForFrame.join(',')}] - re-marked as predicted`);
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

                // Record the corrected actions in JavaScript
                this.actionSequence.push({
                    frame: frame,
                    actions: {...envActions},
                    isFocused: this.focusManager ? !this.focusManager.isBackgrounded : true
                });

                // Update action counts with corrected actions
                for (const [playerId, action] of Object.entries(envActions)) {
                    if (!this.actionCounts[playerId]) {
                        this.actionCounts[playerId] = {};
                    }
                    const actionKey = String(action);
                    this.actionCounts[playerId][actionKey] = (this.actionCounts[playerId][actionKey] || 0) + 1;
                }

                // Add to replay batch
                replayFrames.push({
                    frame: frame,
                    actions: envActions
                });
            }

            // Execute ALL replay steps in a single Python call (no event loop yields)
            // This is the key GGPO optimization - synchronous replay prevents race conditions
            if (replayFrames.length > 0) {
                // Log replay actions for debugging
                const replayActionsStr = replayFrames.map(rf => `${rf.frame}:{${Object.entries(rf.actions).map(([k,v]) => `${k}:${v}`).join(',')}}`).join(' ');
                p2pLog.debug(`REPLAY: snapshotFrame=${snapshotFrame} frames=[${replayActionsStr}]`);

                const replayVerify = await this.pyodide.runPythonAsync(`
import json
import hashlib
import numpy as np
import random
_replay_frames = ${JSON.stringify(replayFrames)}
_snapshot_interval = ${this.snapshotInterval}
_t_before_replay = env.t if hasattr(env, 't') else 'N/A'
_replay_log = []
_snapshots_to_save = {}
_cumulative_rewards = {}  # Track rewards accumulated during replay
for _rf in _replay_frames:
    _frame = _rf['frame']
    _pre_state = env.get_state()
    _pre_hash = hashlib.md5(json.dumps(_pre_state, sort_keys=True).encode()).hexdigest()[:8]

    # Save snapshot BEFORE stepping if this frame is on snapshot interval
    # This updates old incorrect snapshots with correct state after rollback
    if _frame % _snapshot_interval == 0:
        _np_rng_state = np.random.get_state()
        _np_rng_serializable = (
            _np_rng_state[0],
            _np_rng_state[1].tolist(),
            _np_rng_state[2],
            _np_rng_state[3],
            _np_rng_state[4]
        )
        _py_rng_state = random.getstate()
        _snapshots_to_save[_frame] = {
            'env_state': _pre_state,
            'np_rng_state': _np_rng_serializable,
            'py_rng_state': _py_rng_state
        }

    _actions = {int(k) if str(k).isdigit() else k: v for k, v in _rf['actions'].items()}
    _obs, _rewards, _term, _trunc, _info = env.step(_actions)
    # Convert rewards/term/trunc/info to dicts with string keys for JSON
    _rewards_dict = {str(k): v for k, v in _rewards.items()} if isinstance(_rewards, dict) else {'human': _rewards}
    _term_dict = {str(k): v for k, v in _term.items()} if isinstance(_term, dict) else {'human': _term}
    _trunc_dict = {str(k): v for k, v in _trunc.items()} if isinstance(_trunc, dict) else {'human': _trunc}
    _info_dict = {str(k): v for k, v in _info.items()} if isinstance(_info, dict) else {'human': _info}
    # Accumulate rewards from replay (critical for HUD sync)
    if isinstance(_rewards, dict):
        for _k, _v in _rewards.items():
            _cumulative_rewards[str(_k)] = _cumulative_rewards.get(str(_k), 0) + _v
    elif isinstance(_rewards, (int, float)):
        _cumulative_rewards['human'] = _cumulative_rewards.get('human', 0) + _rewards
    _post_state = env.get_state()
    _post_hash = hashlib.md5(json.dumps(_post_state, sort_keys=True).encode()).hexdigest()[:8]
    # Include per-frame data for rollback-safe logging
    _replay_log.append({
        'frame': _frame,
        'actions': _rf['actions'],
        'rewards': _rewards_dict,
        'terminateds': _term_dict,
        'truncateds': _trunc_dict,
        'infos': _info_dict,
        'pre_hash': _pre_hash,
        'post_hash': _post_hash
    })
_t_after_replay = env.t if hasattr(env, 't') else 'N/A'
_state_after = env.get_state()
_state_hash = hashlib.md5(json.dumps(_state_after, sort_keys=True).encode()).hexdigest()[:8]
json.dumps({'t_before': _t_before_replay, 't_after': _t_after_replay, 'num_steps': len(_replay_frames), 'state_hash': _state_hash, 'replay_log': _replay_log, 'snapshots': {str(k): v for k, v in _snapshots_to_save.items()}, 'replay_rewards': _cumulative_rewards})
                `);
                const replayInfo = JSON.parse(replayVerify);
                // Log each replay frame for comparison with client A
                for (const entry of replayInfo.replay_log) {
                    const actionsStr = Object.entries(entry.actions).map(([k,v]) => `${k}:${v}`).join(',');
                    p2pLog.debug(`REPLAY_FRAME: ${entry.frame} pre_hash=${entry.pre_hash} actions={${actionsStr}} post_hash=${entry.post_hash}`);
                }
                p2pLog.debug(`REPLAY_DONE: t_before=${replayInfo.t_before} t_after=${replayInfo.t_after} final_hash=${replayInfo.state_hash}`);

                // Update snapshots with corrected state from replay
                // This is critical: old snapshots had pre-rollback (incorrect) state
                if (replayInfo.snapshots) {
                    for (const [frameStr, snapshotData] of Object.entries(replayInfo.snapshots)) {
                        const frame = parseInt(frameStr);
                        // Add cumulative_rewards to snapshot for future rollbacks
                        snapshotData.cumulative_rewards = {...this.cumulative_rewards};
                        snapshotData.step_num = this.step_num;
                        this.stateSnapshots.set(frame, JSON.stringify(snapshotData));
                        p2pLog.debug(`SNAPSHOT_UPDATED: frame=${frame} (corrected after rollback)`);
                    }
                }

                // Add rewards accumulated during replay to cumulative_rewards
                // This is critical: rewards from replayed frames were lost when we rolled back
                if (replayInfo.replay_rewards) {
                    for (const [playerId, reward] of Object.entries(replayInfo.replay_rewards)) {
                        if (this.cumulative_rewards[playerId] !== undefined) {
                            this.cumulative_rewards[playerId] += reward;
                        } else {
                            this.cumulative_rewards[playerId] = reward;
                        }
                    }
                    p2pLog.debug(`REPLAY_REWARDS: added ${JSON.stringify(replayInfo.replay_rewards)} -> total=${JSON.stringify(this.cumulative_rewards)}`);
                    // Update HUD to reflect corrected rewards
                    ui_utils.updateHUDText(this.getHUDText());
                }

                // Update step_num to account for replayed frames
                this.step_num += replayInfo.num_steps;

                // Store corrected frame data in the rollback-safe buffer
                // This replaces any previously predicted data with correct data
                for (const entry of replayInfo.replay_log) {
                    this.storeFrameData(entry.frame, {
                        actions: entry.actions,
                        rewards: entry.rewards,
                        terminateds: entry.terminateds,
                        truncateds: entry.truncateds,
                        infos: entry.infos,
                        isFocused: this.focusManager ? !this.focusManager.isBackgrounded : true
                    });
                }
                p2pLog.debug(`Stored ${replayInfo.replay_log.length} corrected frames in data buffer`);
            }

            // Update JS frame counter to match Python state
            this.frameNumber = currentFrame;

            p2pLog.debug(`REPLAY_DONE: jsFrame=${this.frameNumber}`);
            return true;
        } finally {
            // Always clear rollback guard
            this.rollbackInProgress = false;
        }
    }

    /**
     * Fast-forward through buffered inputs when returning from background state.
     * Phase 26: Called on first tick after tab is foregrounded.
     *
     * Similar to performRollback, but processes buffered partner inputs
     * to catch up to current game state after being backgrounded.
     *
     * Safety limits prevent browser freeze on long background periods.
     */
    async _performFastForward() {
        // Drain buffered inputs from FocusManager
        const bufferedInputs = this.focusManager.drainBufferedInputs();
        if (bufferedInputs.length === 0) {
            p2pLog.debug('Fast-forward: no buffered inputs to process');
            return;
        }

        const startTime = performance.now();
        const startFrame = this.frameNumber;

        // Safety limit - generous since we're not rendering during fast-forward
        const MAX_FRAMES = 1000;  // ~100 seconds at 10fps

        p2pLog.warn(`FAST-FORWARD: starting from frame ${startFrame}, ${bufferedInputs.length} buffered packets`);

        // 1. Inject buffered inputs into GGPO input buffer
        // Track maxFrame from packet.currentFrame (partner's simulation frame at send time)
        // This is more reliable than input.frame when packets are lost due to unreliable delivery
        let maxFrame = this.frameNumber;
        for (const packet of bufferedInputs) {
            // Packets have format: {playerId, inputs: [{action, frame}, ...], currentFrame}
            // Use currentFrame as target - it's where partner's simulation actually is
            maxFrame = Math.max(maxFrame, packet.currentFrame);
            for (const input of packet.inputs) {
                this.storeRemoteInput(packet.playerId, input.action, input.frame);
            }
        }

        // 2. Determine how many frames to process
        const framesToProcess = maxFrame - this.frameNumber;
        p2pLog.info(`FAST-FORWARD: target frame ${maxFrame}, current ${this.frameNumber}, need ${framesToProcess} frames`);
        if (framesToProcess <= 0) {
            p2pLog.debug('Fast-forward: already caught up or ahead');
            return;
        }

        // Get human player IDs for input retrieval
        const humanPlayerIds = Object.entries(this.policyMapping)
            .filter(([_, policy]) => policy === 'human')
            .map(([id, _]) => String(id));

        // Find the remote player ID (the partner whose inputs we need)
        const remotePlayerId = humanPlayerIds.find(id => id !== String(this.myPlayerId));

        // 3. Check for missing inputs and request them from partner
        if (remotePlayerId) {
            const missingFrames = [];
            for (let frame = this.frameNumber; frame < maxFrame; frame++) {
                const frameInputs = this.inputBuffer.get(frame);
                if (!frameInputs || !frameInputs.has(remotePlayerId)) {
                    missingFrames.push(frame);
                }
            }

            if (missingFrames.length > 0) {
                const missingStart = missingFrames[0];
                const missingEnd = missingFrames[missingFrames.length - 1];
                p2pLog.warn(`FAST-FORWARD: missing ${missingFrames.length} inputs for player ${remotePlayerId} (frames ${missingStart}-${missingEnd})`);

                // Request missing inputs from partner
                try {
                    p2pLog.info(`FAST-FORWARD: requesting inputs from partner...`);
                    const receivedCount = await this._requestMissingInputs(missingStart, missingEnd, 3000);
                    p2pLog.info(`FAST-FORWARD: received ${receivedCount} inputs from partner`);
                } catch (err) {
                    p2pLog.error(`FAST-FORWARD: failed to get missing inputs: ${err.message}`);
                    // Continue anyway - we'll use prediction for missing frames
                    // This is not ideal but prevents getting stuck
                }
            } else {
                p2pLog.info('FAST-FORWARD: all remote inputs available');
            }
        }

        // 4. Set rollback guard to prevent nested operations
        this.rollbackInProgress = true;

        let framesProcessed = 0;

        try {
            // 5. Build batch of frames to process (like rollback replay)
            const fastForwardFrames = [];
            let lastBotActions = {...this.lastExecutedActions};

            for (let frame = this.frameNumber; frame < maxFrame && fastForwardFrames.length < MAX_FRAMES; frame++) {
                // Get inputs for this frame (confirmed from buffer, predicted if missing)
                const inputs = this.getInputsForFrame(frame, humanPlayerIds, false);

                // Build final actions for all agents
                const frameActions = {};
                for (const [agentId, policy] of Object.entries(this.policyMapping)) {
                    if (policy === 'human') {
                        frameActions[agentId] = inputs[String(agentId)] ?? this.defaultAction;
                    } else {
                        // Bot: use last executed action or default
                        frameActions[agentId] = lastBotActions[agentId] ?? this.defaultAction;
                    }
                }

                // Track for next frame's bot action prediction
                for (const [agentId, action] of Object.entries(frameActions)) {
                    lastBotActions[agentId] = action;
                }

                fastForwardFrames.push({
                    frame: frame,
                    actions: frameActions
                });

                // Record in action sequence
                // Note: These frames occurred while we were backgrounded, so isFocused=false
                this.actionSequence.push({
                    frame: frame,
                    actions: {...frameActions},
                    isFocused: false
                });
            }

            if (fastForwardFrames.length === 0) {
                p2pLog.debug('Fast-forward: no frames to process');
                return;
            }

            // 5b. Build focus state for fast-forward frames
            // Local player was backgrounded; partner was focused (they sent us inputs)
            const focusStateForFF = {};
            for (const playerId of humanPlayerIds) {
                focusStateForFF[playerId] = String(playerId) !== String(this.myPlayerId);
            }

            // 6. Execute ALL fast-forward steps in a single Python call (no rendering)
            // This is much faster than calling stepWithActions for each frame
            // Track per-frame data for rollback-safe logging
            p2pLog.info(`FAST-FORWARD: batch stepping ${fastForwardFrames.length} frames`);

            const result = await this.pyodide.runPythonAsync(`
import json
import numpy as np
_ff_frames = ${JSON.stringify(fastForwardFrames)}
_cumulative_rewards = {}
_per_frame_data = []
for _ff in _ff_frames:
    _frame = _ff['frame']
    _actions = {int(k) if str(k).isdigit() else k: v for k, v in _ff['actions'].items()}
    _obs, _rewards, _terms, _truncs, _infos = env.step(_actions)
    # Convert to dicts with string keys for JSON
    _rewards_dict = {str(k): v for k, v in _rewards.items()} if isinstance(_rewards, dict) else {'human': _rewards}
    _term_dict = {str(k): v for k, v in _terms.items()} if isinstance(_terms, dict) else {'human': _terms}
    _trunc_dict = {str(k): v for k, v in _truncs.items()} if isinstance(_truncs, dict) else {'human': _truncs}
    _info_dict = {str(k): v for k, v in _infos.items()} if isinstance(_infos, dict) else {'human': _infos}
    # Store per-frame data
    _per_frame_data.append({
        'frame': _frame,
        'actions': _ff['actions'],
        'rewards': _rewards_dict,
        'terminateds': _term_dict,
        'truncateds': _trunc_dict,
        'infos': _info_dict
    })
    # Accumulate rewards
    for _agent_id, _reward in _rewards.items():
        if _agent_id not in _cumulative_rewards:
            _cumulative_rewards[_agent_id] = 0
        _cumulative_rewards[_agent_id] += _reward
json.dumps({'cumulative_rewards': {str(k): v for k, v in _cumulative_rewards.items()}, 'per_frame_data': _per_frame_data})
            `);

            // Parse result and update state
            const ffResult = JSON.parse(result);

            // Update cumulative rewards from fast-forward
            if (ffResult.cumulative_rewards) {
                for (const [key, value] of Object.entries(ffResult.cumulative_rewards)) {
                    if (this.cumulative_rewards[key] !== undefined) {
                        this.cumulative_rewards[key] += value;
                    } else {
                        this.cumulative_rewards[key] = value;
                    }
                }
            }

            // Store per-frame data in the rollback-safe buffer
            // Note: isFocused=false for local player during fast-forward
            for (const frameData of ffResult.per_frame_data) {
                this.storeFrameData(frameData.frame, {
                    actions: frameData.actions,
                    rewards: frameData.rewards,
                    terminateds: frameData.terminateds,
                    truncateds: frameData.truncateds,
                    infos: frameData.infos,
                    isFocused: focusStateForFF
                });
            }
            p2pLog.debug(`Stored ${ffResult.per_frame_data.length} fast-forward frames in data buffer`);

            framesProcessed = fastForwardFrames.length;

            // Update frame number, step count, and tracking
            this.frameNumber = this.frameNumber + framesProcessed;
            this.step_num += framesProcessed;
            this.lastExecutedActions = lastBotActions;

            // Update confirmedFrame to match - all fast-forwarded frames used real inputs
            // This prevents GGPO from thinking we have many unconfirmed frames
            this.confirmedFrame = this.frameNumber - 1;

            // Update HUD to reflect fast-forwarded state
            ui_utils.updateHUDText(this.getHUDText());

            // Clear old snapshots that are now before our confirmed frame
            // This prevents rollback to pre-fast-forward state
            for (const [snapFrame, _] of this.stateSnapshots) {
                if (snapFrame < this.confirmedFrame - 30) {  // Keep some buffer
                    this.stateSnapshots.delete(snapFrame);
                }
            }

            // Clear predicted frames - fast-forward resolved all predictions
            this.predictedFrames.clear();

            // Prune input buffer after batch processing
            this.pruneInputBuffer();

            // Log if we hit limit
            if (framesProcessed >= MAX_FRAMES && this.frameNumber < maxFrame) {
                p2pLog.warn(`Fast-forward hit frame limit (${MAX_FRAMES}), remaining ${maxFrame - this.frameNumber} frames will catch up normally`);
            }

        } finally {
            // 7. Always clear rollback guard
            this.rollbackInProgress = false;
        }

        const elapsed = performance.now() - startTime;
        p2pLog.warn(
            `FAST-FORWARD: ${startFrame} -> ${this.frameNumber} ` +
            `(${framesProcessed} frames in ${elapsed.toFixed(1)}ms)`
        );

        // Send catch-up inputs to partner so they can confirm our defaultAction frames
        // During background, we sent nothing - partner predicted us as defaultAction
        // Now we confirm that prediction was correct by sending the actual inputs
        if (this.webrtcManager?.isReady() && framesProcessed > 0) {
            const catchUpInputs = [];
            for (let frame = startFrame; frame < this.frameNumber; frame++) {
                catchUpInputs.push({ action: this.defaultAction, frame: frame });
            }

            // Send in batches to avoid oversized packets
            const BATCH_SIZE = 50;
            for (let i = 0; i < catchUpInputs.length; i += BATCH_SIZE) {
                const batch = catchUpInputs.slice(i, i + BATCH_SIZE);
                const packet = encodeInputPacket(
                    this.myPlayerId,
                    this.frameNumber,  // currentFrame for the packet
                    batch
                );
                this.webrtcManager.send(packet);
            }
            p2pLog.info(`Sent ${catchUpInputs.length} catch-up inputs to partner (frames ${startFrame}-${this.frameNumber - 1})`);
        }
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

        // CRITICAL: If a rollback was triggered, release delayed inputs for frames
        // that will be replayed. Future inputs stay delayed to simulate persistent latency.
        if (this.pendingRollbackFrame !== null && this.debugDelayedInputQueue.length > 0) {
            const rollbackTarget = this.pendingRollbackFrame;
            const forReplay = [];
            const keepDelayed = [];

            for (const item of this.debugDelayedInputQueue) {
                // Release inputs for frames that will be replayed (rollback target to current frame)
                // These are needed NOW for correct replay
                if (item.frameNumber >= rollbackTarget && item.frameNumber < this.frameNumber) {
                    forReplay.push(item);
                } else {
                    // Keep future inputs delayed to simulate persistent poor connection
                    keepDelayed.push(item);
                }
            }

            this.debugDelayedInputQueue = keepDelayed;

            if (forReplay.length > 0) {
                p2pLog.debug(`[DEBUG-DELAY] Releasing ${forReplay.length} inputs for rollback replay (frames ${rollbackTarget}-${this.frameNumber - 1})`);
                for (const item of forReplay) {
                    p2pLog.debug(`[DEBUG-DELAY] Released for replay: player=${item.playerId} frame=${item.frameNumber}`);
                    this.storeRemoteInput(item.playerId, item.action, item.frameNumber);
                }
            }
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
     * Preserves cumulative validation data for full session export.
     */
    clearGGPOState() {
        // Archive current episode data to cumulative validation before clearing
        this._archiveEpisodeValidationData();

        this.inputBuffer.clear();
        this.localInputQueue = [];
        this.stateSnapshots.clear();
        this.lastConfirmedActions = {};
        this.predictedFrames.clear();
        this.confirmedFrame = -1;
        this.pendingRollbackFrame = null;
        this.rollbackCount = 0;
        this.maxRollbackFrames = 0;

        // Clear confirmed hash history on episode reset (HASH-04)
        this.confirmedHashHistory.clear();

        // Clear hash exchange structures for new episode (EXCH-03)
        this.pendingHashExchange = [];
        this.pendingPeerHashes.clear();

        // Clear mismatch detection state for new episode (DETECT-03, DETECT-04)
        this.verifiedFrame = -1;
        this.desyncEvents = [];

        // Clear debug delayed input queue
        this.debugDelayedInputQueue = [];

        // Clear GGPO-style input queues and rollback guard
        this.pendingInputPackets = [];
        this.pendingSocketIOInputs = [];
        this.rollbackInProgress = false;

        // NOTE: Do NOT close WebRTC connection here - it persists across episodes
        // WebRTC is only closed when the game session ends (in destroy/cleanup)

        // Reset P2P input sender for new episode
        if (this.p2pInputSender) {
            this.p2pInputSender.reset();
        }

        // Phase 25: Reset focus tracking for new episode
        if (this.focusManager) {
            this.focusManager.reset();
        }

        // Clear global pressed keys to prevent stale inputs from previous episode
        clearHumanInputBuffers();

        p2pLog.debug('GGPO state cleared for new episode');
    }

    /**
     * Archive current episode's validation data to cumulative storage.
     * Called before clearGGPOState() clears per-episode data.
     * @private
     */
    _archiveEpisodeValidationData() {
        // Only archive if we have meaningful data (episode actually ran)
        if (this.frameNumber <= 0 && this.confirmedHashHistory.size === 0) {
            return;
        }

        const episodeNum = this.num_episodes;

        // Archive episode summary
        const episodeSummary = {
            episodeNum: episodeNum,
            totalFrames: this.frameNumber,
            confirmedFrame: this.confirmedFrame,
            verifiedFrame: this.verifiedFrame,
            hashCount: this.confirmedHashHistory.size,
            desyncCount: this.desyncEvents.length,
            rollbackCount: this.rollbackCount,
            maxRollbackFrames: this.maxRollbackFrames,
            timestamp: Date.now()
        };
        this.cumulativeValidation.episodes.push(episodeSummary);

        // Archive all confirmed hashes with episode tag
        for (const [frame, hash] of this.confirmedHashHistory.entries()) {
            this.cumulativeValidation.allHashes.push({
                episode: episodeNum,
                frame: frame,
                hash: hash
            });
        }

        // Archive all verified actions with episode tag
        // Actions from inputBuffer up to verifiedFrame
        // Each action is stored as separate entry for easier cross-client comparison
        const humanPlayerIds = this._getHumanPlayerIds();
        const verifiedFrames = Array.from(this.inputBuffer.keys())
            .filter(f => f <= this.verifiedFrame)
            .sort((a, b) => a - b);

        // Build frame -> isFocused lookup from actionSequence
        const frameFocusMap = new Map();
        for (const record of this.actionSequence) {
            if (record.isFocused !== undefined) {
                frameFocusMap.set(record.frame, record.isFocused);
            }
        }

        for (const frame of verifiedFrames) {
            const frameInputs = this.inputBuffer.get(frame);
            if (frameInputs) {
                for (const playerId of humanPlayerIds) {
                    const action = frameInputs.get(playerId);
                    if (action !== undefined) {
                        // Store one entry per player per frame for easier cross-client comparison
                        // Include focus state for research analysis
                        this.cumulativeValidation.allActions.push({
                            episode: episodeNum,
                            frame: frame,
                            playerId: playerId,
                            action: action,
                            isFocused: frameFocusMap.get(frame) !== undefined ? frameFocusMap.get(frame) : true
                        });
                    }
                }
            }
        }

        // Archive all desync events with episode tag
        for (const evt of this.desyncEvents) {
            this.cumulativeValidation.allDesyncEvents.push({
                episode: episodeNum,
                ...evt
            });
        }

        // Archive rollback summary for this episode
        if (this.rollbackCount > 0) {
            this.cumulativeValidation.allRollbacks.push({
                episode: episodeNum,
                count: this.rollbackCount,
                maxFrames: this.maxRollbackFrames
            });
        }

        p2pLog.debug(
            `Archived episode ${episodeNum} validation: ` +
            `${this.confirmedHashHistory.size} hashes, ${verifiedFrames.length} actions, ${this.desyncEvents.length} desyncs`
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

    // ========== P2P WebRTC Methods ==========

    _initP2PConnection() {
        /**
         * Initialize WebRTC P2P connection to peer.
         * Called after pyodide_game_ready when we know the other player's ID.
         */
        this.p2pValidation.state = 'connecting';
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
            p2pLog.warn('DataChannel OPEN - starting P2P validation');
            this.p2pConnected = true;

            // If we were reconnecting, DataChannel reopen means reconnection succeeded (Phase 20)
            if (this.reconnectionState.state === 'reconnecting') {
                p2pLog.info('DataChannel reopened during reconnection');
                this._onP2PReconnectionSuccess();
            }

            // Initialize P2P input sending (use numeric index for binary protocol)
            const myPlayerIndex = this.playerIdToIndex[this.myPlayerId];
            if (!this.p2pInputSender) {
                this.p2pInputSender = new P2PInputSender(
                    this.webrtcManager,
                    myPlayerIndex,
                    3  // redundancy count
                );
            }

            // Initialize connection health monitoring
            if (!this.connectionHealth) {
                this.connectionHealth = new ConnectionHealthMonitor();
            }

            // Start latency telemetry (Phase 22 - LAT-01)
            if (!this.latencyTelemetry && this.webrtcManager?.peerConnection) {
                this.latencyTelemetry = new LatencyTelemetry(this.webrtcManager.peerConnection, {
                    pollInterval: 1000,  // 1Hz sampling
                    maxSamples: 600      // ~10 minutes of data
                });
                this.latencyTelemetry.start();
                p2pLog.info('Latency telemetry started');
            }

            // Start P2P validation handshake (Phase 19) - only on initial connection
            if (this.p2pValidation.state === 'connecting') {
                if (this.p2pValidation.enabled) {
                    this._startValidation();
                } else {
                    // Validation disabled - resolve immediately
                    this._startPingInterval();
                    this._sendP2PTestMessage();
                    this._resolveP2PReadyGate();
                }
            }
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

        // Connection drop detection (Phase 20)
        this.webrtcManager.onConnectionLost = (info) => {
            this._onP2PConnectionLost(info);
        };

        // Connection restored callback (Phase 20)
        this.webrtcManager.onConnectionRestored = () => {
            p2pLog.info('Connection restored');
            // Trigger reconnection success flow
            this._onP2PReconnectionSuccess();
        };

        // Start the connection (role determined by player ID comparison)
        this.webrtcManager.connectToPeer(this.p2pPeerId);
    }

    /**
     * Log connection type for research analytics.
     * @param {Object} connInfo - Connection type info from WebRTCManager
     */
    _logConnectionType(connInfo) {
        p2pLog.warn(`Connection type: ${connInfo.connectionType} (${connInfo.localCandidateType}/${connInfo.remoteCandidateType})`);

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

    // ========== P2P Health Reporting (Phase 33) ==========

    /**
     * Report P2P health metrics to server for admin dashboard.
     * Called periodically (every 2 seconds) while game is active.
     * Reports: connection type, latency, health status, current episode.
     */
    _reportP2PHealth() {
        if (!socket || !this.gameId) return;

        let connectionType = 'socketio_fallback';  // Default if no P2P
        let latencyMs = null;
        let status = 'healthy';  // SocketIO fallback still works

        if (this.webrtcManager && this.webrtcManager.isReady()) {
            // Get actual P2P data
            const connInfo = this.webrtcManager.connectionType;
            connectionType = connInfo?.connectionType || 'unknown';

            // Get latency from telemetry
            if (this.latencyTelemetry) {
                const stats = this.latencyTelemetry.getStats();
                latencyMs = stats?.medianMs ?? stats?.meanMs ?? null;
            }

            // Determine status
            const iceState = this.webrtcManager.peerConnection?.iceConnectionState;
            if (this.webrtcManager.iceRestartAttempts > 0 || this.reconnectionState.state === 'reconnecting') {
                status = 'reconnecting';
            } else if (latencyMs && latencyMs > 150) {
                status = 'degraded';
            } else if (iceState === 'connected' || iceState === 'completed') {
                status = 'healthy';
            } else if (iceState === 'checking' || iceState === 'disconnected') {
                status = 'degraded';
            }
        }

        // Get current episode number
        const currentEpisode = this.cumulativeValidation.episodes.length;

        socket.emit('p2p_health_report', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            connection_type: connectionType,
            latency_ms: latencyMs,
            status: status,
            episode: currentEpisode
        });
    }

    /**
     * Start periodic P2P health reporting.
     * Called when game starts (after P2P connection established).
     */
    _startP2PHealthReporting() {
        if (this._p2pHealthReportIntervalId) {
            return;  // Already running
        }

        // Report immediately on start
        this._reportP2PHealth();

        // Then report every 2 seconds
        this._p2pHealthReportIntervalId = setInterval(() => {
            this._reportP2PHealth();
        }, 2000);

        p2pLog.debug('P2P health reporting started');
    }

    /**
     * Stop periodic P2P health reporting.
     * Called on game cleanup.
     */
    _stopP2PHealthReporting() {
        if (this._p2pHealthReportIntervalId) {
            clearInterval(this._p2pHealthReportIntervalId);
            this._p2pHealthReportIntervalId = null;
            p2pLog.debug('P2P health reporting stopped');
        }
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
        p2pLog.debug(`P2P ready gate resolved: ${status}`);

        // Initialize Web Worker timer now that P2P gate is resolved
        this._initTimerWorker();

        // Start P2P health reporting for admin dashboard (Phase 33)
        this._startP2PHealthReporting();
    }

    // ========== Web Worker Timer (Phase 24) ==========

    /**
     * Initialize the Web Worker timer for game logic ticks.
     * Worker ticks are exempt from browser throttling when tab is backgrounded.
     * Called after P2P setup completes.
     */
    _initTimerWorker() {
        if (this.timerWorker) {
            // Already initialized
            return;
        }

        const targetFps = this.config.fps || 10;
        this.timerWorker = new GameTimerWorker(targetFps);

        this.timerWorker.onTick = (timestamp) => {
            this._handleWorkerTick(timestamp);
        };

        this.timerWorker.start();
        p2pLog.info(`Web Worker timer started at ${targetFps} FPS`);
    }

    /**
     * Handle a tick from the Web Worker timer.
     * This triggers game logic advancement via the registered callback.
     * @param {number} timestamp - performance.now() timestamp from Worker
     */
    _handleWorkerTick(timestamp) {
        const now = performance.now();
        this._lastTickTime = now;
        this._tickStartTime = now;  // Track when tick processing started

        // Skip if game is done
        if (this.state === 'done') {
            return;
        }

        // Skip if paused for reconnection (Phase 20)
        if (this.reconnectionState.isPaused) {
            return;
        }

        // Skip if waiting for partner to refocus (Phase 27 - configurable pause)
        if (this._waitingForPartnerFocus) {
            return;
        }

        // Phase 26: Fast-forward on refocus before normal tick processing
        // This catches up frames missed while backgrounded using buffered partner inputs.
        // MUST be checked BEFORE isBackgrounded (we're no longer backgrounded when this fires)
        if (this._pendingFastForward && !this.focusManager?.isBackgrounded) {
            this._pendingFastForward = false;
            // Block this tick while fast-forward completes to prevent race conditions
            // with frameNumber modification and input processing
            this.isProcessingTick = true;
            this._performFastForward()
                .catch(err => {
                    p2pLog.error('Fast-forward failed:', err);
                })
                .finally(() => {
                    this.isProcessingTick = false;
                });
            // Return early - next tick will process normally after fast-forward completes
            return;
        }

        // Phase 27: Check focus loss timeout
        if (this.focusManager?.isBackgrounded && this.focusManager.isTimeoutExceeded()) {
            this._handleFocusLossTimeout();
            return;  // Don't process tick - game is ending
        }

        // Phase 25: Skip processing when tab is backgrounded
        // Worker keeps ticking (so we know elapsed time), but we don't advance frames.
        // Partner inputs are buffered; we'll fast-forward on refocus (Phase 26).
        // IMPORTANT: Partner's game loop is unaffected - they continue receiving our
        // defaultAction inputs and stepping normally (PARTNER-01, PARTNER-02).
        if (this.focusManager && this.focusManager.isBackgrounded) {
            // Log background status periodically (every ~50 ticks at 10 FPS = 5 seconds)
            if (!this._backgroundLogCounter) this._backgroundLogCounter = 0;
            this._backgroundLogCounter++;
            if (this._backgroundLogCounter % 50 === 0) {
                const duration = this.focusManager.getCurrentBackgroundDuration();
                const buffered = this.focusManager.backgroundInputBuffer.length;
                p2pLog.info(`Still backgrounded: ${(duration/1000).toFixed(1)}s, ${buffered} inputs buffered`);
            }
            return;
        }
        // Reset counter when not backgrounded
        this._backgroundLogCounter = 0;

        // Periodic diagnostic logging (every ~50 ticks = 5 seconds at 10 FPS)
        if (!this._diagLogCounter) this._diagLogCounter = 0;
        this._diagLogCounter++;
        if (this._diagLogCounter % 50 === 0) {
            const inputBufferSize = this.inputBuffer.size;
            const snapshotCount = this.stateSnapshots.size;
            const predictedCount = this.predictedFrames.size;
            const actionSeqLen = this.actionSequence?.length || 0;
            console.log(`[DIAG] frame=${this.frameNumber} confirmed=${this.confirmedFrame} inputBuf=${inputBufferSize} snapshots=${snapshotCount} predicted=${predictedCount} rollbacks=${this.rollbackCount} actionSeq=${actionSeqLen}`);
        }

        // Skip if already processing a tick (prevents overlapping async operations)
        if (this.isProcessingTick) {
            return;
        }

        // Mark as processing - will be cleared by callback when complete
        this.isProcessingTick = true;

        // Trigger the registered tick callback (Phaser's processPyodideGame)
        if (this.tickCallback) {
            this.tickCallback();
        } else {
            // No callback registered, clear processing flag
            this.isProcessingTick = false;
        }
    }

    /**
     * Register a callback to receive Worker tick notifications.
     * The callback is responsible for clearing isProcessingTick when done.
     * @param {Function} callback - Function to call on each tick
     */
    registerTickCallback(callback) {
        this.tickCallback = callback;
    }

    /**
     * Destroy the Web Worker timer.
     * Called during game cleanup to release resources.
     */
    _destroyTimerWorker() {
        if (this.timerWorker) {
            this.timerWorker.destroy();
            this.timerWorker = null;
            p2pLog.debug('Web Worker timer destroyed');
        }
        // Phase 25: Clean up focus manager
        if (this.focusManager) {
            this.focusManager.destroy();
        }
        // Phase 33: Stop P2P health reporting
        this._stopP2PHealthReporting();
    }

    /**
     * Start P2P validation handshake (Phase 19).
     * Both peers send ping, wait for pong, confirm bidirectional data flow.
     */
    _startValidation() {
        this.p2pValidation.state = 'validating';
        p2pLog.info('Starting P2P validation handshake');

        // Emit status to server for UI update
        socket.emit('p2p_validation_status', {
            game_id: this.gameId,
            status: 'validating'
        });

        // Set validation timeout
        this.p2pValidation.timeoutId = setTimeout(() => {
            if (this.p2pValidation.state === 'validating') {
                this._onValidationTimeout();
            }
        }, this.p2pValidation.timeoutMs);

        // Small delay to ensure DataChannel is stable, then send ping
        setTimeout(() => {
            if (this.p2pValidation.state === 'validating') {
                this._sendValidationPing();
            }
        }, 100);
    }

    _sendValidationPing() {
        const packet = encodeValidationPing();
        if (this.webrtcManager?.isReady()) {
            this.webrtcManager.send(packet);
            this.p2pValidation.pingSentAt = performance.now();
            p2pLog.debug('Sent validation ping');
        }
    }

    _handleValidationPing(buffer) {
        const view = new DataView(buffer);
        const timestamp = view.getFloat64(1, false);

        // Mark that peer's ping was received
        this.p2pValidation.peerPingSeen = true;

        // Respond with pong
        const pong = encodeValidationPong(timestamp);
        this.webrtcManager?.send(pong);
        p2pLog.debug('Received validation ping, sent pong');

        // Check if validation complete
        this._checkValidationComplete();
    }

    _handleValidationPong(buffer) {
        const view = new DataView(buffer);
        const originalTimestamp = view.getFloat64(1, false);

        // Measure RTT from validation handshake
        if (this.p2pValidation.pingSentAt) {
            const rtt = performance.now() - this.p2pValidation.pingSentAt;
            p2pLog.debug(`Validation pong received, RTT: ${rtt.toFixed(1)}ms`);
        }

        this.p2pValidation.pongReceived = true;
        this._checkValidationComplete();
    }

    /**
     * Handle incoming input request from partner.
     * Partner is fast-forwarding after refocus and needs our inputs for a frame range.
     */
    _handleInputRequest(buffer) {
        const request = decodeInputRequest(buffer);
        if (!request) {
            p2pLog.warn('Failed to decode input request');
            return;
        }

        const { startFrame, endFrame } = request;
        p2pLog.info(`INPUT_REQUEST received: frames ${startFrame}-${endFrame}`);

        // Collect inputs from our local input buffer for the requested range
        const inputs = [];
        const myPlayerIdStr = String(this.myPlayerId);

        for (let frame = startFrame; frame <= endFrame; frame++) {
            const frameInputs = this.inputBuffer.get(frame);
            if (frameInputs && frameInputs.has(myPlayerIdStr)) {
                inputs.push({
                    frame: frame,
                    action: frameInputs.get(myPlayerIdStr)
                });
            }
        }

        p2pLog.info(`INPUT_RESPONSE: sending ${inputs.length} inputs for frames ${startFrame}-${endFrame}`);

        // Send response with our inputs
        const response = encodeInputResponse(this.playerIdToIndex[this.myPlayerId], inputs);
        if (this.webrtcManager?.isReady()) {
            this.webrtcManager.send(response);
        } else {
            p2pLog.warn('Cannot send input response - WebRTC not ready');
        }
    }

    /**
     * Handle incoming input response from partner.
     * This completes a pending input request during fast-forward.
     */
    _handleInputResponse(buffer) {
        const response = decodeInputResponse(buffer);
        if (!response) {
            p2pLog.warn('Failed to decode input response');
            return;
        }

        // Convert player index to ID
        const playerId = this.indexToPlayerId[response.playerId];
        if (playerId === undefined) {
            p2pLog.warn(`Unknown player index in input response: ${response.playerId}`);
            return;
        }

        p2pLog.info(`INPUT_RESPONSE received: ${response.inputs.length} inputs from player ${playerId}`);

        // Store the received inputs in our buffer
        for (const input of response.inputs) {
            this.storeRemoteInput(playerId, input.action, input.frame);
        }

        // Resolve pending request if we have one
        if (this._pendingInputRequest) {
            this._pendingInputRequest.resolve(response.inputs.length);
            this._pendingInputRequest = null;
        }
    }

    /**
     * Request missing inputs from partner for a frame range.
     * Returns a promise that resolves when the response is received.
     * @param {number} startFrame - First frame to request
     * @param {number} endFrame - Last frame to request (inclusive)
     * @param {number} timeoutMs - Timeout in milliseconds (default 2000)
     * @returns {Promise<number>} Number of inputs received
     */
    _requestMissingInputs(startFrame, endFrame, timeoutMs = 2000) {
        return new Promise((resolve, reject) => {
            if (!this.webrtcManager?.isReady()) {
                reject(new Error('WebRTC not ready'));
                return;
            }

            // Store pending request state
            this._pendingInputRequest = { resolve, reject, startFrame, endFrame };

            // Set timeout
            const timeoutId = setTimeout(() => {
                if (this._pendingInputRequest) {
                    p2pLog.warn(`Input request timed out for frames ${startFrame}-${endFrame}`);
                    this._pendingInputRequest = null;
                    reject(new Error('Input request timeout'));
                }
            }, timeoutMs);

            // Clear timeout when resolved
            const originalResolve = resolve;
            this._pendingInputRequest.resolve = (count) => {
                clearTimeout(timeoutId);
                originalResolve(count);
            };

            // Send request
            const request = encodeInputRequest(startFrame, endFrame);
            this.webrtcManager.send(request);
            p2pLog.info(`INPUT_REQUEST sent: frames ${startFrame}-${endFrame}`);
        });
    }

    /**
     * Handle incoming focus state message from partner.
     * Updates partner focus tracking for episode sync.
     * If pause_on_partner_background is enabled, pauses game when partner backgrounds.
     */
    _handleFocusState(buffer) {
        const state = decodeFocusState(buffer);
        if (!state) {
            p2pLog.warn('Failed to decode focus state message');
            return;
        }

        const wasFocused = this.p2pEpisodeSync.partnerFocused;
        this.p2pEpisodeSync.partnerFocused = state.isFocused;

        if (state.isFocused && !wasFocused) {
            p2pLog.info(`Partner refocused at frame ${state.frameNumber}`);

            // Resume game if we were paused waiting for partner (mid-episode pause)
            if (this._waitingForPartnerFocus) {
                this._waitingForPartnerFocus = false;
                this._hideWaitingForPartnerOverlay();
                p2pLog.info('Partner returned - resuming game');
            }
            // Note: Episode boundary focus waiting is handled by showEpisodeTransition()
        } else if (!state.isFocused && wasFocused) {
            p2pLog.info(`Partner backgrounded at frame ${state.frameNumber}`);

            // If configured, pause game and show waiting overlay
            if (this.config.pause_on_partner_background && !this._waitingForPartnerFocus) {
                this._waitingForPartnerFocus = true;
                this._showWaitingForPartnerOverlay(true);
                p2pLog.info('Partner backgrounded - pausing game');
            }
        }
    }

    /**
     * Broadcast our focus state to partner.
     * Called when visibility changes.
     */
    _broadcastFocusState(isFocused) {
        if (!this.webrtcManager?.isReady()) {
            return;
        }

        const packet = encodeFocusState(isFocused, this.frameNumber);
        this.webrtcManager.send(packet);
        p2pLog.debug(`Broadcast focus state: ${isFocused ? 'focused' : 'backgrounded'} at frame ${this.frameNumber}`);
    }

    _checkValidationComplete() {
        // Validation complete when we've sent ping, received pong, and seen peer's ping
        if (this.p2pValidation.pingSentAt &&
            this.p2pValidation.pongReceived &&
            this.p2pValidation.peerPingSeen) {
            this._onValidationSuccess();
        }
    }

    _onValidationSuccess() {
        // Clear timeout
        if (this.p2pValidation.timeoutId) {
            clearTimeout(this.p2pValidation.timeoutId);
            this.p2pValidation.timeoutId = null;
        }

        this.p2pValidation.state = 'validated';
        p2pLog.warn('P2P validation successful');

        // Notify server
        socket.emit('p2p_validation_success', {
            game_id: this.gameId,
            player_id: this.myPlayerId
        });

        // Start ping interval now that validation is complete
        this._startPingInterval();
        this._sendP2PTestMessage();

        // Don't resolve gate yet - wait for server to confirm both players validated
    }

    _onValidationTimeout() {
        this.p2pValidation.state = 'failed';
        p2pLog.error('P2P validation timeout');

        // Notify server of failure
        socket.emit('p2p_validation_failed', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            reason: 'timeout'
        });

        // Server will emit p2p_validation_repool, handled by index.js
    }

    // ========== Mid-Game Reconnection Methods (Phase 20) ==========

    /**
     * Handle P2P connection lost (Phase 20 - RECON-01, RECON-02).
     * Called from WebRTCManager callback when connection drop detected.
     */
    _onP2PConnectionLost(info) {
        // Skip if already paused or game is done
        if (this.reconnectionState.isPaused || this.state === 'done') {
            return;
        }

        p2pLog.warn('P2P connection lost, requesting bilateral pause', info);

        // Update state
        this.reconnectionState.state = 'pausing';

        // Log disconnection event (LOG-01)
        this.reconnectionState.disconnections.push({
            timestamp: Date.now(),
            frame: this.frameNumber,
            detectingPeer: this.myPlayerId,
            iceState: info.iceState,
            dcState: info.dcState
        });

        // Notify server to coordinate bilateral pause
        socket.emit('p2p_connection_lost', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            frame_number: this.frameNumber,
            timestamp: Date.now()
        });

        // Apply local pause immediately (server will confirm)
        this._pauseForReconnection(this.frameNumber);
    }

    /**
     * Pause game for reconnection (Phase 20 - RECON-02).
     * Stops game loop and prepares for reconnection attempt.
     */
    _pauseForReconnection(pauseFrame) {
        if (this.reconnectionState.isPaused) {
            return;  // Already paused
        }

        // Don't show reconnecting overlay if we already showed focus loss timeout
        if (this.focusLossTimeoutTerminal) {
            return;
        }

        p2pLog.info(`Pausing game for reconnection at frame ${pauseFrame}`);

        this.reconnectionState.isPaused = true;
        this.reconnectionState.pauseStartTime = Date.now();
        this.reconnectionState.pauseFrame = pauseFrame;
        this.reconnectionState.state = 'paused';

        // Pause continuous monitoring if active
        if (this.continuousMonitor) {
            this.continuousMonitor.pause();
        }

        // Show reconnecting overlay (RECON-03)
        this._showReconnectingOverlay();

        // Transition to reconnecting state and attempt ICE restart
        this.reconnectionState.state = 'reconnecting';
        this._attemptReconnection();
    }

    /**
     * Handle server pause command (Phase 20).
     * Server coordinates pause to ensure both clients pause together.
     */
    _handleServerPause(data) {
        // Don't process pause if we already ended due to focus loss timeout
        if (this.focusLossTimeoutTerminal) {
            p2pLog.info('Ignoring server pause - already terminated due to focus loss timeout');
            return;
        }

        p2pLog.info('Server requested pause for reconnection', data);

        if (!this.reconnectionState.isPaused) {
            this._pauseForReconnection(data.pause_frame);
        }

        // Start reconnection timeout (RECON-04, RECON-06)
        this._startReconnectionTimeout();
    }

    /**
     * Start reconnection timeout (Phase 20 - RECON-04).
     */
    _startReconnectionTimeout() {
        this._clearReconnectionTimeout();

        this.reconnectionState.timeoutId = setTimeout(() => {
            this._onReconnectionTimeout();
        }, this.reconnectionState.timeoutMs);

        p2pLog.debug(`Reconnection timeout started: ${this.reconnectionState.timeoutMs}ms`);
    }

    _clearReconnectionTimeout() {
        if (this.reconnectionState.timeoutId) {
            clearTimeout(this.reconnectionState.timeoutId);
            this.reconnectionState.timeoutId = null;
        }
    }

    /**
     * Handle reconnection timeout (Phase 20 - RECON-06).
     * Game ends cleanly for both players.
     */
    _onReconnectionTimeout() {
        p2pLog.warn('Reconnection timeout reached');

        // Calculate pause duration for logging (LOG-02)
        const duration = this.reconnectionState.pauseStartTime ?
            Date.now() - this.reconnectionState.pauseStartTime : 0;

        this.reconnectionState.reconnectionAttempts.push({
            timestamp: Date.now(),
            duration: duration,
            outcome: 'timeout',
            attempts: this.webrtcManager?.iceRestartAttempts || 0
        });

        this.reconnectionState.totalPauseDuration += duration;
        this.reconnectionState.state = 'terminated';

        // Notify server of timeout
        socket.emit('p2p_reconnection_timeout', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            pause_duration_ms: duration
        });
    }

    /**
     * Handle game end due to reconnection failure (Phase 20 - RECON-06, Phase 23).
     * Shows in-page partner disconnected overlay instead of redirect.
     * Exports all data before showing overlay.
     * @param {Object} data - Game end data from server
     * @param {string} data.game_id - Game identifier
     * @param {string} data.reason - Reason for game end
     * @param {string|number} data.disconnected_player_id - ID of player who disconnected
     */
    _handleReconnectionGameEnd(data) {
        // If we already ended due to focus loss timeout, don't overwrite the message
        // The player who timed out should keep seeing "you left too long", not "partner disconnected"
        if (this.focusLossTimeoutTerminal) {
            p2pLog.info('Ignoring p2p_game_ended - already terminated due to focus loss timeout');
            return;
        }

        p2pLog.warn('Game ended due to partner disconnection', data);

        this._clearReconnectionTimeout();
        this.reconnectionState.state = 'terminated';

        // Stop game state but mark as terminal to prevent scene advancement
        // The in-page overlay is the final state - participant should NOT advance to next scene
        this.state = "done";
        this.episodeComplete = true;
        this.partnerDisconnectedTerminal = true;  // Phase 23: prevents isDone() from triggering scene advance

        // Pause continuous monitoring if active
        if (this.continuousMonitor) {
            this.continuousMonitor.pause();
        }

        // Clean up Web Worker timer (Phase 24)
        this._destroyTimerWorker();

        // Mark session as partial with disconnection metadata (Phase 23 - DATA-02, DATA-03, DATA-04)
        this.sessionPartialInfo = {
            isPartial: true,
            terminationReason: 'partner_disconnected',
            terminationFrame: this.frameNumber,
            disconnectedPlayerId: data.disconnected_player_id || this.p2pPeerId,
            reconnectionData: this.getReconnectionData()
        };

        // Export all metrics BEFORE showing overlay (Phase 23 - DATA-01)
        if (this.gameId && this.sceneId) {
            this.emitMultiplayerMetrics(this.sceneId);
        }

        // Get custom message from config, or use default
        const customMessage = this.config?.partner_disconnect_message;
        const message = customMessage || "Your partner has disconnected.";

        // Show in-page overlay (Phase 23 - UI-01, UI-02, UI-03, UI-04)
        this._showPartnerDisconnectedOverlay(message);

        // Close P2P connection
        if (this.webrtcManager) {
            this.webrtcManager.close();
        }
    }

    /**
     * Show partner disconnected message (Phase 23 - UI-01 through UI-04).
     * Hides ALL page content and replaces with disconnect message.
     * Page stays displayed indefinitely (no redirect, no Continue button).
     * Optionally includes completion code for participant compensation (configurable).
     * @param {string} message - Message to display
     */
    _showPartnerDisconnectedOverlay(message) {
        // Remove reconnecting overlay if present
        this._hideReconnectingOverlay();

        // Check if completion code should be shown (defaults to true)
        const showCompletionCode = this.config?.partner_disconnect_show_completion_code !== false;

        let completionCode = null;
        if (showCompletionCode) {
            // Generate completion code for participant
            completionCode = generateCompletionCode();
            p2pLog.warn('Partner disconnected mid-game - completion code:', completionCode);

            // Emit completion code to server for logging/validation
            if (this.socket) {
                this.socket.emit('waitroom_timeout_completion', {
                    completion_code: completionCode,
                    reason: 'partner_disconnected_mid_game',
                    frame_number: this.frameNumber,
                    episode_number: this.num_episodes
                });
            }
        } else {
            p2pLog.warn('Partner disconnected mid-game - no completion code (disabled in config)');
        }

        // Hide ALL direct children of body (Phase 23 - UI-02)
        Array.from(document.body.children).forEach(child => {
            if (child.id !== 'partnerDisconnectedContainer') {
                child.style.display = 'none';
            }
        });

        // Create container for disconnect message (replaces page content, not overlay)
        let container = document.getElementById('partnerDisconnectedContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'partnerDisconnectedContainer';
            container.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: white;
                display: flex;
                justify-content: center;
                align-items: center;
                z-index: 10000;
            `;
            document.body.appendChild(container);
        }

        // Build content based on whether completion code is shown
        let contentHtml = `
            <div style="
                padding: 40px;
                max-width: 500px;
                text-align: center;
            ">
                <h2 style="color: #333; margin-bottom: 20px;">Session Ended</h2>
                <p style="font-size: 16px; color: #333; margin-bottom: 20px;">${message}</p>
        `;

        if (showCompletionCode && completionCode) {
            contentHtml += `
                <p style="font-size: 14px; color: #333;"><strong>Your completion code is:</strong></p>
                <p style="font-size: 24px; font-family: monospace; background: #f0f0f0; padding: 10px; border-radius: 5px; user-select: all;">
                    ${completionCode}
                </p>
                <p style="font-size: 14px; color: #666; margin-top: 15px;">Please copy this code and submit it to complete the study.</p>
            `;
        }

        contentHtml += `</div>`;

        container.innerHTML = contentHtml;
        container.style.display = 'flex';
    }

    /**
     * Handle focus loss timeout (Phase 27 - TIMEOUT-02).
     * Ends game for both players when focus loss exceeds configured timeout.
     */
    _handleFocusLossTimeout() {
        const timeoutMs = this.focusManager.timeoutMs;
        const actualMs = this.focusManager.getCurrentBackgroundDuration();
        p2pLog.warn(`Focus loss timeout exceeded: ${actualMs.toFixed(0)}ms > ${timeoutMs}ms`);

        // Stop game state - similar to _handleReconnectionGameEnd
        this.state = "done";
        this.episodeComplete = true;
        this.focusLossTimeoutTerminal = true;  // Prevent scene advance

        // Pause continuous monitoring if active
        if (this.continuousMonitor) {
            this.continuousMonitor.pause();
        }

        // Clean up Web Worker timer
        this._destroyTimerWorker();

        // Mark session as partial with focus loss metadata
        this.sessionPartialInfo = {
            isPartial: true,
            terminationReason: 'focus_loss_timeout',
            terminationFrame: this.frameNumber,
            focusLossDurationMs: actualMs,
            focusLossTimeoutMs: timeoutMs,
            focusLossTelemetry: this.focusManager.getTelemetry()
        };

        // Export metrics before showing overlay
        if (this.gameId && this.sceneId) {
            this.emitMultiplayerMetrics(this.sceneId);
        }

        // Get custom message from config or use default
        const customMessage = this.config?.focus_loss_message;
        const message = customMessage || "You were away from the experiment for too long. The session has been terminated.";

        // Show in-page overlay (reuse partner disconnect overlay pattern)
        this._showFocusLossTimeoutOverlay(message);

        // Close P2P connection
        if (this.webrtcManager) {
            this.webrtcManager.close();
        }

        // Notify server that game ended due to focus loss
        socket.emit('p2p_game_ended', {
            game_id: this.gameId,
            reason: 'focus_loss_timeout',
            player_id: this.myPlayerId,
            focus_loss_duration_ms: actualMs
        });
    }

    /**
     * Show focus loss timeout message (Phase 27 - TIMEOUT-03).
     * Reuses partner disconnected overlay pattern.
     * NOTE: No completion code shown here - this is displayed to the participant
     * who was inactive/away. The active partner receives a completion code via
     * _showPartnerDisconnectedOverlay instead.
     * @param {string} message - Message to display
     */
    _showFocusLossTimeoutOverlay(message) {
        // Remove any existing overlays
        this._hideReconnectingOverlay();

        // Hide ALL direct children of body
        Array.from(document.body.children).forEach(child => {
            if (child.id !== 'focusLossContainer') {
                child.style.display = 'none';
            }
        });

        // Create container
        let container = document.getElementById('focusLossContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'focusLossContainer';
            container.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: white;
                display: flex;
                justify-content: center;
                align-items: center;
                z-index: 10000;
            `;
            document.body.appendChild(container);
        }

        container.innerHTML = `
            <div style="
                padding: 40px;
                max-width: 500px;
                text-align: center;
            ">
                <h2 style="color: #333; margin-bottom: 20px;">Session Ended</h2>
                <p style="font-size: 16px; color: #333;">${message}</p>
            </div>
        `;
        container.style.display = 'flex';
    }

    /**
     * Get reconnection event data for export (Phase 20 - LOG-01, LOG-02, LOG-03).
     */
    getReconnectionData() {
        return {
            disconnections: this.reconnectionState.disconnections,
            reconnectionAttempts: this.reconnectionState.reconnectionAttempts,
            totalPauseDurationMs: this.reconnectionState.totalPauseDuration
        };
    }

    /**
     * Show reconnecting overlay (Phase 20 - RECON-03).
     * Displays centered overlay with spinner and status message.
     * Styled to match Interactive Gym aesthetic.
     */
    _showReconnectingOverlay() {
        // Remove existing overlay if any
        this._hideReconnectingOverlay();

        const overlay = document.createElement('div');
        overlay.id = 'reconnect-overlay';
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.75);
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            z-index: 10000;
        `;
        overlay.innerHTML = `
            <div style="
                font-family: 'Press Start 2P', cursive;
                font-size: 18px;
                color: #ffffff;
                text-align: center;
                margin-bottom: 20px;
                text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5);
            ">
                Connection Lost
            </div>
            <div class="reconnect-spinner" style="
                width: 40px;
                height: 40px;
                border: 4px solid #34495e;
                border-top: 4px solid #3498db;
                border-radius: 50%;
                animation: reconnect-spin 1s linear infinite;
            "></div>
            <div id="reconnect-status" style="
                margin-top: 20px;
                font-family: 'Roboto', sans-serif;
                font-size: 16px;
                color: #ecf0f1;
            ">
                Reconnecting...
            </div>
            <style>
                @keyframes reconnect-spin {
                    0% { transform: rotate(0deg); }
                    100% { transform: rotate(360deg); }
                }
            </style>
        `;
        document.body.appendChild(overlay);
    }

    /**
     * Hide reconnecting overlay.
     */
    _hideReconnectingOverlay() {
        const overlay = document.getElementById('reconnect-overlay');
        if (overlay) {
            overlay.remove();
        }
    }

    /**
     * Update reconnecting overlay status message.
     */
    _updateReconnectingStatus(message) {
        const status = document.getElementById('reconnect-status');
        if (status) {
            status.textContent = message;
        }
    }

    /**
     * Show "Waiting for partner..." overlay when partner is backgrounded during episode transition.
     * @param {boolean} partnerBackgrounded - True if waiting for partner, false if waiting for self
     */
    _showWaitingForPartnerOverlay(partnerBackgrounded) {
        // Remove existing overlay if any
        this._hideWaitingForPartnerOverlay();

        // Clear any accumulated human inputs to prevent them executing when game resumes
        clearHumanInputBuffers();

        const message = partnerBackgrounded
            ? 'Waiting for partner to return...'
            : 'Please return to the game window to continue.';

        const overlay = document.createElement('div');
        overlay.id = 'waiting-partner-overlay';
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.75);
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            z-index: 10000;
        `;

        overlay.innerHTML = `
            <div style="
                background: white;
                padding: 30px 50px;
                border-radius: 8px;
                text-align: center;
                max-width: 400px;
            ">
                <div style="
                    width: 40px;
                    height: 40px;
                    border: 4px solid #e0e0e0;
                    border-top-color: #3498db;
                    border-radius: 50%;
                    animation: spin 1s linear infinite;
                    margin: 0 auto 20px;
                "></div>
                <p style="font-size: 18px; color: #333; margin: 0;">${message}</p>
            </div>
            <style>
                @keyframes spin {
                    to { transform: rotate(360deg); }
                }
            </style>
        `;

        document.body.appendChild(overlay);
        p2pLog.info(`Showing waiting for partner overlay: ${message}`);
    }

    /**
     * Hide "Waiting for partner..." overlay.
     */
    _hideWaitingForPartnerOverlay() {
        const overlay = document.getElementById('waiting-partner-overlay');
        if (overlay) {
            overlay.remove();
            // Clear any inputs that accumulated while paused
            clearHumanInputBuffers();
            p2pLog.debug('Hiding waiting for partner overlay');
        }
    }

    /**
     * Attempt to reconnect via ICE restart (Phase 20 - RECON-05).
     */
    async _attemptReconnection() {
        if (!this.webrtcManager) {
            p2pLog.error('Cannot attempt reconnection - no WebRTC manager');
            return;
        }

        this._updateReconnectingStatus('Attempting to reconnect...');

        const started = await this.webrtcManager.attemptIceRestart();
        if (started) {
            p2pLog.info('ICE restart initiated');
            this._updateReconnectingStatus('Restoring connection...');
        } else {
            p2pLog.warn('ICE restart failed to start');
            this._updateReconnectingStatus('Connection cannot be restored...');
        }
    }

    /**
     * Handle successful P2P reconnection (Phase 20 - RECON-05).
     * Called when ICE restart succeeds and DataChannel reopens.
     */
    _onP2PReconnectionSuccess() {
        if (!this.reconnectionState.isPaused) {
            p2pLog.debug('Reconnection success but not paused - ignoring');
            return;
        }

        p2pLog.info('P2P reconnection successful');

        // Calculate duration for logging (LOG-02)
        const duration = this.reconnectionState.pauseStartTime ?
            Date.now() - this.reconnectionState.pauseStartTime : 0;

        // Log reconnection attempt (LOG-02)
        this.reconnectionState.reconnectionAttempts.push({
            timestamp: Date.now(),
            duration: duration,
            outcome: 'success',
            attempts: this.webrtcManager?.iceRestartAttempts || 0
        });

        // Update total pause duration (LOG-03)
        this.reconnectionState.totalPauseDuration += duration;

        this._updateReconnectingStatus('Connection restored!');

        // Notify server that we've reconnected
        socket.emit('p2p_reconnection_success', {
            game_id: this.gameId,
            player_id: this.myPlayerId,
            duration_ms: duration
        });

        // Server will emit p2p_resume when all players reconnected
    }

    /**
     * Handle server resume command (Phase 20 - RECON-05).
     * Server coordinates resume to ensure both clients resume together.
     */
    _handleServerResume(data) {
        if (!this.reconnectionState.isPaused) {
            p2pLog.debug('Server resume received but not paused');
            return;
        }

        p2pLog.info('Server requested resume - restoring gameplay');

        // Clear timeout first (prevent race condition - Pitfall 4 from research)
        this._clearReconnectionTimeout();

        // Reset reconnection state
        this.reconnectionState.isPaused = false;
        this.reconnectionState.pauseStartTime = null;
        this.reconnectionState.pauseFrame = null;
        this.reconnectionState.state = 'connected';

        // Hide overlay
        this._hideReconnectingOverlay();

        // Resume continuous monitoring if it was active
        if (this.continuousMonitor) {
            this.continuousMonitor.resume();
        }

        p2pLog.info('Gameplay resumed successfully');
    }

    /**
     * Wait for a healthy P2P connection before proceeding (Phase 21 - ROUND-01, ROUND-02).
     * Used by reset() to ensure connection is healthy before each round starts.
     *
     * @param {number} timeoutMs - Maximum time to wait for healthy connection (default 10000ms)
     * @returns {Promise<void>} - Resolves when connection is healthy, rejects on timeout/termination
     */
    async _waitForHealthyConnection(timeoutMs = 10000) {
        // Fast path: connection is already usable (ROUND-01)
        if (this.webrtcManager?.isConnectionUsable()) {
            p2pLog.debug('Per-round health check: connection usable');
            return;
        }

        // Check reconnection state to determine behavior
        const state = this.reconnectionState.state;

        // If terminated, game should end - don't proceed
        if (state === 'terminated') {
            throw new Error('Connection terminated - cannot start round');
        }

        // If connected but isConnectionUsable() is false, connection may be transitioning
        // Log warning but continue with polling - this is an edge case
        if (state === 'connected') {
            p2pLog.warn('Per-round health check: connection state is connected but not usable, may be transitioning');
        }

        // If paused or reconnecting, wait for recovery
        if (state === 'paused' || state === 'reconnecting' || state === 'connected') {
            p2pLog.info('Per-round health check: waiting for connection recovery...');

            return new Promise((resolve, reject) => {
                const startTime = Date.now();
                const pollInterval = 100;  // Check every 100ms

                const checkConnection = () => {
                    // Check for timeout
                    if (Date.now() - startTime >= timeoutMs) {
                        p2pLog.warn('Per-round health check: timeout waiting for connection');
                        reject(new Error('Health check timeout - connection not recovered'));
                        return;
                    }

                    // Check for termination during wait
                    if (this.reconnectionState.state === 'terminated') {
                        reject(new Error('Connection terminated during health check'));
                        return;
                    }

                    // Check if connection is now usable
                    if (this.webrtcManager?.isConnectionUsable()) {
                        p2pLog.info('Per-round health check: connection recovered, proceeding');
                        resolve();
                        return;
                    }

                    // Continue polling
                    setTimeout(checkConnection, pollInterval);
                };

                // Start polling
                checkConnection();
            });
        }

        // Fallback: unknown state - log and proceed (shouldn't happen)
        p2pLog.warn(`Per-round health check: unexpected state '${state}', proceeding anyway`);
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
            case P2P_MSG_EPISODE_READY:
                this._handleEpisodeReady(buffer);
                break;
            case P2P_MSG_STATE_HASH:
                this._handleStateHash(buffer);
                break;
            case P2P_MSG_VALIDATION_PING:
                this._handleValidationPing(buffer);
                break;
            case P2P_MSG_VALIDATION_PONG:
                this._handleValidationPong(buffer);
                break;
            case P2P_MSG_INPUT_REQUEST:
                this._handleInputRequest(buffer);
                break;
            case P2P_MSG_INPUT_RESPONSE:
                this._handleInputResponse(buffer);
                break;
            case P2P_MSG_FOCUS_STATE:
                this._handleFocusState(buffer);
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

        // Phase 25: Buffer partner inputs when LOCAL tab is backgrounded
        // They'll be processed on refocus for fast-forward (Phase 26)
        // NOTE: This checks OUR focus state, not partner's. We don't know or care if
        // partner is backgrounded - we just process their inputs normally (PARTNER-01).
        // If partner IS backgrounded, they stop sending inputs and we use prediction.
        if (this.focusManager && this.focusManager.isBackgrounded) {
            this.focusManager.bufferInput({
                playerId: playerId,
                inputs: packet.inputs,
                currentFrame: packet.currentFrame
            });
            p2pLog.debug(`Buffered input from player ${playerId} (backgrounded)`);
            return;
        }

        // Also buffer inputs when waiting for partner to refocus at episode boundaries
        // Game loop is paused (_waitingForPartnerFocus=true), so don't queue inputs
        // that would accumulate and execute all at once when partner returns
        if (this._waitingForPartnerFocus) {
            // Discard inputs while waiting - we're at an episode boundary anyway
            // and will resync state when partner returns
            p2pLog.debug(`Discarding input from player ${playerId} (waiting for partner focus)`);
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
        // Pause continuous monitoring during episode transition (Phase 16)
        this.continuousMonitor?.pause();

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
        // Clear end sync timeout if it exists
        if (this.p2pEpisodeSync.syncTimeoutId) {
            clearTimeout(this.p2pEpisodeSync.syncTimeoutId);
        }
        // Clear start sync timeout if it exists
        if (this.p2pEpisodeSync.startTimeoutId) {
            clearTimeout(this.p2pEpisodeSync.startTimeoutId);
        }
        // Episode END sync state
        this.p2pEpisodeSync.localEpisodeEndDetected = false;
        this.p2pEpisodeSync.localEpisodeEndFrame = null;
        this.p2pEpisodeSync.remoteEpisodeEndReceived = false;
        this.p2pEpisodeSync.remoteEpisodeEndFrame = null;
        this.p2pEpisodeSync.pendingReset = false;
        this.p2pEpisodeSync.syncTimeoutId = null;
        // Episode START sync state
        this.p2pEpisodeSync.localResetComplete = false;
        this.p2pEpisodeSync.remoteResetComplete = false;
        this.p2pEpisodeSync.localStateHash = null;
        this.p2pEpisodeSync.remoteStateHash = null;
        this.p2pEpisodeSync.startResolve = null;
        this.p2pEpisodeSync.startTimeoutId = null;
        // Clear retry timeout
        if (this.p2pEpisodeSync.retryTimeoutId) {
            clearTimeout(this.p2pEpisodeSync.retryTimeoutId);
            this.p2pEpisodeSync.retryTimeoutId = null;
        }
        // Clear waiting for partner focus state (but keep partnerFocused as-is - it's tracked separately)
        this.p2pEpisodeSync.waitingForPartnerFocus = false;
        this._hideWaitingForPartnerOverlay();
    }

    _handleEpisodeReady(buffer) {
        /**
         * Handle episode ready notification from peer.
         * Called when peer has completed their reset and is ready to start the episode.
         *
         * When we receive a peer's "episode ready" message and we've already completed our
         * own reset, we send our ready message back. This ensures two-way acknowledgment
         * even if one side's initial message was lost or arrived before the other was listening.
         */
        const packet = decodeEpisodeReady(buffer);
        if (!packet) {
            p2pLog.warn('Failed to decode episode ready packet');
            return;
        }

        p2pLog.debug(`Received episode ready from peer: episode=${packet.episodeNumber} hash=${packet.stateHash}`);

        // Store peer's state hash for verification
        this.p2pEpisodeSync.remoteResetComplete = true;
        this.p2pEpisodeSync.remoteStateHash = packet.stateHash;

        // If we've already completed our reset but peer might not have received our message,
        // send it again as an acknowledgment. This handles the case where:
        // 1. We finished reset and sent our ready message
        // 2. Peer wasn't ready to receive it (DataChannel timing, message loss, etc.)
        // 3. Peer then finishes and sends their ready message to us
        // 4. We need to echo back our ready status so peer knows we're ready too
        if (this.p2pEpisodeSync.localResetComplete && this.p2pEpisodeSync.localStateHash) {
            const episodeNumber = this.num_episodes + 1;
            const ackPacket = encodeEpisodeReady(episodeNumber, this.p2pEpisodeSync.localStateHash);
            if (this.webrtcManager?.isReady()) {
                this.webrtcManager.send(ackPacket);
                p2pLog.debug(`Sent episode ready acknowledgment: episode=${episodeNumber}`);
            }
        }

        // Check if we can now start the episode
        this._checkEpisodeStartSync();
    }

    _broadcastEpisodeReady(stateHash) {
        /**
         * Send episode ready notification to peer with retry mechanism.
         * Called after local reset completes successfully.
         * Retries a few times to handle case where peer's DataChannel isn't fully ready.
         *
         * @param {string} stateHash - 8-char hex hash of initial environment state
         */
        if (!this.webrtcManager?.isReady()) {
            p2pLog.debug('Cannot broadcast episode ready - WebRTC not ready');
            return;
        }

        const episodeNumber = this.num_episodes + 1;  // Next episode number
        const packet = encodeEpisodeReady(episodeNumber, stateHash);

        // Send immediately
        this.webrtcManager.send(packet);
        p2pLog.debug(`Broadcast episode ready: episode=${episodeNumber} hash=${stateHash}`);

        // Record that our reset is complete
        this.p2pEpisodeSync.localResetComplete = true;
        this.p2pEpisodeSync.localStateHash = stateHash;

        // Retry sending a couple times in case peer's DataChannel wasn't ready
        // Clear any existing retry timeout
        if (this.p2pEpisodeSync.retryTimeoutId) {
            clearTimeout(this.p2pEpisodeSync.retryTimeoutId);
        }

        let retryCount = 0;
        const maxRetries = 3;
        const retryInterval = 500;  // 500ms between retries

        const retryBroadcast = () => {
            retryCount++;
            if (retryCount <= maxRetries && !this.p2pEpisodeSync.remoteResetComplete) {
                // Peer hasn't responded yet - resend
                if (this.webrtcManager?.isReady()) {
                    this.webrtcManager.send(packet);
                    p2pLog.debug(`Episode ready retry ${retryCount}/${maxRetries}`);
                }
                this.p2pEpisodeSync.retryTimeoutId = setTimeout(retryBroadcast, retryInterval);
            }
        };

        this.p2pEpisodeSync.retryTimeoutId = setTimeout(retryBroadcast, retryInterval);

        // Check if peer is already ready
        this._checkEpisodeStartSync();
    }

    _checkEpisodeStartSync() {
        /**
         * Check if both peers have completed reset and are ready to start.
         * If both are ready, resolve the start promise to begin the episode.
         *
         * Note: Focus waiting is now handled by showEpisodeTransition() which runs
         * BEFORE the reset. This function only handles post-reset state sync.
         */
        const sync = this.p2pEpisodeSync;

        if (!sync.localResetComplete || !sync.remoteResetComplete) {
            return;  // Still waiting for both peers to reset
        }

        // If startResolve is null, the episode sync has already completed
        if (!sync.startResolve) {
            return;  // Episode already started, nothing to do
        }

        // Verify state hashes match
        if (sync.localStateHash && sync.remoteStateHash && sync.localStateHash !== sync.remoteStateHash) {
            p2pLog.error(`Episode start state mismatch! local=${sync.localStateHash} remote=${sync.remoteStateHash}`);
            // Continue anyway - the first frame hash logging will show divergence
        } else {
            p2pLog.debug(`Episode start synchronized: both peers have matching state hash=${sync.localStateHash}`);
        }

        // Clear the timeout and retry since we synced successfully
        if (sync.startTimeoutId) {
            clearTimeout(sync.startTimeoutId);
            sync.startTimeoutId = null;
        }
        if (sync.retryTimeoutId) {
            clearTimeout(sync.retryTimeoutId);
            sync.retryTimeoutId = null;
        }

        // Resume continuous monitoring after episode sync complete (Phase 16)
        this.continuousMonitor?.resume();

        // Resolve the start promise to unblock the game loop
        if (sync.startResolve) {
            sync.startResolve();
            sync.startResolve = null;
        }
    }

    waitForP2PEpisodeStart(timeoutMs = 5000) {
        /**
         * Wait for peer to complete reset before starting the episode.
         * Focus waiting is handled earlier by showEpisodeTransition().
         *
         * @param {number} timeoutMs - Maximum wait time before proceeding anyway
         * @returns {Promise<void>}
         */
        return new Promise((resolve) => {
            const sync = this.p2pEpisodeSync;

            // Check if both resets are complete
            if (sync.localResetComplete && sync.remoteResetComplete) {
                p2pLog.debug('Peer already ready - starting immediately');
                resolve();
                return;
            }

            // Store resolve function for when sync completes
            sync.startResolve = resolve;

            // Timeout to prevent infinite waiting if peer message is lost
            sync.startTimeoutId = setTimeout(() => {
                if (sync.startResolve) {
                    p2pLog.warn(`Episode start sync timeout - peer not ready after ${timeoutMs}ms, proceeding anyway`);
                    sync.startResolve = null;
                    resolve();
                }
            }, timeoutMs);
        });
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
     * Get P2P latency statistics for export.
     * Phase 22 - Latency Telemetry (LAT-02)
     * @returns {Object|null} Latency stats or null if unavailable
     */
    getLatencyStats() {
        return this.latencyTelemetry?.getStats() || null;
    }

    /**
     * Get current focus state for all players.
     * Returns an object mapping player IDs to their focus state (true = focused, false = backgrounded).
     * Used for per-frame data logging in CSV exports.
     * @returns {Object} {playerId: boolean, ...}
     */
    getFocusStatePerPlayer() {
        const focusState = {};
        const myFocused = this.focusManager ? !this.focusManager.isBackgrounded : true;
        const partnerFocused = this.p2pEpisodeSync?.partnerFocused ?? true;

        // Get all human player IDs
        const humanPlayerIds = this._getHumanPlayerIds();
        for (const playerId of humanPlayerIds) {
            if (String(playerId) === String(this.myPlayerId)) {
                focusState[playerId] = myFocused;
            } else {
                focusState[playerId] = partnerFocused;
            }
        }

        return focusState;
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
            },

            // Reconnection events (Phase 20)
            reconnection: {
                disconnections: this.reconnectionState.disconnections,
                attempts: this.reconnectionState.reconnectionAttempts,
                totalPauseDurationMs: this.reconnectionState.totalPauseDuration
            },

            // P2P latency telemetry (Phase 22 - LAT-01, LAT-02)
            latency: this.getLatencyStats(),

            // Focus loss telemetry (Phase 27 - TELEM-01, TELEM-02)
            focusLoss: this.focusManager ? {
                backgroundPeriods: this.focusManager.getBackgroundPeriods(),
                totalBackgroundMs: this.focusManager.getTelemetry().totalBackgroundMs,
                periodCount: this.focusManager.getTelemetry().periodCount,
                timeoutMs: this.focusManager.timeoutMs,
                wasTimeoutTriggered: this.focusLossTimeoutTerminal || false
            } : null
        };
    }

    /**
     * Export validation data for sync analysis.
     * Call at episode end or from browser console: window.game.exportValidationData()
     * Returns JSON-serializable object with confirmed hashes, verified actions, and desyncs.
     * @returns {Object} Validation data for research analysis
     */
    exportValidationData() {
        return {
            // Session identification
            gameId: this.gameId,
            playerId: this.myPlayerId,
            exportTimestamp: Date.now(),

            // Sync summary
            summary: {
                totalFrames: this.frameNumber,
                verifiedFrame: this.verifiedFrame,
                desyncCount: this.desyncEvents.length,
                hashesComputed: this.confirmedHashHistory.size
            },

            // Frame-by-frame confirmed hashes (EXPORT-01, EXPORT-02)
            confirmedHashes: this._exportConfirmedHashes(),

            // Verified action sequences per player (EXPORT-04)
            verifiedActions: this._exportVerifiedActions(),

            // All desync events with full context (EXPORT-03)
            desyncEvents: this.desyncEvents.map(evt => ({
                frame: evt.frame,
                ourHash: evt.ourHash,
                peerHash: evt.peerHash,
                timestamp: evt.timestamp,
                verifiedFrameAtDesync: evt.verifiedFrameAtDesync,
                // Include state dump only if present and not too large
                hasStateDump: !!evt.stateDump
            })),

            // Reconnection events (Phase 20 - LOG-01, LOG-02, LOG-03)
            reconnection: this.getReconnectionData(),

            // P2P latency telemetry (Phase 22 - LAT-01, LAT-02)
            latency: this.getLatencyStats(),

            // Focus loss telemetry (Phase 27 - TELEM-01, TELEM-02)
            focusLoss: this.focusManager ? {
                backgroundPeriods: this.focusManager.getBackgroundPeriods(),
                totalBackgroundMs: this.focusManager.getTelemetry().totalBackgroundMs,
                periodCount: this.focusManager.getTelemetry().periodCount,
                timeoutMs: this.focusManager.timeoutMs,
                wasTimeoutTriggered: this.focusLossTimeoutTerminal || false
            } : null
        };
    }

    /**
     * Extract confirmed hashes from confirmedHashHistory for export.
     * @returns {Array<{frame: number, hash: string}>} Sorted array of frame/hash pairs
     * @private
     */
    _exportConfirmedHashes() {
        // Convert Map to sorted array of {frame, hash} objects
        const hashes = [];
        for (const [frame, hash] of this.confirmedHashHistory.entries()) {
            hashes.push({ frame, hash });
        }
        // Sort by frame number for consistent output
        return hashes.sort((a, b) => a.frame - b.frame);
    }

    /**
     * Extract verified actions per player up to verifiedFrame for export.
     * @returns {Object} Per-player action sequences {playerId: [{frame, action}, ...]}
     * @private
     */
    _exportVerifiedActions() {
        // Build per-player action sequences from inputBuffer
        // Only include frames up to verifiedFrame (mutually confirmed)
        const result = {};
        const humanPlayerIds = this._getHumanPlayerIds();

        for (const playerId of humanPlayerIds) {
            result[playerId] = [];
        }

        // Get frames in sorted order
        const frames = Array.from(this.inputBuffer.keys())
            .filter(f => f <= this.verifiedFrame)
            .sort((a, b) => a - b);

        for (const frame of frames) {
            const frameInputs = this.inputBuffer.get(frame);
            if (frameInputs) {
                for (const playerId of humanPlayerIds) {
                    const action = frameInputs.get(playerId);
                    if (action !== undefined) {
                        result[playerId].push({ frame, action });
                    }
                }
            }
        }

        return result;
    }

    /**
     * Export all multiplayer metrics for persistence.
     * Uses cumulative data across all episodes for complete session export.
     * Call at scene termination.
     * @returns {Object} Complete multiplayer metrics for research data export
     */
    exportMultiplayerMetrics() {
        // Archive current episode data first (in case not yet archived)
        this._archiveEpisodeValidationData();

        // Get connection health if available
        const connectionHealth = this.connectionHealth?.getHealthStatus() || null;

        return {
            // Session identification
            gameId: this.gameId,
            playerId: this.myPlayerId,
            peerPlayerId: this._getHumanPlayerIds().find(id => id !== this.myPlayerId) || null,
            exportTimestamp: Date.now(),
            sessionStartTime: this.cumulativeValidation.sessionStartTime,
            sessionDurationMs: Date.now() - this.cumulativeValidation.sessionStartTime,

            // P2P connection metrics
            connection: {
                type: this.p2pMetrics.connectionType || 'unknown',
                connectionDetails: this.p2pMetrics.connectionDetails || {},
                p2pConnected: this.p2pConnected,
                health: connectionHealth ? {
                    rtt: connectionHealth.rtt,
                    latency: connectionHealth.latency,
                    packetsReceived: connectionHealth.packetsReceived,
                    gapCount: connectionHealth.gapCount,
                    status: connectionHealth.status
                } : null,
                fallback: {
                    triggered: this.p2pMetrics.p2pFallbackTriggered,
                    frame: this.p2pMetrics.p2pFallbackFrame
                }
            },

            // Input delivery stats (cumulative across session)
            inputDelivery: {
                sentViaP2P: this.p2pMetrics.inputsSentViaP2P,
                sentViaSocketIO: this.p2pMetrics.inputsSentViaSocketIO,
                receivedViaP2P: this.p2pMetrics.inputsReceivedViaP2P,
                receivedViaSocketIO: this.p2pMetrics.inputsReceivedViaSocketIO,
                p2pReceiveRatio: this._calculateP2PReceiveRatio()
            },

            // Cumulative validation data across ALL episodes
            validation: {
                // Per-episode summaries
                episodes: this.cumulativeValidation.episodes,

                // Aggregate stats
                totalEpisodes: this.cumulativeValidation.episodes.length,
                totalHashes: this.cumulativeValidation.allHashes.length,
                totalActions: this.cumulativeValidation.allActions.length,
                totalDesyncs: this.cumulativeValidation.allDesyncEvents.length,
                totalRollbacks: this.cumulativeValidation.allRollbacks.reduce(
                    (sum, r) => sum + r.count, 0
                ),

                // All frame hashes across all episodes
                allHashes: this.cumulativeValidation.allHashes,

                // All verified actions across all episodes
                // Format: [{episode, frame, actions: {playerId: action, ...}}, ...]
                allActions: this.cumulativeValidation.allActions,

                // All desync events across all episodes
                allDesyncEvents: this.cumulativeValidation.allDesyncEvents.map(evt => ({
                    episode: evt.episode,
                    frame: evt.frame,
                    ourHash: evt.ourHash,
                    peerHash: evt.peerHash,
                    timestamp: evt.timestamp,
                    verifiedFrameAtDesync: evt.verifiedFrameAtDesync,
                    hasStateDump: !!evt.stateDump
                })),

                // All rollback events across all episodes
                allRollbacks: this.cumulativeValidation.allRollbacks
            },

            // Session status (Phase 17: partial session marking, Phase 23: disconnectedPlayerId)
            sessionStatus: {
                isPartial: this.sessionPartialInfo?.isPartial || false,
                terminationReason: this.sessionPartialInfo?.terminationReason || 'normal',
                terminationFrame: this.sessionPartialInfo?.terminationFrame || this.frameNumber,
                completedEpisodes: this.cumulativeValidation?.episodes?.length || 0,
                disconnectedPlayerId: this.sessionPartialInfo?.disconnectedPlayerId || null
            },

            // P2P latency telemetry (Phase 22 - LAT-01, LAT-02)
            latency: this.getLatencyStats(),

            // Focus loss telemetry (Phase 27 - TELEM-01, TELEM-02)
            focusLoss: this.focusManager ? {
                backgroundPeriods: this.focusManager.getBackgroundPeriods(),
                totalBackgroundMs: this.focusManager.getTelemetry().totalBackgroundMs,
                periodCount: this.focusManager.getTelemetry().periodCount,
                timeoutMs: this.focusManager.timeoutMs,
                wasTimeoutTriggered: this.focusLossTimeoutTerminal || false
            } : null
        };
    }

    /**
     * Emit multiplayer metrics to server via socket.
     * Call at scene termination to send validation data for server-side storage.
     * @param {string} sceneId - The scene ID for file organization
     */
    emitMultiplayerMetrics(sceneId) {
        const metrics = this.exportMultiplayerMetrics();

        socket.emit('emit_multiplayer_metrics', {
            scene_id: sceneId,
            metrics: metrics
        });

        p2pLog.info(
            `Emitted multiplayer metrics: ${metrics.validation.totalEpisodes} episodes, ` +
            `${metrics.validation.totalHashes} hashes, ${metrics.validation.totalDesyncs} desyncs`
        );
    }

    /**
     * Calculate the P2P receive ratio (percentage of inputs received via P2P).
     * @returns {number} Ratio from 0-100, or null if no inputs received
     * @private
     */
    _calculateP2PReceiveRatio() {
        const totalReceived = this.p2pMetrics.inputsReceivedViaP2P + this.p2pMetrics.inputsReceivedViaSocketIO;
        if (totalReceived === 0) return null;
        return (this.p2pMetrics.inputsReceivedViaP2P / totalReceived * 100);
    }

    /**
     * Export action history for debugging divergence.
     * Call from browser console: window.game.exportActionHistory()
     * Compare output between two clients to find where they diverged.
     * @param {number} startFrame - Optional start frame (default: 0)
     * @param {number} endFrame - Optional end frame (default: all)
     * @returns {Object} Action history with per-frame actions for all players
     */
    exportActionHistory(startFrame = 0, endFrame = Infinity) {
        const history = {
            playerId: this.myPlayerId,
            gameId: this.gameId,
            currentFrame: this.frameNumber,
            actionCount: this.actionSequence.length,
            frames: {}
        };

        for (const record of this.actionSequence) {
            if (record.frame >= startFrame && record.frame <= endFrame) {
                // Convert actions to simple format: {0: action, 1: action}
                const frameActions = {};
                for (const [pid, action] of Object.entries(record.actions)) {
                    frameActions[pid] = action;
                }
                history.frames[record.frame] = {
                    actions: frameActions,
                    isFocused: record.isFocused !== undefined ? record.isFocused : true
                };
            }
        }

        return history;
    }

    /**
     * Compare action histories from two clients and find divergences.
     * Usage:
     *   1. On client A: let histA = window.game.exportActionHistory()
     *   2. On client B: let histB = window.game.exportActionHistory()
     *   3. On either: window.game.compareActionHistories(histA, histB)
     * @param {Object} histA - Action history from client A
     * @param {Object} histB - Action history from client B
     * @returns {Object} Divergence report
     */
    compareActionHistories(histA, histB) {
        const divergences = [];
        const allFrames = new Set([
            ...Object.keys(histA.frames || {}),
            ...Object.keys(histB.frames || {})
        ]);

        for (const frameStr of [...allFrames].sort((a, b) => parseInt(a) - parseInt(b))) {
            const frame = parseInt(frameStr);
            const actionsA = histA.frames?.[frame];
            const actionsB = histB.frames?.[frame];

            if (!actionsA && actionsB) {
                divergences.push({ frame, issue: 'missing_in_A', actionsB });
            } else if (actionsA && !actionsB) {
                divergences.push({ frame, issue: 'missing_in_B', actionsA });
            } else if (actionsA && actionsB) {
                // Compare each player's action
                const allPlayers = new Set([...Object.keys(actionsA), ...Object.keys(actionsB)]);
                for (const pid of allPlayers) {
                    if (actionsA[pid] !== actionsB[pid]) {
                        divergences.push({
                            frame,
                            player: pid,
                            issue: 'action_mismatch',
                            actionA: actionsA[pid],
                            actionB: actionsB[pid]
                        });
                    }
                }
            }
        }

        return {
            playerA: histA.playerId,
            playerB: histB.playerId,
            framesA: Object.keys(histA.frames || {}).length,
            framesB: Object.keys(histB.frames || {}).length,
            divergenceCount: divergences.length,
            firstDivergence: divergences[0] || null,
            divergences: divergences.slice(0, 20)  // First 20 divergences
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
