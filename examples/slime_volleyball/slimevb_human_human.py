from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from examples.slime_volleyball.slime_volleyball_constants import (
    ACTION_MAPPING, NOOP)
from mug.configurations import configuration_constants, experiment_config
from mug.scenes import gym_scene, stager, static_scene
from mug.server import app

POLICY_MAPPING = {
    "agent_right": configuration_constants.PolicyTypes.Human,
    "agent_left": configuration_constants.PolicyTypes.Human,
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
        hud_score_carry_over=True,
        rollback_smoothing_duration=300,
    )
    .gameplay(
        default_action=NOOP,
        action_mapping=ACTION_MAPPING,
        num_episodes=10,
        max_steps=3000,
        input_mode=configuration_constants.InputModes.PressedKeys,
        action_population_method=configuration_constants.ActionSettings.PreviousSubmittedAction,
    )
    .content(
        scene_header="Slime Volleyball",
        scene_body="<center><p>" "Press start to continue. " "</p></center>",
        in_game_scene_body="""
        <center>
        <p>
        Use the arrow keys <img src="examples/shared/assets/keys/arrow_keys_2.png" alt="Keyboard arrow keys" height="24" width="20" style="vertical-align:middle;">
        to control the slime on the right!
        </p>
        </center>
        <br><br>
        """,
    )
    .waitroom(timeout=120000)  # 2 minutes
    .runtime(
        environment_initialization_code_filepath="examples/slime_volleyball/slimevb_env.py",
        packages_to_install=[
            "slimevb==0.1.1",
        ],
    )
    .multiplayer(
        input_delay=2,
    )
)

end_scene = (
    static_scene.EndScene()
    .scene(scene_id="slimevb_end_scene")
    .display(
        scene_header="Thanks for playing!",
        scene_body="For more information, visit multi-user-gymnasium.readthedocs.io!",
    )
)

stager = stager.Stager(
    scenes=[
        start_scene,
        slime_scene,
        end_scene,
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
        .static_files(
            directories=[
                "examples/slime_volleyball/assets",
                "examples/shared/assets",
            ]
        )
    )

    app.run(experiment_config)
