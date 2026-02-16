# Requirements: Multi-User Gymnasium (MUG)

**Defined:** 2026-02-13
**Core Value:** Researchers can deploy interactive simulation experiments to the browser with minimal friction

## v1.1 Requirements (Complete)

All v1.1 requirements shipped 2026-02-16. See MILESTONES.md for details.

- [x] **CLEAN-01**: Remove `ServerGameRunner` class and all references — Phase 92
- [x] **CLEAN-02**: Remove `server_authoritative` flag from `PyodideGameCoordinator` — Phase 92
- [x] **CLEAN-03**: Remove obsolete server-auth multiplayer config options — Phase 92
- [x] **CLEAN-04**: Clean up `RemoteGameV2` for server-side game runner role — Phase 92
- [x] **PIPE-01**: Server game loop runs at max speed with latest action or default — Phase 93
- [x] **PIPE-02**: Server calls `env.render(render_mode="interactive_gym")` after each step — Phase 93
- [x] **PIPE-03**: Server broadcasts rendering state to clients via socket event — Phase 93
- [x] **PIPE-04**: Server receives client actions via socket event — Phase 93
- [x] **PIPE-05**: Server handles episode transitions and notifies clients — Phase 93
- [x] **CLNT-01**: Client buffers incoming render states from server — Phase 94
- [x] **CLNT-02**: Client renders buffered states at target FPS — Phase 94
- [x] **CLNT-03**: Client supports configurable input delay — Phase 94
- [x] **CLNT-04**: Client sends actions to server on keypress — Phase 94
- [x] **CLNT-05**: Client handles episode reset and game complete events — Phase 94
- [x] **TEST-01**: Unit tests for server game loop lifecycle — Phase 95
- [x] **TEST-02**: Integration test for action-step-render-broadcast flow — Phase 95
- [x] **TEST-03**: E2E Playwright test for server-auth two-player game — Phase 95
- [x] **TEST-04**: E2E test verifying P2P mode still works — Phase 95
- [x] **EXMP-01**: CoGrid Overcooked example for server-authoritative mode — Phase 95

## v1.2 Requirements

Requirements for Test Suite Green milestone. Fix root cause bugs — do not modify tests.

### Scene Transitions

- [ ] **SCNE-01**: Out-of-focus player advances to the next scene after episode completion (scene stager triggers transition even when tab is backgrounded)
- [ ] **SCNE-02**: CSV data export files are written for both players after episode completes under latency conditions
- [ ] **SCNE-03**: CSV data export files are written for both players after episode completes with focus loss at episode boundary

### Rollback

- [ ] **RLBK-01**: Deep rollback after extended tab-hide (6+ seconds) reaches expected depth (>=150 frames)

### Server-Auth E2E

- [ ] **SAUTH-01**: Server-auth E2E game with two browser clients completes an episode within timeout (end_game event reaches clients and triggers scene transition)

## Future Requirements

Deferred to future release. Tracked but not in current roadmap.

### Performance

- **PERF-01**: Adaptive input delay based on measured RTT
- **PERF-02**: Delta compression for rendering state broadcasts (send only changes)

### Features

- **FEAT-01**: Turn-based stepping mode (server waits for action before stepping)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Test modifications | Tests are correct — fix root cause bugs in the code |
| New features | v1.2 is purely about getting all tests green |
| Timing threshold adjustments | Round is 15s, 30s export timeout is generous — fix the bug |
| Adaptive input delay | Fixed delay is sufficient |
| New environment types | Existing support is sufficient |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCNE-01 | Phase 96 | Pending |
| SCNE-02 | Phase 96 | Pending |
| SCNE-03 | Phase 96 | Pending |
| RLBK-01 | Phase 97 | Pending |
| SAUTH-01 | Phase 98 | Pending |

**Coverage:**
- v1.2 requirements: 5 total
- Mapped to phases: 5
- Unmapped: 0

---
*Requirements defined: 2026-02-13*
*Last updated: 2026-02-16 after v1.2 roadmap creation*
