# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-07)

**Core value:** Both players in a multiplayer game experience local-feeling responsiveness regardless of network latency, enabling valid research data collection without latency-induced behavioral artifacts.
**Current focus:** Phase 81 — LatencyFIFOMatchmaker Core

## Current Position

Phase: 81 of 82 (LatencyFIFOMatchmaker Core)
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-07 — Roadmap created for v1.21

Progress: ░░░░░░░░░░ 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0 (v1.21)
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| — | — | — | — |

**Recent Trend:**
- Last 5 plans: —
- Trend: —

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v1.20 Phase 80]: Use sio.start_background_task() for countdown to avoid holding waiting_games_lock during 3s sleep
- [v1.13 Phase 59]: max_p2p_rtt_ms threshold on Matchmaker base class for post-match P2P probe rejection

### Key Files for v1.21

**Matchmaker classes (will be modified):**
- `interactive_gym/server/matchmaker.py` — Matchmaker base, FIFOMatchmaker, GroupReunionMatchmaker, MatchCandidate
- `interactive_gym/server/game_manager.py` — _try_match(), _probe_and_create_game(), _on_probe_complete()
- `interactive_gym/server/probe_coordinator.py` — ProbeCoordinator for P2P RTT measurement

**Configuration:**
- `interactive_gym/scenes/gym_scene.py` — GymScene.matchmaking() config method

### Pending Todos

None yet.

### Blockers/Concerns

- Pre-existing E2E multiplayer_basic test failures (players matched to separate games). Unrelated to v1.21 changes.

## Session Continuity

Last session: 2026-02-07
Stopped at: Roadmap created — ready to plan Phase 81
Resume file: None
