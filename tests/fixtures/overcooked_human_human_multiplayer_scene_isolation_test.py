"""Overcooked Human-Human Multiplayer - Scene Isolation Test Configuration.

Validates post-game scene isolation: after a GymScene completes and players
advance to the survey scene, closing one player's browser does NOT trigger a
partner-disconnected overlay on the remaining player.

Usage: python -m tests.fixtures.overcooked_human_human_multiplayer_scene_isolation_test
Default port: 5707
"""
from __future__ import annotations

import eventlet

eventlet.monkey_patch()

from tests.fixtures.overcooked_hh_factory import make_hh_config, run_from_main

stager, default_port, experiment_id = make_hh_config(
    experiment_id="overcooked_multiplayer_hh_scene_isolation_test",
    default_port=5707,
)

if __name__ == "__main__":
    run_from_main(stager, default_port, experiment_id)
