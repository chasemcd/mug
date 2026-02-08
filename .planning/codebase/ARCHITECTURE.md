# Architecture

**Analysis Date:** 2026-02-07

## Pattern Overview

**Overall:** Server-Driven Scene Orchestration with Dual Runtime Execution (Server-Side and Client-Side Pyodide)

**Key Characteristics:**
- Flask + Socket.IO real-time web server that orchestrates interactive experiments
- Scene-based flow controller (Stager) manages participant progression through experiment stages
- Dual game execution model: server-authoritative game loop OR client-side Pyodide (Python-in-browser) with P2P multiplayer
- Gymnasium (OpenAI Gym) environment interface is the universal abstraction for game environments
- Builder pattern used pervasively for configuration objects (method chaining with `NotProvided` sentinel)
- Module-level global state in `app.py` serves as the application's shared state (no DI container)

## Layers

**Configuration Layer:**
- Purpose: Define experiment structure, environment settings, hosting, policies, and multiplayer parameters
- Location: `interactive_gym/configurations/`
- Contains: `ExperimentConfig` (new API), `RemoteConfig` (legacy API), `configuration_constants.py`
- Depends on: `interactive_gym/scenes/stager.py` (ExperimentConfig references Stager)
- Used by: `interactive_gym/server/app.py` (loaded at startup via `run(config)`)

**Scene Layer:**
- Purpose: Define the stages of interaction participants experience (instructions, games, surveys, completion)
- Location: `interactive_gym/scenes/`
- Contains: Base `Scene`, `StaticScene` (instructions/surveys), `GymScene` (interactive game), `UnityScene` (WebGL games), `Stager` (scene sequencer), `SceneWrapper`/`RandomizeOrder`/`RepeatScene` (composition)
- Depends on: `flask_socketio` for scene activation/deactivation events
- Used by: `interactive_gym/server/app.py` (Stager drives scene progression), `interactive_gym/server/game_manager.py` (GymScene drives game creation)

**Server Layer:**
- Purpose: HTTP/WebSocket server handling participant connections, session management, game orchestration, and data collection
- Location: `interactive_gym/server/`
- Contains: Flask app (`app.py`), `GameManager` (per-scene game orchestration), `RemoteGameV2` (per-game state), `PyodideGameCoordinator` (multiplayer P2P coordination), `Matchmaker` (pluggable matchmaking), `PlayerGroupManager` (cross-scene group tracking), `ProbeCoordinator` (P2P RTT measurement), `MatchAssignmentLogger`, `ParticipantStateTracker`, admin dashboard, `ServerGameRunner` (server-authoritative real-time env)
- Depends on: Scene layer, Configuration layer, `eventlet` for cooperative multitasking, `flask`/`flask_socketio`
- Used by: Client-side JavaScript via Socket.IO events

**Client Layer:**
- Purpose: Browser-based participant interface with Phaser.js rendering, Pyodide Python runtime, WebRTC P2P, and Socket.IO communication
- Location: `interactive_gym/server/static/js/`, `interactive_gym/server/static/templates/`
- Contains: `index.js` (main entry), `socket_handlers.js`, `phaser_gym_graphics.js` (Phaser rendering), `pyodide_remote_game.js` (single-player Pyodide), `pyodide_multiplayer_game.js` (P2P multiplayer), `webrtc_manager.js`, `probe_connection.js` (P2P RTT measurement), `continuous_monitor.js`, `ui_utils.js`, `latency.js`
- Depends on: Phaser 3, Pyodide, Socket.IO client, ONNX Runtime Web, jQuery
- Used by: Participants via browser

**Admin Layer:**
- Purpose: Real-time experiment monitoring dashboard for researchers
- Location: `interactive_gym/server/admin/`
- Contains: Flask Blueprint (`__init__.py`), routes (`routes.py`), Socket.IO namespace (`namespace.py`), event aggregator (`aggregator.py`), HTML templates, static assets
- Depends on: Flask-Login, Server layer globals (PARTICIPANT_SESSIONS, GAME_MANAGERS, etc.)
- Used by: Researchers via `/admin/` route

**Utilities Layer:**
- Purpose: Shared helpers, type definitions, thread-safe data structures
- Location: `interactive_gym/utils/`, `interactive_gym/server/utils.py`
- Contains: `typing.py` (SubjectID, SceneID, etc.), `inference_utils.py`, `onnx_inference_utils.py`, `ThreadSafeDict`, `ThreadSafeSet`, `Available` sentinel
- Used by: All other layers

**Examples Layer:**
- Purpose: Reference implementations showing how to configure and run experiments
- Location: `interactive_gym/examples/`
- Contains: `cogrid/` (Overcooked-style grid environments), `slime_volleyball/`, `mountain_car/`, `footsies/` (Unity WebGL)
- Depends on: Configuration, Scene, and Server layers

## Data Flow

**Participant Connection and Scene Progression:**

1. Participant visits `/` or `/<subject_id>` -> `app.py` generates UUID if needed, creates `ParticipantSession` and builds participant-specific `Stager` from `GENERIC_STAGER`
2. Client loads `index.html`, establishes Socket.IO WebSocket connection
3. Client emits `register_subject` -> server ties socket ID to subject, sends `experiment_config` (entry screening, Pyodide config)
4. Client passes entry screening -> server calls `stager.start()` which activates the first scene (must be `StartScene`)
5. Client clicks advance -> emits `advance_scene` -> server calls `stager.advance()` which deactivates current scene and activates next
6. If next scene is `GymScene`, server creates `GameManager` for that scene ID (if not exists)
7. Client emits `join_game` -> server validates participant state (`ParticipantStateTracker`), adds to matchmaker queue
8. `Matchmaker.find_match()` decides when to form groups -> if match found, `GameManager._create_game_for_match()` creates `RemoteGameV2`, joins participants to Socket.IO room
9. For server-side games: `GameManager.run_server_game()` runs tick loop (env.step -> render -> emit state)
10. For Pyodide games: `PyodideGameCoordinator` coordinates P2P WebRTC connections, seed distribution, action broadcasting
11. Game ends -> `cleanup_game()` -> `PlayerGroupManager` records group -> participants advance to next scene
12. At `EndScene`, participant sees completion code or redirect URL

**Server-Side Game Tick Loop (Non-Pyodide):**

1. `GameManager.run_server_game()` calls `game.reset()` to initialize environment
2. Each tick: collect actions from queues (human via Socket.IO, bot via policy inference), call `env.step(actions)`
3. `render_server_game()` either calls `env_to_state_fn` (sprite-based) or `env.render('rgb_array')` + cv2 encode (image-based)
4. State emitted as `environment_state` to all players in the game room
5. On episode boundary: emit `game_reset`, wait for all players' `reset_complete`, then `game.reset()`
6. On game done: emit `end_game`, trigger callbacks, clean up game

**Pyodide Multiplayer P2P Flow:**

1. Both clients run Python environment locally in Pyodide WebAssembly
2. `PyodideGameCoordinator` assigns player IDs, distributes shared RNG seed
3. Clients establish WebRTC DataChannel connection (via `webrtc_manager.js`)
4. Actions exchanged directly P2P each frame; server coordinates but does not run environment
5. Optional: server-authoritative mode runs parallel environment on server (`ServerGameRunner`), broadcasts authoritative state periodically for reconciliation
6. GGPO-style input delay and rollback for smooth multiplayer experience

**State Management:**
- **Module-level globals in `app.py`:** `CONFIG`, `GENERIC_STAGER`, `STAGERS` (per-participant), `SUBJECTS`, `GAME_MANAGERS` (per-scene), `PYODIDE_COORDINATOR`, `GROUP_MANAGER`, `PARTICIPANT_SESSIONS`, `PARTICIPANT_TRACKER`, `SESSION_ID_TO_SUBJECT_ID`
- All shared state uses `ThreadSafeDict`/`ThreadSafeSet` from `interactive_gym/server/utils.py`
- Per-game state lives in `RemoteGameV2` instances (env, players, actions, rewards)
- Session persistence via `ParticipantSession` dataclass (supports page refresh recovery)
- Client-side state in `interactiveGymGlobals` JavaScript object, synced to server via `sync_globals`

## Key Abstractions

**Scene (and subclasses):**
- Purpose: Represents a single stage of participant interaction
- Examples: `interactive_gym/scenes/scene.py` (base), `interactive_gym/scenes/static_scene.py` (StartScene, EndScene, CompletionCodeScene, TextBox, MultipleChoice, etc.), `interactive_gym/scenes/gym_scene.py` (GymScene), `interactive_gym/scenes/unity_scene.py` (UnityScene)
- Pattern: Builder pattern via method chaining (`.scene()`, `.display()`, `.environment()`, `.rendering()`, `.policies()`, `.gameplay()`, `.multiplayer()`, `.runtime()`, etc.)

**Stager:**
- Purpose: Sequences scenes for a participant, manages progression
- Examples: `interactive_gym/scenes/stager.py`
- Pattern: Linear scene sequence with build/advance/resume; `build_instance()` deep-copies for each participant

**SceneWrapper (and subclasses):**
- Purpose: Composable scene modifiers for randomization and repetition
- Examples: `interactive_gym/scenes/scene.py` (SceneWrapper, RandomizeOrder, RepeatScene)
- Pattern: Decorator/Composite pattern; wraps scenes, transforms them on `build()`

**GameManager:**
- Purpose: Manages all game instances for a single GymScene across all participants
- Examples: `interactive_gym/server/game_manager.py`
- Pattern: Owns matchmaking queue, game lifecycle, player routing; one per scene ID

**RemoteGameV2:**
- Purpose: Manages a single game instance (environment, players, tick loop, state)
- Examples: `interactive_gym/server/remote_game.py`
- Pattern: State machine (SessionState: WAITING -> MATCHED -> VALIDATING -> PLAYING -> ENDED)

**Matchmaker:**
- Purpose: Pluggable strategy for grouping participants into games
- Examples: `interactive_gym/server/matchmaker.py` (abstract `Matchmaker`, `FIFOMatchmaker`)
- Pattern: Strategy pattern; `find_match(arriving, waiting, group_size)` returns matched list or None

**GameCallback:**
- Purpose: Lifecycle hooks for custom game logic
- Examples: `interactive_gym/server/callback.py` (GameCallback, MultiCallback)
- Pattern: Observer/hook pattern; on_episode_start, on_game_tick_end, on_game_end, etc.

**ExperimentConfig / RemoteConfig:**
- Purpose: Top-level experiment configuration
- Examples: `interactive_gym/configurations/experiment_config.py` (new), `interactive_gym/configurations/remote_config.py` (legacy)
- Pattern: Builder pattern with method chaining

**NotProvided Sentinel:**
- Purpose: Distinguish "not provided" from None in builder methods
- Examples: `interactive_gym/scenes/utils.py`
- Pattern: Singleton sentinel (adapted from RLlib)

## Entry Points

**Server Start:**
- Location: `interactive_gym/server/app.py::run(config)`
- Triggers: Called from example scripts (e.g., `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer.py`)
- Responsibilities: Initializes global state (CONFIG, GENERIC_STAGER, PYODIDE_COORDINATOR, GROUP_MANAGER, PROBE_COORDINATOR, ADMIN_AGGREGATOR), registers admin namespace, starts Flask-SocketIO server

**HTTP Entry:**
- Location: `interactive_gym/server/app.py` routes `/` and `/<subject_id>`
- Triggers: Browser navigation
- Responsibilities: Creates participant session, builds stager, renders `index.html`

**WebSocket Entry:**
- Location: `interactive_gym/server/app.py` Socket.IO event handlers
- Triggers: Client-side JavaScript Socket.IO events
- Key events: `register_subject`, `advance_scene`, `join_game`, `leave_game`, `send_pressed_keys`, `reset_complete`, `ping`, `static_scene_data_emission`, `emit_remote_game_data`, `pyodide_loading_start`/`complete`, `sync_globals`, `request_current_scene`, `client_callback`

**Client Entry:**
- Location: `interactive_gym/server/static/js/index.js`
- Triggers: Page load in browser
- Responsibilities: Establishes Socket.IO connection, registers subject, handles scene activation/deactivation, manages game rendering via Phaser, runs Pyodide for client-side games

## Error Handling

**Strategy:** Defensive logging with graceful degradation; exceptions caught and logged at boundaries; participant state machine prevents invalid transitions

**Patterns:**
- `ParticipantStateTracker` validates state transitions (IDLE -> IN_WAITROOM -> IN_GAME -> GAME_ENDED) before routing, logs invalid transitions
- `SessionState` in `RemoteGameV2` validates game lifecycle transitions (WAITING -> MATCHED -> VALIDATING -> PLAYING -> ENDED)
- `GameManager.validate_subject_state()` detects and cleans up orphaned entries (stale game mappings)
- Socket.IO handlers use try/except with error emission to client (`join_game_error`, `waiting_room_error`, `create_game_failed`)
- `ThreadSafeDict.__delitem__` silently ignores missing keys
- Pyodide loading grace period (`LOADING_CLIENTS`) prevents false disconnection during WASM compilation

## Cross-Cutting Concerns

**Logging:** Python `logging` module throughout; `setup_logger()` in `app.py` creates file + console handler to `./iglog.log` at DEBUG level; most modules create their own `logger = logging.getLogger(__name__)` with console handlers

**Validation:** Builder methods use assertions and `NotProvided` sentinel; `ExperimentConfig.entry_screening()` validates device/browser/ping client-side before allowing experiment participation; `GymScene.multiplayer()` cross-validates parameter combinations

**Authentication:** Admin dashboard uses Flask-Login with single hardcoded user (`AdminUser`); password from `ADMIN_PASSWORD` env var (default `admin123`); no participant authentication (UUID-based identification)

**Concurrency:** `eventlet` for cooperative multitasking (green threads); `ThreadSafeDict`/`ThreadSafeSet` for shared state; per-user locks in `SUBJECTS` dict; `waiting_games_lock` semaphore in `GameManager`; `threading.Lock` in `PyodideGameCoordinator` and `PlayerGroupManager`

**Session Persistence:** `ParticipantSession` dataclass tracks stager state, socket ID, connection status; enables page refresh recovery via `stager.resume()`

**Data Collection:** Static scene data saved to CSV in `data/{experiment_id}/{scene_id}/`; game data saved via msgpack-encoded emissions; match assignment logs in `data/match_logs/`; completion codes in `data/{experiment_id}/completion_codes/`; console logs optionally saved via admin aggregator

---

*Architecture analysis: 2026-02-07*
