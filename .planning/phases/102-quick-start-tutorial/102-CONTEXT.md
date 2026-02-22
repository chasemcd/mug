# Phase 102: Quick Start Tutorial - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Rewrite the quick start tutorial (`docs/content/quick_start.rst`) so a new researcher can follow it end-to-end using the Surface API. All code examples migrate from deprecated ObjectContext classes (`Circle`, `Line`, `Polygon` + `.as_dict()`) to Surface draw calls (`surface.circle()`, `surface.line()`, `surface.commit()`). The Mountain Car example stays as the tutorial subject.

</domain>

<decisions>
## Implementation Decisions

### Render function design
- Show the full Surface lifecycle explicitly: create Surface, draw calls, commit — as distinct commented steps
- Surface is created once at class level in `__init__`, not inside `render()` each call
- Use a mix of persistent and transient objects: ground and flag are `persistent=True` (static between frames), car is transient (moves each frame). This naturally demonstrates both patterns
- `return surface.commit()` with a brief inline comment — no prose explanation of what commit returns. API reference (Phase 101) covers details

### Coordinate system
- Use pixel coordinates (e.g., `x=300, y=200` on a 600x400 canvas), not relative 0-1
- Extract a small helper function (e.g., `_to_pixel(pos)`) to map environment state to pixel space. Keeps render() body clean
- Include a brief one-sentence mention that `relative=True` exists as an alternative, with a link to the API reference
- Canvas dimensions stay at 600x400

### Tutorial scope/pacing
- Trim the page: keep core Steps (1-3) + Troubleshooting only
- Drop: "What You'll Build" intro list, "Quick Customizations", "Run Built-in Examples", standalone "Next Steps" section. A brief closing sentence after Step 3 can point to further reading
- Keep the "Key Points" bullet lists after each code block — update them for the new API
- Step 2 (experiment script) is abbreviated since it's mostly unchanged from the old tutorial. Focus on what's different

### Code example style
- Step 1 (environment file): show key parts only — imports + class with render() method. Skip module docstring and step() override if unchanged from before
- Light inline comments — brief notes only where non-obvious (e.g., `# persistent: ground doesn't change between frames`). No numbered step comments
- Import `from mug.rendering import Surface` plus any useful helpers (check what the Mountain Car example actually needs from `mug.rendering`)
- Step 2 abbreviation approach: Claude's discretion on whether to use inline `# ... (scene setup unchanged)` or a two-block approach — pick what reads best in RST

### Claude's Discretion
- Exact abbreviation format for Step 2 (experiment script)
- Whether to keep or rework the "Prerequisites" section (pip install line)
- Troubleshooting section updates — keep relevant items, drop/update stale ones
- How to phrase the brief closing sentence pointing to further reading

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 102-quick-start-tutorial*
*Context gathered: 2026-02-22*
