"""
Overcooked Mixed Kitchen Human-Human Multiplayer (Client-Side with Pyodide)

This example demonstrates multiplayer Pyodide experiments on the
CrampedMixedKitchen layout, which includes both onion and tomato
ingredients plus an order queue that tells players which soup to prepare.

Two human participants play together in real-time with action-queue
synchronization. Each client runs its own Pyodide environment in the
browser.

Usage:
    python -m examples.cogrid.overcooked_mixed_kitchen_hh

Then open two browser windows to http://localhost:5703 and play together!
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from examples.cogrid.scenes import scenes as oc_scenes
from mug.configurations import experiment_config
from mug.scenes import stager, static_scene
from mug.server import app

hh_start_scene = (
    static_scene.StartScene()
    .scene(
        scene_id="overcooked_mixed_kitchen_hh_start_scene",
        experiment_config={},
        should_export_metadata=True,
    )
    .display(
        scene_header="Welcome",
        scene_body_filepath="examples/cogrid/html_pages/overcooked_mixed_kitchen_hh_instructions.html",
    )
)


# Create stager with multiplayer scenes
stager = stager.Stager(
    scenes=[
        hh_start_scene,
        # oc_scenes.tutorial_gym_scene,
        oc_scenes.cramped_mixed_kitchen_human_human.gameplay(
            num_episodes=20, max_steps=4000
        ).multiplayer(pause_on_partner_background=False),
        oc_scenes.multiplayer_feedback_scene,
        oc_scenes.end_scene,
    ]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Overcooked Mixed Kitchen human-human multiplayer experiment"
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
        .entry_screening(
            browser_requirements=["Chrome", "Safari"],
            browser_blocklist=["Firefox"],
            max_ping=200,
        )
        .webrtc(force_relay=False)
        .static_files(
            directories=["examples/cogrid/assets", "examples/shared/assets"]
        )
    )

    app.run(experiment_config)
