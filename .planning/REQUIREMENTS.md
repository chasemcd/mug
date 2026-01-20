# Requirements: Interactive Gym v1.1 Admin Console

**Defined:** 2026-01-19
**Core Value:** Real-time experiment monitoring and light intervention capabilities for researchers running experiments.

## v1.1 Requirements

Requirements for the admin console milestone. Each maps to roadmap phases.

### Infrastructure

- [x] **INFRA-01**: Admin can access dashboard at `/admin` route ✓
- [x] **INFRA-02**: Admin dashboard requires authentication before access ✓

### Monitoring

- [x] **MON-01**: Admin can view table of all participants with subject ID, current scene, and experiment progress ✓
- [x] **MON-02**: Admin can see connection status indicators (connected/reconnecting/disconnected/completed) for each participant ✓
- [x] **MON-03**: Admin can view waiting room population (participants waiting, target group size, wait duration) ✓
- [x] **MON-04**: Admin can view chronological activity timeline of experiment events (joins, scene advances, disconnects) ✓

### Intervention

- [ ] **INT-01**: Admin can kick a participant from the experiment with confirmation dialog

### Data Access

- [ ] **DATA-01**: Admin can download collected data as CSV from the admin panel

### Multiplayer

- [ ] **MULTI-01**: Admin can view multiplayer groups (who's paired with whom, group status)

### Debug

- [ ] **DEBUG-01**: Admin can view debug logs captured from participant browsers (console.log/error/warn)
- [ ] **DEBUG-02**: Admin can filter debug logs by participant and severity level

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Intervention

- **INT-02**: Admin can pause/resume experiment (halt new enrollments)
- **INT-03**: Admin can send message to specific participant

### Monitoring

- **MON-05**: Admin can add notes to individual participants
- **MON-06**: Admin can view scene-specific metrics (completions, episodes, avg time)

### Infrastructure

- **INFRA-03**: All admin actions are logged to audit trail for research validity

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Video recording / screen capture | Privacy/consent implications; huge storage costs |
| Automated fraud/bot detection | Complex, error-prone; recruitment platforms (Prolific, CloudResearch) handle this |
| Bi-directional participant chat | Scope creep; changes experiment dynamics; researcher availability bottleneck |
| Historical analytics dashboards | v1.1 is live monitoring; use R/Python for post-experiment analysis |
| Multi-researcher permissions | Over-engineering for v1.1; single admin password sufficient for small teams |
| Mobile-optimized interface | Desktop-first; researchers monitor from desktops during experiments |
| Experiment design from admin panel | Experiments are code-defined; admin is for monitoring not authoring |
| Push notifications to phones | External service complexity (Twilio); overkill for v1.1 |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 7 | Complete |
| INFRA-02 | Phase 7 | Complete |
| MON-01 | Phase 8 | Complete |
| MON-02 | Phase 8 | Complete |
| MON-03 | Phase 8 | Complete |
| MON-04 | Phase 8 | Complete |
| INT-01 | Phase 9 | Pending |
| DATA-01 | Phase 9 | Pending |
| MULTI-01 | Phase 10 | Pending |
| DEBUG-01 | Phase 10 | Pending |
| DEBUG-02 | Phase 10 | Pending |

**Coverage:**
- v1.1 requirements: 11 total
- Mapped to phases: 11 ✓
- Unmapped: 0

---
*Requirements defined: 2026-01-19*
*Last updated: 2026-01-20 after Phase 8 completion (MON-01, MON-02, MON-03, MON-04 complete)*
