"""Overcooked Human-Human Multiplayer - Focus Timeout Test Configuration.

Enables 10-second focus loss timeout (STRESS-05). When a player's browser tab
loses focus for 10+ seconds, the game ends gracefully.

Usage: python -m tests.fixtures.overcooked_human_human_multiplayer_focus_timeout_test
Default port: 5704
"""
from __future__ import annotations

import eventlet

eventlet.monkey_patch()

from tests.fixtures.overcooked_hh_factory import make_hh_config, run_from_main

stager, default_port, experiment_id = make_hh_config(
    experiment_id="overcooked_multiplayer_hh_focus_timeout_test",
    default_port=5704,
    focus_loss_timeout_ms=10000,
)

if __name__ == "__main__":
    run_from_main(stager, default_port, experiment_id)
