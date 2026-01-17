# Codebase Concerns

**Analysis Date:** 2026-01-16

## Tech Debt

**Duplicate Code in Environment Initializations:**
- Issue: 13 nearly-identical environment initialization files (~750 lines each) exist in the examples directory
- Files: `interactive_gym/examples/cogrid/environments/cramped_room_environment_initialization.py`, `interactive_gym/examples/cogrid/environments/counter_circuit_environment_initialization.py`, and 11 other similar files
- Impact: Any bug fix or feature must be replicated across all files; high maintenance burden
- Fix approach: Extract shared rendering/initialization logic into a base class or shared module, parameterize environment-specific differences

**Commented-Out Session Validation:**
- Issue: Session validation code is disabled throughout `app.py` with `# if not is_valid_session(...)` blocks
- Files: `interactive_gym/server/app.py` (lines 411, 472-475, 562-565, 579)
- Impact: Session validation not enforced; potential for stale or invalid session handling
- Fix approach: Either fully implement and enable session validation or remove dead code

**Duplicate Class Definitions (RemoteGame vs RemoteGameV2):**
- Issue: Both `RemoteGame` and `RemoteGameV2` classes exist with largely duplicated logic (~350 lines each)
- Files: `interactive_gym/server/remote_game.py` (lines 34-375 for V2, lines 377-713 for legacy)
- Impact: Maintenance burden; changes must be made in both places
- Fix approach: Deprecate and remove `RemoteGame`, migrate all usages to `RemoteGameV2`

**Hardcoded Log File Path:**
- Issue: Logger writes to hardcoded path `./iglog.log`
- Files: `interactive_gym/server/app.py` (line 74)
- Impact: Log file location cannot be configured; may conflict in production deployments
- Fix approach: Make log path configurable via `RemoteConfig` or environment variable

**Circular Import Workarounds:**
- Issue: Several `# TODO(chase): add callback typehint but need to avoid circular import` comments indicate type hints are missing to avoid circular imports
- Files: `interactive_gym/configurations/remote_config.py` (lines 44, 229), `interactive_gym/scenes/gym_scene.py` (lines 92, 323)
- Impact: Poor IDE support; harder to understand API contracts
- Fix approach: Refactor to break circular dependencies or use `TYPE_CHECKING` guards with forward references

**Unreachable Code in ONNX Utils:**
- Issue: Code after `return action` is unreachable
- Files: `interactive_gym/utils/onnx_inference_utils.py` (lines 57-73)
- Impact: Dead code clutters the module
- Fix approach: Remove the unreachable code block

## Known Bugs

**Static Scene Constructor Mismatch:**
- Symptoms: `OptionBoxes` constructor takes `scene_id` and `experiment_config` but parent `StaticScene` does not accept these
- Files: `interactive_gym/scenes/static_scene.py` (lines 188-194)
- Trigger: Instantiating `OptionBoxes` with old API
- Workaround: May work if parent ignores extra args, but likely causes runtime errors

**Duplicate Import Statements:**
- Symptoms: `import os` appears twice; `flask_socketio` imported twice
- Files: `interactive_gym/server/app.py` (lines 6, 13), `interactive_gym/server/game_manager.py` (lines 21, 36)
- Trigger: Always present; minor issue
- Workaround: None needed, Python handles it

## Security Considerations

**Dynamic Code Execution:**
- Risk: `ServerGameRunner` uses `exec()` to run environment initialization code from scene configuration
- Files: `interactive_gym/server/server_game_runner.py` (lines 139-150)
- Current mitigation: Code comes from developer-defined scene configurations, not user input
- Recommendations: Document that environment_initialization_code must be trusted; consider sandboxing if user-submitted code ever supported

**CORS Wildcard:**
- Risk: SocketIO configured with `cors_allowed_origins="*"` allows connections from any origin
- Files: `interactive_gym/server/app.py` (line 139)
- Current mitigation: None
- Recommendations: Restrict to specific origins in production; make configurable via `RemoteConfig`

**Session ID Exposed:**
- Risk: Server session ID sent to client via `server_session_id` event
- Files: `interactive_gym/server/app.py` (lines 241-245)
- Current mitigation: Used for session validation (currently disabled)
- Recommendations: If session validation is re-enabled, ensure session IDs are properly cryptographically random (currently uses `secrets.token_urlsafe(16)` which is acceptable)

## Performance Bottlenecks

**Large Files (app.py):**
- Problem: `app.py` is 1214 lines with mixed concerns (routing, socket handlers, business logic)
- Files: `interactive_gym/server/app.py`
- Cause: Monolithic file handles all Flask and SocketIO logic
- Improvement path: Split into separate modules (routes.py, socket_handlers.py, session_manager.py)

**State Serialization in Multiplayer:**
- Problem: Full environment state serialized and broadcast every N frames
- Files: `interactive_gym/server/server_game_runner.py` (lines 495-572)
- Cause: `get_authoritative_state()` serializes entire env state to JSON
- Improvement path: Implement delta updates; only send changed state; use msgpack for smaller payloads

**Pandas DataFrame Creation on Every Data Save:**
- Problem: Creates new DataFrame on each `static_scene_data_emission` and `emit_remote_game_data` call
- Files: `interactive_gym/server/app.py` (lines 745-756, 776-796)
- Cause: Converting single data point to DataFrame each time
- Improvement path: Batch writes; use CSV append instead of full DataFrame creation

## Fragile Areas

**Game Manager Disconnect Handling:**
- Files: `interactive_gym/server/app.py` (lines 1036-1166), `interactive_gym/server/game_manager.py` (lines 482-582)
- Why fragile: Complex state machine logic across multiple data structures (SUBJECTS, STAGERS, GAME_MANAGERS, GROUP_MANAGER, PYODIDE_COORDINATOR)
- Safe modification: Add comprehensive logging; test all disconnect scenarios (host disconnect, client disconnect, during waiting room, during game)
- Test coverage: No automated tests detected

**Input Buffer Pruning (GGPO):**
- Files: `interactive_gym/server/server_game_runner.py` (lines 353-362)
- Why fragile: Timing-sensitive; incorrect pruning could lose player inputs
- Safe modification: Add metrics for buffer size; log when inputs are dropped
- Test coverage: No automated tests detected

**Session Restoration Logic:**
- Files: `interactive_gym/server/app.py` (lines 201-298)
- Why fragile: Complex merging of client and server globals; stager state restoration
- Safe modification: Add unit tests for session restoration paths
- Test coverage: No automated tests detected

## Scaling Limits

**In-Memory Session Storage:**
- Current capacity: All session data stored in Python dicts (STAGERS, SUBJECTS, PARTICIPANT_SESSIONS, etc.)
- Limit: Single server memory; no horizontal scaling
- Scaling path: Move to Redis/external session store; implement sticky sessions or shared state

**Single-Threaded Game Loops:**
- Current capacity: One game loop per RemoteGame using eventlet greenlets
- Limit: CPU-bound environments will block other games
- Scaling path: Move game execution to worker processes; use multiprocessing

**Hardcoded Max Games:**
- Current capacity: `max_games = 1000` in PyodideGameCoordinator
- Limit: Arbitrary limit; may need adjustment
- Scaling path: Make configurable; implement game eviction for stale games

## Dependencies at Risk

**Eventlet Compatibility:**
- Risk: Eventlet has known compatibility issues with newer Python async features
- Impact: May limit Python version upgrades; some libraries incompatible
- Migration plan: Consider migrating to gevent or native asyncio

**Pyodide Version Pinning:**
- Risk: Pyodide version locked via client-side CDN URLs
- Impact: Difficult to track which version is in use; security updates may be missed
- Migration plan: Pin Pyodide version explicitly; implement version checking

## Missing Critical Features

**No Automated Tests:**
- Problem: No test files found in repository (`test_*.py`, `*_test.py`, `*.spec.*`)
- Blocks: Confident refactoring; CI/CD quality gates; regression prevention

**No Rate Limiting:**
- Problem: Socket events have no rate limiting
- Blocks: Production deployment without DDoS protection
- Files: `interactive_gym/server/app.py` (all `@socketio.on` handlers)

**Incomplete Data Tracking:**
- Problem: TODO comments indicate data tracking was disabled and needs reimplementation
- Files: `interactive_gym/server/app.py` (lines 601-614)
- Blocks: Analytics; participant monitoring during experiments

## Test Coverage Gaps

**Server Components:**
- What's not tested: All Flask routes, SocketIO handlers, GameManager, RemoteGame
- Files: `interactive_gym/server/*.py`
- Risk: Regressions undetected; multiplayer sync bugs
- Priority: High

**Scene Logic:**
- What's not tested: Scene transitions, Stager state machine, scene callbacks
- Files: `interactive_gym/scenes/*.py`
- Risk: Experiment flow breaks
- Priority: High

**Pyodide Multiplayer Sync:**
- What's not tested: GGPO rollback, state hash verification, host migration
- Files: `interactive_gym/server/pyodide_game_coordinator.py`, `interactive_gym/server/server_game_runner.py`
- Risk: Desync bugs in production
- Priority: High

**Client-Side JavaScript:**
- What's not tested: `pyodide_multiplayer_game.js` (~2500 lines), socket handlers, game rendering
- Files: `interactive_gym/server/static/js/*.js`
- Risk: Browser-specific bugs; state management issues
- Priority: Medium

---

*Concerns audit: 2026-01-16*
