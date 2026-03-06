# Phase 98: JS Renderer Update - Research

**Researched:** 2026-02-20
**Domain:** Phaser 3 game rendering, JavaScript sprite/graphics management, delta-based state updates, tween animation
**Confidence:** HIGH

## Summary

Phase 98 updates the Phaser JS renderer (`phaser_gym_graphics.js`) to consume the new `RenderPacket` delta wire format produced by the Phase 97 Surface API. The primary JS file is approximately 1350 lines and contains a `GymScene` class that manages object creation, update, and removal via `drawState()`. The current renderer already handles circles, polygons, sprites, lines, and text -- but rectangles and text color are unimplemented (stubs/hardcoded). The new wire format wraps objects in `{game_state_objects: [...], removed: [...]}` rather than being a flat list.

The renderer must be updated in three layers: (1) the `addStateToBuffer()` normalization shim that unwraps the new format, (2) the `drawState()` method that processes deltas (new/update/remove), and (3) individual `_add*`/`_update*` methods for each shape type. Additionally, the tween behavior needs fixing -- the current code skips new tween requests while one is in-progress, but the user decision requires canceling the old tween and starting fresh.

On the Python side, `object_contexts.py` must be deleted and replaced with stubs that raise `NotImplementedError("Migrate to Surface API")`, and all existing imports need stub replacement. This will intentionally break existing examples until Phase 99 migrates them.

**Primary recommendation:** Rewrite `drawState()` to use a single `Map<string, Phaser.GameObjects.*>` keyed by `uuid`, process the `removed` list to destroy objects, and route objects through updated `_add*`/`_update*` methods. Fix tween logic to cancel in-progress tweens. Implement `_addRectangle`/`_updateRectangle` using Phaser `Graphics` in a `Container` (same pattern as circles/polygons). Fix text color to read from wire format.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- No backward compatibility -- drop legacy ObjectContext format entirely
- Renderer only handles new RenderPacket format: `{game_state_objects: [...], removed: [...]}`
- `addStateToBuffer()` does not need format detection logic; assumes new format
- When game_state is null or missing: `console.warn()` and skip the frame
- Delete `mug/configurations/object_contexts.py` in this phase
- Replace all existing imports of ObjectContext classes (Sprite, Circle, Line, etc.) with stubs that raise `NotImplementedError("Migrate to Surface API")` -- provides clear error message until Phase 99 migrates examples
- Update persistent objects in-place (find existing Phaser object by id, update properties) -- do not destroy and recreate
- Maintain a `Map<string, Phaser.GameObjects.*>` lookup for O(1) id-based access
- Objects in the `removed` list are destroyed immediately (no fade-out)
- Before each frame, destroy all non-permanent Phaser objects from the previous frame, then create new ones from the objects list
- First appearance: object appears instantly at position (no fade-in or scale-in)
- Subsequent updates: position (x, y) and size (width, height, radius) changes are tweened over `tween_duration`
- Color and alpha changes are instant (not tweened)
- Easing curve: linear (constant speed)
- If a new tween arrives while a previous tween is in progress: cancel the old tween, start fresh from the object's current position
- Stroke is centered on the shape edge (standard CSS/SVG behavior)
- If stroke_color is set but no fill color: render as outline only (transparent fill)
- Polygon strokes auto-close (connect last point back to first)

### Claude's Discretion
- Exact Phaser API calls for each shape type (Graphics vs GameObjects)
- How to handle unknown object_type values in the wire format
- Internal architecture of the renderer update (refactor vs patch)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| RENDER-01 | Phaser JS renderer implements rectangle creation and update | Implement `_addRectangle`/`_updateRectangle` using Graphics-in-Container pattern (same as circles/polygons). Wire format sends `object_type: "rect"` with `x, y, w, h, color` fields. Coordinates are relative (0-1). |
| RENDER-02 | Phaser JS renderer handles stroke (outline) paths for circle, rect, polygon | Add `lineStyle()` + `strokeCircle()`/`strokeRect()`/`strokePoints()` calls when `stroke_color` and `stroke_width` are present in wire format. If fill color is present, render fill first then stroke. |
| RENDER-03 | Phaser JS renderer processes delta wire format (objects list + removed list) | Rewrite `drawState()` to: (1) process `removed` list and destroy those objects, (2) destroy non-permanent objects from previous frame, (3) iterate `game_state_objects` to add/update objects via uuid-keyed Map. |
| RENDER-04 | `addStateToBuffer()` normalization handles new RenderPacket format | Update to unwrap `{game_state_objects: [...], removed: [...]}` from `render_state` or `game_state_objects`. Warn and skip when `game_state_objects` is null. |
| RENDER-05 | Text color is configurable in JS (currently hardcoded to `#000`) | Change `_addText` to read `text_config.color` from wire format instead of hardcoded `"#000"`. Add color update in `_updateText`. |
| IDENT-02 | Objects with `id=` are tweened smoothly between frames in the browser | Fix tween logic: cancel in-progress tween via `tween.stop()` before starting new one. Extend tweening to cover size changes (width, height, radius) in addition to position. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Phaser | 3.80.1 | Game rendering framework | Already loaded via CDN in `index.html`; all renderer code is built on Phaser Scene/GameObjects |
| JavaScript (ES6+) | Browser native | Language | Existing codebase uses ES6 modules, classes, arrow functions, Map, destructuring |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Phaser.GameObjects.Container | 3.80.1 | Group graphics + position for tweening | All shapes that need tweening (rect, circle, polygon) -- draw at (0,0) relative to container, tween the container |
| Phaser.GameObjects.Graphics | 3.80.1 | Draw primitives (fill, stroke) | Rectangles, circles, polygons -- drawn inside containers |
| Phaser.GameObjects.Text | 3.80.1 | Text rendering | Text labels with configurable color |
| Phaser.Tweens | 3.80.1 | Smooth interpolation | Position and size tweening for identified objects |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Graphics-in-Container for rects | Phaser.GameObjects.Rectangle | Rectangle GameObjects exist in Phaser but don't support stroke as flexibly as Graphics; Container+Graphics is consistent with existing circle/polygon pattern |
| Custom tween cancellation | `this.tweens.killTweensOf(target)` | `killTweensOf` is simpler but kills ALL tweens on target; storing reference and calling `.stop()` is more precise and matches existing code pattern |

**Installation:**
No new dependencies. Phaser 3.80.1 already loaded from CDN.

## Architecture Patterns

### Recommended Project Structure
```
mug/server/static/js/
├── phaser_gym_graphics.js   # Main renderer (MODIFY)
├── index.js                 # Socket handlers, addStateToBuffer caller (MINOR MODIFY)
├── pyodide_remote_game.js   # Pyodide single-player path (MODIFY render wrapping)
├── pyodide_multiplayer_game.js  # Pyodide multiplayer path (MODIFY render wrapping)
└── ...

mug/configurations/
└── object_contexts.py       # DELETE and replace with stub module

mug/rendering/               # Phase 97 output (READ-ONLY for this phase)
├── surface.py
├── types.py
├── color.py
└── __init__.py
```

### Pattern 1: Container+Graphics for Tweenable Shapes
**What:** Each shape (rect, circle, polygon) is rendered as a Phaser `Graphics` object placed inside a `Container`. The Graphics draws at (0,0) relative to the container. The container is positioned at the object's world coordinates. Tweening targets the container, so position interpolation works automatically.
**When to use:** For all shapes that may be tweened (everything except lines and text).
**Why:** The existing codebase already uses this pattern for circles and polygons. Applying it to rectangles maintains consistency.
**Example:**
```javascript
// Verified pattern from existing _addCircle in phaser_gym_graphics.js
_addRectangle(config, objectMap) {
    let x = config.x * this.width;
    let y = config.y * this.height;
    let w = config.w * this.width;
    let h = config.h * this.height;

    let container = this.add.container(x, y);
    container.setDepth(config.depth);

    let graphics = this.add.graphics();
    // Fill
    graphics.fillStyle(this._strToHex(config.color), config.alpha ?? 1);
    graphics.fillRect(0, 0, w, h);
    // Stroke (if specified)
    if (config.stroke_color && config.stroke_width > 0) {
        graphics.lineStyle(config.stroke_width, this._strToHex(config.stroke_color));
        graphics.strokeRect(0, 0, w, h);
    }

    container.add(graphics);
    container.tween = null;
    container.graphics = graphics;
    container.lastConfig = config;
    objectMap[config.uuid] = container;
}
```

### Pattern 2: Tween Cancellation on New Update
**What:** When an object receives a new position/size update while a tween is in progress, stop the existing tween and create a new one from the current interpolated position.
**When to use:** All tweened updates. This is a USER DECISION (locked).
**Example:**
```javascript
// Fix: Cancel existing tween before starting new one
_applyTween(container, props, duration) {
    // Cancel in-progress tween
    if (container.tween) {
        container.tween.stop();
        container.tween = null;
    }

    container.tween = this.tweens.add({
        targets: [container],
        ...props,  // {x: newX, y: newY} or {scaleX: ..., scaleY: ...}
        duration: duration,
        ease: 'Linear',
        onComplete: () => {
            container.tween = null;
        }
    });
}
```

### Pattern 3: Delta-Aware drawState
**What:** `drawState()` processes the new wire format: first processes removals, then destroys stale non-permanent objects, then iterates the objects list for add/update.
**When to use:** Every frame in `drawState()`.
**Example:**
```javascript
drawState() {
    if (!this.state || !this.state.game_state_objects) {
        console.warn("No game state to render.");
        return;
    }

    let gameObjects = this.state.game_state_objects;
    let removedIds = this.state.removed || [];

    // 1. Process explicit removals
    for (const id of removedIds) {
        if (this.objectMap.has(id)) {
            this.objectMap.get(id).destroy();
            this.objectMap.delete(id);
        }
    }

    // 2. Destroy non-permanent objects from previous frame
    // (Track which non-permanent objects are in the current frame)
    let currentFrameIds = new Set(gameObjects.map(o => o.uuid));
    for (const [id, obj] of this.objectMap) {
        if (!obj.permanent && !currentFrameIds.has(id)) {
            obj.destroy();
            this.objectMap.delete(id);
        }
    }

    // 3. Add or update each object
    for (const objConfig of gameObjects) {
        if (!this.objectMap.has(objConfig.uuid)) {
            this._addObject(objConfig);
        }
        this._updateObject(objConfig);
    }
}
```

### Pattern 4: addStateToBuffer Normalization for New Format
**What:** The `addStateToBuffer` function normalizes incoming state data so `drawState()` always sees `{game_state_objects: [...], removed: [...]}`.
**When to use:** On every state buffer push.
**Critical data flow analysis:**

The new format arrives differently depending on the path:

**Server-auth path** (SocketIO `server_render_state` event):
```
Python: render_state = env.render()  → returns RenderPacket.to_dict()
        = {"game_state_objects": [...], "removed": [...]}
Server sends: {render_state: {"game_state_objects": [...], "removed": [...]}, step: N, ...}
JS receives: state_data.render_state = {"game_state_objects": [...], "removed": [...]}
```
Current code does: `state_data.game_state_objects = state_data.render_state` -- this would nest the dict WRONG.
Fix: Unwrap `render_state.game_state_objects` and `render_state.removed`.

**Pyodide path** (pyodide_remote_game.js):
```
Python: render_state = env.render()  → returns RenderPacket (Python object)
Pyodide toJs(): converts to JS Map/Object
JS wraps: render_state = {"game_state_objects": ..., "step": N}
```
Current code calls `render_state.map(item => ...)` which will FAIL on a dict/Map.
Fix: The Pyodide wrapping code must detect RenderPacket format and unwrap `.game_state_objects` and `.removed` properly.

**Example normalized addStateToBuffer:**
```javascript
export function addStateToBuffer(state_data) {
    // Server-auth path: render_state contains the RenderPacket dict
    if (state_data.render_state) {
        if (state_data.render_state.game_state_objects !== undefined) {
            // New RenderPacket format: unwrap
            state_data.game_state_objects = state_data.render_state.game_state_objects;
            state_data.removed = state_data.render_state.removed || [];
        } else {
            // Fallback (shouldn't happen with new-only format)
            state_data.game_state_objects = state_data.render_state;
        }
    }
    if (state_data.game_state_objects == null) {
        console.warn("game_state is null, skipping frame");
        return;
    }
    stateBuffer.push(state_data);
}
```

### Anti-Patterns to Avoid
- **Destroying and recreating objects every frame:** The user decision says "update in-place." Only destroy objects explicitly removed or non-permanent objects no longer in the frame.
- **Using separate temp_object_map and perm_object_map:** The old code splits into two maps. The new format already distinguishes permanence via the `permanent` field. Use a single `Map` keyed by uuid, and track permanence as a property on the stored object.
- **Ignoring the `removed` list:** The old code didn't have explicit removals. The new format includes `removed: [...]` which MUST be processed to destroy persistent objects.
- **Skipping tweens when one is in-progress:** The old code checks `container.tween === null` and does nothing if a tween is running. The user decision requires canceling the old tween.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Smooth interpolation | Manual lerp per frame | `this.tweens.add({...})` | Phaser's tween system handles timing, RAF sync, and cleanup automatically |
| Hex color parsing | Custom parser | `parseInt(str.replace('#', ''), 16)` | Existing `_strToHex` method already does this correctly |
| Object pooling | Custom pool for Graphics | Let Phaser manage creation/destruction | The expected object count (~100-1000) doesn't warrant pooling complexity |
| Shape hit testing | Custom bounds checking | Not needed | This is a rendering-only phase; no interaction |

**Key insight:** The renderer is a display-only consumer of server-generated data. It does not need physics, hit testing, or input handling for rendered objects. Keep changes focused on visual rendering.

## Common Pitfalls

### Pitfall 1: Wire Format Field Name Mismatches
**What goes wrong:** The Surface API emits `object_type: "rect"` but the old renderer checked for `"rectangle"`. The Surface uses `w`/`h` for dimensions but sprites used `width`/`height`.
**Why it happens:** Phase 97 defined a new, cleaner naming convention. The old renderer used legacy names.
**How to avoid:** Update ALL type checks and field reads to match the new wire format exactly:
- `"rect"` (not `"rectangle"`)
- `config.w` and `config.h` (not `config.width`, `config.height`)
- `config.uuid` (same as before)
- `config.permanent` (same as before)
- `config.tween` (boolean, same)
- `config.tween_duration` (number, same)
**Warning signs:** Objects not appearing (type check falls through to `console.warn`).

### Pitfall 2: Nested RenderPacket in addStateToBuffer
**What goes wrong:** `state_data.game_state_objects` is set to the entire RenderPacket dict `{"game_state_objects": [...], "removed": [...]}` instead of the flat array.
**Why it happens:** The current normalization does `state_data.game_state_objects = state_data.render_state`, but `render_state` is now a dict, not an array.
**How to avoid:** Check if `render_state` has a `game_state_objects` property and unwrap it.
**Warning signs:** `forEach is not a function` error in `drawState()` when iterating `game_state_objects`.

### Pitfall 3: Pyodide Path Assumes render_state is Array
**What goes wrong:** `pyodide_remote_game.js` and `pyodide_multiplayer_game.js` call `render_state.map(item => convertUndefinedToNull(item))` which fails if `render_state` is a dict.
**Why it happens:** Old format was a flat array of object dicts. New format is `{game_state_objects: [...], removed: [...]}`.
**How to avoid:** Update the Pyodide render wrapping to detect the new format. If `render_state` has a `game_state_objects` key (is a Map/Object), extract and use it directly instead of calling `.map()`.
**Warning signs:** `render_state.map is not a function` error in browser console.

### Pitfall 4: Alpha Defaults to Undefined
**What goes wrong:** Circles and polygons render as fully transparent because `alpha` is `undefined` and Phaser's `fillStyle(color, undefined)` treats it as 0.
**Why it happens:** The Surface API does not emit an `alpha` field in the wire format.
**How to avoid:** Default alpha to 1.0 in the JS renderer when not present: `config.alpha ?? 1`.
**Warning signs:** Shapes appear invisible despite correct positions.

### Pitfall 5: Tween on First Appearance
**What goes wrong:** An object appears for the first time and immediately tweens from (0,0) to its target position.
**Why it happens:** Creating the container at (0,0) and then tweening to the target in the same frame.
**How to avoid:** The user decision says "First appearance: object appears instantly at position (no fade-in or scale-in)." Create the container AT the target position. Only tween on SUBSEQUENT updates (when the object already exists in the Map).
**Warning signs:** Objects visually fly in from the top-left corner on first frame.

### Pitfall 6: Size Tweening Not Supported in Current Pattern
**What goes wrong:** The user decision says "size (width, height, radius) changes are tweened." But the current Graphics-in-Container pattern draws shapes at fixed sizes on the Graphics. You can't tween Graphics drawing commands.
**Why it happens:** Graphics objects are not scalable in the same way Sprites are.
**How to avoid:** For size changes with tweening, use one of:
  1. Redraw the graphics on each tween frame (expensive, complex)
  2. Use `container.setScale()` to scale the container proportionally, then reset scale + redraw at tween end
  3. Apply Phaser's `scaleX`/`scaleY` tween on the container

  **Recommended approach:** Tween `container.scaleX` and `container.scaleY` for size changes. At the target scale, redraw the graphics at the new actual size and reset scale to 1. This gives smooth visual interpolation without per-frame redraws during the tween.

  For circles: tween scale proportionally (both X and Y same factor based on radius ratio).
  For rects: tween scaleX = newW/oldW, scaleY = newH/oldH.

  **Simpler alternative (recommended for Phase 98):** Since size tweening is less common than position tweening and adds significant complexity, consider making size changes instant (like color) and only tweening position. This aligns with most use cases (moving objects) and avoids the Graphics scaling complexity. The tween_duration parameter primarily serves position interpolation. **However, the user decision explicitly includes size, so this would need user approval.**
**Warning signs:** Jerky size changes or visual artifacts from scale→redraw transitions.

### Pitfall 7: Stale ObjectContext Imports Break Silently
**What goes wrong:** After replacing `object_contexts.py` with stubs, imports in example files still work (no import error), but calling the constructors raises `NotImplementedError` at runtime rather than import time.
**Why it happens:** The stub module defines the same class names but with `__init__` that raises.
**How to avoid:** This is intentional behavior per user decision. The error message "Migrate to Surface API" tells developers what to do. Test that importing works but instantiation raises.
**Warning signs:** None -- this is the desired behavior.

## Code Examples

### Current Wire Format from Surface API (Phase 97)
```python
# What env.render() returns after surface.commit().to_dict():
{
    "game_state_objects": [
        {
            "uuid": "ball",
            "object_type": "circle",
            "depth": 0,
            "tween": True,
            "tween_duration": 100,
            "permanent": False,
            "x": 0.5,          # relative (0-1) coordinates
            "y": 0.3,
            "radius": 0.02,    # relative to max(width, height)
            "color": "#ff0000"
        },
        {
            "uuid": "ground",
            "object_type": "rect",
            "depth": 0,
            "tween": False,
            "tween_duration": 0,
            "permanent": True,
            "x": 0.0,
            "y": 0.8,
            "w": 1.0,
            "h": 0.2,
            "color": "#008000"
        },
        {
            "uuid": "score",
            "object_type": "text",
            "depth": 0,
            "tween": False,
            "tween_duration": 0,
            "permanent": False,
            "text": "Score: 42",
            "x": 0.05,
            "y": 0.02,
            "size": 16,
            "color": "#ffffff",
            "font": "Arial"
        }
    ],
    "removed": ["old_obstacle"]
}
```

### Rectangle Implementation (New)
```javascript
_addRectangle(config, objectMap) {
    let x = config.x * this.width;
    let y = config.y * this.height;
    let w = config.w * this.width;
    let h = config.h * this.height;
    let alpha = config.alpha ?? 1;

    let container = this.add.container(x, y);
    container.setDepth(config.depth);

    let graphics = this.add.graphics();

    // Fill (transparent fill if only stroke is set)
    if (config.color) {
        graphics.fillStyle(this._strToHex(config.color), alpha);
        graphics.fillRect(0, 0, w, h);
    }

    // Stroke
    if (config.stroke_color && config.stroke_width > 0) {
        graphics.lineStyle(config.stroke_width, this._strToHex(config.stroke_color), alpha);
        graphics.strokeRect(0, 0, w, h);
    }

    // Border radius (Phaser 3.80+ supports rounded rect via path)
    // Note: Phaser Graphics doesn't have a built-in rounded rect.
    // For border_radius support, use graphics path commands.

    container.add(graphics);
    container.tween = null;
    container.graphics = graphics;
    container.lastConfig = config;
    container.permanent = config.permanent || false;
    objectMap.set(config.uuid, container);
}
```

### Stroke Rendering for Circle
```javascript
_addCircle(config, objectMap) {
    let x = config.x * this.width;
    let y = config.y * this.height;
    let radius = config.radius * Math.max(this.width, this.height);
    let alpha = config.alpha ?? 1;

    let container = this.add.container(x, y);
    container.setDepth(config.depth);

    let graphics = this.add.graphics();

    // Fill
    if (config.color) {
        graphics.fillStyle(this._strToHex(config.color), alpha);
        graphics.fillCircle(0, 0, radius);
    }

    // Stroke
    if (config.stroke_color && config.stroke_width > 0) {
        graphics.lineStyle(config.stroke_width, this._strToHex(config.stroke_color), alpha);
        graphics.strokeCircle(0, 0, radius);
    }

    container.add(graphics);
    container.tween = null;
    container.graphics = graphics;
    container.lastConfig = config;
    container.permanent = config.permanent || false;
    objectMap.set(config.uuid, container);
}
```

### Fixed Tween Logic (Cancel + Restart)
```javascript
_applyPositionTween(container, newX, newY, duration) {
    if (newX === container.x && newY === container.y) return;

    // Cancel existing tween if in progress
    if (container.tween) {
        container.tween.stop();
        container.tween = null;
    }

    if (duration > 0) {
        container.tween = this.tweens.add({
            targets: [container],
            x: newX,
            y: newY,
            duration: duration,
            ease: 'Linear',
            onComplete: () => {
                container.tween = null;
            }
        });
    } else {
        container.x = newX;
        container.y = newY;
    }
}
```

### Text with Configurable Color
```javascript
_addText(config, objectMap) {
    let x = config.x * this.width;
    let y = config.y * this.height;
    let color = config.color || "#000000";  // Default black, but configurable

    let text = this.add.text(x, y, config.text, {
        fontFamily: config.font || "Arial",
        fontSize: config.size || 16,
        color: color  // Wire format sends hex string directly
    });
    text.setDepth(config.depth || 0);
    text.permanent = config.permanent || false;
    objectMap.set(config.uuid, text);
}

_updateText(config, objectMap) {
    let text = objectMap.get(config.uuid);
    text.x = config.x * this.width;
    text.y = config.y * this.height;
    text.setText(config.text);
    // Update color if changed
    text.setColor(config.color || "#000000");
    text.setFontSize(config.size || 16);
}
```

### ObjectContext Stub Module
```python
# mug/configurations/object_contexts.py -- replacement stub
"""Legacy ObjectContext classes -- DEPRECATED.

These classes have been replaced by the Surface API in mug.rendering.
Import and use mug.rendering.Surface instead.
"""

class _DeprecatedObjectContext:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Migrate to Surface API")

    def as_dict(self):
        raise NotImplementedError("Migrate to Surface API")

# Preserve all class names so existing imports don't fail at import time
Sprite = type("Sprite", (_DeprecatedObjectContext,), {})
Circle = type("Circle", (_DeprecatedObjectContext,), {})
Line = type("Line", (_DeprecatedObjectContext,), {})
Polygon = type("Polygon", (_DeprecatedObjectContext,), {})
Text = type("Text", (_DeprecatedObjectContext,), {})
AtlasSpec = type("AtlasSpec", (_DeprecatedObjectContext,), {})
MultiAtlasSpec = type("MultiAtlasSpec", (_DeprecatedObjectContext,), {})
ImgSpec = type("ImgSpec", (_DeprecatedObjectContext,), {})
```

## Critical Data Flow Analysis

### Server-Auth Path (SocketIO)
```
Python env.render() → RenderPacket.to_dict()
    = {"game_state_objects": [...], "removed": [...]}
         ↓
render_server_game() sends via SocketIO:
    {render_state: {"game_state_objects": [...], "removed": [...]}, step: N, ...}
         ↓
index.js socket.on('server_render_state') → addStateToBuffer(data)
    data.render_state = {"game_state_objects": [...], "removed": [...]}
         ↓
addStateToBuffer MUST unwrap:
    data.game_state_objects = data.render_state.game_state_objects
    data.removed = data.render_state.removed
         ↓
stateBuffer.push(data)
         ↓
processRendering() → drawState()
    this.state.game_state_objects = [...]   ← flat array
    this.state.removed = [...]               ← array of IDs
```

### Pyodide Path
```
Python env.render() → RenderPacket object
    (Pyodide toJs() converts to JS object/Map)
         ↓
pyodide_remote_game.js wraps:
    CURRENT (BROKEN): render_state.map(item => convertUndefinedToNull(item))
    FIX NEEDED: detect dict format, extract .game_state_objects and .removed
         ↓
render_state = {
    "game_state_objects": extractedObjects,
    "removed": extractedRemoved,
    "step": this.step_num
}
         ↓
addStateToBuffer(render_state)
    → already has game_state_objects as flat array
```

### Key Concern: What Does env.render() Return?
The Surface's `commit()` returns a `RenderPacket` Python object. For the server-auth path (SocketIO), this needs to be JSON-serializable. The env's `render()` method should call `self.surface.commit().to_dict()` to return a plain dict.

For the Pyodide path, the Python `env.render()` returns a `RenderPacket`. Pyodide's `toPy().toJs()` chain will convert the dataclass to a JS object. The wrapping code in `pyodide_remote_game.js` must handle this new format.

**The safest convention:** `env.render()` always returns `self.surface.commit().to_dict()` -- a plain Python dict. This works for both SocketIO serialization and Pyodide conversion.

## Object Type to JS Renderer Mapping

| Wire `object_type` | JS Add Method | JS Update Method | Container Pattern | Stroke Support |
|---------------------|---------------|------------------|-------------------|----------------|
| `"rect"` | `_addRectangle` | `_updateRectangle` | YES (new) | YES |
| `"circle"` | `_addCircle` | `_updateCircle` | YES (existing) | YES (add) |
| `"line"` | `_addLine` | `_updateLine` | NO (Graphics only) | N/A (lines are strokes) |
| `"polygon"` | `_addPolygon` | `_updatePolygon` | YES (existing) | YES (add) |
| `"text"` | `_addText` | `_updateText` | NO (Phaser Text) | NO |
| `"sprite"` | `_addSprite` | `_updateSprite` | NO (Phaser Sprite) | NO |
| `"arc"` | `_addArc` | `_updateArc` | YES (new) | Not required |
| `"ellipse"` | `_addEllipse` | `_updateEllipse` | YES (new) | Not required |

**Note on arc and ellipse:** The Surface API can produce these types, but they are not in the Phase 98 requirements. The renderer should log `console.warn` for unknown types (which it already does). Arc and ellipse rendering can be deferred.

## Files Modified by This Phase

| File | Changes | Risk |
|------|---------|------|
| `mug/server/static/js/phaser_gym_graphics.js` | Major: rewrite drawState, implement rect, fix tweens, add stroke, fix text color, consolidate object maps | High -- core rendering logic |
| `mug/server/static/js/pyodide_remote_game.js` | Moderate: update render wrapping to handle RenderPacket dict format | Medium -- two code paths (reset + step) |
| `mug/server/static/js/pyodide_multiplayer_game.js` | Moderate: same render wrapping updates as pyodide_remote_game | Medium -- same pattern |
| `mug/configurations/object_contexts.py` | Replace: delete content, replace with stub classes | Low -- stubs are simple |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Two separate object maps (temp/perm) | Single Map keyed by uuid | This phase (98) | Simpler lookup, consistent with delta format |
| Flat list of object dicts | RenderPacket with objects + removed lists | Phase 97 introduced Python side, Phase 98 JS side | Delta support for persistent objects |
| Skip new tweens while one is running | Cancel old tween, start fresh | This phase (98) | Objects track latest target position smoothly |
| Text color hardcoded `#000` | Text color from wire format | This phase (98) | Configurable text appearance |
| ObjectContext dataclasses | Surface draw-call API (Phase 97) + stub ObjectContext | This phase (98) | Clean break from legacy |

## Open Questions

1. **Should size changes be tweened or instant?**
   - What we know: The user decision says "position (x, y) and size (width, height, radius) changes are tweened over tween_duration."
   - What's unclear: Graphics-in-Container pattern makes size tweening complex (requires scale tweening + redraw at completion).
   - Recommendation: Implement size tweening via container `scaleX`/`scaleY` tweens with redraw on completion. The complexity is manageable for the expected shape types. If this proves too complex during implementation, position-only tweening can be a fallback with user approval.

2. **What about border_radius for rectangles?**
   - What we know: The Surface API supports `border_radius` on `rect()` and the wire format includes it.
   - What's unclear: Phaser 3 `Graphics` does not have a native `fillRoundedRect`. Rounded rects require path commands.
   - Recommendation: Implement as a Phaser `Graphics.beginPath()` + `arc()` + `lineTo()` path for rounded corners. If `border_radius` is not present or 0, use the simple `fillRect`. This is straightforward geometry.

3. **How should `env.render()` return data for SocketIO compatibility?**
   - What we know: SocketIO needs JSON-serializable data. `RenderPacket` is a dataclass, not directly serializable.
   - What's unclear: Whether `env.render()` should return `RenderPacket` object or `RenderPacket.to_dict()`.
   - Recommendation: Convention: `env.render()` returns `self.surface.commit().to_dict()`. This returns a plain dict that works with both SocketIO JSON serialization and Pyodide toJs() conversion. Phase 99 (example migration) should follow this convention.

4. **Should `_addLine` be refactored to Container pattern?**
   - What we know: Lines currently use raw Graphics without a container. The wire format supports tweening for lines.
   - What's unclear: Lines are defined by multiple points, so "position tweening" is ambiguous (translate all points? tween individual points?).
   - Recommendation: Keep lines as Graphics-only (no container, no tweening). Line positions change by redrawing. This matches the current implementation and lines are rarely tweened in practice.

## Sources

### Primary (HIGH confidence)
- Codebase: `mug/server/static/js/phaser_gym_graphics.js` -- complete existing JS renderer (1347 lines), all add/update methods, tween patterns, drawState logic
- Codebase: `mug/rendering/surface.py` -- Phase 97 Surface API, `_to_wire()` wire format, field names (`w`, `h`, `x`, `y`, `radius`, `color`, `stroke_color`, `stroke_width`)
- Codebase: `mug/rendering/types.py` -- `RenderPacket.to_dict()` output structure
- Codebase: `mug/server/game_manager.py:render_server_game()` -- server-auth render and SocketIO emission path
- Codebase: `mug/server/static/js/index.js` -- socket event handlers calling `addStateToBuffer`
- Codebase: `mug/server/static/js/pyodide_remote_game.js` -- Pyodide render wrapping that must be updated
- Codebase: `mug/server/static/js/pyodide_multiplayer_game.js` -- multiplayer Pyodide render wrapping
- Codebase: `mug/configurations/object_contexts.py` -- legacy classes to be replaced with stubs
- Codebase: `mug/server/static/templates/index.html` line 331 -- Phaser 3.80.1 CDN reference
- Codebase: all import sites for object_contexts (26 files total across examples, docs, configs)

### Secondary (MEDIUM confidence)
- Phaser 3 API: `this.tweens.add()` with `stop()` for cancellation -- verified from existing codebase usage patterns
- Phaser 3 API: `Graphics.fillRect()`, `Graphics.strokeRect()`, `Graphics.fillCircle()`, `Graphics.strokeCircle()` -- standard Phaser 3 Graphics API

### Tertiary (LOW confidence)
- Phaser 3 rounded rectangle via path commands -- not verified in this codebase, standard Phaser capability per training data

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- Phaser 3.80.1 is already in use, all APIs verified from existing codebase
- Architecture: HIGH -- Container+Graphics pattern already proven in codebase for circles and polygons
- Pitfalls: HIGH -- identified from actual data flow analysis through 4 code paths (server-auth, pyodide single, pyodide multi, direct)
- Wire format: HIGH -- verified field names from Phase 97 `_to_wire()` implementation

**Research date:** 2026-02-20
**Valid until:** 2026-04-20 (stable domain, Phaser version pinned)
