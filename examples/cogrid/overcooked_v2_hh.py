"""Overcooked V2 (partial observability) — Human-Human Multiplayer (P2P Pyodide).

Two participants play one of the cogrid 0.3.x ``OvercookedV2-*`` layouts
(default: ``OvercookedV2-TestTimeSimple-V0``; swap via ``oc_scenes.v2_scenes_by_id``).
Each browser runs its own Pyodide environment; the render function in
``examples/cogrid/environments/overcooked_v2_template.py`` produces an
agent-centred 5x5 viewport, so each player naturally sees only what their
own chef can observe.

Usage:
    python -m examples.cogrid.overcooked_v2_hh --experiment-id <id>

Open two browser windows to http://localhost:5703 and play together.
"""
from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from examples.cogrid.scenes import scenes as oc_scenes
from mug.configurations import experiment_config
from mug.scenes import stager, static_scene
from mug.server import app

start_scene = (
    static_scene.StartScene()
    .scene(
        scene_id="overcooked_v2_start_scene",
        experiment_config={},
        should_export_metadata=True,
    )
    .display(
        scene_header="Welcome to OvercookedV2",
        scene_body=(
            "<center><p>"
            "In this study you will play a partially-observable variant of "
            "Overcooked with another participant. Each of you can only see a "
            "small area around your own chef. Click <b>Start</b> to join the "
            "lobby."
            "</p></center>"
        ),
    )
)

stager = stager.Stager(
    scenes=[
        start_scene,
        oc_scenes.overcooked_v2_test_time_simple_scene,
        oc_scenes.multiplayer_feedback_scene,
        oc_scenes.end_scene,
    ]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run OvercookedV2 partial-observability multiplayer experiment"
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
            browser_requirements=["Chrome", "Safari", "Firefox"],
            max_ping=200,
        )
        .webrtc(force_relay=False)
        .static_files(
            directories=["examples/cogrid/assets", "examples/shared/assets"]
        )
    )

    app.run(experiment_config)
