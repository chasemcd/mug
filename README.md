# Multi-User Gymnasium (MUG)

![PyPI - Version](https://img.shields.io/pypi/v/multi-user-gymnasium)
![PyPI - Downloads](https://img.shields.io/pypi/dm/multi-user-gymnasium)

<div align="center">
  <img src="docs/assets/images/mug_logo.png" alt="MUG logo" width="300"/>
</div>

Multi-User Gymnasium (MUG) converts [Gymnasium](https://gymnasium.farama.org/) and [PettingZoo](https://pettingzoo.farama.org/) environments into browser-based, multi-user experiments. It enables Python simulation environments to be accessed online, allowing humans to interact with them individually or alongside AI agents and other participants.

## Installation

```bash
pip install multi-user-gymnasium
```

## From PettingZoo env to browser experiment

Take any [Gymnasium](https://gymnasium.farama.org/) environment or [PettingZoo](https://pettingzoo.farama.org/) `ParallelEnv`, a policy trained in it, and put them in a participant's browser for human-AI interaction experiments — no server-side inference, no JavaScript.

### 1. Start with a Gymnasium or PettingZoo env

Any Gymnasium env or PettingZoo `ParallelEnv` works. We'll use [CoGrid](https://github.com/chasemcd/cogrid)'s Overcooked Cramped Room throughout:

```python
import cogrid

env = cogrid.make("Overcooked-CrampedRoom-V0")
obs, _ = env.reset()
# Standard PettingZoo ParallelEnv: obs / actions / rewards are dicts keyed by agent id.
```

### 2. Train a partner

MUG doesn't ship a trainer — bring your own ([CleanRL](https://github.com/vwxyzjn/cleanrl), [RLlib](https://docs.ray.io/en/latest/rllib/index.html), [Stable-Baselines3](https://github.com/DLR-RM/stable-baselines3), ...) and export the resulting policy to ONNX. MUG runs the exported model in the browser via `onnxruntime-web`:

```python
# After training with your framework of choice, export to ONNX:
policy.export_onnx("cramped_room_partner.onnx")
```

For an end-to-end run on this environment, see CoGrid's [Overcooked JAX training example](https://github.com/chasemcd/cogrid/blob/main/examples/train_overcooked_jax.py).

### 3. Render to the browser and launch the experiment

MUG renders through the [Surface API](https://mug.readthedocs.io/en/latest/content/core_concepts/surface_api.html): subclass the env and override `render()` to describe each frame with Surface draw calls.

```python
from cogrid.cogrid_env import CoGridEnv
from mug.rendering import Surface

class OvercookedMUG(CoGridEnv):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.surface = Surface(width=225, height=180)

    def render(self):
        # Draw terrain, agents, held items, etc. with self.surface.image(...),
        # self.surface.circle(...), self.surface.text(...), and so on.
        return self.surface.commit()
```

Then wire the env and your ONNX partner into a `GymScene`, assigning agent `0` to the human participant and agent `1` to the trained model:

```python
import eventlet
eventlet.monkey_patch()

from mug.configurations import experiment_config
from mug.configurations.configuration_constants import ModelConfig, PolicyTypes
from mug.scenes import gym_scene, stager, static_scene
from mug.server import app

policy_mapping = {
    0: PolicyTypes.Human,
    1: ModelConfig(
        onnx_path="cramped_room_partner.onnx",
        obs_input="input",
        logit_output="logits",
    ),
}

game = (
    gym_scene.GymScene()
    .scene(scene_id="overcooked_game")
    .policies(policy_mapping=policy_mapping)
    .rendering(fps=30, game_width=225, game_height=180)
    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath="overcooked_mug_env.py",
    )
)

start = static_scene.StartScene().scene(scene_id="start").display(
    scene_header="Welcome",
    scene_body="You'll cook with an AI partner. Press continue to begin.",
)
end = static_scene.EndScene().scene(scene_id="end").display(
    scene_header="Thanks!",
    scene_body="You're all done.",
)

app.run(
    experiment_config.ExperimentConfig()
    .experiment(
        stager=stager.Stager(scenes=[start, game, end]),
        experiment_id="overcooked_hai",
    )
    .hosting(port=8000)
)
```

The CoGrid env and the ONNX policy both run in the participant's browser via Pyodide — the MUG server only ships scene state and collects data.

> **Server-side mode.** Environments with dependencies that can't be compiled to WebAssembly (heavy C/C++, CUDA, ...) can instead run on the host, with state streamed to the browser each step. See the [documentation](https://mug.readthedocs.io/) for the server-side execution path.

## Documentation

Full documentation is available at [mug.readthedocs.io](https://mug.readthedocs.io/).

- [Getting Started](https://mug.readthedocs.io/en/latest/content/quick_start.html)
- [Core Concepts](https://mug.readthedocs.io/en/latest/content/core_concepts/index.html)
- [Examples](https://mug.readthedocs.io/en/latest/content/examples/index.html)

## Acknowledgements

The Phaser integration and server implementation are inspired by and derived from the
Overcooked AI demo by Carroll et al. (https://github.com/HumanCompatibleAI/overcooked-demo/tree/master).
