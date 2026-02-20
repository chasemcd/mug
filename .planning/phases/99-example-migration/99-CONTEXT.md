# Phase 99: Example Migration - Context

**Gathered:** 2026-02-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Migrate Slime Volleyball and Overcooked examples from the deprecated ObjectContext rendering API to the new Surface draw-call API. Both examples must render correctly through the server-authoritative path (Flask/SocketIO) without visual regressions. This phase does NOT add new features to the Surface API or renderer — it uses what Phases 97-98 built.

</domain>

<decisions>
## Implementation Decisions

### Render function pattern
- Rendering logic lives in `env.render()` on the environment class, not standalone functions
- Env owns its Surface: `self.surface = Surface()` initialized in `__init__`
- `env.render()` draws to `self.surface`, calls `self.surface.render()`, and returns the RenderPacket dict
- Framework calls `env.render()` directly — no wrapper functions needed
- Config references `env.render()` directly instead of old `env_to_state_fn` parameter

### Asset preloading
- Surface has asset registration methods directly: `surface.register_atlas(key, image_path, json_path)` and `surface.register_image(key, path)`
- Assets registered in env `__init__` via Surface methods
- `surface.get_asset_specs()` returns registered assets in the format the config system expects — drop-in replacement for old AtlasSpec lists
- Surface validates atlas keys at draw time — `surface.sprite()` with an unregistered key raises an error early in Python

### Persistent object strategy
- Draw everything every frame with `persistent=True` for static objects — Surface handles delta tracking automatically (no explicit first-frame check needed)
- Env's `reset()` calls `self.surface.reset()` to clear persistent tracking at episode boundaries
- Slime Volleyball stays with relative (0-1) coordinates; Overcooked stays with pixel coordinates — each demonstrates a different Surface coordinate mode
- Slime Volleyball agents stay as geometric primitives (polygon body + circle eyes), not sprites

### Migration completeness
- Delete all old standalone render functions (`slime_volleyball_env_to_rendering`, `overcooked_env_to_render_fn`, and all helpers) entirely — git history has the old code
- Delete old `preload_assets_spec` functions — asset registration now lives on Surface
- Remove `env_to_state_fn` and `preload_assets_spec` from config objects — framework uses `env.render()` and `surface.get_asset_specs()` directly
- Delete `_utils.py` files if empty after removing render functions; move any remaining non-rendering helpers into the env class
- Remove all ObjectContext imports from example files

### Claude's Discretion
- Whether to separate static vs dynamic drawing into distinct code blocks or interleave freely (pick what makes each example clearest)
- Internal code organization within env.render() (helper methods on the env class if needed for clarity)

</decisions>

<specifics>
## Specific Ideas

- Slime Volleyball currently draws: fence (Line, permanent), fence stub (Circle, permanent), ground (Line, permanent, fill_below), 2 agents (Polygon body + 2 Circle eyes each), ball (Circle)
- Overcooked currently draws: counter tiles (Sprite from terrain atlas, permanent), delivery areas (Sprite, permanent), static tools (Sprite, permanent), agent sprites (Sprite from chefs atlas with directional frames), hats (Sprite), interactive objects (Sprite from objects atlas), cooking timer (Text)
- Overcooked uses 3 atlas sheets: terrain, chefs, objects
- Slime Volleyball has ImgSpec assets (slime_red.png, slime_blue.png) but sprite rendering is commented out — geometric primitives are used instead

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 99-example-migration*
*Context gathered: 2026-02-20*
