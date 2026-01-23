---
phase: 28
plan: 01
subsystem: diagnostics
tags: [latency, instrumentation, debugging, pyodide, phaser]
dependency-graph:
  requires: []
  provides: ["pipeline-timestamps", "latency-logging"]
  affects: [29-diagnosis, 30-optimization]
tech-stack:
  added: []
  patterns: ["timestamp-injection", "pipeline-metrics"]
key-files:
  created: []
  modified:
    - interactive_gym/server/static/js/ui_utils.js
    - interactive_gym/server/static/js/phaser_gym_graphics.js
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js
    - interactive_gym/server/static/js/pyodide_remote_game.js
decisions:
  - id: DIAG-FORMAT
    choice: "Console log format: [LATENCY] frame=N total=Xms | queue=Yms step=Zms render=Wms"
    rationale: "Easy to grep, includes frame reference and full breakdown"
  - id: LOG-THROTTLE
    choice: "Log every frame for first 50, then every 10th frame"
    rationale: "Captures initial behavior while reducing noise during gameplay"
  - id: TIMESTAMP-PROPAGATION
    choice: "Pass timestamps via setInputTimestamps() method rather than step() parameter"
    rationale: "Maintains backward compatibility with existing step() signature"
metrics:
  duration: 5 minutes
  completed: 2026-01-23
---

# Phase 28 Plan 01: Pipeline Instrumentation Summary

Added timestamps at each stage of the input-to-render pipeline to diagnose reported 1-2 second input lag.

## One-liner

Performance.now() timestamps capture keypress, queue exit, step call/return, and render begin/complete for per-input latency breakdown logging.

## What Was Built

### DIAG Requirements Met

| Requirement | Description | Implementation |
|-------------|-------------|----------------|
| DIAG-01 | Timestamp at keypress event | `ui_utils.js` keydown handler captures `performance.now()` first |
| DIAG-02 | Input queue entry/exit timestamps | `phaser_gym_graphics.js` tracks timestamps in buffer and returns on shift |
| DIAG-03 | env.step() call timestamp | Both game files capture before `stepWithActions()` |
| DIAG-04 | env.step() return timestamp | Both game files capture after `stepWithActions()` |
| DIAG-05 | Render begin timestamp | `processRendering()` captures at start |
| DIAG-06 | Render complete timestamp | `processRendering()` captures after `drawState()` |
| DIAG-07 | Per-input latency breakdown logged | `logPipelineLatency()` computes and logs breakdown |

### Console Output Format

```
[LATENCY] frame=N total=Xms | queue=Yms step=Zms render=Wms
```

- **queue**: Time from keypress to buffer exit (should be ~0ms for immediate input)
- **step**: Time for Pyodide env.step() execution (typically 10-50ms)
- **render**: Time for Phaser drawState() (typically 1-10ms)
- **total**: End-to-end latency from keypress to render complete

### Edge Cases Handled

- **No input this frame**: Default actions don't generate latency logs
- **Fast-forward frames**: Skip logging during background catch-up
- **Background/foreground transitions**: Skip logging when tab is backgrounded
- **Console toggle**: `window.pipelineMetricsEnabled = false` disables logging

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | c76d4b7 | Add keypress and input queue timestamps |
| 2 | 731c51a | Add env.step() timestamps and latency logging to multiplayer |
| 3 | 46f4a24 | Add pipeline instrumentation to single-player mode |

## Files Modified

- `interactive_gym/server/static/js/ui_utils.js` - Keypress timestamp capture (DIAG-01)
- `interactive_gym/server/static/js/phaser_gym_graphics.js` - Input queue timestamps, render timestamps, timestamp propagation
- `interactive_gym/server/static/js/pyodide_multiplayer_game.js` - pipelineMetrics object, step timestamps, logPipelineLatency()
- `interactive_gym/server/static/js/pyodide_remote_game.js` - Same instrumentation for single-player

## Decisions Made

### DIAG-FORMAT: Console output format
**Decision**: Use `[LATENCY] frame=N total=Xms | queue=Yms step=Zms render=Wms`
**Rationale**: The format is easily greppable, includes frame reference for correlation, and shows full breakdown with clear labels.

### LOG-THROTTLE: Logging frequency
**Decision**: Log every frame for first 50, then every 10th frame
**Rationale**: Captures initial behavior during startup while reducing console noise during extended gameplay.

### TIMESTAMP-PROPAGATION: How to pass timestamps
**Decision**: Use `setInputTimestamps()` method called before `step()` rather than adding parameter to `step()`
**Rationale**: Maintains backward compatibility with existing step() signature and allows independent control of timestamp flow.

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

Phase 29 (Diagnosis) can now:
1. Start any game (single-player or multiplayer)
2. Open browser console
3. Observe `[LATENCY]` logs with breakdown
4. Identify which pipeline stage(s) contribute to the reported 1-2 second lag

Expected findings:
- If **queue** is high: Input buffering issue
- If **step** is high: Pyodide execution bottleneck
- If **render** is high: Phaser rendering issue
- If **total** is much higher than sum: Frame timing/throttling issue

## Testing Notes

To verify instrumentation:
1. Start any game in browser
2. Open developer console
3. Observe `[LATENCY]` logs appearing
4. Press keys during gameplay - verify new entries appear
5. Run `window.pipelineMetricsEnabled = false` - verify logging stops
