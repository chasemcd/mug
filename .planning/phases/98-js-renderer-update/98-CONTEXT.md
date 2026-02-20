# Phase 98: JS Renderer Update - Context

**Gathered:** 2026-02-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Update the Phaser JS renderer to interpret and render the new RenderPacket delta wire format from Phase 97. Support object creation, in-place update, removal, tweened smooth movement for identified objects, stroke rendering, and configurable text color. Drop legacy ObjectContext support entirely — new format only.

</domain>

<decisions>
## Implementation Decisions

### Format routing
- No backward compatibility — drop legacy ObjectContext format entirely
- Renderer only handles new RenderPacket format: `{game_state_objects: [...], removed: [...]}`
- `addStateToBuffer()` does not need format detection logic; assumes new format
- When game_state is null or missing: `console.warn()` and skip the frame
- Delete `mug/configurations/object_contexts.py` in this phase
- Replace all existing imports of ObjectContext classes (Sprite, Circle, Line, etc.) with stubs that raise `NotImplementedError("Migrate to Surface API")` — provides clear error message until Phase 99 migrates examples

### Delta handling
- Update persistent objects in-place (find existing Phaser object by id, update properties) — do not destroy and recreate
- Maintain a `Map<string, Phaser.GameObjects.*>` lookup for O(1) id-based access
- Objects in the `removed` list are destroyed immediately (no fade-out)
- Before each frame, destroy all non-permanent Phaser objects from the previous frame, then create new ones from the objects list

### Tween behavior
- First appearance: object appears instantly at position (no fade-in or scale-in)
- Subsequent updates: position (x, y) and size (width, height, radius) changes are tweened over `tween_duration`
- Color and alpha changes are instant (not tweened)
- Easing curve: linear (constant speed)
- If a new tween arrives while a previous tween is in progress: cancel the old tween, start fresh from the object's current position

### Stroke rendering
- Stroke is centered on the shape edge (standard CSS/SVG behavior)
- If stroke_color is set but no fill color: render as outline only (transparent fill)
- Polygon strokes auto-close (connect last point back to first)

### Claude's Discretion
- Exact Phaser API calls for each shape type (Graphics vs GameObjects)
- How to handle unknown object_type values in the wire format
- Internal architecture of the renderer update (refactor vs patch)

</decisions>

<specifics>
## Specific Ideas

- The stubs replacing ObjectContext imports should clearly say "Migrate to Surface API" so developers know what to do
- Linear easing for tweens — simulations need predictable motion, not decorative easing

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 98-js-renderer-update*
*Context gathered: 2026-02-20*
