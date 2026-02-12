from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from mug.configurations import configuration_constants, experiment_config
from mug.scenes import gym_scene, stager, static_scene
from mug.server import app

POLICY_MAPPING = {
    "human": configuration_constants.PolicyTypes.Human,
}


LEFT_ACCELERATION = 0
NOOP_ACTION = 1
RIGHT_ACCELERATION = 2

# Map the actions to the arrow keys. The keys are Javascript key press events (all others ignored)
action_mapping = {
    "ArrowLeft": LEFT_ACCELERATION,
    "ArrowRight": RIGHT_ACCELERATION,
}


# Define the start scene, which is the landing page for participants.
start_scene = (
    static_scene.StartScene()
    .scene(
        scene_id="mountain_car_start_scene",
        experiment_config={},
        should_export_metadata=True,
    )
    .display(
        scene_header="Welcome",
        scene_body=(
            "Welcome to the Mountain Car experiment! This is a demonstration of "
            "how to set up a basic experiment with an environment that renders via an RGB image.",
        ),
    )
)


mountain_car_scene = (
    gym_scene.GymScene()
    .scene(scene_id="mountain_car_scene", experiment_config={})
    .policies(policy_mapping=POLICY_MAPPING)
    .rendering(
        fps=30,
        game_width=600,
        game_height=400,
    )
    .gameplay(
        default_action=NOOP_ACTION,
        action_mapping=action_mapping,
        num_episodes=5,
        max_steps=200,
        input_mode=configuration_constants.InputModes.PressedKeys,
    )
    .content(
        scene_header="Mountain Car",
        scene_body="<center><p>" "On this page, Python is initializing and loading packages in the background. With a decent internet connection, it should only be a few moments. If it takes longer than inspected, right click on the page and select 'Inspect -> Console' to see if an error was logged. <br> <br> When it has initialized, the button will become active and you can continue on in the experiment." "</p></center>",
        in_game_scene_body="""
        <center>
        <p>
        Use the arrow keys to move the "car" (ball) up the hill!
        </p>
        </center>
        <br><br>
        """,
    )
    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath="mug/examples/mountain_car/mountain_car_rgb_env.py",
    )
)


end_scene = (
    static_scene.EndScene()
    .scene(scene_id="mountain_car_end_scene")
    .display(
        scene_header="Thanks for playing!",
        scene_body="For more information on MUG or to contact us with any questions, visit interactive-gym.readthedocs.io!",
    )
)

stager = stager.Stager(
    scenes=[
        start_scene,
        mountain_car_scene,
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
        .experiment(stager=stager, experiment_id="mountain_car_demo")
        .hosting(port=5702, host="0.0.0.0")
    )

    app.run(experiment_config)
