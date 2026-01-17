# Architecture

**Analysis Date:** 2025-01-16

## Pattern Overview

**Overall:** Scene-based Experiment Framework with Real-time Multiplayer Support

**Key Characteristics:**
- Flask + SocketIO server orchestrating multi-stage experiments via Scenes
- Client-side game execution via Pyodide (Python in browser) or server-side execution
- Support for single-player, human-AI, and human-human multiplayer modes
- WebSocket-based real-time communication for game state synchronization

## Layers

**Configuration Layer:**
- Purpose: Define experiment and scene parameters through fluent builder APIs
- Location: `interactive_gym/configurations/`
- Contains: `ExperimentConfig`, `RemoteConfig`, configuration constants
- Depends on: Nothing (pure configuration)
- Used by: Server, Scenes, GameManager

**Scene Layer:**
- Purpose: Define discrete stages of participant interaction (instructions, games, surveys)
- Location: `interactive_gym/scenes/`
- Contains: `Scene`, `StaticScene`, `GymScene`, `UnityScene`, `Stager`
- Depends on: Configuration Layer
- Used by: Server Layer, Stager

**Server Layer:**
- Purpose: Handle HTTP/WebSocket routing, game coordination, session management
- Location: `interactive_gym/server/`
- Contains: Flask app, SocketIO handlers, GameManager, PyodideGameCoordinator
- Depends on: Configuration Layer, Scene Layer
- Used by: Entry point (experiments)

**Client Layer (Frontend):**
- Purpose: Render game state, capture user input, run Pyodide environments
- Location: `interactive_gym/server/static/js/`
- Contains: JavaScript files for game rendering (Phaser), Pyodide game loops
- Depends on: Server Layer (via WebSocket)
- Used by: Browser clients

## Data Flow

**Experiment Initialization:**

1. Entry script creates `ExperimentConfig` with `Stager` containing `Scene` sequence
2. `app.run(config)` initializes Flask server with global `GENERIC_STAGER`
3. Participant connects, gets unique UUID, Flask creates per-participant `Stager` instance
4. First scene (StartScene) activates, emits `activate_scene` to client

**Single-Player Pyodide Game Flow:**

1. Participant advances to `GymScene`, `GameManager` created for scene
2. Client initializes Pyodide, runs `environment_initialization_code`
3. Client game loop: capture input -> step environment -> render state
4. Episode ends, client emits data, advances scene

**Multiplayer Pyodide Game Flow (Server-Authoritative):**

1. Multiple participants enter `GymScene`, join waitroom via `add_subject_to_game`
2. When N players ready, `PyodideGameCoordinator.create_game()` initializes `ServerGameRunner`
3. Server broadcasts shared RNG seed, host election, `pyodide_game_ready`
4. Each client starts Pyodide environment with same seed
5. Server runs parallel environment at target FPS, steps in real-time
6. Clients send actions via `pyodide_player_action`, server relays to all
7. Server periodically broadcasts authoritative state via `server_state_broadcast`
8. Clients use GGPO-style input delay + rollback for smooth prediction

**State Management:**
- Server: `STAGERS` (per-participant), `GAME_MANAGERS` (per-scene), `PARTICIPANT_SESSIONS` (for reconnection)
- Client: `interactiveGymGlobals` object synchronized with server via `sync_globals`
- Multiplayer: `PyodideGameCoordinator.games` tracks active games, player mappings

## Key Abstractions

**Scene:**
- Purpose: Single stage of experiment (instructions, game, survey)
- Examples: `interactive_gym/scenes/scene.py`, `interactive_gym/scenes/gym_scene.py`, `interactive_gym/scenes/static_scene.py`
- Pattern: Builder pattern with `.scene()`, `.display()`, `.gameplay()` methods

**Stager:**
- Purpose: Sequence of Scenes forming complete experiment flow
- Examples: `interactive_gym/scenes/stager.py`
- Pattern: Iterator over scenes with `start()`, `advance()`, `resume()` for state management

**GymScene:**
- Purpose: Interactive game scene with Gymnasium-compatible environment
- Examples: `interactive_gym/scenes/gym_scene.py`
- Pattern: Configures environment, rendering, policies, multiplayer settings

**GameManager:**
- Purpose: Per-scene game lifecycle (waitroom, player matching, game loop)
- Examples: `interactive_gym/server/game_manager.py`
- Pattern: Factory for `RemoteGameV2` instances, manages player queues

**RemoteGameV2:**
- Purpose: Single game instance with players, environment, tick loop
- Examples: `interactive_gym/server/remote_game.py`
- Pattern: State machine (Inactive -> Active -> Reset -> Done)

**PyodideGameCoordinator:**
- Purpose: Coordinate multiplayer Pyodide games (action relay, state sync)
- Examples: `interactive_gym/server/pyodide_game_coordinator.py`
- Pattern: Mediator for player actions, host election, desync detection

**ServerGameRunner:**
- Purpose: Server-side parallel environment for authoritative multiplayer
- Examples: `interactive_gym/server/server_game_runner.py`
- Pattern: Real-time game loop with input buffering and state broadcast

## Entry Points

**Experiment Scripts:**
- Location: `interactive_gym/examples/*/` (e.g., `slimevb_human_human.py`)
- Triggers: Direct execution (`python script.py`)
- Responsibilities: Configure experiment, define scenes, call `app.run()`

**Flask App:**
- Location: `interactive_gym/server/app.py`
- Triggers: `app.run(config)` from experiment script
- Responsibilities: HTTP routes, SocketIO event handlers, global state

**Client Entry:**
- Location: `interactive_gym/server/static/templates/index.html` (loads `index.js`)
- Triggers: Browser navigation to `/<subject_id>`
- Responsibilities: Initialize SocketIO, scene rendering, input capture

## Error Handling

**Strategy:** Log and recover where possible; disconnect cleanup on critical failures

**Patterns:**
- Server wraps game operations in try/except with logging
- Client disconnect triggers `on_disconnect` handler with session persistence
- Game state saved to `PARTICIPANT_SESSIONS` for reconnection support
- Multiplayer desync detected via state hash comparison, triggers resync

## Cross-Cutting Concerns

**Logging:** Python `logging` module to `iglog.log` with console handler; DEBUG level default

**Validation:** Assertions in builder methods (e.g., `assert num_episodes >= 1`)

**Authentication:** Session-based via Flask session; `SESSION_ID_TO_SUBJECT_ID` mapping

**Thread Safety:** `utils.ThreadSafeDict` and `utils.ThreadSafeSet` for global state; `threading.Lock` for complex operations

**Data Persistence:** Experiment data saved to `data/{scene_id}/{subject_id}.csv` and `*_globals.json`

---

*Architecture analysis: 2025-01-16*
