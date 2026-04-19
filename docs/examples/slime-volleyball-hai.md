# Slime Volleyball: Human-AI

<div align="center">
  <video src="../assets/images/slime_vb_human_ai.webm" autoplay loop muted playsinline width="600">
    Your browser does not support the video tag.
  </video>
</div>

A human plays volleyball against an AI opponent in the browser. The environment and the policy both run in Pyodide, and the example demonstrates ONNX-in-browser inference and multi-key action combinations.

**Source:** [`examples/slime_volleyball/slimevb_human_ai.py`](https://github.com/chasemcd/interactive-gym/blob/main/examples/slime_volleyball/slimevb_human_ai.py)

See [Examples](index.md) for install and run instructions. This example also requires the [Slime Volleyball game](https://github.com/chasemcd/slimevolleygym) (ported from [David Ha's original implementation](https://github.com/hardmaru/slimevolleygym)), which we install in the user's browsers (install locally with `pip install slimevb==0.1.1`).

## File Structure

```text
slime_volleyball/
├── slimevb_human_ai.py        # Human vs AI experiment
├── slimevb_human_human.py     # Human vs Human experiment
├── slimevb_env.py             # Environment with custom rendering
├── slime_volleyball_utils.py  # Rendering helpers
└── assets/
    └── models/
        └── slimevb_policy.onnx
```

## Policy Mapping

The ONNX policy runs in the browser via `onnxruntime-web`. MUG downloads the `.onnx` file, runs inference each step, and uses the output as the action for that agent:

```python
from mug.configurations.configuration_constants import ModelConfig, PolicyTypes

SLIMEVB_MODEL_CONFIG = ModelConfig(
    obs_input="input",
    logit_output="logits",
    onnx_path="examples/slime_volleyball/assets/models/slimevb_policy.onnx",
)

POLICY_MAPPING = {
    "agent_right": SLIMEVB_MODEL_CONFIG,
    "agent_left": PolicyTypes.Human,
}
```

`obs_input` and `logit_output` are the tensor names inside the ONNX model.

## Multi-Key Actions

Tuple keys represent simultaneous key presses:

```python
# Action space mapping from the Gym environment
NOOP = 0
LEFT = 1
UP_LEFT = 2
UP = 3
UP_RIGHT = 4
RIGHT = 5


# Key mapping for human input
ACTION_MAPPING = {
    "ArrowLeft": LEFT,
    ("ArrowLeft", "ArrowUp"): UP_LEFT,
    "ArrowUp": UP,
    ("ArrowRight", "ArrowUp"): UP_RIGHT,
    "ArrowRight": RIGHT,
}
```

## Scene

```python
slime_scene = (
    gym_scene.GymScene()
    .scene(scene_id="slime_gym_scene")
    .policies(policy_mapping=POLICY_MAPPING, frame_skip=1)
    .rendering(fps=30, game_width=600, game_height=250)
    .gameplay(
        default_action=NOOP,
        action_mapping=ACTION_MAPPING,
        num_episodes=5,
        max_steps=3000,
        input_mode=configuration_constants.InputModes.PressedKeys,
    )
    .runtime(
        environment_initialization_code_filepath="examples/slime_volleyball/slimevb_env.py",
        packages_to_install=["slimevb==0.1.1"],
    )
)
```

## Environment Rendering

`slimevb_env.py` overrides `render()` to build dict-shaped render objects:

```python
class SlimeVBEnvIG(slimevolley_env.SlimeVolleyEnv):
    def render(self):
        assert self.render_mode == "mug"
        return slime_volleyball_env_to_rendering(self)

env = SlimeVBEnvIG(config={"human_inputs": True}, render_mode="mug")
```

Static elements (fence, ground, net) are marked `permanent=True` so they are only sent on the first frame. Slimes are rendered as semi-circle polygons with separate eye-white and pupil circles; the pupil position is computed each frame from the ball's position to give the slimes gaze-tracking.
