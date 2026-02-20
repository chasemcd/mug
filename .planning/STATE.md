# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-20)

**Core value:** Researchers can deploy interactive simulation experiments to the browser with minimal friction, supporting both single-player and multiplayer configurations.
**Current focus:** v1.3 Rendering API Redesign — Phase 99: Example Migration

## Current Position

Phase: 99 of 99 (Example Migration)
Plan: 2 of 2 in current phase
Status: In Progress
Last activity: 2026-02-20 — Completed 99-01 (Surface Asset Registration + Slime Volleyball Migration)

Progress: [████████░░] 88%

## Performance Metrics

**Velocity:**
- Total plans completed: 7
- Average duration: 3min
- Total execution time: 0.35 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 97 | 3 | 5min | 2min |
| 98 | 3 | 14min | 5min |
| 99 | 1 | 3min | 3min |

**Recent Trend:**
- Last 5 plans: 97-03 (2min), 98-01 (1min), 98-03 (3min), 98-02 (10min), 99-01 (3min)
- Trend: Stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- PyGame-inspired Surface draw-call API chosen over dataclass serialization
- Optional id= for tweening (not mandatory) keeps simple cases simple
- Persistent objects + state deltas for bandwidth optimization
- Two-format wire protocol: legacy ObjectContext path preserved alongside new RenderPacket delta path
- [97-01] Frozen dataclass for DrawCommand enforces immutability of draw records
- [97-01] RenderPacket.to_dict() uses game_state_objects key for backward compat with JS renderer
- [97-01] CSS named colors follow standard values (green=#008000, lime=#00ff00)
- [97-03] pytest.approx used for floating-point coordinate comparisons
- [97-03] Parametrized NAMED_COLORS tests auto-cover all 20 entries
- [97-03] Test classes organized by requirement ID groups for traceability
- [98-01] Dynamic class stubs via type() preserve __name__ for clear deprecation errors
- [98-01] Error messages include class name + migration target (mug.rendering.Surface)
- [98-03] Handle both Map and plain Object from Pyodide toJs() for RenderPacket format
- [98-03] Preserve legacy flat array fallback for backward compatibility
- [98-03] Forward removed list in all render_state constructions
- [98-02] Single Map replaces dual temp/perm object maps -- permanent flag on each object
- [98-02] Circle radius scaled by max(width, height) per Surface API normalization
- [98-02] Alpha defaults to 1 via nullish coalescing (config.alpha ?? 1)
- [98-02] Tween cancel-and-restart via shared _applyPositionTween helper
- [99-01] Asset specs stored as list of dicts on Surface._asset_specs, not cleared on reset()
- [99-01] All Slime VB draw calls use relative=True to match old ObjectContext coordinate convention
- [99-01] Agent drawing logic moved to _draw_agent() private method on env class

### Prior Milestones

- v1.0 (phases 67-91): foundational cleanup, API consolidation, package rename, declarative model config
- v1.1 (phases 92-95): server-authoritative rendering pipeline, FPS gating, Overcooked example
- v1.2 (phase 96): test suite stabilization — CSV export, rollback depth, server-auth E2E

### Blockers/Concerns

- `env_to_state_fn` calling convention may need Surface parameter — resolve during Phase 97 planning
- Rollback behavior with new delta format untested — flag for Phase 99 E2E validation

## Session Continuity

Last session: 2026-02-20
Stopped at: Completed 99-01-PLAN.md
Resume file: .planning/phases/99-example-migration/99-01-SUMMARY.md
