"""Overcooked Human-Human Multiplayer - Multi-Episode Test Configuration.

Tests back-to-back episode transitions (STRESS-02) with num_episodes=2.

Usage: python -m tests.fixtures.overcooked_human_human_multiplayer_multi_episode_test
Default port: 5703
"""
from __future__ import annotations

import eventlet

eventlet.monkey_patch()

from tests.fixtures.overcooked_hh_factory import make_hh_config, run_from_main

stager, default_port, experiment_id = make_hh_config(
    experiment_id="overcooked_multiplayer_hh_multi_episode_test",
    default_port=5703,
    num_episodes=2,
)

if __name__ == "__main__":
    run_from_main(stager, default_port, experiment_id)
