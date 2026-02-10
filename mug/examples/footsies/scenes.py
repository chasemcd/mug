from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse
import copy
from interactive_gym.server import app
from interactive_gym.scenes import scene
from interactive_gym.scenes import stager
from interactive_gym.scenes import static_scene

from interactive_gym.configurations import experiment_config
from interactive_gym.scenes import unity_scene
from interactive_gym.scenes import static_scene
from interactive_gym.scenes import scene

from interactive_gym.configurations import (
    configuration_constants,
)
from interactive_gym.examples.footsies import footsies_scene


FOOTSIES_BUILD_NAME = "footsies_webgl_47f26fc"
BONUS_PER_WIN = 0.20

# Define the start scene, which is the landing page for participants.
start_scene = (
    static_scene.StartScene()
    .scene(
        scene_id="footsies_start_scene",
        experiment_config={},
        should_export_metadata=True,
    )
    .display(
        scene_header="Welcome",
        scene_body_filepath="interactive_gym/examples/footsies/static/introduction.html",
    )
)


footsies_initial_survey_scene = (
    static_scene.ScalesAndTextBox(
        scale_questions=[
            "I play video games frequently.",
            "I have experience playing fighting games (Street Fighter, Tekken, etc.).",
            "I know the fundamental strategies of fighting games.",
        ],
        pre_scale_header="",
        scale_labels=[
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
        ],
        text_box_header="Please leave any additional comments about your experience with fighting games. Write N/A if you do not have anything to add.",
        scale_size=7,
    )
    .scene(scene_id="footsies_initial_survey_0", experiment_config={})
    .display(scene_subheader="Initial Survey")
)


footsies_tutorial_scene = (
    static_scene.StaticScene()
    .scene("footsies_tutorial_scene")
    .display(
        scene_header="Footsies Tutorial",
        scene_body_filepath="interactive_gym/examples/footsies/static/tutorial_static.html",
    )
)

CONTROLS_SUBHEADER = """ 
        <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px; color: #000;">
        <p style="margin: 10px;">
        MOVE WITH <img src="static/assets/keys/icons8-a-key-50.png" alt="A key" height="24" width="24" style="vertical-align:middle;"> AND <img src="static/assets/keys/icons8-d-key-50.png" alt="D key" height="24" width="24" style="vertical-align:middle;">
        </p>
        <p style="margin: 5px;">
        ATTACK WITH THE SPACE BAR <img src="static/assets/keys/icons8-space-key-50.png" alt="Space key" height="24" width="24" style="vertical-align:middle;">
        </p>
        </div>
"""


EPISODES_SCALE_DOWN = 1


footsies_initial_challenge_intro = (
    static_scene.StaticScene()
    .display(
        scene_header="Footsies",
        scene_body=f"""
    <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px;">
        <p>
        You'll now play 10 "initial challenge" rounds against a CPU opponent. This is your first opportunity to earn a bonus and <span style="color: red;">you'll earn ${BONUS_PER_WIN:.2f} for each win</span>.
        <br>
        <br>
        When the game loads on the next screen, click "vs CPU" to start.
        </p>
    </div>
    """,
    )
    .scene(scene_id="footsies_initial_challenge_intro", experiment_config={})
)


footsies_initial_challenge_scene = (
    footsies_scene.FootsiesScene()
    .display(
        scene_header="Footsies",
        scene_subheader="""
        <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px;">
            <p style="color: #000; text-shadow: 2px 2px #FFF; margin: 5px;">INITIAL CHALLENGE</p>
        </div>
        """
        + CONTROLS_SUBHEADER,
    )
    .scene(scene_id="footsies_initial_challenge", experiment_config={})
    .webgl(
        build_name=FOOTSIES_BUILD_NAME,
        height=1080 / 3,
        width=1960 / 3,
        preload_game=True,
    )
    .game(
        num_episodes=10 // EPISODES_SCALE_DOWN,
        score_fn=lambda data: int(data["winner"] == "P1"),
    )
    .set_opponent_sequence(
        [
            footsies_scene.OpponentConfig(
                model_path="4fs-16od-13c7f7b-0.05to0.01-sp-00",
                frame_skip=4,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.0,
            ),
            footsies_scene.OpponentConfig(
                model_path="4fs-16od-13c7f7b-0.05to0.01-sp-01",
                frame_skip=4,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.0,
            ),
            footsies_scene.OpponentConfig(
                model_path="4fs-16od-13c7f7b-0.05to0.01-sp-02",
                frame_skip=4,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.0,
            ),
            footsies_scene.OpponentConfig(
                model_path="4fs-16od-13c7f7b-0.05to0.01-sp-03",
                frame_skip=4,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.0,
            ),
            footsies_scene.OpponentConfig(
                model_path="4fs-16od-082992f-0.03to0.01-sp",
                frame_skip=4,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.0,
            ),
            footsies_scene.OpponentConfig(
                model_path="4fs-16od-13c7f7b-0.05to0.01-sp-00",
                frame_skip=8,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.2,
            ),
            footsies_scene.OpponentConfig(
                model_path="4fs-16od-13c7f7b-0.05to0.01-sp-01",
                frame_skip=8,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.2,
            ),
            footsies_scene.OpponentConfig(
                model_path="4fs-16od-13c7f7b-0.05to0.01-sp-02",
                frame_skip=8,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.2,
            ),
            footsies_scene.OpponentConfig(
                model_path="4fs-16od-13c7f7b-0.05to0.01-sp-03",
                frame_skip=8,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.2,
            ),
            footsies_scene.OpponentConfig(
                model_path="4fs-16od-082992f-0.03to0.01-sp",
                frame_skip=8,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.2,
            ),
        ],
        randomize=True,
    )
)


footsies_initial_challenge_survey_scene = (
    static_scene.ScalesAndTextBox(
        scale_questions=[
            "I enjoyed playing against the initial challenge opponent.",
            "The initial challenge CPU felt...",
        ],
        pre_scale_header="",
        scale_labels=[
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Too Easy to Beat", "Evenly Matched", "Too Hard to Beat"],
        ],
        text_box_header="Please describe any additional reasoning for your selections. You may write N/A if you do not have any anything to add.",
        scale_size=7,
    )
    .scene(scene_id="footsies_initial_challenge_survey_0", experiment_config={})
    .display(scene_subheader="Feedback About Your CPU Training Partner")
)


footsies_training_scene_intro = (
    static_scene.StaticScene()
    .display(
        scene_header="Footsies",
        scene_body="""
    <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px;">
        <p>You'll now play 45 rounds against a CPU training partner. Remember, your goal is to build up your skill as much as 
        possible to maximize your bonus in the final challenge rounds. <span style="color: red;">You will not earn a bonus for winning in these rounds</span>. 
        
        <br>
        <br>
        When the game loads on the next screen, click "vs CPU" to start.
        
        </p>
    </div>
    """,
    )
    .scene(scene_id="footsies_training_scene_intro", experiment_config={})
)

footsies_fixed_high_skill_rounds = (
    footsies_scene.FootsiesScene()
    .display(
        scene_header="Footsies",
        scene_subheader="""
        <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px;">
            <p style="color: #000; text-shadow: 2px 2px #FFF; margin: 5px;">TRAINING ROUNDS</p>
        </div>
        """
        + CONTROLS_SUBHEADER,
    )
    .scene(scene_id="footsies_high_skill", experiment_config={})
    .webgl(
        build_name=FOOTSIES_BUILD_NAME,
        height=1080 / 3,
        width=1960 / 3,
        preload_game=True,
    )
    .game(
        num_episodes=45 // EPISODES_SCALE_DOWN,
        score_fn=lambda data: int(data["winner"] == "P1"),
    )
    .set_opponent_sequence(
        [
            footsies_scene.OpponentConfig(
                model_path="4sf-16od-1c73fcc-0.03to0.01-500m-00",
                frame_skip=4,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.0,
            )
        ]
    )
)

footsies_high_skill_rounds = scene.SceneWrapper(
    [footsies_training_scene_intro, footsies_fixed_high_skill_rounds]
)


footsies_fixed_low_skill_rounds = (
    footsies_scene.FootsiesScene()
    .display(
        scene_header="Footsies",
        scene_subheader="""
        <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px;">
            <p style="color: #000; text-shadow: 2px 2px #FFF; margin: 5px;">TRAINING ROUNDS</p>
        </div>
        """
        + CONTROLS_SUBHEADER,
    )
    .scene(scene_id="footsies_low_skill", experiment_config={})
    .webgl(
        build_name=FOOTSIES_BUILD_NAME,
        height=1080 / 3,
        width=1960 / 3,
        preload_game=True,
    )
    .game(
        num_episodes=45 // EPISODES_SCALE_DOWN,
        score_fn=lambda data: int(data["winner"] == "P1"),
    )
    .set_opponent_sequence(
        [
            footsies_scene.OpponentConfig(
                model_path="4sf-16od-1c73fcc-0.03to0.01-500m-00",
                frame_skip=24,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.6,
            ),
        ]
    )
)

footsies_low_skill_rounds = scene.SceneWrapper(
    [footsies_training_scene_intro, footsies_fixed_low_skill_rounds]
)


footsies_fixed_empowerment_rounds = (
    copy.deepcopy(footsies_fixed_high_skill_rounds)
    .scene(scene_id="footsies_fixed_empowerment", experiment_config={})
    .set_opponent_sequence(
        [
            footsies_scene.OpponentConfig(
                model_path="esr-0.5alpha-00",
                frame_skip=4,
                obs_delay=16,
                inference_cadence=4,
                softmax_temperature=1.0,
            )
        ]
    )
)

footsies_empowerment_rounds = scene.SceneWrapper(
    [footsies_training_scene_intro, footsies_fixed_empowerment_rounds]
)


footsies_dynamic_empowerment_scene = (
    footsies_scene.FootsiesDynamicEmpowermentScene()
    .scene(scene_id="footsies_dynamic_empowerment", experiment_config={})
    .display(
        scene_header="Footsies",
        scene_subheader="""
        <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px;">
            <p style="color: #000; text-shadow: 2px 2px #FFF; margin: 5px;">TRAINING ROUNDS</p>
        </div>
        """
        + CONTROLS_SUBHEADER,
    )
    .scene(scene_id="footsies_dynamic_empowerment", experiment_config={})
    .webgl(
        build_name=FOOTSIES_BUILD_NAME,
        height=1080 / 3,
        width=1960 / 3,
        preload_game=True,
    )
    .game(
        num_episodes=45 // EPISODES_SCALE_DOWN,
        score_fn=lambda data: int(data["winner"] == "P1"),
    )
)

footsies_dynamic_empowerment_rounds = scene.SceneWrapper(
    [footsies_training_scene_intro, footsies_dynamic_empowerment_scene]
)

footsies_dynamic_difficulty_scene = (
    footsies_scene.FootsiesDynamicDifficultyScene()
    .display(
        scene_header="Footsies",
        scene_subheader="""
        <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px;">
            <p style="color: #000; text-shadow: 2px 2px #FFF; margin: 5px;">TRAINING ROUNDS</p>
        </div>
        """
        + CONTROLS_SUBHEADER,
    )
    .scene(scene_id="footsies_dynamic_difficulty", experiment_config={})
    .webgl(
        build_name=FOOTSIES_BUILD_NAME,
        height=1080 / 3,
        width=1960 / 3,
        preload_game=True,
    )
    .game(
        num_episodes=45 // EPISODES_SCALE_DOWN,
        score_fn=lambda data: int(data["winner"] == "P1"),
    )
)

footsies_dynamic_difficulty_rounds = scene.SceneWrapper(
    [footsies_training_scene_intro, footsies_dynamic_difficulty_scene]
)


footsies_random_difficulty_scene = (
    footsies_scene.FootsiesRandomDifficultyScene()
    .display(
        scene_header="Footsies",
        scene_subheader="""
        <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px;">
            <p style="color: #000; text-shadow: 2px 2px #FFF; margin: 5px;">TRAINING ROUNDS</p>
        </div>
        """
        + CONTROLS_SUBHEADER,
    )
    .scene(scene_id="footsies_random_difficulty", experiment_config={})
    .webgl(
        build_name=FOOTSIES_BUILD_NAME,
        height=1080 / 3,
        width=1960 / 3,
        preload_game=True,
    )
    .game(
        num_episodes=45 // EPISODES_SCALE_DOWN,
        score_fn=lambda data: int(data["winner"] == "P1"),
    )
)

footsies_random_difficulty_rounds = scene.SceneWrapper(
    [footsies_training_scene_intro, footsies_random_difficulty_scene]
)


footsies_controllable_difficulty_scene_intro = static_scene.StaticScene().display(
    scene_header="Footsies",
    scene_body="""
    <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px;">
        <p>You'll now play 45 rounds against a CPU training partner. You will be able to control the difficulty by using the slider on the next page. Remember, your goal is to build up your skill as much as 
        possible to maximize your bonus in the final challenge rounds. <span style="color: red;">You will not earn a bonus for winning in these rounds</span> 
        <br>
        <br>
        When the game loads on the next screen, click "vs CPU" to start.
        </p>
    </div>
    """,
)

footsies_controllable_difficulty_scene = (
    footsies_scene.FootsiesControllableDifficultyScene()
    .display(
        scene_header="Footsies",
        scene_subheader="""
        <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px;">
            <p style="color: #000; text-shadow: 2px 2px #FFF; margin: 5px;">TRAINING ROUNDS</p>
        </div>
        """
        + CONTROLS_SUBHEADER,
        scene_body_filepath="interactive_gym/examples/footsies/static/controllable_difficulty.html",
    )
    .scene(scene_id="footsies_controllable_difficulty", experiment_config={})
    .webgl(
        build_name=FOOTSIES_BUILD_NAME,
        height=1080 / 3,
        width=1960 / 3,
        preload_game=True,
    )
    .game(
        num_episodes=45 // EPISODES_SCALE_DOWN,
        score_fn=lambda data: int(data["winner"] == "P1"),
    )
)


footsies_controllable_difficulty_rounds = scene.SceneWrapper(
    [
        footsies_controllable_difficulty_scene_intro,
        footsies_controllable_difficulty_scene,
    ]
)


footsies_training_survey_scene = (
    static_scene.ScalesAndTextBox(
        scale_questions=[
            "My skills improved over the course of playing with my training partner.",
            "I learned new strategies from my training partner.",
            "I enjoyed playing against my training partner.",
            "I was motivated to beat my training partner.",
            "My training partner felt...",
        ],
        pre_scale_header="",
        scale_labels=[
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Too Easy to Beat", "Evenly Matched", "Too Hard to Beat"],
        ],
        text_box_header="Please describe the general strategy you've learned from your training partner. What is your approach to winning?",
        scale_size=7,
    )
    .scene(scene_id="footsies_training_survey", experiment_config={})
    .display(
        scene_subheader="Feedback About Your CPU Training Partner",
        scene_header="Training Survey 1/2",
    )
)

footsies_mc_survey = (
    static_scene.MultipleChoice(
        pre_questions_header="""
    In this survey, we'll ask about what you learned about the game. Specifically in how controls result in particular actions in the game. Please select all that apply for each option. 
    You will earn an aditional bonus of $0.10 for each question that you answer correctly.
    <br>
    <br>
    The answer correspond to key press sequence or single pressses. For example 
    <img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'> -> <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>
    means pressing the "D" key followed by the space bar. On the other hand, <img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> means
    pressing the "D" key and the space bar at the same time. 
    """,
        questions=[
            "What key press(es) result in this movement?",
            "What key press(es) result in this movement?",
            "What key press(es) result in this attack?",
            "What key press(es) result in this attack?",
            "What key press(es) result in this attack?",
            "What key press(es) result in this attack?",
            "What key press(es) result in this attack?",
            "What key press(es) result in this attack?",
        ],
        choices=[
            [
                "<img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'> -> <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'> -> <img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'> (Held then released)",
                "<img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'> -> <img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> -> <img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'>",
            ],
            [
                "<img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'> -> <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'> -> <img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'> (Held then released)",
                "<img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'> -> <img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> -> <img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'>",
            ],
            [
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released)",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released) + <img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released) + <img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
            ],
            [
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released)",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released) + <img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released) + <img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
            ],
            [
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released)",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released) + <img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released) + <img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
            ],
            [
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released)",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released) + <img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released) + <img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
            ],
            [
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released)",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released) + <img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released) + <img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
            ],
            [
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released)",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released) + <img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'> (Held then released) + <img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-d-key-50.png' alt='D key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
                "<img src='static/assets/keys/icons8-a-key-50.png' alt='A key' height='24' width='24' style='vertical-align:middle;'> + <img src='static/assets/keys/icons8-space-key-50.png' alt='Space key' height='24' width='24' style='vertical-align:middle;'>",
            ],
        ],
        images=[
            "static/assets/footsies/gifs/backward_dash.gif",
            "static/assets/footsies/gifs/forward_dash.gif",
            "static/assets/footsies/gifs/kick_ko.gif",
            "static/assets/footsies/gifs/kick_no_ko.gif",
            "static/assets/footsies/gifs/knee_no_ko.gif",
            "static/assets/footsies/gifs/low_kick.gif",
            "static/assets/footsies/gifs/uppercut_miss.gif",
            "static/assets/footsies/gifs/uppercut.gif",
        ],
        multi_select=True,
    )
    .display(scene_header="Training Survey 2/2")
    .scene(scene_id="footsies_mc_survey", experiment_config={})
)

footsies_final_challenge_intro = (
    static_scene.StaticScene()
    .display(
        scene_header="Footsies",
        scene_body=f"""
    <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px;">
        <p>
        You'll now play 10 "final challenge" rounds against a CPU opponent. This is your final opportunity to earn a bonus and <span style="color: red;">you'll earn ${BONUS_PER_WIN:.2f} for each win</span>.
        <br>
        <br>
        When the game loads on the next screen, click "vs CPU" to start.
        </p>
    </div>
    """,
    )
    .scene(scene_id="footsies_final_challenge_intro", experiment_config={})
)


footsies_final_challenge_scene = (
    copy.deepcopy(footsies_initial_challenge_scene)
    .scene(scene_id="footsies_final_challenge_scene", experiment_config={})
    .display(
        scene_header="Footsies",
        scene_subheader="""
        <div style="text-align: center; font-family: 'Press Start 2P', cursive; padding: 8px;">
            <p style="color: #000; text-shadow: 2px 2px #FFF; margin: 5px;">FINAL CHALLENGE</p>
        </div>
        """
        + CONTROLS_SUBHEADER,
    )
)


footsies_end_survey_scene = (
    static_scene.ScalesAndTextBox(
        scale_questions=[
            "The strategy I learned from my training partner was effective against the final challenge opponents.",
            "I enjoyed playing against the final challenge opponent.",
            "The final challenge opponent felt...",
        ],
        pre_scale_header="",
        scale_labels=[
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Strongly Disagree", "Neutral", "Strongle Agree"],
            ["Too Easy to Beat", "Evenly Matched", "Too Hard to Beat"],
        ],
        text_box_header="Please describe any additional reasoning for your selections or thoughts on the study. You may write N/A if you do not have any anything to add.",
        scale_size=7,
    )
    .scene(scene_id="footsies_final_challenge_survey", experiment_config={})
    .display(scene_subheader="Feedback About Your Final Challenge Opponent")
)

footsies_end_scene = (
    static_scene.CompletionCodeScene()
    .scene(
        scene_id="footsies_end_completion_code_scene",
        should_export_metadata=True,
        experiment_config={},
    )
    .display(
        scene_header="Thank you for participating!",
    )
)
