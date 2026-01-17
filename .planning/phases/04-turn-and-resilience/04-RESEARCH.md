# Phase 4: TURN and Resilience - Research

**Researched:** 2026-01-17
**Domain:** TURN Server Fallback, Connection Type Detection, Resilience Monitoring
**Confidence:** HIGH

## Summary

This phase adds TURN server fallback for users behind restrictive NATs (symmetric NAT, corporate firewalls) and implements connection type detection via `RTCPeerConnection.getStats()` for research analytics. The existing WebRTC implementation in `webrtc_manager.js` only configures STUN servers; Phase 4 extends this with TURN credentials and adds monitoring to detect and log whether connections are direct P2P or relayed.

The primary work involves:
1. Adding TURN server credentials to the ICE server configuration
2. Implementing `getStats()` polling to detect connection type (host/srflx/relay)
3. Logging connection type to session data for research analytics
4. Adding connection quality degradation warnings with configurable thresholds
5. Testing TURN functionality using `iceTransportPolicy: 'relay'` mode

Without TURN, approximately 10-20% of users cannot connect due to symmetric NAT or restrictive firewalls. TURN acts as a relay server when direct P2P connections fail, ensuring connectivity at the cost of additional latency (typically 100-300ms RTT increase).

**Primary recommendation:** Use the free Open Relay Project TURN servers from Metered.ca for initial implementation (20GB/month free tier). Configure both UDP and TCP TURN transports on ports 80/443 for maximum firewall traversal. Monitor connection type and log to session data for research analysis.

## Current WebRTC Configuration

### Existing ICE Server Config (webrtc_manager.js line 112-117)

```javascript
const config = {
    iceServers: [
        { urls: 'stun:stun.l.google.com:19302' }
    ]
};
```

**Issue:** STUN only. If direct P2P and server-reflexive candidates fail (symmetric NAT), connection fails entirely.

### Target Configuration

```javascript
const config = {
    iceServers: [
        // STUN servers (free, always available)
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },

        // TURN servers (relay fallback)
        {
            urls: 'turn:a.relay.metered.ca:80',
            username: '<credential-username>',
            credential: '<credential-password>'
        },
        {
            urls: 'turn:a.relay.metered.ca:80?transport=tcp',
            username: '<credential-username>',
            credential: '<credential-password>'
        },
        {
            urls: 'turn:a.relay.metered.ca:443',
            username: '<credential-username>',
            credential: '<credential-password>'
        },
        {
            urls: 'turns:a.relay.metered.ca:443?transport=tcp',
            username: '<credential-username>',
            credential: '<credential-password>'
        }
    ]
};
```

## Standard Stack

### Core
| Component | Purpose | Why Standard |
|-----------|---------|--------------|
| RTCPeerConnection.getStats() | Connection type detection | Browser-native API, standardized W3C spec |
| Open Relay Project TURN | Free TURN relay | 20GB/month free, enterprise reliability, global distribution |
| TURN REST API pattern | Ephemeral credentials | Industry standard (draft-uberti-behave-turn-rest-00) |

### Supporting
| Component | Purpose | When to Use |
|-----------|---------|-------------|
| Google STUN servers | NAT traversal discovery | Always (free, unlimited) |
| iceTransportPolicy: 'relay' | Force TURN testing | Development/testing only |
| Trickle ICE test page | Verify TURN config | Initial setup validation |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Open Relay Project | Self-hosted Coturn | More control but ops overhead |
| Open Relay Project | Twilio TURN | More expensive but enterprise SLA |
| Open Relay Project | ExpressTURN | Alternative free tier (1TB/month) |
| Dynamic credentials | Static credentials | Less secure but simpler |

**TURN Provider Comparison:**

| Provider | Free Tier | Features | Notes |
|----------|-----------|----------|-------|
| Open Relay (Metered) | 20GB/month | Ports 80/443, TCP/UDP, TURNS | Recommended for research |
| ExpressTURN | 1TB/month | Ports 3478, 80, 443 | Higher limit, alternative |
| Google STUN | Unlimited | STUN only | No TURN relay |
| Self-hosted Coturn | N/A | Full control | Requires infrastructure |

## Architecture Patterns

### Pattern 1: ICE Server Configuration with TURN

**What:** Configure RTCPeerConnection with multiple TURN server options
**When to use:** Always - ensures connectivity even behind symmetric NAT
**Why:** ICE tries candidates in priority order; TURN is last resort fallback

```javascript
// Source: MDN RTCPeerConnection, Open Relay documentation
_createPeerConnection() {
    const config = {
        iceServers: this._getIceServers(),
        // Optional: force relay for testing
        // iceTransportPolicy: 'relay'
    };

    this.peerConnection = new RTCPeerConnection(config);
    // ... existing setup code
}

_getIceServers() {
    return [
        // Public STUN (free, always first)
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },

        // TURN UDP on port 80 (most permissive)
        {
            urls: 'turn:a.relay.metered.ca:80',
            username: this.turnUsername,
            credential: this.turnCredential
        },
        // TURN TCP on port 80 (for UDP-blocked networks)
        {
            urls: 'turn:a.relay.metered.ca:80?transport=tcp',
            username: this.turnUsername,
            credential: this.turnCredential
        },
        // TURN UDP on port 443 (alternative)
        {
            urls: 'turn:a.relay.metered.ca:443',
            username: this.turnUsername,
            credential: this.turnCredential
        },
        // TURNS over TLS on port 443 (most restrictive networks)
        {
            urls: 'turns:a.relay.metered.ca:443?transport=tcp',
            username: this.turnUsername,
            credential: this.turnCredential
        }
    ];
}
```

### Pattern 2: Connection Type Detection via getStats()

**What:** Poll RTCPeerConnection.getStats() to determine active connection type
**When to use:** After connection established, for logging/analytics
**Why:** Research analytics need to know if P2P was direct or relayed

```javascript
// Source: MDN RTCIceCandidatePairStats, RTCIceCandidateStats
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
```

### Pattern 3: Connection Quality Monitoring

**What:** Periodic getStats() polling for RTT, packet loss, and quality metrics
**When to use:** During active gameplay for degradation warnings
**Why:** Detect TURN latency overhead, trigger warnings/fallbacks

```javascript
// Source: MDN RTCIceCandidatePairStats
class ConnectionQualityMonitor {
    constructor(peerConnection, options = {}) {
        this.pc = peerConnection;
        this.pollInterval = options.pollInterval || 2000;  // 2 seconds
        this.warningLatencyMs = options.warningLatency || 150;
        this.criticalLatencyMs = options.criticalLatency || 300;

        this.lastStats = null;
        this.intervalId = null;

        // Callbacks
        this.onQualityChange = null;
        this.onDegradation = null;
    }

    start() {
        this.intervalId = setInterval(() => this._poll(), this.pollInterval);
    }

    stop() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
    }

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
```

### Pattern 4: ICE Restart for Recovery

**What:** Use restartIce() when connection fails to attempt recovery
**When to use:** When iceConnectionState becomes 'failed'
**Why:** ICE restart can recover ~66% of failed connections

```javascript
// Source: MDN RTCPeerConnection.restartIce()
_setupConnectionStateHandlers() {
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
                this._logConnectionType();
                break;
        }
    };
}

_handleIceFailure() {
    if (this.iceRestartAttempts >= this.maxIceRestarts) {
        console.error('[WebRTC] Max ICE restart attempts reached');
        this.onConnectionFailed?.();
        return;
    }

    this.iceRestartAttempts++;
    this.peerConnection.restartIce();

    // restartIce() triggers negotiationneeded event
    // Need to create new offer with ice restart flag
}

_startDisconnectTimeout() {
    this.disconnectTimeoutId = setTimeout(() => {
        if (this.peerConnection?.iceConnectionState === 'disconnected') {
            console.warn('[WebRTC] Disconnect timeout, triggering ICE restart');
            this._handleIceFailure();
        }
    }, 5000);  // 5 second grace period
}

_cancelDisconnectTimeout() {
    if (this.disconnectTimeoutId) {
        clearTimeout(this.disconnectTimeoutId);
        this.disconnectTimeoutId = null;
    }
}
```

### Anti-Patterns to Avoid

- **Hardcoding TURN credentials in JavaScript:** Credentials should be fetched from server or use ephemeral tokens
- **Not including TCP TURN transport:** UDP may be blocked; always include TCP on ports 80/443
- **Polling getStats() too frequently:** 1-2 second intervals sufficient; more wastes CPU
- **Treating 'disconnected' as terminal:** Connection may recover; only 'failed' is terminal
- **Single TURN server:** Include multiple URLs/ports for redundancy

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TURN infrastructure | Self-hosted Coturn | Open Relay Project / Metered | Free tier sufficient for research |
| Credential generation | Custom auth system | TURN REST API pattern | Industry standard, well-tested |
| Connection type parsing | Manual stats iteration | Helper function pattern above | getStats() API is complex |
| Latency detection | Custom ping system | getStats() currentRoundTripTime | Browser already measures accurately |

**Key insight:** The browser's WebRTC implementation handles TURN failover automatically via ICE priority. The main work is configuration and monitoring, not protocol implementation.

## Common Pitfalls

### Pitfall 1: TURN Credentials Not Reaching Client

**What goes wrong:** TURN servers configured but relay candidates never generated
**Why it happens:** Credentials expired, wrong format, or not passed to client
**How to avoid:** Test with Trickle ICE tool; verify relay candidates appear
**Warning signs:** Only host/srflx candidates generated, no relay candidates

**Verification:**
```javascript
// Add to debugging - watch for relay candidates
this.peerConnection.onicecandidate = (event) => {
    if (event.candidate) {
        console.log('[WebRTC] ICE candidate:', {
            type: event.candidate.type,
            protocol: event.candidate.protocol,
            address: event.candidate.address
        });
        // Should see type: 'relay' if TURN is working
    }
};
```

### Pitfall 2: TURN Latency Not Detected

**What goes wrong:** Connection is relayed but metrics show good latency
**Why it happens:** Not accounting for relay hop in measurements
**How to avoid:** Log connection type separately from latency; expect 50-150ms overhead
**Warning signs:** Users report lag but metrics look fine

**Research note:** For research analytics, always log both:
1. Connection type (direct vs relay)
2. Measured RTT

Don't assume relay = bad experience. TURN latency varies by server location.

### Pitfall 3: ICE Restart Loop

**What goes wrong:** Continuous ICE restarts without recovery
**Why it happens:** Underlying network issue not resolvable; no attempt limit
**How to avoid:** Limit restart attempts; fall back to SocketIO gracefully
**Warning signs:** Multiple "ICE restart" logs in quick succession

### Pitfall 4: getStats() Browser Differences

**What goes wrong:** Connection type detection fails on some browsers
**Why it happens:** Firefox lacks some stats; Chrome uses different property names
**How to avoid:** Handle missing properties gracefully; test all target browsers
**Warning signs:** null/undefined values in stats on certain browsers

**Note (as of 2025):** Firefox still has some gaps in getStats() implementation. The `selectedCandidatePairId` approach works in Chrome/Edge but may need fallback for Firefox using the non-standard `selected` property on candidate-pair stats.

### Pitfall 5: TURN Bandwidth Exhaustion

**What goes wrong:** Free tier exhausted mid-study
**Why it happens:** Not monitoring TURN usage; relay used more than expected
**How to avoid:** Monitor usage via provider dashboard; set alerts; have backup plan
**Warning signs:** Connection failures after sustained use

**Bandwidth estimation:**
- 60 FPS game at 30 bytes/packet = ~1.8 KB/s per peer
- 2 players, 60-minute session = ~13 MB via TURN
- 20 GB free tier = ~1500 sessions/month if all relayed

## Code Examples

### Complete TURN Configuration

```javascript
// Source: Open Relay Project documentation, MDN RTCPeerConnection
class WebRTCManager {
    constructor(socket, gameId, myPlayerId, options = {}) {
        // ... existing constructor code ...

        // TURN configuration
        this.turnUsername = options.turnUsername || null;
        this.turnCredential = options.turnCredential || null;
        this.forceRelay = options.forceRelay || false;  // For testing

        // Connection monitoring
        this.connectionType = null;
        this.qualityMonitor = null;
        this.iceRestartAttempts = 0;
        this.maxIceRestarts = 3;

        // Callbacks
        this.onConnectionTypeDetected = null;
        this.onQualityDegraded = null;
    }

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

        // ... existing event handlers ...

        // Add connection type detection on connected
        const originalStateHandler = this.peerConnection.onconnectionstatechange;
        this.peerConnection.onconnectionstatechange = async () => {
            originalStateHandler?.call(this);

            if (this.peerConnection.connectionState === 'connected') {
                await this._detectConnectionType();
                this._startQualityMonitoring();
            }
        };
    }

    _getIceServers() {
        const servers = [
            { urls: 'stun:stun.l.google.com:19302' },
            { urls: 'stun:stun1.l.google.com:19302' }
        ];

        // Add TURN servers if credentials provided
        if (this.turnUsername && this.turnCredential) {
            const turnServers = [
                'turn:a.relay.metered.ca:80',
                'turn:a.relay.metered.ca:80?transport=tcp',
                'turn:a.relay.metered.ca:443',
                'turns:a.relay.metered.ca:443?transport=tcp'
            ];

            for (const url of turnServers) {
                servers.push({
                    urls: url,
                    username: this.turnUsername,
                    credential: this.turnCredential
                });
            }
        }

        return servers;
    }

    async _detectConnectionType() {
        const connType = await this.getConnectionType();
        if (connType) {
            this.connectionType = connType;
            console.log('[WebRTC] Connection type:', connType);
            this.onConnectionTypeDetected?.(connType);
        }
    }

    _startQualityMonitoring() {
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

    // Clean up in close()
    close() {
        this.qualityMonitor?.stop();
        this.qualityMonitor = null;

        // ... existing close code ...
    }
}
```

### Server-Side TURN Credential Endpoint

```python
# Source: TURN REST API draft, coturn documentation
# Add to app.py or create new endpoint

import hmac
import hashlib
import base64
import time

# Configuration (would typically come from environment)
TURN_SECRET = os.environ.get('TURN_SECRET', 'openrelayprojectsecret')
TURN_SERVERS = [
    'turn:a.relay.metered.ca:80',
    'turn:a.relay.metered.ca:80?transport=tcp',
    'turn:a.relay.metered.ca:443',
    'turns:a.relay.metered.ca:443?transport=tcp'
]
CREDENTIAL_TTL = 86400  # 24 hours

def generate_turn_credentials(user_id: str) -> dict:
    """
    Generate time-limited TURN credentials using HMAC-SHA1.

    Uses the TURN REST API credential format:
    - username: "<expiry-timestamp>:<user-id>"
    - password: base64(hmac-sha1(secret, username))
    """
    expiry = int(time.time()) + CREDENTIAL_TTL
    username = f"{expiry}:{user_id}"

    # Generate HMAC-SHA1 password
    hmac_obj = hmac.new(
        TURN_SECRET.encode('utf-8'),
        username.encode('utf-8'),
        hashlib.sha1
    )
    password = base64.b64encode(hmac_obj.digest()).decode('utf-8')

    return {
        'username': username,
        'credential': password,
        'ttl': CREDENTIAL_TTL,
        'uris': TURN_SERVERS
    }

@app.route('/api/turn-credentials')
def get_turn_credentials():
    """
    Endpoint to fetch TURN credentials for WebRTC.
    Called by client before establishing P2P connection.
    """
    # Could use session ID, player ID, etc.
    user_id = request.args.get('user_id', 'anonymous')

    credentials = generate_turn_credentials(user_id)

    return jsonify({
        'iceServers': [
            {'urls': 'stun:stun.l.google.com:19302'},
            {'urls': 'stun:stun1.l.google.com:19302'},
            *[{
                'urls': uri,
                'username': credentials['username'],
                'credential': credentials['credential']
            } for uri in credentials['uris']]
        ]
    })
```

### Session Data Logging

```javascript
// Add to pyodide_multiplayer_game.js - log connection type for research

_logConnectionTypeForResearch() {
    if (!this.webrtcManager?.connectionType) return;

    const connInfo = this.webrtcManager.connectionType;

    // Add to session metadata
    this.sessionData = this.sessionData || {};
    this.sessionData.p2p_connection = {
        type: connInfo.connectionType,  // 'direct' or 'relay'
        local_candidate_type: connInfo.localCandidateType,
        remote_candidate_type: connInfo.remoteCandidateType,
        protocol: connInfo.localProtocol,
        relay_protocol: connInfo.relayProtocol,
        detected_at_frame: this.frameNumber,
        timestamp: Date.now()
    };

    // Log for immediate visibility
    console.log('[Research] P2P connection type:', this.sessionData.p2p_connection);

    // Send to server for persistence
    this.socket.emit('session_metadata', {
        game_id: this.gameId,
        player_id: this.myPlayerId,
        metadata: { p2p_connection: this.sessionData.p2p_connection }
    });
}
```

### Testing TURN with Force Relay

```javascript
// For development/testing - force all connections through TURN

// Option 1: Via constructor option
const webrtcManager = new WebRTCManager(socket, gameId, myPlayerId, {
    turnUsername: credentials.username,
    turnCredential: credentials.credential,
    forceRelay: true  // Forces iceTransportPolicy: 'relay'
});

// Option 2: Via console for ad-hoc testing
// Set before connection is established
window.FORCE_TURN_RELAY = true;

// Then in WebRTCManager._createPeerConnection():
if (window.FORCE_TURN_RELAY) {
    config.iceTransportPolicy = 'relay';
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Static TURN credentials | Ephemeral HMAC-SHA1 credentials | Always better | Time-limited access, more secure |
| Single TURN server | Multiple URLs/ports/protocols | Always | Better firewall traversal |
| No connection type logging | getStats() detection | Standard practice | Research insights into network conditions |
| Manual ping for RTT | getStats() currentRoundTripTime | getStats() more accurate | Browser-measured, no overhead |

**Deprecated/outdated:**
- Relying on STUN alone: 10-20% of users cannot connect
- Long-lived static TURN passwords: Security risk
- Ignoring connection type in analytics: Missing research data

## Integration Points

### Files to Modify

| File | Changes |
|------|---------|
| `webrtc_manager.js` | Add TURN servers, getStats() methods, quality monitoring |
| `pyodide_multiplayer_game.js` | Add connection type logging, quality warning UI |
| `app.py` | Add TURN credential endpoint (optional) |

### New Methods to Add

| Method | Location | Purpose |
|--------|----------|---------|
| `_getIceServers()` | WebRTCManager | Build ICE server config with TURN |
| `getConnectionType()` | WebRTCManager | Detect direct vs relay via getStats() |
| `ConnectionQualityMonitor` | New class | Poll getStats() for quality metrics |
| `_logConnectionTypeForResearch()` | PyodideMultiplayerGame | Save connection type to session data |

### Success Verification

The success criteria from the phase description:

1. **TURN server credentials are configured and used when ICE direct connection fails**
   - Verify: Test with `forceRelay: true`; confirm relay candidates generated
   - Verify: Connection succeeds behind corporate firewall (if available)

2. **Connection type (direct vs relay) is detected via RTCPeerConnection.getStats()**
   - Verify: `getConnectionType()` returns correct type
   - Verify: Works in Chrome, Firefox, Safari

3. **Connection type is logged in session data for research analytics**
   - Verify: Session data includes `p2p_connection.type`
   - Verify: Data persists to server

4. **Gameplay works correctly over TURN relay with acceptable latency**
   - Verify: With `forceRelay: true`, game is playable
   - Verify: RTT typically 100-300ms higher than direct

5. **Connection quality degradation triggers appropriate warnings/fallbacks**
   - Verify: Warning callback fires when RTT > threshold
   - Verify: Existing SocketIO fallback still functions

## Open Questions

1. **Ephemeral vs static credentials**
   - What we know: Ephemeral is more secure
   - What's unclear: Whether Open Relay supports ephemeral auth
   - Recommendation: Start with static for Open Relay; add ephemeral if self-hosting later

2. **Quality threshold tuning**
   - What we know: 100ms warning, 200ms critical from Phase 2
   - What's unclear: Whether TURN adds consistent overhead
   - Recommendation: Measure actual TURN latency; may need higher thresholds for relay

3. **Firefox getStats() compatibility**
   - What we know: Firefox has some gaps in stats implementation
   - What's unclear: Exact properties missing
   - Recommendation: Test thoroughly; add fallbacks for missing properties

## Sources

### Primary (HIGH confidence)
- [MDN: RTCPeerConnection.getStats()](https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnection/getStats) - getStats API documentation
- [MDN: RTCIceCandidatePairStats](https://developer.mozilla.org/en-US/docs/Web/API/RTCIceCandidatePairStats) - Candidate pair stats properties
- [MDN: RTCIceCandidateStats](https://developer.mozilla.org/en-US/docs/Web/API/RTCIceCandidateStats) - Candidate type detection
- [MDN: restartIce()](https://developer.mozilla.org/en-US/docs/Web/API/RTCPeerConnection/restartIce) - ICE restart for recovery
- [Open Relay Project](https://www.metered.ca/tools/openrelay/) - Free TURN server documentation

### Secondary (MEDIUM confidence)
- [WebRTC.ventures STUN/TURN Setup](https://webrtc.ventures/2025/01/how-to-set-up-self-hosted-stun-turn-servers-for-webrtc-applications/) - TURN best practices
- [VideoSDK TURN Guide](https://www.videosdk.live/developer-hub/webrtc/turn-server-for-webrtc) - TURN overview and usage patterns
- [BlogGeek ICE Connections](https://bloggeek.me/webrtc-ice-connection/) - Connection type detection guide
- [TestRTC Active Connection](https://testrtc.com/find-webrtc-active-connection/) - Finding active candidate pair

### Tertiary (LOW confidence)
- [TURN REST API Draft](https://datatracker.ietf.org/doc/html/draft-uberti-behave-turn-rest-00) - Ephemeral credential standard
- WebSearch results for TURN latency overhead - estimates vary by provider/location

## Metadata

**Confidence breakdown:**
- TURN configuration: HIGH - Standard practice, well-documented
- getStats() API: HIGH - MDN documentation is authoritative
- Connection type detection: MEDIUM - Browser differences may require testing
- Quality monitoring: MEDIUM - Thresholds need real-world tuning
- Open Relay free tier: HIGH - Documented 20GB/month limit

**Research date:** 2026-01-17
**Valid until:** 30 days (TURN providers may change; getStats API stable)
