"""
Overcooked Human-Human Multiplayer (Client-Side with Pyodide)

This example demonstrates multiplayer Pyodide experiments where:
- Two human participants play together in real-time
- Each client runs their own Pyodide environment in the browser
- Server coordinates action synchronization
- Deterministic execution via seeded RNG ensures perfect synchronization
- Only the host logs data (avoids duplicates)
- State verification detects and recovers from desyncs

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
    print("  5. Server coordinates actions for perfect synchronization")
    print("  6. Only one participant (host) logs data to avoid duplicates")
    print("\nFeatures:")
    print("  ✓ Zero server-side computation (environments run in browsers)")
    print("  ✓ Deterministic AI via seeded RNG")
    print("  ✓ State verification every 30 frames")
    print("  ✓ Automatic desync recovery")
    print("  ✓ Host migration on disconnection")
    print("="*70 + "\n")

    app.run(experiment_config)
