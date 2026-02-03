/**
 * Probe Connection
 *
 * Lightweight WebRTC connection wrapper for P2P RTT probing.
 * Used during matchmaking to measure actual peer-to-peer latency
 * BEFORE a game is created.
 *
 * Wraps WebRTCManager but uses probe-specific signaling events.
 */

import { WebRTCManager } from './webrtc_manager.js';

export class ProbeConnection {
    /**
     * Create a probe connection.
     * @param {Object} socket - SocketIO socket instance
     * @param {string} probeSessionId - Unique probe session identifier
     * @param {string} mySubjectId - This participant's subject_id
     * @param {string} peerSubjectId - Peer participant's subject_id
     * @param {Object} options - Configuration options
     * @param {string} options.turnUsername - TURN server username
     * @param {string} options.turnCredential - TURN server credential
     */
    constructor(socket, probeSessionId, mySubjectId, peerSubjectId, options = {}) {
        this.socket = socket;
        this.probeSessionId = probeSessionId;
        this.mySubjectId = mySubjectId;
        this.peerSubjectId = peerSubjectId;
        this.closed = false;

        // Create WebRTCManager with probe context
        // Use probeSessionId where gameId would go, mySubjectId where playerId would go
        this.webrtcManager = new WebRTCManager(
            socket,
            probeSessionId,
            mySubjectId,
            {
                turnUsername: options.turnUsername,
                turnCredential: options.turnCredential,
                // Don't force relay for probes - we want to find best path
            }
        );

        // Callbacks
        this.onConnected = null;
        this.onFailed = null;
        this.onClosed = null;

        // Timeout for connection establishment (10 seconds)
        this.connectionTimeout = null;
        this.connectionTimeoutMs = 10000;

        // Pending ping measurements keyed by sequence number
        // Each entry: { resolve: Function, reject: Function, timeout: number, sentAt: number }
        this.pendingPings = new Map();
        this.nextPingSeq = 0;

        this._setupCallbacks();
        this._setupSignaling();
    }

    _setupCallbacks() {
        this.webrtcManager.onDataChannelOpen = () => {
            console.log(`[Probe ${this.probeSessionId}] DataChannel open`);
            this._clearConnectionTimeout();
            this.onConnected?.();
        };

        this.webrtcManager.onConnectionFailed = () => {
            console.log(`[Probe ${this.probeSessionId}] Connection failed`);
            this._clearConnectionTimeout();
            this.onFailed?.();
        };

        this.webrtcManager.onDataChannelClose = () => {
            console.log(`[Probe ${this.probeSessionId}] DataChannel closed`);
            this.onClosed?.();
        };

        // Handle ping/pong messages over DataChannel
        this.webrtcManager.onDataChannelMessage = (data) => {
            this._handleDataChannelMessage(data);
        };
    }

    /**
     * Handle incoming DataChannel messages for ping-pong protocol.
     * @param {string} data - DataChannel message data (JSON string)
     */
    _handleDataChannelMessage(data) {
        try {
            const message = JSON.parse(data);

            if (message.type === 'ping') {
                // Received ping - immediately send back pong with same seq and ts
                const pong = {
                    type: 'pong',
                    seq: message.seq,
                    ts: message.ts
                };
                this.webrtcManager.dataChannel?.send(JSON.stringify(pong));
            } else if (message.type === 'pong') {
                // Received pong - resolve pending measurement
                const pending = this.pendingPings.get(message.seq);
                if (pending) {
                    clearTimeout(pending.timeout);
                    const rtt = Date.now() - pending.sentAt;
                    console.log(`[Probe ${this.probeSessionId}] Received pong seq=${message.seq}, RTT=${rtt}ms`);
                    this.pendingPings.delete(message.seq);
                    pending.resolve(rtt);
                }
            }
        } catch (e) {
            console.warn(`[Probe ${this.probeSessionId}] Failed to parse DataChannel message:`, e);
        }
    }

    _setupSignaling() {
        // Listen for probe-specific signals
        this._boundSignalHandler = (data) => {
            if (data.probe_session_id !== this.probeSessionId) return;

            // Translate probe signal to WebRTCManager signal format
            const webrtcSignal = {
                type: data.type,
                from_player_id: data.from_subject_id,
                game_id: this.probeSessionId,
                payload: data.payload,
            };

            // Pass to WebRTCManager's signal handler
            this.webrtcManager._handleSignal(webrtcSignal);
        };

        this.socket.on('probe_signal', this._boundSignalHandler);
    }

    /**
     * Start the probe connection.
     * Lower subject_id is deterministic initiator (same as game connections).
     */
    start() {
        if (this.closed) {
            console.warn(`[Probe ${this.probeSessionId}] Cannot start - already closed`);
            return;
        }

        console.log(`[Probe ${this.probeSessionId}] Starting connection to ${this.peerSubjectId}`);

        // Set connection timeout
        this.connectionTimeout = setTimeout(() => {
            console.warn(`[Probe ${this.probeSessionId}] Connection timeout`);
            this.onFailed?.();
        }, this.connectionTimeoutMs);

        // Override _sendSignal to use probe events instead of webrtc_signal
        const originalSendSignal = this.webrtcManager._sendSignal.bind(this.webrtcManager);
        this.webrtcManager._sendSignal = (type, payload) => {
            if (this.closed) return;
            this.socket.emit('probe_signal', {
                probe_session_id: this.probeSessionId,
                target_subject_id: this.peerSubjectId,
                type: type,
                payload: payload,
            });
        };

        // WebRTCManager.connectToPeer uses deterministic initiator
        this.webrtcManager.connectToPeer(this.peerSubjectId);
    }

    _clearConnectionTimeout() {
        if (this.connectionTimeout) {
            clearTimeout(this.connectionTimeout);
            this.connectionTimeout = null;
        }
    }

    /**
     * Check if probe connection is ready for measurement.
     * @returns {boolean}
     */
    isReady() {
        return this.webrtcManager.isReady();
    }

    /**
     * Get RTT via WebRTC getStats().
     * @returns {Promise<number|null>} RTT in milliseconds or null if unavailable
     */
    async getRTT() {
        if (!this.webrtcManager.peerConnection) return null;

        try {
            const stats = await this.webrtcManager.peerConnection.getStats();
            let selectedPairId = null;

            // Find transport with selected candidate pair
            stats.forEach(report => {
                if (report.type === 'transport' && report.selectedCandidatePairId) {
                    selectedPairId = report.selectedCandidatePairId;
                }
            });

            if (!selectedPairId) return null;

            // Find RTT from selected pair
            let rtt = null;
            stats.forEach(report => {
                if (report.type === 'candidate-pair' && report.id === selectedPairId) {
                    if (report.currentRoundTripTime !== undefined) {
                        rtt = report.currentRoundTripTime * 1000;  // Convert seconds to ms
                    }
                }
            });

            return rtt;
        } catch (e) {
            console.warn('[Probe] getRTT failed:', e);
            return null;
        }
    }

    /**
     * Close the probe connection and clean up.
     */
    close() {
        if (this.closed) return;
        this.closed = true;

        console.log(`[Probe ${this.probeSessionId}] Closing`);

        this._clearConnectionTimeout();

        // Remove signal listener
        if (this._boundSignalHandler) {
            this.socket.off('probe_signal', this._boundSignalHandler);
            this._boundSignalHandler = null;
        }

        // Close WebRTC connection
        this.webrtcManager.close();
    }
}
