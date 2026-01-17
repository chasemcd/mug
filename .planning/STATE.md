# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.
**Current focus:** Phase 5 - Validation and Cleanup (in progress)

## Current Position

Phase: 5 of 5 (Validation and Cleanup)
Plan: 1 of 3 complete
Status: In progress
Last activity: 2026-01-17 - Completed 05-01-PLAN.md (host concept removal)

Progress: [########+-] 82%

## Phase Overview

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 1 | WebRTC Foundation | WEBRTC-01, WEBRTC-02 | Complete |
| 2 | P2P Transport Layer | GGPO-02, GGPO-03 | Complete |
| 3 | GGPO P2P Integration | GGPO-01, NPLAY-01 | Complete |
| 4 | TURN and Resilience | WEBRTC-03, WEBRTC-04 | Complete |
| 5 | Validation and Cleanup | CLEAN-01 | In progress |

## Performance Metrics

**Velocity:**
- Total plans completed: 9
- Average duration: ~5 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 2 | ~20 min | ~10 min |
| 2 | 3 | ~6 min | ~2 min |
| 3 | 1 | ~5 min | ~5 min |
| 4 | 2 | ~10 min | ~5 min |
| 5 | 1 | ~2.5 min | ~2.5 min |

## Accumulated Context

### Key Files

**Created in Phase 1:**
- `interactive_gym/server/static/js/webrtc_manager.js` - WebRTCManager class (387 lines)

**Modified in Phase 1:**
- `interactive_gym/server/pyodide_game_coordinator.py` - Added `handle_webrtc_signal` method (lines 497-568)
- `interactive_gym/server/app.py` - Registered `webrtc_signal` SocketIO event (line 838)
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Integrated WebRTCManager, P2P test messages

**Modified in Phase 2:**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Binary protocol (encode/decode), RTTTracker, ConnectionHealthMonitor, P2PInputSender, message handlers, ping interval

**Modified in Phase 3:**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - broadcastSymmetricStateSync(), p2pMetrics, _checkP2PHealth()

**Modified in Phase 4:**
- `interactive_gym/server/static/js/webrtc_manager.js` - TURN config, ConnectionQualityMonitor, getConnectionType(), ICE restart (759 lines now)
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - _logConnectionType(), p2pMetrics.connectionType, episode summary update, turnConfig storage
- `interactive_gym/configurations/remote_config.py` - Added turn_username, turn_credential, force_turn_relay, webrtc() method
- `interactive_gym/server/pyodide_game_coordinator.py` - TURN config in PyodideGameState and pyodide_game_ready event

**Modified in Phase 5:**
- `interactive_gym/server/pyodide_game_coordinator.py` - Removed host_player_id, renamed event to pyodide_player_assigned
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Removed isHost, renamed handler to pyodide_player_assigned

### Decisions

| Plan | Decision | Rationale |
|------|----------|-----------|
| 01-01 | Native WebRTC API (no wrapper libraries) | Full control, no external dependencies, simple-peer unmaintained |
| 01-01 | Deterministic initiator: lower player ID creates offer | Prevents race conditions in role assignment |
| 01-01 | DataChannel unreliable/unordered | GGPO handles packet loss via prediction and rollback |
| 01-02 | WebRTC persists across episodes | Fixed bug where clearGGPOState() closed P2P on episode reset |
| 02-01 | Big-endian (network byte order) for binary protocol | Network byte order convention for compatibility |
| 02-01 | 9-byte header + 5 bytes/input format | Compact binary format, supports 1-5 inputs for redundancy |
| 02-01 | Float64 for RTT timestamps | Preserves precision from performance.now() |
| 02-02 | RTTTracker uses 10-sample sliding window | Stable average RTT without excessive memory |
| 02-02 | Ping interval 500ms | Balance measurement accuracy vs overhead |
| 02-02 | Connection health thresholds: 100ms/200ms | Warning/critical latency for UI feedback |
| 02-03 | Redundancy count 3 (current + 2 previous) | Handles up to 2 consecutive packet losses |
| 02-03 | Buffer congestion threshold 16KB | Prevents DataChannel overflow |
| 02-03 | Parallel SocketIO/P2P sending | Phase 3 will add P2P-first routing |
| 03-01 | Symmetric state sync (both peers broadcast) | Removed host-only restriction for mutual verification |
| 03-01 | Fallback at 300ms latency or critical status | Explicit threshold for degraded P2P detection |
| 04-01 | Open Relay Project TURN provider | Free 20GB/month tier sufficient for research |
| 04-01 | Quality thresholds: 150ms/300ms | Higher than Phase 2 to account for TURN overhead |
| 04-01 | Max 3 ICE restart attempts | Balance recovery vs giving up on broken connections |
| 04-01 | 5 second disconnect timeout | Grace period for transient issues |
| 04-02 | TURN config conditional in socket event | Only include when credentials provided |
| 04-02 | webrtc() follows fluent chaining pattern | Consistency with existing config methods |
| 05-01 | pyodide_player_assigned as single event name | Descriptive name reflecting symmetric peer assignment |

### Pending Todos

(None)

### Blockers/Concerns

**Research pitfalls addressed:**
- Pitfall #4: DataChannel reliability mode - using unreliable/unordered (ordered: false, maxRetransmits: 0)
- Pitfall #11: TURN latency detection - Connection type detection via getStats() implemented in Phase 4

**Research pitfalls remaining:**
- Pitfall #1: Determinism validation - Deferred to Phase 5 (05-03-PLAN.md)

## Session Continuity

Last session: 2026-01-17
Stopped at: Completed 05-01-PLAN.md (host concept removal)
Resume with: Continue with 05-02-PLAN.md
