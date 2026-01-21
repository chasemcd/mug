# Research Summary: v1.1 Admin Console

**Project:** Interactive Gym — Admin Dashboard for Experiment Monitoring
**Researched:** 2026-01-19
**Overall Confidence:** HIGH

## Executive Summary

Research confirms the admin dashboard is a well-scoped, achievable milestone that leverages existing infrastructure. The existing Flask/SocketIO architecture already tracks all necessary data (`PARTICIPANT_SESSIONS`, `STAGERS`, `GAME_MANAGERS`, `PyodideGameCoordinator`) - the dashboard simply needs to expose this through a separate `/admin` namespace. The recommended stack (**HTMX + DaisyUI + Tabulator + Chart.js**) avoids introducing a separate frontend framework, keeping the codebase unified with existing Jinja2 templates.

Key insight: This is fundamentally a read-access layer over existing state, not new data collection. The challenge is **integration without disruption** and **intervention without corruption**.

---

## Key Findings by Dimension

### Stack (HIGH confidence)

- **Frontend:** HTMX 2.0.8 + DaisyUI 5/Tailwind 4 (no React/Vue needed)
- **Data tables:** Tabulator 6.x (MIT, lightweight, real-time friendly)
- **Charts:** Chart.js 4.x (~70KB, sufficient for simple metrics)
- **Real-time:** Flask-SocketIO `/admin` namespace (existing infrastructure)
- **Backend:** Flask Blueprint + Flask-Login (minimal additions)

**What NOT to use:** React/Vue (overkill), AG-Grid Enterprise (expensive), Plotly.js (3MB), Flask-Admin (opinionated)

### Features (HIGH confidence)

**Table Stakes (MVP):**
1. Participant Overview Table - Low complexity
2. Connection Status Indicators - Low complexity
3. Waiting Room View - Low complexity
4. Kick Participant - Medium complexity
5. Data Export - Low complexity
6. Experiment Pause/Resume - Low complexity

**Nice to Have (defer some to v1.2):**
- Multiplayer Group View - Medium complexity
- Debug Log Viewer - **High complexity** (client-side changes required)
- Send Message - Medium complexity
- Scene Metrics - Medium complexity

**Anti-Features (do NOT build):**
- Video recording, bot detection, bi-directional chat, historical analytics, multi-user permissions, mobile optimization, experiment authoring

### Architecture (HIGH confidence)

**Core components:**
1. `AdminNamespace` - Separate SocketIO namespace (`/admin`)
2. `AdminEventAggregator` - Observer pattern, reads existing state
3. `AdminDashboardBlueprint` - Flask routes for dashboard

**Key pattern:** Admin code observes existing state structures without modifying participant code paths. Use existing locks when intervening.

**Data flow:** Existing handlers emit to participants → Aggregator mirrors to admin namespace → Dashboard renders

### Pitfalls (MEDIUM confidence)

**Critical risks:**
1. **State corruption** - Admin actions racing with game state (use existing locks)
2. **Unlogged interventions** - Research data validity compromised (audit log FIRST)
3. **Namespace leaking** - Participants see admin events (separate namespace)
4. **Pause/resume desync** - Multiple clocks not frozen consistently

**Performance risks:**
- Console log capture flooding server (buffer + rate limit)
- Dashboard queries scanning all state (incremental updates)
- High-frequency emissions to dashboard (throttle to 1-2 Hz)

---

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 7: Admin Foundation
**Goal:** Establish secure admin infrastructure
- Admin SocketIO namespace (`/admin`) with authentication
- AdminEventAggregator skeleton (observer pattern)
- Flask Blueprint with basic dashboard route
- Admin audit logging infrastructure

**Addresses:** Security pitfalls, namespace isolation, audit trail
**Avoids:** Namespace leaking, no-auth access
**Uses:** HTMX, DaisyUI, Flask-Login

### Phase 8: Read-Only Dashboard
**Goal:** See all participants and experiment state
- Participant overview table (Tabulator)
- Connection status indicators
- Waiting room view
- Real-time push updates (1-2 Hz)

**Addresses:** Core monitoring need (table stakes features)
**Avoids:** Polling-based updates, blocking queries
**Uses:** Tabulator, Chart.js, SocketIO push

### Phase 9: Intervention Controls
**Goal:** Act on participant issues
- Kick participant (with confirmation + audit)
- Experiment pause/resume
- Data export from admin panel
- Send message to participant

**Addresses:** Light intervention requirement
**Avoids:** State corruption (use locks), unlogged actions (audit first)
**Requires:** Careful integration with existing game state handlers

### Phase 10: Debug & Multiplayer Views
**Goal:** Deeper visibility for troubleshooting
- Debug log viewer (client-side capture + server streaming)
- Multiplayer group view
- Scene-specific metrics

**Addresses:** Debug capability, multiplayer-specific monitoring
**Avoids:** Console log flooding (buffer + rate limit)
**Note:** Debug log viewer is HIGH complexity - may split into own phase

---

## Phase Ordering Rationale

1. **Foundation first** - Security and namespace separation MUST come before any functionality
2. **Read-only before intervention** - Reduces risk; provides value without corruption risk
3. **Core interventions before debug tools** - Kick/pause are higher priority than log viewing
4. **Debug/multiplayer last** - Highest complexity, builds on stable foundation

## Research Flags for Phases

| Phase | Research Needed? | Reason |
|-------|-----------------|--------|
| Phase 7 (Foundation) | LOW | Standard Flask patterns, well-documented |
| Phase 8 (Read-Only) | LOW | Existing data structures, just projecting |
| Phase 9 (Interventions) | MEDIUM | Lock integration patterns need careful design |
| Phase 10 (Debug/Groups) | HIGH | Client-side console capture is novel |

---

## Open Questions

1. **Authentication approach:** Simple password vs Flask-Login with sessions?
2. **Debug log viewer scope:** v1.1 or defer to v1.2 given high complexity?
3. **Eventlet deprecation:** Plan migration path to threading/gevent for v1.2+

---

## Files in This Research

| File | Contents |
|------|----------|
| [STACK.md](./STACK.md) | Technology recommendations with versions and rationale |
| [FEATURES.md](./FEATURES.md) | Feature landscape with table stakes, complexity, anti-features |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Component structure, data flow, integration points |
| [PITFALLS.md](./PITFALLS.md) | Critical risks and prevention strategies |

---

## Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| Stack choices | HIGH | Leverages existing infrastructure, well-documented patterns |
| Feature scope | HIGH | Industry consensus on research monitoring dashboards |
| Architecture | HIGH | Based on existing codebase analysis |
| Pitfall prevention | MEDIUM | Some risks require runtime validation |
| Phase structure | MEDIUM | Logical ordering, but effort estimates need phase research |

---

*Research complete. Proceed to `/gsd:define-requirements` to scope detailed requirements.*
