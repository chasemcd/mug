# Requirements: Interactive Gym v1.5 Focus Loss Handling

**Defined:** 2026-01-22
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1.5 Requirements

Requirements for v1.5 Focus Loss Handling milestone. Each maps to roadmap phases.

### Web Worker Timing

- [x] **WORK-01**: Game timing logic runs in Web Worker (unthrottled when backgrounded)
- [x] **WORK-02**: Worker maintains accurate game clock even when main thread is throttled

### Focus Detection

- [ ] **FOCUS-01**: Tab visibility changes detected via Page Visibility API
- [ ] **FOCUS-02**: Duration of each background period tracked

### Backgrounded Player Behavior

- [ ] **BG-01**: Backgrounded player's actions default to idle/no-op
- [ ] **BG-02**: Partner inputs buffered via WebRTC while backgrounded
- [ ] **BG-03**: On refocus, simulation fast-forwards using queued inputs to resync

### Partner Experience

- [ ] **PARTNER-01**: Focused partner experiences no interruption when other player backgrounds
- [ ] **PARTNER-02**: Focused partner sees backgrounded player go idle (inputs stop)

### Timeout & Messaging

- [ ] **TIMEOUT-01**: Configurable focus loss timeout before ending game (default 30s)
- [ ] **TIMEOUT-02**: Game ends for both players when timeout exceeded
- [ ] **TIMEOUT-03**: Configurable message displayed when game ends due to focus loss

### Research Telemetry

- [ ] **TELEM-01**: Focus loss events recorded in session metadata
- [ ] **TELEM-02**: Duration of each focus loss period included in metadata

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

(None for v1.5)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Pause for both on focus loss | User specified focused partner keeps playing seamlessly |
| Audio-based throttle prevention | No longer works in modern browsers (2025+) |
| Fullscreen enforcement | Not related to focus loss handling |
| Adaptive input delay | Deferred to future milestone |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| WORK-01 | Phase 24 | Complete |
| WORK-02 | Phase 24 | Complete |
| FOCUS-01 | Phase 25 | Pending |
| FOCUS-02 | Phase 25 | Pending |
| BG-01 | Phase 25 | Pending |
| BG-02 | Phase 25 | Pending |
| BG-03 | Phase 26 | Pending |
| PARTNER-01 | Phase 26 | Pending |
| PARTNER-02 | Phase 26 | Pending |
| TIMEOUT-01 | Phase 27 | Pending |
| TIMEOUT-02 | Phase 27 | Pending |
| TIMEOUT-03 | Phase 27 | Pending |
| TELEM-01 | Phase 27 | Pending |
| TELEM-02 | Phase 27 | Pending |

**Coverage:**
- v1.5 requirements: 14 total
- Mapped to phases: 14
- Unmapped: 0 ✓

---
*Requirements defined: 2026-01-22*
*Last updated: 2026-01-23 after Phase 24 execution*
