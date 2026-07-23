# MUG repository structure

| Field | Value |
| --- | --- |
| Status | Accepted (2026-07-20) |
| Scope | Package layout, family shape, and the layer graph |
| Style | This document uses ASD-STE100 Simplified Technical English |

One repository holds two language roots: `mug/` (Python, the runtime) and `ts/`
(TypeScript, the browser kernel twin). We build a clean `mug/` package. Git
history keeps the legacy runtime. We name a package after its domain, not after
its API number. The map in the last section links the two.

## Top-level layout

```text
mug/                          # Python package (the runtime)
  kernel/                     # L0 — depends on nothing in mug
    ids.py                    #   typed IDs, kind registry, UUIDv7 prefix rules
    refs.py                   #   Digest, SchemaRef, ArtifactRef, SecretRef, ResourceRef, ...
    canonical.py              #   RFC 8785 canonicalization and digest
    schema.py                 #   load and resolve the frozen schema corpus (offline)
    typed_object.py           #   TypedObject envelope (SchemaRef + validated data)
    command.py                #   WireCommandEnvelope, CommandReceipt, receipt classes
    errors.py                 #   DomainError taxonomy, categories, retry directives
    clock.py                  #   Duration, StreamPosition, EventCursor, LeaseRef, ...
    privacy.py                #   privacy lattice, DataHandlingRef, join rule
  storage/                    # L1 — API-11 (repositories, unit of work, outbox, artifacts)
  events/                     # L1 — API-10 (canonical ledger, capture, streams, cursors)
  jobs/                       # L1 — API-22 (durable jobs, fenced workers)
  authoring/                  # L2 — API-01 (compiler, git provenance, publication, catalog)
  platform/                   # L2 — API-02 (deploy/stop, deployment revisions, secrets)
  identity/                   # L3 — API-03 (enrollment, launch ticket, return link)
  visits/                     # L3 — API-04 (visit plan, treatment, advancement, recovery)
  casting/                    # L4 — API-05 (seats, actors, controllers)
  interactions/               # L4 — API-06 (channels, membership, leases, matchmaking)
  client/                     # L4 — API-09 (participant protocol, realtime, uploads)
  game/                       # L5 — API-07 (server/browser/P2P game, rendering, episodes)
  conversation/               # L5 — API-08 (turns, ordering, context, delivery)
  scheduling/                 # L6 — API-12 (controller scheduler and executor)
  providers/                  # L6 — API-13 (model provider adapters, usage)
  tools/                      # L6 — API-14 (tools, approval, egress, mailbox)
  memory/                     # L6 — API-15 (agent memory scopes, content-addressed store)
  replay/                     # L7 — API-16 (capture, bundles, safe player)
  content/                    # L7 — API-17 (forms, presentation, accessibility)
  preferences/                # L7 — API-18 (candidates, assignment, response, quality)
  export/                     # L8 — API-19 (JSONL dataset query, export, lineage)
  server/                     # ASGI edge (FastAPI app, routes, websocket loop, DI)
  cli/                        # mug commands (publish, deploy, simulate, replay)

ts/                           # TypeScript workspace (browser)
  kernel/                     # kernel twin: canonicalization, wire types, ids
  client/                     # participant client (later phases)

tests/
  architecture/               # the frozen contract corpus and conformance (exists)
  conformance/                # cross-language kernel vectors (Python == TypeScript)
  unit/                       # per-module pure tests
  integration/                # per-family, contract fixtures as acceptance tests
  e2e/                        # full-slice browser tests (Playwright)

docs/architecture/implementation/   # this standard and this structure
```

> The legacy runtime (`mug/server/`, `mug/scenes/`, `mug/configurations/`,
> `mug/rendering/`) still sits in the working tree. The rewrite does not port it.
> A later step removes it deliberately; git history keeps it.

## Inside a family package (uniform shape)

Every family package uses the same internal shape. The shape makes any family
readable once you learn one.

```text
mug/<family>/
  __init__.py        # the public surface of the family (re-exports only)
  types.py           # frozen Pydantic models for the family's typed objects
  service.py         # the application command and query functions (async at the edge)
  <domain>.py        # pure domain logic modules, split by responsibility
  ports.py           # Protocols this family needs from a lower layer (if any)
  errors.py          # family-specific error detail shapes (codes stay in kernel)
```

- `service.py` holds the command handlers. A handler validates the input, builds
  the context, calls a pure domain function, and commits through a repository
  port.
- Pure domain logic never sits in `service.py`. It sits in a `<domain>.py` module
  and returns data.

## The layer graph

| Layer | Package(s) | API family | Allowed inward dependencies |
| --- | --- | --- | --- |
| L0 | `kernel` | shared kernel | none |
| L1 | `storage` `events` `jobs` | API-11, API-10, API-22 | kernel |
| L2 | `authoring` `platform` | API-01, API-02 | kernel, L1 |
| L3 | `identity` `visits` | API-03, API-04 | kernel, L1, L2 |
| L4 | `casting` `interactions` `client` | API-05, API-06, API-09 | kernel, L1–L3 |
| L5 | `game` `conversation` | API-07, API-08 | kernel, L1–L4 |
| L6 | `scheduling` `providers` `tools` `memory` | API-12, API-13, API-14, API-15 | kernel, L1–L5 |
| L7 | `replay` `content` `preferences` | API-16, API-17, API-18 | kernel, L1–L6 |
| L8 | `export` | API-19 | kernel, L1–L7 |

The `server` and `cli` packages sit above all layers. They wire the families to
the transport edge and the command line. No family imports `server` or `cli`.

## The kernel twin (Python and TypeScript)

- The Python `kernel` and the TypeScript `ts/kernel` implement the same wire
  behavior: canonicalization, digest, ID encoding, and the typed-object envelope.
- The two share one set of conformance vectors under `tests/conformance`. A CI
  job runs the vectors in both languages and asserts byte-identical output.
- The canonicalization work (G5) already proved this pattern. We extend it to
  IDs and the typed-object envelope.
- The TypeScript side stays small. It holds only what the browser needs.

## Build increments

Build the smallest end-to-end vertical that proves the shape, then scale it.

1. **Increment 1 — kernel and evidence foundation.** `kernel`, then `storage`,
   `events`, `jobs`. This gives typed IDs, refs, canonicalization,
   command/receipt, errors, clocks, privacy, a local backend with a unit of work
   and an outbox, the canonical event ledger, and the durable job runtime. It
   touches every hard cross-cutting rule once (idempotency, receipts, fencing,
   privacy) on the layer that everything else depends on.
2. **Increment 2 — authoring and deploy.** `authoring`, `platform`.
3. **Increment 3 — identity and visits.** `identity`, `visits`.
4. **Increment 4 — interaction fabric and game.** `casting`, `interactions`,
   `client`, then `game`. This completes the Phase-1 parity slice.

Later increments add conversation, agents, providers, tools, memory, replay,
content, preferences, and export.

### Definition of done for a work item

A work item is done when:

1. Its package matches the family shape and the coding principles.
2. Its contract fixtures pass as acceptance tests.
3. Its failure-matrix rows have fault-injection tests.
4. The type checker and the import linter pass.
5. The family's contract bytes freeze against the running code. This is the
   deferred per-family G0–G8 from the Phase-0 close. We freeze each family when
   its code proves the shape, not before.
