"""
Overcooked Human-Human Multiplayer - Probe Test Configuration

This is a test-specific version of the multiplayer experiment with P2P RTT
probing enabled via FIFOMatchmaker(max_p2p_rtt_ms=100). Used by stress tests
to validate probe-based matchmaking under load.

Key differences from the base test config:
- FIFOMatchmaker(max_p2p_rtt_ms=100) enables P2P RTT probing with 100ms threshold
- No max_rtt limit (allows latency injection testing)
- No focus loss timeout (prevents disconnection during test automation)
- Shorter episodes for faster test completion
- Higher input confirmation timeout (2000ms) for packet loss resilience

Usage:
    python -m interactive_gym.examples.cogrid.overcooked_human_human_multiplayer_probe_test

This is used by pytest E2E stress tests via the conftest.py flask_server_probe fixture.
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from mug.server import app
from mug.server.matchmaker import FIFOMatchmaker
from mug.scenes import stager
from mug.examples.cogrid.scenes import (
    scenes as oc_scenes,
)
from mug.scenes import static_scene

from mug.configurations import experiment_config


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


# Create stager with test-configured multiplayer scenes
# Key differences from production:
# - No tutorial scene (saves ~30 seconds per test)
# - FIFOMatchmaker(max_p2p_rtt_ms=100) enables P2P probe with 100ms threshold
# - multiplayer(focus_loss_timeout_ms=0) disables focus timeout
# - gameplay(num_episodes=1, max_steps=450) shorter episodes (~15s at 30fps)
stager = stager.Stager(
    scenes=[
        hh_start_scene,
        # Tutorial scene removed for faster test execution
        (
            oc_scenes.cramped_room_human_human
            .gameplay(num_episodes=1, max_steps=450)  # ~15 seconds per episode
            .matchmaking(max_rtt=None, matchmaker=FIFOMatchmaker(max_p2p_rtt_ms=100))  # P2P probe enabled with 100ms threshold
            .multiplayer(focus_loss_timeout_ms=0, pause_on_partner_background=False, input_confirmation_timeout_ms=2000)  # Disable focus timeout, higher timeout for packet loss tests
        ),
        oc_scenes.multiplayer_feedback_scene,
        oc_scenes.end_scene,
    ]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Overcooked human-human multiplayer experiment (PROBE TEST CONFIG)"
    )
    parser.add_argument(
        "--port", type=int, default=5708, help="Port number to listen on"
    )
    args = parser.parse_args()

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager, experiment_id="overcooked_multiplayer_hh_probe_test")
        .hosting(port=args.port, host="0.0.0.0")
        # Relaxed browser requirements for test automation
        .entry_screening(browser_requirements=["Chrome"], browser_blocklist=[], max_ping=500)
        .webrtc(force_relay=False)
    )

    app.run(experiment_config)
