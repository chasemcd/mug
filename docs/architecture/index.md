# MUG Platform Architecture

| Field | Value |
| --- | --- |
| Status | Proposed |
| Purpose | Working architecture RFC for the next major platform version |
| Scope | The next major MUG platform architecture |
| Last updated | 2026-07-20 |
| Compatibility policy | Functional parity; no backward compatibility |

This section defines the target architecture for the next major version of
MUG. It is intentionally separate from the current user documentation. The
current documentation describes the software that exists today; these
architecture documents describe the platform that will replace it.

!!! important "Governing compatibility rule"

    The redesign must preserve MUG's platform capabilities, but it has no
    obligation to preserve old Python APIs, experiment code, configuration
    objects, browser protocols, storage layouts, data formats, or deployment
    procedures. Capability parity is an acceptance criterion. Code
    compatibility is not.

This freedom applies to the transition into the new architecture. It does not
mean that published study versions or future public APIs may change silently.
Published protocols remain immutable, and new wire and data contracts will be
explicitly versioned.

## Document map

- [North-star architecture](north-star.md) defines the intended product,
  capability set, conceptual model, system boundaries, and invariants.
- [Functional-parity contract](functional-parity.md) records what the current
  platform can do and what the replacement must still support.
- [Quality attributes](quality-attributes.md) make integrity, latency, recovery,
  security, accessibility, and scale expectations testable.
- [Roadmap](roadmap.md) gives the delivery phases and dependency gates.
- [Phase 0: architecture and contracts](phase-0/index.md) turns the planning
  phase into concrete work packages and review gates.
- [API catalog](phase-0/api-catalog.md) inventories every planned API family.
- [API design standard](phase-0/api-design-standard.md) defines the questions
  every API proposal must answer.
- [API review tracker](phase-0/api-review-tracker.md) records the working order,
  dependencies, scenario coverage, and acceptance checklist for all API
  families (two retired: API-20 removed under ADR-0015, API-21 retracted for
  v0).
- [Public Python authoring API](phase-0/python-authoring-api.md) specifies the
  author-facing Python surface over the contract families.
- [Shared-kernel contract](phase-0/shared-kernel/index.md) is the first concrete
  Phase 0 API review: identifiers, references, schemas, commands, receipts,
  errors, clocks, fencing, privacy, secrets, and conformance fixtures.
- [Acceptance scenarios](phase-0/acceptance-scenarios.md) provide end-to-end
  contract tests for the architecture.
- [Failure and recovery matrix](phase-0/failure-matrix.md) defines the default
  behavior for retries, crashes, stale work, partial capture, and disagreement.
- [Runtime parity audit](runtime-parity/index.md) maps the current `mug/`
  runtime's data flow (P2P, server-authoritative, Pyodide, capture,
  matchmaking, flow, policies) onto the Phase 0 contracts and records the
  cross-cutting parity decisions RP-1..RP-10.
- [Glossary](glossary.md) defines the domain language used by all proposals.
- [Architecture decisions](decisions/index.md) records accepted and proposed
  decisions.

## Authority and document status

When target-architecture documents disagree, use this order:

1. Accepted architecture decision records (ADRs)
2. Accepted API specifications
3. The north-star architecture
4. The Phase 0 plan and API catalog
5. Existing implementation documentation

Documents use these statuses:

- **Draft**: incomplete and not ready for architectural review.
- **Proposed**: concrete enough for review, but not yet binding.
- **Accepted**: a binding design decision for implementation.
- **Superseded**: replaced by a named newer document or ADR.
- **Rejected**: considered and intentionally not selected.

The architecture is not complete merely because documents exist. Phase 0 is
complete only when its decision, API, schema, security, and scenario gates all
pass.
