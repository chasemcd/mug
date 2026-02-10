# External Integrations

**Analysis Date:** 2026-02-07

## APIs & External Services

**WebRTC / TURN Server:**
- TURN server (e.g., metered.ca) - NAT traversal for P2P multiplayer connections
  - SDK/Client: Native browser `RTCPeerConnection` API via `interactive_gym/server/static/js/webrtc_manager.js`
  - Auth: `TURN_USERNAME` and `TURN_CREDENTIAL` env vars (or passed to `ExperimentConfig.webrtc()` / `RemoteConfig.webrtc()`)
  - Config location: `interactive_gym/configurations/remote_config.py` (lines 96-98), `interactive_gym/configurations/experiment_config.py` (lines 82-131)
  - Usage: P2P game input exchange via DataChannel (unreliable/unordered for GGPO-style), P2P RTT probing during matchmaking

**Pyodide CDN:**
- Pyodide WASM runtime - Loads Python interpreter in browser for client-side game execution
  - Loaded from CDN at runtime in browser
  - Configured per-scene: `GymScene.pyodide()` method in `interactive_gym/scenes/gym_scene.py`
  - Package installation: `micropip` for installing Python packages in browser (e.g., interactive-gym itself)
  - Client code: `interactive_gym/server/static/js/pyodide_remote_game.js`, `interactive_gym/server/static/js/pyodide_multiplayer_game.js`

**ONNX Runtime:**
- ONNX model inference for AI bot policies (optional)
  - SDK/Client: `onnxruntime` Python package (server-side) and `interactive_gym/server/static/js/onnx_inference.js` (client-side)
  - Auth: None (local model files)
  - Server implementation: `interactive_gym/utils/onnx_inference_utils.py`
  - Usage: Load and run pre-trained AI policies exported from RLLib

**Google Fonts CDN:**
- Font loading for experiment UI
  - Fonts: "Press Start 2P", "Roboto"
  - Loaded in: `interactive_gym/server/static/templates/index.html` (line 8-9)

## Data Storage

**Databases:**
- None. No database integration. All state is in-memory during server runtime.

**File Storage:**
- Local filesystem only
  - Experiment data: `data/{scene_id}/` directories, saved as JSON/CSV files
  - Match assignment logs: `data/match_logs/{scene_id}_matches.jsonl` (JSONL format, written by `interactive_gym/server/match_logger.py`)
  - Console logs: `data/console_logs/` directory
  - Server logs: Configurable via `RemoteConfig.logfile` (default: `./server_log.log`)
  - Application log: `./iglog.log` (hardcoded in `interactive_gym/server/app.py` line 83)

**Caching:**
- None. All state held in in-memory Python dictionaries with thread-safe wrappers (`interactive_gym/server/utils.py` `ThreadSafeDict`, `ThreadSafeSet`).

## Authentication & Identity

**Admin Dashboard Auth:**
- Flask-Login with simple single-user password auth
  - Implementation: `interactive_gym/server/admin/routes.py`, `interactive_gym/server/admin/__init__.py`
  - Password: `ADMIN_PASSWORD` env var (default: `"admin123"`)
  - Session: Flask session cookies via Flask-Login `LoginManager`
  - Routes: `/admin/login`, `/admin/logout`, `/admin/` (dashboard)

**Participant Identity:**
- UUID-based subject IDs, no authentication
  - Generated server-side on first visit: `interactive_gym/server/app.py` line 233 (`str(uuid.uuid4())`)
  - Can be passed via URL query parameter for external recruitment platforms (e.g., Prolific, MTurk)
  - Session restoration via `ParticipantSession` tracking in `interactive_gym/server/app.py`
  - Server session ID: `secrets.token_urlsafe(16)` for server instance identification

## Monitoring & Observability

**Error Tracking:**
- None. No external error tracking service (no Sentry, Datadog, etc.)

**Logs:**
- Python `logging` module throughout server code
  - Main application logger: `interactive_gym/server/app.py` -> `./iglog.log`
  - Per-module loggers: `logging.getLogger(__name__)` in each module
  - Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
  - Console log collection from clients: saved to `data/console_logs/` via `AdminEventAggregator`

**Admin Dashboard:**
- Real-time experiment monitoring via Flask Blueprint + SocketIO namespace
  - Routes: `interactive_gym/server/admin/routes.py`
  - Real-time updates: `interactive_gym/server/admin/namespace.py` (AdminNamespace SocketIO)
  - State aggregation: `interactive_gym/server/admin/aggregator.py` (AdminEventAggregator, 1-2 Hz updates)
  - UI: `interactive_gym/server/admin/templates/dashboard.html`, `interactive_gym/server/admin/static/admin.js`

## CI/CD & Deployment

**Hosting:**
- Self-hosted Flask + eventlet server
- Nginx reverse proxy supported: `interactive_gym/configurations/interactive-gym-nginx.conf` (load balancing across 3 workers on ports 5701-5703)
- No cloud platform integration (no Heroku, AWS, GCP, etc.)

**CI Pipeline:**
- None detected. No `.github/workflows/`, `.gitlab-ci.yml`, or similar CI config files.

**Package Distribution:**
- PyPI via `twine upload dist/*`
  - Build script: `update_pypi.sh` (runs `python setup.py sdist bdist_wheel && twine upload dist/*`)
  - Package name: `interactive-gym`
  - Current version: `0.1.1`

## Environment Configuration

**Required env vars (for full functionality):**
- `TURN_USERNAME` - TURN server username (required for P2P multiplayer through NAT)
- `TURN_CREDENTIAL` - TURN server credential (required for P2P multiplayer through NAT)
- `ADMIN_PASSWORD` - Admin dashboard password (has insecure default `"admin123"`)

**Optional env vars:**
- `FLASK_ENV` - Set to `"development"` for debug mode

**Secrets location:**
- Environment variables only. No `.env` file, no secrets manager integration.
- TURN credentials can alternatively be passed programmatically via `ExperimentConfig.webrtc()` or `RemoteConfig.webrtc()`

## Real-Time Communication

**WebSocket (Flask-SocketIO):**
- Primary server-client communication channel
  - Transport: WebSocket only (no long-polling fallback, configured in `interactive_gym/server/static/js/index.js` line 8-11)
  - Serialization: msgpack binary format for game state, JSON for control messages
  - CORS: `cors_allowed_origins="*"` (open, configured in `interactive_gym/server/app.py` line 196)
  - Ping: interval=8s, timeout=30s (tuned for Pyodide WASM loading)
  - Namespaces: default `/` (game), `/admin` (dashboard)

**WebRTC (P2P):**
- Peer-to-peer game input exchange for multiplayer
  - DataChannel: unreliable/unordered for low-latency input exchange (GGPO-style)
  - Signaling: Via SocketIO relay through server
  - ICE: STUN + TURN fallback
  - Connection quality monitoring: `ConnectionQualityMonitor` in `interactive_gym/server/static/js/webrtc_manager.js`
  - RTT probing: `ProbeConnection` in `interactive_gym/server/static/js/probe_connection.js` (pre-game RTT measurement)
  - Server coordination: `interactive_gym/server/probe_coordinator.py` (ProbeCoordinator)

## Webhooks & Callbacks

**Incoming:**
- None. No webhook endpoints.

**Outgoing:**
- Redirect URLs after experiment completion: `experiment_end_redirect_url` and `waitroom_timeout_redirect_url` in config
  - Can append subject ID to redirect URL for integration with recruitment platforms (Prolific, MTurk)
  - Configured via `RemoteConfig.user_experience()` or scene-level configuration

**Server-Side Callbacks:**
- `GameCallback` system (`interactive_gym/server/callback.py`) - Lifecycle hooks:
  - `on_episode_start`, `on_episode_end`
  - `on_game_tick_start`, `on_game_tick_end`
  - `on_graphics_start`, `on_graphics_end`
  - `on_waitroom_start`, `on_waitroom_join`, `on_waitroom_end`, `on_waitroom_timeout`
  - `on_game_end`
- `MultiCallback` - Compose multiple callbacks
- Entry screening callback: `entry_exclusion_callback` in `ExperimentConfig` for custom participant filtering

## External Environment Integrations

**Gymnasium Environments:**
- Any Gymnasium-compatible environment can be used via `env_creator` callable
  - Configured per-scene in `GymScene.environment()` or `RemoteConfig.environment()`
  - Environment runs server-side (standard mode) or client-side (Pyodide mode)

**CoGrid Environments:**
- Overcooked-style cooperative cooking environments (example integration)
  - Location: `interactive_gym/examples/cogrid/`
  - Multiple layout variants: cramped_room, coordination_ring, counter_circuit, asymmetric_advantages, forced_coordination

**Unity WebGL:**
- Unity game builds can be embedded via `UnityScene` (`interactive_gym/scenes/unity_scene.py`)
  - Example: FOOTSIES fighting game in `interactive_gym/examples/footsies/`
  - WebGL builds stored in: `interactive_gym/server/static/web_gl/`

**Slime Volleyball:**
- Slime Volleyball environment integration
  - Location: `interactive_gym/examples/slime_volleyball/`
  - Custom environment wrappers: `slimevb_env.py`, `slimevb_boost_env.py`

---

*Integration audit: 2026-02-07*
