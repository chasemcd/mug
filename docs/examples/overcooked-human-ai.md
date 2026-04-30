# Overcooked: Human-AI (Client-Side)

<div align="center">
  <video src="../../assets/images/overcooked_human_ai_experiment.webm" autoplay loop muted playsinline width="600">
    Your browser does not support the video tag.
  </video>
</div>

A human collaborates with an ONNX AI teammate to prepare and deliver dishes on the Cramped Room Overcooked kitchen, with the environment and policy both running client-side via Pyodide. The participant plays two rounds with an AI partner and then fills out a side-by-side preference survey over the two rounds. For illustration, both rounds load the same ONNX weights — swap in different `onnx_path` values to turn this into a real within-subjects comparison between two partners.

**Source:** [`examples/cogrid/overcooked_hai.py`](https://github.com/chasemcd/mug/blob/main/examples/cogrid/overcooked_hai.py)

See [Examples](index.md) for install and run instructions. This example also requires the [CoGrid Overcooked environment](https://github.com/chasemcd/cogrid), which we install in the user's browser (install locally with `pip install cogrid==0.2.1` if you want to run the environment outside the experiment).

## File Structure

```text
cogrid/
├── overcooked_hai.py         # Main experiment file
├── scenes/scenes.py          # Scene definitions
├── overcooked_utils.py       # Rendering + shared helpers
├── environments/
│   └── cramped_room_environment_initialization.py   # Pyodide env (single-agent + ONNX partner)
└── assets/overcooked/models/
    └── cogrid-0.2.1-cramped-room.onnx               # ONNX weights used by both rounds
```

## Experiment Flow

```python
stager = stager.Stager(
    scenes=[
        oc_scenes.start_scene,
        oc_scenes.tutorial_gym_scene,
        oc_scenes.cramped_room_0,       # round 1 + round 2 + preference survey
        oc_scenes.feedback_scene,
        oc_scenes.end_scene,
    ]
)
```

`cramped_room_0` is a `SceneWrapper` that sequences two partner rounds on the Cramped Room kitchen followed by a side-by-side preference survey comparing them.

## Policy Mapping

Each round pairs the human with an ONNX partner loaded in the browser via `onnxruntime-web`. Both mappings point at the same weights file here for illustration — so the partner "changes" between rounds only in that it's a fresh instance. Replace either `onnx_path` with a second model to turn this into an actual comparison.

```python
OVERCOOKED_MODEL_CONFIG = ModelConfig(obs_input="input", logit_output="logits")

POLICY_MAPPING_CRAMPED_ROOM_0 = {
    0: configuration_constants.PolicyTypes.Human,
    1: dataclasses.replace(
        OVERCOOKED_MODEL_CONFIG,
        onnx_path="examples/cogrid/assets/overcooked/models/cogrid-0.2.1-cramped-room.onnx",
    ),
}

POLICY_MAPPING_CRAMPED_ROOM_1 = {
    0: configuration_constants.PolicyTypes.Human,
    1: dataclasses.replace(
        OVERCOOKED_MODEL_CONFIG,
        onnx_path="examples/cogrid/assets/overcooked/models/cogrid-0.2.1-cramped-room.onnx",
    ),
}
```

## Round scene

The second round is built as `copy.deepcopy(...)` of the first with only the policy mapping swapped — everything else (rendering, gameplay, environment file) is identical.

```python
cramped_room_sp_0 = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_sp_0", experiment_config={})
    .policies(policy_mapping=POLICY_MAPPING_CRAMPED_ROOM_0, frame_skip=5)
    .rendering(
        fps=30,
        hud_text_fn=overcooked_utils.hud_text_fn,
        game_width=overcooked_utils.TILE_SIZE * 5,
        game_height=overcooked_utils.TILE_SIZE * 4,
        background="#e6b453",
    )
    .assets(assets_to_preload=overcooked_utils.overcooked_preload_assets_spec())
    .gameplay(
        default_action=Noop, action_mapping=action_mapping,
        num_episodes=1, max_steps=600,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .content(
        scene_header="Overcooked",
        scene_body="... intro copy ...",
        game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
        in_game_scene_body=overcooked_utils.overcooked_two_column_layout(
            'You control <img src="examples/cogrid/assets/overcooked/blue_chef.png" ...>.'
            "<br>Combine onions in the pot, plate the cooked soup, and deliver it to the grey zone."
        ),
    )
    .runtime(
        environment_initialization_code_filepath=(
            "examples/cogrid/environments/cramped_room_environment_initialization.py"
        ),
        packages_to_install=["numpy", "cogrid==0.2.1", "opencv-python"],
    )
)
```

## Preference Survey

After both rounds the participant fills out an `OptionBoxesWithScalesAndTextBox` survey ranking the two partners on coordination, predictability, and human-likeness, plus a text box:

```python
cramped_room_options_scene_0 = (
    static_scene.OptionBoxesWithScalesAndTextBox(
        options=["First Partner", "Second Partner"],
        scale_questions=[
            "My partner and I coordinated our actions well together.",
            "My partner perceived accurately what tasks I was trying to accomplish.",
            "I was able to understand and predict what tasks my partner was trying to accomplish.",
            "My partner felt human-like.",
        ],
        scale_labels=["First Partner", "No Difference", "Second Partner"],
        text_box_header="Please describe any additional reasoning for your preference.",
        option_box_header="Did you prefer your first or second partner?",
    )
    .scene(scene_id="cramped_room_options_scene_0")
    .display(scene_subheader="Partner Feedback")
)
```
