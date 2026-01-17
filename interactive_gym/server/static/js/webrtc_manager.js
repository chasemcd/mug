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
 */

class WebRTCManager {
    /**
     * Create a WebRTC connection manager.
     * @param {Object} socket - SocketIO socket instance
     * @param {string} gameId - Game identifier
     * @param {string|number} myPlayerId - This player's ID
     */
    constructor(socket, gameId, myPlayerId) {
        this.socket = socket;
        this.gameId = gameId;
        this.myPlayerId = myPlayerId;
        this.peerConnection = null;
        this.dataChannel = null;
        this.pendingCandidates = [];
        this.remoteDescriptionSet = false;
        this.targetPeerId = null;

        // Callbacks (set by consumer)
        this.onDataChannelOpen = null;
        this.onDataChannelMessage = null;
        this.onDataChannelClose = null;
        this.onConnectionFailed = null;

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
            iceServers: [
                { urls: 'stun:stun.l.google.com:19302' }
            ]
        };

        this.peerConnection = new RTCPeerConnection(config);

        // Handle ICE candidates
        this.peerConnection.onicecandidate = (event) => {
            if (event.candidate) {
                this._sendSignal('ice-candidate', event.candidate);
                console.log('[WebRTC] Sent ICE candidate');
            }
        };

        // Handle connection state changes
        this.peerConnection.onconnectionstatechange = () => {
            const state = this.peerConnection.connectionState;
            console.log(`[WebRTC] Connection state: ${state}`);

            if (state === 'failed') {
                console.error('[WebRTC] Connection failed');
                this.onConnectionFailed?.();
            } else if (state === 'connected') {
                console.log('[WebRTC] Peer connection established');
            }
        };

        // Handle ICE connection state (more granular than connection state)
        this.peerConnection.oniceconnectionstatechange = () => {
            const state = this.peerConnection.iceConnectionState;
            console.log(`[WebRTC] ICE connection state: ${state}`);
        };

        // Handle incoming DataChannel (for answerer)
        this.peerConnection.ondatachannel = (event) => {
            console.log('[WebRTC] Received DataChannel');
            this.dataChannel = event.channel;
            this._setupDataChannel(this.dataChannel);
        };
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
export { WebRTCManager };
export default WebRTCManager;
