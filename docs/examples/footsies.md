# Footsies

Footsies is a minimalist fighting game (Unity WebGL build) used as a research experiment on human skill learning against controllable AI opponents. Each participant runs through surveys, a tutorial, initial challenge rounds, a training block against an AI partner with a randomly-assigned difficulty-adaptation scheme, and a final challenge block. Opponent ONNX policies are exposed through `OpponentConfig` parameters (`frame_skip`, `obs_delay`, `softmax_temperature`, `inference_cadence`) so training conditions can dial difficulty up or down.

**Source:** [`examples/footsies/footsies_experiment.py`](https://github.com/chasemcd/interactive-gym/blob/main/examples/footsies/footsies_experiment.py)

See [Examples](index.md) for install and run instructions. The Unity WebGL build is included under `examples/footsies/assets/web_gl/`.

## File Structure

```text
footsies/
├── footsies_experiment.py       # Main experiment with full flow
├── scenes.py                    # Scene definitions
├── footsies_scene.py            # Custom FootsiesScene class
├── assets/
│   ├── footsies/                # GIFs, images
│   └── web_gl/                  # Unity WebGL builds
└── static/
    ├── introduction.html
    ├── tutorial_static.html
    └── controllable_difficulty.html
```

## Experiment Flow

```python
stager = stager.Stager(
    scenes=[
        scenes.start_scene,
        scenes.footsies_initial_survey_scene,
        scenes.footsies_tutorial_scene,
        scenes.footsies_initial_challenge_intro,
        scenes.footsies_initial_challenge_scene,
        scenes.footsies_initial_challenge_survey_scene,
        scene.RandomizeOrder(
            [
                scenes.footsies_dynamic_difficulty_rounds,
                scenes.footsies_controllable_difficulty_rounds,
                scenes.footsies_high_skill_rounds,
                scenes.footsies_low_skill_rounds,
                scenes.footsies_random_difficulty_rounds,
                scenes.footsies_dynamic_empowerment_rounds,
                scenes.footsies_empowerment_rounds,
            ],
            keep_n=1,  # one training condition per participant
        ),
        scenes.footsies_training_survey_scene,
        scenes.footsies_mc_survey,
        scenes.footsies_final_challenge_intro,
        scenes.footsies_final_challenge_scene,
        scenes.footsies_end_survey_scene,
        scenes.footsies_end_scene,
    ]
)
```

## Unity WebGL Scene

```python
FOOTSIES_BUILD_NAME = "footsies_webgl_47f26fc"
FOOTSIES_WEBGL_BASE_URL = "examples/footsies/assets/web_gl"

footsies_initial_challenge_scene = (
    footsies_scene.FootsiesScene()
    .scene(scene_id="footsies_initial_challenge")
    .webgl(
        build_name=FOOTSIES_BUILD_NAME,
        height=1080 / 3,
        width=1960 / 3,
        preload_game=True,
        webgl_base_url=FOOTSIES_WEBGL_BASE_URL,
    )
    .game(
        num_episodes=10,
        score_fn=lambda data: int(data["winner"] == "P1"),
    )
    .set_opponent_sequence(
        [
            footsies_scene.OpponentConfig(
                model_path="4fs-16od-13c7f7b-0.05to0.01-sp-00",
                frame_skip=4,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.0,
            ),
            # more opponent configs...
        ],
        randomize=True,
    )
)
```

- `.webgl(...)` loads the Unity build.
- `.game(num_episodes, score_fn)` defines episode count and a per-episode scoring function.
- `.set_opponent_sequence(configs, randomize=True)` cycles opponent configs across episodes, sampling randomly when `randomize=True`.

## Opponent Configuration

`OpponentConfig` parameters control AI difficulty:

| Parameter | Range | Effect |
|-----------|-------|--------|
| `frame_skip` | 4-24 | Higher = AI acts less often (slower / easier) |
| `obs_delay` | 8-24 | Simulates reaction time |
| `softmax_temperature` | 0.5-2.0 | Higher = more random actions |
| `inference_cadence` | 2-8 | How often the policy is queried |

## Training Conditions

Seven conditions are selected between-subjects:

1. **Fixed High Skill** — `frame_skip=4`, `softmax_temperature=1.0`.
2. **Fixed Low Skill** — `frame_skip=24`, `softmax_temperature=1.6`.
3. **Fixed Empowerment** — empowerment-trained policy (`esr-0.5alpha-00`).
4. **Dynamic Difficulty** — adjusts based on player performance (`FootsiesDynamicDifficultyScene`).
5. **Random Difficulty** — resamples difficulty each episode.
6. **Dynamic Empowerment** — empowerment-based adaptive difficulty.
7. **Controllable Difficulty** — participant adjusts opponent difficulty via a slider defined in `static/controllable_difficulty.html`.

## Surveys

- `static_scene.ScalesAndTextBox` — Likert + free text.
- `static_scene.MultipleChoice` with `images=[...]` and `multi_select=True` — each question shows a move GIF and asks the participant to pick the correct key sequence.
- `static_scene.CompletionCodeScene` — generates a unique completion code for Prolific/MTurk.
