from __future__ import annotations

import copy
import dataclasses

import eventlet

eventlet.monkey_patch()


from examples.cogrid import overcooked_utils
from mug.configurations import configuration_constants
from mug.configurations.configuration_constants import ModelConfig
from mug.scenes import gym_scene, scene, static_scene
from mug.server.matchmaker import FIFOMatchmaker

# Constants for controls/actions/etc.
MoveUp = 0
MoveDown = 1
MoveLeft = 2
MoveRight = 3
PickupDrop = 4
Toggle = 5
Noop = 6


OVERCOOKED_MODEL_CONFIG = ModelConfig(
    obs_input="input",
    logit_output="logits",
)

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

HUMAN_HUMAN_POLICY_MAPPING = {
    0: configuration_constants.PolicyTypes.Human,
    1: configuration_constants.PolicyTypes.Human,
}

# Map the actions to the arrow keys. The keys are Javascript key press events (all others ignored)
action_mapping = {
    "ArrowLeft": MoveLeft,
    "ArrowRight": MoveRight,
    "ArrowUp": MoveUp,
    "ArrowDown": MoveDown,
    "w": PickupDrop,
    "W": PickupDrop,
    "q": Toggle,
    "Q": Toggle,
}


# Define the start scene, which is the landing page for participants.
start_scene = (
    static_scene.StartScene()
    .scene(
        scene_id="overcooked_start_scene",
        experiment_config={},
        should_export_metadata=True,
    )
    .display(
        scene_header="Welcome",
        scene_body_filepath="examples/cogrid/html_pages/overcooked_instructions.html",
    )
)


# Now define the tutorial gym scene, where we teach participants how to play.
tutorial_gym_scene = (
    gym_scene.GymScene()
    .scene(
        scene_id="overcooked_tutorial",
        experiment_config={},
    )
    .policies(
        policy_mapping={
            0: configuration_constants.PolicyTypes.Human,
        },
    )
    .rendering(
        fps=30,
        hud_text_fn=overcooked_utils.hud_text_fn,
        game_width=overcooked_utils.TILE_SIZE * 5,
        game_height=overcooked_utils.TILE_SIZE * 4,
        background="#e6b453",
    )
    .assets(
        assets_to_preload=overcooked_utils.overcooked_preload_assets_spec(),
    )
    .gameplay(
        default_action=Noop,
        action_mapping=action_mapping,
        num_episodes=1,
        max_steps=500,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .content(
        scene_header="Overcooked Tutorial",
        scene_body_filepath="examples/cogrid/html_pages/overcooked_controls.html",
        in_game_scene_body=overcooked_utils.overcooked_two_column_layout(
            'You control <img src="examples/cogrid/assets/overcooked/blue_chef.png" '
            'alt="Blue Chef" style="height: 1.2em; vertical-align: -0.25em;">.'
            "<br>Try to deliver as many dishes as possible: combine onions in the pot, "
            "plate the cooked soup, and deliver it to the grey zone."
        ),
        game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
    )
    .runtime(
        environment_initialization_code_filepath="examples/cogrid/environments/tutorial_cramped_room_environment_initialization.py",
        packages_to_install=["numpy", "cogrid==0.2.1", "opencv-python"],
    )
)


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
    .assets(
        assets_to_preload=overcooked_utils.overcooked_preload_assets_spec(),
    )
    .gameplay(
        default_action=Noop,
        action_mapping=action_mapping,
        num_episodes=1,
        max_steps=600,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .content(
        scene_header="Overcooked",
        scene_body="<center><p>"
        "You'll now play with a partner for a single round. "
        "This will be followed by a round with a different partner "
        "in the same environment layout."
        "<br><br> "
        "You will be playing on the layout pictured below. "
        '<center><img src="examples/cogrid/assets/overcooked/cramped_room.png" alt="Annotated Overcooked environment." height="270" width="315"></center>'
        "When the button activates, click it to begin. "
        "</p></center>",
        game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
        in_game_scene_body=overcooked_utils.overcooked_two_column_layout(
            'You control <img src="examples/cogrid/assets/overcooked/blue_chef.png" '
            'alt="Blue Chef" style="height: 1.2em; vertical-align: -0.25em;">.'
            "<br>Combine onions in the pot, plate the cooked soup, and deliver it to "
            "the grey zone."
        ),
    )
    .runtime(
        environment_initialization_code_filepath="examples/cogrid/environments/cramped_room_environment_initialization.py",
        packages_to_install=["numpy", "cogrid==0.2.1", "opencv-python"],
    )
)
cramped_room_ibc_0 = (
    copy.deepcopy(cramped_room_sp_0)
    .scene(scene_id="cramped_room_ibc_0", experiment_config={})
    .policies(policy_mapping=POLICY_MAPPING_CRAMPED_ROOM_1)
    .content(
        scene_header="Overcooked",
        scene_body="<center><p>"
        "You'll now play another round on the same layout. "
        "After this round, you will provide your preference "
        "between the two partners you interacted with. "
        "When the button activates, click it to begin. "
        "</p></center>",
    )
)
cramped_room_options_scene_0 = (
    static_scene.OptionBoxesWithScalesAndTextBox(
        options=["First Partner", "Second Partner"],
        scale_questions=[
            "My partner and I coordinated our actions well together.",
            "My partner perceived accurately what tasks I was trying to accomplish.",
            "I was able to understand and predict what tasks my partner was trying to accomplish.",
            "My partner felt human-like.",
        ],
        pre_scale_header="Now, please indicate the relative extent to which you agree with the following statements about each partner. Move the slider to the left if the statement holds more for the first partner, and to the right for the second partner.",
        scale_labels=["First Partner", "No Difference", "Second Partner"],
        text_box_header="Please describe any additional reasoning for your preference. This might include specific actions or behaviors that you liked or disliked. You may write N/A if you do not have any anything to add.",
        option_box_header="Did you prefer your first or second partner?",
    )
    .scene(scene_id="cramped_room_options_scene_0", experiment_config={})
    .display(scene_subheader="Partner Feedback")
)


def _build_human_human_scene(
    layout_name: str, cols: int, rows: int, label: str, preview_img: str
):
    """Build a human-human multiplayer scene for one Overcooked layout."""
    scene_id = f"hh_{layout_name}"
    width_px = overcooked_utils.TILE_SIZE * cols
    height_px = overcooked_utils.TILE_SIZE * rows
    # Preview image dimensions scaled to keep a consistent on-screen footprint.
    preview_width = 315
    preview_height = int(preview_width * rows / cols)
    return (
        gym_scene.GymScene()
        .scene(scene_id=scene_id, experiment_config={})
        .policies(policy_mapping=HUMAN_HUMAN_POLICY_MAPPING)
        .rendering(
            fps=30,
            hud_text_fn=overcooked_utils.hud_text_fn,
            game_width=width_px,
            game_height=height_px,
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
            scene_header=f"Overcooked - {label}",
            scene_body=(
                "<center><p>"
                "You'll now play with another player! "
                "Press start to join the lobby and find a partner. "
                "<br><br> "
                f"You will be playing on the <b>{label}</b> layout pictured below. "
                "Work together to prepare and deliver as many dishes as possible."
                f'<br><br><img src="{preview_img}" alt="{label} layout" '
                f'height="{preview_height}" width="{preview_width}">'
                "</p></center>"
            ),
            game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
            in_game_scene_body=overcooked_utils.overcooked_two_column_layout(
                "You and your partner control the two chefs."
                "<br>Coordinate to deliver as many dishes as possible."
            ),
        )
        .waitroom(
            timeout=300000,  # 5 minutes
            timeout_message="Sorry, we could not find enough players for this study. Please return the HIT now. You will be paid through a Compensation HIT.",
        )
        .runtime(
            environment_initialization_code=overcooked_utils.make_hh_env_init_code(
                layout_name, cols, rows
            ),
            packages_to_install=["numpy", "cogrid==0.2.1", "opencv-python"],
        )
        .multiplayer(
            input_delay=3,
            matchmaker=FIFOMatchmaker(
                max_p2p_rtt_ms=100,  # only pair participants with <=100ms RTT
            ),
            hide_lobby_count=True,
            partner_disconnect_message="Your partner disconnected. The task will end here and you will be compensated for your performance so far. Please submit the completion code below.",
            partner_disconnect_show_completion_code=True,
        )
    )


# One scene per layout. RandomizeOrder(keep_n=1) picks one for each
# participant pair so the study covers all five layouts across participants.
human_human_layout_scenes = [
    _build_human_human_scene(layout_name, cols, rows, label, preview_img)
    for layout_name, cols, rows, label, preview_img in overcooked_utils.HH_LAYOUTS
]

cramped_room_human_human = human_human_layout_scenes[
    0
]  # retained for back-compat

randomized_human_human_layouts = scene.RandomizeOrder(
    human_human_layout_scenes,
    keep_n=1,
)

# Feedback scene for multiplayer
multiplayer_feedback_scene = (
    static_scene.ScalesAndTextBox(
        pre_scale_header="",
        scale_questions=[
            "On a scale from 1-7, with 1 being detrimental and 7 being beneficial to your success, how effective was your partner as a teammate?",
            "On a scale from 1-7, with 1 being not at all and 7 being very much, rate how much you enjoyed playing the game with your partner.",
            "On a scale of 1-7, rate how much you think that your partner contributed to the success of your team. With 1 meaning they made your team worse off and 7 being that they made a very positive contribution.",
            "On a scale of 1-7, rate how much you think that you contributed to the success of your team. With 1 meaning you made your team worse off and 7 being you made a very positive contribution.",
            "On a scale from 1 to 7, where 1 is definitely a bot, 4 is unsure, and 7 is definitely a human, indicate how likely you think that your partner is a human or a bot build to play this game?",
        ],
        scale_labels=[
            [str(i + 1) for i in range(7)],
            [str(i + 1) for i in range(7)],
            [str(i + 1) for i in range(7)],
            [str(i + 1) for i in range(7)],
            [str(i + 1) for i in range(7)],
        ],
        text_box_header="Please provide any additional feedback you would like to share. If you had any technical issues with the task, please describe them here.",
        scale_size=7,
    )
    .scene(scene_id="multiplayer_feedback_scene", experiment_config={})
    .display(scene_header="Multiplayer Feedback")
)

# ============================================================================
# SCENE WRAPPERS
# ============================================================================

cramped_room_0 = scene.SceneWrapper(
    scenes=[cramped_room_sp_0, cramped_room_ibc_0, cramped_room_options_scene_0]
)


feedback_scene = static_scene.TextBox(
    text_box_header="If desired, please provide any additional feedback on your experience with this game. You will receive a completion code on the next page.",
    required=False,
).scene(
    scene_id="feedback_scene",
)


end_scene = (
    static_scene.CompletionCodeScene()
    .scene(
        scene_id="end_completion_code_scene",
        should_export_metadata=True,
        experiment_config={},
    )
    .display(
        scene_header="Thank you for participating!",
    )
)


# ============================================================================
# OVERCOOKED V2 (Gessler et al., partial observability)
# ============================================================================
# The cogrid 0.3.0 OvercookedV2 environments use ``local_view_radius=2`` so
# each agent observes only a 5x5 window centred on themselves. The render
# function in the env file produces an agent-centred viewport (option B from
# the design discussion): the canvas is exactly the 5x5 view, scrolling with
# the agent. Off-grid cells render as void; the partner is hidden when their
# cell falls outside the viewer's window.

_V2_TILE_SIZE = 60
_V2_VIEW_DIAM = 5  # 2 * local_view_radius + 1
_V2_CANVAS_PX = _V2_TILE_SIZE * _V2_VIEW_DIAM  # 300

overcooked_v2_test_time_simple_scene = (
    gym_scene.GymScene()
    .scene(scene_id="overcooked_v2_test_time_simple", experiment_config={})
    .policies(policy_mapping=HUMAN_HUMAN_POLICY_MAPPING)
    .rendering(
        fps=30,
        hud_text_fn=overcooked_utils.hud_text_fn,
        game_width=_V2_CANVAS_PX,
        game_height=_V2_CANVAS_PX,
        background="#0E0E0E",
    )
    .assets(
        assets_to_preload=overcooked_utils.overcooked_preload_assets_spec()
        + [
            # V2 mixed-soup frames live in soups.png — Phaser must preload
            # this atlas alongside the V1 set or pot renders for mixed
            # onion+tomato pots will silently fail.
            {
                "object_type": "atlas_spec",
                "name": "soups",
                "img_path": "examples/cogrid/assets/overcooked/sprites/soups.png",
                "atlas_path": "examples/cogrid/assets/overcooked/sprites/soups.json",
            },
        ],
    )
    .gameplay(
        default_action=Noop,
        action_mapping=action_mapping,
        num_episodes=3,
        max_steps=400,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .content(
        scene_header="OvercookedV2 - Test Time (Partial Observability)",
        scene_body=(
            "<center><p>"
            "You'll play OvercookedV2 with another participant. "
            "Each chef has a <b>limited 5x5 view</b> centred on themselves -- "
            "you can only see what's nearby. The recipe indicator (blue tile) "
            "shows which soup the kitchen is currently asking for; deliver "
            "the right soup to the green X to score, and avoid wrong "
            "deliveries (they lose points)."
            "<br><br>Press start to join the lobby and find a partner."
            "</p></center>"
        ),
        game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
        in_game_scene_body=overcooked_utils.overcooked_two_column_layout(
            "You and your partner each see only your own 5x5 surroundings."
            "<br>Communicate by where you stand and what you carry."
        ),
    )
    .waitroom(
        timeout=300000,  # 5 minutes
        timeout_message=(
            "Sorry, we could not find enough players for this study. Please "
            "return the HIT now. You will be paid through a Compensation HIT."
        ),
    )
    .runtime(
        environment_initialization_code_filepath=(
            "examples/cogrid/environments/overcooked_v2_test_time_simple.py"
        ),
        packages_to_install=["numpy", "cogrid==0.3.1", "opencv-python"],
    )
    .multiplayer(
        input_delay=3,
        matchmaker=FIFOMatchmaker(max_p2p_rtt_ms=100),
        hide_lobby_count=True,
        partner_disconnect_message=(
            "Your partner disconnected. The task will end here and you will "
            "be compensated for your performance so far. Please submit the "
            "completion code below."
        ),
        partner_disconnect_show_completion_code=True,
    )
)
