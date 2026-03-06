# Phase 97: Python Surface Core - Research

**Researched:** 2026-02-20
**Domain:** Python drawing API design, state delta computation, wire format serialization
**Confidence:** HIGH

## Summary

Phase 97 creates a new `Surface` class that replaces the current `ObjectContext` dataclass-based rendering approach with a PyGame-inspired imperative draw-call API. The current system requires researchers to manually instantiate `Circle`, `Line`, `Polygon`, `Text`, and `Sprite` dataclass objects and return lists of dictionaries from `env.render()`. The new Surface API will let researchers call `surface.rect()`, `surface.circle()`, etc. as side effects, then `surface.commit()` returns a serializable `RenderPacket`.

This is a pure Python library phase with no external dependencies. The entire implementation lives within the `mug` package. The existing wire format (lists of object dictionaries with `uuid`, `object_type`, `permanent`, and type-specific fields) is already understood by the JS renderer in `phaser_gym_graphics.js`. The new Surface API must produce output compatible with this existing renderer (Phase 98 updates the renderer, but the wire format from Phase 97 should be designed to map cleanly).

**Primary recommendation:** Create a new `mug/rendering/` subpackage containing `surface.py` (Surface class), `color.py` (color normalization), and `types.py` (RenderPacket, DrawCommand dataclasses). Use full object replacement for delta granularity (not property-level diffs) to keep complexity manageable. The Surface tracks persistent objects by `id`, compares against previously-committed state via dict equality, and emits only changed/new/removed objects.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- All keyword arguments for draw methods: `surface.rect(x=100, y=200, w=50, h=30, color='red')`
- Draw calls are fire-and-forget (return None) -- pure side effects, like PyGame
- Researcher creates Surface themselves: `self.surface = Surface(width=800, height=600)` in `__init__`
- Auto-clear ephemeral draws after `commit()` -- next frame starts fresh, persistent objects remain
- Both lifecycles valid: create once in `__init__` and reuse (required for persistence), or create per-call for stateless rendering
- Ephemeral by default -- objects disappear after `commit()` unless marked `persistent=True`
- `persistent=True` requires an `id=` parameter (raise error if missing)
- Update persistent objects by redrawing with same `id=` and new params -- delta engine detects changes
- Remove persistent objects explicitly via `surface.remove(id='name')`
- `surface.reset()` clears all persistent tracking for episode boundaries
- Origin is top-left, y increases downward (matches PyGame, HTML Canvas, Phaser)
- Pixel coordinates by default
- Per-call `relative=True` parameter to use 0-1 coordinates -- can mix pixel and relative in one frame
- For `rect()` and `image()`: (x, y) is the top-left corner
- For `circle()`: (x, y) is the center (natural for circles)
- Surface integrates through `env.render()` -- returns `RenderPacket` from `surface.commit()`
- `render_mode = 'mug'` on the environment class
- Researcher calls `surface.reset()` explicitly in their `env.reset()` method
- No framework magic for episode detection -- explicit is better than implicit

### Claude's Discretion
- Delta granularity: full object replacement vs property-level diffs on persistent object changes
- Exact wire format structure of RenderPacket
- Internal data structures for tracking persistent state
- Error message wording and validation details

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SURF-01 | Draw filled rectangles via `surface.rect()` | Draw method accepting x, y, w, h, color, plus optional id, persistent, relative, depth, border_radius params |
| SURF-02 | Draw filled circles via `surface.circle()` | Draw method accepting x, y, radius, color; center-origin per user decision |
| SURF-03 | Draw lines via `surface.line()` | Draw method accepting points list, color, width |
| SURF-04 | Draw filled polygons via `surface.polygon()` | Draw method accepting points list, color |
| SURF-05 | Render text via `surface.text()` | Draw method accepting text, x, y, size, color, font |
| SURF-06 | Render preloaded images via `surface.image()` | Draw method accepting image_name, x, y, w, h, frame; top-left origin per user decision |
| SURF-07 | Draw outlines (width>0) for rect, circle, polygon | Add `stroke_color=` and `stroke_width=` params to rect, circle, polygon methods |
| SURF-08 | Draw arcs via `surface.arc()` | Draw method accepting x, y, radius, start_angle, end_angle, color |
| SURF-09 | Draw ellipses via `surface.ellipse()` | Draw method accepting x, y, rx, ry, color |
| SURF-10 | Rounded rectangles via `border_radius=` on `rect()` | Optional `border_radius` param on rect method |
| COLOR-01 | RGB tuples `(255, 0, 0)` | Color normalization utility converts tuple to `#rrggbb` |
| COLOR-02 | Hex strings `'#FF0000'` | Color normalization validates and lowercases hex |
| COLOR-03 | Named strings `'red'`, `'blue'` (~20 common) | Inline lookup dict of ~20 CSS named colors to hex |
| COLOR-04 | All draw methods accept any color format | Single `normalize_color()` function called in every draw method |
| COORD-01 | Pixel coordinates by default | Wire format stores values as-is when `relative=False` (default) |
| COORD-02 | Relative (0-1) coordinates when desired | Per-call `relative=True` flag; wire format includes coord mode or pre-converts |
| IDENT-01 | Optional `id=` parameter on any draw call | All draw methods accept `id=` kwarg; auto-generated UUID if not provided |
| IDENT-03 | Control tween duration via `tween_duration=` | All draw methods accept `tween_duration=` kwarg (only meaningful when `id=` is set) |
| DELTA-01 | Mark objects as persistent via `persistent=True` | Draw methods accept `persistent=True`; requires `id=` (validated) |
| DELTA-02 | Surface computes state deltas | `commit()` compares current persistent objects to last-committed state; only changed/new/removed objects emitted |
| DELTA-03 | Surface tracks which persistent objects have been sent | Internal `_committed_persistent` dict stores last-sent state of each persistent object |
| DELTA-04 | `surface.reset()` clears persistent tracking | Clears `_committed_persistent` dict and current ephemeral/persistent buffers |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.10+ | Everything (dataclasses, typing, re, copy, uuid) | Zero dependencies; this is a pure Python data structure layer |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `dataclasses` | stdlib | DrawCommand and RenderPacket definitions | Immutable, serializable command records |
| `copy` | stdlib | Deep comparison of persistent state | Detecting changes between commits |
| `uuid` | stdlib | Auto-generating IDs for ephemeral objects | When user does not provide `id=` |
| `re` | stdlib | Hex color validation | Parsing color input |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Inline named color dict | `webcolors` package | Extra dependency for 20 colors is not justified; inline is simpler |
| dataclass-based DrawCommand | Plain dicts | Dataclasses provide type safety, IDE autocomplete, and validation; dicts are more error-prone |
| `deepcopy` for delta tracking | Manual dict comparison | deepcopy is correct but slow for large objects; for the expected scale (~100-1000 objects) it's fine |

**Installation:**
No new dependencies required. Pure Python stdlib.

## Architecture Patterns

### Recommended Project Structure
```
mug/
├── rendering/
│   ├── __init__.py        # Exports: Surface, RenderPacket
│   ├── surface.py         # Surface class with draw methods and commit()
│   ├── color.py           # normalize_color() and NAMED_COLORS dict
│   └── types.py           # DrawCommand, RenderPacket dataclasses
├── configurations/
│   └── object_contexts.py # EXISTING - legacy ObjectContext classes (preserved)
└── ...
```

### Pattern 1: Command Buffer Pattern
**What:** Draw calls append DrawCommand objects to an internal buffer. `commit()` processes the buffer, computes deltas, and returns a RenderPacket. The buffer is then cleared.
**When to use:** Always -- this is the core pattern for the Surface class.
**Example:**
```python
@dataclasses.dataclass(frozen=True)
class DrawCommand:
    """Immutable record of a single draw call."""
    object_type: str          # "rect", "circle", "line", etc.
    id: str                   # User-provided or auto-generated
    params: dict              # All draw parameters (already normalized)
    persistent: bool = False

class Surface:
    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._ephemeral_buffer: list[DrawCommand] = []
        self._persistent_current: dict[str, DrawCommand] = {}  # id -> command
        self._committed_persistent: dict[str, dict] = {}  # id -> last-sent wire dict

    def rect(self, *, x, y, w, h, color='white', **kwargs):
        color = normalize_color(color)
        cmd = self._build_command("rect", x=x, y=y, w=w, h=h, color=color, **kwargs)
        self._add_command(cmd)

    def commit(self) -> RenderPacket:
        # Build wire-format dicts for all objects
        # Compute delta for persistent objects
        # Return RenderPacket
        # Clear ephemeral buffer
        ...
```

### Pattern 2: Delta Computation via Full Object Comparison
**What:** When `commit()` is called, compare each persistent object's wire-format dict against the last committed version. If they differ, include the object in the delta. Track removed persistent objects separately.
**When to use:** For DELTA-02 and DELTA-03. Full object replacement is simpler than property-level diffing.
**Example:**
```python
def commit(self) -> RenderPacket:
    objects_to_send = []
    removed_ids = []

    # 1. All ephemeral objects always sent
    for cmd in self._ephemeral_buffer:
        objects_to_send.append(cmd.to_wire_dict(self.width, self.height))

    # 2. Persistent objects: only send if new or changed
    for obj_id, cmd in self._persistent_current.items():
        wire = cmd.to_wire_dict(self.width, self.height)
        if obj_id not in self._committed_persistent or self._committed_persistent[obj_id] != wire:
            objects_to_send.append(wire)
            self._committed_persistent[obj_id] = wire

    # 3. Detect removed persistent objects
    for obj_id in list(self._committed_persistent.keys()):
        if obj_id not in self._persistent_current and obj_id not in self._pending_removals:
            pass  # Still there, just not redrawn (persistent stays)
    for obj_id in self._pending_removals:
        removed_ids.append(obj_id)
        self._committed_persistent.pop(obj_id, None)

    # 4. Clear ephemeral buffer (persistent stays)
    self._ephemeral_buffer.clear()
    self._pending_removals.clear()

    return RenderPacket(objects=objects_to_send, removed=removed_ids)
```

### Pattern 3: Wire Format Compatibility
**What:** The wire format must be compatible with the existing JS renderer's `drawState()` method which expects objects with `uuid`, `object_type`, and type-specific fields. The RenderPacket wraps a list of these objects plus a list of removed IDs.
**When to use:** For the `to_wire_dict()` conversion.
**Example:**
```python
# Current JS renderer expects this format:
# {uuid: "id", object_type: "circle", color: "#ff0000", x: 0.5, y: 0.5, radius: 10, ...}
# {uuid: "id", object_type: "sprite", x: 0.5, y: 0.5, image_name: "tex", ...}

# RenderPacket wire format:
{
    "game_state_objects": [...],  # List of object dicts (backward compatible key)
    "removed": [...]              # List of removed IDs (new for delta support)
}
```

### Anti-Patterns to Avoid
- **Storing draw calls as dicts from the start:** Use typed DrawCommand dataclasses for internal representation; convert to dicts only at `to_wire_dict()` time. This enables validation and IDE support.
- **Making Surface a singleton or global:** The user decision explicitly says researchers create their own Surface instances. No global state.
- **Implicit persistence detection:** User explicitly marks `persistent=True`. Never guess based on whether an `id=` was provided.
- **Lazy color normalization:** Always normalize color at draw-call time, not at commit time. Fail fast on bad input.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Color validation | Custom regex for every format | Single `normalize_color()` function with known pattern | Centralizes all color handling; prevents inconsistency |
| UUID generation | Custom counter-based IDs | `uuid.uuid4().hex[:8]` | Unique across frames, no collision risk |
| Deep comparison | Custom recursive dict diff | `dict.__eq__` on wire-format dicts | Python dicts with simple values (str, int, float, list) compare correctly by value |

**Key insight:** The Surface API is a thin command-recording layer. The complexity is in the ergonomics (keyword args, color normalization, coordinate modes) and correctness (delta computation, persistence tracking), not in any algorithmic difficulty. Keep it simple.

## Common Pitfalls

### Pitfall 1: Forgetting to Clear Ephemeral Buffer After Commit
**What goes wrong:** If ephemeral objects from the previous frame leak into the next commit, the JS renderer will see duplicate objects.
**Why it happens:** Forgetting to call `self._ephemeral_buffer.clear()` at the end of `commit()`.
**How to avoid:** Clear the ephemeral buffer as the last step in `commit()`. Test explicitly that calling `commit()` twice without new draws produces an empty delta.
**Warning signs:** Visual artifacts -- objects appearing twice or ghost objects from previous frames.

### Pitfall 2: Persistent Object Update Misdetection
**What goes wrong:** A persistent object is redrawn with identical parameters, but the delta engine incorrectly detects it as changed and retransmits.
**Why it happens:** Floating point comparison, dict ordering, or reference equality vs value equality issues.
**How to avoid:** Convert to wire-format dicts before comparison. Use `==` on dicts (which does deep value comparison for simple types). Be careful with float coordinates -- consider rounding or using a tolerance.
**Warning signs:** Non-empty deltas when nothing visually changed; excessive bandwidth usage.

### Pitfall 3: Missing ID Validation for Persistent Objects
**What goes wrong:** User passes `persistent=True` without `id=`, leading to auto-generated UUIDs that change every frame, defeating persistence.
**Why it happens:** Not validating the id/persistent combination.
**How to avoid:** Raise `ValueError` immediately in the draw method if `persistent=True` and `id` is not provided. This is a locked user decision.
**Warning signs:** Persistent objects being retransmitted every frame.

### Pitfall 4: Coordinate Mode Confusion in Wire Format
**What goes wrong:** The JS renderer doesn't know whether coordinates are pixel or relative, leading to misplaced objects.
**Why it happens:** The current renderer assumes ALL coordinates are relative (0-1) -- it multiplies by `this.width` and `this.height`. If we send pixel coordinates without conversion, objects render in wrong positions.
**How to avoid:** The wire format should always contain relative (0-1) coordinates for compatibility with the existing JS renderer. The Surface's `commit()` should convert pixel coordinates to relative using `self.width` and `self.height`. This way the JS renderer continues to work without modification in Phase 97, and Phase 98 can update the renderer to handle both modes.
**Warning signs:** Objects appearing at coordinates 100x their expected size.

### Pitfall 5: Reset Not Clearing Everything
**What goes wrong:** After `surface.reset()`, persistent objects from the previous episode are not retransmitted because the committed state wasn't cleared.
**Why it happens:** Reset clears the current persistent buffer but forgets to clear `_committed_persistent`.
**How to avoid:** `reset()` must clear ALL internal state: `_ephemeral_buffer`, `_persistent_current`, `_committed_persistent`, and `_pending_removals`.
**Warning signs:** Blank screen after episode reset (persistent background objects not retransmitted).

### Pitfall 6: Wire Format Backward Compatibility Break
**What goes wrong:** New Surface output breaks existing JS renderer which expects `game_state_objects` key with flat object list.
**Why it happens:** Changing the wire format structure without maintaining backward compatibility.
**How to avoid:** The RenderPacket's serialization should include `game_state_objects` as the key name (matching existing format). The `removed` list is additive -- the existing renderer ignores unknown keys, so it's safe to add.
**Warning signs:** Blank canvas or JS errors in the browser.

## Code Examples

Verified patterns from codebase analysis:

### Current Wire Format (Object Context)
```python
# From slimevb_env.py - current approach
from mug.configurations.object_contexts import Circle, Line, Polygon

def render(self):
    render_objects = []
    ball = Circle(
        uuid="ball",
        color="#000000",
        x=0.5,  # relative coordinate
        y=0.3,
        radius=10,
    )
    render_objects.append(ball)
    return [obj.as_dict() for obj in render_objects]
# Returns: [{"uuid": "ball", "object_type": "circle", "color": "#000000", "x": 0.5, ...}]
```

### New Surface API (Target)
```python
# How researchers will use the new Surface API
from mug.rendering import Surface

class MyEnv:
    def __init__(self):
        self.surface = Surface(width=800, height=600)

    def reset(self):
        self.surface.reset()
        # Draw persistent background
        self.surface.rect(x=0, y=500, w=800, h=100, color='green', id='ground', persistent=True)
        # ... env reset logic ...

    def render(self):
        # Ephemeral objects -- redrawn each frame
        self.surface.circle(x=self.ball_x, y=self.ball_y, radius=10, color='red')
        # Commit and return
        return self.surface.commit()
```

### Color Normalization
```python
NAMED_COLORS = {
    'red': '#ff0000', 'green': '#008000', 'blue': '#0000ff',
    'white': '#ffffff', 'black': '#000000', 'yellow': '#ffff00',
    'cyan': '#00ffff', 'magenta': '#ff00ff', 'orange': '#ffa500',
    'purple': '#800080', 'pink': '#ffc0cb', 'brown': '#a52a2a',
    'gray': '#808080', 'grey': '#808080', 'lime': '#00ff00',
    'navy': '#000080', 'teal': '#008080', 'maroon': '#800000',
    'olive': '#808000', 'aqua': '#00ffff',
}

def normalize_color(color) -> str:
    """Normalize any supported color format to '#rrggbb' hex string."""
    if isinstance(color, tuple):
        if len(color) != 3 or not all(isinstance(c, int) and 0 <= c <= 255 for c in color):
            raise ValueError(f"RGB tuple must be 3 ints 0-255, got {color}")
        return f'#{color[0]:02x}{color[1]:02x}{color[2]:02x}'
    if isinstance(color, str):
        lower = color.lower().strip()
        if lower in NAMED_COLORS:
            return NAMED_COLORS[lower]
        if re.match(r'^#[0-9a-f]{6}$', lower):
            return lower
        if re.match(r'^#[0-9a-f]{3}$', lower):
            # Expand shorthand: #abc -> #aabbcc
            return f'#{lower[1]*2}{lower[2]*2}{lower[3]*2}'
        raise ValueError(f"Unrecognized color string: {color!r}")
    raise TypeError(f"Color must be RGB tuple or string, got {type(color).__name__}")
```

### Coordinate Conversion
```python
def _to_wire_coords(self, x, y, relative: bool) -> tuple[float, float]:
    """Convert coordinates to relative (0-1) for wire format.

    The JS renderer always multiplies by canvas width/height,
    so we must send relative coordinates.
    """
    if relative:
        return (x, y)  # Already 0-1
    else:
        return (x / self.width, y / self.height)
```

### Delta-Aware Commit
```python
def commit(self) -> dict:
    """Commit current frame and return serializable RenderPacket."""
    objects = []
    removed = list(self._pending_removals)

    # All ephemeral objects always included
    for cmd in self._ephemeral_buffer:
        objects.append(self._to_wire(cmd))

    # Persistent: only include if new or changed
    for obj_id, cmd in self._persistent_current.items():
        wire = self._to_wire(cmd)
        prev = self._committed_persistent.get(obj_id)
        if prev != wire:
            objects.append(wire)
            self._committed_persistent[obj_id] = wire

    # Process removals
    for obj_id in removed:
        self._committed_persistent.pop(obj_id, None)

    # Clear frame state
    self._ephemeral_buffer.clear()
    self._pending_removals.clear()

    return {
        "game_state_objects": objects,
        "removed": removed,
    }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `env_to_state_fn` callback on scene config | `env.render()` returning object list | v1.1 (Phase 93+) | Server game loop calls `env.render()` directly; `env_to_state_fn` still exists on scene config but is unused in server loop |
| `render_mode = "interactive_gym"` | `render_mode = "mug"` | Feature branch (current) | SlimeVB env already uses `render_mode = "mug"`; server's `_build_env` still sets `"interactive_gym"` |
| ObjectContext dataclasses (Circle, Line, etc.) | Surface draw-call API | This phase (97) | ObjectContext classes preserved for backward compatibility; Surface is the new recommended API |

**Key observation:** There is a disconnect in the codebase:
- `_build_env()` in `remote_game.py` (line 352) sets `render_mode = "interactive_gym"`
- But `SlimeVBEnvIG` already expects `render_mode = "mug"` (line 186)
- The `env_to_state_fn` is defined on GymScene but never called in `render_server_game()`
- `render_server_game()` calls `game.env.render()` directly

This means Phase 97 should:
1. Have `_build_env()` set `render_mode = "mug"` instead of `"interactive_gym"`
2. The Surface API integrates cleanly because `env.render()` already returns the wire format directly
3. `env_to_state_fn` can be deprecated (but not removed -- backward compat)

## Open Questions

1. **How should arc() and ellipse() map to the wire format?**
   - What we know: The existing JS renderer in `phaser_gym_graphics.js` has no `_addArc` or `_addEllipse` methods. It only handles: sprite, line, circle, rectangle, polygon, text.
   - What's unclear: Phase 97 needs to define the wire format for arc and ellipse, but Phase 98 is where the JS renderer gets updated.
   - Recommendation: Define the `object_type` values as `"arc"` and `"ellipse"` in the wire format. The Python side produces them; the JS side will handle them in Phase 98. For Phase 97, the wire format is correct even if the JS can't render them yet.

2. **Should `render_server_game()` be updated to handle the new RenderPacket format?**
   - What we know: Currently `render_server_game()` calls `game.env.render()` and sends the result directly via SocketIO. The result is a list of dicts. The new Surface returns `{"game_state_objects": [...], "removed": [...]}`.
   - What's unclear: The `addStateToBuffer` JS function normalizes `render_state` to `game_state_objects`. The dict format from Surface includes `game_state_objects` as a key.
   - Recommendation: The new format is compatible. `addStateToBuffer` sets `state_data.game_state_objects = state_data.render_state` when the `render_state` key exists. Since `render_server_game` sends `{"render_state": render_state, ...}`, and `render_state` is now `{"game_state_objects": [...], "removed": [...]}`, the JS will set `state_data.game_state_objects = {"game_state_objects": [...], "removed": [...]}` which is WRONG -- it'll be nested. This needs attention in the wire format design. Either `env.render()` should return the flat list (backward compat) and RenderPacket should have a `.to_legacy()` method, or the `addStateToBuffer` normalization needs updating (Phase 98).

3. **Should `stroke_width` and `stroke_color` use outline-only or filled+outline?**
   - What we know: SURF-07 says "draw outlines (width>0) for rect, circle, polygon"
   - What's unclear: Does `stroke_width > 0` mean ONLY stroke (no fill), or fill + stroke border?
   - Recommendation: Follow PyGame convention -- `width=0` means filled, `width>0` means outline only. But also allow both via separate `stroke_width` and `stroke_color` params (fill when `color` is set, outline when `stroke_width > 0`). This is more flexible.

## Sources

### Primary (HIGH confidence)
- Codebase analysis: `mug/configurations/object_contexts.py` -- existing wire format (Circle, Line, Polygon, Text, Sprite dataclasses)
- Codebase analysis: `mug/server/static/js/phaser_gym_graphics.js` -- JS renderer consuming wire format (drawState, _addCircle, _updateCircle, etc.)
- Codebase analysis: `mug/server/game_manager.py:render_server_game()` -- server game loop render path
- Codebase analysis: `mug/server/remote_game.py:_build_env()` -- render_mode injection
- Codebase analysis: `mug/examples/slime_volleyball/slimevb_env.py` -- existing env.render() implementation
- Codebase analysis: `mug/examples/cogrid/overcooked_utils.py` -- sprite-based rendering with permanent objects
- Codebase analysis: `mug/examples/mountain_car/mountain_car_rgb_env.py` -- simple rendering example

### Secondary (MEDIUM confidence)
- PyGame draw API conventions (center-origin circles, top-left-origin rects, width=0 for fill)
- HTML Canvas coordinate conventions (top-left origin, y-down)

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- pure Python stdlib, no external dependencies to research
- Architecture: HIGH -- based on thorough codebase analysis of existing wire format and JS renderer
- Pitfalls: HIGH -- identified from actual codebase patterns (coordinate conversion, wire format key naming, delta logic)

**Research date:** 2026-02-20
**Valid until:** 2026-04-20 (stable domain, no fast-moving dependencies)
