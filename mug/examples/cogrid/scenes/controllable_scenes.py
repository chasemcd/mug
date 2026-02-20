from __future__ import annotations

import copy

import eventlet

eventlet.monkey_patch()


from mug.configurations import configuration_constants
from mug.examples.cogrid import overcooked_utils
from mug.scenes import gym_scene, scene, static_scene

SCENES_PER_SETTING = 1

LAYOUT_HEIGHT_WIDTHS = {
    "cramped_room": (6, 7),
    "counter_circuit": (7, 9),
    "forced_coordination": (7, 7),
    "asymmetric_advantages": (7, 11),
    "coordination_ring": (7, 7),
}


# Constants for controls/actions/etc.
MoveUp = 0
MoveDown = 1
MoveLeft = 2
MoveRight = 3
PickupDrop = 4
Toggle = 5
Noop = 6

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

IBC_POLICY_MAPPING_CRAMPED_ROOM = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/ibc_cramped_room_00.onnx",
}

IBC_POLICY_MAPPING_COUNTER_CIRCUIT = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/ibc_counter_circuit_00.onnx",
}

IBC_POLICY_MAPPING_FORCED_COORDINATION = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/ibc_forced_coordination_0.008tau_00.onnx",
}

IBC_POLICY_MAPPING_ASYMMETRIC_ADVANTAGES = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/ibc_asymmetric_advantages_00.onnx",
}

IBC_POLICY_MAPPING_COORDINATION_RING = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/ibc_coordination_ring_00.onnx",
}


POLICY_MAPPING_BY_LAYOUT = {
    "cramped_room": IBC_POLICY_MAPPING_CRAMPED_ROOM,
    "counter_circuit": IBC_POLICY_MAPPING_COUNTER_CIRCUIT,
    "forced_coordination": IBC_POLICY_MAPPING_FORCED_COORDINATION,
    "asymmetric_advantages": IBC_POLICY_MAPPING_ASYMMETRIC_ADVANTAGES,
    "coordination_ring": IBC_POLICY_MAPPING_COORDINATION_RING,
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
        scene_body_filepath="mug/server/static/templates/overcooked_controllable_instructions.html",
    )
)


on_game_step_code = """
import js
interactive_gym_globals = dict(js.window.interactiveGymGlobals.object_entries())
env.reward_weights[1] = {k: interactive_gym_globals.get(k, 0.0) for k in env.reward_weights[1].keys()}
"""
control_tutorial_scene = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_control_tutorial_0", experiment_config={})
    .policies(
        policy_mapping={
            0: "static/assets/overcooked/models/ibc_cramped_room_00.onnx",
            1: "static/assets/overcooked/models/ibc_cramped_room_00.onnx",
        },
        frame_skip=5,
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
        max_steps=2000,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .content(
        scene_header="Overcooked",
        scene_body_filepath="mug/examples/cogrid/html_pages/control_tutorial.html",
        game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
        in_game_scene_body_filepath="mug/examples/cogrid/html_pages/control_tutorial_in_game_body.html",
    )
    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath="mug/examples/cogrid/environments/cramped_room_controllable_tutorial_environment_initialization.py",
        on_game_step_code=on_game_step_code,
        packages_to_install=["numpy", "cogrid==0.0.15", "opencv-python"],
    )
)


tutorial_with_bot_scene = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_with_bot_tutorial_0", experiment_config={})
    .policies(policy_mapping=IBC_POLICY_MAPPING_CRAMPED_ROOM, frame_skip=5)
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
        max_steps=1350,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .content(
        scene_header="Overcooked",
        scene_body="""
        <center><p>
        You'll now try playing with a partner for a single practice round.
        <br><br>
        You will be playing on the layout pictured below.
        <center><img src="static/assets/overcooked/cramped_room.png" alt="Annotated Overcooked environment." height="270" width="315"></center>

        <div style="display: flex; justify-content: center; align-items: center; gap: 40px; margin: 20px 0;">
        <div style="text-align: center;">
            <img src="static/assets/overcooked/blue_chef.png" alt="Chef with blue hat." width="24" height="32">
            <p style="margin: 5px 0;">Your Chef</p>
        </div>
        <div style="text-align: center;">
            <img src="static/assets/overcooked/green_chef.png" alt="Chef with green hat." width="24" height="32">
            <p style="margin: 5px 0;">AI Chef</p>
        </div>
    </div>

        When the button activates, click it to begin.
        </p></center>
        """,
        game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
        in_game_scene_body="""
        <center>
        <p>
        Use the arrow keys <img src="static/assets/keys/arrow_keys_2.png" alt="Keyboard arrow keys" height="24" width="20" style="vertical-align:middle;">
        to control your chef <img src="static/assets/overcooked/blue_chef.png" alt="Blue Chef" height="24" width="24" style="vertical-align:middle;">
        and press <img src="static/assets/keys/icons8-w-key-50.png" alt="W key" height="24" width="24" style="vertical-align:middle;"> to pick up and
        drop objects. Try to deliver as many dishes as possible by combining onions in the pot, plating the cooked onions,
        and delivering them to the grey delivery zone.
        </p>
        </center>
        <br><br>
        """,
    )
    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath="mug/examples/cogrid/environments/cramped_room_environment_initialization.py",
        packages_to_install=["numpy", "cogrid==0.0.15", "opencv-python"],
    )
)


end_tutorial_static_scene = (
    static_scene.StaticScene()
    .scene(scene_id="end_tutorial_static_scene", experiment_config={})
    .display(
        scene_header="Tutorial Complete",
        scene_body="You've completed the tutorial! All rounds after this will be part of the main study and all points earned will count towards your bonus.",
    )
)


base_controllable_ = (
    gym_scene.GymScene()
    .scene(scene_id="base_controllable", experiment_config={})
    .policies(policy_mapping=IBC_POLICY_MAPPING_CRAMPED_ROOM, frame_skip=5)
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
        max_steps=1350,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .content(
        scene_header="Overcooked",
        scene_body_filepath="mug/examples/cogrid/html_pages/controllable_cramped_room.html",
        game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
        in_game_scene_body="""
        <center>
        <p>
        Use the arrow keys <img src="static/assets/keys/arrow_keys_2.png" alt="Keyboard arrow keys" height="24" width="20" style="vertical-align:middle;">
        to control your chef <img src="static/assets/overcooked/blue_chef.png" alt="Blue Chef" height="24" width="24" style="vertical-align:middle;">
        and press <img src="static/assets/keys/icons8-w-key-50.png" alt="W key" height="24" width="24" style="vertical-align:middle;"> to pick up and
        drop objects. Try to deliver as many dishes as possible by combining onions in the pot, plating the cooked onions,
        and delivering them to the grey delivery zone.
        </p>
        <div style="border: 1px solid black; padding: 10px; display: inline-block;">
            <p style="margin: 0 0 5px 0; font-weight: bold;">Current AI Partner Behavior Settings</p>
            <p id="reward-status" style="margin: 0;"></p>
        </div>
        <script>
            function getControlText(value) {
                if (value === -1) return "<span style='color: red'>Discourage</span>";
                if (value === 1) return "<span style='color: green'>Encourage</span>";
                if (value === 0) return "<span style='color: #b3a600'>Neutral</span>";
                return value;
            }


            document.getElementById('reward-status').innerHTML =
                "Delivering Dishes: " + getControlText(window.interactiveGymGlobals.delivery_act_reward) + ", " +
                "Onions in Pot: " + getControlText(window.interactiveGymGlobals.onion_in_pot_reward);
        </script>
        </center>
        """,
    )
    .runtime(
        run_through_pyodide=True,
        environment_initialization_code_filepath="mug/examples/cogrid/environments/cramped_room_controllable_environment_initialization.py",
        packages_to_install=["numpy", "cogrid==0.0.15", "opencv-python"],
    )
)
base_controllable_eval_ = (
    static_scene.ScalesAndTextBox(
        scale_questions=[
            "My partner followed its behavior settings.",
            "My partner was enjoyable to work with.",
            "My partner's behavior was predictable.",
            "My partner was effective as a teammate.",
            "My ability to control my partner's behavior made it, as a teammate:",
            "My ability to control my partner's behavior made it, as a teammate:",
        ],
        scale_labels=[
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Less Effective", "No Difference", "More Effective"],
            ["Less Predictable", "No Difference", "More Predictable"],
        ],
        pre_scale_header="Please indicate your responses to the following statements about your partner in the previous round.",
        text_box_header="Please describe any additional reasoning for your selections. This might include specific actions or behaviors. You may write N/A if you do not have any anything to add.",
    )
    .scene(scene_id="base_controllable_eval_", experiment_config={})
    .display(scene_subheader="Feedback About Your AI Partner")
)


base_fixed_ = (
    copy.deepcopy(base_controllable_)
    .scene(scene_id="base_fixed_", experiment_config={})
    .policies(policy_mapping=IBC_POLICY_MAPPING_CRAMPED_ROOM, frame_skip=5)
    .content(
        scene_body_filepath="mug/examples/cogrid/html_pages/fixed_cramped_room.html",
    )
)
base_fixed_eval_ = (
    static_scene.ScalesAndTextBox(
        scale_questions=[
            "My partner followed its behavior settings.",
            "My partner was enjoyable to work with.",
            "My partner's behavior was predictable.",
            "My partner was effective as a teammate.",
            "My inability to control my partner's behavior made it, as a teammate:",
            "My inability to control my partner's behavior made it, as a teammate:",
        ],
        scale_labels=[
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Less Effective", "No Difference", "More Effective"],
            ["Less Predictable", "No Difference", "More Predictable"],
        ],
        pre_scale_header="Please indicate your responses to the following statements about your partner in the previous round.",
        text_box_header="Please describe any additional reasoning for your selections. This might include specific actions or behaviors. You may write N/A if you do not have any anything to add.",
    )
    .scene(scene_id="cramped_room_fixed_eval_", experiment_config={})
    .display(scene_subheader="Feedback About Your AI Partner")
)


base_nospec_ = (
    copy.deepcopy(base_controllable_)
    .scene(scene_id="base_nospec_", experiment_config={})
    .content(
        in_game_scene_body="""
        <center>
        <p>
        Use the arrow keys <img src="static/assets/keys/arrow_keys_2.png" alt="Keyboard arrow keys" height="24" width="20" style="vertical-align:middle;">
        to control your chef <img src="static/assets/overcooked/blue_chef.png" alt="Blue Chef" height="24" width="24" style="vertical-align:middle;">
        and press <img src="static/assets/keys/icons8-w-key-50.png" alt="W key" height="24" width="24" style="vertical-align:middle;"> to pick up and
        drop objects. Try to deliver as many dishes as possible by combining onions in the pot, plating the cooked onions,
        and delivering them to the grey delivery zone.
        </p>
        </center>
        """,
    )
)
base_nospec_eval_ = (
    static_scene.ScalesAndTextBox(
        scale_questions=[
            "My partner was enjoyable to work with.",
            "My partner's behavior was predictable.",
            "My partner was effective as a teammate.",
            "My inability to control my partner's behavior made it, as a teammate:",
            "My inability to control my partner's behavior made it, as a teammate:",
        ],
        scale_labels=[
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Less Effective", "No Difference", "More Effective"],
            ["Less Predictable", "No Difference", "More Predictable"],
        ],
        pre_scale_header="Please indicate your responses to the following statements about your partner in the previous round.",
        text_box_header="Please describe any additional reasoning for your selections. This might include specific actions or behaviors. You may write N/A if you do not have any anything to add.",
    )
    .scene(scene_id="base_nospec_eval_", experiment_config={})
    .display(scene_subheader="Feedback About Your AI Partner")
)


base_choice_ = (
    copy.deepcopy(base_controllable_)
    .scene(scene_id="base_choice_", experiment_config={})
    .content(
        in_game_scene_body="""
        <center>
        <p>
        Use the arrow keys <img src="static/assets/keys/arrow_keys_2.png" alt="Keyboard arrow keys" height="24" width="20" style="vertical-align:middle;">
        to control your chef <img src="static/assets/overcooked/blue_chef.png" alt="Blue Chef" height="24" width="24" style="vertical-align:middle;">
        and press <img src="static/assets/keys/icons8-w-key-50.png" alt="W key" height="24" width="24" style="vertical-align:middle;"> to pick up and
        drop objects. Try to deliver as many dishes as possible by combining onions in the pot, plating the cooked onions,
        and delivering them to the grey delivery zone.
        </p>
        <div id="behavior-settings" style="border: 1px solid black; padding: 10px; display: inline-block;">
            <p style="margin: 0 0 5px 0; font-weight: bold;">Current AI Partner Behavior Settings</p>
            <p id="reward-status" style="margin: 0;"></p>
        </div>
        <script>
            function getControlText(value) {
                if (value === -1) return "<span style='color: red'>Discourage</span>";
                if (value === 1) return "<span style='color: green'>Encourage</span>";
                if (value === 0) return "<span style='color: #b3a600'>Neutral</span>";
                return value;
            }

            if (window.interactiveGymGlobals.partner_mode === "noSpec") {
                document.getElementById('behavior-settings').style.display = 'none';
            } else {
                document.getElementById('reward-status').innerHTML =
                    "Delivering Dishes: " + getControlText(window.interactiveGymGlobals.delivery_act_reward) + ", " +
                    "Onions in Pot: " + getControlText(window.interactiveGymGlobals.onion_in_pot_reward);
            }
        </script>
        </center>
        """,
    )
)


def make_n_controllable_scenes(layout_name, n):
    n_controllable_scenes = []
    h, w = LAYOUT_HEIGHT_WIDTHS[layout_name]
    for i in range(n):
        controllable_scene_ = copy.deepcopy(base_controllable_)
        controllable_scene = (
            controllable_scene_.scene(
                scene_id=f"{layout_name}_controllable_{i}",
                experiment_config={},
            )
            .runtime(
                environment_initialization_code_filepath=f"mug/examples/cogrid/environments/{layout_name}_controllable_environment_initialization.py",
            )
            .content(
                scene_body_filepath=f"mug/examples/cogrid/html_pages/controllable_{layout_name}.html",
            )
            .rendering(
                game_width=overcooked_utils.TILE_SIZE * w,
                game_height=overcooked_utils.TILE_SIZE * h,
            )
            .policies(policy_mapping=POLICY_MAPPING_BY_LAYOUT[layout_name])
        )

        eval_scene = copy.deepcopy(base_controllable_eval_).scene(
            scene_id=f"{layout_name}_controllable_eval_{i}",
            experiment_config={},
        )

        n_controllable_scenes.append(
            scene.SceneWrapper([controllable_scene, eval_scene])
        )

    return n_controllable_scenes


def make_n_fixed_scenes(layout_name, n):
    n_fixed_scenes = []
    h, w = LAYOUT_HEIGHT_WIDTHS[layout_name]
    for i in range(n):
        controllable_scene_ = copy.deepcopy(base_controllable_)
        controllable_scene = (
            controllable_scene_.scene(
                scene_id=f"{layout_name}_fixed_{i}",
                experiment_config={},
            )
            .runtime(
                environment_initialization_code_filepath=f"mug/examples/cogrid/environments/{layout_name}_controllable_environment_initialization.py",
            )
            .content(
                scene_body_filepath=f"mug/examples/cogrid/html_pages/fixed_{layout_name}.html",
            )
            .policies(policy_mapping=POLICY_MAPPING_BY_LAYOUT[layout_name])
            .rendering(
                game_width=overcooked_utils.TILE_SIZE * w,
                game_height=overcooked_utils.TILE_SIZE * h,
            )
        )

        eval_scene = copy.deepcopy(base_fixed_eval_).scene(
            scene_id=f"{layout_name}_fixed_eval_{i}",
            experiment_config={},
        )

        n_fixed_scenes.append(
            scene.SceneWrapper([controllable_scene, eval_scene])
        )

    return n_fixed_scenes


def make_n_nospec_scenes(layout_name, n):
    n_nospec_scenes = []
    h, w = LAYOUT_HEIGHT_WIDTHS[layout_name]
    for i in range(n):
        nospec_scene = copy.deepcopy(base_nospec_)
        nospec_scene = (
            nospec_scene.scene(
                scene_id=f"{layout_name}_nospec_{i}",
                experiment_config={},
            )
            .runtime(
                environment_initialization_code_filepath=f"mug/examples/cogrid/environments/{layout_name}_controllable_environment_initialization.py",
            )
            .content(
                scene_body_filepath=f"mug/examples/cogrid/html_pages/nospec_{layout_name}.html",
            )
            .policies(policy_mapping=POLICY_MAPPING_BY_LAYOUT[layout_name])
            .rendering(
                game_width=overcooked_utils.TILE_SIZE * w,
                game_height=overcooked_utils.TILE_SIZE * h,
            )
        )

        eval_scene = copy.deepcopy(base_nospec_eval_).scene(
            scene_id=f"{layout_name}_nospec_eval_{i}",
            experiment_config={},
        )

        n_nospec_scenes.append(scene.SceneWrapper([nospec_scene, eval_scene]))

    return n_nospec_scenes


def make_choice_scene(layout_name):
    h, w = LAYOUT_HEIGHT_WIDTHS[layout_name]
    return (
        copy.deepcopy(base_choice_)
        .scene(
            scene_id=f"{layout_name}_choice_0",
            experiment_config={},
        )
        .policies(policy_mapping=POLICY_MAPPING_BY_LAYOUT[layout_name])
        .content(
            scene_body_filepath=f"mug/examples/cogrid/html_pages/choice_{layout_name}.html",
        )
        .runtime(
            environment_initialization_code_filepath=f"mug/examples/cogrid/environments/{layout_name}_controllable_environment_initialization.py",
        )
        .rendering(
            game_width=overcooked_utils.TILE_SIZE * w,
            game_height=overcooked_utils.TILE_SIZE * h,
        )
    )


SCENES_BY_LAYOUT = {}
for layout_name in [
    "cramped_room",
    "counter_circuit",
    "forced_coordination",
    "asymmetric_advantages",
    "coordination_ring",
]:
    controllable_scenes = make_n_controllable_scenes(
        layout_name, SCENES_PER_SETTING
    )
    fixed_scenes = make_n_fixed_scenes(layout_name, SCENES_PER_SETTING)
    nospec_scenes = make_n_nospec_scenes(layout_name, SCENES_PER_SETTING)
    randomized_game_scenes = scene.RandomizeOrder(
        [*controllable_scenes, *fixed_scenes, *nospec_scenes]
    )

    choice_scene = make_choice_scene(layout_name)

    SCENES_BY_LAYOUT[layout_name] = scene.SceneWrapper(
        [randomized_game_scenes, choice_scene]
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
