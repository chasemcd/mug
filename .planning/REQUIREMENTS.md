# Requirements: Multi-User Gymnasium (MUG)

**Defined:** 2026-02-20
**Core Value:** Researchers can deploy interactive simulation experiments to the browser with minimal friction, supporting both single-player and multiplayer configurations.

## v1.3 Requirements

Requirements for Rendering API Redesign. Each maps to roadmap phases.

### Surface Core

- [x] **SURF-01**: User can draw filled rectangles via `surface.rect()`
- [x] **SURF-02**: User can draw filled circles via `surface.circle()`
- [x] **SURF-03**: User can draw lines via `surface.line()`
- [x] **SURF-04**: User can draw filled polygons via `surface.polygon()`
- [x] **SURF-05**: User can render text via `surface.text()`
- [x] **SURF-06**: User can render preloaded images via `surface.image()`
- [x] **SURF-07**: User can draw outlines (width>0) for rect, circle, and polygon
- [x] **SURF-08**: User can draw arcs via `surface.arc()`
- [x] **SURF-09**: User can draw ellipses via `surface.ellipse()`
- [x] **SURF-10**: User can draw rounded rectangles via `border_radius=` parameter on `rect()`

### Color

- [x] **COLOR-01**: User can specify colors as RGB tuples `(255, 0, 0)`
- [x] **COLOR-02**: User can specify colors as hex strings `'#FF0000'`
- [x] **COLOR-03**: User can specify colors as named strings `'red'`, `'blue'`, etc. (~20 common colors)
- [x] **COLOR-04**: All draw methods accept any supported color format interchangeably

### Coordinates

- [x] **COORD-01**: Draw methods accept pixel coordinates by default
- [x] **COORD-02**: User can use relative (0-1) coordinates when desired

### Identity & Tweening

- [x] **IDENT-01**: User can provide optional `id=` parameter on any draw call for object identity
- [ ] **IDENT-02**: Objects with `id=` are tweened smoothly between frames in the browser
- [x] **IDENT-03**: User can control tween duration via `tween_duration=` parameter

### Persistence & Deltas

- [x] **DELTA-01**: User can mark objects as persistent via `persistent=True` (drawn once, stay on canvas)
- [x] **DELTA-02**: Surface computes state deltas — only sends changed objects per frame
- [x] **DELTA-03**: Surface tracks which persistent objects have been sent to client
- [x] **DELTA-04**: `Surface.reset()` clears persistent tracking for episode boundaries

### JS Renderer

- [ ] **RENDER-01**: Phaser JS renderer implements rectangle creation and update (currently empty stubs)
- [ ] **RENDER-02**: Phaser JS renderer handles stroke (outline) paths for circle, rect, polygon
- [ ] **RENDER-03**: Phaser JS renderer processes delta wire format (objects list + removed list)
- [ ] **RENDER-04**: `addStateToBuffer()` normalization handles new RenderPacket format
- [ ] **RENDER-05**: Text color is configurable in JS (currently hardcoded to `#000`)

### Example Migration

- [ ] **MIGR-01**: Slime Volleyball example migrated from ObjectContext to Surface API
- [ ] **MIGR-02**: Overcooked example migrated from ObjectContext to Surface API

## Future Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Extended Primitives

- **SURF-11**: User can draw multi-point polylines via `surface.lines()`
- **SURF-12**: User can draw anti-aliased lines

### Extended Colors

- **COLOR-05**: Support full CSS 140+ named color vocabulary
- **COLOR-06**: Support RGBA tuples `(255, 0, 0, 128)` for per-color alpha

### Additional Migration

- **MIGR-03**: Mountain Car example migrated from ObjectContext to Surface API

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Sub-surface compositing (`surface.blit(other_surface)`) | Doesn't map to server->browser serialization pipeline; enormous protocol complexity |
| Pixel-level surface manipulation (`set_at()`) | Would require transmitting entire pixel arrays; use existing `game_image_binary` path |
| Real-time texture loading per frame | Breaks asset preloading lifecycle; unpredictable network behavior mid-game |
| Keyframe animation API | Out of scope for rendering API; existing tween + sprite frame covers movement |
| Audio API | Rendering only this milestone |
| New game modes or environment types | Rendering API only |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SURF-01 | Phase 97 | Complete |
| SURF-02 | Phase 97 | Complete |
| SURF-03 | Phase 97 | Complete |
| SURF-04 | Phase 97 | Complete |
| SURF-05 | Phase 97 | Complete |
| SURF-06 | Phase 97 | Complete |
| SURF-07 | Phase 97 | Complete |
| SURF-08 | Phase 97 | Complete |
| SURF-09 | Phase 97 | Complete |
| SURF-10 | Phase 97 | Complete |
| COLOR-01 | Phase 97 | Complete |
| COLOR-02 | Phase 97 | Complete |
| COLOR-03 | Phase 97 | Complete |
| COLOR-04 | Phase 97 | Complete |
| COORD-01 | Phase 97 | Complete |
| COORD-02 | Phase 97 | Complete |
| IDENT-01 | Phase 97 | Complete |
| IDENT-02 | Phase 98 | Pending |
| IDENT-03 | Phase 97 | Complete |
| DELTA-01 | Phase 97 | Complete |
| DELTA-02 | Phase 97 | Complete |
| DELTA-03 | Phase 97 | Complete |
| DELTA-04 | Phase 97 | Complete |
| RENDER-01 | Phase 98 | Pending |
| RENDER-02 | Phase 98 | Pending |
| RENDER-03 | Phase 98 | Pending |
| RENDER-04 | Phase 98 | Pending |
| RENDER-05 | Phase 98 | Pending |
| MIGR-01 | Phase 99 | Pending |
| MIGR-02 | Phase 99 | Pending |

**Coverage:**
- v1.3 requirements: 30 total
- Mapped to phases: 30
- Unmapped: 0

---
*Requirements defined: 2026-02-20*
*Last updated: 2026-02-20 after roadmap creation*
