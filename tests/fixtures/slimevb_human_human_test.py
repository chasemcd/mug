"""
Slime Volleyball Human-Human - Test Configuration

Minimal test server for slime volleyball multiplayer E2E testing:
- Two human players (Pyodide P2P)
- Short episode (200 steps ~7s at 30fps)
- No tutorial, no feedback
- Relaxed browser requirements for test automation

Usage:
    python -m tests.fixtures.slimevb_human_human_test

This is used by pytest E2E tests via the conftest.py flask_server_slimevb_human_human fixture.
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from examples.cogrid.scenes import scenes as oc_scenes
from mug.configurations import configuration_constants, experiment_config
from mug.scenes import gym_scene, stager, static_scene
from mug.server import app

POLICY_MAPPING = {
    "agent_right": configuration_constants.PolicyTypes.Human,
    "agent_left": configuration_constants.PolicyTypes.Human,
}

NOOP = 0
LEFT = 1
UPLEFT = 2
UP = 3
UPRIGHT = 4
RIGHT = 5

ACTION_MAPPING = {
    "ArrowLeft": LEFT,
    ("ArrowLeft", "ArrowUp"): UPLEFT,
    "ArrowUp": UP,
    ("ArrowRight", "ArrowUp"): UPRIGHT,
    "ArrowRight": RIGHT,
}

start_scene = (
    static_scene.StartScene()
    .scene(scene_id="slimevb_start_scene", experiment_config={})
    .display(
        scene_header="Welcome",
        scene_body="Slime Volleyball multiplayer test.",
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
        num_episodes=1,
        max_steps=200,
        input_mode=configuration_constants.InputModes.PressedKeys,
        action_population_method=configuration_constants.ActionSettings.PreviousSubmittedAction,
    )
    .content(
        scene_header="Slime Volleyball",
        scene_body="<center><p>Press start to continue.</p></center>",
        in_game_scene_body="<center><p>Use arrow keys!</p></center>",
    )
    .waitroom(timeout=120000)
    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath="examples/slime_volleyball/slimevb_env.py",
        packages_to_install=["slimevb==0.1.1"],
    )
    .multiplayer(
        multiplayer=True,
        input_delay=2,
    )
)

stager = stager.Stager(
    scenes=[start_scene, slime_scene, oc_scenes.end_scene]
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Slime Volleyball human-human experiment (TEST CONFIG)"
    )
    parser.add_argument(
        "--port", type=int, default=5712, help="Port number to listen on"
    )
    args = parser.parse_args()

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager, experiment_id="slimevb_human_human_test")
        .hosting(port=args.port, host="0.0.0.0")
        .entry_screening(
            browser_requirements=["Chrome"], browser_blocklist=[], max_ping=500
        )
        .static_files(
            directories=[
                "examples/slime_volleyball/assets",
                "examples/shared/assets",
            ]
        )
    )

    app.run(experiment_config)
