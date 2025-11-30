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

from interactive_gym.configurations import experiment_config

# Create stager with multiplayer scenes
stager = stager.Stager(
    scenes=[
        oc_scenes.start_scene,
        # oc_scenes.tutorial_gym_scene,
        # For multiplayer, all players must be on the same scene
        # Using RandomizeOrder creates different scenes per player
        oc_scenes.cramped_room_human_human,
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
    )

    print("\n" + "="*70)
    print("Overcooked Human-Human Multiplayer Experiment")
    print("="*70)
    print(f"\nServer starting on http://localhost:{args.port}")
    print("\nInstructions:")
    print("  1. Open TWO browser windows to the URL above")
    print("  2. Both participants will be placed in a waiting room")
    print("  3. Once both joined, the game will start automatically")
    print("  4. Each participant plays in their own browser with Pyodide")
    print("  5. Games run independently - no waiting for other player's input")
    print("  6. Only one participant (host) logs data to avoid duplicates")
    print("\nSync Architecture:")
    print("  ✓ Action Queue: Actions broadcast immediately and queued")
    print("  ✓ No blocking: Games run at full speed independently")
    print("  ✓ Fallback: Use previous action when queue is empty")
    print("  ✓ State verification every 300 frames (~10s at 30fps)")
    print("  ✓ Automatic desync recovery via full state transfer")
    print("  ✓ Host migration on disconnection")
    print("="*70 + "\n")

    app.run(experiment_config)
