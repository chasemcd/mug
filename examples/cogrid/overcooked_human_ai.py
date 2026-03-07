"""
Overcooked Human-AI Comparison (Client-Side with Pyodide)

This example demonstrates Human-AI experiments where:
- One human participant plays with AI partners in the browser
- Environment runs client-side using Pyodide (zero server computation)
- Two AI partners (SP and IBC) for within-subjects comparison
- Participant provides preference feedback between partners

Usage:
    python -m examples.cogrid.overcooked_human_ai
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from examples.cogrid.scenes import scenes as oc_scenes
from mug.configurations import experiment_config
from mug.scenes import stager
from mug.server import app

stager = stager.Stager(
    scenes=[
        oc_scenes.start_scene,
        oc_scenes.tutorial_gym_scene,
        oc_scenes.cramped_room_0,
        oc_scenes.feedback_scene,
        oc_scenes.end_scene,
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
        .experiment(stager=stager, experiment_id="overcooked_test")
        .hosting(port=args.port, host="0.0.0.0")
        .static_files(directories=["examples/cogrid/assets", "examples/shared/assets"])
    )

    app.run(experiment_config)
