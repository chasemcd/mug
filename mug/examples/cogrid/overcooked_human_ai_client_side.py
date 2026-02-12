"""
Overcooked Human-AI Comparison (Client-Side with Pyodide)

This example demonstrates Human-AI experiments where:
- One human participant plays with AI partners in the browser
- Environment runs client-side using Pyodide (zero server computation)
- Two AI partners (SP and BS) for within-subjects comparison
- Participant provides preference feedback between partners

Note: This example is fully compatible with the new multiplayer Pyodide
implementation. While this is single-player from the server's perspective
(one human + AI in one browser), the same infrastructure supports true
multiplayer experiments. See overcooked_human_human_multiplayer.py for
an example of two humans playing together with synchronized Pyodide
environments.

Usage:
    python -m mug.examples.cogrid.overcooked_human_ai_client_side
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from mug.server import app
from mug.scenes import scene
from mug.scenes import stager
from mug.examples.cogrid.scenes import (
    scenes as oc_scenes,
)

from mug.configurations import experiment_config

stager = stager.Stager(
    scenes=[
        oc_scenes.start_scene,
        oc_scenes.tutorial_gym_scene,
        scene.RandomizeOrder(
            scenes=[
                oc_scenes.cramped_room_0,
                oc_scenes.counter_circuit_0,
                oc_scenes.forced_coordination_0,
                oc_scenes.asymmetric_advantages_0,
                oc_scenes.coordination_ring_0,
            ],
            keep_n=1,  # Only select one of the five layouts
        ),
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
        .hosting(port=5702, host="0.0.0.0")
    )

    app.run(experiment_config)
