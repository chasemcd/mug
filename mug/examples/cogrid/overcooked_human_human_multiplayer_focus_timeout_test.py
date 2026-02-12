"""
Overcooked Human-Human Multiplayer - Focus Timeout Test Configuration

This is a test-specific version for focus loss timeout testing (STRESS-05).
Based on the standard test config with these changes:
- multiplayer(focus_loss_timeout_ms=10000) enables 10 second focus loss timeout
- When a player's browser tab loses focus for 10+ seconds, game ends gracefully

Other settings remain identical to the standard test config:
- No max_rtt limit (allows latency injection testing)
- num_episodes=1 (single episode)
- Higher input confirmation timeout (2000ms) for packet loss resilience

The 10 second timeout is short enough for tests to complete quickly but long
enough to be realistic for actual focus loss scenarios.

Usage:
    python -m mug.examples.cogrid.overcooked_human_human_multiplayer_focus_timeout_test

This is used by pytest E2E tests via the conftest.py flask_server_focus_timeout fixture.
Default port: 5704
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from mug.configurations import experiment_config
from mug.examples.cogrid.scenes import scenes as oc_scenes
from mug.scenes import stager, static_scene
from mug.server import app
from mug.server.matchmaker import FIFOMatchmaker

hh_start_scene = (
    static_scene.StartScene()
    .scene(
        scene_id="overcooked_hh_start_scene",
        experiment_config={},
        should_export_metadata=True,
    )
    .display(
        scene_header="Welcome",
        scene_body_filepath="mug/server/static/templates/overcooked_hh_instructions.html",
    )
)


# Create stager with focus timeout test configuration
# Key differences from standard test config:
# - multiplayer(focus_loss_timeout_ms=10000) enables 10s focus timeout (STRESS-05)
#
# Same as standard test config:
# - gameplay(num_episodes=1, max_steps=450) single episode
# - matchmaking(max_rtt=None) removes RTT limit for latency testing
# - multiplayer(input_confirmation_timeout_ms=2000) for packet loss resilience
stager = stager.Stager(
    scenes=[
        hh_start_scene,
        # Tutorial scene removed for faster test execution
        (
            oc_scenes.cramped_room_human_human
            .gameplay(num_episodes=1, max_steps=450)  # ~15 seconds per episode
            .matchmaking(max_rtt=None, matchmaker=FIFOMatchmaker())  # No RTT limit for latency tests
            .multiplayer(focus_loss_timeout_ms=10000, pause_on_partner_background=False, input_confirmation_timeout_ms=2000)  # 10 second timeout, higher timeout for packet loss tests
        ),
        oc_scenes.multiplayer_feedback_scene,
        oc_scenes.end_scene,
    ]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Overcooked human-human multiplayer experiment (FOCUS TIMEOUT TEST CONFIG)"
    )
    parser.add_argument(
        "--port", type=int, default=5704, help="Port number to listen on"
    )
    args = parser.parse_args()

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager, experiment_id="overcooked_multiplayer_hh_focus_timeout_test")
        .hosting(port=args.port, host="0.0.0.0")
        # Relaxed browser requirements for test automation
        .entry_screening(browser_requirements=["Chrome"], browser_blocklist=[], max_ping=500)
        .webrtc(force_relay=False)
    )

    app.run(experiment_config)
