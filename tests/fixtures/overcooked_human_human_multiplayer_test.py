"""Overcooked Human-Human Multiplayer - Standard Test Configuration.

Base test config with relaxed constraints for E2E testing:
- No focus loss timeout, no RTT limit, shorter episodes (450 steps).

Usage: python -m tests.fixtures.overcooked_human_human_multiplayer_test
Default port: 5702
"""
from __future__ import annotations

import eventlet

eventlet.monkey_patch()

from tests.fixtures.overcooked_hh_factory import make_hh_config, run_from_main

stager, default_port, experiment_id = make_hh_config(
    experiment_id="overcooked_multiplayer_hh_test",
    default_port=5702,
)

if __name__ == "__main__":
    run_from_main(stager, default_port, experiment_id)
