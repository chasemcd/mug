# Requirements: Multi-User Gymnasium (MUG)

**Defined:** 2026-02-21
**Core Value:** Researchers can deploy interactive simulation experiments to the browser with minimal friction, supporting both single-player and multiplayer configurations.

## v1.4 Requirements

Requirements for Documentation Update. Each maps to one roadmap phase.

### Rendering Docs

- [ ] **RDOC-01**: `rendering_system.rst` rewritten to describe the Surface-based rendering pipeline with correct code examples, tables for comparisons, no emojis
- [ ] **RDOC-02**: `object_contexts.rst` replaced with a Surface API reference page documenting all draw methods, parameters, and usage patterns
- [ ] **RDOC-03**: `quick_start.rst` Mountain Car tutorial updated to use Surface API instead of ObjectContext imports

### Mode Docs

- [ ] **MDOC-01**: `server_mode.rst` updated with correct Surface rendering examples, no emojis, tables for comparisons
- [ ] **MDOC-02**: `pyodide_mode.rst` updated with correct Surface rendering examples, `render_mode="mug"`, no emojis, tables for comparisons

### Config Docs

- [ ] **CDOC-01**: `scenes.rst` updated to remove stale `env_to_state_fn` and `location_representation` references in `.rendering()` config

## Future Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Additional Docs

- **RDOC-04**: Example RST pages (mountain_car.rst, slime_volleyball.rst, overcooked_*.rst) updated for Surface API
- **RDOC-05**: Root README.md expanded with Surface API overview
- **RDOC-06**: mug/examples/cogrid/README.md updated for Surface API patterns
- **MIGR-03**: Mountain Car example migrated from ObjectContext to Surface API (code change, not docs)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Multiplayer/P2P docs rewrite | Already current (Jan-Feb 2026) |
| Advanced technical docs (multiplayer_pyodide_implementation.md, etc.) | Already current |
| Sphinx autodoc/API auto-generation | Separate tooling concern |
| Code changes to library | Documentation only milestone |
| Example README files | Separate from Sphinx core docs |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| RDOC-01 | Phase 100 | Pending |
| RDOC-02 | Phase 101 | Pending |
| RDOC-03 | Phase 102 | Pending |
| MDOC-01 | Phase 103 | Pending |
| MDOC-02 | Phase 104 | Pending |
| CDOC-01 | Phase 105 | Pending |

**Coverage:**
- v1.4 requirements: 6 total
- Mapped to phases: 6
- Unmapped: 0

---
*Requirements defined: 2026-02-21*
*Last updated: 2026-02-21 after roadmap creation*
