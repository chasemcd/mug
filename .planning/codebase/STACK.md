# Technology Stack

**Analysis Date:** 2026-02-07

## Languages

**Primary:**
- Python 3.10+ - Server-side application, environment simulation, experiment orchestration
- JavaScript (ES Modules) - Client-side game rendering, WebRTC P2P, Pyodide game engine

**Secondary:**
- HTML/CSS - Jinja2 templates for experiment UI pages
- Bash - Build/deploy scripts (`update_pypi.sh`)

## Runtime

**Environment:**
- Python 3.10+ (uses `from __future__ import annotations` and `X | Y` union syntax throughout)
- Browser runtime for client-side JS (ES Modules via `<script type="module">`)
- Pyodide WASM runtime for client-side Python execution in browser

**Package Manager:**
- pip with setuptools
- Lockfile: Not present (no `requirements.lock` or `pip.lock`)

## Frameworks

**Core:**
- Flask (latest) - HTTP server, route handling, template rendering
- Flask-SocketIO (latest) - Real-time bidirectional communication (WebSocket transport)
- eventlet - Async networking / green threads for concurrent game sessions
- Gymnasium (OpenAI) - Environment abstraction (Gym-style `env.step()`, `env.reset()`)

**Client-Side:**
- Phaser.js - 2D game rendering engine (`interactive_gym/server/static/lib/phaser.min.js`)
- Socket.IO (client) - WebSocket communication with server
- Pyodide - Python-in-browser via WebAssembly for client-side game execution

**Testing:**
- pytest >= 8.0 - Test runner, configured in `pytest.ini`
- Playwright >= 1.49 - Browser automation for E2E tests
- pytest-playwright >= 0.6 - Playwright integration for pytest
- pytest-timeout >= 2.3 - Test timeout management

**Build/Dev:**
- setuptools + wheel - Package building (`pyproject.toml`, `setup.py`)
- twine - PyPI upload (`update_pypi.sh`)

## Key Dependencies

**Critical (install_requires):**
- `numpy` - Numerical computation, observation/action spaces
- `gymnasium` - Environment interface (listed in `requirements.txt`)

**Server extras (extras_require["server"]):**
- `eventlet` - Green-thread concurrency for handling multiple simultaneous games
- `flask` - HTTP framework
- `flask-socketio` - WebSocket layer for real-time game state transmission
- `msgpack` - Binary serialization for efficient state transfer over WebSocket
- `pandas` - Data logging and experiment data export
- `flatten_dict` - Dictionary flattening for data export

**Authentication:**
- `flask-login >= 0.6.3` - Admin dashboard authentication (listed in `requirements.txt`)

**Optional:**
- `onnxruntime` - ONNX model inference for AI policies (optional import in `interactive_gym/utils/onnx_inference_utils.py`)
- `cv2` (OpenCV) - RGB array rendering fallback (optional import in `interactive_gym/server/game_manager.py`)

**Client-Side Libraries (vendored in `interactive_gym/server/static/lib/`):**
- `phaser.min.js` - 2D game engine for canvas rendering
- `jquery-min.js` - DOM manipulation
- `bootstrap.min.js` - UI framework
- `d3.v3.min.js` - Data visualization
- `underscore-min.js` - Utility library
- `backbone-min.js` - Client MVC structure
- `babel.min.js` - JS transpilation

**Client-Side Application JS (`interactive_gym/server/static/js/`):**
- `index.js` - Main entry point, SocketIO connection, probe manager
- `phaser_gym_graphics.js` - Phaser-based game rendering
- `pyodide_remote_game.js` - Single-player Pyodide game engine
- `pyodide_multiplayer_game.js` - Multiplayer Pyodide game with P2P sync
- `webrtc_manager.js` - WebRTC peer connection, DataChannel, TURN fallback
- `probe_connection.js` - Lightweight WebRTC RTT probing for matchmaking
- `continuous_monitor.js` - Ping/tab visibility monitoring during gameplay
- `socket_handlers.js` - SocketIO event handlers
- `latency.js` - Latency measurement utilities
- `game_events.js` - Game event dispatching
- `seeded_random.js` - Deterministic RNG for multiplayer sync
- `ui_utils.js` - UI helper functions
- `unity_utils.js` - Unity WebGL integration utilities
- `onnx_inference.js` - Client-side ONNX model inference
- `msgpack.min.js` - Binary serialization (client-side)

## Configuration

**Environment Variables:**
- `FLASK_ENV` - Set to `"development"` for debug mode (default: `"production"`)
- `ADMIN_PASSWORD` - Admin dashboard password (default: `"admin123"` for dev)
- `TURN_USERNAME` - TURN server username for WebRTC NAT traversal
- `TURN_CREDENTIAL` - TURN server credential for WebRTC NAT traversal

**Python Configuration Objects:**
- `RemoteConfig` - Legacy configuration class (`interactive_gym/configurations/remote_config.py`), builder-pattern API for environment, rendering, hosting, policies, gameplay, UX, Pyodide, WebRTC
- `ExperimentConfig` - Newer configuration class (`interactive_gym/configurations/experiment_config.py`), adds entry screening, stager-based scene flow, experiment-level settings
- `configuration_constants.py` - Frozen dataclass constants for input modes, policy types, action settings

**Build Configuration:**
- `pyproject.toml` - Build system declaration (setuptools + wheel)
- `setup.py` - Package metadata, version 0.1.1, install/extras requires
- `MANIFEST.in` - Source distribution file inclusion rules
- `pytest.ini` - Test configuration (paths, markers, addopts)

**Deployment:**
- `interactive_gym/configurations/interactive-gym-nginx.conf` - Nginx reverse proxy config for load balancing (3 Flask workers on ports 5701-5703, fronted by port 5700)

## Platform Requirements

**Development:**
- Python 3.10+
- Node.js not required (no npm/package.json; JS is vendored)
- Playwright browsers for E2E tests: `playwright install` (must run in headed mode)

**Production:**
- Linux server with Python 3.10+
- Nginx for reverse proxy / load balancing (optional but recommended)
- TURN server credentials (e.g., metered.ca) for WebRTC NAT traversal in multiplayer
- Published on PyPI as `interactive-gym` version 0.1.1

**Package Version:** 0.1.1 (defined in `setup.py`)

---

*Stack analysis: 2026-02-07*
