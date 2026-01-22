---
phase: 23-partner-disconnect-handling
plan: 01
subsystem: multiplayer-ux
tags: [disconnect-handling, in-page-overlay, data-export, config-api]
dependency-graph:
  requires:
    - "Phase 20: Mid-game reconnection infrastructure"
    - "Phase 17: Partial session marking"
  provides:
    - "In-page partner disconnection overlay"
    - "partner_disconnect_message_config() API"
    - "disconnectedPlayerId in exported metrics"
  affects:
    - "Future: Custom disconnect callbacks"
tech-stack:
  added: []
  patterns:
    - "In-page overlay (no redirect) for session termination"
    - "Config API method pattern (NotProvided default)"
key-files:
  created: []
  modified:
    - interactive_gym/scenes/gym_scene.py
    - interactive_gym/server/static/js/pyodide_multiplayer_game.js
    - interactive_gym/server/app.py
    - interactive_gym/server/pyodide_game_coordinator.py
decisions:
  - id: ui-overlay-not-redirect
    context: "Partner disconnects mid-game"
    choice: "In-page overlay instead of page redirect"
    rationale: "Keeps participant on same page, preserves data, better UX"
metrics:
  duration: 3m 48s
  completed: 2026-01-22
---

# Phase 23 Plan 01: Partner Disconnect Handling Implementation Summary

In-page partner disconnection handling with configurable messages and complete data export.

## Objective

Implement in-page partner disconnection handling that keeps participants on the same page with a configurable message overlay, exports all data with disconnection metadata, and marks the session as partial.

## Completed Tasks

| # | Task | Commit | Key Changes |
|---|------|--------|-------------|
| 1 | Add GymScene config method and serialize to client | 3641548 | `partner_disconnect_message` attribute, `partner_disconnect_message_config()` method |
| 2 | Modify client to show in-page overlay with data export | 8985f16 | `_handleReconnectionGameEnd()` rewrite, `_showPartnerDisconnectedOverlay()` in-page overlay |
| 3 | Update server to include disconnected player ID | efcca80 | `disconnected_player_id` tracking, `get_disconnected_player_id()` method |

## Implementation Details

### Config API (CFG-01, CFG-02)

Added `partner_disconnect_message_config()` method to GymScene:

```python
scene.partner_disconnect_message_config(
    message="Your partner left the experiment. Thank you for participating."
)
```

- Default message: "Your partner has disconnected. The game has ended."
- Message automatically included in scene_metadata via `vars(self)` serialization
- Stored in client's `this.config.partner_disconnect_message`

### UI Changes (UI-01 through UI-04)

Replaced redirect-based handling with in-page overlay:

- **UI-01**: No redirect - participant stays on same page
- **UI-02**: Game container and HUD hidden via `display: none`
- **UI-03**: Overlay displays configurable message
- **UI-04**: Page remains indefinitely (no Continue button, no auto-redirect)

Overlay styling matches existing partner exclusion UI for visual consistency.

### Data Export (DATA-01 through DATA-04)

Complete data export before showing overlay:

- **DATA-01**: `emitMultiplayerMetrics()` called before overlay appears
- **DATA-02**: `sessionPartialInfo.isPartial = true` for partial sessions
- **DATA-03**: `sessionPartialInfo.terminationReason = 'partner_disconnected'`
- **DATA-04**: `sessionPartialInfo.disconnectedPlayerId` tracks who disconnected

Server-side tracking identifies disconnected player:
- `handle_connection_lost()` determines which player disconnected (the OTHER player, not the detector)
- `get_disconnected_player_id()` retrieves the ID for the `p2p_game_ended` event
- ID included in exported metrics for research analysis

## Verification Results

All 10 requirements satisfied:

**UI Handling:**
- [x] UI-01: Participant stays on same page when partner disconnects (no redirect)
- [x] UI-02: Game container and HUD hidden when partner disconnection detected
- [x] UI-03: Disconnection message displayed on same page after partner disconnects
- [x] UI-04: Page remains displayed indefinitely (participant closes when done)

**Data Export:**
- [x] DATA-01: All gameplay data collected before disconnection is exported to server
- [x] DATA-02: Session marked as partial in exported data when partner disconnects
- [x] DATA-03: Disconnection reason included in session metadata
- [x] DATA-04: Disconnected player ID included in session metadata

**Configuration:**
- [x] CFG-01: Researchers can set custom partner disconnect message via GymScene config
- [x] CFG-02: Default message provided when no custom message configured

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

| Decision | Context | Choice | Rationale |
|----------|---------|--------|-----------|
| In-page overlay | Partner disconnects | Overlay instead of redirect | Preserves data, better UX, participant controls when to leave |

## Next Phase Readiness

Phase 23 complete (single phase milestone).

**Milestone v1.4 Partner Disconnection Handling is complete.**

All key functionality delivered:
- Researchers can customize disconnect messages
- Participants see a clean overlay instead of being redirected
- All gameplay data is exported with full disconnection metadata
- Session marked as partial for proper data analysis

No blockers identified for future milestones.
