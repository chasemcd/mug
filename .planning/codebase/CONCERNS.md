# Codebase Concerns

**Analysis Date:** 2026-02-07

## Dead Code

**Legacy `RemoteGame` class (entire class is unused):**
- Issue: `RemoteGame` (the original, non-V2 class) is defined alongside `RemoteGameV2` but is never instantiated anywhere in the codebase. All game creation uses `RemoteGameV2`. The class is 336 lines of dead code that is nearly a line-by-line duplicate of `RemoteGameV2`.
- Files: `interactive_gym/server/remote_game.py` (lines 452-787)
- Impact: Confusing to readers who must distinguish between two near-identical classes. Maintenance burden if either is updated.
- Fix approach: Delete the `RemoteGame` class entirely. The `GameCallback` class in `interactive_gym/server/callback.py` references `RemoteGame` in its type hints -- update those to `RemoteGameV2`.

**`GameCallback` / `MultiCallback` classes reference dead `RemoteGame`:**
- Issue: `interactive_gym/server/callback.py` imports and type-hints `RemoteGame` (the dead class). The callback system itself is only used via `self.scene.callback` in `GameManager` methods, but the type annotations point to the legacy class.
- Files: `interactive_gym/server/callback.py` (all 92 lines)
- Impact: Type hints are misleading. If anyone tries to use them, they'll reference the wrong class.
- Fix approach: Update type hints from `remote_game.RemoteGame` to `remote_game.RemoteGameV2`.

**Empty JS files:**
- Issue: `socket_handlers.js` and `latency.js` are empty files (0 bytes). `game_events.js` has a single empty function stub (`export function endGame() {};`).
- Files:
  - `interactive_gym/server/static/js/socket_handlers.js` (0 lines)
  - `interactive_gym/server/static/js/latency.js` (0 lines)
  - `interactive_gym/server/static/js/game_events.js` (3 lines, empty function)
- Impact: These files serve no purpose and create confusion about where socket/latency/game event code actually lives.
- Fix approach: Delete all three files. Verify no HTML template references them via `<script>` tags.

**Unused methods in `GameManager`:**
- Issue: Five methods in `GameManager` are defined but never called from anywhere in the codebase:
  - `_is_rtt_compatible()` -- superseded by the matchmaker's RTT filtering
  - `_get_waiting_subject_ids()` -- returns subjects from old game-based waitroom (replaced by `waitroom_participants` list)
  - `_remove_from_waitroom()` -- removes candidates from old game-based waitroom (replaced by `waitroom_participants` removal in Phase 60+)
  - `send_participant_to_waiting_room()` -- sends waitroom status to a subject by their subject_id room (superseded by socket-based emission in `_add_to_waitroom`)
  - `broadcast_waiting_room_status()` -- broadcasts to a game room (superseded by Phase 60+ flow where no game exists during waitroom)
- Files: `interactive_gym/server/game_manager.py` (lines 381-432, 719-763, 954-1001)
- Impact: ~120 lines of dead code that references the old game-based waitroom model, confusing readers about the current flow.
- Fix approach: Delete all five methods.

**`render_configs.py` is unused:**
- Issue: The `Animation` dataclass in `render_configs.py` is never imported by any file in the codebase.
- Files: `interactive_gym/configurations/render_configs.py` (19 lines)
- Impact: Minor clutter.
- Fix approach: Delete the file.

**`TYPE_CHECKING` import with empty body:**
- Issue: `player_pairing_manager.py` has `if TYPE_CHECKING: pass` -- an empty TYPE_CHECKING block that imports nothing.
- Files: `interactive_gym/server/player_pairing_manager.py` (lines 20-21)
- Impact: Minor clutter.
- Fix approach: Remove the `TYPE_CHECKING` import and empty block.

## Duplicate Imports

**`os` imported twice in `app.py`:**
- Issue: `import os` appears on line 9 and again on line 13.
- Files: `interactive_gym/server/app.py` (lines 9, 13)
- Fix approach: Remove the duplicate `import os` on line 13.

**`flask_socketio` imported twice in `game_manager.py`:**
- Issue: `import flask_socketio` appears on line 13 and again on line 50.
- Files: `interactive_gym/server/game_manager.py` (lines 13, 50)
- Fix approach: Remove the duplicate on line 50.

**`game_manager as gm` imported twice in `app.py`:**
- Issue: `from interactive_gym.server import game_manager as gm` appears on line 24 and again on line 29.
- Files: `interactive_gym/server/app.py` (lines 24, 29)
- Fix approach: Remove the duplicate on line 29.

## Commented-Out Code Blocks

**Large commented-out `on_connect` handler (~18 lines):**
- Issue: An entire SocketIO `on_connect` handler is commented out with `#` prefixes. It contains a TODO about session checking.
- Files: `interactive_gym/server/app.py` (lines 483-500)
- Fix approach: Delete the commented-out block entirely.

**Large commented-out `on_disconnect` handler (~32 lines):**
- Issue: A complete SocketIO `on_disconnect` handler is commented out. The actual working `on_disconnect` handler exists at line 2705. The commented-out version is vestigial.
- Files: `interactive_gym/server/app.py` (lines 862-896)
- Fix approach: Delete the commented-out block entirely.

**Commented-out session validation calls (5 locations):**
- Issue: Multiple calls to `is_valid_session()` are commented out across different handlers (`leave_game`, `send_pressed_keys`, `reset_complete`). The function `is_valid_session()` itself still exists but is never called.
- Files: `interactive_gym/server/app.py` (lines 629-631, 786-789, 930-933, 947-948)
- Impact: Suggests incomplete security implementation. The `is_valid_session()` function on lines 761-776 is dead code.
- Fix approach: Either re-enable session validation or delete `is_valid_session()` and all commented-out call sites.

**Commented-out metadata saving in `receive_remote_game_data` (~12 lines):**
- Issue: A block saving scene metadata to JSON is commented out with a TODO about a race condition.
- Files: `interactive_gym/server/app.py` (lines 1243-1255)
- Fix approach: Delete the commented-out block. The TODO describes a known race condition that has likely been addressed by other mechanisms.

**Commented-out `return` statement and debug print:**
- Issue: Line 904 has `# return` (dead early return in `send_pressed_keys`). Lines 928-929 have commented-out print statements.
- Files: `interactive_gym/server/app.py` (lines 904, 925, 928-929)
- Fix approach: Delete commented-out lines.

**Commented-out Game class instantiation (~5 lines):**
- Issue: Old `Game` class instantiation is commented out in `_create_game`.
- Files: `interactive_gym/server/game_manager.py` (lines 197-203)
- Fix approach: Delete the commented-out block.

## Redundant / Duplicated Logic

**`on_exit()` calls `tear_down()` twice on every game manager:**
- Issue: The `on_exit()` function iterates over `GAME_MANAGERS` and calls `tear_down()` in an identical loop twice in succession. This is a copy-paste bug.
- Files: `interactive_gym/server/app.py` (lines 1121-1127)
- Impact: Double tear-down on server shutdown. Likely harmless due to idempotent cleanup but wasteful and confusing.
- Fix approach: Delete the second `for` loop (lines 1126-1127).

**`serialize_dict()` and `is_json_serializable()` duplicated across two files:**
- Issue: Both `experiment_config.py` and `remote_config.py` contain identical implementations of `serialize_dict()` and `is_json_serializable()`.
- Files:
  - `interactive_gym/configurations/experiment_config.py` (lines 263-299)
  - `interactive_gym/configurations/remote_config.py` (lines 464-500)
- Impact: Any bug fix must be applied to both copies.
- Fix approach: Move both functions to a shared utility module (e.g., `interactive_gym/configurations/utils.py`) and import from there.

**`webrtc()` method duplicated between `ExperimentConfig` and `RemoteConfig`:**
- Issue: Both classes have nearly identical `webrtc()` methods (~30 lines each) that resolve TURN credentials from args or env vars.
- Files:
  - `interactive_gym/configurations/experiment_config.py` (lines 82-131)
  - `interactive_gym/configurations/remote_config.py` (lines 366-415)
- Impact: Any change to WebRTC credential resolution must be applied to both.
- Fix approach: Extract into a shared function or have one class inherit from the other.

**`RemoteConfig` duplicates much of `GymScene`'s configuration surface:**
- Issue: `RemoteConfig` has attributes for `env_creator`, `env_config`, `policy_mapping`, `action_mapping`, `fps`, `game_width`, `game_height`, `hud_text_fn`, etc. -- virtually all the same fields as `GymScene`. The `RemoteConfig` was the original configuration class; `GymScene` was introduced later as the scene-based replacement. `RemoteConfig` is still used as the experiment-level config (`CONFIG` in `app.py`) but its game-specific fields overlap heavily with `GymScene` and are no longer the primary source of truth for game configuration.
- Files:
  - `interactive_gym/configurations/remote_config.py` (500 lines)
  - `interactive_gym/scenes/gym_scene.py` (1005 lines)
- Impact: Confusing API surface. Users may set values on `RemoteConfig` expecting them to take effect, but `GymScene` is what actually drives game behavior.
- Fix approach: Long-term, deprecate the game-specific fields on `RemoteConfig` and keep it focused on experiment-level concerns (hosting, redirect URLs, data saving). For now, document clearly that `GymScene` is the authoritative source for game configuration.

## Unclear Naming

**`SUBJECTS` dict is misleading:**
- Issue: `SUBJECTS` in `app.py` maps subject_id to a `threading.Lock`, not to any subject data. The name suggests it stores subject information.
- Files: `interactive_gym/server/app.py` (line 98)
- Fix approach: Rename to `USER_LOCKS` or `SUBJECT_LOCKS`. Note: there is already a `USER_LOCKS` dict on line 120 that appears to serve the same purpose (but is never used). Consolidate to one.

**`USER_LOCKS` dict is never used:**
- Issue: `USER_LOCKS = utils.ThreadSafeDict()` is defined on line 120 but never read or written to. Meanwhile `SUBJECTS` serves the same purpose.
- Files: `interactive_gym/server/app.py` (line 120)
- Fix approach: Delete `USER_LOCKS`. If consolidating with `SUBJECTS`, rename `SUBJECTS` to `SUBJECT_LOCKS`.

**`subject` attribute in `GameManager`:**
- Issue: `self.subject = utils.ThreadSafeDict()` is defined but appears unused anywhere in the codebase.
- Files: `interactive_gym/server/game_manager.py` (line 91)
- Fix approach: Delete the attribute.

**Module-level `# Phase N` comments throughout:**
- Issue: 90+ references to "Phase N" scattered across 9 files. These are internal development tracking comments that reference the feature branch's incremental development history. They are meaningless to external readers and clutter the code.
- Files: Throughout `interactive_gym/server/app.py`, `interactive_gym/server/game_manager.py`, `interactive_gym/server/pyodide_game_coordinator.py`, `interactive_gym/scenes/gym_scene.py`, and others
- Impact: Reduces readability. Comments like `# Phase 54`, `# Phase 56: assignment logging`, `# Phase 59: P2P RTT probing` are not useful documentation.
- Fix approach: Remove all `Phase N` references from comments. Keep substantive technical comments but strip the phase labels.

**Requirement ID references (BUG-04, REUN-01, SESS-01, etc.):**
- Issue: ~25 references to requirement IDs like `BUG-04`, `REUN-01/REUN-02`, `SESS-01/SESS-02`, `DATA-01/DATA-04`, `RECON-01` through `RECON-06`, `PARITY-01/PARITY-02`, `LOG-03`. These reference internal planning documents that won't exist in the merged codebase.
- Files: `interactive_gym/server/app.py`, `interactive_gym/server/game_manager.py`, `interactive_gym/server/remote_game.py`, `interactive_gym/server/pyodide_game_coordinator.py`, `interactive_gym/server/match_logger.py`, `interactive_gym/scenes/gym_scene.py`
- Fix approach: Remove requirement ID labels from comments. Keep the descriptive text.

## Structural Issues

**`app.py` is 3020 lines -- far too large:**
- Issue: The main Flask application file handles HTTP routes, SocketIO events, data saving, metrics aggregation, WebRTC signaling, P2P probe handling, entry screening callbacks, continuous monitoring callbacks, session management, disconnect handling, and server startup. This is a "god module."
- Files: `interactive_gym/server/app.py` (3020 lines)
- Impact: Extremely difficult to navigate, test, or modify safely. Any change risks unintended side effects.
- Fix approach: Extract into focused modules:
  - `interactive_gym/server/routes.py` -- HTTP routes (index, partner_disconnected)
  - `interactive_gym/server/socket_events.py` -- Core socket handlers (register, advance_scene, join_game, etc.)
  - `interactive_gym/server/data_handlers.py` -- Data emission/saving (data_emission, receive_remote_game_data, receive_episode_data, receive_multiplayer_metrics, _create_aggregated_metrics, _compare_hashes, _compare_actions)
  - `interactive_gym/server/webrtc_handlers.py` -- WebRTC/P2P probe/sync handlers
  - `interactive_gym/server/globals.py` -- Module-level state (CONFIG, STAGERS, GAME_MANAGERS, etc.)

**`pyodide_multiplayer_game.js` is 8152 lines:**
- Issue: The largest JS file in the codebase. Handles game loop, input handling, WebRTC, rollback, state sync, UI, data collection, and more.
- Files: `interactive_gym/server/static/js/pyodide_multiplayer_game.js` (8152 lines)
- Impact: Difficult to navigate and modify. Single-file architecture makes it hard to test individual components.
- Fix approach: Consider splitting into logical modules (game loop, WebRTC manager, input handler, state sync, UI). This is lower priority than the Python refactoring since JS is client-side.

**Module-level global state in `app.py`:**
- Issue: 15+ module-level global variables (`CONFIG`, `GENERIC_STAGER`, `STAGERS`, `SUBJECTS`, `GAME_MANAGERS`, `PYODIDE_COORDINATOR`, `GROUP_MANAGER`, `ADMIN_AGGREGATOR`, `MATCH_LOGGER`, `PROBE_COORDINATOR`, `SESSION_ID_TO_SUBJECT_ID`, `PARTICIPANT_SESSIONS`, `PARTICIPANT_TRACKER`, `PENDING_MULTIPLAYER_METRICS`, `LOADING_CLIENTS`, `PROCESSED_SUBJECT_NAMES`, `MAX_CONCURRENT_SESSIONS`, `SERVER_SESSION_ID`, `USER_LOCKS`). Many handlers declare `global` to modify these.
- Files: `interactive_gym/server/app.py` (lines 85-143)
- Impact: Hard to reason about state, impossible to unit test handlers in isolation, no clear ownership of state lifecycle.
- Fix approach: Wrap in an `AppState` class or similar container. Pass as dependency rather than relying on module globals.

**`constructors/` directory contains incomplete, non-functional code:**
- Issue: The `constructors/` directory has three files: `constructor.py` (base class with TODO saying "under active development and not functional yet"), `options.py`, and `text.py`. The base `Constructor.build()` method has a missing `self` parameter.
- Files:
  - `interactive_gym/scenes/constructors/constructor.py` (31 lines)
  - `interactive_gym/scenes/constructors/options.py` (84 lines)
  - `interactive_gym/scenes/constructors/text.py` (unknown)
- Impact: Dead code that advertises functionality that doesn't work.
- Fix approach: Either complete the implementation or remove the entire `constructors/` directory.

## Security Considerations

**Hard-coded Flask SECRET_KEY:**
- Risk: `app.config["SECRET_KEY"] = "secret!"` on line 191 of `app.py`. This is a well-known insecure default.
- Files: `interactive_gym/server/app.py` (line 191)
- Current mitigation: None.
- Recommendations: Generate a random secret key at startup or read from an environment variable.

**Admin login with hard-coded user check:**
- Risk: `load_user()` returns an `AdminUser` if `user_id == 'admin'`. The actual authentication is handled by Flask-Login but the user loading is simplistic.
- Files: `interactive_gym/server/app.py` (lines 215-219)
- Recommendations: Verify the admin password is properly configured and not hard-coded elsewhere.

## Fragile Areas

**`disconnect` handler complexity:**
- Files: `interactive_gym/server/app.py` (lines 2705-2934, ~230 lines)
- Why fragile: The disconnect handler must coordinate cleanup across 6+ data structures (`PYODIDE_COORDINATOR`, `GAME_MANAGERS`, `GROUP_MANAGER`, `PARTICIPANT_SESSIONS`, `STAGERS`, `LOADING_CLIENTS`). It has multiple code paths for Pyodide vs non-Pyodide games, active vs inactive games, and grace period handling.
- Safe modification: Always test with multiplayer disconnect scenarios. Ensure idempotent cleanup (call `cleanup_game` which is already idempotent).
- Test coverage: E2E tests exist in `tests/e2e/test_network_disruption.py` and `tests/e2e/test_lifecycle_stress.py`.

**Waitroom/matchmaker state transitions:**
- Files: `interactive_gym/server/game_manager.py` (methods: `_add_to_fifo_queue`, `_create_game_for_match`, `_probe_and_create_game`, `_on_probe_complete`)
- Why fragile: The matchmaker flow has several code paths (immediate match, deferred probe, probe success/failure) that modify `waitroom_participants`, `waiting_games`, `subject_games`, and `active_games`. Race conditions are mitigated by `waiting_games_lock` but the logic is complex.
- Safe modification: Always acquire `waiting_games_lock` before modifying matchmaking state. Test with concurrent participant arrivals.

## Test Coverage Gaps

**No unit tests for `app.py` socket handlers:**
- What's not tested: The 3020-line `app.py` has no unit tests. All testing relies on E2E tests.
- Files: `interactive_gym/server/app.py`
- Risk: Socket handler logic changes could break without detection. E2E tests are slow and flaky.
- Priority: Medium. The E2E tests provide some coverage, but unit tests would catch regressions faster.

**`RemoteGameV2` tick/reset logic untested:**
- What's not tested: The game loop logic in `RemoteGameV2.tick()` and `RemoteGameV2.reset()` has no unit tests.
- Files: `interactive_gym/server/remote_game.py` (lines 295-449)
- Risk: Action population, reward tracking, and episode boundary handling could break without detection.
- Priority: Low (most games use Pyodide path instead).

**Admin aggregator untested:**
- What's not tested: The 1482-line admin aggregator has no dedicated tests.
- Files: `interactive_gym/server/admin/aggregator.py`
- Risk: Dashboard data could be incorrect without detection.
- Priority: Low (admin dashboard is monitoring, not critical path).

## Dependencies at Risk

**`flatten_dict` package:**
- Risk: Small, infrequently maintained package used only for data flattening during CSV export.
- Impact: If abandoned, CSV data export breaks.
- Files: `interactive_gym/server/app.py` (line 14, used on lines 1204, 1295)
- Migration plan: Replace with a simple recursive flatten function (10-15 lines). The package is only used in two places.

---

*Concerns audit: 2026-02-07*
