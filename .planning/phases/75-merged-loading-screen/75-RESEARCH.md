# Phase 75: Merged Loading Screen - Research

**Researched:** 2026-02-06
**Domain:** Client-side loading UX, Pyodide preload lifecycle, experiment configuration
**Confidence:** HIGH

## Summary

Phase 75 merges two currently separate loading indicators (the `#screeningLoader` for entry screening and the `#pyodideLoader` for Pyodide preloading) into a single unified loading screen. The current codebase already runs both processes concurrently: when `experiment_config` arrives, `preloadPyodide()` fires without await while entry screening runs. However, participants currently see two separate visual indicators and the advance button gating logic only checks `pyodidePreloadStatus !== 'loading'` without a timeout or proper error handling.

The key challenge is NOT the concurrency (that already works) but the UI unification, timeout mechanism, and error handling. The current `showPyodideProgress`/`hidePyodideProgress` functions manipulate a standalone `#pyodideLoader` div, while entry screening uses `#screeningLoader`. These must be merged into a single loading screen that shows combined status and gates progression on BOTH readiness conditions.

**Primary recommendation:** Replace the two separate loaders (`#screeningLoader` and `#pyodideLoader`) with a single `#loadingScreen` element. Refactor the `experiment_config` handler to track both readiness signals with a shared state object, implement a configurable timeout with `setTimeout`, and show an error page (reusing the existing `showExclusionMessage` pattern) on timeout/failure.

## Standard Stack

No new libraries needed. This phase is entirely within the existing stack:

### Core (Already In Use)
| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| jQuery | 3.7.1 | DOM manipulation | Already loaded via CDN in index.html |
| Socket.IO | 4.7.2 | Client-server communication | Already loaded, used for experiment_config event |
| Pyodide | 0.26.2 | Python runtime in browser | Already loaded via CDN, preload mechanism exists |

### Supporting (Already In Use)
| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| Flask | N/A | Server-side rendering of index.html | Jinja templates |
| Flask-SocketIO | N/A | Server-side socket events | experiment_config emission |

**No new installations required.**

## Architecture Patterns

### Current Flow (What Exists)

```
1. Client loads index.html (shows #sceneHeader, #sceneSubHeader from initial StartScene)
2. Socket connects -> register_subject -> experiment_config emitted
3. experiment_config handler:
   a. preloadPyodide() fire-and-forget (shows #pyodideLoader independently)
   b. runEntryScreening() awaited (shows #screeningLoader)
   c. On screening pass: process pending scene or request current scene
4. Scene activates -> activateScene() routes to startStaticScene/startGymScene
5. startStaticScene: gates #advanceButton on pyodidePreloadStatus !== 'loading'
6. startGymScene: enableStartRefreshInterval polls pyodideReadyIfUsing()
```

### Problems With Current Flow
1. **Two separate loading UIs**: `#screeningLoader` and `#pyodideLoader` are independent divs
2. **No Pyodide timeout**: preloadPyodide catches errors but has no timeout; can hang forever
3. **No client-side error page for Pyodide failure**: On preload error, status shows "Loading failed - will retry when game starts" but the scene still advances (status becomes 'error', not 'loading', so gate passes)
4. **Advancement gating is scattered**: Static scenes gate on advance button disable, gym scenes gate via `enableStartRefreshInterval` polling. Neither properly handles the 'error' status

### Target Flow (What Phase 75 Builds)

```
1. Client loads index.html
2. Socket connects -> register_subject -> experiment_config emitted
3. experiment_config handler:
   a. Show unified #loadingScreen (replaces both #screeningLoader and #pyodideLoader)
   b. preloadPyodide() fire-and-forget (updates shared loading state)
   c. Start pyodide timeout timer (configurable, default 60s)
   d. runEntryScreening() awaited (updates shared loading state)
   e. Check: BOTH screening passed AND pyodide ready?
      - YES: hide loading screen, proceed to scene
      - SCREENING FAILED: show exclusion message (existing behavior)
      - PYODIDE STILL LOADING: wait (loading screen stays visible)
      - PYODIDE ERROR/TIMEOUT: show error page
4. On pyodide ready (if screening already done): hide loading screen, proceed
5. On pyodide timeout/error: show clear error page via showExclusionMessage
```

### Pattern: Dual-Signal Loading Gate

**What:** A shared state object that tracks two independent async processes and gates progression on both completing successfully.

**When to use:** When two parallel async operations must BOTH succeed before the UI can advance.

**Implementation sketch:**
```javascript
// Shared loading state
const loadingGate = {
    screeningComplete: false,
    screeningPassed: null,     // true/false/null
    screeningMessage: null,
    pyodideComplete: false,
    pyodideSuccess: null,      // true/false/null
    timeoutId: null,
};

function checkLoadingGate() {
    // Both must be complete
    if (!loadingGate.screeningComplete || !loadingGate.pyodideComplete) {
        updateLoadingStatus(); // Update UI with current status text
        return;
    }

    // Screening failed -> show exclusion (existing behavior)
    if (!loadingGate.screeningPassed) {
        showExclusionMessage(loadingGate.screeningMessage);
        return;
    }

    // Pyodide failed -> show error page (LOAD-04)
    if (!loadingGate.pyodideSuccess) {
        showExclusionMessage('Failed to load the Python runtime. Please refresh the page or try a different browser.');
        return;
    }

    // Both passed -> proceed
    clearTimeout(loadingGate.timeoutId);
    hideLoadingScreen();
    proceedToScene();
}
```

### Pattern: Configurable Timeout via Experiment Config

**What:** Server sends `pyodide_load_timeout_s` in the `pyodide_config` dict, client uses it for `setTimeout`.

**Implementation path:**
1. Add `pyodide_load_timeout_s: int = 60` to `ExperimentConfig.__init__`
2. Include it in `get_pyodide_config()` return dict
3. Client reads it from `data.pyodide_config.pyodide_load_timeout_s`
4. Client starts `setTimeout(handlePyodideTimeout, timeout * 1000)`

### Anti-Patterns to Avoid
- **Polling-only gate (no event-driven):** The current `setInterval` polling in `enableStartRefreshInterval` is fragile. The new loading gate should be event-driven (called when each signal completes) with a final poll as safety net only.
- **Separate UI elements for parallel operations:** Having `#screeningLoader` and `#pyodideLoader` as siblings means they can both be visible simultaneously, confusing participants.
- **Silent failure on Pyodide error:** Current code sets status to 'error' and shows a message in the Pyodide loader, but still lets the user advance. Phase 75 must BLOCK advancement and show a proper error page.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Error/exclusion display | New error page component | Existing `showExclusionMessage()` function | Already hides all interactive elements and shows formatted error text. Handles all the UI state cleanup. |
| Loading spinner CSS | New spinner animation | Existing `.screening-spinner` CSS class | Already defined with proper sizing, colors, and animation. |
| Config propagation to client | New socket event | Existing `experiment_config` socket event | Already carries `pyodide_config` dict, just add `pyodide_load_timeout_s` field. |
| Pyodide preload | New loading mechanism | Existing `preloadPyodide()` function | Already handles loadPyodide + micropip + packages + grace period signaling. Just needs timeout wrapper. |

## Common Pitfalls

### Pitfall 1: Race Condition Between Screening Completion and Pyodide Completion
**What goes wrong:** Entry screening completes and calls `processPendingScene()` before Pyodide is ready. The scene activates and the participant sees the scene content but cannot interact because Pyodide is still loading.
**Why it happens:** Currently, screening and Pyodide preload are truly independent. Screening can complete in <1s while Pyodide takes 5-15s.
**How to avoid:** The loading gate MUST check both signals. Do NOT call `processPendingScene()` until both are complete. The current code already queues pending scenes; the gate just needs to delay the dispatch.
**Warning signs:** Scene content (headers, body text) appearing while the loading spinner is still visible.

### Pitfall 2: Timeout Not Cleared on Success
**What goes wrong:** Pyodide loads successfully but the timeout timer fires later, showing an error page mid-experiment.
**Why it happens:** `clearTimeout` not called in the success path.
**How to avoid:** Always `clearTimeout(loadingGate.timeoutId)` in both the success AND error paths of `checkLoadingGate()`.
**Warning signs:** Intermittent "failed to load" errors appearing after the game has already started.

### Pitfall 3: Advance Button Still Gated After Loading Screen Removed
**What goes wrong:** The loading screen is removed but the advance button is still disabled because the old `pyodidePreloadStatus === 'loading'` check in `startStaticScene()` fires.
**Why it happens:** Two separate gating mechanisms: the new loading screen gate AND the old per-scene advance button gate. They can conflict.
**How to avoid:** The per-scene advance button gating (lines 1305-1313 in index.js) should be simplified. Once the loading screen has passed, pyodide is guaranteed to be ready (or in error state). The scene-level gate should either be removed or kept as a safety net that is redundant with the loading screen.
**Warning signs:** Advance button staying disabled on static scenes even though loading completed.

### Pitfall 4: Non-Pyodide Experiments Broken by Loading Gate
**What goes wrong:** Experiments that don't use Pyodide get stuck on the loading screen because the Pyodide signal never fires.
**Why it happens:** `preloadPyodide()` already handles this -- when `needs_pyodide` is false, it immediately sets status to 'ready'. But if the loading gate expects an explicit signal, it might miss this.
**How to avoid:** When `data.pyodide_config.needs_pyodide === false`, immediately mark `pyodideComplete: true, pyodideSuccess: true` in the loading gate. Don't start a timeout.
**Warning signs:** Non-Pyodide experiments hanging on the loading screen.

### Pitfall 5: Multiple experiment_config Events on Reconnect
**What goes wrong:** If a participant reconnects, `register_subject` fires again and `experiment_config` is re-emitted. This could restart the loading flow and show the loading screen again mid-experiment.
**Why it happens:** The `experiment_config` handler in index.js fires on every emission.
**How to avoid:** Guard the handler with a flag: `if (loadingGateComplete) return;` to prevent re-running the loading flow after it has already succeeded.
**Warning signs:** Loading screen appearing after a page refresh when the participant was already past the loading phase.

### Pitfall 6: Server-Side Grace Period Mismatch
**What goes wrong:** Client timeout (60s default) fires before server-side `LOADING_TIMEOUT_S` (also 60s), or vice versa. The client shows an error but the server still considers the client in grace period (or the opposite).
**Why it happens:** Two independent timeouts that are not coordinated.
**How to avoid:** The client timeout should be shorter than or equal to the server-side `LOADING_TIMEOUT_S`. The configurable timeout should apply to both sides, or the server should always be >= client. For Phase 75, the client timeout from `pyodide_load_timeout_s` config should also update the server's `LOADING_TIMEOUT_S`.
**Warning signs:** Server logging grace period expiration while client has already shown error, or client succeeding but server already killed the session.

## Code Examples

### Current: How experiment_config Handler Works (index.js lines 585-652)
```javascript
socket.on('experiment_config', async function(data) {
    // Fire and forget Pyodide preload
    if (data.pyodide_config) {
        preloadPyodide(data.pyodide_config);  // No await
    }

    if (data.entry_screening) {
        // Show screening loader, run screening, hide loader
        // If passed, process pending scene or request current scene
    } else {
        // No screening, mark complete, process pending scene
    }
});
```

### Current: preloadPyodide (index.js lines 216-262)
```javascript
async function preloadPyodide(pyodideConfig) {
    if (!pyodideConfig || !pyodideConfig.needs_pyodide) {
        window.pyodidePreloadStatus = 'ready';
        return;
    }
    window.pyodidePreloadStatus = 'loading';
    showPyodideProgress('Loading Python runtime...');

    socket.emit('pyodide_loading_start', {});
    await new Promise(resolve => setTimeout(resolve, 50));  // Yield for emit

    try {
        const pyodide = await loadPyodide();
        // ... install micropip and packages ...
        window.pyodidePreloadStatus = 'ready';
        hidePyodideProgress();
        socket.emit('pyodide_loading_complete', {});
    } catch (error) {
        window.pyodidePreloadStatus = 'error';
        showPyodideProgress('Loading failed - will retry when game starts');
        socket.emit('pyodide_loading_complete', { error: true });
    }
}
```

### Current: HTML Loading Elements (index.html lines 287-295)
```html
<!-- Entry screening loading indicator -->
<div id="screeningLoader" style="display: none;">
    <div class="screening-spinner"></div>
    <div id="screeningStatus">Loading...</div>
</div>
<!-- Pyodide preloading indicator (Phase 67) -->
<div id="pyodideLoader" style="display: none;">
    <div class="screening-spinner"></div>
    <div id="pyodideStatus">Loading Python runtime...</div>
</div>
```

### Current: Advance Button Pyodide Gate (index.js lines 1305-1313, 1493-1497)
```javascript
// In startStaticScene():
if (window.pyodidePreloadStatus === 'loading') {
    $("#advanceButton").attr("disabled", true);
    const pyodideGateInterval = setInterval(() => {
        if (window.pyodidePreloadStatus !== 'loading') {
            $("#advanceButton").attr("disabled", false);
            clearInterval(pyodideGateInterval);
        }
    }, 500);
}

// In advanceButton click handler:
if (window.pyodidePreloadStatus === 'loading') {
    console.log('[AdvanceScene] Blocked - Pyodide still loading');
    return;
}
```

### Current: ExperimentConfig.get_pyodide_config (experiment_config.py lines 223-250)
```python
def get_pyodide_config(self) -> dict:
    # Scans stager scenes for Pyodide needs
    return {
        "needs_pyodide": needs_pyodide,
        "packages_to_install": list(all_packages),
    }
```

### Target: Unified Loading Screen HTML
```html
<!-- Replace both #screeningLoader and #pyodideLoader with: -->
<div id="loadingScreen" style="display: none;">
    <div class="screening-spinner"></div>
    <div id="loadingStatus">Checking compatibility...</div>
</div>
```

### Target: Loading Gate Object
```javascript
const loadingGate = {
    screeningComplete: false,
    screeningPassed: null,
    screeningMessage: null,
    pyodideComplete: false,
    pyodideSuccess: null,
    timeoutId: null,
    gateResolved: false,  // Prevents re-entry on reconnect
};
```

### Target: ExperimentConfig with Timeout
```python
# In ExperimentConfig.__init__:
self.pyodide_load_timeout_s: int = 60

# In get_pyodide_config():
return {
    "needs_pyodide": needs_pyodide,
    "packages_to_install": list(all_packages),
    "pyodide_load_timeout_s": self.pyodide_load_timeout_s,
}
```

### Target: RemoteConfig with Timeout
```python
# In RemoteConfig.__init__ (pyodide section):
self.pyodide_load_timeout_s: int = 60

# In get_pyodide_config():
return {
    "needs_pyodide": self.run_through_pyodide,
    "packages_to_install": self.packages_to_install,
    "pyodide_load_timeout_s": self.pyodide_load_timeout_s,
}
```

## State of the Art

| Old Approach (Current) | New Approach (Phase 75) | Impact |
|------------------------|------------------------|--------|
| Two separate loaders (`#screeningLoader`, `#pyodideLoader`) | Single `#loadingScreen` | LOAD-01: One loading screen |
| Pyodide gate only on advance button in per-scene code | Loading gate blocks before ANY scene renders | LOAD-02: Gates on both signals |
| No timeout on Pyodide preload | Configurable timeout via `pyodide_load_timeout_s` | LOAD-03: Configurable timeout |
| Error status allows advancement, shows inline message | Error/timeout shows `showExclusionMessage()` error page | LOAD-04: Clear error, no hang |

## Files to Modify

| File | What Changes | Why |
|------|-------------|-----|
| `interactive_gym/server/static/templates/index.html` | Replace `#screeningLoader` + `#pyodideLoader` with single `#loadingScreen` element | LOAD-01 |
| `interactive_gym/server/static/js/index.js` | Refactor `experiment_config` handler: add loading gate, timeout, error handling. Simplify per-scene Pyodide gating. | LOAD-01, LOAD-02, LOAD-04 |
| `interactive_gym/configurations/experiment_config.py` | Add `pyodide_load_timeout_s` field and include in `get_pyodide_config()` | LOAD-03 |
| `interactive_gym/configurations/remote_config.py` | Add `pyodide_load_timeout_s` field and include in `get_pyodide_config()` | LOAD-03 |
| `interactive_gym/server/app.py` | Optionally: use `pyodide_load_timeout_s` from config for `LOADING_TIMEOUT_S` | LOAD-03 (server-side consistency) |

## Open Questions

1. **Should per-scene Pyodide gating be removed entirely?**
   - What we know: Once the loading gate passes, Pyodide is guaranteed ready. The per-scene gating in `startStaticScene()` and `enableStartRefreshInterval()` becomes redundant.
   - What's unclear: Whether removing it could break edge cases (e.g., session restoration where loading screen was already bypassed).
   - Recommendation: Keep the per-scene gating as a safety net (it costs nothing) but ensure it does not conflict with the loading screen. The loading gate should mark `window.pyodidePreloadStatus = 'ready'` before proceeding, which makes the safety net a no-op in the normal path.

2. **Should the configurable timeout also propagate to the server-side `LOADING_TIMEOUT_S`?**
   - What we know: Currently `LOADING_TIMEOUT_S = 60` is hardcoded in app.py. The client timeout will come from config.
   - What's unclear: Whether a mismatch causes issues. The grace period is about preventing the server from treating a loading client as disconnected.
   - Recommendation: Have the server read `pyodide_load_timeout_s` from config and set `LOADING_TIMEOUT_S` accordingly. This ensures client and server timeouts are aligned.

3. **Does the `preloadPyodide()` function need to call `checkLoadingGate()` on completion?**
   - What we know: Currently `preloadPyodide()` calls `hidePyodideProgress()` on success and sets `window.pyodidePreloadStatus`.
   - Recommendation: Yes. `preloadPyodide()` should update `loadingGate.pyodideComplete` and `loadingGate.pyodideSuccess`, then call `checkLoadingGate()`. This makes the gate event-driven rather than polling.

## Sources

### Primary (HIGH confidence)
- Direct code inspection of `interactive_gym/server/static/js/index.js` (1720 lines) - full loading/screening/scene flow
- Direct code inspection of `interactive_gym/server/static/templates/index.html` - HTML structure and CSS
- Direct code inspection of `interactive_gym/configurations/experiment_config.py` - `get_pyodide_config()`, `get_entry_screening_config()`
- Direct code inspection of `interactive_gym/configurations/remote_config.py` - `get_pyodide_config()`, pyodide config fields
- Direct code inspection of `interactive_gym/server/app.py` - experiment_config emission, LOADING_CLIENTS, grace period
- Direct code inspection of `interactive_gym/server/static/js/pyodide_remote_game.js` - preload reuse in initialize()
- Direct code inspection of `interactive_gym/scenes/stager.py` - start/resume/advance scene flow
- Direct code inspection of `interactive_gym/scenes/scene.py` - activate() emits activate_scene

### Secondary (MEDIUM confidence)
- Prior phase decisions from v1.16 (Phases 67-69) - preload approach, grace period design

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new libraries, all code inspected directly
- Architecture: HIGH - current flow traced end-to-end through source code
- Pitfalls: HIGH - identified from actual code structure and race conditions visible in source
- File modifications: HIGH - all files inspected, exact locations identified

**Research date:** 2026-02-06
**Valid until:** 2026-03-06 (stable codebase, no external dependency changes expected)
