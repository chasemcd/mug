# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-07)

**Core value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.
**Current focus:** Phase 82 — Scene API & P2P Probe Integration

## Current Position

Phase: 82 of 82 (Scene API & P2P Probe Integration)
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-07 — Phase 81 executed and verified

Progress: █████░░░░░ 50%

## Performance Metrics

**Velocity:**
- Total plans completed: 1 (v1.21)
- Average duration: 2min
- Total execution time: 2min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 81-latency-fifo-matchmaker-core | 1/1 | 2min | 2min |

**Recent Trend:**
- Last 5 plans: 81-01 (2min)
- Trend: N/A (first plan)

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v1.21 Phase 81]: LatencyFIFOMatchmaker extends Matchmaker directly (not FIFOMatchmaker) to avoid coupling
- [v1.21 Phase 81]: None rtt_ms treated as compatible — err on matching rather than waiting forever
- [v1.21 Phase 81]: max_server_rtt_ms is required (no default) so researchers must explicitly choose a threshold
- [v1.20 Phase 80]: Use sio.start_background_task() for countdown to avoid holding waiting_games_lock during 3s sleep
- [v1.13 Phase 59]: max_p2p_rtt_ms threshold on Matchmaker base class for post-match P2P probe rejection

### Key Files for v1.21

**Matchmaker classes (modified in Phase 81):**
- `interactive_gym/server/matchmaker.py` — Matchmaker base, FIFOMatchmaker, LatencyFIFOMatchmaker, GroupReunionMatchmaker, MatchCandidate
- `interactive_gym/server/game_manager.py` — _try_match(), _probe_and_create_game(), _on_probe_complete()
- `interactive_gym/server/probe_coordinator.py` — ProbeCoordinator for P2P RTT measurement

**Tests (created in Phase 81):**
- `tests/unit/test_latency_fifo_matchmaker.py` — 13 unit tests for LatencyFIFOMatchmaker

**Configuration:**
- `interactive_gym/scenes/gym_scene.py` — GymScene.matchmaking() config method

### Pending Todos

None.

### Blockers/Concerns

- Pre-existing E2E multiplayer_basic test failures (players matched to separate games). Unrelated to v1.21 changes.

## Session Continuity

Last session: 2026-02-07
Stopped at: Phase 81 complete and verified — ready to plan Phase 82
Resume file: None
