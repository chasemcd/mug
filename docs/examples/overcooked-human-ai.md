# Overcooked: Human-AI (Client-Side)

Human-AI coordination experiment where one human player collaborates with an AI teammate to prepare and deliver dishes. The environment runs client-side with AI policy inference in the browser or on the server. In the example, we show Experiment 1 from from [McDonald & Gonzalez (2025)](https://arxiv.org/abs/2503.05455).
It represents an experiment where humans play with two different AI partners, produced by two separate algorithms. Participants play
with the agents across layouts and their subjective preferences between the two are evaluated, alongside survey responses.

## Overview

Participants work alongside an AI chef to complete cooking tasks in various kitchen layouts. This example demonstrates client-side execution with trained ONNX policies, tutorial onboarding, and randomized layout selection for research experiments.

**What you'll learn:**

- Client-side Human-AI coordination experiments
- Tutorial scenes for participant onboarding
- Randomized scene selection for between-subjects designs
- ONNX policy integration with multiple trained models
- Complex sprite-based rendering with atlases

## Features Demonstrated

| Feature | Details |
|---------|---------|
| **Execution Mode** | Client-side |
| **Players** | 1 human + 1 AI |
| **Environment** | CoGrid Overcooked with 5 kitchen layouts |
| **Rendering** | Sprite atlases with tile-based rendering |
| **Input** | Arrow keys + action keys (W, Q) |
| **AI Policies** | Self-Play (SP) and Behavior Shaping (BS) models for each layout |
| **Complexity** | Advanced |

## Prerequisites

1. Clone the MUG repository and install with server dependencies:

    ```bash
    git clone https://github.com/chasemcd/interactive-gym.git
    cd interactive-gym
    pip install -e .[server]
    ```

2. Install the CoGrid Overcooked environment:

    ```bash
    pip install cogrid
    ```

## Running the Example

From the repository root, run as a module:

```bash
python -m examples.cogrid.overcooked_human_ai_client_side
```

Then:

1. **Open browser** to http://localhost:5702
2. **Read instructions** on the start screen
3. **Complete tutorial** - Solo practice to learn controls
4. **Play main game** - Collaborate with AI on one randomly-selected layout
5. **Provide feedback** - Complete survey about AI teammate

**Controls:**

- **Arrow Keys**: Move chef up/down/left/right
- **W**: Pick up / drop objects
- **Q**: Toggle (interact with pots)

## File Structure

```text
cogrid/
├── overcooked_human_ai_client_side.py  # Main experiment file
├── scenes/
│   └── scenes.py                       # Scene definitions
└── overcooked_utils.py                 # Rendering functions
```

## Experiment Flow

The experiment uses a Stager to manage scene progression:

```python
from mug.scenes import stager, scene
from examples.cogrid.scenes import scenes as oc_scenes

stager = stager.Stager(
    scenes=[
        oc_scenes.start_scene,           # Welcome and instructions
        oc_scenes.tutorial_gym_scene,    # Solo practice
        scene.RandomizeOrder(            # Random layout selection
            scenes=[
                oc_scenes.cramped_room_0,
                oc_scenes.counter_circuit_0,
                oc_scenes.forced_coordination_0,
                oc_scenes.asymmetric_advantages_0,
                oc_scenes.coordination_ring_0,
            ],
            keep_n=1,                   # Only play on one of the 5 layouts
        ),
        oc_scenes.feedback_scene,        # Survey
        oc_scenes.end_scene,             # Thank you
    ]
)
```

Each participant experiences:

1. **Start Scene** - Instructions and consent
2. **Tutorial** - Solo practice in a simple layout
3. **One Random Layout** - Collaboration with AI
4. **Feedback Survey** - Questions about the AI teammate
5. **End Scene** - Thank you message

### Serving Assets

Because sprites, ONNX models, and images live outside the MUG package (under
`examples/cogrid/assets/`), the experiment config registers them with
`static_files()` so the server can serve them to the browser:

```python
config = (
    experiment_config.ExperimentConfig()
    .experiment(stager=stager, experiment_id="overcooked_test")
    .hosting(port=5702, host="0.0.0.0")
    .static_files(directories=[
        "examples/cogrid/assets",
        "examples/shared/assets",   # shared keyboard icon images
    ])
)

app.run(config)
```

Each directory is served at a URL that matches its filesystem path. For example,
`examples/cogrid/assets/overcooked/sprites/terrain.png` is available at
`/examples/cogrid/assets/overcooked/sprites/terrain.png` in the browser —
the same path used in Python rendering code, HTML `<img>` tags, and atlas specs.

## Kitchen Layouts

Five layouts with different coordination challenges:

**Cramped Room**
:   Small kitchen requiring tight coordination and turn-taking

**Asymmetric Advantages**
:   Asymmetric layout where players have different optimal roles

**Counter Circuit**
:   Large kitchen with circular counter layout promoting specialization

**Forced Coordination**
:   Layout requiring specific division of labor to succeed

**Coordination Ring**
:   Ring-shaped kitchen with central cooking area

Each layout has trained AI policies:

- **Self-Play (SP)** policies: Trained via self-play reinforcement learning
- **Behavior Shaping (BS)** policies: Trained to complement human partners using behavioral shaping techniques (McDonald & Gonzalez, 2025)

## AI Policies

### Policy Configuration

Each layout has two policy variants defined in `scenes/scenes.py`. The Behavior Shaping (BS) policies are trained using techniques from McDonald & Gonzalez (2025) to create AI teammates that complement human partners:

```python
# Cramped Room policies
SP_POLICY_MAPPING_CRAMPED_ROOM = {
    0: configuration_constants.PolicyTypes.Human,
    1: "examples/cogrid/assets/overcooked/models/sp_cramped_room_00.onnx",
}

BS_POLICY_MAPPING_CRAMPED_ROOM = {
    0: configuration_constants.PolicyTypes.Human,
    1: "examples/cogrid/assets/overcooked/models/ibc_cramped_room_00.onnx",
}

# Similarly for other layouts...
# - SP_POLICY_MAPPING_ASYMMETRIC_ADVANTAGES
# - BS_POLICY_MAPPING_COUNTER_CIRCUIT
# - SP_POLICY_MAPPING_FORCED_COORDINATION
# - BS_POLICY_MAPPING_COORDINATION_RING
```

### Scene Creation

Each layout scene is configured with its policy:

```python
cramped_room_0 = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_0", experiment_config={})
    .policies(policy_mapping=SP_POLICY_MAPPING_CRAMPED_ROOM)
    .rendering(
        fps=30,
        env_to_state_fn=overcooked_utils.overcooked_env_to_render_fn,
        assets_to_preload=overcooked_utils.overcooked_preload_assets_spec(),
        hud_text_fn=overcooked_utils.hud_text_fn,
        game_width=overcooked_utils.TILE_SIZE * 5,
        game_height=overcooked_utils.TILE_SIZE * 4,
        background="#e6b453",
    )
    .gameplay(
        default_action=Noop,
        action_mapping=action_mapping,
        num_episodes=3,
        max_steps=30 * 60,  # 60 seconds at 30 FPS
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .environment(
        env_creator=make_cramped_room_env,
        env_name="cramped_room",
    )
)
```

## Tutorial Scene

Solo practice before playing with AI:

```python
tutorial_gym_scene = (
    gym_scene.GymScene()
    .scene(scene_id="overcooked_tutorial", experiment_config={})
    .policies(
        policy_mapping={
            0: configuration_constants.PolicyTypes.Human,
        },
    )
    .rendering(
        fps=30,
        env_to_state_fn=overcooked_utils.overcooked_env_to_render_fn,
        assets_to_preload=overcooked_utils.overcooked_preload_assets_spec(),
        hud_text_fn=overcooked_utils.hud_text_fn,
        game_width=overcooked_utils.TILE_SIZE * 5,
        game_height=overcooked_utils.TILE_SIZE * 4,
        background="#e6b453",
    )
    .gameplay(
        default_action=Noop,
        action_mapping=action_mapping,
        num_episodes=1,
        max_steps=1000,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .content(
        scene_header="Overcooked Tutorial",
        scene_body_filepath="examples/cogrid/html_pages/overcooked_controls.html",
        in_game_scene_body="""
            <center>
            <p>Use arrow keys and W to pick up/drop. Try delivering a dish!</p>
            </center>
        """,
    )
    .environment(
        env_creator=make_tutorial_env,
        env_name="tutorial",
    )
)
```

The tutorial allows participants to learn:

- Movement with arrow keys
- Picking up onions with W
- Dropping onions in pots with W
- Picking up plates
- Delivering completed dishes

## Rendering System

### Sprite Atlases

Overcooked uses texture atlases for efficient rendering. Atlases are registered
via the `Surface` API, which handles loading sprite sheets and their
accompanying JSON frame maps.

In client-side/Pyodide environments, atlases are registered directly on the
`Surface` instance:

```python
from mug.rendering import Surface

ASSET_PATH = "examples/cogrid/assets/overcooked/sprites"

self.surface = Surface(width=WIDTH, height=HEIGHT)
self.surface.register_atlas(
    "terrain",
    img_path=f"{ASSET_PATH}/terrain.png",
    json_path=f"{ASSET_PATH}/terrain.json",
)
self.surface.register_atlas(
    "chefs",
    img_path=f"{ASSET_PATH}/chefs.png",
    json_path=f"{ASSET_PATH}/chefs.json",
)
self.surface.register_atlas(
    "objects",
    img_path=f"{ASSET_PATH}/objects.png",
    json_path=f"{ASSET_PATH}/objects.json",
)
```

For server-authoritative scenes that need to tell the browser which atlases to
preload, the `overcooked_preload_assets_spec()` helper returns a list of atlas
descriptors:

```python
ASSET_PATH = "examples/cogrid/assets/overcooked/sprites"

def overcooked_preload_assets_spec() -> list[dict]:
    return [
        {"object_type": "atlas_spec", "name": "terrain", "img_path": f"{ASSET_PATH}/terrain.png", "atlas_path": f"{ASSET_PATH}/terrain.json"},
        {"object_type": "atlas_spec", "name": "chefs", "img_path": f"{ASSET_PATH}/chefs.png", "atlas_path": f"{ASSET_PATH}/chefs.json"},
        {"object_type": "atlas_spec", "name": "objects", "img_path": f"{ASSET_PATH}/objects.png", "atlas_path": f"{ASSET_PATH}/objects.json"},
    ]
```

### Tile-Based Coordinates

```python
TILE_SIZE = 45

def get_x_y(pos: tuple[int, int], game_height: int, game_width: int):
    col, row = pos
    x = row * TILE_SIZE / game_width
    y = col * TILE_SIZE / game_height
    return x, y
```

### Static vs Dynamic Rendering

Permanent objects (counters, stacks, delivery zones) are rendered once:

```python
def overcooked_env_to_render_fn(env, config):
    render_objects = []

    # Static objects rendered only on first frame
    if env.t == 0:
        render_objects += generate_counter_objects(env, config)
        render_objects += generate_delivery_areas(env, config)
        render_objects += generate_static_tools(env, config)

    # Dynamic objects every frame
    render_objects += generate_agent_sprites(env, config)
    render_objects += generate_objects(env, config)

    return [obj.as_dict() for obj in render_objects]
```

### HUD Display

```python
def hud_text_fn(game):
    score = int(list(game.episode_rewards.values())[0])
    time_left = (game.env.max_steps - game.tick_num) / game.config.fps
    return f"Score: {score:03d}   |    Time Left: {time_left:.1f}s"
```

## Data Collection

MUG automatically tracks:

- Each player's observations
- Actions taken by human and AI
- Shared team reward (dishes delivered)
- Episode score and time
- Timestamped event logs

### Feedback Survey

The experiment includes a post-game survey:

```python
feedback_scene = (
    static_scene.ScalesAndTextBox(
        scale_questions=[
            "The AI teammate was helpful.",
            "I enjoyed working with the AI teammate.",
            "The AI teammate understood my intentions.",
        ],
        scale_labels=[
            ["Strongly Disagree", "Neutral", "Strongly Agree"],
            ["Strongly Disagree", "Neutral", "Strongly Agree"],
            ["Strongly Disagree", "Neutral", "Strongly Agree"],
        ],
        text_box_header="Please describe your experience working with the AI teammate.",
        scale_size=7,
    )
    .scene(scene_id="feedback_scene", experiment_config={})
)
```

## Research Applications

This example is designed for research on:

**Human-AI Coordination**
:   Study how humans adapt to different AI policies

**Policy Comparison**
:   Compare Self-Play vs Behavior Shaping policies with human partners

**Layout Effects**
:   Investigate how environment structure affects coordination

**Learning and Adaptation**
:   Track how humans change strategy when working with AI

**Theory of Mind**
:   Study mental model formation during collaboration

## References

McDonald, C., & Gonzalez, C. (2025). Controllable Complementarity: Subjective Preferences in Human-AI Collaboration. *arXiv preprint arXiv:2503.05455*.
