"""
Overcooked Human-AI - Test Configuration

Minimal test server for ONNX inference E2E testing:
- Single human + ONNX AI partner (cramped_room_sp_0 with ModelConfig)
- Short episode (200 steps ~7s at 30fps)
- No tutorial, no feedback, no randomization
- Relaxed browser requirements for test automation

Usage:
    python -m mug.examples.cogrid.overcooked_human_ai_test

This is used by pytest E2E tests via the conftest.py flask_server_human_ai fixture.
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse
import copy

from mug.server import app
from mug.scenes import stager
from mug.examples.cogrid.scenes import (
    scenes as oc_scenes,
)

from mug.configurations import experiment_config


stager = stager.Stager(
    scenes=[
        oc_scenes.start_scene,
        (
            copy.deepcopy(oc_scenes.cramped_room_sp_0)
            .gameplay(num_episodes=1, max_steps=200)
        ),
        oc_scenes.end_scene,
    ]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Overcooked human-AI experiment (TEST CONFIG)"
    )
    parser.add_argument(
        "--port", type=int, default=5709, help="Port number to listen on"
    )
    args = parser.parse_args()

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager, experiment_id="overcooked_human_ai_test")
        .hosting(port=args.port, host="0.0.0.0")
        .entry_screening(browser_requirements=["Chrome"], browser_blocklist=[], max_ping=500)
    )

    app.run(experiment_config)
