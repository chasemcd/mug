# Phase 67: Pyodide Pre-load Infrastructure - Research

**Researched:** 2026-02-06
**Domain:** Pyodide initialization, client-side preloading, compatibility check flow
**Confidence:** HIGH

## Summary

This research investigates how to build a Pyodide pre-loading mechanism that runs during the compatibility check / entry screening screen, so that by the time a participant clicks "Start" and enters a game, the heavy `loadPyodide()` WASM compilation (5-15 seconds) is already complete. The goal is to eliminate Socket.IO disconnects that occur when multiple games initialize Pyodide concurrently.

The existing codebase has a clear, well-defined flow: participant connects, `register_subject` fires, `experiment_config` is sent (with entry screening rules), then `activate_scene` sends the first scene (a `StartScene`). Currently, Pyodide initialization only begins when a `GymScene` with `run_through_pyodide: true` activates -- far too late. The pre-loading strategy moves initialization to the `experiment_config` event, which fires before any scene activation and during the compatibility check screen.

The approach requires four changes: (1) the server sends Pyodide config metadata (packages, flag) alongside the `experiment_config` event, (2) the client starts `loadPyodide()` + package installation immediately upon receiving that config, (3) a progress indicator shows the participant what is happening, and (4) the start button / advance button remains gated until Pyodide is ready. This phase does NOT change how `RemoteGame` or `MultiplayerPyodideGame` consume the Pyodide instance -- that is Phase 68.

**Primary recommendation:** Add a `pyodide_config` field to the `experiment_config` socket event that contains `{needs_pyodide: true, packages_to_install: [...]}` derived from scanning the Stager's scenes. On the client, start `loadPyodide()` + `micropip.install()` immediately when this config is received, storing the result on `window.pyodideInstance`. Show an indeterminate progress indicator during loading. Gate scene advancement until loading completes.

## Standard Stack

This phase uses NO new libraries. Everything needed is already in the codebase.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Pyodide | 0.26.2 | Python-in-browser via WASM | Already loaded via CDN in index.html |
| Socket.IO | 4.7.2 | Real-time client-server messaging | Already used for all event flow |
| jQuery | 3.7.1 | DOM manipulation | Already used throughout index.js |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| micropip | (bundled with Pyodide) | Install Python packages in Pyodide | Already used in RemoteGame.initialize() |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Indeterminate spinner | fetch interception for % progress | Adds complexity, Content-Length may not match decompressed size, indeterminate is simpler and honest |
| New socket event for pyodide config | Piggybacking on experiment_config | New event is cleaner separation but experiment_config already exists and is the right timing |

**Installation:** No new packages needed.

## Architecture Patterns

### Recommended Approach

The pre-loading mechanism fits cleanly into the existing `experiment_config` flow:

```
Server                          Client
  |                               |
  |-- experiment_config --------->|  (includes pyodide_config)
  |                               |  START loadPyodide() + micropip
  |                               |  Show progress indicator
  |-- activate_scene (StartScene)->|  Queue if screening in progress
  |                               |  Show scene content
  |                               |  Gate advance/start until pyodide ready
  |                               |  PYODIDE READY
  |                               |  Enable advance/start button
  |                               |
  |<-- join_game / advance_scene -|  User clicks (Pyodide already loaded)
```

### Pattern 1: Server-Side Scene Scanning (INIT-01)
**What:** Server scans all scenes in the Stager to detect any `GymScene` with `run_through_pyodide: true`, and collects the union of all `packages_to_install` across those scenes.
**When to use:** During `register_subject`, before sending `experiment_config`.
**Key insight:** The `GENERIC_STAGER` (and each participant's copy) contains the full list of scenes. We can iterate them at registration time.

```python
# In ExperimentConfig or wherever experiment_config is assembled
def get_pyodide_config(self) -> dict:
    """Scan stager scenes for Pyodide requirements."""
    needs_pyodide = False
    all_packages = set()

    for scene in self.stager.scenes:
        # Handle SceneWrapper by unpacking
        unpacked = scene.unpack() if hasattr(scene, 'unpack') else [scene]
        for s in unpacked:
            if hasattr(s, 'run_through_pyodide') and s.run_through_pyodide:
                needs_pyodide = True
                if hasattr(s, 'packages_to_install') and s.packages_to_install:
                    all_packages.update(s.packages_to_install)

    return {
        "needs_pyodide": needs_pyodide,
        "packages_to_install": list(all_packages),
    }
```

**Important caveats:**
- `Stager.scenes` contains `Scene` and `SceneWrapper` objects. Must recursively unpack.
- The `build_instance()` deepcopy happens per-participant. Scanning should use `GENERIC_STAGER` for efficiency (all participants see the same scene types).
- `RandomizeOrder` and `RepeatScene` wrappers still contain the same scene types -- the Pyodide need is determined by scene CLASS, not scene order.

### Pattern 2: Client-Side Preloading (INIT-02)
**What:** Client receives `pyodide_config` in `experiment_config` and immediately starts `loadPyodide()` + package installation.
**When to use:** In the `experiment_config` socket handler, right alongside entry screening.

```javascript
// In index.js, inside socket.on('experiment_config', ...)
// Global state for pre-loaded Pyodide
window.pyodideInstance = null;
window.pyodidePreloadStatus = 'idle'; // 'idle' | 'loading' | 'ready' | 'error'
window.pyodidePreloadError = null;

async function preloadPyodide(pyodideConfig) {
    if (!pyodideConfig || !pyodideConfig.needs_pyodide) return;

    window.pyodidePreloadStatus = 'loading';
    updatePyodideProgressUI('loading', 'Loading Python runtime...');

    try {
        // Step 1: Load Pyodide core (~15MB WASM download + compilation)
        const pyodide = await loadPyodide();
        updatePyodideProgressUI('loading', 'Installing packages...');

        // Step 2: Load micropip
        await pyodide.loadPackage("micropip");
        const micropip = pyodide.pyimport("micropip");

        // Step 3: Install experiment packages
        if (pyodideConfig.packages_to_install && pyodideConfig.packages_to_install.length > 0) {
            await micropip.install(pyodideConfig.packages_to_install);
        }

        // Store globally for Phase 68 to consume
        window.pyodideInstance = pyodide;
        window.pyodideMicropip = micropip;
        window.pyodideInstalledPackages = pyodideConfig.packages_to_install || [];
        window.pyodidePreloadStatus = 'ready';
        updatePyodideProgressUI('ready', 'Ready!');

    } catch (error) {
        console.error('[PyodidePreload] Failed:', error);
        window.pyodidePreloadStatus = 'error';
        window.pyodidePreloadError = error;
        updatePyodideProgressUI('error', 'Failed to load Python runtime');
    }
}
```

**Critical design decisions:**
- Store on `window` for global access (both `index.js` and `pyodide_remote_game.js` need it).
- Track status explicitly (`idle`/`loading`/`ready`/`error`) so Phase 68 can check.
- Store `micropip` and installed packages list so `RemoteGame` can skip redundant installs.
- Do NOT change `RemoteGame`/`MultiplayerPyodideGame` in this phase -- that's Phase 68.

### Pattern 3: Progress Indicator (INIT-03)
**What:** Show a loading status to the participant during Pyodide initialization.
**When to use:** While `loadPyodide()` and package installation are running.

The existing `#screeningLoader` element (spinner + status text) provides the perfect model. Add a similar `#pyodideLoader` element, or reuse `#screeningLoader` if screening completes before Pyodide loads.

```javascript
function updatePyodideProgressUI(status, message) {
    const loader = document.getElementById('pyodideLoader');
    const statusText = document.getElementById('pyodideStatus');

    if (!loader || !statusText) return;

    if (status === 'loading') {
        loader.style.display = 'flex';
        statusText.textContent = message;
    } else if (status === 'ready') {
        loader.style.display = 'none';
    } else if (status === 'error') {
        statusText.textContent = message;
        // Keep visible so user knows something went wrong
    }
}
```

**UI placement:** The Pyodide loading indicator should appear within the `#sceneBody` area or as a dedicated element above the advance/start button. It should be visible during the StartScene (compat check) and should NOT block the scene header/body content from displaying.

### Pattern 4: Advancement Gating (INIT-04)
**What:** Prevent participant from advancing past the compatibility check scene until Pyodide is fully loaded.
**When to use:** In the advance button and start button handlers.

The existing `enableStartRefreshInterval()` function already polls `pyodideReadyIfUsing()` before enabling the start button. For the StartScene/advance button flow, we need similar gating:

```javascript
// Modify the advanceButton click handler or add a guard
$('#advanceButton').click(() => {
    // If Pyodide is loading, don't advance yet
    if (window.pyodidePreloadStatus === 'loading') {
        console.log('[Advance] Waiting for Pyodide preload...');
        // Show message to user
        return;
    }
    // ... existing advance logic
});
```

**Better approach:** Disable the advance button while Pyodide is loading, and poll to re-enable it (similar to `enableStartRefreshInterval`). This way the button visually communicates "not ready yet" with the existing disabled styling + spinner.

### Recommended Project Structure Changes
```
interactive_gym/server/static/js/
    index.js                        # ADD: pyodide preload logic in experiment_config handler
                                    # ADD: pyodidePreloadStatus tracking
                                    # ADD: advance button gating for Pyodide readiness

interactive_gym/server/static/templates/
    index.html                      # ADD: #pyodideLoader element (spinner + status text)

interactive_gym/configurations/
    experiment_config.py            # ADD: get_pyodide_config() method to scan stager scenes

interactive_gym/server/
    app.py                          # MODIFY: include pyodide_config in experiment_config event
```

### Anti-Patterns to Avoid
- **Starting preload on scene activation:** Too late. By the time the GymScene activates, the user might already be in the waiting room or about to start a game. The preload MUST start at `experiment_config` time (first connection).
- **Blocking entry screening on Pyodide:** Entry screening and Pyodide loading should run concurrently, not sequentially. If screening fails, wasted Pyodide load is acceptable (participant is excluded anyway).
- **Using a Web Worker for `loadPyodide`:** Explicitly deferred per project decision. The pre-loading during compat check avoids the need. Web Worker would require Comlink or message passing overhead.
- **Putting pyodideConfig in each scene's metadata:** The whole point is to detect Pyodide need BEFORE any scene activates. Scene metadata arrives per-scene; we need experiment-level detection.
- **Changing RemoteGame/MultiplayerPyodideGame in this phase:** That is Phase 68. This phase creates the preload infrastructure; Phase 68 wires the game classes to use it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Progress tracking for WASM download | Custom fetch interception | Indeterminate spinner | `Content-Length` is for compressed size, not uncompressed. Indeterminate spinner is honest and simple. Three stages ("Loading runtime...", "Installing packages...", "Ready!") give enough feedback. |
| Pyodide loading state machine | Custom state manager | Simple `window.pyodidePreloadStatus` string | Only 4 states needed: idle, loading, ready, error. No transitions are complex. |
| Scene scanning for Pyodide need | Complex recursive tree walk | Simple iteration over `stager.scenes` with `unpack()` | `SceneWrapper.unpack()` already exists and handles recursion. Just iterate and check `run_through_pyodide`. |

**Key insight:** The complexity here is minimal -- the hard part is getting the TIMING right (load during compat check, not during game start). The implementation is straightforward once the timing is established.

## Common Pitfalls

### Pitfall 1: Race Between experiment_config and activate_scene
**What goes wrong:** `experiment_config` starts Pyodide loading, but `activate_scene` for the StartScene arrives before loading completes. If the advance button is enabled before Pyodide is ready, the participant can advance to a GymScene with no Pyodide.
**Why it happens:** Both events fire in quick succession during `register_subject`.
**How to avoid:** Gate the advance button on `window.pyodidePreloadStatus === 'ready'`. Poll at 500ms intervals (matching existing `enableStartRefreshInterval` pattern). The StartScene already shows content while loading happens.
**Warning signs:** Participant clicks "Continue" and then sees a long loading delay on the GymScene screen (the OLD behavior).

### Pitfall 2: ExperimentConfig vs RemoteConfig Divergence
**What goes wrong:** `CONFIG` in `app.py` can be either `ExperimentConfig` or `RemoteConfig`. Only `ExperimentConfig` has a `stager` attribute. `RemoteConfig` does NOT have `get_entry_screening_config()` (currently called without checking type).
**Why it happens:** Two config classes coexist for backward compatibility. `ExperimentConfig` is the modern path with Stager-based scene flow.
**How to avoid:** Add `get_pyodide_config()` to `ExperimentConfig` only. In `app.py`, check `hasattr(CONFIG, 'get_pyodide_config')` before calling it. The `RemoteConfig` path doesn't use Stagers, so scene scanning doesn't apply there.
**Warning signs:** `AttributeError: 'RemoteConfig' object has no attribute 'stager'` in server logs.

### Pitfall 3: SceneWrapper Recursion
**What goes wrong:** Scenes can be wrapped in `RandomizeOrder`, `RepeatScene`, or nested `SceneWrapper` objects. A naive `for scene in stager.scenes` misses the actual `GymScene` objects inside wrappers.
**Why it happens:** The Stager holds a mix of bare `Scene` objects and `SceneWrapper` objects.
**How to avoid:** Use `scene.unpack()` which recursively resolves all wrappers to flat `Scene` lists. This method already exists on both `Scene` and `SceneWrapper`.
**Warning signs:** Experiment has Pyodide scenes inside a `RandomizeOrder` wrapper but `get_pyodide_config()` returns `needs_pyodide: false`.

### Pitfall 4: Double loadPyodide() If Phase 68 Is Not Yet Implemented
**What goes wrong:** This phase pre-loads Pyodide and stores it on `window.pyodideInstance`. But the existing `RemoteGame.initialize()` will ALSO call `loadPyodide()` when the GymScene starts, resulting in two Pyodide instances and wasted memory/time.
**Why it happens:** Phase 67 creates the preload; Phase 68 modifies game classes to skip their own loading.
**How to avoid:** This is EXPECTED during the gap between Phase 67 and Phase 68. The pre-loaded instance will be unused until Phase 68 connects it. This is acceptable because the primary goal of Phase 67 is to have Pyodide ready -- even if the game class loads its own copy temporarily, the preload proves the infrastructure works. Phase 68 eliminates the redundancy.
**Warning signs:** Console shows two `loadPyodide()` calls. This is expected and documented.

### Pitfall 5: Pyodide Preload Failure Should Not Block Experiment
**What goes wrong:** If `loadPyodide()` fails (network error, CDN down), the participant is permanently stuck on the compat check screen with a disabled advance button.
**Why it happens:** The gating logic prevents advancement when status is not 'ready'.
**How to avoid:** Add a fallback: if preload fails, set status to 'error' but still allow advancement. The existing game-time loading (`RemoteGame.initialize()`) will attempt its own load. The preload is an optimization, not a requirement.
**Warning signs:** Participant stuck on "Loading Python runtime..." with an error in console.

### Pitfall 6: `loadPyodide()` Blocks Main Thread During WASM Compilation
**What goes wrong:** Even though `loadPyodide()` is `async`, the WASM compilation step blocks the main thread for several seconds. During this time, Socket.IO pings won't be answered, potentially causing disconnects.
**Why it happens:** WebAssembly.compile() is synchronous within the microtask queue.
**How to avoid:** This is the EXACT problem this milestone solves! During compat check, no game is running and disconnects don't matter (the participant hasn't joined a game yet). The server already has `ping_interval=8, ping_timeout=8` which gives 16 seconds of grace. If that's not enough, Phase 69 adds explicit server-side grace. The key point: blocking during compat check is FINE because the participant is just reading instructions.
**Warning signs:** Server logs show disconnect during preload. Phase 69 addresses this.

## Code Examples

### Server: Scanning Stager for Pyodide Config

```python
# In experiment_config.py ExperimentConfig class
def get_pyodide_config(self) -> dict:
    """Scan stager scenes for Pyodide requirements.

    Iterates through all scenes (including wrapped scenes) to find
    any GymScene with run_through_pyodide=True, and collects the
    union of all packages_to_install.
    """
    if self.stager is None:
        return {"needs_pyodide": False, "packages_to_install": []}

    needs_pyodide = False
    all_packages = set()

    for scene_or_wrapper in self.stager.scenes:
        # unpack() handles SceneWrapper recursion
        unpacked = scene_or_wrapper.unpack() if hasattr(scene_or_wrapper, 'unpack') else [scene_or_wrapper]
        for s in unpacked:
            if hasattr(s, 'run_through_pyodide') and s.run_through_pyodide:
                needs_pyodide = True
                if hasattr(s, 'packages_to_install') and s.packages_to_install:
                    all_packages.update(s.packages_to_install)

    return {
        "needs_pyodide": needs_pyodide,
        "packages_to_install": list(all_packages),
    }
```

### Server: Sending Pyodide Config in experiment_config Event

```python
# In app.py register_subject handler
# Existing code:
flask_socketio.emit(
    "experiment_config",
    {"entry_screening": CONFIG.get_entry_screening_config()},
    room=sid,
)

# Modified to include pyodide_config:
experiment_config_data = {
    "entry_screening": CONFIG.get_entry_screening_config(),
}
if hasattr(CONFIG, 'get_pyodide_config'):
    experiment_config_data["pyodide_config"] = CONFIG.get_pyodide_config()

flask_socketio.emit("experiment_config", experiment_config_data, room=sid)
```

### Client: Preloading Pyodide on experiment_config

```javascript
// In index.js, new global state
window.pyodideInstance = null;
window.pyodideMicropip = null;
window.pyodideInstalledPackages = [];
window.pyodidePreloadStatus = 'idle'; // 'idle' | 'loading' | 'ready' | 'error'

async function preloadPyodide(pyodideConfig) {
    if (!pyodideConfig || !pyodideConfig.needs_pyodide) {
        window.pyodidePreloadStatus = 'ready'; // No Pyodide needed, so "ready"
        return;
    }

    console.log('[PyodidePreload] Starting preload...');
    window.pyodidePreloadStatus = 'loading';
    showPyodideProgress('Loading Python runtime...');

    try {
        const pyodide = await loadPyodide();
        console.log('[PyodidePreload] Core loaded, installing micropip...');
        showPyodideProgress('Installing packages...');

        await pyodide.loadPackage("micropip");
        const micropip = pyodide.pyimport("micropip");

        const packages = pyodideConfig.packages_to_install || [];
        if (packages.length > 0) {
            console.log('[PyodidePreload] Installing:', packages);
            await micropip.install(packages);
        }

        window.pyodideInstance = pyodide;
        window.pyodideMicropip = micropip;
        window.pyodideInstalledPackages = packages;
        window.pyodidePreloadStatus = 'ready';
        hidePyodideProgress();
        console.log('[PyodidePreload] Complete');

    } catch (error) {
        console.error('[PyodidePreload] Failed:', error);
        window.pyodidePreloadStatus = 'error';
        showPyodideProgress('Loading failed - will retry when game starts');
        // Don't block advancement -- fallback to game-time loading
    }
}

// In the experiment_config handler:
socket.on('experiment_config', async function(data) {
    // ... existing entry screening logic ...

    // Start Pyodide preload concurrently with entry screening
    if (data.pyodide_config) {
        preloadPyodide(data.pyodide_config); // Fire and forget (async)
    }
});
```

### Client: Advancement Gating

```javascript
// Two gating strategies depending on scene type:

// 1. For StartScene advance button: poll and disable
function gatePyodideAdvancement() {
    if (window.pyodidePreloadStatus === 'idle') return; // No Pyodide needed

    const checkInterval = setInterval(() => {
        if (window.pyodidePreloadStatus === 'ready' ||
            window.pyodidePreloadStatus === 'error') {
            // Ready or failed (fallback to game-time loading)
            $("#advanceButton").attr("disabled", false);
            clearInterval(checkInterval);
        } else {
            // Still loading
            $("#advanceButton").attr("disabled", true);
        }
    }, 500);
}

// 2. For GymScene start button: existing enableStartRefreshInterval already
//    checks pyodideReadyIfUsing(). Phase 68 will make that check use the
//    pre-loaded instance. For now, the existing check still works.
```

### HTML: Pyodide Loading Indicator

```html
<!-- In index.html, after #screeningLoader -->
<div id="pyodideLoader" style="display: none;">
    <div class="screening-spinner"></div>
    <div id="pyodideStatus">Loading Python runtime...</div>
</div>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Load Pyodide when GymScene starts | Pre-load during compat check | Phase 67 (this phase) | Eliminates 5-15s blocking at game start |
| No progress feedback during load | Indeterminate spinner with phase messages | Phase 67 (this phase) | Better UX during wait |
| Advance button always enabled | Gated on Pyodide readiness | Phase 67 (this phase) | Prevents premature advancement |

**Current Pyodide version in use:** v0.26.2 (from CDN in index.html)
**Latest Pyodide version:** v0.29.3 (upgrade not in scope for this phase)
**Note:** The TODO comment in index.html mentions upgrading Pyodide for more package availability (e.g., scipy). This is a separate concern from pre-loading.

## Open Questions

1. **Should preload use GENERIC_STAGER or per-participant stager?**
   - What we know: `GENERIC_STAGER` is shared; per-participant stagers are deep copies. All copies have the same scene types (randomization only affects order, not which scene types exist).
   - What's unclear: Could a researcher use `RandomizeOrder` with `keep_n` that conditionally excludes all Pyodide scenes for some participants?
   - Recommendation: Scan `GENERIC_STAGER` for efficiency. If `keep_n` is used, the worst case is pre-loading Pyodide unnecessarily (no harm). Pre-loading when not needed costs a few seconds of loading but doesn't break anything.

2. **Should the advance button gate apply to ALL scenes or just StartScene?**
   - What we know: The advance button is used on StaticScene and StartScene. The start button is used on GymScene.
   - What's unclear: If there are multiple static scenes before the GymScene, should ALL be gated?
   - Recommendation: Only gate the FIRST scene (StartScene) since Pyodide loading starts at `experiment_config` time, which is before the first scene. By the time the participant reads the start scene instructions, Pyodide will likely be loaded. If they're fast readers, they wait. For subsequent static scenes, Pyodide should already be loaded. Add gating to the advance button handler generically (check status before emitting `advance_scene`) so it works on any scene.

3. **How to handle RemoteConfig (non-Stager) experiments?**
   - What we know: `RemoteConfig` has `run_through_pyodide` but no `stager`.
   - What's unclear: Is `RemoteConfig` still actively used with Pyodide?
   - Recommendation: Add `get_pyodide_config()` to `RemoteConfig` that returns `{needs_pyodide: self.run_through_pyodide, packages_to_install: self.packages_to_install}`. This handles both config types.

## Sources

### Primary (HIGH confidence)
- Codebase analysis of `index.js`, `pyodide_remote_game.js`, `experiment_config.py`, `app.py`, `stager.py`, `scene.py`, `gym_scene.py` -- direct code reading
- Codebase analysis of `index.html` template -- CDN versions and UI structure
- `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` -- project decisions and requirements

### Secondary (MEDIUM confidence)
- [Pyodide JS API v0.29.3](https://pyodide.org/en/stable/usage/api/js-api.html) -- `loadPyodide` API signature, no built-in progress callback
- [micropip API](https://micropip.pyodide.org/en/stable/project/api.html) -- `install()` has verbose param but no progress callback
- [Pyodide loadPyodide progress discussion #2927](https://github.com/pyodide/pyodide/discussions/2927) -- fetch interception workaround for download progress

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new libraries, all verified from existing codebase
- Architecture: HIGH - directly derived from codebase analysis, clear event flow
- Pitfalls: HIGH - identified from concrete code paths (ExperimentConfig vs RemoteConfig, SceneWrapper recursion, double loadPyodide)
- Code examples: HIGH - based on existing patterns in the codebase (entry screening, start button gating)

**Research date:** 2026-02-06
**Valid until:** Indefinite (codebase-specific research, no external dependencies changing)
