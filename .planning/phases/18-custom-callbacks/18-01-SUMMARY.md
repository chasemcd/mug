---
phase: 18-custom-callbacks
plan: 01
subsystem: exclusion-system
tags: [callbacks, python, entry-screening, continuous-monitoring, socket.io]

dependency_graph:
  requires:
    - phase-15-entry-screening
    - phase-16-continuous-monitoring
    - phase-17-multiplayer-exclusion
  provides:
    - custom-entry-callback-execution
    - custom-continuous-callback-execution
    - researcher-defined-exclusion-logic
  affects: []

tech_stack:
  added: []
  patterns:
    - async-callback-pattern
    - server-side-callback-execution
    - fail-open-error-handling

key_files:
  created: []
  modified:
    - interactive_gym/scenes/gym_scene.py
    - interactive_gym/server/app.py
    - interactive_gym/server/static/js/index.js
    - interactive_gym/server/static/js/continuous_monitor.js
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js

decisions:
  - id: CALLBACK-01
    decision: Callbacks execute server-side, not client-side
    rationale: Security and flexibility - researcher Python code runs on trusted server, receives context from untrusted client
  - id: CALLBACK-02
    decision: Entry callback runs AFTER built-in checks pass
    rationale: Researcher callbacks are additions to, not replacements for, built-in screening rules
  - id: CALLBACK-03
    decision: Fail-open on callback errors
    rationale: Better to allow a participant than crash the experiment; errors are logged for researcher review
  - id: CALLBACK-04
    decision: Async continuous callback with non-blocking game loop
    rationale: Callback round-trip to server could be slow; don't block 30fps game loop waiting for response
  - id: CALLBACK-05
    decision: 5-second timeout for entry callback
    rationale: Entry screening should be fast; fail-open after timeout to prevent stuck participants

metrics:
  duration: ~15 minutes
  completed: 2026-01-22
---

# Phase 18 Plan 01: Custom Exclusion Callbacks Summary

Custom exclusion callbacks allowing researchers to define arbitrary Python exclusion logic that executes server-side with full participant context.

## One-liner

Researcher-defined Python callbacks for entry and continuous exclusion with server-side execution and async non-blocking integration.

## What Was Built

### 1. GymScene Configuration (`gym_scene.py`)

Added `exclusion_callbacks()` fluent builder method:

```python
scene.exclusion_callbacks(
    entry_callback=my_entry_fn,
    continuous_callback=my_continuous_fn,
    continuous_callback_interval_frames=60  # Check every 60 frames
)
```

Entry callback signature:
```python
def my_entry_callback(context: dict) -> dict:
    # context: ping, browser_name, browser_version, device_type, os_name, subject_id, scene_id
    return {"exclude": bool, "message": str | None}
```

Continuous callback signature:
```python
def my_continuous_callback(context: dict) -> dict:
    # context: ping, is_tab_hidden, tab_hidden_duration_ms, frame_number, episode_number, subject_id, scene_id
    return {"exclude": bool, "warn": bool, "message": str | None}
```

Metadata flags added (callbacks themselves are not serialized):
- `has_entry_callback: bool`
- `has_continuous_callback: bool`
- `continuous_callback_interval_frames: int`

### 2. Server-Side Handlers (`app.py`)

Added two Socket.IO handlers:

- `execute_entry_callback`: Receives participant context, executes researcher's entry callback, returns exclusion decision
- `execute_continuous_callback`: Receives gameplay context, executes researcher's continuous callback, returns exclusion/warning decision

Both handlers:
- Look up scene from participant's stager
- Add `subject_id` and `scene_id` to context
- Fail-open on errors (allow entry, log error)

### 3. Client-Side Entry Integration (`index.js`)

- Made `runEntryScreening()` async
- Added `executeEntryCallback()` function
- Updated `startGymScene()` to async/await
- Entry callback runs AFTER built-in device/browser checks pass
- 5-second timeout with fail-open behavior

### 4. Client-Side Continuous Integration (`continuous_monitor.js`, `pyodide_multiplayer_game.js`)

ContinuousMonitor additions:
- `hasCallback`, `callbackIntervalFrames`, `callbackPending` state
- `shouldExecuteCallback()` - frame-based trigger
- `setCallbackPending(bool)` - prevent overlapping calls
- `setCallbackResult(result)` - store server response
- `check()` now processes callback results first

MultiplayerPyodideGame additions:
- `continuous_callback_result` socket listener
- `_executeContinuousCallback()` method to send context to server
- Integration in game loop after monitor check

Flow is fully async:
1. Game loop calls `shouldExecuteCallback()` every frame
2. When true, `_executeContinuousCallback()` sends context to server
3. Game loop continues immediately (non-blocking)
4. Server executes callback, emits `continuous_callback_result`
5. Next `check()` processes the stored result

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 28dbc4b | Add exclusion_callbacks() method to GymScene |
| 2 | ca85438 | Add server-side callback execution socket handlers |
| 3 | 3bf06ee | Integrate entry callback in client-side screening |
| 4 | 47eca52 | Integrate continuous callback in game loop |

## Deviations from Plan

None - plan executed exactly as written.

## Success Criteria Verification

- [x] EXT-01: Researcher can define custom exclusion rules via Python callback functions
  - `GymScene.exclusion_callbacks(entry_callback=fn, continuous_callback=fn)` works
  - Callbacks stored on scene instance

- [x] EXT-02: Callbacks receive full participant context
  - Entry: ping, browser_name, browser_version, device_type, os_name, subject_id, scene_id
  - Continuous: ping, is_tab_hidden, tab_hidden_duration_ms, frame_number, episode_number, subject_id, scene_id

- [x] EXT-03: Callbacks return exclusion decision with optional message
  - Entry returns: {"exclude": bool, "message": str|None}
  - Continuous returns: {"exclude": bool, "warn": bool, "message": str|None}
  - Custom messages displayed in exclusion UI

## Usage Example

```python
from interactive_gym.scenes.gym_scene import GymScene

# Track prior participation (example)
completed_subjects = set()

def check_prior_participation(ctx):
    """Exclude participants who already completed the study."""
    if ctx['subject_id'] in completed_subjects:
        return {
            "exclude": True,
            "message": "You have already participated in this study."
        }
    return {"exclude": False}

def check_attention(ctx):
    """Warn on high ping, exclude on sustained tab switching."""
    if ctx['tab_hidden_duration_ms'] > 5000:
        return {
            "exclude": True,
            "message": "Please keep the experiment window in focus."
        }
    if ctx['ping'] > 300:
        return {
            "warn": True,
            "message": "Your connection appears slow. Please close other tabs."
        }
    return {"exclude": False}

scene = (
    GymScene()
    .exclusion_callbacks(
        entry_callback=check_prior_participation,
        continuous_callback=check_attention,
        continuous_callback_interval_frames=30  # ~1 second at 30fps
    )
)
```

## Next Phase Readiness

This completes Phase 18 and the v1.2 Participant Exclusion milestone.

All four phases of v1.2 are now complete:
- Phase 15: Entry Screening Rules
- Phase 16: Continuous Monitoring
- Phase 17: Multiplayer Exclusion
- Phase 18: Custom Exclusion Callbacks

The exclusion system now provides:
1. Built-in device, browser, and ping screening at entry
2. Continuous ping and tab visibility monitoring during gameplay
3. Proper multiplayer handling (partner notification, data export)
4. Researcher-defined custom callbacks for arbitrary exclusion logic
