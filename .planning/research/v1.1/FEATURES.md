# Features Research: Admin Dashboard

**Domain:** Experiment Monitoring for Browser-Based Research
**Researched:** 2026-01-19
**Overall Confidence:** HIGH

## Executive Summary

Admin dashboards for research experiments with human participants have a well-established feature landscape. Table stakes features center on **real-time participant visibility** (who's connected, where they are in the experiment, their status), **session management** (pause, kick, message), and **data export** capabilities. Research platforms like JATOS, oTree, Gorilla, and Prolific have converged on similar patterns: centralized participant lists with status indicators, configurable metrics per study/scene, and intervention controls for handling dropouts or misbehaving participants.

For Interactive Gym's v1.1, the core value proposition is enabling researchers to **monitor live experiments without interrupting them** and **intervene when participants need assistance** (stuck, disconnected, or paired with problematic partners). The existing Flask-SocketIO architecture provides an ideal foundation since participant state (STAGERS, PARTICIPANT_SESSIONS, GAME_MANAGERS) is already centralized server-side.

Critical differentiators from generic admin dashboards: **multiplayer-aware grouping views** (essential for pairing-based experiments) and **client-side debug log capture** (browser console errors are invisible to researchers without explicit tooling).

---

## Table Stakes Features

Features that are **essential** for a research experiment admin dashboard. Without these, the dashboard is unusable for its core purpose.

### 1. Participant Overview Table

| Aspect | Details |
|--------|---------|
| **Description** | Real-time table showing all connected participants with current scene, status (connected/disconnected), and experiment progress |
| **Why Essential** | Researchers cannot run experiments blind; must know who's connected and where they are |
| **Complexity** | **Low** - Data already exists in PARTICIPANT_SESSIONS and STAGERS |
| **Key columns** | subject_id, current_scene, is_connected, scene_index/total_scenes, last_seen timestamp |
| **Update frequency** | Push on state change, no polling needed |

**Reference:** JATOS provides a Study Manager displaying participant count, study status, and active sessions. Gorilla's Participants tab shows "the status of all your participants so that you can manage attrition" ([source](https://support.gorilla.sc/support/tools/experiment-builder)).

### 2. Connection Status Indicators

| Aspect | Details |
|--------|---------|
| **Description** | Visual badges (green/yellow/red) showing connection health for each participant |
| **Why Essential** | Disconnections are the #1 data collection issue; researchers need instant visibility |
| **Complexity** | **Low** - Already track is_connected in ParticipantSession; add last_ping timestamp |
| **States** | Connected (green), Reconnecting (yellow), Disconnected (red), Completed (gray) |

**Reference:** CloudResearch shows "how many participants have dropped out" with real-time tracking ([source](https://www.cloudresearch.com/resources/research/how-mturk-toolkit-enhances-research-studies/)).

### 3. Waiting Room Population View

| Aspect | Details |
|--------|---------|
| **Description** | Show how many participants are in each waiting room, with wait duration |
| **Why Essential** | Multiplayer experiments fail if participants wait too long; researchers need to see queue state |
| **Complexity** | **Low** - Data exists in GameManager.waiting_games and group_waitrooms |
| **Key metrics** | Participants waiting, target group size, time waiting, timeout countdown |

**Reference:** Interactive Gym already broadcasts waiting_room status to participants; admin view exposes same data.

### 4. Basic Intervention: Kick Participant

| Aspect | Details |
|--------|---------|
| **Description** | Remove a participant from the experiment with optional redirect URL |
| **Why Essential** | Researchers must handle misbehaving participants (bots, AFK, policy violations) |
| **Complexity** | **Medium** - Need to gracefully disconnect, notify partners, trigger redirect |
| **Confirmation** | Require click confirmation; irreversible action |

**Reference:** oTree admin interface includes "deactivate" functionality: "an admin can deactivate it by clicking the switch... A deactivated study cannot be started by participants anymore" ([source](https://www.jatos.org/Administration.html)).

### 5. Data Export Access

| Aspect | Details |
|--------|---------|
| **Description** | Download collected data as CSV from admin panel without server SSH access |
| **Why Essential** | Researchers need data during/after experiments for validation and analysis |
| **Complexity** | **Low** - Data already saved to data/{scene_id}/*.csv; add download route |
| **Format** | Per-scene CSV, metadata JSON, combined experiment-wide export |

**Reference:** Every research platform (Qualtrics, JATOS, oTree, Gorilla) provides "Export to CSV" functionality from the admin interface ([source](https://www.userinterviews.com/support/download-participant-data)).

### 6. Experiment Pause/Resume

| Aspect | Details |
|--------|---------|
| **Description** | Temporarily stop accepting new participants while keeping existing sessions active |
| **Why Essential** | Researchers need to halt recruitment if issues discovered mid-experiment |
| **Complexity** | **Low** - Add global flag checked in user_index route |
| **Behavior** | Existing participants continue; new arrivals see "experiment paused" message |

**Reference:** CloudResearch: "When you pause a study, any participants who are active in the study at the time of the pause will have an opportunity to complete the study" ([source](https://go.cloudresearch.com/knowledge/pausing-your-study)).

---

## Nice to Have Features

Features that **improve the experience** but aren't critical for v1.1 launch.

### 7. Multiplayer Group View

| Aspect | Details |
|--------|---------|
| **Description** | Visual representation of which participants are paired/grouped together |
| **Why Essential** | Critical for debugging multiplayer issues; "why didn't they get matched?" |
| **Complexity** | **Medium** - Need to expose GROUP_MANAGER state and visualize relationships |
| **Display** | Group cards showing members, current scene, group status (playing/waiting/completed) |

**Rationale for Nice-to-Have:** Can launch with participant list alone; group view is enhancement for multiplayer debugging.

### 8. Debug Log Viewer

| Aspect | Details |
|--------|---------|
| **Description** | Capture and display console.log/error/warn from participant browsers |
| **Why Essential** | JavaScript errors in participant browsers are invisible without explicit capture |
| **Complexity** | **High** - Requires client-side console interception + server storage + filtering UI |
| **Implementation** | Intercept console.* methods, batch send to server, display with filtering by participant/severity |

**Reference:** Bugfender describes the value: "monitor our users behaviour and see the problems they were facing in real-time" through remote console log capture ([source](https://bugfender.com/platforms/javascript/)).

**Rationale for Nice-to-Have:** High value but high complexity; participant overview provides core monitoring without it.

### 9. Send Message to Participant

| Aspect | Details |
|--------|---------|
| **Description** | Push a message to a specific participant's screen |
| **Why Essential** | Help stuck participants, provide instructions, notify of issues |
| **Complexity** | **Medium** - Need message display component on participant side, admin message input |
| **Display** | Modal or toast on participant screen with researcher's message |

**Reference:** Cognition.run offers "Live Monitoring" allowing researchers to "communicate via microphone" ([source](https://www.cognition.run/)).

### 10. Scene-Specific Metrics Dashboard

| Aspect | Details |
|--------|---------|
| **Description** | Configurable metrics panels showing per-scene statistics (completions, episodes, avg time) |
| **Why Essential** | Researchers want to see experiment progress and catch issues early |
| **Complexity** | **Medium** - Need metrics aggregation, scene-configurable displays, Chart.js integration |
| **Metrics** | Participants per scene, completion rate, avg duration, episode counts |

**Reference:** Clinical trial dashboards show "the count of participants who have completed each stage or action within the process, the rates of completion and trends" ([source](https://trialsjournal.biomedcentral.com/articles/10.1186/s13063-024-08646-0)).

### 11. Activity Timeline

| Aspect | Details |
|--------|---------|
| **Description** | Chronological log of experiment events (joins, scene advances, disconnects, completions) |
| **Why Essential** | Post-hoc debugging; "what happened at 2:15pm when data looks weird?" |
| **Complexity** | **Medium** - Need event logging, storage, filterable display |

### 12. Participant Notes

| Aspect | Details |
|--------|---------|
| **Description** | Researcher can add notes to individual participants (e.g., "flagged for review") |
| **Why Essential** | Track observations about specific participants during live experiments |
| **Complexity** | **Low** - Add notes field to PARTICIPANT_SESSIONS, inline editing in table |

---

## Anti-Features (Do NOT Build in v1.1)

Features to **explicitly avoid** building. Either over-scoped, wrong timing, or counterproductive.

### 1. Full Video Recording / Screen Capture

| Feature | Reason to Avoid |
|---------|-----------------|
| **What** | Record participant screens or webcams |
| **Why Avoid** | Massive privacy/consent implications; huge storage costs; out of scope for monitoring |
| **Instead** | Debug log viewer provides sufficient error capture without privacy issues |

### 2. Automated Fraud Detection / Bot Detection

| Feature | Reason to Avoid |
|---------|-----------------|
| **What** | AI-powered detection of bots, cheaters, or low-quality participants |
| **Why Avoid** | Complex, error-prone, can create false positives; Prolific/CloudResearch handle this at recruitment |
| **Instead** | Manual kick functionality; trust recruitment platform screening |

### 3. Participant Chat / Support Ticket System

| Feature | Reason to Avoid |
|---------|-----------------|
| **What** | Two-way chat between researcher and participant |
| **Why Avoid** | Scope creep; changes experiment dynamics; researcher availability becomes bottleneck |
| **Instead** | One-way "send message" is sufficient for notifications |

### 4. Historical Data Analytics / Dashboards

| Feature | Reason to Avoid |
|---------|-----------------|
| **What** | Aggregated analytics across past experiments (completion rates over time, etc.) |
| **Why Avoid** | v1.1 is about live monitoring; analytics is post-experiment analysis (different tool) |
| **Instead** | Export data; use R/Python for analysis |

### 5. Multi-Researcher Permission System

| Feature | Reason to Avoid |
|---------|-----------------|
| **What** | Fine-grained roles (viewer, operator, admin) with per-experiment permissions |
| **Why Avoid** | Over-engineering for v1.1; most research teams are small with trusted members |
| **Instead** | Single admin password; revisit multi-user in v1.2+ if needed |

### 6. Mobile-Optimized Admin Interface

| Feature | Reason to Avoid |
|---------|-----------------|
| **What** | Responsive design for monitoring from phones |
| **Why Avoid** | Researchers monitor from desktops during experiments; mobile optimization is polish not core |
| **Instead** | Desktop-first; basic functionality on tablets |

### 7. Experiment Design/Configuration from Admin Panel

| Feature | Reason to Avoid |
|---------|-----------------|
| **What** | Create/edit scenes, configure policies from web UI |
| **Why Avoid** | Experiments are code-defined; admin panel is for monitoring not authoring |
| **Instead** | Keep experiment definition in Python; admin panel is read-only + intervention |

### 8. Push Notifications to Researcher Phones

| Feature | Reason to Avoid |
|---------|-----------------|
| **What** | SMS/push alerts when participants disconnect or errors occur |
| **Why Avoid** | Requires external services (Twilio, etc.); complicates deployment; overkill for v1.1 |
| **Instead** | Browser-based alerts when admin dashboard is open |

---

## Feature Dependencies

Features that **require other features** to be built first.

```
DEPENDENCIES:

Participant Overview Table (1)
    |
    +-- Waiting Room View (3)          # Depends on participant state
    +-- Multiplayer Group View (7)      # Depends on participant-to-group mapping
    +-- Connection Status (2)           # Enhances participant table
    |
    +-- Kick Participant (4)            # Operates on participant from table
    +-- Send Message (9)                # Operates on participant from table
    +-- Participant Notes (12)          # Attaches to participant records

Experiment Pause/Resume (6)
    # Independent; no dependencies

Data Export (5)
    # Independent; accesses existing data files

Debug Log Viewer (8)
    |
    +-- Requires client-side interception first (participant JS changes)
    +-- Requires server-side log storage
    +-- Requires filtering UI

Scene Metrics (10)
    |
    +-- Requires metrics aggregation system
    +-- Requires Chart.js integration (already chosen in STACK.md)

Activity Timeline (11)
    |
    +-- Requires event logging infrastructure
    +-- Can be built on existing server logs or new event store
```

**Build Order Recommendation:**

1. **Phase 1 (Core):** Participant Overview Table, Connection Status, Experiment Pause
2. **Phase 2 (Control):** Kick Participant, Data Export, Waiting Room View
3. **Phase 3 (Multiplayer):** Group View, Send Message
4. **Phase 4 (Debug):** Debug Log Viewer, Activity Timeline
5. **Phase 5 (Polish):** Scene Metrics, Participant Notes

---

## Complexity Assessment

| Feature | Complexity | Rationale |
|---------|------------|-----------|
| **Participant Overview Table** | Low | Data exists in PARTICIPANT_SESSIONS; render with Tabulator |
| **Connection Status Indicators** | Low | Add last_ping to session; simple badge logic |
| **Waiting Room View** | Low | Expose existing GameManager.waiting_games data |
| **Kick Participant** | Medium | Need graceful disconnect, partner notification, redirect |
| **Data Export** | Low | Already saving CSVs; add Flask route to serve files |
| **Experiment Pause** | Low | Global flag in app config; check on new connections |
| **Multiplayer Group View** | Medium | Need to visualize GROUP_MANAGER relationships |
| **Debug Log Viewer** | High | Client-side interception, server storage, filtering UI |
| **Send Message** | Medium | Client-side toast component, admin input, SocketIO emit |
| **Scene Metrics** | Medium | Aggregation logic, Chart.js integration, scene config |
| **Activity Timeline** | Medium | Event logging, storage, time-based filtering |
| **Participant Notes** | Low | Add notes field, inline editing in Tabulator |

---

## Minimum Viable Admin Dashboard (MVP)

For v1.1, ship features that provide the **core monitoring loop**:

| Feature | Priority | Complexity |
|---------|----------|------------|
| Participant Overview Table | P0 | Low |
| Connection Status Indicators | P0 | Low |
| Experiment Pause/Resume | P0 | Low |
| Kick Participant | P1 | Medium |
| Data Export | P1 | Low |
| Waiting Room View | P1 | Low |

**MVP enables:** "I can see who's connected, pause if something's wrong, kick bad actors, and download my data."

**Defer to v1.2:**
- Debug Log Viewer (high complexity)
- Group View (multiplayer polish)
- Scene Metrics (analytics, not monitoring)
- Activity Timeline (post-hoc debugging)

---

## Sources

### Research Platform Documentation
- [JATOS Administration](https://www.jatos.org/Administration.html) - Study activation/deactivation, user management
- [Gorilla Experiment Builder](https://gorilla.sc/) - Participant tab, checkpoint nodes, attrition management
- [CloudResearch Study Pausing](https://go.cloudresearch.com/knowledge/pausing-your-study) - Pause behavior with active participants
- [oTree Admin Interface](https://otree.readthedocs.io/en/latest/mturk.html) - MTurk/Prolific integration, admin features

### Real-Time Monitoring Research
- [Clinical Trial Monitoring Dashboard](https://trialsjournal.biomedcentral.com/articles/10.1186/s13063-024-08646-0) - Metrics, completion tracking, control charts
- [Cognition.run Live Monitoring](https://www.cognition.run/) - Real-time participant observation
- [QuestionPro Real-Time Reports](https://www.questionpro.com/features/real-time-reports.html) - Dashboard completion tracking

### Remote Logging
- [Bugfender JavaScript Logging](https://bugfender.com/platforms/javascript/) - Remote console log capture patterns
- [Acumen Logs Synthetic Monitoring](https://www.acumenlogs.com/post/catching-javascript-console-errors-with-synthetic-monitoring) - Browser error capture

### A/B Experiment Dashboards
- [Amplitude Experiment Dashboard](https://amplitude.com/templates/ab-experiment-dashboard-template) - Funnel performance, metrics
- [Optimizely Reporting Dashboards](https://support.optimizely.com/hc/en-us/articles/34545831762829-Experimentation-reporting-dashboards-overview) - Experiment status tracking

### Intervention Patterns
- [Statsig Stop New Assignment](https://www.statsig.com/updates/update/pause-xp-assign) - Halting enrollment while continuing analysis
- [jsPsych Pause Discussion](https://github.com/jspsych/jsPsych/discussions/1284) - Client-side pause on tab blur
