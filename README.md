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

## Documentation 

Full documentation is available at [multi-user-gymnasium.readthedocs.io](https://multi-user-gymnasium.readthedocs.io/).


## Quick Start

```python
import eventlet
eventlet.monkey_patch()

from mug.configurations import configuration_constants, experiment_config
from mug.scenes import gym_scene, stager, static_scene
from mug.server import app

start = static_scene.StartScene().scene(scene_id="start").display(
    scene_header="Welcome",
    scene_body="Press continue to begin.",
)

game = (
    gym_scene.GymScene()
    .scene(scene_id="game")
    .rendering(fps=30, game_width=600, game_height=400)
    .gameplay(num_episodes=1)
    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath="my_env.py",
    )
)

end = static_scene.EndScene().scene(scene_id="end").display(
    scene_header="Thanks!",
    scene_body="You're all done.",
)

config = (
    experiment_config.ExperimentConfig()
    .experiment(
        stager=stager.Stager(scenes=[start, game, end]),
        experiment_id="my_experiment",
    )
    .hosting(port=5000)
)

app.run(config)
```

## Acknowledgements

The Phaser integration and server implementation are inspired by and derived from the
Overcooked AI demo by Carroll et al. (https://github.com/HumanCompatibleAI/overcooked-demo/tree/master).
