from __future__ import annotations

import eventlet
import copy

eventlet.monkey_patch()


from interactive_gym.configurations import (
    configuration_constants,
)
from interactive_gym.examples.cogrid import (
    overcooked_utils,
)
from interactive_gym.scenes import gym_scene
from interactive_gym.scenes import static_scene
from interactive_gym.scenes import scene


# Constants for controls/actions/etc.
MoveUp = 0
MoveDown = 1
MoveLeft = 2
MoveRight = 3
PickupDrop = 4
Toggle = 5
Noop = 6


SP_POLICY_MAPPING_CRAMPED_ROOM = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/sp_cramped_room_00.onnx",
}

IBC_POLICY_MAPPING_CRAMPED_ROOM = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/ibc_cramped_room_00.onnx",
}

SP_POLICY_MAPPING_ASYMMETRIC_ADVANTAGES = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/sp_asymmetric_advantages_00.onnx",
}

IBC_POLICY_MAPPING_ASYMMETRIC_ADVANTAGES = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/ibc_asymmetric_advantages_00.onnx",
}

SP_POLICY_MAPPING_COUNTER_CIRCUIT = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/sp_counter_circuit_00.onnx",
}

IBC_POLICY_MAPPING_COUNTER_CIRCUIT = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/ibc_counter_circuit_00.onnx",
}

SP_POLICY_MAPPING_FORCED_COORDINATION = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/sp_forced_coordination_00.onnx",
}

IBC_POLICY_MAPPING_FORCED_COORDINATION = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/ibc_forced_coordination_00.onnx",
}

SP_POLICY_MAPPING_COORDINATION_RING = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/sp_coordination_ring_00.onnx",
}

IBC_POLICY_MAPPING_COORDINATION_RING = {
    0: configuration_constants.PolicyTypes.Human,
    1: "static/assets/overcooked/models/ibc_coordination_ring_00.onnx",
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
        scene_body_filepath="interactive_gym/server/static/templates/overcooked_instructions.html",
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
        env_to_state_fn=overcooked_utils.overcooked_env_to_render_fn,
        assets_to_preload=overcooked_utils.overcooked_preload_assets_spec(),
        hud_text_fn=overcooked_utils.hud_text_fn,
        game_width=overcooked_utils.TILE_SIZE * 7,
        game_height=overcooked_utils.TILE_SIZE * 6,
        background="#e6b453",
    )
    .gameplay(
        default_action=Noop,
        action_mapping=action_mapping,
        num_episodes=1,
        max_steps=1000,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .user_experience(
        scene_header="Overcooked Tutorial",
        scene_body_filepath="interactive_gym/server/static/templates/overcooked_controls.html",
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
        game_page_html_fn=overcooked_utils.overcooked_game_page_header_fn,
    )
    .pyodide(
        run_through_pyodide=True,
        environment_initialization_code_filepath="interactive_gym/examples/cogrid/environments/tutorial_cramped_room_environment_initialization.py",
        packages_to_install=["numpy", "cogrid==0.0.15", "opencv-python"],
    )
)


cramped_room_sp_0 = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_sp_0", experiment_config={})
    .policies(policy_mapping=SP_POLICY_MAPPING_CRAMPED_ROOM, frame_skip=5)
    .rendering(
        fps=30,
        env_to_state_fn=overcooked_utils.overcooked_env_to_render_fn,
        assets_to_preload=overcooked_utils.overcooked_preload_assets_spec(),
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
    .user_experience(
        scene_header="Overcooked",
        scene_body="<center><p>"
        "You'll now play with a partner for a single round. "
        "This will be followed by a round with a different partner "
        "in the same environment layout."
        "<br><br> "
        "You will be playing on the layout pictured below. "
        '<center><img src="static/assets/overcooked/cramped_room.png" alt="Annotated Overcooked environment." height="270" width="315"></center>'
        "When the button activates, click it to begin. "
        "</p></center>",
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
    .pyodide(
        run_through_pyodide=True,
        environment_initialization_code_filepath="interactive_gym/examples/cogrid/environments/cramped_room_environment_initialization.py",
        packages_to_install=["numpy", "cogrid==0.0.15", "opencv-python"],
    )
)
cramped_room_ibc_0 = (
    copy.deepcopy(cramped_room_sp_0)
    .scene(scene_id="cramped_room_ibc_0", experiment_config={})
    .policies(policy_mapping=IBC_POLICY_MAPPING_CRAMPED_ROOM)
    .user_experience(
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
counter_circuit_sp_0 = (
    copy.deepcopy(cramped_room_sp_0)
    .scene(scene_id="counter_circuit_sp_0", experiment_config={})
    .pyodide(
        environment_initialization_code_filepath="interactive_gym/examples/cogrid/environments/counter_circuit_environment_initialization.py"
    )
    .user_experience(
        scene_header="Overcooked",
        scene_body="<center><p>"
        "You'll now play with a partner for a single round. "
        "This will be followed by a round with a different partner "
        "in the same environment layout."
        "<br><br> "
        "You will be playing on the layout pictured below. "
        '<center><img src="static/assets/overcooked/counter_circuit.png" alt="Annotated Overcooked environment." height="270" width="315"></center>'
        "When the button activates, click it to begin. "
        "</p></center>",
    )
    .rendering(
        game_width=overcooked_utils.TILE_SIZE * 9,
        game_height=overcooked_utils.TILE_SIZE * 7,
    )
    .policies(policy_mapping=SP_POLICY_MAPPING_COUNTER_CIRCUIT)
)
counter_circuit_ibc_0 = (
    copy.deepcopy(counter_circuit_sp_0)
    .scene(scene_id="counter_circuit_ibc_0", experiment_config={})
    .policies(policy_mapping=IBC_POLICY_MAPPING_COUNTER_CIRCUIT)
    .user_experience(
        scene_header="Overcooked",
        scene_body="<center><p>"
        "You'll now play another round on the same layout. "
        "After this round, you will provide your preference "
        "between the two partners you interacted with. "
        "When the button activates, click it to begin. "
        "</p></center>",
    )
)


counter_circuit_options_scene_0 = copy.deepcopy(
    cramped_room_options_scene_0
).scene(scene_id="counter_circuit_options_scene_0", experiment_config={})

forced_coordination_sp_0 = (
    copy.deepcopy(cramped_room_sp_0)
    .scene(scene_id="forced_coordination_sp_0", experiment_config={})
    .pyodide(
        environment_initialization_code_filepath="interactive_gym/examples/cogrid/environments/forced_coordination_environment_initialization.py"
    )
    .user_experience(
        scene_header="Overcooked",
        scene_body="<center><p>"
        "You'll now play with a partner for a single round. "
        "This will be followed by a round with a different partner "
        "in the same environment layout."
        "<br><br> "
        "You will be playing on the layout pictured below. "
        '<center><img src="static/assets/overcooked/forced_coordination.png" alt="Annotated Overcooked environment." height="270" width="315"></center>'
        "When the button activates, click it to begin. "
        "</p></center>",
    )
    .rendering(
        game_width=overcooked_utils.TILE_SIZE * 7,
        game_height=overcooked_utils.TILE_SIZE * 7,
    )
    .policies(policy_mapping=SP_POLICY_MAPPING_FORCED_COORDINATION)
)

forced_coordination_ibc_0 = (
    copy.deepcopy(forced_coordination_sp_0)
    .scene(scene_id="forced_coordination_ibc_0", experiment_config={})
    .policies(policy_mapping=IBC_POLICY_MAPPING_FORCED_COORDINATION)
    .user_experience(
        scene_header="Overcooked",
        scene_body="<center><p>"
        "You'll now play another round on the same layout. "
        "After this round, you will provide your preference "
        "between the two partners you interacted with. "
        "When the button activates, click it to begin. "
        "</p></center>",
    )
)


forced_coordination_options_scene_0 = copy.deepcopy(
    cramped_room_options_scene_0
).scene(scene_id="forced_coordination_options_scene_0", experiment_config={})
asymmetric_advantages_sp_0 = (
    copy.deepcopy(cramped_room_sp_0)
    .scene(scene_id="asymmetric_advantages_sp_0", experiment_config={})
    .pyodide(
        environment_initialization_code_filepath="interactive_gym/examples/cogrid/environments/asymmetric_advantages_environment_initialization.py"
    )
    .user_experience(
        scene_header="Overcooked",
        scene_body="<center><p>"
        "You'll now play with a partner for a single round. "
        "This will be followed by a round with a different partner "
        "in the same environment layout."
        "<br><br> "
        "You will be playing on the layout pictured below. "
        '<center><img src="static/assets/overcooked/asymmetric_advantages.png" alt="Annotated Overcooked environment." height="270" width="315"></center>'
        "When the button activates, click it to begin. "
        "</p></center>",
    )
    .rendering(
        game_width=overcooked_utils.TILE_SIZE * 11,
        game_height=overcooked_utils.TILE_SIZE * 7,
    )
    .policies(policy_mapping=SP_POLICY_MAPPING_ASYMMETRIC_ADVANTAGES)
)
asymmetric_advantages_ibc_0 = (
    copy.deepcopy(asymmetric_advantages_sp_0)
    .scene(scene_id="asymmetric_advantages_ibc_0", experiment_config={})
    .policies(policy_mapping=IBC_POLICY_MAPPING_ASYMMETRIC_ADVANTAGES)
    .user_experience(
        scene_header="Overcooked",
        scene_body="<center><p>"
        "You'll now play another round on the same layout. "
        "After this round, you will provide your preference "
        "between the two partners you interacted with. "
        "When the button activates, click it to begin. "
        "</p></center>",
    )
)


asymmetric_advantages_options_scene_0 = copy.deepcopy(
    cramped_room_options_scene_0
).scene(scene_id="asymmetric_advantages_options_scene_0", experiment_config={})

coordination_ring_sp_0 = (
    copy.deepcopy(cramped_room_sp_0)
    .scene(scene_id="coordination_ring_sp_0", experiment_config={})
    .pyodide(
        environment_initialization_code_filepath="interactive_gym/examples/cogrid/environments/coordination_ring_environment_initialization.py"
    )
    .user_experience(
        scene_header="Overcooked",
        scene_body="<center><p>"
        "You'll now play with a partner for a single round. "
        "This will be followed by a round with a different partner "
        "in the same environment layout."
        "<br><br> "
        "You will be playing on the layout pictured below. "
        '<center><img src="static/assets/overcooked/coordination_ring.png" alt="Annotated Overcooked environment." height="270" width="315"></center>'
        "When the button activates, click it to begin. "
        "</p></center>",
    )
    .rendering(
        game_width=overcooked_utils.TILE_SIZE * 7,
        game_height=overcooked_utils.TILE_SIZE * 7,
    )
    .policies(policy_mapping=SP_POLICY_MAPPING_COORDINATION_RING)
)

coordination_ring_ibc_0 = (
    copy.deepcopy(coordination_ring_sp_0)
    .policies(policy_mapping=IBC_POLICY_MAPPING_COORDINATION_RING)
    .scene(scene_id="coordination_ring_ibc_0", experiment_config={})
    .user_experience(
        scene_header="Overcooked",
        scene_body="<center><p>"
        "You'll now play another round on the same layout. "
        "After this round, you will provide your preference "
        "between the two partners you interacted with. "
        "When the button activates, click it to begin. "
        "</p></center>",
    )
)


coordination_ring_options_scene_0 = copy.deepcopy(
    cramped_room_options_scene_0
).scene(scene_id="coordination_ring_options_scene_0", experiment_config={})

HUMAN_HUMAN_POLICY_MAPPING = {
    0: configuration_constants.PolicyTypes.Human,
    1: configuration_constants.PolicyTypes.Human,
}

cramped_room_human_human = (
    gym_scene.GymScene()
    .scene(scene_id="cramped_room_hh", experiment_config={})
    .policies(policy_mapping=HUMAN_HUMAN_POLICY_MAPPING)
    .rendering(
        fps=30,
        env_to_state_fn=overcooked_utils.overcooked_env_to_render_fn,
        assets_to_preload=overcooked_utils.overcooked_preload_assets_spec(),
        hud_text_fn=overcooked_utils.hud_text_fn,
        game_width=overcooked_utils.TILE_SIZE * 7,
        game_height=overcooked_utils.TILE_SIZE * 6,
        background="#e6b453",
    )
    .gameplay(
        default_action=Noop,
        action_mapping=action_mapping,
        num_episodes=20,
        max_steps=1350,
        input_mode=configuration_constants.InputModes.SingleKeystroke,
    )
    .user_experience(
        scene_header="Overcooked - Multiplayer",
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
        waitroom_timeout=300000,  # 5 minutes
        waitroom_timeout_message="Sorry, we could not find enough players for this study. Please return the HIT now. You will be paid through a Compensation HIT.",
    )
    .pyodide(
        run_through_pyodide=True,
        multiplayer=True,  # Enable multiplayer Pyodide coordination
        environment_initialization_code_filepath="interactive_gym/examples/cogrid/environments/cramped_room_environment_initialization_hh.py",
        packages_to_install=["numpy", "cogrid==0.1.2", "opencv-python"],
        # Multiplayer sync settings (Action Queue with queue-based resync)
        state_broadcast_interval=15,  # Sync state every 300 frames (~10s at 30fps), None to disable
        server_authoritative=False,  # Server-authoritative mode
        input_delay=3,
    )
    .partner_disconnect_message_config(message="Your partner disconnected. The task will end here and you will be compensated for your performance so far. Please submit the completion code below.", show_completion_code=True)
)

counter_circuit_human_human = (
    copy.deepcopy(cramped_room_human_human)
    .scene(scene_id="counter_circuit_hh", experiment_config={})
    .pyodide(
        environment_initialization_code_filepath="interactive_gym/examples/cogrid/environments/counter_circuit_environment_initialization.py"
    )
    .user_experience(
        scene_body="<center><p>"
        "You'll now play with another human participant! "
        "Please wait in the lobby for your partner to join. "
        "<br><br> "
        "You will be playing on the layout pictured below. "
        '<center><img src="static/assets/overcooked/counter_circuit.png" alt="Annotated Overcooked environment." height="270" width="315"></center>'
        "Work together to prepare and deliver as many dishes as possible. "
        "</p></center>",
    )
    .rendering(
        game_width=overcooked_utils.TILE_SIZE * 9,
        game_height=overcooked_utils.TILE_SIZE * 7,
    )
)

forced_coordination_human_human = (
    copy.deepcopy(cramped_room_human_human)
    .scene(scene_id="forced_coordination_hh", experiment_config={})
    .pyodide(
        environment_initialization_code_filepath="interactive_gym/examples/cogrid/environments/forced_coordination_environment_initialization.py"
    )
    .user_experience(
        scene_body="<center><p>"
        "You'll now play with another human participant! "
        "Please wait in the lobby for your partner to join. "
        "<br><br> "
        "You will be playing on the layout pictured below. "
        '<center><img src="static/assets/overcooked/forced_coordination.png" alt="Annotated Overcooked environment." height="270" width="315"></center>'
        "Work together to prepare and deliver as many dishes as possible. "
        "</p></center>",
    )
    .rendering(
        game_width=overcooked_utils.TILE_SIZE * 7,
        game_height=overcooked_utils.TILE_SIZE * 7,
    )
)

asymmetric_advantages_human_human = (
    copy.deepcopy(cramped_room_human_human)
    .scene(scene_id="asymmetric_advantages_hh", experiment_config={})
    .pyodide(
        environment_initialization_code_filepath="interactive_gym/examples/cogrid/environments/asymmetric_advantages_environment_initialization.py"
    )
    .user_experience(
        scene_body="<center><p>"
        "You'll now play with another human participant! "
        "Please wait in the lobby for your partner to join. "
        "<br><br> "
        "You will be playing on the layout pictured below. "
        '<center><img src="static/assets/overcooked/asymmetric_advantages.png" alt="Annotated Overcooked environment." height="270" width="315"></center>'
        "Work together to prepare and deliver as many dishes as possible. "
        "</p></center>",
    )
    .rendering(
        game_width=overcooked_utils.TILE_SIZE * 11,
        game_height=overcooked_utils.TILE_SIZE * 7,
    )
)

coordination_ring_human_human = (
    copy.deepcopy(cramped_room_human_human)
    .scene(scene_id="coordination_ring_hh", experiment_config={})
    .pyodide(
        environment_initialization_code_filepath="interactive_gym/examples/cogrid/environments/coordination_ring_environment_initialization.py"
    )
    .user_experience(
        scene_body="<center><p>"
        "You'll now play with another human participant! "
        "Please wait in the lobby for your partner to join. "
        "<br><br> "
        "You will be playing on the layout pictured below. "
        '<center><img src="static/assets/overcooked/coordination_ring.png" alt="Annotated Overcooked environment." height="270" width="315"></center>'
        "Work together to prepare and deliver as many dishes as possible. "
        "</p></center>",
    )
    .rendering(
        game_width=overcooked_utils.TILE_SIZE * 7,
        game_height=overcooked_utils.TILE_SIZE * 7,
    )
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
            [str(i+1) for i in range(7)],
            [str(i+1) for i in range(7)],
            [str(i+1) for i in range(7)],
            [str(i+1) for i in range(7)],
            [str(i+1) for i in range(7)],
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
counter_circuit_0 = scene.SceneWrapper(
    scenes=[
        counter_circuit_sp_0,
        counter_circuit_ibc_0,
        counter_circuit_options_scene_0,
    ]
)
forced_coordination_0 = scene.SceneWrapper(
    scenes=[
        forced_coordination_sp_0,
        forced_coordination_ibc_0,
        forced_coordination_options_scene_0,
    ]
)
asymmetric_advantages_0 = scene.SceneWrapper(
    scenes=[
        asymmetric_advantages_sp_0,
        asymmetric_advantages_ibc_0,
        asymmetric_advantages_options_scene_0,
    ]
)
coordination_ring_0 = scene.SceneWrapper(
    scenes=[
        coordination_ring_sp_0,
        coordination_ring_ibc_0,
        coordination_ring_options_scene_0,
    ]
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
