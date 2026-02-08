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

## Current

### v1.23 Pre-Merge Cleanup
- Remove dead code, unused functions/classes/imports across full repo
- Rename unclear variables, functions, modules for readability
- Reorganize file/module structure where it aids navigation
- Zero functionality changes — every refactor verified by tests
