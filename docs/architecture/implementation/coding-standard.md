# MUG coding standard

| Field | Value |
| --- | --- |
| Status | Accepted (2026-07-20) |
| Scope | All Python code in `mug/` and TypeScript code in `ts/` |
| Style | This document uses ASD-STE100 Simplified Technical English |

This standard ranks **simplicity, readability, and minimal abstraction** above
cleverness, reuse, and speculative flexibility. The legacy runtime shows one
failure mode we reject: `app.py` grew to 107 KB, `game_manager.py` to 76 KB.
These are god-modules. Its opposite is also a failure: a small feature spread
across ten tiny files and a zoo of one-line helpers. Both hide the code.

## P0 — Minimize the amount of code and the surface to understand

- Write the least code that meets the contract. Fewer files, fewer classes,
  fewer functions, fewer public names.
- Prefer one cohesive module over several tiny ones. The line caps in P5 are
  ceilings, not targets. Split only when a module holds two clear
  responsibilities.
- Do not add a wrapper function that only forwards to a constructor. Let callers
  build the object.
- Keep the public surface small. A package's `__all__` exports what a consumer
  uses, not every internal helper.
- A family is usually a handful of files: the typed objects, the logic, and (when
  a real second implementation exists) the seam. Reach for more only when the
  domain is genuinely large.

The companion document [repo-structure.md](repo-structure.md) defines the
package layout and the layer graph that P6 references.

## P1 — Write data and functions first; add a class only for real state

- Represent contract objects as frozen Pydantic v2 models. They hold data, not
  behavior. Do not add a method that carries domain logic to a model.
- Write behavior as a module-level function. The function takes data and returns
  data.
- Add a stateful class only when an object owns mutable state and identity. A
  live interaction, a lease holder, or a unit of work is such an object. Do not
  model these with Pydantic; they are runtime state, not wire data.
- Do not wrap a single function in a class. Do not build a `Manager` or a
  `Service` class that only groups functions. A module already groups functions.

## P2 — Abstract only at a proven seam; never speculatively

- A `typing.Protocol` belongs only at a true external seam: storage, object
  store, model provider, tool transport, clock, and the wire. These are the seams
  the API standard names, but the Protocol arrives with the second
  implementation, not before. One backend needs no interface; write the concrete
  class and extract the Protocol when a real second backend lands.
- Do not define an interface for internal code. Call the function directly.
- Apply the rule of three. Do not extract a shared abstraction until three real
  call sites need it. Two call sites duplicate; the third justifies the shape.
- A small amount of duplication is cheaper than the wrong abstraction.

## P3 — Keep a pure core and an imperative shell

- Domain logic is pure and synchronous. It compiles, validates, randomizes,
  orders, classifies, and fingerprints. It takes data and returns data or a
  typed error.
- I/O lives at the edges. The server, the repositories, and the adapters are
  `async`. The pure core never calls the network, the database, or the clock.
- This rule makes the core easy to test with plain values and no mocks.

## P4 — Make control flow explicit

- Do not use a metaclass, `__getattr__`/`__setattr__` magic, dynamic attribute
  injection, or an import-time side effect in domain or service code.
- Do not hide control flow in a decorator. A decorator may add a cross-cutting
  concern such as tracing or a retry at a seam. It must not change what a
  function returns.
- Prefer an explicit `if` to a registry lookup when the set of cases is small
  and closed. Closed vocabularies stay closed (ADR-0015).
- Pydantic's own metaclass and validators are an accepted dependency at the
  data-definition layer. This rule binds our own code, not the library.

## P5 — Keep modules and functions small

- A module has one clear responsibility. Soft cap: **400 lines**. Above the cap,
  split by responsibility, not by line count.
- A function does one thing. Soft cap: **40 lines**. A function above the cap
  usually hides two functions.
- A public function takes few arguments. Above four arguments, pass a small
  frozen object. Use a Pydantic model for a wire or contract object. A plain
  frozen dataclass is fine for an internal parameter bundle.
- The caps are review guidance. CI warns; it does not fail the build. A hard cap
  invites a bad split.

## P6 — Let dependencies point inward, along the layer graph

- The kernel depends on nothing in `mug`. Each family depends only on the kernel
  and on the families the layer graph allows.
- A family never imports a sibling that its contract does not list as a
  dependency. An import linter enforces this rule in CI.
- A lower layer never imports a higher layer.

## P7 — Errors are typed values from the shared taxonomy

- Return or raise only the kernel `DomainError` taxonomy across a boundary.
- Never leak a provider stack trace, a credential, prompt text, or protected
  participant data into an error.
- Fail closed. An unknown state, an expired lease, or a stale generation rejects
  the effect.

## P8 — Name code after the contract vocabulary

- Use the glossary terms for types, functions, and files: enrollment, visit,
  seat, actor, controller, interaction, lease, receipt. One term, one meaning.
- Do not invent a synonym for a contract term. Consistent names make the code
  readable next to the contracts.

## P9 — Type everything; run the checker strict

- Every function has full type hints. Put `from __future__ import annotations`
  at the top of every module.
- The type checker is **pyright** in strict mode. It runs in CI. New code adds
  no `type: ignore` without a reason comment.

## P10 — Comments and docstrings state intent, in Simplified Technical English

- Write a docstring for every public function, class, and module. State what it
  does and the contract it serves. Keep sentences short and active.
- Do not comment on obvious code. Comment on a non-obvious decision or a
  contract rule that the code enforces.

## Contract-binding rules

These rules make the code match the API design standard and the shared kernel.

### Typed objects

- Write one frozen Pydantic v2 model per contract typed object. Set
  `model_config = ConfigDict(frozen=True, extra="forbid")`.
- The model field names match the schema property names exactly.
- The frozen JSON-Schema corpus stays the authority. A conformance test binds
  each model to its schema: every fixture the schema accepts must parse into the
  model, and the model must reject what the schema rejects. Drift fails the
  build.

### The wire boundary

- Every inbound payload parses into its Pydantic model at the edge.
- Every outbound object serializes with `model_dump(mode="json")`.
- A digest never uses the Pydantic serializer. Digested content passes through
  the kernel canonicalizer (`kernel/canonical.py`, RFC 8785) on the dumped JSON.
  No other canonicalizer exists in the code.

### Commands and receipts

- A command handler returns a typed receipt or a `DomainError`. It never returns
  a bare success.
- The gateway builds the trusted `CommandContext` from verified state. A handler
  never trusts a client-supplied scope.
- A commit receipt commits the aggregate, the idempotency record, the canonical
  event, and the outbox in one unit of work.

### Idempotency and concurrency

- Each command declares one retry policy from the kernel set.
- The unit of work checks the expected revision. A scientific decision, such as
  randomization or preference assignment, never silently retries on a conflict.

### Async rules

- The server, the repositories, the workers, and the adapters are `async`.
- No code performs provider, tool, database, or object-store I/O while it holds
  an environment mutation lock.
- A blocking call, such as a CPU-bound compile or a synchronous library, runs in
  a thread through `asyncio.to_thread`. The core stays pure and synchronous; the
  shell offloads it.

### Privacy and secrets

- Every persisted field carries or inherits a `DataHandlingRef`. The classifier
  lives in `kernel/privacy.py`.
- Secret material never enters a model, an event, an artifact, a log, or an
  export. Code references a secret only by `SecretRef`.

## Tooling

| Concern | Tool | Note |
| --- | --- | --- |
| Package and virtual environment | uv | Already in use. |
| Lint, format, and import sort | ruff | Replaces isort, pyupgrade, and pycln. |
| Type check | pyright (strict) | Native Pydantic v2 inference, no plugin. |
| Import boundaries | import-linter | Enforces the layer graph in CI. |
| Tests | pytest and pytest-asyncio | asyncio mode. |
| TypeScript toolchain | tsc and a formatter | Kernel twin only for now. |
