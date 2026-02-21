# Roadmap: MUG v1.4 Documentation Update

## Overview

Update all Sphinx documentation pages to reflect the Surface rendering API shipped in v1.3, remove stale ObjectContext references, and establish consistent tone (no emojis, tables for key info). Each phase corresponds to one RST documentation page. Rendering system docs come first because mode docs and the quick start tutorial reference rendering concepts established there.

## Milestones

- v1.0 MVP -- Phases 67-91 (shipped 2026-02-19)
- v1.1 Server-Auth -- Phases 92-95 (shipped 2026-02-20)
- v1.2 Test Suite -- Phase 96 (shipped 2026-02-20)
- v1.3 Rendering API -- Phases 97-99 (shipped 2026-02-21)
- v1.4 Documentation Update -- Phases 100-105 (in progress)

## Phases

**Phase Numbering:**
- Integer phases (100-105): Planned v1.4 milestone work
- Decimal phases (100.1, 100.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 100: Rendering System Docs** - Rewrite rendering_system.rst for the Surface-based rendering pipeline
- [ ] **Phase 101: Surface API Reference** - Replace object_contexts.rst with Surface API reference documenting all draw methods
- [ ] **Phase 102: Quick Start Tutorial** - Update quick_start.rst Mountain Car tutorial for Surface API
- [ ] **Phase 103: Server Mode Docs** - Update server_mode.rst with correct rendering examples and tone
- [ ] **Phase 104: Pyodide Mode Docs** - Update pyodide_mode.rst with correct rendering examples and tone
- [ ] **Phase 105: Scenes Config Docs** - Update scenes.rst to remove stale rendering config references

## Phase Details

### Phase 100: Rendering System Docs
**Goal**: A researcher reading the rendering system page understands the full Surface-based rendering pipeline -- from Python draw calls through wire format to browser display
**Depends on**: Nothing (first phase in v1.4; establishes rendering concepts referenced by all other pages)
**Requirements**: RDOC-01
**Success Criteria** (what must be TRUE):
  1. The page explains the Surface draw-call workflow (create Surface, call draw methods, call commit(), return RenderPacket) with a runnable code example that uses `render_mode="mug"`
  2. The page documents the rendering pipeline stages (Python draw calls -> RenderPacket delta -> wire transmission -> Phaser JS rendering) in a clear progression, using a table or diagram
  3. The page covers key concepts: persistent vs temporary objects, state delta compression, the `id=` parameter for tweened movement, and pixel vs relative coordinates
  4. The page contains no references to ObjectContext, Circle(), Line(), Polygon() classes, or `env_to_state_fn` patterns from the old API
  5. The page uses no emojis and uses tables for key comparisons (e.g., persistent vs temporary objects, pixel vs relative coordinates)
**Plans**: TBD

### Phase 101: Surface API Reference
**Goal**: A researcher looking up Surface API details finds a complete reference of all draw methods, their parameters, return types, and usage patterns
**Depends on**: Phase 100 (rendering concepts established)
**Requirements**: RDOC-02
**Success Criteria** (what must be TRUE):
  1. The page documents every Surface draw method (rect, circle, line, polygon, text, image, arc, ellipse) with parameter signatures, types, and default values
  2. The page documents Surface lifecycle methods (commit, reset) and constructor parameters (width, height, coordinate mode)
  3. The page includes usage examples showing color input formats (RGB tuple, hex string, named color), the `id=` parameter, and `persistent=True`
  4. The page title and filename reflect "Surface API Reference" (not "Object Contexts") and the old object_contexts.rst content is fully replaced
  5. The page uses tables to present method parameters and their descriptions
**Plans**: TBD

### Phase 102: Quick Start Tutorial
**Goal**: A new researcher can follow the quick start tutorial end-to-end and run a Mountain Car example using the Surface API
**Depends on**: Phase 101 (API reference available for cross-linking)
**Requirements**: RDOC-03
**Success Criteria** (what must be TRUE):
  1. The tutorial imports from `mug.rendering` (not `mug.configurations.object_contexts`) and all code examples use Surface draw calls
  2. The tutorial uses `render_mode="mug"` (not `"interactive-gym"` or `"interactive_gym"`) in all environment configuration
  3. The tutorial demonstrates a complete render function using Surface (create surface, draw shapes, commit, return packet) that a researcher can adapt for their own environment
  4. The page contains no emojis, no references to ObjectContext classes, and uses tables where appropriate
**Plans**: TBD

### Phase 103: Server Mode Docs
**Goal**: A researcher reading the server mode page understands how to run environments in server-authoritative mode with correct Surface rendering examples
**Depends on**: Phase 100 (rendering pipeline concepts)
**Requirements**: MDOC-01
**Success Criteria** (what must be TRUE):
  1. All rendering code examples use the Surface API (not ObjectContext) and show the correct `env_to_state_fn` pattern that creates a Surface, draws, commits, and returns a RenderPacket
  2. The page explains the server-authoritative rendering flow (server runs env, calls render function, broadcasts RenderPacket to thin clients via SocketIO) with correct terminology
  3. The page uses `render_mode="mug"` in all configuration examples
  4. The page uses no emojis and uses tables for key comparisons (e.g., server-auth vs client-side differences, configuration options)
**Plans**: TBD

### Phase 104: Pyodide Mode Docs
**Goal**: A researcher reading the Pyodide mode page understands how to run environments client-side with correct Surface rendering examples
**Depends on**: Phase 100 (rendering pipeline concepts)
**Requirements**: MDOC-02
**Success Criteria** (what must be TRUE):
  1. All rendering code examples use the Surface API (not ObjectContext) and show the correct pattern for client-side rendering via Pyodide
  2. The page uses `render_mode="mug"` in all configuration examples
  3. The page explains how Pyodide mode handles rendering differently from server mode (environment runs in browser via Pyodide, rendering happens client-side) using a table or clear comparison
  4. The page uses no emojis and uses tables for key comparisons
**Plans**: TBD

### Phase 105: Scenes Config Docs
**Goal**: A researcher reading the scenes configuration page sees only current, valid configuration options with no stale rendering references
**Depends on**: Phase 100 (rendering concepts for cross-references)
**Requirements**: CDOC-01
**Success Criteria** (what must be TRUE):
  1. The `.rendering()` configuration section contains no references to `env_to_state_fn`, `location_representation`, or other removed ObjectContext-era configuration keys
  2. The page shows the current valid rendering configuration options for scene setup with correct examples
  3. The page uses no emojis and uses tables for configuration options and their descriptions
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 100 -> 101 -> 102 -> 103 -> 104 -> 105

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 100. Rendering System Docs | 0/0 | Not started | - |
| 101. Surface API Reference | 0/0 | Not started | - |
| 102. Quick Start Tutorial | 0/0 | Not started | - |
| 103. Server Mode Docs | 0/0 | Not started | - |
| 104. Pyodide Mode Docs | 0/0 | Not started | - |
| 105. Scenes Config Docs | 0/0 | Not started | - |
