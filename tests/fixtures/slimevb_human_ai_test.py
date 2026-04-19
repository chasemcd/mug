"""
Slime Volleyball Human-AI - Test Configuration

Minimal test server for slime volleyball ONNX inference E2E testing:
- Single human + ONNX AI partner
- Short episode (200 steps ~7s at 30fps)
- No tutorial, no feedback
- Relaxed browser requirements for test automation

Usage:
    python -m tests.fixtures.slimevb_human_ai_test

This is used by pytest E2E tests via the conftest.py flask_server_slimevb_human_ai fixture.
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from mug.configurations import configuration_constants, experiment_config
from mug.configurations.configuration_constants import ModelConfig
from mug.scenes import gym_scene, stager, static_scene
from mug.server import app

SLIMEVB_MODEL_CONFIG = ModelConfig(
    obs_input="input",
    logit_output="logits",
    onnx_path="examples/slime_volleyball/assets/models/slimevb_policy.onnx",
)

POLICY_MAPPING = {
    "agent_right": SLIMEVB_MODEL_CONFIG,
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
        scene_body="Slime Volleyball test.",
    )
)

slime_scene = (
    gym_scene.GymScene()
    .scene(scene_id="slime_gym_scene", experiment_config={})
    .policies(policy_mapping=POLICY_MAPPING, frame_skip=1)
    .rendering(fps=30, game_width=600, game_height=250)
    .gameplay(
        default_action=NOOP,
        action_mapping=ACTION_MAPPING,
        num_episodes=1,
        max_steps=200,
        input_mode=configuration_constants.InputModes.PressedKeys,
    )
    .content(
        scene_header="Slime Volleyball",
        scene_body="<center><p>Press start to continue.</p></center>",
        in_game_scene_body="<center><p>Use arrow keys!</p></center>",
    )
    .runtime(
        environment_initialization_code_filepath="examples/slime_volleyball/slimevb_env.py",
        packages_to_install=["slimevb==0.1.1"],
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

stager = stager.Stager(scenes=[start_scene, slime_scene, end_scene])

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Slime Volleyball human-AI experiment (TEST CONFIG)"
    )
    parser.add_argument(
        "--port", type=int, default=5711, help="Port number to listen on"
    )
    args = parser.parse_args()

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager, experiment_id="slimevb_human_ai_test")
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
