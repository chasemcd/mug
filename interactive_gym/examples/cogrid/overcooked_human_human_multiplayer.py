"""
Overcooked Human-Human Multiplayer (Client-Side with Pyodide)

This example demonstrates multiplayer Pyodide experiments where:
- Two human participants play together in real-time
- Each client runs their own Pyodide environment in the browser
- Action Queue synchronization: actions are sent immediately and queued on other clients
- No blocking/waiting: games run independently at full speed
- Fallback to previous action or default when queue is empty
- Optional state verification (hybrid fallback) for desync detection
- Only the host logs data (avoids duplicates)

Sync Architecture:
- Primary: Action Queue (each player's action is broadcast to others and queued)
- Fallback: State Verification (periodic hash comparison with full state resync if needed)

Usage:
    python -m interactive_gym.examples.cogrid.overcooked_human_human_multiplayer

Then open two browser windows to http://localhost:5702 and play together!
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse

from interactive_gym.server import app
from interactive_gym.scenes import scene
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


# Create stager with multiplayer scenes
stager = stager.Stager(
    scenes=[
        hh_start_scene,
        # oc_scenes.tutorial_gym_scene,
        # For multiplayer, all players must be on the same scene
        # Using RandomizeOrder creates different scenes per player
        oc_scenes.cramped_room_human_human.gameplay(num_episodes=2),
        oc_scenes.multiplayer_feedback_scene,
        oc_scenes.end_scene,
    ]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Overcooked human-human multiplayer experiment"
    )
    parser.add_argument(
        "--port", type=int, default=5702, help="Port number to listen on"
    )
    args = parser.parse_args()

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(stager=stager, experiment_id="overcooked_multiplayer_hh")
        .hosting(port=args.port, host="0.0.0.0")
        # For TURN server fallback, use:
        # $ export TURN_USERNAME=<open-relay-username>
        # $ export TURN_CREDENTIAL=<open-relay-password>
        # Or pass them in below.
        .webrtc(force_relay=False)
    )
		
    app.run(experiment_config)
