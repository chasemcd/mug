# Technology Stack

**Analysis Date:** 2025-01-16

## Languages

**Primary:**
- Python 3.x - Server-side, environment logic, game coordination
- JavaScript (ES6+) - Client-side browser rendering and game loop

**Secondary:**
- HTML/CSS - Web UI templates and styling
- JSON - Configuration and data serialization

## Runtime

**Environment:**
- Python 3.x (no specific version pinned in config files)
- Browser JavaScript with Pyodide (Python in WebAssembly)

**Package Manager:**
- pip (via setuptools)
- Lockfile: Not present (uses requirements.txt)

## Frameworks

**Core:**
- Flask 2.x - Web server framework
- Flask-SocketIO - Real-time WebSocket communication
- Gymnasium - Reinforcement learning environment interface
- Pyodide - Python runtime in browser (client-side execution)

**Graphics:**
- Phaser.js - Browser-based game rendering (`interactive_gym/server/static/lib/`)

**Testing:**
- Not configured - no test framework in dependencies

**Build/Dev:**
- setuptools - Package building
- wheel - Distribution format

## Key Dependencies

**Critical (from `requirements.txt` and `setup.py`):**
- `gymnasium` - RL environment API (Gym-style environments)
- `numpy` - Numerical operations (core dependency)
- `flask` - Web server
- `flask_socketio` - WebSocket communication
- `eventlet` - Async networking (cooperative multithreading)
- `msgpack` - Binary serialization for game state

**Infrastructure:**
- `pandas` - Data export/manipulation (CSV saving)
- `flatten_dict` - Nested dict flattening for data logging

**Optional:**
- `onnxruntime` - ONNX model inference for AI policies (see `interactive_gym/utils/onnx_inference_utils.py`)
- `cv2` (OpenCV) - Image encoding when using rgb_array rendering (see `interactive_gym/server/game_manager.py`)

## Configuration

**Environment:**
- No `.env` file usage detected
- Configuration via Python classes: `ExperimentConfig`, `RemoteConfig`
- Key config files:
  - `interactive_gym/configurations/experiment_config.py` - Experiment-level config
  - `interactive_gym/configurations/remote_config.py` - Server and gameplay config

**Build:**
- `pyproject.toml` - Build system config (setuptools backend)
- `setup.py` - Package metadata and dependencies
- `MANIFEST.in` - Source distribution includes

## Platform Requirements

**Development:**
- Python 3.x
- pip for dependency installation
- Browser with WebSocket support for testing

**Production:**
- Flask/eventlet WSGI server
- Optional nginx reverse proxy (config at `interactive_gym/configurations/interactive-gym-nginx.conf`)
- WebSocket-capable hosting

## Client-Side Stack

**JavaScript Libraries (in `interactive_gym/server/static/`):**
- Phaser.js - 2D game rendering (`lib/phaser.min.js`)
- Socket.IO client - WebSocket communication
- msgpack.js - Binary serialization (`js/msgpack.min.js`)
- Pyodide - Python in browser (loaded from CDN or bundled)

**Key Client JS Files:**
- `js/index.js` - Main entry, scene management
- `js/phaser_gym_graphics.js` - Game rendering
- `js/pyodide_multiplayer_game.js` - P2P multiplayer game loop
- `js/pyodide_remote_game.js` - Single-player Pyodide games

## Documentation Stack

**ReadTheDocs (from `docs/requirements.txt`):**
- `sphinx-rtd-theme==2.0.0`
- `sphinx-book-theme`
- `sphinx-copybutton`

---

*Stack analysis: 2025-01-16*
