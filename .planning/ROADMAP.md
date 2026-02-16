# Roadmap: Multi-User Gymnasium (MUG)

## Milestones

- v1.0 MVP - Phases 67-91 (shipped 2026-02-12)
- v1.1 Server-Authoritative Cleanup - Phases 92-95 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (92, 93, 94, 95): Planned milestone work
- Decimal phases (e.g., 93.1): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 92: Remove Obsolete Server-Auth Code** - Strip out Pyodide server-auth sync and simplify RemoteGameV2
- [x] **Phase 93: Server Pipeline** - Server runs env at max speed, renders, and broadcasts state to clients
- [ ] **Phase 94: Client Rendering and Input** - Client buffers server state, gates FPS, and sends actions
- [ ] **Phase 95: Example and Verification** - CoGrid Overcooked example with full test coverage

## Phase Details

### Phase 92: Remove Obsolete Server-Auth Code
**Goal**: Obsolete Pyodide server-auth sync code is fully removed and RemoteGameV2 is simplified for its new role
**Depends on**: Nothing (first phase of v1.1)
**Requirements**: CLEAN-01, CLEAN-02, CLEAN-03, CLEAN-04
**Success Criteria** (what must be TRUE):
  1. `ServerGameRunner` class and all references are gone from the codebase
  2. `PyodideGameCoordinator` has no `server_authoritative` flag or Pyodide server-auth sync config
  3. Multiplayer config no longer exposes obsolete server-auth options (broadcast interval, sync epoch, etc.)
  4. `RemoteGameV2` is audited and simplified -- dead methods removed, role as server-side game runner is clear
  5. Existing P2P multiplayer mode still works (no regressions from cleanup)
**Plans**: 1 plan

Plans:
- [x] 92-01-PLAN.md -- Delete ServerGameRunner, strip server-auth from all Python/JS/docs, gut and rename RemoteGameV2 to ServerGame

### Phase 93: Server Pipeline
**Goal**: Server can run an environment at max speed, render it, broadcast state, receive actions, and handle episode transitions
**Depends on**: Phase 92 (clean RemoteGameV2 as foundation)
**Requirements**: PIPE-01, PIPE-02, PIPE-03, PIPE-04, PIPE-05
**Success Criteria** (what must be TRUE):
  1. Server game loop runs continuously, stepping the environment with latest player actions (or default action if none received), with no artificial FPS cap
  2. After each step, server calls `env.render(render_mode="interactive_gym")` and broadcasts the resulting Phaser-compatible state dict to all connected clients via socket event
  3. Server receives player actions from clients via socket event and stores the latest action per player for next step
  4. Server handles episode reset (environment done) and game completion, notifying clients of both transitions
**Plans**: 2 plans

Plans:
- [x] 93-01-PLAN.md -- Rebuild ServerGame env lifecycle and game loop in GameManager (max-speed stepping, env.render broadcast, episode transitions)
- [x] 93-02-PLAN.md -- Add server_authoritative mode toggle, player_action socket handler, and server-auth-aware game flow

### Phase 94: Client Rendering and Input
**Goal**: Client receives server-broadcast render states, buffers them, renders at controlled FPS with configurable input delay, and sends actions back
**Depends on**: Phase 93 (server must be broadcasting state)
**Requirements**: CLNT-01, CLNT-02, CLNT-03, CLNT-04, CLNT-05
**Success Criteria** (what must be TRUE):
  1. Client JS receives and buffers incoming render states from the server
  2. Client renders buffered states at a target FPS independent of server step rate (client-side frame rate gating)
  3. Client applies a configurable fixed N-frame input delay to absorb round-trip lag
  4. Client sends player actions to the server via socket event on keypress
  5. Client handles episode reset and game-complete events from the server (transitions scenes appropriately)
**Plans**: 2 plans

Plans:
- [ ] 94-01-PLAN.md -- Server-auth state buffer, rendering pipeline, and input sending (buffer incoming states, render at FPS, send player_action on keypress)
- [ ] 94-02-PLAN.md -- Episode transitions and reconnection (flush buffer on reset, game-complete flow, reconnect to running game with disconnect timeout)

### Phase 95: Example and Verification
**Goal**: CoGrid Overcooked runs in server-authoritative mode end-to-end, with automated tests proving both server-auth and P2P modes work
**Depends on**: Phase 94 (full pipeline must be functional)
**Requirements**: EXMP-01, TEST-01, TEST-02, TEST-03, TEST-04
**Success Criteria** (what must be TRUE):
  1. CoGrid Overcooked example is configured and launchable in server-authoritative mode
  2. Unit tests cover server game loop lifecycle (start, step, broadcast, cleanup) and pass
  3. Integration test runs action-to-step-to-render-to-broadcast flow and passes
  4. Playwright E2E test with two browser clients completes a server-auth CoGrid game
  5. Playwright E2E regression test confirms P2P mode still works
**Plans**: TBD

Plans:
- [ ] 95-01: TBD
- [ ] 95-02: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 92 -> 93 -> 94 -> 95

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 92. Remove Obsolete Server-Auth Code | v1.1 | 1/1 | Complete | 2026-02-15 |
| 93. Server Pipeline | v1.1 | 2/2 | Complete | 2026-02-15 |
| 94. Client Rendering and Input | v1.1 | 0/TBD | Not started | - |
| 95. Example and Verification | v1.1 | 0/TBD | Not started | - |
