"""
Overcooked Server-Authoritative - Test Configuration

This is a test-specific version of the server-authoritative experiment with
settings suitable for E2E testing:
- Short episodes (200 steps, ~7 seconds at 30fps)
- Single episode for fast test completion
- No focus loss timeout
- No RTT limit
- Uses cramped_room layout

Usage:
    python -m tests.fixtures.overcooked_server_auth_test --port 5710

This is used by pytest E2E tests via the conftest.py flask_server_auth fixture.
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from mug.configurations import configuration_constants, experiment_config
from mug.examples.cogrid import overcooked_utils
from mug.examples.cogrid.scenes.scenes import (HUMAN_HUMAN_POLICY_MAPPING,
                                               Noop, action_mapping, end_scene)
from mug.scenes import gym_scene, stager, static_scene
from mug.server import app
from mug.server.matchmaker import FIFOMatchmaker


def _create_overcooked_env(**kwargs):
    """Lazy env_creator that imports cogrid only when the server creates the env.

    Defers the heavy cogrid import to runtime so this module can be imported
    without cogrid installed (same pattern as overcooked_server_auth.py).
    """
    from mug.examples.cogrid.environments.cramped_room_environment_initialization_hh import (
        OvercookedEnv, overcooked_config)

    return OvercookedEnv(config=overcooked_config, **kwargs)


# Start scene: landing page
hh_start_scene = (
    static_scene.StartScene()
    .scene(
        scene_id="overcooked_server_auth_test_start",
        experiment_config={},
        should_export_metadata=True,
    )
    .display(
        scene_header="Welcome",
        scene_body_filepath="mug/server/static/templates/overcooked_hh_instructions.html",
    )
)

# Server-authoritative GymScene with short episodes for testing
server_auth_test_scene = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_server_auth_test", experiment_config={})
    .policies(policy_mapping=HUMAN_HUMAN_POLICY_MAPPING)
    .environment(
        env_creator=_create_overcooked_env,
        env_config={"render_mode": "mug"},
    )
    .rendering(
        fps=30,
        hud_text_fn=overcooked_utils.hud_text_fn,
        game_width=overcooked_utils.TILE_SIZE * 7,
        game_height=overcooked_utils.TILE_SIZE * 6,
        background="#e6b453",
    )
    .gameplay(
        default_action=Noop,
        action_mapping=action_mapping,
        num_episodes=1,
        max_steps=200,  # ~7 seconds at 30fps for fast test completion
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .content(
        scene_header="Overcooked - Server Auth Test",
        scene_body="<center><p>Server-authoritative test game.</p></center>",
        game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
        in_game_scene_body="""
        <center>
        <p>
        Use the arrow keys to control your chef and press W to pick up and drop objects.
        </p>
        </center>
        <br><br>
        """,
    )
    .multiplayer(
        mode="server_authoritative",
        focus_loss_timeout_ms=0,  # Disable focus timeout for test automation
    )
    .matchmaking(
        max_rtt=None,  # No RTT limit for testing
        matchmaker=FIFOMatchmaker(),
    )
)

# Stager: StartScene -> server-auth GymScene -> end scene
stager = stager.Stager(
    scenes=[
        hh_start_scene,
        server_auth_test_scene,
        end_scene,
    ]
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Overcooked server-authoritative experiment (TEST CONFIG)"
    )
    parser.add_argument(
        "--port", type=int, default=5710, help="Port number to listen on"
    )
    args = parser.parse_args()

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(
            stager=stager,
            experiment_id="overcooked_server_auth_test",
        )
        .hosting(port=args.port, host="0.0.0.0")
        .entry_screening(
            browser_requirements=["Chrome"],
            browser_blocklist=[],
            max_ping=500,
        )
        .webrtc(force_relay=False)
    )

    app.run(experiment_config)
