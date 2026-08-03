# Examples

Each directory is one study a researcher can read, copy, and run. A study is
written with the authoring API (`mug.content`, `mug.authoring`) and started with
`build_app_from_env`. The platform stays generic: the environment, the policies,
and the words a participant reads all live here, beside the study.

These documents use ASD-STE100 Simplified Technical English.

## Run one

```bash
uv run uvicorn examples.mountain_car.native_demo:app
```

Set `MUG_PG_DSN` to run on Postgres instead of the in-memory store. A study that
sets `require_launch=True` prints one launch ticket at start, and each
participant needs a ticket of their own.

## What each example shows

| Example | What it shows | Execution | Environment package |
| --- | --- | --- | --- |
| `mountain_car/native_demo` | One participant, one game, server execution | server | built in (Gymnasium) |
| `mountain_car/browser_demo` | The same study, run in the participant's browser | browser (Pyodide) | built in (Gymnasium) |
| `tandem/study` | Two participants in one grid, no game server | browser peer-to-peer | built in |
| `render_conformance/scene` | Every drawing primitive the renderer supports | server | none |
| `slime_volleyball/human_heuristic` | A person against a policy this example wrote | server | `slime_volleyball` |
| `slime_volleyball/human_ai` | A person against an exported network | server | `slime_volleyball`, `onnxruntime` |
| `slime_volleyball/human_human` | Two people, one fast game, no game server | browser peer-to-peer | `slime_volleyball` |
| `cogrid/overcooked_human_ai` | A trained network and a written partner, then a judgement between them on five axes | server | `cogrid`, `onnxruntime` |
| `cogrid/overcooked_human_ai_browser` | The same task with **nothing on the server**: the kitchen and the trained partner both run in the participant's browser | browser (Pyodide + onnxruntime-web) | `cogrid` |
| `cogrid/overcooked_human_human` | Two people in one kitchen | browser peer-to-peer | `cogrid` |
| `cogrid/overcooked_server_auth` | The same two people, with the server stepping | server | `cogrid` |
| `preference_chat/ollama` | Two candidate replies judged inside a live conversation, on a model on your own machine | chat | none (needs a local Ollama runner) |
| `preference_chat/anthropic` | The same study on a hosted Anthropic model | chat | none (needs `ANTHROPIC_API_KEY`) |
| `footsies/` | **Nothing to run.** The Unity capability is undecided — see its README and ADR-0016 | — | — |

Two pairs of examples are deliberately the same study twice. The `mountain_car`
demos differ only in **where the environment steps**, and the `preference_chat`
studies differ only in **which model the conversation runs on**. In both cases the
study is written once: a backend is a deployment decision, not a study one.

## The environment packages

`mountain_car`, `tandem`, and `render_conformance` need nothing that is not
already installed. The others need a package this repository does not depend on:

| Package | Used by | Install |
| --- | --- | --- |
| `slime_volleyball` | `slime_volleyball/*` | `uv pip install slimevb` |
| `cogrid` | `cogrid/*` | `uv pip install cogrid==0.3.2` |
| `onnxruntime` | the exported-policy partners, where the **server** runs them | `uv pip install onnxruntime` |

A study that runs its exported partner in the participant's browser needs nothing
installed: the browser loads the JavaScript build of the same inference runtime and
scores the model beside the environment. So the same trained network plays on the
server and in the browser, and only the server case needs a package here.

`preference_chat` needs no package: `ollama.py` talks to a local runner over plain
HTTP (`ollama serve`), and `anthropic.py` needs an API key in the environment.
Neither reaches a vendor SDK.

This is deliberate. A study's environment is the study's own choice, and the
platform must not depend on any one of them. An example that needs a package it
does not find says so and stops; it does not fail in the middle of a run.

## The examples and the parity fixtures

`tests/parity/` proves the platform capabilities that
`docs/architecture/functional-parity.md` requires. The two are related but they
are not the same thing, and the difference decides where a test goes:

- **A parity fixture proves a platform capability.** It runs in the gate, so it
  uses only environments this repository owns. A fixture that could not run
  because an optional package was absent would prove nothing on the day it
  mattered.
- **An example proves the authoring surface for one environment.** It is what a
  researcher copies. An example that needs `cogrid` is still an example; its test
  is skipped when the package is absent, and it says which package it wanted.

`tests/parity/README.md` maps each of the ten required fixtures to the module
that proves it.

`tests/unit/test_examples_build.py` holds every example here to composing a
study, naming each activity once, and ending somewhere a participant can stop. An
example added without a row in that file is an example nothing checks.

## An example is not done until somebody has watched it

Composing a study proves that the study composed. Three examples on this page
passed every test while being unplayable: one raised on its first step, and all
three drew an empty canvas for as long as they ran. So two more checks were added,
and an example needs a row in both:

- `tests/unit/test_examples_build.py::test_an_example_game_steps_and_draws` runs
  each game through the real stepping loop and reads the render packets. It is
  fast, so it is in the gate.
- `tests/e2e_native/test_examples_render_browser.py` opens the real client in
  Chromium, plays the real game, and **reads the pixels the browser drew**. It
  asserts that something was painted, that the picture kept moving, that the study's
  own colours reached the canvas, that a key press changes what the participant
  sees, and that two browsers at one table both see the game.

The second one is the only test that can answer "did the participant see
anything". A render packet full of drawing commands and a blank canvas look the
same from the server.

`tests/e2e_native/test_pages_and_hud_browser.py` holds the written pages and the
status line to the same standard: it reads back that a declared picture really
decoded in the browser, that a page is read as written material rather than as its
own source, and that the status band is painted on the canvas the participant
watches. `tests/e2e_native/test_overcooked_browser_partner.py` plays the whole
browser-run human-AI kitchen in Chromium.

`tests/robustness/` holds the platform to the rest of what the legacy suite
proved: twelve people at once, two rounds back to back, a partner who leaves, a
run that outlives the process that recorded it, and what the record says
afterwards.

## The legacy versions

Every example on this page is written on the new stack. The versions that ran on
the legacy scene and configuration modules were replaced rather than kept beside
them, so that `examples/` is one thing a researcher can read rather than two. They
are in git history at commit `7d92d9e` if a behaviour needs to be compared.

What changed is recorded where it matters: `cogrid/README.md` on the layout
choice, `slime_volleyball/README.md` on chorded keys, and `footsies/README.md` on
the capability that has no replacement yet.
