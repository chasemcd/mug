# Pitfalls Research: Admin Dashboard

**Project:** Interactive Gym v1.1 - Admin Dashboard / Experiment Monitoring
**Researched:** 2026-01-19
**Confidence:** MEDIUM (verified through official docs, academic research, and codebase analysis)

## Executive Summary

Adding an admin dashboard to an existing real-time Flask/SocketIO research platform presents several critical risks. The most dangerous pitfalls involve **state corruption from admin interventions** (kick/pause actions racing with game state), **research data validity compromise** (admin actions not being properly logged for reproducibility), and **performance degradation** (dashboard updates competing with participant traffic). The existing codebase has complex state management with thread-safe dictionaries, game managers, and session restoration - admin controls must integrate carefully without introducing race conditions. Console log capture, while useful, can flood the server and degrade participant experience if not properly throttled.

---

## Critical Pitfalls

Mistakes that could break the system, corrupt experiment state, or invalidate research data.

### Pitfall 1: Admin Actions Racing with Game State

**What goes wrong:** Admin kick/pause/message actions execute while game state is mid-transition (e.g., during `game.tick()`, episode reset, or player matching). This can leave games in inconsistent states - partially removed players, corrupted reward tracking, or orphaned coordinator entries.

**Why it happens:** The existing `GameManager` uses locks (`game.lock`) for critical sections, but admin actions would bypass these if not carefully integrated. The `PyodideGameCoordinator` maintains separate state (`games`, `players` dicts) that must stay synchronized with `GameManager`.

**Consequences:**
- Players stuck in games that don't exist in coordinator
- Experiment data with incomplete episodes (mid-game terminations not properly recorded)
- Session restoration (`PARTICIPANT_SESSIONS`) pointing to cleaned-up games
- Race between `leave_game()` and admin `kick_player()` causing double-cleanup

**Warning signs:**
- KeyError exceptions in logs for player/game lookups
- Players reporting "stuck" states after admin actions
- Data files with unexpected `None` values or truncated episodes

**Prevention:**
1. Admin actions MUST acquire the same locks used by game logic (`game.lock`)
2. Use the existing `with game.lock:` pattern consistently
3. Admin actions should emit through the same event handlers (e.g., trigger `leave_game` rather than direct cleanup)
4. Add state validation after admin actions (verify player removed from all data structures)

**Phase to address:** Foundation phase - design admin event handlers to integrate with existing lock patterns from day one.

---

### Pitfall 2: Unlogged Admin Interventions Invalidating Research

**What goes wrong:** Admin actions (kick participant, pause game, send message) are not recorded in experiment data, making it impossible to determine which data points were affected by researcher intervention vs. natural participant behavior.

**Why it happens:** Researchers focus on building functionality first, treating logging as an afterthought. The existing data emission (`data_emission`, `receive_remote_game_data`) doesn't have hooks for admin events.

**Consequences:**
- Published research questioned due to lack of audit trail
- Unable to exclude intervention-affected data points in analysis
- IRB compliance issues for human subjects research
- Cannot reproduce experiment conditions

**Warning signs:**
- No admin action entries in data files
- Data analysis reveals unexplained discontinuities
- Unable to answer "why did this participant's session end early?"

**Prevention:**
1. Create `AdminAuditLog` class that mirrors `PARTICIPANT_SESSIONS` pattern
2. Every admin action MUST write to audit log BEFORE executing the action
3. Include: timestamp, admin ID, action type, target subject, game state snapshot, reason field
4. Link audit entries to participant data via subject_id
5. Store audit log separately from participant data but with cross-references

**Phase to address:** Core intervention phase - implement audit logging before any admin action handlers.

**Research-specific requirement:**
```python
@dataclass
class AdminAuditEntry:
    timestamp: float
    admin_id: str
    action_type: str  # kick, pause, message, etc.
    target_subject_id: str
    target_game_id: str | None
    target_scene_id: str | None
    reason: str
    game_state_snapshot: dict | None  # For reproducibility
    pre_action_stager_state: dict | None
```

---

### Pitfall 3: Admin Namespace Leaking to Participants

**What goes wrong:** Admin-only SocketIO events or data accidentally become visible to participants, either through shared namespaces, room misconfiguration, or frontend code exposure.

**Why it happens:** The current codebase uses a single SocketIO instance with room-based isolation. Adding admin events to the same namespace risks accidental broadcast. Frontend JavaScript might include admin event handlers that participants shouldn't see.

**Consequences:**
- Participants see admin controls (experiment validity compromised)
- Participants receive admin-only data emissions
- Security vulnerability: participants could emit admin events

**Warning signs:**
- Participants reporting seeing "admin" UI elements
- Admin events appearing in participant browser console
- No authentication/authorization on admin events

**Prevention:**
1. Use separate SocketIO namespace for admin (`/admin`) - [Flask-SocketIO supports this](https://flask-socketio.readthedocs.io/en/latest/api.html)
2. Admin namespace requires authentication before any event handling
3. Serve admin dashboard from different route/template than participant interface
4. Frontend: separate build/bundle for admin vs. participant
5. Server-side: decorator to validate admin session on every admin event handler

**Phase to address:** Foundation phase - establish namespace separation architecture first.

---

### Pitfall 4: Pause/Resume Corrupting Realtime State

**What goes wrong:** Pausing a realtime game doesn't properly freeze all state advancement, leading to desync between clients, incorrect timing data, or accumulated actions executing in a burst on resume.

**Why it happens:** The existing system has multiple clocks: server-side game loop (`run_server_game`), client-side Pyodide execution, and the `fps`-based tick timing. Pause must freeze ALL of these consistently.

**Consequences:**
- Clients desync after pause (P2P state hash mismatches)
- Action buffer overflows during long pauses
- Timing data shows impossible values (negative or extremely long frame times)
- Accumulated keyboard inputs execute all at once on resume

**Warning signs:**
- Desync errors spike after pause/resume
- Players report "laggy" feeling after unpause
- Frame timing outliers in data

**Prevention:**
1. Pause must set a flag checked by ALL tick sources (server loop AND client)
2. Clear action buffers on pause, not on resume
3. Record pause/resume timestamps in game state (for data analysis)
4. On resume, emit explicit "sync" event to realign all clients
5. For Pyodide multiplayer: use the existing `sync_epoch` mechanism to reset after pause

**Phase to address:** Intervention controls phase - requires careful design before implementing pause.

---

## Common Mistakes

Less critical but still problematic patterns that cause technical debt or user confusion.

### Mistake 1: Polling-Based Dashboard Updates

**What goes wrong:** Dashboard fetches experiment state via HTTP polling instead of using the existing SocketIO infrastructure, creating unnecessary load and stale data.

**Why it happens:** Developers default to familiar REST patterns; adding dashboard-specific SocketIO events seems like more work.

**Consequences:**
- Server handles N extra HTTP requests per second per admin viewer
- Dashboard shows data that's up to [polling_interval] stale
- Two different data paths to maintain (REST + SocketIO)

**Prevention:**
1. Admin dashboard connects via SocketIO (to `/admin` namespace)
2. Server emits state updates to admin room on actual state changes
3. No polling - purely push-based updates
4. Reuse existing data structures (`GAME_MANAGERS`, `STAGERS`, etc.) - just project them for admin view

---

### Mistake 2: Blocking Admin Event Handlers

**What goes wrong:** Admin event handlers (e.g., "get all participants") perform expensive operations synchronously, blocking the SocketIO worker and degrading participant experience.

**Why it happens:** Admin queries seem low-priority, so blocking seems acceptable. But Flask-SocketIO with eventlet uses cooperative multitasking.

**Consequences:**
- Participant actions delayed while admin query runs
- Timeout errors for participants during admin operations
- Server appears to "hang" briefly

**Prevention:**
1. Admin queries should use `socketio.start_background_task()` for expensive operations
2. Emit results asynchronously when ready
3. Keep admin event handlers non-blocking (< 10ms)
4. Paginate large result sets (don't fetch all 1000 participants at once)

---

### Mistake 3: Dashboard UI Showing Raw Internal State

**What goes wrong:** Dashboard displays raw internal identifiers (UUIDs, socket IDs) instead of meaningful information, making it hard to identify specific participants or games.

**Why it happens:** Internal state is convenient to expose; creating human-readable projections requires extra work.

**Consequences:**
- Admins can't identify participants ("which UUID is the person who emailed me?")
- Copying wrong ID for admin actions
- Screenshots for reports contain meaningless strings

**Prevention:**
1. Map UUIDs to human-readable identifiers where possible (or allow custom labels)
2. Show context: scene name, game status, time in current state
3. Use consistent formatting (not raw JSON dumps)
4. Include search/filter by meaningful attributes

---

### Mistake 4: No Confirmation for Destructive Actions

**What goes wrong:** Admin accidentally kicks wrong participant or clears data without confirmation prompt.

**Why it happens:** Speed of implementation; "admins know what they're doing" assumption.

**Consequences:**
- Accidentally terminated experiments
- Lost data
- Participant complaints
- Trust erosion in the tool

**Prevention:**
1. Two-step confirmation for destructive actions (kick, clear, restart)
2. Show target information in confirmation ("Kick participant ABC from game XYZ?")
3. Add undo capability where possible (or at least audit trail)
4. Rate limit destructive actions (prevent accidental button mashing)

---

## Performance Pitfalls

Things that could slow down the system or degrade participant experience.

### Pitfall 1: Console Log Streaming Floods Server

**What goes wrong:** Client-side console log capture sends every `console.log` to the server in realtime, creating massive traffic volume that saturates the connection and delays game state updates.

**Why it happens:** console.log is synchronous and can fire thousands of times per second during game loops. Naive implementation sends each one immediately.

**Consequences:**
- Server bandwidth exhausted by log traffic
- Game state updates delayed (same SocketIO connection)
- Browser performance degradation (synchronous emission)
- Server memory exhaustion (unbounded log queue)

**Warning signs:**
- Network tab shows constant small messages
- Game feels laggy when dev tools are open
- Server memory grows unbounded
- Participants report worse experience than dev/test

**Prevention:**
1. **Buffer logs client-side** - accumulate for 100-500ms before sending batch
2. **Rate limit** - max N log batches per second (e.g., 2-5)
3. **Sampling** - for very high-frequency logs, sample 1-in-N
4. **Level filtering** - only capture warn/error by default, debug opt-in
5. **Size limits** - truncate individual log entries, cap batch size
6. **Separate channel** - if possible, use different transport than game state (lower priority)

**Phase to address:** Debug log viewer phase - design buffering from the start.

**Reference:** [Console.log performance impact](https://medium.com/@xiaweiliang94/why-you-should-think-twice-before-using-console-log-and-tips-for-avoiding-performance-pitfalls-1228efc27360)

---

### Pitfall 2: Dashboard Queries Scanning All State

**What goes wrong:** Every dashboard refresh scans all `STAGERS`, `GAME_MANAGERS`, `PARTICIPANT_SESSIONS` to build the view, O(n) for n participants.

**Why it happens:** Current data structures are optimized for lookup-by-ID, not for aggregate queries ("all participants in scene X").

**Consequences:**
- Dashboard refresh time grows linearly with participant count
- At scale (100+ concurrent), each refresh takes seconds
- Multiple admin viewers multiply the load

**Prevention:**
1. Maintain secondary indexes for common queries (by scene, by status)
2. Use incremental updates - only send changes, not full state
3. Server-side filtering before emission (don't send all data to client)
4. Cache dashboard state, invalidate on relevant events

---

### Pitfall 3: High-Frequency State Emissions to Dashboard

**What goes wrong:** Dashboard receives game state updates at the same frequency as participants (30+ fps), even though admins only need ~1 Hz updates.

**Why it happens:** Reusing participant event emissions for dashboard seems efficient.

**Consequences:**
- Admin browsers struggle with update frequency
- Unnecessary server-to-admin traffic
- Dashboard UI becomes sluggish/unresponsive

**Prevention:**
1. Dashboard subscriptions are throttled (1-2 updates/sec max)
2. Aggregate statistics instead of raw state
3. Admin can opt-in to higher frequency for specific game if needed
4. Different event names for dashboard vs. participant updates

---

## Security Pitfalls

Access control and data exposure risks.

### Pitfall 1: No Authentication on Admin Routes/Events

**What goes wrong:** Admin dashboard accessible to anyone who knows the URL, admin SocketIO events can be emitted by any connected client.

**Why it happens:** Internal tools often skip auth for "convenience"; assumption that only researchers have the URL.

**Consequences:**
- Participants discover admin interface
- Bad actors disrupt experiments
- Research data exposed
- Potential for data manipulation

**Warning signs:**
- No login prompt for admin dashboard
- SocketIO events work without session validation
- Admin URLs are guessable (`/admin`, `/dashboard`)

**Prevention:**
1. Admin routes require authentication (Flask-Login, session-based)
2. Admin SocketIO namespace validates session on connect
3. Every admin event handler checks authorization
4. Consider IP allowlist for admin access
5. Log all admin access attempts (successful and failed)

**Phase to address:** Foundation phase - security first, before any functionality.

---

### Pitfall 2: Admin Actions Not Authorized by Subject

**What goes wrong:** All admins can perform all actions on any participant/game, no granular permissions.

**Why it happens:** Single "admin" role seems sufficient initially.

**Consequences:**
- Experimenter A accidentally affects Experimenter B's participants
- No accountability for who did what
- Over-privileged access increases risk

**Prevention:**
1. Consider experiment-scoped admin access (admin sees only their experiments)
2. Role levels: viewer (read-only), operator (message/pause), admin (kick/modify)
3. Action authorization checks experiment ownership
4. Audit log includes admin identity (from session, not client-provided)

---

### Pitfall 3: Participant Data Exposed in Dashboard

**What goes wrong:** Dashboard shows more participant data than necessary (full responses, PII, etc.) when admins only need operational data.

**Why it happens:** Easiest to dump full state; filtering requires intentional design.

**Consequences:**
- PII visible to users who shouldn't see it
- IRB protocol violations
- Data breach risk if dashboard compromised

**Prevention:**
1. Dashboard shows operational data only by default (status, timing, scene)
2. Detailed data access requires higher permission level
3. Never expose raw `interactiveGymGlobals` without filtering
4. Consider data masking for sensitive fields

---

## Prevention Strategies Summary

| Pitfall | Prevention | Phase |
|---------|------------|-------|
| Admin actions racing with game state | Use existing locks, route through standard handlers | Foundation |
| Unlogged interventions | AdminAuditLog before any action executes | Core Intervention |
| Namespace leaking | Separate `/admin` namespace with auth | Foundation |
| Pause/resume corruption | Freeze all clocks, clear buffers, emit sync | Intervention Controls |
| Polling-based updates | Push-only via SocketIO | Foundation |
| Blocking handlers | Background tasks, async patterns | Core Dashboard |
| Raw internal state display | Human-readable projections | Dashboard UI |
| No confirmation dialogs | Two-step confirm for destructive actions | Dashboard UI |
| Console log floods | Client-side buffering, rate limits | Debug Log Viewer |
| Full state scans | Secondary indexes, incremental updates | Core Dashboard |
| High-frequency dashboard updates | Throttle to 1-2 Hz | Core Dashboard |
| No admin auth | Session-based auth on routes and events | Foundation |
| No action authorization | Experiment-scoped permissions | Foundation |
| PII exposure | Data filtering, permission levels | Core Dashboard |

---

## Phase-Specific Warnings

| Phase | Likely Pitfall | Mitigation |
|-------|----------------|------------|
| Foundation | Security bypass, namespace mixing | Establish auth and namespace separation first |
| Core Dashboard | Performance degradation, blocking queries | Use push model, background tasks from start |
| Intervention Controls | State corruption, desync | Route through existing handlers, extensive testing |
| Debug Log Viewer | Server flooding, participant impact | Implement buffering before capture |
| Multiplayer View | Scale issues, complex queries | Secondary indexes, pagination |

---

## Sources

### Official Documentation
- [Flask-SocketIO API Reference - Namespaces](https://flask-socketio.readthedocs.io/en/latest/api.html)
- [Socket.IO Namespaces](https://socket.io/docs/v4/namespaces/)

### Security
- [OWASP Top 10 2025 - Broken Access Control](https://owasp.org/Top10/2025/A01_2025-Broken_Access_Control/)
- [Invicti - Broken Access Control Detection](https://www.invicti.com/blog/web-security/broken-access-control)

### Performance
- [Console.log Performance Impact](https://medium.com/@xiaweiliang94/why-you-should-think-twice-before-using-console-log-and-tips-for-avoiding-performance-pitfalls-1228efc27360)
- [Flask-SocketIO Performance Discussion](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/2049)

### Research Data Integrity
- [Principles for Monitoring Data Collection Integrity in Clinical Trials](https://pmc.ncbi.nlm.nih.gov/articles/PMC3272671/)
- [Data Reliability and Treatment Integrity Monitoring](https://pmc.ncbi.nlm.nih.gov/articles/PMC2846587/)

### WebSocket/Real-time
- [WebSockets Race Conditions Research](https://portswigger.net/research/smashing-the-state-machine)
- [Dashboard Design Pitfalls](https://moldstud.com/articles/p-avoiding-common-mistakes-in-datadog-dashboard-design-for-enhanced-performance-and-user-experience)
