# Milestones

## Shipped

### v1.0–v1.21 (Feature Branch: P2P Multiplayer)

82 phases of development covering:
- v1.0–v1.5: WebRTC foundation, P2P transport, GGPO integration, resilience
- v1.6–v1.8: State hash verification, desync detection, validation export
- v1.9–v1.10: Entry screening, continuous monitoring, multiplayer exclusion
- v1.11: Custom callbacks, waiting room validation
- v1.12: Matchmaker base class, custom attributes logging
- v1.13: P2P probe infrastructure, RTT measurement, matchmaker RTT integration
- v1.14: Single game creation path, input confirmation, data parity validation
- v1.15: Multi-participant test infrastructure, stress tests, server recovery
- v1.16: Pyodide preload, shared instance integration, server init grace
- v1.17: Test stabilization, latency diagnosis, network regression, stability cert
- v1.18: Merged loading screen, test/roadmap cleanup
- v1.19: P2P connection scoping, group history tracking
- v1.20: Pre-game countdown, latency FIFO matchmaker core, scene API integration
- v1.21: Latency-aware matchmaking (LatencyFIFOMatchmaker + P2P probe integration)

Bug fixes (post v1.21):
- fix: join participants to socket room after probe-accepted match creation
- fix: register players with Pyodide coordinator in probe-accepted match path
- fix: reorder probe path so room joins and state transition happen before Pyodide coordinator registration

### v1.22 GymScene Config Cleanup

5 phases (67–71), 10 plans, 18 requirements:
- Phase 67: API method consolidation (14 → 10 builder methods)
- Phase 68: Clean break (9 old method names removed)
- Phase 69: Example configs migration (5 examples updated)
- Phase 70: Verification & test pass (27/27 tests, 44/44 params, 10/10 chaining)
- Phase 71: Documentation migration (15 doc files updated)

Audit: passed (18/18 requirements, 5/5 phases, 6/6 integration, 3/3 flows)

### v1.23 Pre-Merge Cleanup

7 phases (72–78), 13 plans, 4 requirements:
- Phase 72–74: Dead code removal (server, client JS, scenes/examples)
- Phase 75–76: Naming cleanup (sio→socketio, abbreviation expansion, parameter renames)
- Phase 77: Module structure reorganization (sentinels, thread_safe_collections, consolidation)
- Phase 78: Final verification (27/27 tests, 35/35 artifact checks)

Note: Bulk `sio` → `socketio` rename introduced corruption (72 occurrences of "session"/"exclusion"/"transmission" mangled). Fixed in v1.24.

### v1.24 Test Fix & Hardening (Shipped: 2026-02-09)

4 phases (79–82), 6 plans, 16 requirements:
- Phase 79: Rename corruption fix (72 mangled identifiers restored across 3 server files)
- Phase 80: Test suite restoration (all 52 tests passing — 27 unit + 25 E2E)
- Phase 81: Data parity hardening (export parity validation added to all 7 episode-producing E2E tests)
- Phase 82: Examples & documentation (12 examples verified, 22 sio→socketio doc fixes, 3 stale file refs removed)

Note: This milestone was pure correctness — zero new features, only fixing v1.23 bulk rename damage and hardening validation.

### v1.25 Data Export Path Fix (Shipped: 2026-02-09)

1 phase (83), 1 plan, 4 requirements:
- Phase 83: Export path consolidation (scene metadata + match logs under data/{experiment_id}/)

---

### v1.26 Project Rename (Shipped: 2026-02-10)

3 phases (84–86), 7 plans, 25 requirements:
- Phase 84: Package & code rename (directory `interactive_gym/` → `mug/`, 54 Python files updated, class renames MountainCarEnv/OvercookedEnv)
- Phase 85: Documentation & frontend (31 doc files, admin templates, JS comments, example READMEs updated to MUG branding)
- Phase 86: Final verification (7 stale docstrings fixed, 27/27 tests pass, 33/33 example imports verified)

Key stats: 291 files changed, 1,879 insertions, 515 deletions, completed in 22.3 minutes.

---
