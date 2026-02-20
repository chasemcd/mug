"""
Overcooked Server-Authoritative Example

This example demonstrates a server-authoritative Overcooked experiment where:
- The environment runs entirely on the server (not in the browser via Pyodide)
- Clients are thin renderers that receive game state via server_render_state events
- Player actions are sent to the server via player_action socket events
- The server maps key presses to environment actions and steps the environment

This is in contrast to the P2P (Pyodide) approach where each client runs their own
copy of the environment. Server-authoritative mode is useful when:
- The environment is too heavy to run in the browser
- You need a single source of truth for the game state
- You want to prevent client-side cheating

Usage:
    python -m mug.examples.cogrid.overcooked_server_auth --experiment-id my_experiment

Then open two browser windows to http://localhost:5703 and play together!
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from mug.configurations import configuration_constants, experiment_config
from mug.examples.cogrid import overcooked_utils
from mug.examples.cogrid.scenes.scenes import (HUMAN_HUMAN_POLICY_MAPPING,
                                               Noop, action_mapping, end_scene,
                                               multiplayer_feedback_scene)
from mug.scenes import gym_scene, stager, static_scene
from mug.server import app


def _create_overcooked_env(**kwargs):
    """Lazy env_creator that imports cogrid only when the server actually creates the env.

    This avoids importing the heavy cogrid environment initialization module at
    import time, which allows the example to be imported for inspection without
    requiring cogrid to be installed.
    """
    from mug.examples.cogrid.environments.cramped_room_environment_initialization_hh import (
        OvercookedEnv, overcooked_config)

    return OvercookedEnv(config=overcooked_config, **kwargs)

# Start scene: landing page for participants
hh_start_scene = (
    static_scene.StartScene()
    .scene(
        scene_id="overcooked_server_auth_start_scene",
        experiment_config={},
        should_export_metadata=True,
    )
    .display(
        scene_header="Welcome",
        scene_body_filepath="mug/server/static/templates/overcooked_hh_instructions.html",
    )
)

# Server-authoritative Overcooked scene
# Key differences from P2P multiplayer:
# - Uses .multiplayer(mode='server_authoritative') instead of P2P mode
# - Uses .environment(env_creator=..., env_config=...) since server creates the env
# - Does NOT use .runtime(run_through_pyodide=True) since there is no Pyodide
server_auth_scene = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_server_auth", experiment_config={})
    .policies(policy_mapping=HUMAN_HUMAN_POLICY_MAPPING)
    .environment(
        env_creator=_create_overcooked_env,
        env_config={"render_mode": "interactive_gym"},
    )
    .rendering(
        fps=30,
        env_to_state_fn=overcooked_utils.overcooked_env_to_render_fn,
        hud_text_fn=overcooked_utils.hud_text_fn,
        game_width=overcooked_utils.TILE_SIZE * 7,
        game_height=overcooked_utils.TILE_SIZE * 6,
        background="#e6b453",
    )
    .assets(
        assets_to_preload=overcooked_utils.overcooked_preload_assets_spec(),
    )
    .gameplay(
        default_action=Noop,
        action_mapping=action_mapping,
        num_episodes=5,
        max_steps=1350,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .content(
        scene_header="Overcooked - Server Authoritative",
        scene_body="<center><p>"
        "You'll now play with another human participant! "
        "Please wait in the lobby for your partner to join. "
        "<br><br> "
        "You will be playing on the layout pictured below. "
        '<center><img src="static/assets/overcooked/cramped_room.png" alt="Annotated Overcooked environment." height="270" width="315"></center>'
        "Work together to prepare and deliver as many dishes as possible. "
        "</p></center>",
        game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
        in_game_scene_body="""
        <center>
        <p>
        Use the arrow keys <img src="static/assets/keys/arrow_keys_2.png" alt="Keyboard arrow keys" height="24" width="20" style="vertical-align:middle;">
        to control your chef and press <img src="static/assets/keys/icons8-w-key-50.png" alt="W key" height="24" width="24" style="vertical-align:middle;"> to pick up and
        drop objects. Coordinate with your partner to deliver as many dishes as possible!
        </p>
        </center>
        <br><br>
        """,
    )
    .multiplayer(mode="server_authoritative")
)

# Create stager with server-auth scenes
stager = stager.Stager(
    scenes=[
        hh_start_scene,
        server_auth_scene,
        multiplayer_feedback_scene,
        end_scene,
    ]
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Overcooked server-authoritative experiment"
    )
    parser.add_argument(
        "--port", type=int, default=5703, help="Port number to listen on"
    )
    parser.add_argument(
        "--experiment-id", type=str, help="Experiment ID", required=True
    )
    args = parser.parse_args()

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager, experiment_id=args.experiment_id)
        .hosting(port=args.port, host="0.0.0.0")
    )

    app.run(experiment_config)
