"""
Overcooked Human-Human Multiplayer - Multi-Episode Test Configuration

This is a test-specific version for multi-episode stress testing (STRESS-02).
Based on the standard test config with these changes:
- num_episodes=2 (tests back-to-back episode transitions)
- max_steps=450 per episode (~15 seconds at 30fps)

Other settings remain identical to the standard test config:
- No max_rtt limit (allows latency injection testing)
- No focus loss timeout (prevents disconnection during test automation)
- Higher input confirmation timeout (2000ms) for packet loss resilience

Usage:
    python -m mug.examples.cogrid.overcooked_human_human_multiplayer_multi_episode_test

This is used by pytest E2E tests via the conftest.py flask_server_multi_episode fixture.
Default port: 5703
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


# Create stager with multi-episode test configuration
# Key differences from standard test config:
# - gameplay(num_episodes=2) for back-to-back episode testing (STRESS-02)
#
# Same as standard test config:
# - matchmaking(max_rtt=None) removes RTT limit for latency testing
# - multiplayer(focus_loss_timeout_ms=0) disables focus timeout
# - multiplayer(input_confirmation_timeout_ms=2000) for packet loss resilience
stager = stager.Stager(
    scenes=[
        hh_start_scene,
        # Tutorial scene removed for faster test execution
        (
            oc_scenes.cramped_room_human_human
            .gameplay(num_episodes=2, max_steps=450)  # Two episodes ~30 seconds total
            .matchmaking(max_rtt=None, matchmaker=FIFOMatchmaker())  # No RTT limit for latency tests
            .multiplayer(focus_loss_timeout_ms=0, pause_on_partner_background=False, input_confirmation_timeout_ms=2000)  # Disable focus timeout, higher timeout for packet loss tests
        ),
        oc_scenes.multiplayer_feedback_scene,
        oc_scenes.end_scene,
    ]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Overcooked human-human multiplayer experiment (MULTI-EPISODE TEST CONFIG)"
    )
    parser.add_argument(
        "--port", type=int, default=5703, help="Port number to listen on"
    )
    args = parser.parse_args()

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager, experiment_id="overcooked_multiplayer_hh_multi_episode_test")
        .hosting(port=args.port, host="0.0.0.0")
        # Relaxed browser requirements for test automation
        .entry_screening(browser_requirements=["Chrome"], browser_blocklist=[], max_ping=500)
        .webrtc(force_relay=False)
    )

    app.run(experiment_config)
