# Roadmap: MUG v1.3 Rendering API Redesign

## Overview

Replace the ObjectContext-based rendering API with a PyGame-inspired imperative Surface draw-call API. The build follows a strict dependency chain: Python Surface core (fully unit-testable in isolation) -> JS renderer update (consumes finalized wire format) -> example migration (proves ergonomics with real environments). The two-format wire protocol (legacy path preserved alongside new delta path) enables incremental migration without breaking existing functionality.

## Phases

**Phase Numbering:**
- Integer phases (97, 98, 99): Planned v1.3 milestone work
- Decimal phases (97.1, 97.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 97: Python Surface Core** - Surface class with draw-call API, color normalization, coordinate handling, and delta computation
- [ ] **Phase 98: JS Renderer Update** - Phaser renderer processes new delta wire format with object lifecycle management and tweening
- [ ] **Phase 99: Example Migration** - Migrate Slime Volleyball and Overcooked from ObjectContext to Surface API

## Phase Details

### Phase 97: Python Surface Core
**Goal**: Researchers can construct render frames using imperative draw calls on a Surface object, with flexible color input, coordinate modes, object identity, persistence, and efficient delta computation
**Depends on**: Nothing (first phase in v1.3)
**Requirements**: SURF-01, SURF-02, SURF-03, SURF-04, SURF-05, SURF-06, SURF-07, SURF-08, SURF-09, SURF-10, COLOR-01, COLOR-02, COLOR-03, COLOR-04, COORD-01, COORD-02, IDENT-01, IDENT-03, DELTA-01, DELTA-02, DELTA-03, DELTA-04
**Success Criteria** (what must be TRUE):
  1. User can call `surface.rect()`, `surface.circle()`, `surface.line()`, `surface.polygon()`, `surface.text()`, `surface.image()`, `surface.arc()`, and `surface.ellipse()` to add draw commands to a frame, and `surface.commit()` returns a serializable RenderPacket
  2. User can pass colors as RGB tuples `(255, 0, 0)`, hex strings `'#FF0000'`, or named strings `'red'` to any draw method and the output wire format always contains normalized `#rrggbb` hex strings
  3. User can draw with pixel coordinates by default and opt into relative (0-1) coordinates, with both modes producing correct wire format values
  4. User can mark objects as `persistent=True` so they are transmitted once and only retransmitted if changed; `surface.commit()` produces an empty delta when nothing has changed between frames
  5. User can call `surface.reset()` at episode boundaries and persistent objects are correctly retransmitted in the next episode (validated across 3+ sequential episodes)
**Plans**: 3 plans

Plans:
- [ ] 97-01-PLAN.md — Foundation: rendering package, types (DrawCommand, RenderPacket), color normalization
- [ ] 97-02-PLAN.md — Surface class: all draw methods, coordinate handling, commit/delta/reset
- [ ] 97-03-PLAN.md — Tests: comprehensive unit tests for color and Surface

### Phase 98: JS Renderer Update
**Goal**: The Phaser JS renderer correctly interprets and renders the new delta wire format, supporting object creation, update, removal, and tweened smooth movement for identified objects
**Depends on**: Phase 97
**Requirements**: RENDER-01, RENDER-02, RENDER-03, RENDER-04, RENDER-05, IDENT-02
**Success Criteria** (what must be TRUE):
  1. Phaser renderer creates and displays rectangles, circles, lines, polygons, text, and images from the new RenderPacket delta format (new/update/remove lists)
  2. Objects with `id=` set move smoothly between positions via tweening in the browser, with configurable tween duration
  3. The `addStateToBuffer()` normalization shim correctly routes both legacy ObjectContext format and new RenderPacket format, with a console warning when game state is null
  4. Stroke/outline rendering works for circle, rect, and polygon when `width > 0` is specified in the draw command
  5. Text color is configurable from the wire format (not hardcoded to `#000`)
**Plans**: TBD

Plans:
- [ ] 98-01: TBD
- [ ] 98-02: TBD

### Phase 99: Example Migration
**Goal**: The reference environments use the new Surface API, proving it is ergonomic for real Gymnasium/PettingZoo environments and validating both render paths end-to-end
**Depends on**: Phase 98
**Requirements**: MIGR-01, MIGR-02
**Success Criteria** (what must be TRUE):
  1. Slime Volleyball example runs in the browser using the Surface API with tweened ball/player movement, persistent fence/net objects, and relative coordinates
  2. Overcooked example runs in the browser using the Surface API with persistent static tiles, pixel coordinates, and multi-agent rendering
  3. Both migrated examples render correctly through the server-authoritative path (Flask/SocketIO) without visual regressions compared to the ObjectContext version
**Plans**: TBD

Plans:
- [ ] 99-01: TBD
- [ ] 99-02: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 97 -> 98 -> 99

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 97. Python Surface Core | 0/3 | Planned | - |
| 98. JS Renderer Update | 0/? | Not started | - |
| 99. Example Migration | 0/? | Not started | - |
