# Architecture Research: Admin Dashboard for Experiment Monitoring

**Researched:** 2026-01-19
**Domain:** Real-time monitoring dashboard for multiplayer experiment platform
**Confidence:** HIGH (based on codebase analysis + established patterns)

## Executive Summary

The admin dashboard should be implemented as a **separate namespace** (`/admin`) within the existing Flask-SocketIO infrastructure, using an **observer pattern** to tap into existing data flows without modifying participant-facing code. The architecture leverages the already-comprehensive state tracking in `PyodideGameCoordinator`, `GameManager`, `ServerGameRunner`, and `PlayerGroupManager` - these components already maintain all the data needed for monitoring; the dashboard simply needs read access and subscription to existing events.

The key insight: Interactive Gym already emits detailed SocketIO events to participant rooms. The admin dashboard can subscribe to a **broadcast mirror** of these events, plus access aggregated state through periodic polling or push-based state digests.

## Component Structure

### Overview Diagram

```
+------------------+     +-------------------+     +------------------+
|  Admin Client    |     | Participant       |     | Participant      |
|  (Dashboard UI)  |     | Client 1          |     | Client 2         |
+--------+---------+     +--------+----------+     +--------+---------+
         |                        |                         |
         | /admin namespace       | / namespace (default)   |
         |                        |                         |
+--------v------------------------v-------------------------v---------+
|                        Flask-SocketIO Server                        |
|  +----------------------------------------------------------------+ |
|  |                    Namespace Router                            | |
|  |  /admin -> AdminNamespace    / -> ParticipantNamespace         | |
|  +----------------------------------------------------------------+ |
|                                                                     |
|  +------------------+  +------------------+  +------------------+   |
|  | Admin Event      |  | PyodideGame      |  | Game             |   |
|  | Aggregator       |  | Coordinator      |  | Manager          |   |
|  | (NEW)            |  | (existing)       |  | (existing)       |   |
|  +--------+---------+  +--------+---------+  +--------+---------+   |
|           |                     |                     |             |
|           | observes/subscribes | emits events        | emits events|
|           +---------------------+---------------------+             |
|                                                                     |
|  +------------------+  +------------------+  +------------------+   |
|  | Server Game      |  | Player Pairing   |  | Participant      |   |
|  | Runner           |  | Manager          |  | Sessions         |   |
|  | (existing)       |  | (existing)       |  | (existing)       |   |
|  +------------------+  +------------------+  +------------------+   |
+---------------------------------------------------------------------+
```

### Major Components

#### 1. AdminNamespace (NEW)
**Responsibility:** Handles all admin client connections on `/admin` namespace
**Location:** `interactive_gym/server/admin_namespace.py`

```python
class AdminNamespace(flask_socketio.Namespace):
    """
    Separate namespace for admin dashboard connections.

    Isolation benefits:
    - Admin traffic doesn't pollute participant rooms
    - Different authentication can be applied
    - Can be disabled in production without affecting participants
    """

    def on_connect(self):
        # Authenticate admin (API key, session, etc.)
        # Join admin-specific room for broadcasts

    def on_subscribe_session(self, data):
        # Admin subscribes to specific session/game updates

    def on_request_state_snapshot(self, data):
        # Admin requests current state of all games

    def on_send_intervention(self, data):
        # Admin sends message/action to participant(s)
```

#### 2. AdminEventAggregator (NEW)
**Responsibility:** Collects and transforms existing events for admin consumption
**Location:** `interactive_gym/server/admin_event_aggregator.py`

```python
class AdminEventAggregator:
    """
    Central hub that:
    1. Subscribes to existing SocketIO events
    2. Aggregates state from existing managers
    3. Pushes updates to admin namespace

    Uses observer pattern - never modifies source components.
    """

    def __init__(self, sio, pyodide_coordinator, game_managers,
                 group_manager, participant_sessions):
        self.sio = sio
        # References to existing components (read-only)

    def get_experiment_snapshot(self) -> dict:
        """Aggregate current state across all components."""

    def emit_to_admins(self, event: str, data: dict):
        """Emit to all connected admins."""
        self.sio.emit(event, data, namespace='/admin')
```

#### 3. AdminDashboardBlueprint (NEW)
**Responsibility:** Flask routes for dashboard HTML/assets
**Location:** `interactive_gym/server/admin_routes.py`

```python
admin_bp = flask.Blueprint('admin', __name__,
                           url_prefix='/admin',
                           template_folder='templates/admin')

@admin_bp.route('/')
def dashboard():
    """Serve admin dashboard SPA."""

@admin_bp.route('/api/sessions')
def get_sessions():
    """REST endpoint for initial state load."""
```

#### 4. Existing Components (UNCHANGED)
The following components already track the data we need:

| Component | Data Available | How to Access |
|-----------|---------------|---------------|
| `PyodideGameCoordinator.games` | All active Pyodide games, players, frame numbers, diagnostics | Direct dict access |
| `GameManager.games` | RemoteGame instances, player mappings | Direct dict access |
| `GameManager.active_games` | Which games are currently running | Set membership |
| `GameManager.waiting_games` | Games in lobby/waiting room | List |
| `ServerGameRunner` | Frame number, episode, rewards, actions | Per-game instance |
| `PlayerGroupManager.groups` | Player groupings across scenes | Dict access |
| `PARTICIPANT_SESSIONS` | Session state, scene progress, connection status | Dict in app.py |
| `STAGERS` | Per-participant scene progression | Dict in app.py |

## Data Flow

### Flow 1: Participant State to Admin Dashboard

```
1. Participant action occurs
   |
   v
2. Existing handler processes (e.g., on_pyodide_player_action)
   |
   v
3. Coordinator/Manager updates internal state
   |
   +---> [existing path] emit to participant room
   |
   v
4. AdminEventAggregator.on_state_change() triggered
   (via hook or periodic poll)
   |
   v
5. Aggregator transforms data for admin view
   |
   v
6. sio.emit('participant_update', data, namespace='/admin')
   |
   v
7. Admin dashboard receives and renders
```

### Flow 2: Admin Intervention to Participant

```
1. Admin clicks "Send Message" in dashboard
   |
   v
2. AdminNamespace.on_send_intervention(data)
   |
   v
3. Validate admin has permission for this game/participant
   |
   v
4. Route to appropriate participant room
   |
   v
5. sio.emit('admin_message', data, room=participant_socket_id)
   |
   v
6. Participant client displays intervention
```

### Flow 3: Real-time Subscription Model

```
Admin connects to /admin namespace
   |
   v
on_connect: join 'admin_broadcast' room
   |
   v
Periodic aggregator tick (every 1-2 seconds):
   |
   +---> Collect: active games from GAME_MANAGERS
   +---> Collect: pyodide game states from PYODIDE_COORDINATOR
   +---> Collect: session states from PARTICIPANT_SESSIONS
   +---> Collect: group info from GROUP_MANAGER
   |
   v
Emit digest to 'admin_broadcast' room
   |
   v
For high-frequency data (frame-by-frame):
   - Admin explicitly subscribes to specific game_id
   - Aggregator forwards existing events for that game
```

## Integration Points

### Where Dashboard Hooks Into Existing Code

| Hook Point | File | Method | Integration Approach |
|------------|------|--------|---------------------|
| Game created | `game_manager.py` | `_create_game()` | Add aggregator callback after game creation |
| Player joined | `game_manager.py` | `add_subject_to_game()` | Add aggregator callback |
| Game started | `game_manager.py` | `start_game()` | Add aggregator callback |
| Player action | `pyodide_game_coordinator.py` | `receive_action()` | Add optional aggregator notification |
| State broadcast | `server_game_runner.py` | `broadcast_state()` | Forward to admin namespace |
| Player disconnect | `app.py` | `on_disconnect()` | Add aggregator callback |
| Scene advance | `app.py` | `advance_scene()` | Add aggregator callback |

### Minimal Changes to Existing Code

The integration should be **additive** with minimal changes to existing files:

```python
# In app.py - Add during initialization
ADMIN_AGGREGATOR: AdminEventAggregator | None = None

def run(config):
    global ADMIN_AGGREGATOR
    ...
    # After existing initializations
    if config.enable_admin_dashboard:
        ADMIN_AGGREGATOR = AdminEventAggregator(
            sio=socketio,
            game_managers=GAME_MANAGERS,
            pyodide_coordinator=PYODIDE_COORDINATOR,
            group_manager=GROUP_MANAGER,
            participant_sessions=PARTICIPANT_SESSIONS
        )
        socketio.on_namespace(AdminNamespace('/admin', ADMIN_AGGREGATOR))
        app.register_blueprint(admin_bp)
```

### Event Mirroring Pattern

Rather than modifying every emit call, use SocketIO middleware/hooks:

```python
# Wrap socketio.emit to optionally mirror to admin
original_emit = socketio.emit

def emit_with_admin_mirror(event, data, **kwargs):
    # Original emit to participants
    original_emit(event, data, **kwargs)

    # If admin aggregator exists and this event is monitored
    if ADMIN_AGGREGATOR and event in MONITORED_EVENTS:
        ADMIN_AGGREGATOR.mirror_event(event, data, kwargs.get('room'))
```

## Suggested Build Order

Based on dependencies and incremental value delivery:

### Phase 1: Foundation (Build First)
1. **AdminNamespace class** - Required for any admin connectivity
2. **AdminEventAggregator skeleton** - Central data collection point
3. **Admin blueprint with basic route** - Serve dashboard shell

**Why first:** Everything else depends on these. Can be tested with minimal UI.

### Phase 2: Read-Only Dashboard
4. **State snapshot endpoint** - `/admin/api/sessions` REST endpoint
5. **Periodic state broadcast** - Push updates to connected admins
6. **Basic dashboard UI** - Display participants, games, scenes

**Why second:** Provides immediate value (see what's happening) without intervention risk.

### Phase 3: Real-Time Subscriptions
7. **Game-specific subscriptions** - Admin subscribes to individual game events
8. **Frame-level data forwarding** - Mirror high-frequency events for subscribed games
9. **Debug log viewer** - Stream server logs to admin

**Why third:** Builds on foundation, adds depth to monitoring capability.

### Phase 4: Interventions
10. **Admin message sending** - Send text to participant
11. **Session management** - Force disconnect, reset session
12. **Game controls** - Pause/resume (if supported by game)

**Why last:** Highest risk, requires careful access control. Read-only dashboard is useful without this.

### Dependency Graph

```
AdminNamespace ─────────┬─────────────────────────────────────────────┐
                        │                                             │
AdminEventAggregator ───┼─── State Snapshot ─── Dashboard UI         │
                        │         │                   │               │
                        │         v                   v               │
                        └─── Game Subscriptions ─── Log Viewer        │
                                  │                                   │
                                  v                                   │
                        Intervention Controls ────────────────────────┘
```

## Separation Concerns

### Code Organization

```
interactive_gym/server/
  admin/                    # NEW directory for all admin code
    __init__.py
    namespace.py            # AdminNamespace class
    aggregator.py           # AdminEventAggregator class
    routes.py               # Flask blueprint
    templates/              # Admin-specific templates
      dashboard.html
    static/                 # Admin-specific JS/CSS
      admin.js
      admin.css
```

### Configuration Isolation

```python
# In remote_config.py
@dataclasses.dataclass
class AdminConfig:
    enabled: bool = False
    require_auth: bool = True
    auth_token: str | None = None
    allowed_ips: list[str] = field(default_factory=list)
    broadcast_interval_ms: int = 2000
    max_connected_admins: int = 5
```

### Namespace Isolation Benefits

Using `/admin` namespace provides:

1. **Traffic isolation** - Admin messages don't enter participant rooms
2. **Authentication boundary** - Can require API key only for admin namespace
3. **Disable without disruption** - Remove admin namespace in production without code changes
4. **Rate limiting** - Apply different limits to admin vs participant traffic
5. **Logging separation** - Admin actions can be logged separately for audit

### Security Considerations

| Concern | Mitigation |
|---------|-----------|
| Unauthorized admin access | Token-based auth on namespace connect |
| Admin sees sensitive data | Sanitize PII before sending to dashboard |
| Admin DoS via subscriptions | Limit subscriptions per admin, rate limit |
| Admin intervention abuse | Audit log all interventions, require confirmation |
| Data leakage through logs | Redact sensitive fields in debug log viewer |

## Technical Recommendations

### SocketIO Namespace Pattern

```python
# Recommended pattern from Flask-SocketIO docs
class AdminNamespace(Namespace):
    def __init__(self, namespace, aggregator):
        super().__init__(namespace)
        self.aggregator = aggregator

    def on_connect(self):
        # Verify admin token from auth parameter
        token = request.args.get('token')
        if not self._verify_token(token):
            raise ConnectionRefusedError('Invalid admin token')

        # Join broadcast room
        join_room('admin_broadcast')

        # Send initial state
        emit('initial_state', self.aggregator.get_snapshot())
```

### Efficient State Broadcasting

```python
# Don't send full state every tick - use deltas
class AdminEventAggregator:
    def __init__(self):
        self.last_state_hash = {}

    def broadcast_if_changed(self):
        current = self.get_snapshot()
        changed_keys = []

        for key, value in current.items():
            value_hash = hash(str(value))
            if self.last_state_hash.get(key) != value_hash:
                changed_keys.append(key)
                self.last_state_hash[key] = value_hash

        if changed_keys:
            delta = {k: current[k] for k in changed_keys}
            self.emit_to_admins('state_delta', delta)
```

### Existing Data Structures to Expose

The admin dashboard should expose views of these existing structures:

```python
# From app.py
PARTICIPANT_SESSIONS: dict[SubjectID, ParticipantSession]
# Fields: subject_id, stager_state, current_scene_id, socket_id, is_connected

STAGERS: dict[SubjectID, Stager]
# Access: stager.current_scene, stager.get_state()

GAME_MANAGERS: dict[SceneID, GameManager]
# Access: gm.games, gm.active_games, gm.waiting_games

# From pyodide_game_coordinator.py
PyodideGameState dataclass:
# Fields: game_id, players, player_subjects, frame_number, is_active,
#         last_action_times, action_delays (diagnostics!)

# From player_pairing_manager.py
PlayerGroup dataclass:
# Fields: group_id, subject_ids, source_scene_id, is_active
```

## Sources

Research informed by:

- [Flask-SocketIO Namespaces Documentation](https://flask-socketio.readthedocs.io/en/latest/getting_started.html)
- [Socket.IO Namespaces Guide](https://socket.io/docs/v4/namespaces/)
- [Socket.IO Admin UI Architecture](https://socket.io/docs/v4/admin-ui/)
- [Building Real-Time Client Monitoring with Flask and Socket.IO](https://medium.com/@boata.andrei88/building-a-real-time-client-monitoring-system-with-flask-and-socket-io-c023fba5e26c)
- [Real-time User Monitoring Platform Pattern](https://github.com/avidas/socketio-monitoring)
- [Real-Time Dashboard Architecture Patterns](https://estuary.dev/blog/how-to-build-a-real-time-dashboard/)
- [System Design: Real-Time Monitoring Systems](https://systemdesignschool.io/problems/realtime-monitoring-system/solution)

## Quality Gate Checklist

- [x] Components clearly defined (AdminNamespace, AdminEventAggregator, AdminBlueprint)
- [x] Boundaries explicit (separate namespace, observer pattern, no modification to participant code paths)
- [x] Build order implications noted (4-phase incremental approach)
- [x] Integration with existing coordinator/session system clear (hooks into existing data structures, event mirroring pattern)
