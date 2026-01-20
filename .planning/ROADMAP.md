# Roadmap: Interactive Gym

## Milestones

- **v1.0 P2P Multiplayer** - Phases 1-6 (shipped 2026-01-19)
- **v1.1 Admin Console** - Phases 7-10 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

<details>
<summary>v1.0 P2P Multiplayer (Phases 1-6) - SHIPPED 2026-01-19</summary>

See .planning/MILESTONES.md for v1.0 details.

**Delivered:** True peer-to-peer multiplayer with GGPO-style rollback netcode.
**Phases completed:** 1-6 (11 plans total)

</details>

### v1.1 Admin Console (In Progress)

**Milestone Goal:** Real-time experiment monitoring and light intervention capabilities for researchers running experiments.

- [x] **Phase 7: Admin Foundation** - Secure admin infrastructure with authentication
- [x] **Phase 8: Read-Only Dashboard** - Participant monitoring and experiment state visibility ✓
- [ ] **Phase 9: Intervention & Data** - Kick participants and download data
- [ ] **Phase 10: Debug & Multiplayer** - Debug log viewer and multiplayer group view

## Phase Details

### Phase 7: Admin Foundation
**Goal**: Establish secure admin infrastructure
**Depends on**: v1.0 complete (phases 1-6)
**Requirements**: INFRA-01, INFRA-02
**Success Criteria** (what must be TRUE):
  1. Admin can navigate to `/admin` and see a dashboard page
  2. Unauthenticated users are redirected to login when accessing `/admin`
  3. Admin can authenticate and access the dashboard
**Research**: Unlikely needed (standard Flask patterns)
**Plans**: 1

Plans:
- [x] 07-01: Secure admin infrastructure with authentication and namespace isolation

### Phase 8: Read-Only Dashboard
**Goal**: See all participants and experiment state in real-time
**Depends on**: Phase 7
**Requirements**: MON-01, MON-02, MON-03, MON-04
**Success Criteria** (what must be TRUE):
  1. Admin can see a table of all participants with subject ID, current scene, and progress
  2. Admin can see connection status (green/yellow/red) for each participant
  3. Admin can see how many participants are in each waiting room and how long they've waited
  4. Admin can see a chronological timeline of experiment events
**Research**: Unlikely needed (existing data structures, just projecting)
**Plans**: 2

Plans:
- [x] 08-01: Backend state aggregation (AdminEventAggregator + SocketIO emissions) ✓
- [x] 08-02: Frontend dashboard UI (participant table, status badges, waiting room view, timeline) ✓

### Phase 9: Intervention & Data
**Goal**: Act on participant issues and access data
**Depends on**: Phase 8
**Requirements**: INT-01, DATA-01
**Success Criteria** (what must be TRUE):
  1. Admin can kick a participant (with confirmation dialog)
  2. Kicked participant is gracefully disconnected and partners are notified
  3. Admin can download collected data as CSV from the dashboard
**Research**: May need research (lock integration patterns)
**Plans**: TBD

Plans:
- [ ] 09-01: TBD

### Phase 10: Debug & Multiplayer
**Goal**: Deeper visibility for troubleshooting
**Depends on**: Phase 9
**Requirements**: DEBUG-01, DEBUG-02, MULTI-01
**Success Criteria** (what must be TRUE):
  1. Admin can see debug logs captured from participant browsers (console.log/error/warn)
  2. Admin can filter debug logs by participant and severity level
  3. Admin can see which participants are grouped together in multiplayer games
**Research**: Likely needed (client-side console capture is novel)
**Plans**: TBD

Plans:
- [ ] 10-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 7 -> 8 -> 9 -> 10

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 7. Admin Foundation | v1.1 | 1/1 | Complete | 2026-01-19 |
| 8. Read-Only Dashboard | v1.1 | 2/2 | ✓ Complete | 2026-01-20 |
| 9. Intervention & Data | v1.1 | 0/TBD | Not started | - |
| 10. Debug & Multiplayer | v1.1 | 0/TBD | Not started | - |

---
*Created: 2026-01-19*
*Last updated: 2026-01-20 after Phase 8 completion*
