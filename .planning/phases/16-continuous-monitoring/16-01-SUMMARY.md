---
phase: 16
plan: 01
subsystem: participant-monitoring
tags: [javascript, python, continuous-monitoring, ping, tab-visibility, exclusion]
dependency-graph:
  requires:
    - 15 # Entry screening rules
  provides:
    - continuous_monitoring() Python configuration method
    - ContinuousMonitor JavaScript module
    - Mid-game exclusion handling
    - Warning/exclusion UI overlays
  affects:
    - 17 # Partner notification (mid_game_exclusion event)
    - 18 # Session data export (exclusion events)
tech-stack:
  added:
    - Page Visibility API (visibilitychange event)
  patterns:
    - Rolling window ping tracking
    - Sustained violation detection
    - Frame-throttled monitoring checks
key-files:
  created:
    - interactive_gym/server/static/js/continuous_monitor.js
  modified:
    - interactive_gym/scenes/gym_scene.py
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js
    - interactive_gym/server/static/js/index.js
decisions:
  - id: MONITOR-01
    choice: Frame-throttled checking (every 30 frames ~1s)
    reason: Reduces overhead while maintaining responsive detection
  - id: MONITOR-02
    choice: Rolling window with N-of-M consecutive violations
    reason: Avoids false positives from transient ping spikes
  - id: MONITOR-03
    choice: Page Visibility API (not polling)
    reason: Immediate tab switch detection without performance overhead
  - id: MONITOR-04
    choice: Warning before exclusion with configurable thresholds
    reason: Gives participants chance to correct before game termination
metrics:
  duration: ~15 minutes
  completed: 2026-01-21
---

# Phase 16 Plan 01: Continuous Monitoring Summary

Continuous monitoring during gameplay with ping and tab visibility tracking, warning and exclusion for sustained violations.

## What Was Built

### 1. GymScene Configuration (gym_scene.py)
Added `continuous_monitoring()` method with fluent builder pattern:
- `max_ping`: Maximum allowed latency during gameplay (ms)
- `ping_violation_window`: Rolling window size for tracking (default: 5)
- `ping_required_violations`: Consecutive violations needed (default: 3)
- `tab_warning_ms`: Tab hidden warning threshold (default: 3000ms)
- `tab_exclude_ms`: Tab hidden exclusion threshold (default: 10000ms)
- `exclusion_messages`: Customizable warning/exclusion messages

New attributes automatically serialize via `get_complete_scene_metadata()`.

### 2. ContinuousMonitor JavaScript Module (continuous_monitor.js)
New ES module with:
- **Rolling Window Ping Tracking**: Records last N measurements, avoids false positives
- **Sustained Violation Detection**: Requires M consecutive measurements over threshold
- **Tab Visibility Monitoring**: Uses Page Visibility API `visibilitychange` event for immediate detection
- **Warning/Exclusion Thresholds**: Configurable warning and exclusion points
- **Pause/Resume**: For episode transitions
- **Reset**: For new episodes

### 3. Game Loop Integration (pyodide_multiplayer_game.js)
- Import and instantiate ContinuousMonitor from scene metadata
- Expose `window.currentPing` from Socket.IO pong handler
- Record ping every frame, check every 30 frames (~1s at 30fps)
- `_handleMidGameExclusion()`: Stops game, shows overlay, notifies server
- `_showMidGameExclusionUI()`: Full-screen exclusion message
- `_showMonitorWarning()`: Top banner warning (auto-hides after 5s)
- Pause monitoring in `_broadcastEpisodeEnd()`
- Resume monitoring in `_checkEpisodeStartSync()`

### 4. Server Communication
Emits `mid_game_exclusion` event with:
- `game_id`, `player_id`, `reason`, `frame_number`, `timestamp`

This enables Phase 17 partner notification and Phase 18 data export.

## Key Technical Decisions

| ID | Decision | Rationale |
|----|----------|-----------|
| MONITOR-01 | Check every 30 frames | Balances responsiveness with performance |
| MONITOR-02 | 3-of-5 consecutive violations | Filters transient spikes, catches sustained issues |
| MONITOR-03 | visibilitychange event | Native API, no polling overhead, immediate detection |
| MONITOR-04 | Warning before exclusion | Participant can correct (close tabs, return to window) |

## Usage Example

```python
scene = GymScene()
scene.continuous_monitoring(
    max_ping=200,                    # Exclude if ping > 200ms sustained
    ping_required_violations=3,       # Need 3 consecutive violations
    tab_warning_ms=3000,             # Warn after 3s tab hidden
    tab_exclude_ms=10000,            # Exclude after 10s tab hidden
    exclusion_messages={
        "ping_exclude": "Your connection became too slow for this study.",
        "tab_exclude": "You left the experiment window for too long."
    }
)
```

## Files Changed

| File | Change |
|------|--------|
| `interactive_gym/scenes/gym_scene.py` | +94 lines: continuous_monitoring() method and attributes |
| `interactive_gym/server/static/js/continuous_monitor.js` | +277 lines: New ContinuousMonitor class |
| `interactive_gym/server/static/js/pyodide_multiplayer_game.js` | +169 lines: Integration and UI |
| `interactive_gym/server/static/js/index.js` | +3 lines: window.currentPing exposure |

## Commits

1. `7b78d0a` - feat(16-01): add continuous_monitoring() configuration to GymScene
2. `7c4cf0c` - feat(16-01): create ContinuousMonitor JavaScript module
3. `f9fd5fa` - feat(16-01): integrate ContinuousMonitor with game loop

## Deviations from Plan

None - plan executed exactly as written.

## Success Criteria Verification

- [x] **MONITOR-01**: `continuousMonitor.recordPing()` called in step() with each ping update
- [x] **MONITOR-02**: `_checkPing()` requires 3 consecutive violations from 5-measurement window
- [x] **MONITOR-03**: `visibilitychange` event listener detects tab hidden/visible immediately
- [x] **MONITOR-04**: Warning at 3s, exclusion at 10s (configurable), messages customizable

## Next Phase Readiness

Phase 17 (Partner Notification) can now:
1. Listen for `mid_game_exclusion` socket event
2. Notify the excluded participant's partner
3. Handle partner's game termination gracefully

Phase 18 (Session Export) can now:
- Include exclusion events in session data
- Track reason and timing of mid-game exclusions
