# Phase 100: Rendering System Docs - Context

**Gathered:** 2026-02-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Rewrite `rendering_system.rst` so a researcher understands the full Surface-based rendering pipeline -- from Python draw calls through wire format to browser display. This page establishes rendering concepts referenced by all subsequent documentation phases. Server-auth vs Pyodide mode-specific details belong in Phases 103/104.

</domain>

<decisions>
## Implementation Decisions

### Page structure & flow
- Open with problem/solution framing: "you need to render your environment -- here's how the system solves that"
- Progress top-down: pipeline overview first (all 4 stages at a glance), then zoom into each stage with details
- Comprehensive reference depth -- this is THE page for understanding the rendering system; don't defer content to other pages
- Cover the shared rendering pipeline only; server-auth and Pyodide path differences belong in Phases 103/104

### Code example depth
- Anchor with a minimal toy example showing the Surface/draw/commit/return pattern with simple shapes (not a full real-world env)
- Inline code snippets with each section -- each concept (persistent objects, id= parameter, etc.) gets its own short snippet right there
- Each key concept (persistent vs temporary, id= for tweening, pixel vs relative coords) gets a dedicated code snippet showing the usage pattern
- Show full imports in the first example; subsequent examples assume imports are already established

### Audience & assumed knowledge
- Primary reader: RL researcher who knows reinforcement learning and Gymnasium but is new to interactive-gym / MUG rendering
- Include a brief Gymnasium refresher paragraph bridging from Gymnasium's render_mode pattern to MUG's approach
- Approachable & explanatory tone -- friendly but not casual, explains the "why" alongside the "what" (like FastAPI or Stripe docs)
- Include design rationale -- explain why Surface-based rendering was chosen, why delta compression matters, etc. to help researchers understand trade-offs

### Diagrams & visual aids
- Use ASCII/text diagrams in RST code blocks for the rendering pipeline stages -- renders everywhere, easy to maintain
- Use RST tables for key concept comparisons (persistent vs temporary objects, pixel vs relative coordinates)
- No admonitions (note/warning/tip boxes) -- keep everything in regular prose
- Include forward cross-references (:ref: links) to planned pages (Surface API Reference, server mode, Pyodide mode) even if those pages don't exist yet

### Claude's Discretion
- Exact ASCII diagram layout for the pipeline
- Section heading names and ordering within the top-down structure
- How much Gymnasium context to include in the refresher paragraph
- Specific wording of design rationale sections

</decisions>

<specifics>
## Specific Ideas

No specific requirements -- open to standard approaches within the decisions above.

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope.

</deferred>

---

*Phase: 100-rendering-system-docs*
*Context gathered: 2026-02-21*
