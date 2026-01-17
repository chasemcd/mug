# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.
**Current focus:** Phase 2 - P2P Transport Layer

## Current Position

Phase: 2 of 5 (P2P Transport Layer)
Plan: 1 of 2 complete
Status: In progress
Last activity: 2026-01-17 - Completed 02-01-PLAN.md

Progress: [███-------] 30%

## Phase Overview

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 1 | WebRTC Foundation | WEBRTC-01, WEBRTC-02 | Complete |
| 2 | P2P Transport Layer | GGPO-02, GGPO-03 | In progress |
| 3 | GGPO P2P Integration | GGPO-01, NPLAY-01 | Not started |
| 4 | TURN and Resilience | WEBRTC-03, WEBRTC-04 | Not started |
| 5 | Validation and Cleanup | CLEAN-01 | Not started |

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: ~7 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1 | 2 | ~20 min | ~10 min |
| 2 | 1 | ~1 min | ~1 min |

## Accumulated Context

### Key Files

**Created in Phase 1:**
- `interactive_gym/server/static/js/webrtc_manager.js` - WebRTCManager class (387 lines)

**Modified in Phase 1:**
- `interactive_gym/server/pyodide_game_coordinator.py` - Added `handle_webrtc_signal` method (lines 497-568)
- `interactive_gym/server/app.py` - Registered `webrtc_signal` SocketIO event (line 838)
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Integrated WebRTCManager, P2P test messages

**Modified in Phase 2:**
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Added P2P binary message protocol functions

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

### Pending Todos

(None)

### Blockers/Concerns

**Research pitfalls addressed:**
- Pitfall #4: DataChannel reliability mode - using unreliable/unordered (ordered: false, maxRetransmits: 0)

**Research pitfalls remaining:**
- Pitfall #11: TURN latency detection - Deferred to Phase 4
- Pitfall #1: Determinism validation - Deferred to Phase 3

## Session Continuity

Last session: 2026-01-17
Stopped at: Completed 02-01-PLAN.md
Resume with: Execute 02-02-PLAN.md
