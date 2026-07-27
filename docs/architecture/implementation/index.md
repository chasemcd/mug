# Implementation

| Field | Value |
| --- | --- |
| Status | Accepted (2026-07-20) |
| Purpose | The coding standard and repository structure for the MUG runtime build |
| Style | These documents use ASD-STE100 Simplified Technical English |

Phase 0 accepted the architecture contracts. This section holds the rules for the
code that implements them.

- [Coding standard](coding-standard.md) — the ten principles (P1–P10) and the
  contract-binding rules. It ranks simplicity, readability, and minimal
  abstraction first.
- [Repository structure](repo-structure.md) — the package layout, the uniform
  family shape, the layer graph, and the build increments.
- [Authenticated browser P2P vertical](authenticated-browser-p2p.md) — the
  authenticated signalling, ICE, full-mesh start barrier, and capture path. It
  also states the pending Pyodide rollback-executor gate.
- [Deployment topology](deployment-topology.md) — what may run in more than one
  process, the three environment variables that makes necessary, and the two
  runtimes that do not replicate yet.

The working document that produced these (open questions, decision history) is
`scratch/impl/IMPLEMENTATION-PLAN.md`.
