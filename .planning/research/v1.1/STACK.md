# Stack Research: Admin Dashboard

**Project:** Interactive Gym v1.1 Admin Dashboard
**Researched:** 2026-01-19
**Overall Confidence:** HIGH

## Recommendation Summary

For adding an admin dashboard to Interactive Gym's existing Flask/SocketIO stack, the recommended approach is **HTMX + Jinja2 templates with DaisyUI/Tailwind CSS styling**, leveraging the **existing Flask-SocketIO infrastructure** for real-time updates. This avoids introducing a separate frontend framework (React/Vue), keeps the codebase unified with the existing Jinja2 template system, and provides excellent real-time capabilities through SocketIO namespaces. For data tables use **Tabulator** (lightweight, MIT licensed), and for charts use **Chart.js** (simple, well-documented). The admin panel should use a dedicated SocketIO namespace (`/admin`) to isolate admin traffic from participant traffic.

---

## Frontend Framework

### Recommendation: HTMX 2.0.8

**Why HTMX over React/Vue/Svelte:**

| Criterion | HTMX | React/Vue | Why HTMX Wins |
|-----------|------|-----------|---------------|
| Learning curve | Minimal | Significant | Team already knows Flask/Jinja2 |
| Bundle size | ~14KB | 40-200KB+ | Faster load, less complexity |
| Integration | Native with Flask | Requires API layer | Direct HTML returns from Flask routes |
| Real-time | SSE + WebSocket extensions | Custom implementation | Works seamlessly with existing SocketIO |
| Maintenance | HTML attributes | Build systems, state management | No npm, webpack, or JS toolchain |

**Key HTMX features for admin dashboards:**
- `hx-get`/`hx-post`: AJAX requests returning HTML fragments
- `hx-trigger="every 5s"`: Built-in polling for live updates
- `hx-swap-oob`: Out-of-band swaps for updating multiple elements
- WebSocket extension: Integrates with existing Flask-SocketIO
- SSE extension: Server-pushed updates for metrics

**Installation:**
```html
<!-- CDN (recommended for simplicity) -->
<script src="https://cdn.jsdelivr.net/npm/htmx.org@2.0.8/dist/htmx.min.js"
        integrity="sha384-/TgkGk7p307TH7EXJDuUlgG3Ce1UVolAOFopFekQkkXihi5u/6OCvVKyz1W+idaz"
        crossorigin="anonymous"></script>

<!-- WebSocket extension for SocketIO integration -->
<script src="https://unpkg.com/htmx-ext-ws@2.0.0/ws.js"></script>
```

**Confidence:** HIGH - HTMX is actively maintained, well-documented, and specifically designed for server-rendered applications like Flask.

### Alternatives Considered

| Framework | Why Not |
|-----------|---------|
| React | Overkill for admin panel; requires separate API, build toolchain, increases complexity |
| Vue | Same issues as React; would bifurcate codebase between Jinja2 and Vue |
| Svelte | Smaller bundle but still requires build step and separate paradigm |
| Vanilla JS | More code to write/maintain; HTMX handles common patterns declaratively |

---

## Real-time Updates Strategy

### Recommendation: Flask-SocketIO Namespaces + HTMX

The existing Interactive Gym app already uses Flask-SocketIO. The admin dashboard should:

1. **Use a dedicated `/admin` namespace** to isolate admin traffic
2. **Emit HTML fragments** that HTMX can swap directly into the DOM
3. **Use rooms** to group admin sessions viewing the same data

**Architecture:**

```
Participant Browser                 Admin Browser
      |                                  |
      v                                  v
[Flask-SocketIO]                  [Flask-SocketIO]
  namespace: /                      namespace: /admin
      |                                  |
      v                                  v
  Game Events                      Admin Events
  (existing)                    (participant_update,
                                 metrics_update,
                                 log_entry, etc.)
```

**Implementation pattern:**

```python
# Server-side: admin namespace
from flask_socketio import Namespace, emit

class AdminNamespace(Namespace):
    def on_connect(self):
        # Verify admin authentication
        if not current_user_is_admin():
            return False
        join_room('admin_dashboard')

    def on_subscribe_participant(self, data):
        """Subscribe to updates for a specific participant"""
        join_room(f"admin_participant_{data['subject_id']}")

# Emit updates from existing game code
def broadcast_participant_update(subject_id, data):
    socketio.emit('participant_update',
                  render_template('admin/_participant_row.html', **data),
                  namespace='/admin',
                  room='admin_dashboard')
```

```html
<!-- Client-side: HTMX + SocketIO -->
<div hx-ext="ws" ws-connect="/admin">
    <table id="participants">
        <tbody hx-swap-oob="beforeend:#participants tbody">
            <!-- Rows injected via SocketIO -->
        </tbody>
    </table>
</div>
```

**Why not SSE?**
- Flask-SocketIO already handles WebSocket connections
- Bi-directional communication needed for intervention controls (kick, pause, message)
- Avoids adding another async pattern to the codebase

**Confidence:** HIGH - This leverages existing infrastructure and is a well-documented Flask-SocketIO pattern.

---

## UI Components

### Styling: DaisyUI 5 + Tailwind CSS 4

**Why DaisyUI:**
- Pure CSS, no JavaScript dependencies
- Framework-agnostic (works with Jinja2)
- 30+ built-in themes (easy dark mode)
- Component classes match admin dashboard needs (`table`, `card`, `badge`, `stat`, `tabs`)
- 22M+ npm downloads in 2025; actively maintained

**Installation:**
```bash
npm install -D tailwindcss@4 daisyui@5
```

Or use CDN for simpler setup (recommended for admin panel):
```html
<link href="https://cdn.jsdelivr.net/npm/daisyui@5/dist/full.min.css" rel="stylesheet">
<script src="https://cdn.tailwindcss.com"></script>
```

**Key components for admin dashboard:**
- `table` + `table-zebra`: Participant list
- `stats`: Overview metrics (active participants, games, etc.)
- `badge`: Status indicators (connected, in-game, waiting)
- `tabs`: Switch between views (participants, groups, logs)
- `modal`: Intervention confirmations
- `alert`: System notifications

**Confidence:** HIGH - DaisyUI is the most popular Tailwind component library, MIT licensed.

### Data Tables: Tabulator 6.x

**Why Tabulator over AG-Grid:**

| Feature | Tabulator | AG-Grid Community |
|---------|-----------|-------------------|
| License | MIT (fully free) | MIT but limited features |
| Bundle size | ~90KB | ~300KB |
| Complexity | Simple API | Steeper learning curve |
| Real-time updates | Native support | Requires transaction API |
| Pagination/Filtering | Built-in | Built-in |
| Framework | Vanilla JS | Prefers React/Angular |

**Key features needed:**
- Sorting, filtering, pagination (all included)
- Row selection for bulk actions
- Inline cell editing (for notes)
- Real-time row updates via `table.updateData()`
- Export to CSV (for researchers)

**Installation:**
```html
<link href="https://unpkg.com/tabulator-tables@6.3/dist/css/tabulator.min.css" rel="stylesheet">
<script src="https://unpkg.com/tabulator-tables@6.3/dist/js/tabulator.min.js"></script>
```

**Integration with HTMX:**
```javascript
// Initialize table
const table = new Tabulator("#participants-table", {
    columns: [...],
    pagination: true,
    paginationSize: 25
});

// Update from SocketIO
socket.on('participant_update', (data) => {
    table.updateOrAddData([data]);
});
```

**Confidence:** HIGH - Tabulator is mature, well-documented, and explicitly designed for real-time dashboards.

### Charts: Chart.js 4.x

**Why Chart.js over Plotly:**

| Feature | Chart.js | Plotly.js |
|---------|----------|-----------|
| Bundle size | ~70KB | ~3MB |
| Learning curve | Low | Medium-High |
| Real-time updates | Simple `.update()` | More complex |
| Use case | Simple metrics | Scientific visualization |

For an admin dashboard showing participant counts, game activity over time, and basic metrics, Chart.js is sufficient.

**Installation:**
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4/dist/chart.umd.min.js"></script>
```

**Confidence:** HIGH - Chart.js is the most popular charting library, perfect for simple metrics.

---

## Backend Additions

### Required Python Packages

```txt
# Already in requirements.txt
flask
flask_socketio
eventlet  # Consider migration plan to threading/gevent

# New for admin dashboard
flask-login>=0.6.3        # Admin authentication
python-dotenv>=1.0.0      # Environment config for admin secrets
```

### Admin Blueprint Structure

```python
# interactive_gym/server/admin/__init__.py
from flask import Blueprint

admin_bp = Blueprint('admin', __name__,
                     url_prefix='/admin',
                     template_folder='templates')

# interactive_gym/server/admin/routes.py
@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    return render_template('admin/dashboard.html')

# Register in app.py
from interactive_gym.server.admin import admin_bp
app.register_blueprint(admin_bp)
```

### SocketIO Namespace Registration

```python
# interactive_gym/server/admin/events.py
from flask_socketio import Namespace

class AdminNamespace(Namespace):
    namespace = '/admin'

    def on_connect(self):
        # Authentication check
        pass

    def on_request_participant_list(self):
        # Emit current state
        pass

# In app.py
socketio.on_namespace(AdminNamespace('/admin'))
```

**Confidence:** HIGH - Standard Flask patterns, well-documented.

### Eventlet Migration Consideration

The current stack uses `eventlet`. Per Flask-SocketIO maintainer Miguel Grinberg (2025):

> "Eventlet is winding down... the third option with threads is now preferred, and if that does not work then the alternative is to use gevent."

**Recommendation:** For v1.1, continue with eventlet (it works). Plan migration to threading mode or gevent for v1.2+.

**Confidence:** MEDIUM - Migration is recommended but not urgent.

---

## What NOT to Use

### Avoid These Technologies

| Technology | Why Avoid |
|------------|-----------|
| **React/Vue/Angular** | Overkill for admin panel; fragments the codebase; requires build toolchain |
| **AG-Grid Enterprise** | Expensive ($999+/dev/year); Community version sufficient |
| **Plotly.js** | 3MB bundle; overkill for simple metrics |
| **Flask-Admin** | Opinionated; hard to customize; doesn't integrate well with existing SocketIO |
| **Dash (Plotly)** | Separate framework; would run as separate app |
| **Celery** | Not needed for admin dashboard; adds complexity |
| **Redis** | Not needed unless scaling to multiple server instances |
| **Server-Sent Events (pure)** | Already have SocketIO; don't add another async pattern |

### Avoid These Patterns

| Pattern | Why Avoid |
|---------|-----------|
| **Separate admin API** | HTMX returns HTML; no need for JSON API layer |
| **Global SocketIO broadcasts** | Use namespaces/rooms to isolate admin traffic |
| **Polling for everything** | Use SocketIO push for real-time; polling only for fallback |
| **Heavy client-side state** | Let server be source of truth; HTMX swaps HTML |

---

## Integration with Existing Flask/SocketIO

### Minimal Changes to Existing Code

The admin dashboard should be additive, not requiring changes to existing participant flows:

1. **New Blueprint**: `/admin` routes in separate blueprint
2. **New Namespace**: `/admin` SocketIO namespace
3. **Hook into existing events**: Add admin broadcast calls to existing handlers

**Example: Broadcasting participant updates**

```python
# In app.py, modify register_subject
@socketio.on("register_subject")
def register_subject(data):
    # ... existing code ...

    # NEW: Notify admin dashboard
    socketio.emit('participant_registered',
                  {'subject_id': subject_id, 'timestamp': time.time()},
                  namespace='/admin',
                  room='admin_dashboard')
```

**Example: Exposing state for admin**

```python
# In admin/routes.py
@admin_bp.route('/api/participants')
@admin_required
def get_participants():
    """Return current participant state for admin dashboard"""
    from interactive_gym.server.app import STAGERS, PARTICIPANT_SESSIONS

    participants = []
    for subject_id, session in PARTICIPANT_SESSIONS.items():
        stager = STAGERS.get(subject_id)
        participants.append({
            'subject_id': subject_id,
            'is_connected': session.is_connected,
            'current_scene': session.current_scene_id,
            'scene_index': session.stager_state.get('current_scene_index') if session.stager_state else 0
        })

    return render_template('admin/_participants_table.html', participants=participants)
```

---

## Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| HTMX choice | HIGH | Well-documented Flask integration; matches existing Jinja2 pattern |
| DaisyUI/Tailwind | HIGH | Most popular Tailwind library; pure CSS works with Jinja2 |
| Tabulator | HIGH | MIT licensed; designed for real-time; simpler than AG-Grid |
| Chart.js | HIGH | Dominant market share; simple API; lightweight |
| SocketIO namespaces | HIGH | Official Flask-SocketIO pattern; existing infrastructure |
| Eventlet status | MEDIUM | Working but deprecated; migration needed eventually |
| Authentication | MEDIUM | Flask-Login is standard, but needs design decisions |

---

## Version Summary

| Package | Version | Source |
|---------|---------|--------|
| HTMX | 2.0.8 | CDN/npm |
| DaisyUI | 5.x | CDN/npm |
| Tailwind CSS | 4.x | CDN/npm |
| Tabulator | 6.3.x | CDN/npm |
| Chart.js | 4.4.x | CDN |
| Flask-SocketIO | 5.6.0 | PyPI (already installed) |
| Flask-Login | 0.6.3+ | PyPI (new) |

---

## Sources

### Official Documentation
- [Flask-SocketIO Deployment](https://flask-socketio.readthedocs.io/en/latest/deployment.html)
- [Flask-SocketIO PyPI](https://pypi.org/project/Flask-SocketIO/)
- [HTMX Documentation](https://htmx.org/docs/)
- [HTMX 2.0.8 npm](https://www.npmjs.com/package/htmx.org)
- [DaisyUI Documentation](https://daisyui.com/?lang=en)
- [Socket.IO Namespaces](https://socket.io/docs/v4/namespaces/)

### Tutorials and Guides
- [Streaming data from Flask to HTMX using SSE](https://mathspp.com/blog/streaming-data-from-flask-to-htmx-using-server-side-events)
- [Building Real-time APIs with Flask WebSockets](https://blog.poespas.me/posts/2025/03/04/building-real-time-apis-with-flask-websockets/)
- [Flask Postgres SocketIO Dashboard](https://testdriven.io/blog/flask-postgres-socketio/)
- [HTMX WebSocket Guide 2025](https://www.videosdk.live/developer-hub/websocket/htmx-websocket)

### Comparisons and Analysis
- [HTMX vs React Vue Angular 2025](https://redskydigital.com/au/htmx-vs-react-vue-angular-frontend-development-in-2025/)
- [Flask-SocketIO Eventlet vs Gevent Discussion](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/2037)
- [AG-Grid Alternatives 2025](https://www.thefrontendcompany.com/posts/ag-grid-alternatives)
- [JavaScript Charting Libraries Comparison](https://www.digitalocean.com/community/tutorials/javascript-charts)
