/**
 * WebRTC Connection Manager
 *
 * Handles RTCPeerConnection lifecycle, DataChannel creation, and signaling
 * message handling for peer-to-peer game communication.
 *
 * Features:
 * - Unreliable/unordered DataChannel for GGPO-style input exchange
 * - ICE candidate buffering to handle out-of-order signaling
 * - SocketIO-based signaling relay
 * - Deterministic initiator/answerer role assignment
 * - TURN server fallback for NAT traversal
 * - Connection type detection (direct vs relay)
 * - Connection quality monitoring
 * - ICE restart for connection recovery
 */

/**
 * Monitors P2P connection quality by polling RTCPeerConnection.getStats().
 * Detects latency degradation and invokes callbacks for warnings.
 */
class ConnectionQualityMonitor {
    /**
     * Create a connection quality monitor.
     * @param {RTCPeerConnection} peerConnection - The peer connection to monitor
     * @param {Object} options - Monitor options
     * @param {number} options.pollInterval - Polling interval in ms (default: 2000)
     * @param {number} options.warningLatency - RTT threshold for warning in ms (default: 150)
     * @param {number} options.criticalLatency - RTT threshold for critical in ms (default: 300)
     */
    constructor(peerConnection, options = {}) {
        this.pc = peerConnection;
        this.pollInterval = options.pollInterval || 2000;
        this.warningLatencyMs = options.warningLatency || 150;
        this.criticalLatencyMs = options.criticalLatency || 300;

        this.lastStats = null;
        this.intervalId = null;

        // Callbacks
        this.onQualityChange = null;
        this.onDegradation = null;
    }

    /**
     * Start polling for connection quality metrics.
     */
    start() {
        this.intervalId = setInterval(() => this._poll(), this.pollInterval);
    }

    /**
     * Stop polling.
     */
    stop() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
    }

    /**
     * Poll getStats() and check thresholds.
     * @private
     */
    async _poll() {
        if (!this.pc || this.pc.connectionState !== 'connected') return;

        try {
            const stats = await this.pc.getStats();
            const quality = this._extractQualityMetrics(stats);

            if (quality) {
                this._checkThresholds(quality);
                this.lastStats = quality;
            }
        } catch (e) {
            console.warn('[QualityMonitor] Poll failed:', e);
        }
    }

    /**
     * Extract quality metrics from getStats() results.
     * @private
     * @param {RTCStatsReport} stats - Stats from getStats()
     * @returns {Object|null} Quality metrics or null if unavailable
     */
    _extractQualityMetrics(stats) {
        let selectedPairId = null;
        let pairStats = null;

        // Find transport and selected pair
        stats.forEach(report => {
            if (report.type === 'transport' && report.selectedCandidatePairId) {
                selectedPairId = report.selectedCandidatePairId;
            }
        });

        if (!selectedPairId) return null;

        stats.forEach(report => {
            if (report.type === 'candidate-pair' && report.id === selectedPairId) {
                pairStats = report;
            }
        });

        if (!pairStats) return null;

        return {
            currentRtt: pairStats.currentRoundTripTime ?
                        pairStats.currentRoundTripTime * 1000 : null,  // Convert to ms
            avgRtt: pairStats.totalRoundTripTime && pairStats.responsesReceived ?
                    (pairStats.totalRoundTripTime / pairStats.responsesReceived) * 1000 : null,
            bytesSent: pairStats.bytesSent,
            bytesReceived: pairStats.bytesReceived,
            packetsSent: pairStats.packetsSent,
            packetsReceived: pairStats.packetsReceived,
            state: pairStats.state,
            availableOutgoingBitrate: pairStats.availableOutgoingBitrate,
            timestamp: pairStats.timestamp
        };
    }

    /**
     * Check metrics against thresholds and invoke callbacks.
     * @private
     * @param {Object} quality - Quality metrics
     */
    _checkThresholds(quality) {
        const rtt = quality.currentRtt || quality.avgRtt;

        if (rtt === null) return;

        let status = 'good';
        if (rtt > this.criticalLatencyMs) {
            status = 'critical';
        } else if (rtt > this.warningLatencyMs) {
            status = 'warning';
        }

        this.onQualityChange?.({
            status,
            rtt,
            ...quality
        });

        if (status !== 'good') {
            this.onDegradation?.({
                status,
                rtt,
                message: `Connection latency ${status}: ${rtt.toFixed(0)}ms RTT`
            });
        }
    }
}

class WebRTCManager {
    /**
     * Create a WebRTC connection manager.
     * @param {Object} socket - SocketIO socket instance
     * @param {string} gameId - Game identifier
     * @param {string|number} myPlayerId - This player's ID
     * @param {Object} options - Optional configuration
     * @param {string} options.turnUsername - TURN server username
     * @param {string} options.turnCredential - TURN server credential/password
     * @param {boolean} options.forceRelay - Force relay-only connections (for testing)
     */
    constructor(socket, gameId, myPlayerId, options = {}) {
        this.socket = socket;
        this.gameId = gameId;
        this.myPlayerId = myPlayerId;
        this.peerConnection = null;
        this.dataChannel = null;
        this.pendingCandidates = [];
        this.remoteDescriptionSet = false;
        this.targetPeerId = null;

        // TURN configuration
        this.turnUsername = options.turnUsername || null;
        this.turnCredential = options.turnCredential || null;
        this.forceRelay = options.forceRelay || false;

        // Connection monitoring
        this.connectionType = null;
        this.iceRestartAttempts = 0;
        this.maxIceRestarts = 3;
        this.disconnectTimeoutId = null;
        this.qualityMonitor = null;

        // Callbacks (set by consumer)
        this.onDataChannelOpen = null;
        this.onDataChannelMessage = null;
        this.onDataChannelClose = null;
        this.onConnectionFailed = null;
        this.onConnectionTypeDetected = null;
        this.onQualityDegraded = null;

        // Bound handler reference for cleanup
        this._boundSignalHandler = null;

        this._setupSignalingHandlers();
    }

    /**
     * Set up SocketIO event listeners for WebRTC signaling.
     * @private
     */
    _setupSignalingHandlers() {
        this._boundSignalHandler = (data) => this._handleSignal(data);
        this.socket.on('webrtc_signal', this._boundSignalHandler);
    }

    /**
     * Initiate connection to a peer.
     * Uses deterministic role assignment: lower player ID is the initiator.
     * @param {string|number} peerId - Target peer's player ID
     */
    async connectToPeer(peerId) {
        this.targetPeerId = peerId;
        this._createPeerConnection();

        // Deterministic role assignment: lower ID is initiator
        const isInitiator = this._comparePlayerIds(this.myPlayerId, peerId) < 0;

        console.log(`[WebRTC] Connecting to peer ${peerId} as ${isInitiator ? 'initiator' : 'answerer'}`);

        if (isInitiator) {
            // Create DataChannel before creating offer
            this.dataChannel = this.peerConnection.createDataChannel('game', {
                ordered: false,       // Unordered for UDP-like behavior
                maxRetransmits: 0     // No retransmits (GGPO handles loss)
            });
            this._setupDataChannel(this.dataChannel);

            // Create and send offer
            try {
                const offer = await this.peerConnection.createOffer();
                await this.peerConnection.setLocalDescription(offer);
                this._sendSignal('offer', this.peerConnection.localDescription);
                console.log('[WebRTC] Sent offer');
            } catch (error) {
                console.error('[WebRTC] Failed to create offer:', error);
                this.onConnectionFailed?.();
            }
        }
        // Answerer waits for ondatachannel event
    }

    /**
     * Compare player IDs for initiator determination.
     * Handles both string and numeric player IDs.
     * @private
     * @param {string|number} a - First player ID
     * @param {string|number} b - Second player ID
     * @returns {number} Negative if a < b, positive if a > b, 0 if equal
     */
    _comparePlayerIds(a, b) {
        // Convert to numbers if both are numeric
        const numA = typeof a === 'number' ? a : (isNaN(Number(a)) ? null : Number(a));
        const numB = typeof b === 'number' ? b : (isNaN(Number(b)) ? null : Number(b));

        if (numA !== null && numB !== null) {
            return numA - numB;
        }
        // Fall back to string comparison
        return String(a).localeCompare(String(b));
    }

    /**
     * Create and configure RTCPeerConnection.
     * @private
     */
    _createPeerConnection() {
        const config = {
            iceServers: this._getIceServers()
        };

        // Force relay for testing TURN
        if (this.forceRelay) {
            config.iceTransportPolicy = 'relay';
            console.log('[WebRTC] Forcing relay mode (testing)');
        }

        this.peerConnection = new RTCPeerConnection(config);

        // Handle ICE candidates
        this.peerConnection.onicecandidate = (event) => {
            if (event.candidate) {
                this._sendSignal('ice-candidate', event.candidate);
                console.log('[WebRTC] Sent ICE candidate:', {
                    type: event.candidate.type,
                    protocol: event.candidate.protocol
                });
            }
        };

        // Handle connection state changes
        this.peerConnection.onconnectionstatechange = async () => {
            const state = this.peerConnection.connectionState;
            console.log(`[WebRTC] Connection state: ${state}`);

            if (state === 'failed') {
                console.error('[WebRTC] Connection failed');
                this.onConnectionFailed?.();
            } else if (state === 'connected') {
                console.log('[WebRTC] Peer connection established');
                // Detect connection type after connection is established
                await this._detectConnectionType();
                // Start quality monitoring
                this._startQualityMonitoring();
            }
        };

        // Handle ICE connection state (more granular than connection state)
        this.peerConnection.oniceconnectionstatechange = () => {
            const state = this.peerConnection.iceConnectionState;
            console.log(`[WebRTC] ICE connection state: ${state}`);

            switch (state) {
                case 'failed':
                    console.warn('[WebRTC] ICE failed, attempting restart');
                    this._handleIceFailure();
                    break;
                case 'disconnected':
                    // May recover on its own - start timeout
                    this._startDisconnectTimeout();
                    break;
                case 'connected':
                case 'completed':
                    this._cancelDisconnectTimeout();
                    this.iceRestartAttempts = 0;  // Reset restart counter on successful connection
                    break;
            }
        };

        // Handle incoming DataChannel (for answerer)
        this.peerConnection.ondatachannel = (event) => {
            console.log('[WebRTC] Received DataChannel');
            this.dataChannel = event.channel;
            this._setupDataChannel(this.dataChannel);
        };
    }

    /**
     * Build ICE server configuration with STUN and optional TURN servers.
     * @private
     * @returns {Array} ICE server configuration array
     */
    _getIceServers() {
        const servers = [
            // Public STUN servers (free, always available)
            { urls: 'stun:stun.l.google.com:19302' },
            { urls: 'stun:stun1.l.google.com:19302' }
        ];

        // Add TURN servers if credentials provided
        if (this.turnUsername && this.turnCredential) {
            const turnServers = [
                // TURN UDP on port 80 (most permissive)
                'turn:a.relay.metered.ca:80',
                // TURN TCP on port 80 (for UDP-blocked networks)
                'turn:a.relay.metered.ca:80?transport=tcp',
                // TURN UDP on port 443 (alternative)
                'turn:a.relay.metered.ca:443',
                // TURNS over TLS on port 443 (most restrictive networks)
                'turns:a.relay.metered.ca:443?transport=tcp'
            ];

            for (const url of turnServers) {
                servers.push({
                    urls: url,
                    username: this.turnUsername,
                    credential: this.turnCredential
                });
            }

            console.log('[WebRTC] TURN servers configured');
        }

        return servers;
    }

    /**
     * Detect connection type (direct vs relay) via getStats() API.
     * @private
     */
    async _detectConnectionType() {
        const connType = await this.getConnectionType();
        if (connType) {
            this.connectionType = connType;
            console.log('[WebRTC] Connection type:', connType);
            this.onConnectionTypeDetected?.(connType);
        }
    }

    /**
     * Get connection type by analyzing the active candidate pair.
     * @returns {Promise<Object|null>} Connection type info or null if unavailable
     */
    async getConnectionType() {
        if (!this.peerConnection) return null;

        try {
            const stats = await this.peerConnection.getStats();

            // Step 1: Find selected candidate pair via transport stats
            let selectedPairId = null;
            stats.forEach(report => {
                if (report.type === 'transport' && report.selectedCandidatePairId) {
                    selectedPairId = report.selectedCandidatePairId;
                }
            });

            if (!selectedPairId) return null;

            // Step 2: Get the candidate pair
            let localCandidateId = null;
            let remoteCandidateId = null;
            stats.forEach(report => {
                if (report.type === 'candidate-pair' && report.id === selectedPairId) {
                    localCandidateId = report.localCandidateId;
                    remoteCandidateId = report.remoteCandidateId;
                }
            });

            // Step 3: Get candidate details
            let localCandidate = null;
            let remoteCandidate = null;
            stats.forEach(report => {
                if (report.type === 'local-candidate' && report.id === localCandidateId) {
                    localCandidate = report;
                }
                if (report.type === 'remote-candidate' && report.id === remoteCandidateId) {
                    remoteCandidate = report;
                }
            });

            // Step 4: Determine connection type
            const isRelay = localCandidate?.candidateType === 'relay' ||
                            remoteCandidate?.candidateType === 'relay';

            return {
                connectionType: isRelay ? 'relay' : 'direct',
                localCandidateType: localCandidate?.candidateType,
                remoteCandidateType: remoteCandidate?.candidateType,
                localProtocol: localCandidate?.protocol,
                relayProtocol: localCandidate?.relayProtocol || null
            };
        } catch (e) {
            console.error('[WebRTC] Failed to get connection type:', e);
            return null;
        }
    }

    /**
     * Handle ICE failure by attempting restart.
     * @private
     */
    _handleIceFailure() {
        if (this.iceRestartAttempts >= this.maxIceRestarts) {
            console.error('[WebRTC] Max ICE restart attempts reached');
            this.onConnectionFailed?.();
            return;
        }

        this.iceRestartAttempts++;
        console.log(`[WebRTC] ICE restart attempt ${this.iceRestartAttempts}/${this.maxIceRestarts}`);
        this.peerConnection.restartIce();
    }

    /**
     * Start timeout for disconnect recovery.
     * If still disconnected after timeout, trigger ICE restart.
     * @private
     */
    _startDisconnectTimeout() {
        this._cancelDisconnectTimeout();
        this.disconnectTimeoutId = setTimeout(() => {
            if (this.peerConnection?.iceConnectionState === 'disconnected') {
                console.warn('[WebRTC] Disconnect timeout, triggering ICE restart');
                this._handleIceFailure();
            }
        }, 5000);  // 5 second grace period
    }

    /**
     * Cancel disconnect timeout.
     * @private
     */
    _cancelDisconnectTimeout() {
        if (this.disconnectTimeoutId) {
            clearTimeout(this.disconnectTimeoutId);
            this.disconnectTimeoutId = null;
        }
    }

    /**
     * Start connection quality monitoring.
     * @private
     */
    _startQualityMonitoring() {
        if (this.qualityMonitor) {
            this.qualityMonitor.stop();
        }

        this.qualityMonitor = new ConnectionQualityMonitor(this.peerConnection, {
            warningLatency: 150,
            criticalLatency: 300
        });

        this.qualityMonitor.onDegradation = (info) => {
            console.warn('[WebRTC] Quality degraded:', info);
            this.onQualityDegraded?.(info);
        };

        this.qualityMonitor.start();
    }

    /**
     * Configure DataChannel event handlers.
     * @private
     * @param {RTCDataChannel} dc - The DataChannel to configure
     */
    _setupDataChannel(dc) {
        dc.binaryType = 'arraybuffer';

        dc.onopen = () => {
            console.log('[WebRTC] DataChannel open');
            this.onDataChannelOpen?.();
        };

        dc.onmessage = (event) => {
            this.onDataChannelMessage?.(event.data);
        };

        dc.onclose = () => {
            console.log('[WebRTC] DataChannel closed');
            this.onDataChannelClose?.();
        };

        dc.onerror = (error) => {
            console.error('[WebRTC] DataChannel error:', error);
        };
    }

    /**
     * Handle incoming signaling messages.
     * @private
     * @param {Object} data - Signaling message data
     */
    async _handleSignal(data) {
        const { type, from_player_id, payload, game_id } = data;

        // Ignore messages not for our game
        if (game_id !== this.gameId) {
            return;
        }

        // Ignore our own messages (shouldn't happen but safety check)
        if (from_player_id === this.myPlayerId) {
            return;
        }

        console.log(`[WebRTC] Received ${type} from player ${from_player_id}`);

        try {
            switch (type) {
                case 'offer':
                    await this._handleOffer(from_player_id, payload);
                    break;

                case 'answer':
                    await this._handleAnswer(payload);
                    break;

                case 'ice-candidate':
                    await this._handleIceCandidate(payload);
                    break;

                default:
                    console.warn(`[WebRTC] Unknown signal type: ${type}`);
            }
        } catch (error) {
            console.error(`[WebRTC] Error handling ${type}:`, error);
        }
    }

    /**
     * Handle incoming SDP offer.
     * @private
     * @param {string|number} fromPlayerId - Sender's player ID
     * @param {Object} payload - SDP offer
     */
    async _handleOffer(fromPlayerId, payload) {
        // Create peer connection if we don't have one
        if (!this.peerConnection) {
            this.targetPeerId = fromPlayerId;
            this._createPeerConnection();
        }

        // Set remote description (the offer)
        await this.peerConnection.setRemoteDescription(
            new RTCSessionDescription(payload)
        );
        this.remoteDescriptionSet = true;

        // Flush buffered ICE candidates
        await this._flushPendingCandidates();

        // Create and send answer
        const answer = await this.peerConnection.createAnswer();
        await this.peerConnection.setLocalDescription(answer);
        this._sendSignal('answer', this.peerConnection.localDescription);
        console.log('[WebRTC] Sent answer');
    }

    /**
     * Handle incoming SDP answer.
     * @private
     * @param {Object} payload - SDP answer
     */
    async _handleAnswer(payload) {
        await this.peerConnection.setRemoteDescription(
            new RTCSessionDescription(payload)
        );
        this.remoteDescriptionSet = true;

        // Flush buffered ICE candidates
        await this._flushPendingCandidates();
    }

    /**
     * Handle incoming ICE candidate.
     * Buffers candidates if remote description not yet set.
     * @private
     * @param {Object} payload - ICE candidate
     */
    async _handleIceCandidate(payload) {
        if (!payload) {
            // Null candidate signals end of candidates
            return;
        }

        const candidate = new RTCIceCandidate(payload);

        if (this.remoteDescriptionSet && this.peerConnection) {
            await this.peerConnection.addIceCandidate(candidate);
            console.log('[WebRTC] Added ICE candidate');
        } else {
            // Buffer until remote description is set
            this.pendingCandidates.push(candidate);
            console.log('[WebRTC] Buffered ICE candidate (waiting for remote description)');
        }
    }

    /**
     * Flush buffered ICE candidates after remote description is set.
     * @private
     */
    async _flushPendingCandidates() {
        for (const candidate of this.pendingCandidates) {
            try {
                await this.peerConnection.addIceCandidate(candidate);
                console.log('[WebRTC] Added buffered ICE candidate');
            } catch (error) {
                console.warn('[WebRTC] Failed to add buffered ICE candidate:', error);
            }
        }
        this.pendingCandidates = [];
    }

    /**
     * Send signaling message to target peer via SocketIO.
     * @private
     * @param {string} type - Signal type (offer, answer, ice-candidate)
     * @param {Object} payload - Signal payload
     */
    _sendSignal(type, payload) {
        this.socket.emit('webrtc_signal', {
            game_id: this.gameId,
            target_player_id: this.targetPeerId,
            type: type,
            payload: payload
        });
    }

    /**
     * Send data over the DataChannel.
     * @param {string|ArrayBuffer|Blob} data - Data to send
     * @returns {boolean} True if sent, false if channel not ready
     */
    send(data) {
        if (this.dataChannel?.readyState === 'open') {
            this.dataChannel.send(data);
            return true;
        }
        console.warn('[WebRTC] DataChannel not ready, dropping message');
        return false;
    }

    /**
     * Check if DataChannel is open and ready for sending.
     * @returns {boolean} True if ready to send
     */
    isReady() {
        return this.dataChannel?.readyState === 'open';
    }

    /**
     * Get current connection state.
     * @returns {string|null} Connection state or null if no connection
     */
    getConnectionState() {
        return this.peerConnection?.connectionState ?? null;
    }

    /**
     * Close the connection and clean up resources.
     */
    close() {
        console.log('[WebRTC] Closing connection');

        // Stop quality monitoring
        if (this.qualityMonitor) {
            this.qualityMonitor.stop();
            this.qualityMonitor = null;
        }

        // Cancel disconnect timeout
        this._cancelDisconnectTimeout();

        // Remove signaling event listener
        if (this._boundSignalHandler) {
            this.socket.off('webrtc_signal', this._boundSignalHandler);
            this._boundSignalHandler = null;
        }

        // Close DataChannel
        if (this.dataChannel) {
            this.dataChannel.close();
            this.dataChannel = null;
        }

        // Close PeerConnection
        if (this.peerConnection) {
            this.peerConnection.close();
            this.peerConnection = null;
        }

        // Clear state
        this.pendingCandidates = [];
        this.remoteDescriptionSet = false;
        this.targetPeerId = null;
    }
}

// Export for ES modules and global access
export { WebRTCManager, ConnectionQualityMonitor };
export default WebRTCManager;
