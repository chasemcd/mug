"""Factory for Overcooked human-human multiplayer test configurations.

All HH multiplayer test fixtures share the same structure and differ only in
a few parameters. This factory eliminates the duplication.
"""
from __future__ import annotations

from examples.cogrid.scenes import scenes as oc_scenes
from mug.configurations import experiment_config
from mug.scenes import stager, static_scene
from mug.server.matchmaker import FIFOMatchmaker


def make_hh_start_scene():
    return (
        static_scene.StartScene()
        .scene(
            scene_id="overcooked_hh_start_scene",
            experiment_config={},
            should_export_metadata=True,
        )
        .display(
            scene_header="Welcome",
            scene_body_filepath="examples/cogrid/html_pages/overcooked_hh_instructions.html",
        )
    )


def make_hh_config(
    *,
    experiment_id: str,
    default_port: int,
    num_episodes: int = 1,
    max_steps: int = 450,
    focus_loss_timeout_ms: int = 0,
    matchmaker=None,
) -> tuple:
    """Build a stager and return (stager, default_port, experiment_id).

    The caller is responsible for parsing args and calling app.run().
    """
    if matchmaker is None:
        matchmaker = FIFOMatchmaker()

    hh_start_scene = make_hh_start_scene()

    _stager = stager.Stager(
        scenes=[
            hh_start_scene,
            (
                oc_scenes.cramped_room_human_human
                .gameplay(num_episodes=num_episodes, max_steps=max_steps)
                .matchmaking(max_rtt=None, matchmaker=matchmaker)
                .multiplayer(
                    focus_loss_timeout_ms=focus_loss_timeout_ms,
                    pause_on_partner_background=False,
                    input_confirmation_timeout_ms=2000,
                )
            ),
            oc_scenes.multiplayer_feedback_scene,
            oc_scenes.end_scene,
        ]
    )

    return _stager, default_port, experiment_id


def run_from_main(stager_obj, default_port: int, experiment_id: str):
    """Parse --port arg and run the server. Call from __main__ blocks."""
    import argparse

    from mug.server import app

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port", type=int, default=default_port, help="Port number to listen on"
    )
    args = parser.parse_args()

    config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager_obj, experiment_id=experiment_id)
        .hosting(port=args.port, host="0.0.0.0")
        .entry_screening(
            browser_requirements=["Chrome"], browser_blocklist=[], max_ping=500
        )
        .webrtc(force_relay=False)
        .static_files(
            directories=["examples/cogrid/assets", "examples/shared/assets"]
        )
    )

    app.run(config)
