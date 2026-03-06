# Phase 99: Example Migration - Research

**Researched:** 2026-02-20
**Domain:** Python Surface API migration — converting existing ObjectContext-based render functions to Surface draw-call API
**Confidence:** HIGH

## Summary

This phase migrates two reference environments (Slime Volleyball and Overcooked) from the deprecated `ObjectContext` rendering pattern to the new `Surface` draw-call API built in Phases 97-98. The migration is mechanical: each old `ObjectContext` class (Circle, Line, Polygon, Sprite, Text) maps directly to a `Surface` draw method (`.circle()`, `.line()`, `.polygon()`, `.image()`, `.text()`). The Surface handles delta compression automatically, so the old `if env.t == 0:` first-frame guard for persistent objects is replaced by simply marking objects `persistent=True` every frame and letting the Surface skip retransmission.

The biggest complexity is scope: there are 12+ Overcooked environment initialization files that each duplicate the full render function set. All must be migrated. The Slime Volleyball side is simpler with 2 files containing render logic. The wire format (`RenderPacket.to_dict()`) is already supported by both the Pyodide JS wrapper and the server-authoritative `game_manager.py`, so no JS changes are needed.

**Primary recommendation:** Migrate Slime Volleyball first (simpler, fewer files, validates the pattern), then apply the same pattern to Overcooked (more complex, many files, sprite-heavy).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Rendering logic lives in `env.render()` on the environment class, not standalone functions
- Env owns its Surface: `self.surface = Surface()` initialized in `__init__`
- `env.render()` draws to `self.surface`, calls `self.surface.render()`, and returns the RenderPacket dict
- Framework calls `env.render()` directly — no wrapper functions needed
- Config references `env.render()` directly instead of old `env_to_state_fn` parameter
- Surface has asset registration methods directly: `surface.register_atlas(key, image_path, json_path)` and `surface.register_image(key, path)`
- Assets registered in env `__init__` via Surface methods
- `surface.get_asset_specs()` returns registered assets in the format the config system expects — drop-in replacement for old AtlasSpec lists
- Surface validates atlas keys at draw time — `surface.sprite()` with an unregistered key raises an error early in Python
- Draw everything every frame with `persistent=True` for static objects — Surface handles delta tracking automatically
- Env's `reset()` calls `self.surface.reset()` to clear persistent tracking at episode boundaries
- Slime Volleyball stays with relative (0-1) coordinates; Overcooked stays with pixel coordinates
- Slime Volleyball agents stay as geometric primitives (polygon body + circle eyes), not sprites
- Delete all old standalone render functions entirely
- Delete old `preload_assets_spec` functions
- Remove `env_to_state_fn` and `preload_assets_spec` from config objects
- Delete `_utils.py` files if empty after removing render functions; move any remaining non-rendering helpers into the env class
- Remove all ObjectContext imports from example files

### Claude's Discretion
- Whether to separate static vs dynamic drawing into distinct code blocks or interleave freely
- Internal code organization within env.render() (helper methods on the env class if needed for clarity)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MIGR-01 | Slime Volleyball example migrated from ObjectContext to Surface API | Surface API fully supports all primitives used: polygon (body), circle (eyes, ball, fence_stub), line (fence, ground). Relative coordinates via `relative=True`. `fill_below` passes through Surface's `**common`/`**params` kwargs to wire dict where JS renderer already handles it. |
| MIGR-02 | Overcooked example migrated from ObjectContext to Surface API | Surface `.image()` method maps to wire `"sprite"` object_type. Supports `frame=`, `image_name=`, `tween_duration=`. Pixel coordinates are default (no `relative=True` needed). 12 environment initialization files + 1 utils file + 1 server-auth test fixture all need updating. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `mug.rendering.Surface` | Current (Phase 97) | Draw-call accumulator, delta compression, coordinate normalization | The new rendering API this phase migrates TO |
| `mug.rendering.RenderPacket` | Current (Phase 97) | Wire-format container (`to_dict()` produces `{game_state_objects, removed}`) | Standard wire format, already handled by Pyodide JS and server-auth paths |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `mug.rendering.DrawCommand` | Current (Phase 97) | Immutable draw record (frozen dataclass) | Internal to Surface — not used directly by env code |

### Alternatives Considered
N/A — this phase uses what Phases 97-98 built. No alternatives.

**Installation:** No new packages needed.

## Architecture Patterns

### Recommended Project Structure

The migration moves rendering code FROM standalone utility functions INTO the environment class:

```
# BEFORE (old pattern)
mug/examples/slime_volleyball/
├── slimevb_env.py              # env class + standalone render functions
├── slime_volleyball_utils.py   # more render functions + asset specs
├── slimvb_human_ai.py          # config uses env_to_state_fn=
└── slimevb_human_human.py      # config uses env_to_state_fn=

# AFTER (new pattern)
mug/examples/slime_volleyball/
├── slimevb_env.py              # env class with self.surface, render() method
├── slime_volleyball_utils.py   # ONLY non-rendering helpers (hud_text_fn, page_header_fn)
├── slimvb_human_ai.py          # config has NO env_to_state_fn, NO preload_assets_spec
└── slimevb_human_human.py      # same
```

### Pattern 1: Surface-Based Environment Render

**What:** Environment owns a Surface, draws to it in render(), commits, returns the packet dict.
**When to use:** Every environment that renders to the browser.
**Example:**
```python
# Source: CONTEXT.md decisions + Surface API (mug/rendering/surface.py)
from mug.rendering import Surface

class MyEnv:
    def __init__(self, ...):
        self.surface = Surface(width=600, height=250)
        # Register assets if needed:
        # self.surface.register_atlas("terrain", img_path, json_path)

    def reset(self, ...):
        self.surface.reset()  # Clear persistent tracking at episode boundaries
        # ... normal reset logic ...

    def render(self):
        # Draw persistent objects every frame — Surface handles deltas
        self.surface.line(
            points=[(0.5, 0.3), (0.5, 0.7)],
            color="#000000",
            width=3,
            id="fence",
            persistent=True,
            relative=True,
        )
        # Draw dynamic objects (no persistent flag)
        self.surface.circle(
            x=0.3, y=0.5, radius=0.05,
            color="#FF0000",
            id="ball",
            relative=True,
        )
        packet = self.surface.commit()
        return packet.to_dict()
```

### Pattern 2: ObjectContext → Surface Method Mapping

**What:** Direct mapping from old ObjectContext classes to Surface draw methods.
**When to use:** Every render function being migrated.

| Old ObjectContext | Surface Method | Key Differences |
|-------------------|---------------|-----------------|
| `Circle(uuid=, x=, y=, radius=, color=, permanent=, depth=)` | `surface.circle(id=, x=, y=, radius=, color=, persistent=, depth=)` | `uuid` → `id`, `permanent` → `persistent` |
| `Line(uuid=, points=, color=, width=, permanent=, fill_below=, depth=)` | `surface.line(id=, points=, color=, width=, persistent=, fill_below=, depth=)` | Same renames. `fill_below` passes through `**common` → wire dict |
| `Polygon(uuid=, points=, color=, depth=)` | `surface.polygon(id=, points=, color=, depth=)` | Same renames |
| `Sprite(uuid, x=, y=, height=, width=, image_name=, frame=, permanent=, tween=, tween_duration=, depth=)` | `surface.image(id=, x=, y=, h=, w=, image_name=, frame=, persistent=, tween_duration=, depth=)` | `height` → `h`, `width` → `w`, `tween=True` → provide `tween_duration=` value |
| `Text(uuid=, text=, x=, y=, size=, color=)` | `surface.text(id=, text=, x=, y=, size=, color=)` | Same renames |

### Pattern 3: Coordinate Mode Selection

**What:** Slime Volleyball uses relative (0-1) coordinates, Overcooked uses pixel coordinates.
**When to use:** Every draw call.

```python
# Slime Volleyball: relative=True on every draw call
self.surface.circle(x=0.5, y=0.3, radius=0.02, relative=True, ...)

# Overcooked: pixel coordinates (default, no relative= needed)
self.surface.image(x=45, y=90, w=45, h=45, ...)
# Surface auto-normalizes: x/width, y/height → 0-1 range for wire
```

### Pattern 4: Asset Registration on Surface (NEW — must be added)

**What:** The CONTEXT.md decisions specify `surface.register_atlas()` and `surface.get_asset_specs()` methods, but these DO NOT EXIST on Surface yet.
**When to use:** Any environment that uses sprite atlases or images.

```python
# Per CONTEXT.md decisions, Surface should gain:
surface.register_atlas("terrain", img_path="static/assets/overcooked/sprites/terrain.png",
                       json_path="static/assets/overcooked/sprites/terrain.json")
surface.register_image("slime_red.png", path="static/assets/.../slime_red.png")

# Then config uses:
.assets(assets_to_preload=env.surface.get_asset_specs())
```

**CRITICAL:** These methods must be implemented as part of this phase since the CONTEXT.md locks this decision.

### Anti-Patterns to Avoid
- **First-frame conditional rendering:** Old pattern `if env.t == 0: render_static_objects()` is replaced by drawing persistent objects every frame. Surface handles delta tracking. Do NOT replicate the `if env.t == 0:` guard.
- **Returning a flat list of dicts:** Old pattern `return [obj.as_dict() for obj in render_objects]`. New pattern: `return self.surface.commit().to_dict()` which returns `{"game_state_objects": [...], "removed": [...]}`.
- **Standalone render functions:** Decision locks rendering into `env.render()`. Do NOT create standalone utility functions for rendering.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Delta compression | Manual first-frame tracking | `Surface.commit()` with `persistent=True` | Surface automatically diffs persistent objects |
| Object wire format | Manual dict construction | `Surface._to_wire()` via `commit()` | Handles coordinate normalization, tween flags, etc. |
| Color normalization | Manual hex/rgb/name conversion | Surface's built-in `normalize_color()` | Covers hex, RGB tuple, and named colors |
| Asset spec formatting | Manual AtlasSpec/ImgSpec dicts | `surface.get_asset_specs()` (to be added) | Single source of truth |

**Key insight:** The Surface handles all serialization concerns. The env just calls draw methods and commits.

## Common Pitfalls

### Pitfall 1: Missing `surface.reset()` on Episode Boundaries
**What goes wrong:** Persistent objects are not retransmitted after a reset, so new episode starts with stale rendering state.
**Why it happens:** The old pattern manually checked `if env.t == 0:` to send persistent objects. The new pattern relies on `surface.reset()` clearing the committed cache so all persistent objects are retransmitted.
**How to avoid:** Every env's `reset()` (or `on_reset()`) must call `self.surface.reset()`.
**Warning signs:** Objects from previous episode linger, or static tiles don't appear after episode 2.

### Pitfall 2: Forgetting to Return `packet.to_dict()` Instead of `packet`
**What goes wrong:** Pyodide's `toJs()` can't serialize the dataclass properly.
**Why it happens:** `RenderPacket` is a dataclass, not a dict. The JS side expects a dict with `game_state_objects` key.
**How to avoid:** Always `return self.surface.commit().to_dict()`.
**Warning signs:** TypeError or undefined `game_state_objects` in JS console.

### Pitfall 3: Mixing Up `height`/`width` vs `h`/`w` for Sprites
**What goes wrong:** `surface.image()` uses `h=` and `w=`, but old `Sprite` used `height=` and `width=`.
**Why it happens:** Surface API uses shorter parameter names.
**How to avoid:** Reference the mapping table above during migration.
**Warning signs:** TypeError from unexpected keyword arguments.

### Pitfall 4: Forgetting `tween_duration` Value When Old Code Had `tween=True`
**What goes wrong:** Agent sprites don't tween because `tween_duration` is None (the Surface default).
**Why it happens:** Old `Sprite(tween=True)` is replaced by `surface.image(tween_duration=75)`. Must provide an actual duration.
**How to avoid:** Wherever old code had `tween=True`, provide `tween_duration=` with a sensible value (75ms for Overcooked agents per existing env init files).
**Warning signs:** Agent movement appears jerky instead of smooth.

### Pitfall 5: Many Duplicate Overcooked Files
**What goes wrong:** Migration becomes inconsistent if some files are updated and others forgotten.
**Why it happens:** There are 12 environment initialization files for Overcooked that each independently duplicate the render functions (cramped_room, counter_circuit, forced_coordination, asymmetric_advantages, coordination_ring — each with regular + controllable + HH variants).
**How to avoid:** Migrate all 12 Overcooked env init files + 1 utils file + 1 test fixture. Verify with grep that zero imports from `object_contexts` remain.
**Warning signs:** `NotImplementedError: Sprite is removed. Migrate to Surface API` at runtime.

### Pitfall 6: `fill_below` on Line — Not Explicitly in Surface API
**What goes wrong:** Ground rendering in Slime Volleyball breaks if `fill_below` is not passed through.
**Why it happens:** Surface's `line()` method doesn't have an explicit `fill_below` parameter, but it does have `**common` kwargs that flow through to the wire dict.
**How to avoid:** Pass `fill_below=True` as a keyword argument. It will pass through `**common` → `_build_command(**params)` → `DrawCommand.params` → `_to_wire()` → wire dict. The JS renderer already handles `fill_below`.
**Warning signs:** Ground doesn't render as a filled rectangle below the line.

### Pitfall 7: Surface Asset Registration Methods Don't Exist Yet
**What goes wrong:** Can't call `surface.register_atlas()` or `surface.get_asset_specs()` because they haven't been implemented.
**Why it happens:** Phase 97 built the draw-call API but not asset registration. CONTEXT.md decisions require these methods.
**How to avoid:** Must add `register_atlas()`, `register_image()`, and `get_asset_specs()` to `Surface` class as part of this phase.
**Warning signs:** AttributeError on Surface.

## Code Examples

### Slime Volleyball: Old → New Render Pattern

```python
# OLD (slimevb_env.py)
from mug.configurations.object_contexts import Circle, Line, Polygon

def slime_volleyball_env_to_rendering(env):
    render_objects = []
    if env.t == 0:
        fence = Line(uuid="fence", color="#000000", points=[...], width=..., permanent=True)
        render_objects.append(fence)
    ball = Circle(uuid="ball", color="#000000", x=..., y=..., radius=...)
    render_objects.append(ball)
    return [obj.as_dict() for obj in render_objects]

# NEW (slimevb_env.py)
from mug.rendering import Surface

class SlimeVBEnvIG(slimevolley_env.SlimeVolleyEnv):
    def __init__(self, ...):
        super().__init__(...)
        self.surface = Surface(width=600, height=250)

    def reset(self, ...):
        result = super().reset(...)
        self.surface.reset()
        return result

    def render(self):
        # Persistent objects — drawn every frame, Surface handles deltas
        self.surface.line(
            points=[(to_x(self.game.fence.x), to_y(self.game.fence.y + self.game.fence.h / 2)),
                    (to_x(self.game.fence.x), to_y(self.game.fence.y - self.game.fence.h / 2))],
            color="#000000",
            width=self.game.fence.w * 600 / constants.REF_W,
            id="fence", persistent=True, relative=True,
        )
        # Dynamic objects
        terminateds, _ = self.get_terminateds_truncateds()
        self.surface.circle(
            x=self.game.ball.x / constants.REF_W + 0.5,
            y=1 - self.game.ball.y / constants.REF_W,
            radius=self.game.ball.r * 600 / constants.REF_W,
            color="#000000" if not terminateds["__all__"] else "#AAFF00",
            id="ball", relative=True,
        )
        return self.surface.commit().to_dict()
```

### Overcooked: Old → New Sprite Pattern

```python
# OLD (environment initialization files)
from mug.configurations.object_contexts import Sprite, Text

def generate_counter_objects(env):
    objs = []
    for obj in env.grid.grid:
        if isinstance(obj, grid_object.Counter):
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
            objs.append(Sprite(obj.uuid, x=x, y=y, height=TILE_SIZE, width=TILE_SIZE,
                               image_name="terrain", frame="counter.png", permanent=True, depth=-2))
    return objs

# NEW (on the env class)
def render(self):
    for obj in self.grid.grid:
        if isinstance(obj, grid_object.Counter):
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
            self.surface.image(
                image_name="terrain", frame="counter.png",
                x=x, y=y, w=TILE_SIZE, h=TILE_SIZE,
                id=obj.uuid, persistent=True, depth=-2,
            )
    # ... agents, objects, etc. ...
    return self.surface.commit().to_dict()
```

### Asset Registration Pattern

```python
# OLD (overcooked_utils.py)
def overcooked_preload_assets_spec():
    terrain = object_contexts.AtlasSpec(
        name="terrain",
        img_path=os.path.join(ASSET_PATH, "terrain.png"),
        atlas_path=os.path.join(ASSET_PATH, "terrain.json"),
    )
    return [terrain.as_dict(), ...]

# NEW (on the env class __init__)
class OvercookedEnv:
    def __init__(self, ...):
        super().__init__(...)
        self.surface = Surface(width=WIDTH, height=HEIGHT)
        self.surface.register_atlas("terrain",
            img_path="static/assets/overcooked/sprites/terrain.png",
            json_path="static/assets/overcooked/sprites/terrain.json")
        self.surface.register_atlas("chefs", ...)
        self.surface.register_atlas("objects", ...)

# Config:
.assets(assets_to_preload=env.surface.get_asset_specs())
# But note: for Pyodide envs, env is created in-browser, so asset specs
# may need to be provided statically in the config. This is a design question.
```

### Config Changes

```python
# OLD
slime_scene = (
    gym_scene.GymScene()
    .rendering(
        fps=30,
        env_to_state_fn=slime_volleyball_utils.slime_volleyball_env_to_rendering,
        game_width=600, game_height=250,
    )
    .assets(
        assets_to_preload=slime_volleyball_utils.slime_volleyball_preload_assets_spec(),
    )
)

# NEW — env_to_state_fn removed, assets_to_preload may change
slime_scene = (
    gym_scene.GymScene()
    .rendering(
        fps=30,
        game_width=600, game_height=250,
    )
    # assets_to_preload: depends on how asset registration flows for Pyodide envs
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `ObjectContext` dataclass instantiation + `.as_dict()` | `Surface` draw methods + `.commit().to_dict()` | Phase 97 (current branch) | All rendering code must migrate |
| `env_to_state_fn` callback on config | `env.render()` method on env class | Phase 97-98 (current branch) | Config parameter removed |
| `if env.t == 0:` for persistent objects | `persistent=True` every frame, Surface diffs | Phase 97 (current branch) | Simpler rendering code |
| `AtlasSpec`/`ImgSpec` for asset preloading | `surface.register_atlas()`/`surface.get_asset_specs()` | Phase 99 (this phase — to be added) | Asset management moves to Surface |

**Deprecated/outdated:**
- `mug.configurations.object_contexts.Circle/Line/Polygon/Sprite/Text`: raise `NotImplementedError` on instantiation (Phase 98)
- `mug.configurations.object_contexts.AtlasSpec/MultiAtlasSpec/ImgSpec`: raise `NotImplementedError` on instantiation (Phase 98)

## Open Questions

1. **Asset registration for Pyodide environments**
   - What we know: Pyodide envs are initialized in the browser. The config's `.assets(assets_to_preload=...)` is set at server config time. The CONTEXT.md says `surface.get_asset_specs()` replaces old AtlasSpec lists.
   - What's unclear: For Pyodide envs, the env instance doesn't exist at config-definition time. The asset specs must be available before the env is created. For server-auth mode, the env IS created server-side so `env.surface.get_asset_specs()` works. For Pyodide mode, asset specs may need to be defined statically or the config must be populated differently.
   - Recommendation: For Pyodide envs, define asset spec lists as module-level constants (same paths, just using the new dict format that `get_asset_specs()` would return). For server-auth envs, use `surface.get_asset_specs()`. Alternatively, keep `.assets()` as-is with raw dict literals matching the expected format. The planner should decide the cleanest approach per the user's decision that "Surface validates atlas keys at draw time."

2. **Scope of Overcooked file migration**
   - What we know: There are 12 environment init files + 1 overcooked_utils.py + 1 test fixture, all containing duplicated render functions using deprecated ObjectContext classes. The user decision says "delete all old standalone render functions entirely."
   - What's unclear: Whether ALL 12 env init files need full migration, or just the primary ones (cramped_room variants). The controllable variants and other layout variants all have identical render logic.
   - Recommendation: Migrate ALL files. They will all crash at import time if ObjectContext classes remain (they raise `NotImplementedError`). The render functions are identical across files, so a consistent mechanical replacement is straightforward.

3. **`env_to_state_fn` removal from scene configs**
   - What we know: The server-auth `game_manager.py` already calls `game.env.render()` directly and never calls `env_to_state_fn`. For Pyodide, the JS wrapper calls `env.render()` directly. So `env_to_state_fn` is vestigial on the scene config.
   - What's unclear: Whether removing `env_to_state_fn` from `GymScene.rendering()` is in scope or if we just stop passing it in example configs.
   - Recommendation: Just remove it from example configs (don't pass it). Removing it from the GymScene class itself is a framework change beyond this phase's scope. The attribute can remain on GymScene as `None`.

## Sources

### Primary (HIGH confidence)
- `mug/rendering/surface.py` — Surface API with all draw methods, `commit()`, `reset()`
- `mug/rendering/types.py` — DrawCommand and RenderPacket dataclasses
- `mug/examples/slime_volleyball/slimevb_env.py` — Current Slime VB env with ObjectContext render
- `mug/examples/slime_volleyball/slime_volleyball_utils.py` — Standalone render functions + asset specs
- `mug/examples/cogrid/overcooked_utils.py` — Overcooked render functions + asset specs
- `mug/examples/cogrid/environments/cramped_room_environment_initialization.py` — Overcooked env with duplicated render logic
- `mug/server/game_manager.py:1541-1570` — Server-auth render path (calls `env.render()` only)
- `mug/server/static/js/pyodide_remote_game.js` — Pyodide render path (handles both legacy and RenderPacket formats)
- `mug/server/static/js/phaser_gym_graphics.js` — JS renderer (handles `fill_below`, `game_state_objects`, `removed`)
- `mug/configurations/object_contexts.py` — Deprecated stubs that raise NotImplementedError
- `mug/scenes/gym_scene.py` — GymScene config class with `env_to_state_fn` parameter

### Secondary (MEDIUM confidence)
- `.planning/phases/99-example-migration/99-CONTEXT.md` — User decisions constraining implementation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already exist and are tested in prior phases
- Architecture: HIGH — direct code inspection of all files involved; mapping is mechanical
- Pitfalls: HIGH — identified from actual code patterns (fill_below gap, 12 duplicate files, missing Surface methods)

**Research date:** 2026-02-20
**Valid until:** 2026-03-20 (stable — codebase-internal migration)

## Files Requiring Changes

### Must Modify (Rendering Migration)
1. `mug/rendering/surface.py` — Add `register_atlas()`, `register_image()`, `get_asset_specs()`
2. `mug/examples/slime_volleyball/slimevb_env.py` — Rewrite render to use Surface
3. `mug/examples/slime_volleyball/slime_volleyball_utils.py` — Delete render functions, keep hud/header helpers
4. `mug/examples/slime_volleyball/slimvb_human_ai.py` — Remove `env_to_state_fn` from config
5. `mug/examples/slime_volleyball/slimevb_human_human.py` — Remove `env_to_state_fn` from config
6. `mug/examples/cogrid/overcooked_utils.py` — Delete render + asset functions, keep hud/header helpers
7. `mug/examples/cogrid/environments/cramped_room_environment_initialization.py` — Rewrite render
8. `mug/examples/cogrid/environments/cramped_room_environment_initialization_hh.py` — Rewrite render
9. `mug/examples/cogrid/environments/cramped_room_controllable_environment_initialization.py` — Rewrite render
10. `mug/examples/cogrid/environments/cramped_room_controllable_tutorial_environment_initialization.py` — Rewrite render
11. `mug/examples/cogrid/environments/tutorial_cramped_room_environment_initialization.py` — Rewrite render (has local Sprite/Text classes)
12. `mug/examples/cogrid/environments/counter_circuit_environment_initialization.py` — Rewrite render
13. `mug/examples/cogrid/environments/counter_circuit_controllable_environment_initialization.py` — Rewrite render
14. `mug/examples/cogrid/environments/forced_coordination_environment_initialization.py` — Rewrite render
15. `mug/examples/cogrid/environments/forced_coordination_controllable_environment_initialization.py` — Rewrite render
16. `mug/examples/cogrid/environments/asymmetric_advantages_environment_initialization.py` — Rewrite render
17. `mug/examples/cogrid/environments/asymmetric_advantages_controllable_environment_initialization.py` — Rewrite render
18. `mug/examples/cogrid/environments/coordination_ring_environment_initialization.py` — Rewrite render
19. `mug/examples/cogrid/environments/coordination_ring_controllable_environment_initialization.py` — Rewrite render

### Must Modify (Config Cleanup)
20. `mug/examples/cogrid/scenes/scenes.py` — Remove `env_to_state_fn=` and `assets_to_preload=` from all scene `.rendering()` / `.assets()` calls
21. `mug/examples/cogrid/scenes/controllable_scenes.py` — Same cleanup
22. `mug/examples/cogrid/overcooked_server_auth.py` — Remove `env_to_state_fn=` and `assets_to_preload=`
23. `mug/examples/cogrid/overcooked_human_ai.py` — Remove if it has `env_to_state_fn=`
24. `mug/examples/cogrid/overcooked_human_human_multiplayer.py` — Remove if it has `env_to_state_fn=`
25. `tests/fixtures/overcooked_server_auth_test.py` — Remove `env_to_state_fn=` and `assets_to_preload=`
