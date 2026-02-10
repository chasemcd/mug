# Phase 72: Server Python Dead Code Removal - Research

**Researched:** 2026-02-07
**Domain:** Python dead code identification and removal in Flask/SocketIO server codebase
**Confidence:** HIGH

## Summary

Comprehensive analysis of all Python files in `interactive_gym/server/`, `interactive_gym/configurations/`, and `interactive_gym/utils/` (26 files total) was performed. Every function, class, and method definition was cross-referenced against the entire codebase using grep to determine usage. The analysis also identified vestigial logic including commented-out code blocks, unreachable code, duplicate imports, and obsolete feature remnants.

The codebase has a moderate amount of dead code concentrated in a few areas: an entire legacy class (`RemoteGame`), two entirely unused utility files (`onnx_inference_utils.py` and `inference_utils.py`), an unused configuration file (`render_configs.py`), several unused methods on otherwise-active classes, and scattered vestigial code (commented-out handlers, duplicate imports, unreachable code after return statements).

**Primary recommendation:** Remove dead code in dependency order -- start with standalone dead files/classes, then remove dead methods from live classes, then clean up vestigial patterns. Run unit tests after each removal group to catch regressions.

## Standard Stack

Not applicable for this phase. This is a pure removal/cleanup phase using only grep-based analysis and testing.

### Tools Needed
| Tool | Purpose | Why |
|------|---------|-----|
| `grep`/`rg` | Cross-reference each definition against codebase | Verify truly unused |
| `pytest` | Regression testing | Verify no functionality changes |
| `git` | Incremental commits | Rollback safety |

## Architecture Patterns

### Codebase Scope

Files in scope (26 Python files):

```
interactive_gym/
  server/
    __init__.py                    # Empty
    app.py                         # ~3020 lines - Main Flask app, SocketIO handlers
    callback.py                    # ~93 lines - GameCallback, MultiCallback
    game_manager.py                # ~1604 lines - GameManager class
    match_logger.py                # ~138 lines - MatchAssignmentLogger
    matchmaker.py                  # ~412 lines - Matchmaker ABC + implementations
    participant_state.py           # ~133 lines - ParticipantState enum + tracker
    player_pairing_manager.py      # ~317 lines - PlayerGroup, PlayerGroupManager
    probe_coordinator.py           # ~279 lines - ProbeCoordinator (P2P RTT)
    pyodide_game_coordinator.py    # ~954 lines - PyodideGameCoordinator
    remote_game.py                 # ~788 lines - RemoteGameV2 (active) + RemoteGame (dead)
    server_game_runner.py          # ~627 lines - ServerGameRunner
    utils.py                       # ~95 lines - ThreadSafe*, GameExitStatus, Available
    admin/
      __init__.py                  # admin_bp Blueprint, AdminUser
      aggregator.py                # ~1483 lines - AdminEventAggregator
      namespace.py                 # ~111 lines - AdminNamespace
      routes.py                    # ~61 lines - admin routes
  configurations/
    __init__.py                    # Empty
    configuration_constants.py     # InputModes, PolicyTypes, ActionSettings
    experiment_config.py           # ~300 lines - ExperimentConfig class
    object_contexts.py             # ~361 lines - Sprite, Line, Circle, etc.
    remote_config.py               # ~501 lines - RemoteConfig class
    render_configs.py              # ~19 lines - Animation dataclass (DEAD)
  utils/
    __init__.py                    # Empty
    inference_utils.py             # ~14 lines - sample_action_via_softmax (DEAD)
    onnx_inference_utils.py        # ~84 lines - ONNX inference (DEAD)
    typing.py                      # ~5 lines - SubjectID, GameID, RoomID, SceneID
```

### Dynamic Dispatch Patterns (CAUTION zones)

The following patterns call code indirectly. Do NOT remove anything that appears unused if it falls into these categories:

1. **SocketIO event handlers** (`@socketio.on("event_name")`) - Called by client JS, not by Python code. Never remove based on lack of Python references alone.

2. **Flask-SocketIO Namespace methods** (`on_connect`, `on_disconnect`, `on_request_state`, etc. in `AdminNamespace`) - Called dynamically by Flask-SocketIO framework. Never remove.

3. **Callback class methods** (`GameCallback.on_episode_start`, etc.) - Called via `MultiCallback` from `RemoteGameV2.tick()`. The base class methods are no-ops that get overridden by user subclasses.

4. **`atexit.register` callbacks** - `on_exit()` is registered at startup.

5. **Thread targets** - `policy_consumer` is used as a thread target in `RemoteGameV2._init_bot_threads()`.

6. **Flask route decorators** (`@app.route`, `@admin_bp.route`) - Called by HTTP requests.

7. **Dataclass/frozen dataclass fields** - May be accessed via `getattr()` patterns.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Dead code detection | Manual line-by-line review | Grep-based cross-referencing | Systematic, verifiable, reproducible |
| Verifying no functionality change | Manual testing | `pytest tests/unit/` baseline | Automated, consistent |

## Common Pitfalls

### Pitfall 1: Removing SocketIO Handlers Mistakenly
**What goes wrong:** A handler decorated with `@socketio.on("event")` appears unused in Python grep because it's called from JavaScript client code.
**Why it happens:** Grep only searches Python files, but SocketIO events are emitted from JS.
**How to avoid:** NEVER remove functions decorated with `@socketio.on(...)`. These are all live.
**Warning signs:** Any function with `@socketio.on` decorator is dynamically dispatched.

### Pitfall 2: Removing Callback Base Class Methods
**What goes wrong:** `GameCallback` methods like `on_episode_start` appear to do nothing (they're no-ops in the base class).
**Why it happens:** These are meant to be overridden by user-provided subclasses.
**How to avoid:** Do not remove `GameCallback` or `MultiCallback` methods. The base class interface is part of the public API.
**Warning signs:** Abstract-like base class methods with `pass` bodies.

### Pitfall 3: Breaking Type Annotations When Removing Dead Classes
**What goes wrong:** Removing `RemoteGame` class breaks type annotations in `callback.py` and example files that reference `remote_game.RemoteGame` in type hints.
**Why it happens:** Type annotations reference the class even though it's never instantiated.
**How to avoid:** When removing dead classes, update all type annotations to reference the live class (`RemoteGameV2`). Search for the class name in ALL file types, not just `.py`.

### Pitfall 4: Duplicate Removal Creating Import Errors
**What goes wrong:** Removing duplicate imports (e.g., `import os` appears twice in app.py) by removing the wrong one causes import ordering issues.
**Why it happens:** The second `import os` on line 13 is redundant with line 6, but careless removal could cause issues.
**How to avoid:** Always remove the LATER duplicate, preserving the first occurrence.

### Pitfall 5: Removing Methods Called Only From Dead Code
**What goes wrong:** A method that is called only from other dead code appears "used" in grep because it has callers -- but those callers are themselves dead.
**Why it happens:** The old `RemoteGame` class has methods that call each other internally.
**How to avoid:** When removing a dead class, remove ALL its methods together. Don't leave orphans.

## Code Examples

N/A - This phase removes code rather than adding it.

## Dead Code Inventory

### Category A: Entire Dead Files (can be deleted entirely)

| File | Contents | Evidence | Confidence |
|------|----------|----------|------------|
| `configurations/render_configs.py` | `Animation` dataclass | Never imported anywhere in codebase | HIGH |
| `utils/onnx_inference_utils.py` | ONNX model inference functions | Never imported outside own file; only referenced in documentation (.rst files) | HIGH |
| `utils/inference_utils.py` | `sample_action_via_softmax` | Only imported by `onnx_inference_utils.py` which is itself dead | HIGH |

### Category B: Dead Classes Within Live Files

| File | Dead Class/Code | Evidence | Confidence | Notes |
|------|----------------|----------|------------|-------|
| `remote_game.py` | `RemoteGame` class (lines ~452-788) | Never instantiated; `RemoteGameV2` is used everywhere; old class uses `RemoteConfig` instead of `GymScene` | HIGH | Type annotations in `callback.py` and example utils reference this class -- must update those |
| `object_contexts.py` | `RenderedEnvRGB` class (line ~354) | Never referenced anywhere in codebase | HIGH | |

### Category C: Dead Methods on Live Classes

| File | Class | Dead Method | Evidence | Confidence |
|------|-------|-------------|----------|------------|
| `game_manager.py` | `GameManager` | `_is_rtt_compatible` | Only defined, never called (line 381) | HIGH |
| `game_manager.py` | `GameManager` | `_get_waiting_subject_ids` | Only defined, never called (line 420) | HIGH |
| `game_manager.py` | `GameManager` | `send_participant_to_waiting_room` | Only defined, never called (line 954) | HIGH |
| `game_manager.py` | `GameManager` | `broadcast_waiting_room_status` | Only defined, never called (line 975) | HIGH |
| `aggregator.py` | `AdminEventAggregator` | `track_participant_game_start` | Only defined, never called (line 206) | HIGH |
| `aggregator.py` | `AdminEventAggregator` | `track_participant_game_end` | Only defined, never called (line 232) | HIGH |
| `aggregator.py` | `AdminEventAggregator` | `track_wait_complete` | Only defined, never called (line 445) | HIGH |
| `aggregator.py` | `AdminEventAggregator` | `archive_active_session` | Only defined, never called (line 355) | HIGH |
| `aggregator.py` | `AdminEventAggregator` | `get_session_detail` | Only defined, never called (line 391) | HIGH |
| `aggregator.py` | `AdminEventAggregator` | `get_participant_detail` | Only defined, never called (line 824) | HIGH |
| `aggregator.py` | `AdminEventAggregator` | `get_session_history_detail` | Only defined, never called (line 1220) | HIGH |
| `aggregator.py` | `AdminEventAggregator` | `stop_broadcast_loop` | Only defined, never called (line 1436) | HIGH |
| `experiment_config.py` | `ExperimentConfig` | `to_dict` | Only referenced in a comment (game_manager.py line 1202) | HIGH |
| `remote_config.py` | `RemoteConfig` | `logging` | Never called anywhere (line 100) | HIGH |
| `remote_config.py` | `RemoteConfig` | `to_dict` | Never called anywhere (line 457) | HIGH |
| `remote_config.py` | `RemoteConfig` | `simulate_waiting_room` | Never called anywhere (line 449) | HIGH |
| `app.py` | (module-level) | `is_valid_session` | Defined line 761, only referenced in comments (all calls commented out) | HIGH |

### Category D: Dead Standalone Functions

| File | Function | Evidence | Confidence |
|------|----------|----------|------------|
| `experiment_config.py` | `serialize_dict` | Only called from dead `to_dict` method (line 263) | HIGH |
| `experiment_config.py` | `is_json_serializable` | Only called from dead `serialize_dict` (line 288) | HIGH |
| `remote_config.py` | `serialize_dict` | Only called from dead `to_dict` method (line 464) | HIGH |
| `remote_config.py` | `is_json_serializable` | Only called from dead `serialize_dict` (line 489) | HIGH |

### Category E: Backward Compatibility Aliases

| File | Alias | Target | Evidence | Confidence |
|------|-------|--------|----------|------------|
| `player_pairing_manager.py` | `PlayerPairing = PlayerGroup` | `PlayerGroup` | Only used in `game_manager.py` line 65 type annotation (`PlayerPairingManager`) | MEDIUM |
| `player_pairing_manager.py` | `PlayerPairingManager = PlayerGroupManager` | `PlayerGroupManager` | Used in `game_manager.py` line 65 as parameter type | MEDIUM |

**Note on aliases:** `PlayerPairingManager` alias IS referenced in `game_manager.py` (line 65: `pairing_manager: player_pairing_manager.PlayerPairingManager | None = None`). The alias is functionally dead (could be replaced with `PlayerGroupManager`), but removing it requires updating the type annotation in game_manager.py. Treat as a rename candidate rather than pure dead code.

### Category F: Vestigial Logic (commented-out code, unreachable code, duplicates)

| File | Lines | Description | Confidence |
|------|-------|-------------|------------|
| `app.py` | 483-501 | Commented-out `on_connect` SocketIO handler | HIGH |
| `app.py` | 862-896 | Commented-out `on_disconnect` SocketIO handler | HIGH |
| `app.py` | 904 | Commented-out `# return` in `send_pressed_keys` | HIGH |
| `app.py` | 905 | Commented-out `# sess_id = ...` | HIGH |
| `app.py` | 925 | Commented-out `# game = game_manager.get_subject_game(subject_id)` | HIGH |
| `app.py` | 928-929 | Commented-out print statements | HIGH |
| `app.py` | 6, 13 | Duplicate `import os` | HIGH |
| `app.py` | 24, 29 | Duplicate `from interactive_gym.server import game_manager as gm` | HIGH |
| `app.py` | 1122-1127 | `on_exit()` calls `tear_down()` twice on each game_manager (duplicate loop) | HIGH |
| `app.py` | 487, 629, 786, 925, 930, 947 | Commented-out `is_valid_session` calls and related | HIGH |
| `onnx_inference_utils.py` | 58-73 | Unreachable code after `return action` on line 57 | HIGH |
| `aggregator.py` | 409 | `game.host_id` references non-existent attribute on `PyodideGameState` | HIGH |
| `game_manager.py` | 198-203 | Commented-out Game instantiation code | HIGH |

## Risks and Mitigation

### Risk 1: RemoteGame Type Annotations
**Risk:** Removing `RemoteGame` class breaks type annotations in `callback.py` (13 method signatures) and example utility files.
**Mitigation:** Update all type annotations from `remote_game.RemoteGame` to `remote_game.RemoteGameV2` simultaneously with class removal. Search pattern: `RemoteGame[^V]`.
**Files affected:** `callback.py` (lines 10-90), `examples/slime_volleyball/slime_volleyball_utils.py`, `examples/cogrid/overcooked_utils.py`.

### Risk 2: `host_id` Reference in Aggregator
**Risk:** `aggregator.py` line 409 references `game.host_id` which does not exist on `PyodideGameState`. This will raise `AttributeError` at runtime if that code path executes.
**Mitigation:** Remove the `host_id` line or replace with a safe default. This is vestigial from an earlier design.

### Risk 3: Test Coverage Gaps
**Risk:** Only 27 unit tests exist, and they only test matchmaker functionality. No tests cover the areas where dead code is being removed (app.py, game_manager.py methods, admin aggregator).
**Mitigation:** Run unit tests after each removal group as a smoke test. The E2E tests require headed browser mode and are expensive to run. Rely on code review to confirm removals are safe.

## Test Infrastructure

**Test command:** `pytest tests/unit/ -v`
**Baseline:** 27 tests, all passing (0.18s)
**Coverage:** Unit tests cover matchmaker (`test_latency_fifo_matchmaker.py`, `test_latency_fifo_integration.py`) only
**E2E tests:** Require headed Playwright browser (`pytest tests/e2e/ --headed`), test full server lifecycle. Available but expensive.
**Note:** E2E tests cannot run headless (Playwright headless sets `document.hidden=true`, breaking FocusManager).

## Removal Strategy

**Recommended order (dependency-safe):**

1. **Dead files first** - Delete `render_configs.py`, `onnx_inference_utils.py`, `inference_utils.py`
2. **Dead class** - Remove `RemoteGame` from `remote_game.py`, update type annotations
3. **Dead class member** - Remove `RenderedEnvRGB` from `object_contexts.py`
4. **Dead methods** - Remove dead methods from `GameManager`, `AdminEventAggregator`, `ExperimentConfig`, `RemoteConfig`
5. **Dead functions** - Remove `is_valid_session`, `serialize_dict`, `is_json_serializable` from their files
6. **Vestigial logic** - Clean up commented-out code, duplicate imports, unreachable code
7. **Backward compat aliases** - Remove `PlayerPairing`/`PlayerPairingManager` aliases, update references

Run `pytest tests/unit/` after each step.

## Open Questions

1. **Backward compatibility aliases**
   - What we know: `PlayerPairing = PlayerGroup` and `PlayerPairingManager = PlayerGroupManager` are backward compat aliases. `PlayerPairingManager` is actively used in `game_manager.py` type annotation.
   - What's unclear: Whether external users (researchers using this library) reference these aliases in their own code.
   - Recommendation: Remove aliases and update the one reference in game_manager.py. This is an internal-only codebase being cleaned before merge to main, so external compatibility is not a concern.

2. **`close_console_log_files` in aggregator**
   - What we know: Called only from `stop_broadcast_loop` which is itself dead.
   - What's unclear: Whether the broadcast loop cleanup was intentionally deferred or just never wired up.
   - Recommendation: Remove both `stop_broadcast_loop` and `close_console_log_files` since they're unreachable. The console log files are closed individually via `close_subject_console_log` which IS used.

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis via grep cross-referencing
- All 26 in-scope Python files read in full
- `pytest tests/unit/` baseline run (27/27 passing)

### Methodology
- Every function/class/method definition grepped against entire codebase
- Dynamic dispatch patterns (SocketIO handlers, Flask routes, thread targets, atexit callbacks) explicitly excluded from dead code candidates
- Type annotation references tracked alongside runtime references

## Metadata

**Confidence breakdown:**
- Dead code inventory: HIGH - Every item verified by grep cross-reference against full codebase
- Vestigial logic: HIGH - Commented-out code and unreachable code are directly observable
- Risk assessment: HIGH - Type annotation dependencies and test coverage verified

**Research date:** 2026-02-07
**Valid until:** Indefinite (codebase analysis, not library version dependent)
