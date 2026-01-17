# External Integrations

**Analysis Date:** 2025-01-16

## APIs & External Services

**Pyodide CDN:**
- Purpose: Python runtime in browser for client-side game execution
- SDK/Client: Loaded via CDN or bundled in static assets
- Auth: None required

**Public IP Detection:**
- Purpose: Display server's public IP address on startup
- Client: `urllib.request.urlopen("https://api.ipify.org")`
- Auth: None (public API)

## Data Storage

**Databases:**
- None - Data persisted to local filesystem only

**File Storage:**
- Local filesystem only
- Data directory: `data/{scene_id}/` (created dynamically)
- Data format: CSV files and JSON globals files

**Caching:**
- None - In-memory state only

## Authentication & Identity

**Auth Provider:**
- Custom UUID-based participant IDs
- Implementation: Server generates UUID on first visit (`interactive_gym/server/app.py:150-153`)
- Session tracking via Flask sessions and custom `SESSION_ID_TO_SUBJECT_ID` mapping

**Session Management:**
- `PARTICIPANT_SESSIONS` dict stores session state for reconnection
- `SERVER_SESSION_ID` (random token) validates client-server session matching
- Socket.IO rooms for game/multiplayer grouping

## Monitoring & Observability

**Error Tracking:**
- None - No external error tracking integration

**Logging:**
- Python `logging` module to file and stdout
- Log file: `./iglog.log` (configurable)
- Format: Timestamp, logger name, level, message
- See `setup_logger()` in `interactive_gym/server/app.py:52-71`

## CI/CD & Deployment

**Hosting:**
- Self-hosted (Flask/eventlet server)
- Optional nginx reverse proxy config: `interactive_gym/configurations/interactive-gym-nginx.conf`

**CI Pipeline:**
- None detected

**PyPI Publishing:**
- Script: `update_pypi.sh`
- Package: `interactive-gym` (version 0.1.1)

## Environment Configuration

**Required env vars:**
- `FLASK_ENV` - Set to "development" for debug mode (optional, defaults to "production")

**Secrets location:**
- Flask SECRET_KEY hardcoded as `"secret!"` in `app.py:134`
- No external secrets management

## Webhooks & Callbacks

**Incoming:**
- None - No webhook endpoints

**Outgoing:**
- Experiment redirect URLs (configurable):
  - `experiment_end_redirect_url` - Redirect after experiment completion
  - `waitroom_timeout_redirect_url` - Redirect if waiting room times out
  - Subject ID optionally appended via `append_subject_id_to_redirect` flag

## WebSocket Events (Socket.IO)

**Client -> Server:**
| Event | Purpose |
|-------|---------|
| `register_subject` | Associate socket with participant ID |
| `sync_globals` | Sync client-side globals to server |
| `advance_scene` | Progress to next scene in experiment |
| `join_game` | Join a game session |
| `leave_game` | Exit current game |
| `send_pressed_keys` | Transmit keyboard input |
| `reset_complete` | Signal client ready after episode reset |
| `ping` | Latency measurement |
| `pyodide_player_action` | Multiplayer action submission |
| `pyodide_state_hash` | State verification hash |
| `p2p_state_sync` | P2P state synchronization |
| `static_scene_data_emission` | Save static scene data |
| `emit_remote_game_data` | Save game replay data |

**Server -> Client:**
| Event | Purpose |
|-------|---------|
| `server_session_id` | Send session validation token |
| `session_restored` | Acknowledge session restoration |
| `duplicate_session` | Reject concurrent connections |
| `waiting_room` | Waiting room status update |
| `start_game` | Game session beginning |
| `environment_state` | Game state broadcast |
| `game_reset` | Episode reset signal |
| `end_game` | Game termination |
| `pyodide_host_elected` | Multiplayer host assignment |
| `pyodide_game_ready` | All players joined |
| `pyodide_other_player_action` | Relay other player's action |
| `server_authoritative_state` | Authoritative state broadcast |
| `server_episode_start` | New episode starting |

## Unity Integration

**Purpose:** Support for Unity WebGL builds as game scenes
- Files: `interactive_gym/scenes/unity_scene.py`, `js/unity_utils.js`
- Communication: Socket.IO events `unityEpisodeEnd`, `unityEpisodeStart`
- Assets: `interactive_gym/server/static/web_gl/`

## ONNX Model Inference

**Purpose:** Run trained RL policies server-side
- File: `interactive_gym/utils/onnx_inference_utils.py`
- Dependency: `onnxruntime` (optional)
- Usage: Load ONNX models exported from RLLib for AI agents

---

*Integration audit: 2025-01-16*
