# Codebase Structure

**Analysis Date:** 2025-01-16

## Directory Layout

```
interactive-gym/
├── interactive_gym/              # Main package
│   ├── configurations/           # Experiment and scene configuration classes
│   ├── scenes/                   # Scene types and Stager
│   │   └── constructors/         # HTML construction utilities for scenes
│   ├── server/                   # Flask app, game management, multiplayer coordination
│   │   └── static/               # Frontend assets
│   │       ├── js/               # JavaScript (game loops, rendering, Pyodide)
│   │       ├── templates/        # HTML templates
│   │       ├── lib/              # Third-party JS libraries
│   │       ├── assets/           # Game assets (sprites, models, images)
│   │       └── web_gl/           # Unity WebGL builds
│   ├── utils/                    # Shared utilities (typing, inference)
│   └── examples/                 # Example experiments
│       ├── cogrid/               # Overcooked-style games
│       ├── footsies/             # Fighting game examples
│       ├── mountain_car/         # Classic control example
│       └── slime_volleyball/     # Slime volleyball examples
├── docs/                         # Sphinx documentation
├── data/                         # Experiment data output (gitignored)
├── build/                        # Build artifacts
├── dist/                         # Distribution packages
└── .planning/                    # GSD planning documents
```

## Directory Purposes

**`interactive_gym/configurations/`:**
- Purpose: Define experiment-wide and scene-level configuration
- Contains: Builder-pattern configuration classes
- Key files:
  - `experiment_config.py`: Top-level `ExperimentConfig` class
  - `remote_config.py`: Legacy `RemoteConfig` (environment, policies, rendering)
  - `configuration_constants.py`: Enums for PolicyTypes, InputModes, ActionSettings
  - `object_contexts.py`: Rendering context objects

**`interactive_gym/scenes/`:**
- Purpose: Scene abstractions for experiment stages
- Contains: Scene base class, specific scene types, Stager
- Key files:
  - `scene.py`: Base `Scene` class, `SceneWrapper`, `RandomizeOrder`
  - `static_scene.py`: `StaticScene`, `StartScene`, `EndScene`, survey scenes
  - `gym_scene.py`: `GymScene` for interactive environments
  - `unity_scene.py`: `UnityScene` for Unity WebGL games
  - `stager.py`: `Stager` class managing scene sequence
  - `utils.py`: `NotProvided` sentinel, helper functions

**`interactive_gym/server/`:**
- Purpose: Flask server, WebSocket handlers, game orchestration
- Contains: Server entry point, game management, multiplayer coordination
- Key files:
  - `app.py`: Flask app, SocketIO routes, global state (`STAGERS`, `GAME_MANAGERS`)
  - `game_manager.py`: `GameManager` - per-scene game lifecycle
  - `remote_game.py`: `RemoteGameV2` - single game instance
  - `pyodide_game_coordinator.py`: `PyodideGameCoordinator` - multiplayer sync
  - `server_game_runner.py`: `ServerGameRunner` - server-authoritative game loop
  - `player_pairing_manager.py`: `PlayerGroupManager` - track player groups
  - `callback.py`: `GameCallback` interface for game lifecycle hooks
  - `utils.py`: Thread-safe data structures, constants

**`interactive_gym/server/static/js/`:**
- Purpose: Client-side JavaScript for game execution and rendering
- Contains: Game loop implementations, Phaser graphics, Pyodide integration
- Key files:
  - `index.js`: Main client entry, SocketIO handlers, scene switching
  - `pyodide_remote_game.js`: Single-player Pyodide game loop
  - `pyodide_multiplayer_game.js`: Multiplayer Pyodide with GGPO-style sync
  - `phaser_gym_graphics.js`: Phaser-based game rendering
  - `unity_utils.js`: Unity WebGL integration
  - `onnx_inference.js`: ONNX model inference in browser
  - `seeded_random.js`: Deterministic RNG for multiplayer

**`interactive_gym/utils/`:**
- Purpose: Shared utility modules
- Contains: Type definitions, inference utilities
- Key files:
  - `typing.py`: Type aliases (`SubjectID`, `GameID`, `SceneID`)
  - `inference_utils.py`: Policy inference helpers
  - `onnx_inference_utils.py`: ONNX runtime utilities

**`interactive_gym/examples/`:**
- Purpose: Example experiments demonstrating framework usage
- Contains: Complete experiment scripts with scenes and configurations
- Key files:
  - `slime_volleyball/slimevb_human_human.py`: 2-player multiplayer example
  - `cogrid/overcooked_human_human_multiplayer.py`: Overcooked multiplayer
  - `cogrid/overcooked_human_ai_client_side.py`: Human-AI Pyodide example
  - `mountain_car/mountain_car_experiment.py`: Server-side rendering example

## Key File Locations

**Entry Points:**
- `interactive_gym/server/app.py`: Flask server entry via `app.run(config)`
- `interactive_gym/examples/**/*_experiment.py` or `*_human_human.py`: Experiment scripts

**Configuration:**
- `interactive_gym/configurations/experiment_config.py`: `ExperimentConfig`
- `interactive_gym/configurations/configuration_constants.py`: Constants/enums
- `interactive_gym/scenes/gym_scene.py`: `GymScene` with builder methods

**Core Logic:**
- `interactive_gym/server/game_manager.py`: Game lifecycle management
- `interactive_gym/server/pyodide_game_coordinator.py`: Multiplayer coordination
- `interactive_gym/scenes/stager.py`: Scene sequencing

**Testing:**
- No test directory present (tests not yet implemented)

## Naming Conventions

**Files:**
- `snake_case.py` for Python modules
- `camelCase.js` or `snake_case.js` for JavaScript
- Class-per-file not enforced; related classes grouped in modules

**Directories:**
- `snake_case` for all directories
- Plural for collections (`scenes`, `examples`, `configurations`)

**Classes:**
- `PascalCase` for classes (e.g., `GymScene`, `GameManager`)
- Suffix with purpose (e.g., `RemoteConfig`, `ServerGameRunner`)

**Variables/Functions:**
- `snake_case` for Python functions and variables
- `camelCase` for JavaScript functions and variables
- UPPER_CASE for module-level constants

## Where to Add New Code

**New Scene Type:**
- Primary code: `interactive_gym/scenes/` (create new `*_scene.py` or add to existing)
- Register in `interactive_gym/scenes/__init__.py`
- May need client handler in `interactive_gym/server/static/js/index.js`

**New Example Experiment:**
- Implementation: `interactive_gym/examples/{game_name}/`
- Include: `{game_name}_experiment.py` (entry point), environment code, scene definitions
- Assets: `interactive_gym/server/static/assets/{game_name}/`

**New Server Feature:**
- SocketIO handlers: `interactive_gym/server/app.py`
- Game logic: `interactive_gym/server/game_manager.py` or new module
- Multiplayer: `interactive_gym/server/pyodide_game_coordinator.py`

**New Client Feature:**
- JavaScript: `interactive_gym/server/static/js/` (new file or extend existing)
- Load in: `interactive_gym/server/static/templates/index.html`

**Utilities:**
- Shared Python: `interactive_gym/utils/`
- Server-specific: `interactive_gym/server/utils.py`
- Scene-specific: `interactive_gym/scenes/utils.py`

## Special Directories

**`data/`:**
- Purpose: Experiment output data (CSV files, JSON metadata)
- Generated: Yes, at runtime
- Committed: No (gitignored)

**`build/`:**
- Purpose: Python build artifacts, contains copy of package
- Generated: Yes, during `pip install -e .`
- Committed: Partially (check .gitignore)

**`dist/`:**
- Purpose: Distribution packages for PyPI
- Generated: Yes, during `python setup.py sdist`
- Committed: No

**`.planning/`:**
- Purpose: GSD planning and codebase analysis documents
- Generated: Yes, by GSD tools
- Committed: Yes

**`interactive_gym/server/static/web_gl/`:**
- Purpose: Unity WebGL builds for UnityScene games
- Generated: Externally (Unity build output)
- Committed: Yes (large binary files)

---

*Structure analysis: 2025-01-16*
