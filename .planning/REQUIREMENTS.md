# Requirements: Interactive Gym v1.2 Participant Exclusion

**Defined:** 2026-01-21
**Core Value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.

## v1.2 Requirements

Requirements for v1.2 Participant Exclusion milestone. Each maps to roadmap phases.

### Entry Screening

- [ ] **ENTRY-01**: Researcher can configure device type exclusion (mobile/desktop/both allowed)
- [ ] **ENTRY-02**: Researcher can configure browser type requirements (e.g., require Chrome/Firefox, block Safari)
- [ ] **ENTRY-03**: Researcher can configure ping threshold for entry (exclude if latency > N ms)
- [ ] **ENTRY-04**: Participant sees configurable message explaining why they were excluded at entry

### Continuous Monitoring

- [ ] **MONITOR-01**: System continuously monitors participant ping during gameplay
- [ ] **MONITOR-02**: Participant excluded mid-game if ping exceeds threshold for sustained period
- [ ] **MONITOR-03**: System detects when participant switches to another tab
- [ ] **MONITOR-04**: Tab switch triggers configurable warning or exclusion

### Multiplayer Handling

- [ ] **MULTI-01**: When one player excluded, the other player receives clear notification ("Your partner experienced a technical issue")
- [ ] **MULTI-02**: Game terminates cleanly for both players when one is excluded
- [ ] **MULTI-03**: Valid game data up to exclusion point is preserved and marked as partial session

### Extensibility

- [ ] **EXT-01**: Researcher can define custom exclusion rules via Python callback functions
- [ ] **EXT-02**: Custom callbacks receive participant context (ping, browser, focus state, etc.)
- [ ] **EXT-03**: Custom callbacks return exclusion decision with optional message

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Entry Screening

- **ENTRY-05**: Researcher can configure screen size minimum requirement
- **ENTRY-06**: Researcher can exclude based on connection type (P2P vs TURN vs fallback)

### Continuous Monitoring

- **MONITOR-05**: System detects participant inactivity (no inputs for N seconds)
- **MONITOR-06**: System detects disconnect patterns (multiple reconnects indicate unstable environment)

### Extensibility

- **EXT-04**: Each built-in rule has its own configurable participant-facing message
- **EXT-05**: GameCallback.on_exclusion() hook for researcher custom handling
- **EXT-06**: Exclusion analytics export (rate by rule, time, browser)
- **EXT-07**: Grace period warning system before exclusion (warn, then exclude if persists)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Duplicate Prolific/MTurk prescreeners | Handled by recruitment platforms; duplicating creates maintenance burden |
| Auto-rejection on first attention check | Research shows 61% of failures may be false positives |
| Complex rule engine (AND/OR/NOT operators) | Over-engineering; custom callbacks handle complex logic |
| Browser fingerprinting for repeat detection | Privacy/GDPR concerns; recruitment platforms track this |
| Mandatory fullscreen enforcement | Safari has keyboard issues in fullscreen; creates friction |
| Webcam/microphone permission blocking | Only check when experiment actually uses A/V |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| ENTRY-01 | TBD | Pending |
| ENTRY-02 | TBD | Pending |
| ENTRY-03 | TBD | Pending |
| ENTRY-04 | TBD | Pending |
| MONITOR-01 | TBD | Pending |
| MONITOR-02 | TBD | Pending |
| MONITOR-03 | TBD | Pending |
| MONITOR-04 | TBD | Pending |
| MULTI-01 | TBD | Pending |
| MULTI-02 | TBD | Pending |
| MULTI-03 | TBD | Pending |
| EXT-01 | TBD | Pending |
| EXT-02 | TBD | Pending |
| EXT-03 | TBD | Pending |

**Coverage:**
- v1.2 requirements: 14 total
- Mapped to phases: 0 (pending roadmap)
- Unmapped: 14

---
*Requirements defined: 2026-01-21*
*Last updated: 2026-01-21 after initial definition*
