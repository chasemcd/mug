"""
Overcooked Human-Human Multiplayer - Scene Isolation Test Configuration

This is a test-specific version of the multiplayer experiment designed to
validate post-game scene isolation (Phase 79). The stager includes multiple
scenes so the test can verify that after a GymScene completes and players
advance to the survey (feedback) scene, closing one player's browser does
NOT trigger a partner-disconnected overlay on the remaining player.

Scene flow:
1. StartScene (instructions) - advanceButton
2. GymScene (multiplayer Overcooked) - startButton -> waitroom -> P2P game
3. ScalesAndTextBox (multiplayer feedback) - survey scene (isolation tested here)
4. CompletionCodeScene (end)

Key differences from production:
- No tutorial scene (saves ~30 seconds per test)
- matchmaking(max_rtt=None) removes RTT limit for testing
- focus_loss_config(timeout_ms=0) disables focus timeout
- gameplay(num_episodes=1, max_steps=450) shorter episodes (~15s at 30fps)
- pyodide(input_confirmation_timeout_ms=2000) higher timeout for resilience

Usage:
    python -m interactive_gym.examples.cogrid.overcooked_human_human_multiplayer_scene_isolation_test

This is used by pytest E2E tests via the conftest.py flask_server_scene_isolation fixture.
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from interactive_gym.server import app
from interactive_gym.scenes import stager
from interactive_gym.examples.cogrid.scenes import (
    scenes as oc_scenes,
)
from interactive_gym.scenes import static_scene

from interactive_gym.configurations import experiment_config


hh_start_scene = (
    static_scene.StartScene()
    .scene(
        scene_id="overcooked_hh_start_scene",
        experiment_config={},
        should_export_metadata=True,
    )
    .display(
        scene_header="Welcome",
        scene_body_filepath="interactive_gym/server/static/templates/overcooked_hh_instructions.html",
    )
)


# Create stager with test-configured multiplayer scenes
# Includes multiplayer_feedback_scene after GymScene for scene isolation testing
stager = stager.Stager(
    scenes=[
        hh_start_scene,
        # Tutorial scene removed for faster test execution
        (
            oc_scenes.cramped_room_human_human
            .gameplay(num_episodes=1, max_steps=450)  # ~15 seconds per episode
            .matchmaking(max_rtt=None)  # No RTT limit for testing
            .focus_loss_config(timeout_ms=0, pause_on_partner_background=False)  # Disable focus timeout
            .pyodide(input_confirmation_timeout_ms=2000)  # Higher timeout for resilience
        ),
        oc_scenes.multiplayer_feedback_scene,  # Survey scene (isolation tested here)
        oc_scenes.end_scene,
    ]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Overcooked human-human multiplayer experiment (SCENE ISOLATION TEST CONFIG)"
    )
    parser.add_argument(
        "--port", type=int, default=5707, help="Port number to listen on"
    )
    args = parser.parse_args()

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager, experiment_id="overcooked_multiplayer_hh_scene_isolation_test")
        .hosting(port=args.port, host="0.0.0.0")
        # Relaxed browser requirements for test automation
        .entry_screening(browser_requirements=["Chrome"], browser_blocklist=[], max_ping=500)
        .webrtc(force_relay=False)
    )

    app.run(experiment_config)
