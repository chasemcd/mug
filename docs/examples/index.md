# Examples

Complete example experiments demonstrating various MUG features. Each example includes full source code and documentation.

All examples are located in the [examples/](https://github.com/chasemcd/interactive-gym/tree/main/examples) directory.

| Example | Players | Mode |
|---------|---------|------|
| [Mountain Car](mountain-car.md) | Human | Client |
| [Slime Volleyball: Human-AI](slime-volleyball-hai.md) | Human vs AI | Client |
| [Slime Volleyball: Human-Human](slime-volleyball-hh.md) | Human-Human | Client (P2P/GGPO) |
| [Overcooked: Human-AI](overcooked-human-ai.md) | Human + AI | Client |
| [Overcooked: Human-Human](overcooked-client-side.md) | Human-Human | Client (P2P/GGPO, with server-auth variant) |
| [Footsies](footsies.md) | Human vs AI | Client (WebGL) |

## Running Examples

Examples must be run from a cloned repository, not a pip install, because they rely on relative paths for assets (sprites, models, ONNX files).

1. Clone the repository and install with server dependencies:

    ```bash
    git clone https://github.com/chasemcd/interactive-gym.git
    cd interactive-gym
    pip install -e .[server]
    ```

2. Install any example-specific dependencies listed in the individual example page.

3. From the repository root, run the example as a module:

    ```bash
    # Mountain Car
    python -m examples.mountain_car.mountain_car_experiment

    # Slime Volleyball (Human vs AI)
    python -m examples.slime_volleyball.slimevb_human_ai

    # Slime Volleyball (Human vs Human, client-side P2P)
    python -m examples.slime_volleyball.slimevb_human_human

    # Overcooked (Human + AI)
    python -m examples.cogrid.overcooked_human_ai

    # Overcooked (Human vs Human) — client-side P2P by default
    python -m examples.cogrid.overcooked_human_human_multiplayer --experiment-id test
    # Server-authoritative variant of the same example
    python -m examples.cogrid.overcooked_server_auth --experiment-id test

    # Footsies
    python -m examples.footsies.footsies_experiment
    ```

4. Open a browser to the port printed on startup (typically http://localhost:5702).

## Common Patterns

These apply across every example and are not repeated on individual pages.

### Eventlet monkey-patching

Every experiment file starts with:

```python
from __future__ import annotations
import eventlet
eventlet.monkey_patch()
```

This must happen before any other imports so Flask-SocketIO networking is non-blocking.

### Serving assets outside the MUG package

Anything loaded by path — sprites, ONNX models, HTML, GIFs — must be registered with `.static_files()` so the server can serve it:

```python
config = (
    experiment_config.ExperimentConfig()
    .experiment(stager=stager, experiment_id="...")
    .hosting(port=5702, host="0.0.0.0")
    .static_files(directories=[
        "examples/<example>/assets",
        "examples/shared/assets",
    ])
)
```

Each directory is served at a URL matching its filesystem path, so the same string used in Python (e.g. `examples/cogrid/assets/.../terrain.png`) is also the browser URL.

### Pyodide environments

For client-side examples, the browser runs a Python file you point `.runtime()` at. That file must leave a module-level variable named `env`:

```python
env = MyEnv(render_mode="mug")
```

MUG loads Pyodide in the browser, pip-installs any `packages_to_install`, executes the file, and calls `env.reset()` / `env.step()` / `env.render()` from JavaScript. For multiplayer P2P, the env must also implement `get_state()` / `set_state()` for GGPO rollback.
