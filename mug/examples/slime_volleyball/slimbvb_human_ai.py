from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from mug.server import app
from mug.scenes import scene
from mug.scenes import stager
from mug.examples.cogrid.scenes import (
    scenes as oc_scenes,
)
from mug.scenes import static_scene

from mug.configurations import experiment_config
from mug.scenes import gym_scene
from mug.scenes import static_scene
from mug.scenes import scene


from mug.configurations import (
    configuration_constants,
)

POLICY_MAPPING = {
    "agent_right": configuration_constants.PolicyTypes.Human,
    "agent_left": "static/assets/slime_volleyball/models/model.onnx",
}

NOOP = 0
LEFT = 1
UPLEFT = 2
UP = 3
UPRIGHT = 4
RIGHT = 5

# Map the actions to the arrow keys. The keys are Javascript key press events (all others ignored)
ACTION_MAPPING = {
    "ArrowLeft": LEFT,
    ("ArrowLeft", "ArrowUp"): UPLEFT,
    "ArrowUp": UP,
    ("ArrowRight", "ArrowUp"): UPRIGHT,
    "ArrowRight": RIGHT,
}

# Define the start scene, which is the landing page for participants.
start_scene = (
    static_scene.StartScene()
    .scene(
        scene_id="slimevb_start_scene",
        experiment_config={},
        should_export_metadata=True,
    )
    .display(
        scene_header="Welcome",
        scene_body=(
            "Welcome to the Slime Volleyball experiment! This is a demonstration of "
            "how to set up a basic experiment with a human and AI interacting together.",
        ),
    )
)


slime_scene = (
    gym_scene.GymScene()
    .scene(scene_id="slime_gym_scene", experiment_config={})
    .policies(policy_mapping=POLICY_MAPPING, frame_skip=1)
    .rendering(
        fps=30,
        game_width=600,
        game_height=250,
    )
    .gameplay(
        default_action=NOOP,
        action_mapping=ACTION_MAPPING,
        num_episodes=5,
        max_steps=3000,
        input_mode=configuration_constants.InputModes.PressedKeys,
    )
    .content(
        scene_header="Slime Volleyball",
        scene_body="<center><p>" "Press start to continue. " "</p></center>",
        in_game_scene_body="""
        <center>
        <p>
        Use the arrow keys <img src="static/assets/keys/arrow_keys_2.png" alt="Keyboard arrow keys" height="24" width="20" style="vertical-align:middle;">
        to control the slime on the right!
        </p>
        </center>
        <br><br>
        """,
    )
    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath="mug/examples/slime_volleyball/slimevb_env.py",
        packages_to_install=[
            "slimevb==0.0.4",
            "opencv-python",
        ],
    )
)


stager = stager.Stager(
    scenes=[
        start_scene,
        slime_scene,
        oc_scenes.end_scene,
    ]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port", type=int, default=5702, help="Port number to listen on"
    )
    args = parser.parse_args()

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager, experiment_id="slime_vb_demo")
        .hosting(port=5702, host="0.0.0.0")
    )

    app.run(experiment_config)
