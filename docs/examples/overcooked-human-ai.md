# Overcooked: Human-AI (Client-Side)

<div align="center">
  <video src="../assets/images/overcooked_human_ai_experiment.webm" autoplay loop muted playsinline width="600">
    Your browser does not support the video tag.
  </video>
</div>

A human collaborates with an ONNX AI teammate to prepare and deliver dishes in an Overcooked kitchen, with the environment and policy both running client-side via Pyodide. Each participant plays one of five kitchen layouts — selected at random via `RandomizeOrder` — against a Self-Play or Behavior Shaping policy, then completes a feedback survey. The example reproduces Experiment 1 from [McDonald & Gonzalez (2025)](https://arxiv.org/abs/2503.05455).

**Source:** [`examples/cogrid/overcooked_human_ai.py`](https://github.com/chasemcd/interactive-gym/blob/main/examples/cogrid/overcooked_human_ai.py)

See [Examples](index.md) for install and run instructions. This example also requires:

```bash
pip install cogrid
```

## File Structure

```text
cogrid/
├── overcooked_human_ai.py    # Main experiment file
├── scenes/scenes.py          # Scene definitions for each layout
└── overcooked_utils.py       # Rendering functions
```

## Experiment Flow

```python
stager = stager.Stager(
    scenes=[
        oc_scenes.start_scene,
        oc_scenes.tutorial_gym_scene,
        scene.RandomizeOrder(
            scenes=[
                oc_scenes.cramped_room_0,
                oc_scenes.counter_circuit_0,
                oc_scenes.forced_coordination_0,
                oc_scenes.asymmetric_advantages_0,
                oc_scenes.coordination_ring_0,
            ],
            keep_n=1,  # one randomly-selected layout per participant
        ),
        oc_scenes.feedback_scene,
        oc_scenes.end_scene,
    ]
)
```

## Policy Mapping

Each layout has two ONNX variants — Self-Play and Behavior Shaping:

```python
SP_POLICY_MAPPING_CRAMPED_ROOM = {
    0: configuration_constants.PolicyTypes.Human,
    1: "examples/cogrid/assets/overcooked/models/sp_cramped_room_00.onnx",
}

BS_POLICY_MAPPING_CRAMPED_ROOM = {
    0: configuration_constants.PolicyTypes.Human,
    1: "examples/cogrid/assets/overcooked/models/ibc_cramped_room_00.onnx",
}
```

## Scene Template

```python
cramped_room_0 = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_0")
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
        max_steps=30 * 60,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .environment(env_creator=make_cramped_room_env, env_name="cramped_room")
)
```

## Sprite Atlases

Overcooked uses texture atlases. In Pyodide environments, register them on the `Surface`:

```python
ASSET_PATH = "examples/cogrid/assets/overcooked/sprites"

self.surface = Surface(width=WIDTH, height=HEIGHT)
self.surface.register_atlas("terrain", img_path=f"{ASSET_PATH}/terrain.png", json_path=f"{ASSET_PATH}/terrain.json")
self.surface.register_atlas("chefs",   img_path=f"{ASSET_PATH}/chefs.png",   json_path=f"{ASSET_PATH}/chefs.json")
self.surface.register_atlas("objects", img_path=f"{ASSET_PATH}/objects.png", json_path=f"{ASSET_PATH}/objects.json")
```

For server-authoritative scenes, `overcooked_preload_assets_spec()` returns descriptors the browser uses to preload the same atlases.

## Static vs Dynamic Rendering

Counters, stacks, and delivery zones are drawn once on frame 0; agents and held objects are drawn every frame:

```python
def overcooked_env_to_render_fn(env, config):
    objs = []
    if env.t == 0:
        objs += generate_counter_objects(env, config)
        objs += generate_delivery_areas(env, config)
        objs += generate_static_tools(env, config)
    objs += generate_agent_sprites(env, config)
    objs += generate_objects(env, config)
    return [o.as_dict() for o in objs]
```

## Feedback Survey

Post-game Likert + free-text scene:

```python
feedback_scene = (
    static_scene.ScalesAndTextBox(
        scale_questions=[
            "The AI teammate was helpful.",
            "I enjoyed working with the AI teammate.",
            "The AI teammate understood my intentions.",
        ],
        scale_labels=[["Strongly Disagree", "Neutral", "Strongly Agree"]] * 3,
        text_box_header="Please describe your experience working with the AI teammate.",
        scale_size=7,
    )
    .scene(scene_id="feedback_scene")
)
```

## References

McDonald, C., & Gonzalez, C. (2025). *Controllable Complementarity: Subjective Preferences in Human-AI Collaboration*. arXiv:2503.05455.
