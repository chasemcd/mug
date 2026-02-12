from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from mug.server import app
from mug.scenes import stager

from mug.configurations import experiment_config
from mug.scenes import scene


from mug.examples.footsies import scenes


stager = stager.Stager(
    scenes=[
        scenes.start_scene,
        scenes.footsies_initial_survey_scene,
        scenes.footsies_tutorial_scene,
        scenes.footsies_initial_challenge_intro,
        scenes.footsies_initial_challenge_scene,
        scenes.footsies_initial_challenge_survey_scene,
        scene.RandomizeOrder(
            [
                scenes.footsies_dynamic_difficulty_rounds,
                scenes.footsies_controllable_difficulty_rounds,
                scenes.footsies_high_skill_rounds,
                scenes.footsies_low_skill_rounds,
                scenes.footsies_random_difficulty_rounds,
                scenes.footsies_dynamic_empowerment_rounds,
                scenes.footsies_empowerment_rounds,
            ],
            keep_n=1,
        ),
        scenes.footsies_training_survey_scene,
        scenes.footsies_mc_survey,
        scenes.footsies_final_challenge_intro,
        scenes.footsies_final_challenge_scene,
        scenes.footsies_end_survey_scene,
        scenes.footsies_end_scene,
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
        .experiment(stager=stager, experiment_id="footsies_test")
        .hosting(port=5702, host="0.0.0.0")
    )

    app.run(experiment_config)
