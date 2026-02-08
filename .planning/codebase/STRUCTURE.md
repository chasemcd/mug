# Codebase Structure

**Analysis Date:** 2026-02-07

## Directory Layout

```
interactive-gym/
├── interactive_gym/                    # Main Python package
│   ├── __init__.py                     # Empty
│   ├── configurations/                 # Experiment and game configuration classes
│   │   ├── __init__.py                 # Empty
│   │   ├── configuration_constants.py  # Frozen dataclass constants (InputModes, PolicyTypes, ActionSettings)
│   │   ├── experiment_config.py        # ExperimentConfig class (new builder-pattern API)
│   │   ├── object_contexts.py          # Object context helpers
│   │   ├── remote_config.py            # RemoteConfig class (legacy flat config)
│   │   └── render_configs.py           # Rendering configuration helpers
│   ├── examples/                       # Reference experiment implementations
│   │   ├── cogrid/                     # Overcooked-style grid world experiments
│   │   │   ├── assets/                 # Sprite images for Overcooked rendering
│   │   │   ├── environments/           # Pyodide environment initialization code (Python strings)
│   │   │   ├── html_pages/             # HTML content for scene bodies
│   │   │   ├── policies/               # Pre-trained policy files (ONNX models)
│   │   │   ├── pyodide_overcooked/     # Client-side Pyodide helper code
│   │   │   ├── scenes/                 # Scene configuration modules
│   │   │   ├── overcooked_human_ai_client_side.py       # Human vs AI (Pyodide)
│   │   │   ├── overcooked_human_human_multiplayer.py     # Human vs Human P2P multiplayer
│   │   │   ├── overcooked_controllable_demo.py           # Controllable AI demo
│   │   │   └── overcooked_utils.py                       # Shared utilities
│   │   ├── footsies/                   # Unity WebGL fighting game example
│   │   │   ├── static/                 # Footsies-specific static assets
│   │   │   ├── footsies_experiment.py  # Main experiment runner
│   │   │   ├── footsies_scene.py       # Scene definitions
│   │   │   └── scenes.py               # Scene configurations
│   │   ├── mountain_car/               # Mountain Car RGB environment example
│   │   │   ├── mountain_car_experiment.py
│   │   │   └── mountain_car_rgb_env.py
│   │   └── slime_volleyball/           # Slime Volleyball game example
│   │       ├── policies/               # Pre-trained models
│   │       ├── slimevb_env.py          # Environment wrapper
│   │       ├── slimevb_boost_env.py    # Boosted variant
│   │       ├── slimevb_human_human.py  # Human vs Human
│   │       ├── human_ai_pyodide_boost.py # Pyodide-based
│   │       └── slime_volleyball_utils.py
│   ├── scenes/                         # Scene abstraction layer
│   │   ├── __init__.py                 # Empty
│   │   ├── constructors/               # HTML component constructors (WIP)
│   │   │   ├── constructor.py          # Base Constructor class
│   │   │   ├── options.py              # Options constructor
│   │   │   └── text.py                 # Text constructor
│   │   ├── gym_scene.py                # GymScene (interactive game scene, ~1000 lines)
│   │   ├── scene.py                    # Base Scene, SceneWrapper, RandomizeOrder, RepeatScene
│   │   ├── stager.py                   # Stager (scene sequencer)
│   │   ├── static_scene.py             # StaticScene, StartScene, EndScene, CompletionCodeScene,
│   │   │                               #   TextBox, MultipleChoice, OptionBoxes, ScalesAndTextBox, etc.
│   │   ├── unity_scene.py              # UnityScene (WebGL games)
│   │   └── utils.py                    # NotProvided sentinel
│   ├── server/                         # Flask server and game orchestration
│   │   ├── __init__.py                 # Empty
│   │   ├── admin/                      # Admin monitoring dashboard
│   │   │   ├── __init__.py             # Blueprint definition, AdminUser class
│   │   │   ├── aggregator.py           # AdminEventAggregator (collects dashboard state)
│   │   │   ├── namespace.py            # AdminNamespace (Socket.IO namespace for /admin)
│   │   │   ├── routes.py               # Flask routes (/admin/, /admin/login, /admin/logout)
│   │   │   ├── static/                 # Admin CSS/JS assets
│   │   │   └── templates/              # Admin HTML templates (dashboard.html, login.html)
│   │   ├── app.py                      # Main Flask app (~3020 lines) - routes, Socket.IO handlers,
│   │   │                               #   global state, run() entry point
│   │   ├── callback.py                 # GameCallback and MultiCallback (lifecycle hooks)
│   │   ├── game_manager.py             # GameManager (~1600 lines) - per-scene game orchestration,
│   │   │                               #   matchmaking, waitroom, game lifecycle
│   │   ├── match_logger.py             # MatchAssignmentLogger (JSONL match logs)
│   │   ├── matchmaker.py               # Matchmaker ABC, FIFOMatchmaker, MatchCandidate, GroupHistory
│   │   ├── participant_state.py        # ParticipantState enum, ParticipantStateTracker
│   │   ├── player_pairing_manager.py   # PlayerGroupManager, PlayerGroup (cross-scene group tracking)
│   │   ├── probe_coordinator.py        # ProbeCoordinator (WebRTC P2P RTT probes)
│   │   ├── pyodide_game_coordinator.py # PyodideGameCoordinator, PyodideGameState
│   │   ├── remote_game.py              # RemoteGame (legacy), RemoteGameV2, GameStatus, SessionState
│   │   ├── server_game_runner.py       # ServerGameRunner (server-authoritative real-time env)
│   │   ├── utils.py                    # ThreadSafeDict, ThreadSafeSet, GameExitStatus, Available
│   │   └── static/                     # Client-side web assets
│   │       ├── assets/                 # Game assets (sprites, models, instructions)
│   │       │   ├── footsies/           # Footsies game assets
│   │       │   ├── keys/               # Keyboard key images
│   │       │   ├── overcooked/         # Overcooked sprites, models, instructions
│   │       │   └── slime_volleyball/   # Slime Volleyball sprites and models
│   │       ├── js/                     # Client-side JavaScript modules
│   │       │   ├── index.js            # Main entry: Socket.IO setup, ProbeManager, event routing
│   │       │   ├── socket_handlers.js  # Socket.IO event handler registration
│   │       │   ├── phaser_gym_graphics.js  # Phaser 3 game rendering engine
│   │       │   ├── pyodide_remote_game.js  # Single-player Pyodide game runner
│   │       │   ├── pyodide_multiplayer_game.js # P2P multiplayer Pyodide game (GGPO rollback)
│   │       │   ├── webrtc_manager.js   # WebRTC DataChannel manager for P2P
│   │       │   ├── probe_connection.js # Lightweight WebRTC probe for RTT measurement
│   │       │   ├── continuous_monitor.js # Runtime ping/tab monitoring
│   │       │   ├── game_events.js      # Game event abstractions
│   │       │   ├── latency.js          # Latency measurement utilities
│   │       │   ├── ui_utils.js         # UI helper functions
│   │       │   ├── unity_utils.js      # Unity WebGL loader/lifecycle
│   │       │   ├── onnx_inference.js   # ONNX model inference in browser
│   │       │   ├── seeded_random.js    # Deterministic RNG for multiplayer
│   │       │   └── msgpack.min.js      # MessagePack library
│   │       ├── lib/                    # Third-party JavaScript libraries
│   │       ├── templates/              # Jinja2 HTML templates
│   │       │   ├── index.html          # Main experiment page template
│   │       │   ├── partner_disconnected.html
│   │       │   └── *.html              # Game-specific instruction/header templates
│   │       └── web_gl/                 # Unity WebGL builds
│   │           └── footsies_webgl_*/   # Footsies game builds
│   └── utils/                          # Shared Python utilities
│       ├── __init__.py                 # Empty
│       ├── inference_utils.py          # General inference helpers
│       ├── onnx_inference_utils.py     # ONNX model loading/inference
│       └── typing.py                   # Type aliases (SubjectID, SceneID, GameID, RoomID)
├── tests/                              # Test suite
│   ├── __init__.py
│   ├── conftest.py                     # Shared pytest fixtures
│   ├── e2e/                            # End-to-end tests (Playwright browser automation)
│   │   ├── __init__.py
│   │   ├── conftest.py                 # E2E fixtures (server management, browser contexts)
│   │   ├── test_data_comparison.py
│   │   ├── test_focus_loss_data_parity.py
│   │   ├── test_infrastructure.py
│   │   ├── test_latency_injection.py
│   │   ├── test_lifecycle_stress.py
│   │   ├── test_multi_participant.py
│   │   └── ...
│   ├── fixtures/                       # Test fixtures
│   │   ├── __init__.py
│   │   └── ...
│   └── unit/                           # Unit tests
│       ├── __init__.py
│       └── ...
├── scripts/                            # Utility scripts
│   └── validate_action_sequences.py    # Data validation tool
├── data/                               # Experiment output data (gitignored)
│   ├── console_logs/
│   ├── match_logs/
│   └── {experiment_id}/                # Per-experiment data directories
├── docs/                               # Sphinx documentation
│   ├── conf.py
│   ├── content/
│   └── _build/
├── build/                              # Python build artifacts
├── dist/                               # Python distribution artifacts
├── .planning/                          # GSD planning documents
├── setup.py                            # Package setup (interactive_gym v0.1.1)
├── pyproject.toml                      # Build system config
├── requirements.txt                    # Core dependencies
├── pytest.ini                          # Pytest configuration
├── .pre-commit-config.yaml             # Pre-commit hooks
├── .readthedocs.yaml                   # ReadTheDocs config
├── .gitignore
├── LICENSE                             # MIT-style license
└── README.rst                          # Project README
```

## Directory Purposes

**`interactive_gym/configurations/`:**
- Purpose: All configuration classes for experiments, environments, and rendering
- Contains: Builder-pattern config objects with method chaining
- Key files: `experiment_config.py` (new API), `remote_config.py` (legacy), `configuration_constants.py`

**`interactive_gym/scenes/`:**
- Purpose: Scene abstraction layer - the core "stage" concept of the experiment
- Contains: Base `Scene` class and all specializations (static, gym, unity), plus `Stager` for sequencing
- Key files: `gym_scene.py` (most complex, ~1000 lines), `static_scene.py` (many UI components), `stager.py`

**`interactive_gym/server/`:**
- Purpose: Flask web server, Socket.IO real-time communication, game orchestration
- Contains: Application entry point, game lifecycle management, matchmaking, P2P coordination, admin dashboard
- Key files: `app.py` (~3020 lines, monolithic), `game_manager.py` (~1600 lines)

**`interactive_gym/server/static/js/`:**
- Purpose: Client-side JavaScript for browser-based experiment interaction
- Contains: ES modules for rendering (Phaser), game execution (Pyodide), networking (Socket.IO, WebRTC)
- Key files: `index.js`, `pyodide_multiplayer_game.js`, `phaser_gym_graphics.js`

**`interactive_gym/server/admin/`:**
- Purpose: Real-time admin dashboard for monitoring active experiments
- Contains: Flask Blueprint, Socket.IO namespace, event aggregation
- Key files: `aggregator.py`, `routes.py`, `namespace.py`

**`interactive_gym/examples/`:**
- Purpose: Reference implementations demonstrating the framework's capabilities
- Contains: Complete experiment configurations for different game types
- Key files: `cogrid/overcooked_human_human_multiplayer.py` (P2P multiplayer example), `cogrid/overcooked_human_ai_client_side.py` (Pyodide example)

**`tests/`:**
- Purpose: Automated testing (unit + E2E with Playwright)
- Contains: Unit tests and end-to-end browser automation tests
- Key files: `e2e/conftest.py` (server fixtures), `e2e/test_multi_participant.py`

## Key File Locations

**Entry Points:**
- `interactive_gym/server/app.py::run(config)`: Server startup function
- `interactive_gym/server/static/js/index.js`: Client-side entry point
- `interactive_gym/server/static/templates/index.html`: Main HTML template
- `interactive_gym/examples/*/`: Example experiment scripts (each has a `if __name__ == "__main__"` block)

**Configuration:**
- `interactive_gym/configurations/experiment_config.py`: `ExperimentConfig` class (primary config API)
- `interactive_gym/configurations/remote_config.py`: `RemoteConfig` class (legacy config)
- `interactive_gym/configurations/configuration_constants.py`: Enum-like constants (`PolicyTypes.Human`, `InputModes.PressedKeys`, etc.)
- `setup.py`: Package metadata and dependencies
- `pytest.ini`: Test configuration
- `.pre-commit-config.yaml`: Pre-commit hooks (black, isort, flake8)

**Core Logic:**
- `interactive_gym/server/app.py`: All HTTP routes, Socket.IO event handlers, global state management
- `interactive_gym/server/game_manager.py`: Per-scene game orchestration, matchmaking, game lifecycle
- `interactive_gym/server/remote_game.py`: Per-game state management (`RemoteGameV2`), game tick loop
- `interactive_gym/server/pyodide_game_coordinator.py`: Multiplayer Pyodide game coordination
- `interactive_gym/server/matchmaker.py`: Matchmaking strategy abstraction
- `interactive_gym/scenes/gym_scene.py`: Interactive game scene configuration (~1000 lines)
- `interactive_gym/scenes/stager.py`: Scene sequencing and progression
- `interactive_gym/scenes/scene.py`: Base scene class, wrappers (RandomizeOrder, RepeatScene)

**Testing:**
- `tests/conftest.py`: Shared test fixtures
- `tests/e2e/conftest.py`: E2E test fixtures (server management)
- `tests/e2e/test_*.py`: End-to-end Playwright tests
- `tests/unit/`: Unit tests

## Naming Conventions

**Files:**
- Python: `snake_case.py` (e.g., `game_manager.py`, `remote_game.py`, `experiment_config.py`)
- JavaScript: `snake_case.js` (e.g., `pyodide_remote_game.js`, `phaser_gym_graphics.js`)
- HTML templates: `snake_case.html` (e.g., `index.html`, `partner_disconnected.html`)

**Directories:**
- Python packages: `snake_case` (e.g., `interactive_gym`, `configurations`, `scenes`)
- Asset directories: `snake_case` (e.g., `slime_volleyball`, `web_gl`)

**Classes:**
- PascalCase: `GameManager`, `RemoteGameV2`, `ExperimentConfig`, `GymScene`, `StaticScene`, `PyodideGameCoordinator`
- Frozen dataclass constants: `PolicyTypes`, `InputModes`, `ActionSettings`

**Functions/Methods:**
- snake_case: `add_subject_to_game()`, `run_server_game()`, `process_pressed_keys()`
- Builder methods: short verb phrases that return `self` (e.g., `.environment()`, `.rendering()`, `.multiplayer()`)

**Socket.IO Events:**
- snake_case: `register_subject`, `advance_scene`, `join_game`, `start_game`, `end_game`, `environment_state`

## Where to Add New Code

**New Scene Type:**
- Implementation: Create class in `interactive_gym/scenes/` extending `Scene` or `StaticScene`
- Follow pattern of `interactive_gym/scenes/gym_scene.py` or `interactive_gym/scenes/unity_scene.py`
- Add activation/deactivation logic, builder methods with `NotProvided` sentinel
- Client-side handling: Add case in `interactive_gym/server/static/js/index.js` Socket.IO handlers

**New Socket.IO Event Handler:**
- Add handler in `interactive_gym/server/app.py` using `@socketio.on("event_name")` decorator
- Get subject_id via `get_subject_id_from_session_id(flask.request.sid)`
- Client-side: Add emission/listener in `interactive_gym/server/static/js/index.js` or `socket_handlers.js`

**New Matchmaker Strategy:**
- Implementation: Create class in `interactive_gym/server/matchmaker.py` extending `Matchmaker`
- Implement `find_match(arriving, waiting, group_size)` -> returns matched `list[MatchCandidate]` or `None`
- Use via `GymScene.matchmaking(matchmaker=MyMatchmaker())`

**New Game Callback:**
- Implementation: Create class extending `GameCallback` in a new file or `interactive_gym/server/callback.py`
- Override desired hooks: `on_episode_start`, `on_game_tick_end`, `on_game_end`, etc.
- Attach via `GymScene.gameplay(callback=MyCallback())`

**New Example Experiment:**
- Create directory under `interactive_gym/examples/{name}/`
- Create main script that builds `ExperimentConfig` with `Stager` containing scenes
- Call `from interactive_gym.server import app; app.run(config)` to start
- Follow pattern of `interactive_gym/examples/cogrid/overcooked_human_human_multiplayer.py`

**New Admin Feature:**
- Routes: Add to `interactive_gym/server/admin/routes.py`
- Real-time data: Add to `interactive_gym/server/admin/aggregator.py` and `namespace.py`
- Templates: Add to `interactive_gym/server/admin/templates/`

**New Static Scene Component (survey element):**
- Add class in `interactive_gym/scenes/static_scene.py` extending `StaticScene`
- Generate HTML/JS in `_create_html*()` method
- Set `self.element_ids` for data collection
- Follow pattern of `TextBox`, `MultipleChoice`, `ScalesAndTextBox`

**New Utility:**
- Shared Python helpers: `interactive_gym/utils/`
- Server-specific helpers: `interactive_gym/server/utils.py`
- Type aliases: `interactive_gym/utils/typing.py`

## Special Directories

**`data/`:**
- Purpose: Experiment output data (CSV, JSON, JSONL logs)
- Generated: Yes (at runtime by the server)
- Committed: No (gitignored)

**`build/`:**
- Purpose: Python build artifacts (contains stale copy of library code)
- Generated: Yes (by `setup.py`)
- Committed: No (should be gitignored, but appears partially tracked)

**`dist/`:**
- Purpose: Python distribution packages
- Generated: Yes (by `setup.py bdist`)
- Committed: No

**`interactive_gym/server/static/web_gl/`:**
- Purpose: Pre-built Unity WebGL game binaries
- Generated: No (built externally, checked in)
- Committed: Yes (binary assets)

**`interactive_gym/server/static/assets/`:**
- Purpose: Game sprites, models (ONNX), instruction images
- Generated: No (created manually or by training pipelines)
- Committed: Yes

**`.planning/`:**
- Purpose: GSD planning and codebase analysis documents
- Generated: Yes (by GSD commands)
- Committed: Yes

---

*Structure analysis: 2026-02-07*
