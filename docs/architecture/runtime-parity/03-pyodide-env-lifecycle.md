# Dimension 3 — Browser (Pyodide) Environment Execution Lifecycle

| Field | Value |
| --- | --- |
| Audit date | 2026-07-19 |
| Sources | `mug/server/static/js/pyodide_remote_game.js`, `mug/scenes/gym_scene.py`, `mug/server/app.py` pyodide_* handlers, env-side parts of `pyodide_multiplayer_game.js`, `mug/configurations/experiment_config.py`, `examples/mountain_car/` |
| Contracts mapped | API-07, API-09, API-16 (rev 0.2) |

## 1. Mechanism map

### 1.1 Pyodide bootstrap sequence

- **Runtime version**: Pyodide loaded from CDN, pinned in the page template: `https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.js` (`index.html:333`). Matches the version used in api-07's import-proof validation.
- **Preload path (normal path)**: on `experiment_config` socket event, the client fires `preloadPyodide()` concurrently with entry screening (`index.js:651-687`). The server computes the config in `ExperimentConfig.get_pyodide_config()` (`experiment_config.py:221-249`): walks all stager scenes, sets `needs_pyodide` if any GymScene has `run_through_pyodide=True`, and returns the **union of `packages_to_install` across all scenes** plus `pyodide_load_timeout_s`. Preload sequence (`index.js:287-340`): emit `pyodide_loading_start` → 50 ms yield so the emit escapes before WASM compilation blocks the main thread → `loadPyodide()` → `loadPackage("micropip")` → `micropip.install(unionPackages)` → stash on `window.pyodideInstance / pyodideMicropip / pyodideInstalledPackages` → emit `pyodide_loading_complete`.
- **Loading gate**: a unified gate requires both screening and Pyodide completion before any scene is processed (`index.js:209-278`); early scenes queue in `pendingSceneData`. A configurable timeout (default 60 s) fails the gate.
- **Per-scene bootstrap**: `activate_scene` → `startGymScene(data)`; if `data.run_through_pyodide`, `initializePyodideRemoteGame(data)` (`index.js:1704-1728`) decides between new `MultiplayerPyodideGame`, new `RemoteGame`, or **reuse** via `reinitialize_environment(data)` when neither `restart_pyodide` nor a single↔multi type switch applies.
- `RemoteGame.initialize()` (`pyodide_remote_game.js:48-110`): reuses the preloaded instance if ready, otherwise loads fresh. Installs only packages not in `this.installed_packages` (dedup against preload).
- **`data` is the GymScene's `scene_metadata`** — every public attribute serialized by `serialize_dict`, which silently drops non-JSON-serializable values (callables like `env_creator`, `hud_text_fn`) (`gym_scene.py:238-251`, `scene.py:145-165`).

### 1.2 The init-code-string mechanism (exact contract)

**Python side (`GymScene.runtime()`, `gym_scene.py:739-814`):**
- `environment_initialization_code` (string) or `environment_initialization_code_filepath` (file read at config time); setting both asserts.
- `packages_to_install`: arbitrary micropip requirement strings; if none mention `multi-user-gymnasium`, `DEFAULT_MUG_PACKAGE = f"multi-user-gymnasium=={mug.__version__}"` is appended — the only auto-pin.
- `on_game_step_code`: Python source injected at the top of every step execution.
- `restart_pyodide`: forces a new game instance next scene.
- Setting any pyodide param auto-infers `run_through_pyodide=True`; `pyodide_multiplayer` auto-inferred from ≥2 human policies + pyodide + not server-auth.

**JS side (`pyodide_remote_game.js:90-110`):** the code string is executed via `runPythonAsync` with:
1. All `from __future__` lines hoisted above an injected preamble.
2. Injected preamble: `import js` + `mug_globals = dict(js.window.mugGlobals.object_entries())` — researcher code can read a `mug_globals` dict inside the env namespace. The `pyodide.globals.set("mug_globals", ...)` at js:87 is immediately shadowed by this preamble; `config.mug_globals` doesn't exist — **the window global is the real channel**.
3. The user's code, verbatim, executed in the **Pyodide module-global namespace**; the contract is that it leaves a module-level variable `env` bound.
4. A trailing bare `env` expression returns the proxy; if `undefined`, a descriptive Error is thrown.

Everything else the runtime does — reset, step, hashing, snapshot, resync — is Python snippets referring to the **global name `env`**.

`reinitialize_environment(config)` re-runs the same sequence in the **same interpreter** (installing only new packages), so globals from a previous scene persist unless rebound.

### 1.3 Step loop

- **Driver (single-player)**: Phaser's RAF `update()` calls `processPyodideGame()` when ready (`phaser_gym_graphics.js:431-459`). No Web Worker: stepping is RAF-throttled, so a backgrounded tab pauses the env. Multiplayer uses Worker ticks instead.
- **Per tick** (`phaser_gym_graphics.js:463-546`): if `shouldReset` → `reset()`; else `buildPyodideActionDict()` assembles a full action dict for **every agent in `policy_mapping`**: human agents from keyboard, bot agents from `getBotAction` (ONNX async into `botActionBuffers`; **heuristics execute synchronously inside Pyodide against the live `env`**; `"random"` uses `Math.random`); `frame_skip` gates bot decision frames; fallback is `previous_submitted_action` or `default_action` per `action_population_method`.
- **`RemoteGame.step(actions)`** (`pyodide_remote_game.js:313-466`): runs a Python snippet that (a) executes `on_game_step_code` first, (b) coerces numeric string keys to ints, (c) `env.step(agent_actions)`, `env.render()`, (d) normalizes obs: flat array → `reshape(-1).astype(np.float32)`; dict → per-key flatten; dict-of-dicts → nested flatten; else ValueError, (e) promotes scalar rewards / non-dict obs/terminateds/truncateds to `{"human": ...}`.
- **Render state out**: result converted via `toPy(...).toJs()`; nested-array render_state treated as an RGB frame painted to canvas → base64 PNG; otherwise the Surface dict `{game_state_objects, removed}` (each object through `convertUndefinedToNull`, which also converts Pyodide Maps to plain objects) wrapped as `{game_state_objects, removed, step}` and buffered for Phaser.
- **Episode end**: `all(terminateds) || all(truncateds) || step_num >= max_steps` → incremental `emitEpisodeData(sceneId, episodeNum)` → `num_episodes++`; done or `shouldReset`. `index.js:1730-1768` polls `isDone()` every 100 ms and starts a 3 s "Done!" countdown with a MessageChannel watchdog before `advance_scene`.
- **Reset** (js:185-310): episode-transition UI for episodes ≥2, `env.reset()` — **no seed in single-player** — obs normalization, cumulative-rewards init honoring `hud_score_carry_over`.
- **Data logging (single-player)**: per-step `remoteGameLogger.logData({observations, actions, rewards, ...})`; at scene termination the residual buffer is msgpack'd and emitted as `emit_remote_game_data`.

### 1.4 Server-side pyodide_* events

| Event | Handler | What the server does | Status |
|---|---|---|---|
| `pyodide_loading_start` | `app.py:908-913` | Records a **disconnect grace period** during WASM compile | live |
| `pyodide_loading_complete` | `app.py:916-925` | Pops grace entry, logs duration | live |
| `pyodide_player_action` | `app.py:1795-1835` | Relay to other players (SocketIO fallback lane beside P2P) | live (multiplayer) |
| `pyodide_hud_update` | `app.py:2439-2461` | Broadcasts `pyodide_hud_sync` | **vestigial** — no client emits or listens |
| `pyodide_state_hash` | `app.py:2581-2618` | Calls `receive_state_hash(...)` | **dead + broken** — method does not exist on the coordinator |
| `pyodide_send_full_state` | `app.py:2621-2649` | Calls `receive_full_state(...)` | **dead + broken** — same |

The *live* hash/resync path is the peer-relayed trio `p2p_state_sync/request/response` (dumb server relay). Disconnect grace: `on_disconnect` skips all cleanup if the subject is inside the loading window (`pyodide_load_timeout_s`, default 60 s). SocketIO ping is relaxed to 8/30 explicitly to survive WASM compile stalls.

### 1.5 Multiplayer env-side (bootstrap/seed/snapshot/hash)

- `MultiplayerPyodideGame.initialize()`: `super.initialize()` → `validateStateSync()` → `seedPythonEnvironment(gameSeed)`.
- `validateStateSync()` (js:1634-1683): runtime `hasattr` detection of `env.get_state`/`env.set_state`; absence silently disables hash comparison, P2P resync, snapshots, rollback.
- Seed: server-generated per game; client seeds Mulberry32 JS RNG and Python `np.random`/`random`.
- Reset: re-seeds Python RNGs **with the same seed every episode**, resets Mulberry32, `env.reset(seed=gameSeed)`; episode-start verification hash is an 8-char **md5** of `json.dumps(env.get_state(), sort_keys=True)`.
- Snapshots (every `snapshot_interval` frames, pre-step): `{env_state, np_rng_state, py_rng_state}` + JS-side `cumulative_rewards`, `step_num`; restore verifies round-trip equality.
- Hashing: `computeQuickStateHash` = SHA-256 first 16 chars over `json.dumps(normalized, sort_keys=True, separators=(',',':'))` with floats rounded to 10 dp; confirmed-frame hashes computed from **snapshots**, not current state.
- Full-state resync: apply via `env.set_state(json.loads(...))` with backslash/quote escaping into a triple-quoted Python literal — injection-fragile encoding.

### 1.6 HUD and loading UX

- HUD is **client-computed JS**: `"Round: X/Y | Score: NN | Time left: SS.Ss"`, score = `cumulative_rewards[myPlayerId]` or first value, time from `max_steps`/`fps` (`pyodide_remote_game.js:468-494`). The scene's `hud_text_fn` is a callable and thus stripped from metadata — it never reaches the Pyodide path.
- Loading UX: unified `#loadingScreen` with status text; start button spinner until `pyodideReadyIfUsing()`; `advanceButton` blocked while preload is in-flight.

## 2. Failure semantics

1. **Preload failure or timeout**: terminal error page "Failed to load the Python runtime..."; `pyodide_loading_complete {error:true}` clears server grace.
2. **Scene-time package install or env-construction failure**: `RemoteGame`'s constructor calls `this.initialize()` **without awaiting** (js:10), and no caller catches it — a micropip failure or an exception in the researcher's init code becomes an **unhandled promise rejection**: `pyodideReady` stays false, the start-button spinner spins forever, no UI error, and no server signal. The participant is silently wedged.
3. **`on_game_step_code`/step exceptions**: rejected promise propagates out of `processPyodideGame` with no catch — single-player stepping stops with no surfaced error.
4. **Mid-episode tab backgrounding**: single-player — RAF stops, game freezes, no detection or exclusion. Multiplayer — Worker ticks continue; FocusManager + fast-forward + focus-loss timeout + ContinuousMonitor thresholds.
5. **Server detection of a wedged browser env**: for single-player, **none beyond transport** — only the relaxed SocketIO ping (8/30) and the 60 s loading-grace expiry. No env-level heartbeat, no step-progress report, no state reporting in single-player.
6. **Desync (multiplayer)**: hash mismatch → logged `desyncEvents`, deterministic tie-break, full-state resync; telemetry exported in `cumulativeValidation` metrics.

## 3. Determinism

- **Single-player is not reproducible.** `env.reset()` is called with **no seed**; Python RNGs never seeded; `GymScene.env_seed` (default 42) is serialized into scene metadata but **consumed by nothing** (dead config). `"random"` bot policy uses `Math.random`.
- **Multiplayer is best-effort deterministic**: shared server seed → Python RNG seeding at init and re-seed before each episode reset; `env.reset(seed=gameSeed)`; JS Mulberry32 for ONNX sampling, reset at episode boundaries; snapshots capture numpy + Python RNG state (but **not** the JS Mulberry32 state — bot sampling during rollback replay is not RNG-faithful; recorded actions are reused, explicit TODO).
- Hash determinism measures: float rounding to 10 dp, sorted keys, compact separators, SHA-256/16.
- Environment identity: Pyodide version pinned; mug package version-pinned by default; **`packages_to_install` entries are whatever the researcher wrote** — unpinned specs resolve at load time, so two participants can get different dependency versions.

## 4. Contract mapping (0.2)

### api-07 — EnvFactory

| Legacy behavior | Contract | Verdict |
|---|---|---|
| Exec-string `environment_initialization_code(_filepath)` leaving global `env` | R-17 qualified-name factory, compile-checked importability | **GAP (deliberate replacement)** — see reproduction list below |
| `packages_to_install` (arbitrary micropip specs, union-installed up-front, auto mug pin) | `requires=[...]` exact pins resolved at publish | **IMPROVE** — parity must keep the "install once up-front, dedupe per scene" performance property and the implicit self-dependency |
| Env args baked into the code string; `env_config`/`env_creator` never reach Pyodide (callables stripped) | Recorded per-occurrence `args` (treatment-capable) | **GAP** — no structured args channel exists today for browser envs |
| Study code delivery: single code string; heuristic policies ship module source in `policy_configs` as a second ad-hoc channel | `source_bundle` → `unpackArchive` → `sys.path` → import | **GAP** — multi-file study code unsupported today; the source-bundle design must subsume the heuristic-policy channel too |
| `get_state`/`set_state` detected at runtime, silently degrading | `hooks: snapshot-restore` declared | **IMPROVE** — declared beats sniffed; preserve graceful degradation (game still runs without hooks) |
| State hash computed platform-side from `get_state()` JSON | `hooks: state-hash` (env-provided) | **GAP/IMPROVE** — no env implements `state_hash` today; the exact normalization (10 dp rounding, sort_keys, compact separators, 16-char truncation) is the de-facto compatibility surface |
| No per-seat observation enforcement | `hooks: per-seat-observation`, per-seat `RenderPacket` | **GAP** — feature doesn't exist in legacy |
| RenderPacket dict from `Surface.commit().to_dict()`, plus legacy flat-array and RGB fallbacks | Typed Surface command vocabulary | **PARITY** on dict format + delta semantics; RGB and flat-array fallbacks are undocumented extras (RGB path half-broken in reset) |
| Worker ticks — multiplayer only | Contract implies all browser games get Worker ticks | **GAP** — single-player legacy has no Worker |

**What the init-code-string does that the R-17 factory must reproduce (exhaustive):**
1. Arbitrary module-level statements: imports, class definitions, subclassing, helpers, constants — everything before the final `env` binding.
2. **Execution in the interpreter's global namespace** — env methods can and do reference the global `env` by name: `examples/mountain_car/mountain_car_env.py:49` calls `env.unwrapped.min_position` *inside* `MountainCarEnv.render`. A factory-import world breaks this shipped example; parity work must flag it.
3. Constructor arguments inline (`render_mode="mug"`) → must map to `args`.
4. Ambient `mug_globals` dict injected from `window.mugGlobals` available to init code → api-09 retires `mugGlobals`; any env conditioned on subject/condition needs an `args`/treatment path.
5. `from __future__` hoisting quirk.
6. `on_game_step_code` — arbitrary Python run **before every `env.step`** in the same namespace. No contract equivalent anywhere in api-07; must be reproduced or explicitly dropped.
7. Re-init semantics: same interpreter across scenes, globals persist; `restart_pyodide` requests a fresh instance — but with preloading, "new instance" **still reuses `window.pyodideInstance`**, so a truly fresh interpreter no longer exists.
8. The implicit `env` global anchors every later runtime snippet (step/reset/get_state/set_state/hash/render); the factory contract's "MUG drives the env" replaces these snippet contracts wholesale.

### api-09 — client boundary

- `mugGlobals` explicitly retired (boundary #7): legacy injects it into the env namespace, merges it server-side on every data emission, restores it on reconnect. **GAP by design** — env init code is a consumer of this retired surface.
- Input: `action_mapping` maps JS key names → raw ints (composite tuples serialized to sorted comma-joined strings), `default_action` fill, both input modes → **PARITY** on capability, **IMPROVE** on typing.
- Per-seat delivery: nothing seat-scoped in legacy. **GAP**.

### api-16 — determinism declarations

- Legacy has **no declaration anywhere**; capability is discovered at runtime and single-player is non-deterministic (unseeded). Declaring `deterministic` for anything shaped like today's single-player mode would be false — **GAP**.
- Partial precedent for the state-hash chain: multiplayer exports `cumulativeValidation.allHashes` — an ancestor of `state_hash_chain_digest`, but never chained/digested, never verified server-side.
- Visual-fallback tier maps cleanly onto today's reality. **PARITY at "visual"; "deterministic" is new work.**

## 5. Intricacies register

1. **Obs normalization rules** — flat/dict/dict-of-dicts flattening to float32, scalar reward → `{"human": ...}`, non-dict terminateds/truncateds → `{"human": ...}`. Envs and downstream loggers depend on this canonical shape.
2. **Action-key coercion** `int(k) if k.isnumeric() ...` — agent IDs cross the JS boundary as strings; numeric IDs must round-trip to ints before `env.step`.
3. **`env.reset()` unseeded in single-player vs re-seeded with the *same* seed every episode in multiplayer** — multiplayer episodes only differ if the env carries state across resets.
4. **Numpy import persistence**: single-player `step()`'s Python uses `np` without importing it — valid only because `reset()` ran `import numpy as np` into shared globals first. Reordering breaks it.
5. **RGB-array rendering asymmetry**: `step()` produces `game_image_base64` correctly; `reset()` assigns to an undeclared variable while testing a never-set one — the reset-frame image path is broken today; RGB envs work only from frame 1.
6. **`convertUndefinedToNull` also converts Pyodide Maps → plain objects** — the Phaser renderer requires property access.
7. **HUD contract**: fixed text format, score-source fallback order, time-left derived from `max_steps` and `fps`, round display capped; `hud_score_carry_over` gates cumulative reward reset.
8. **Incremental episode export** at each episode end exists to avoid giant end-of-scene payloads; scene-end residual export + `sync_globals` ordering in `terminateGymScene`.
9. **Loading grace protocol**: `pyodide_loading_start/complete` around any main-thread-blocking load, the 50 ms yield, disconnect-with-grace, relaxed socket ping — all exist because WASM compile stalls look like disconnects.
10. **Preload union across scenes**: every scene's packages install before scene 1 — a startup-latency/scene-latency trade the manifest design should preserve.
11. **`restart_pyodide` no longer yields a fresh interpreter** when preload exists — cross-scene global pollution is possible today and silently accepted.
12. **Runtime capability sniffing degrades gracefully**: no hooks → game still runs, rollback/hash/resync silently off. Contract-declared hooks must keep a "runs anyway" story for undeclared envs.
13. **Two hash algorithms coexist**: md5/8-char for episode-start check and early-frame debug vs SHA-256/16-char float-normalized for confirmed frames. Confirmed hashes computed from **snapshots**, not live state.
14. **Snapshot completeness**: env_state + numpy RNG + Python RNG + JS `cumulative_rewards`/`step_num` — but **not** the Mulberry32 JS RNG, so bot sampling isn't rollback-deterministic (replay reuses recorded actions).
15. **State strings injected into Python via escaped triple-quoted literals** — replace with proper data passing.
16. **Dead server surface**: `pyodide_state_hash`/`pyodide_send_full_state` call nonexistent methods; `pyodide_hud_update`/`pyodide_hud_sync` has no client counterpart. Fossils of a pre-P2P server-verification design — do not port.
17. **Doc drift**: `GymScene` docstring advertises `state_sync_frequency_frames` and `queue_resync_threshold` which are never defined as attributes.
18. **Error swallowing**: unawaited `initialize()` means env/package failures after preload are invisible (infinite spinner). R-17's compile-time import checking eliminates the biggest class; runtime construction failure still needs a surfaced failure path.
19. **Heuristic policies run inside the same Pyodide interpreter against the live `env`** with module source shipped via `policy_configs` — the source-bundle design should subsume this second code-shipping mechanism.
20. **`env == undefined` is the sole validation** of init code; no type/protocol check of the resulting object until first reset/step.
