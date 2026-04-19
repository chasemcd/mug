from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from examples.slime_volleyball.slime_volleyball_constants import (
    ACTION_MAPPING, NOOP)
from mug.configurations import configuration_constants, experiment_config
from mug.scenes import gym_scene, stager, static_scene
from mug.server import app
from mug.server.matchmaker import FIFOMatchmaker

POLICY_MAPPING = {
    "agent_right": configuration_constants.PolicyTypes.Human,
    "agent_left": configuration_constants.PolicyTypes.Human,
}


RED_SLIME_IMG = (
    "examples/slime_volleyball/assets/slime_volleyball/red_slime.png"
)
BLUE_SLIME_IMG = (
    "examples/slime_volleyball/assets/slime_volleyball/blue_slime.png"
)
ARROW_KEYS_IMG = "examples/shared/assets/keys/arrow_keys_2.png"

CONTROLS_LEGEND_HTML = f"""
<div style="display: flex; align-items: center; gap: 14px;">
    <img src="{ARROW_KEYS_IMG}" alt="Keyboard arrow keys"
         style="height: 80px; width: auto;">
    <div style="text-align: left; font-size: 0.9em; line-height: 1.4;">
        <div><b>&larr; / &rarr;</b> &nbsp;move</div>
        <div><b>&uarr;</b> &nbsp;jump</div>
        <div><b>&uarr; + &larr; / &rarr;</b> &nbsp;jump diagonally</div>
    </div>
</div>
"""


def _two_column_layout(header_html: str) -> str:
    """Wrap an identity header and the controls legend side-by-side."""
    return f"""
    <div style="font-family: sans-serif; margin: 8px auto; max-width: 720px;">
        <div style="display: flex; align-items: center; justify-content: center;
                    gap: 28px; flex-wrap: wrap;">
            <div style="text-align: left; font-size: 0.95em; max-width: 260px;">
                {header_html}
            </div>
            {CONTROLS_LEGEND_HTML}
        </div>
    </div>
    """


def slime_game_page_html_fn(game, subject_id) -> str:
    """Per-participant in-game HTML so each player sees their own slime color."""
    agent_id = None
    for aid, sid in game.human_players.items():
        if sid == subject_id:
            agent_id = aid
            break

    if agent_id == "agent_left":
        slime_img, side = RED_SLIME_IMG, "left"
    elif agent_id == "agent_right":
        slime_img, side = BLUE_SLIME_IMG, "right"
    else:
        # Spectator / lookup failed — show the generic fallback.
        return ""

    header = (
        f'You control <img src="{slime_img}" alt="Your slime" '
        f'style="height: 1.2em; vertical-align: -0.25em;"> on the <b>{side}</b>.'
        f'<br>Land the ball on your opponent\'s side to score.'
    )
    return _two_column_layout(header)


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
            "how to set up a basic experiment with two human participants.",
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
        num_episodes=2,
        max_steps=3000,
        input_mode=configuration_constants.InputModes.PressedKeys,
        action_population_method=configuration_constants.ActionSettings.PreviousSubmittedAction,
    )
    .content(
        scene_header="Slime Volleyball",
        scene_body="<center><p>"
        "Press start to join the waiting room to find another player!"
        "</p></center>",
        # Fallback HTML shown before player slots are assigned (and for any
        # spectators). Once game_page_html_fn runs, each participant's sceneBody
        # is replaced with the per-player version below.
        in_game_scene_body=_two_column_layout(
            f'<img src="{RED_SLIME_IMG}" alt="Red slime" '
            f'style="height: 1.2em; vertical-align: -0.25em;"> vs '
            f'<img src="{BLUE_SLIME_IMG}" alt="Blue slime" '
            f'style="height: 1.2em; vertical-align: -0.25em;">'
            f"<br>Control your slime and land the ball on your opponent's side to score."
        ),
        game_page_html_fn=slime_game_page_html_fn,
    )
    .waitroom(
        timeout=120000,  # 2 minutes
        timeout_message=(
            "We couldn't find another participant for you to play with. "
            "Thanks for waiting — please close this tab."
        ),
    )
    .runtime(
        environment_initialization_code_filepath="examples/slime_volleyball/slimevb_env.py",
        packages_to_install=[
            "slimevb==0.1.1",
        ],
    )
    .multiplayer(
        input_delay=2,
        # Slime Volleyball is fast-paced and frame-sensitive — rollback
        # corrections become very visible under lag. After FIFO proposes a
        # pair, probe the real peer-to-peer RTT over WebRTC and reject the
        # match if it exceeds 100ms.
        matchmaker=FIFOMatchmaker(max_p2p_rtt_ms=100),
    )
)

end_scene = (
    static_scene.EndScene()
    .scene(scene_id="slimevb_end_scene")
    .display(
        scene_header="Thanks for playing!",
        scene_body=(
            '<div style="text-align: center; font-family: sans-serif; margin-top: 12px;">'
            "For more information, visit "
            '<a href="https://multi-user-gymnasium.readthedocs.io" target="_blank" rel="noopener noreferrer" '
            'style="color: #3f51b5; text-decoration: none; font-weight: 600; border-bottom: 1px solid #3f51b5;">'
            "multi-user-gymnasium.readthedocs.io"
            "</a>."
            "</div>"
        ),
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
