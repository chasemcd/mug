# Contributing to MUG

MUG is a self-hosted platform for experiments among humans, scripted policies,
and LLM agents. It is a clean rewrite of interactive-gym.

## Coding standard and structure

Read these before you write code. They are the authority.

- **[Coding standard](docs/architecture/implementation/coding-standard.md)** —
  the ten principles (P1–P10) and the contract-binding rules. The standard ranks
  simplicity, readability, and minimal abstraction above cleverness and reuse.
- **[Repository structure](docs/architecture/implementation/repo-structure.md)**
  — the package layout, the uniform family shape, and the layer graph.

Two rules to note up front:

1. The frozen JSON-Schema corpus under `docs/architecture/` is the authoritative
   contract. Pydantic models serve it; a conformance test fails the build on
   drift.
2. All docstrings, comments, and prose use ASD-STE100 Simplified Technical
   English.

## Tooling

| Concern | Tool |
| --- | --- |
| Package and environment | uv |
| Lint and format | ruff |
| Type check | pyright (strict) |
| Import boundaries | import-linter |
| Tests | pytest, pytest-asyncio |

Run the architecture and unit tests with `uv run pytest`. The system Python is
too old for the schema validator; always use the uv environment.

Run the type checker with a modern Node. The host Node may be too old for the
pyright wrapper, so use the bundled Node:

```
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright mug/kernel
```
