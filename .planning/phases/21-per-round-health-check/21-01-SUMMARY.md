---
phase: 21-per-round-health-check
plan: 01
subsystem: p2p-networking
tags: [webrtc, health-check, datachannel, round-start]

dependency-graph:
  requires:
    - 20-mid-game-reconnection
  provides:
    - per-round-connection-verification
    - health-check-gating
  affects:
    - 22-connection-health-metrics

tech-stack:
  added: []
  patterns:
    - pre-round-health-gating-pattern
    - polling-with-timeout-pattern

key-files:
  created: []
  modified:
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js

decisions:
  - id: ROUND-01
    choice: Fast path returns immediately when connection usable
    rationale: Avoid unnecessary delay when connection is healthy
  - id: ROUND-02
    choice: 10-second health check timeout before round start
    rationale: Balance between waiting for recovery and not blocking indefinitely

metrics:
  duration: 3m
  completed: 2026-01-22
---

# Phase 21 Plan 01: Per-Round DataChannel Health Check Summary

**Per-round health verification with _waitForHealthyConnection() helper that gates round start on P2P connection health, integrating with Phase 20 reconnection state machine.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-01-22
- **Completed:** 2026-01-22
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Added `_waitForHealthyConnection(timeoutMs)` async helper method for connection health verification
- Wired health check into reset() flow before P2P episode synchronization
- Integration with Phase 20 reconnection state machine (paused/reconnecting/terminated states)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add _waitForHealthyConnection helper method** - `f32c47f` (feat)
2. **Task 2: Wire health check into reset() flow** - `c04263b` (feat)

## Files Created/Modified

- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - Added `_waitForHealthyConnection()` method (~70 lines) and health check gating in reset() (~12 lines)

## Implementation Details

### _waitForHealthyConnection Method (lines 4712-4772)

The helper method provides per-round health verification:

**Fast path (ROUND-01):**
- Returns immediately if `webrtcManager.isConnectionUsable()` returns true
- Logs debug message for tracing

**State-aware behavior:**
- `terminated` state: Throws error immediately (game should end)
- `connected` but not usable: Logs warning (edge case - ICE transitioning), proceeds to poll
- `paused`/`reconnecting`: Waits for connection recovery via polling

**Polling mechanism:**
- 100ms poll interval
- Configurable timeout (default 10 seconds)
- Resolves when `isConnectionUsable()` returns true
- Rejects on timeout or termination during wait

**Logging:**
- `p2pLog.debug`: Fast path success
- `p2pLog.info`: Waiting for recovery, recovery successful
- `p2pLog.warn`: Edge cases, timeout

### reset() Integration (lines 1526-1537)

Health check runs BEFORE existing P2P episode sync:

```javascript
// P2P per-round health check (Phase 21 - ROUND-01, ROUND-02)
if (!this.serverAuthoritative && this.webrtcManager) {
    try {
        await this._waitForHealthyConnection(10000);
    } catch (e) {
        p2pLog.error(`Per-round health check failed: ${e.message}`);
        return [obs, infos, render_state];  // Early return
    }
}
```

**Key design choices:**
- Uses `this.webrtcManager` existence check (not `.isReady()`) for broader coverage
- Early return on failure lets reconnection handler or game flow handle termination
- Preserves existing episode sync logic unchanged

## Decisions Made

1. **ROUND-01: Fast path optimization** - If connection is already usable, return immediately without polling overhead

2. **ROUND-02: 10-second timeout** - Matches existing timeout patterns (validation, episode sync) while allowing sufficient recovery time

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 22 (Connection Health Metrics) can proceed. This phase provides:
- `_waitForHealthyConnection()` method that Phase 22 can extend for metric collection
- Health check logging that can be incorporated into export data
- Integration point in reset() for additional health telemetry

---
*Phase: 21-per-round-health-check*
*Completed: 2026-01-22*
