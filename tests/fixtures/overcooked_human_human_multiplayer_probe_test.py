"""Overcooked Human-Human Multiplayer - Probe Test Configuration.

Enables P2P RTT probing via FIFOMatchmaker(max_p2p_rtt_ms=100). Used by stress
tests to validate probe-based matchmaking under load.

Usage: python -m tests.fixtures.overcooked_human_human_multiplayer_probe_test
Default port: 5708
"""
from __future__ import annotations

import eventlet

eventlet.monkey_patch()

from mug.server.matchmaker import FIFOMatchmaker
from tests.fixtures.overcooked_hh_factory import make_hh_config, run_from_main

stager, default_port, experiment_id = make_hh_config(
    experiment_id="overcooked_multiplayer_hh_probe_test",
    default_port=5708,
    matchmaker=FIFOMatchmaker(max_p2p_rtt_ms=100),
)

if __name__ == "__main__":
    run_from_main(stager, default_port, experiment_id)
