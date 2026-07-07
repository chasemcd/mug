"""Overcooked Human-Human Multiplayer - Long-Episode Test Configuration.

Same as overcooked_human_human_multiplayer_test, but with a long episode
(max_steps=450, ~15s at 30fps). A few E2E tests intrinsically need a long
episode and cannot use the faster 200-step default:
- test_focus_loss_data_parity: waits for frame 360 (80% of 450) before acting.
- test_network_disruption (deep rollback): hides a tab for 6s mid-episode and
  asserts a rollback depth >=150 frames before the episode ends.

Usage: python -m tests.fixtures.overcooked_hh_long_episode_test
Default port: 5713

Shares the standard test experiment_id ("overcooked_multiplayer_hh_test") so
export-parity tests find the CSV files via get_experiment_id(). Safe because
e2e tests run serially and clean_data_dir wipes the data dir before each test.
"""
from __future__ import annotations

import eventlet

eventlet.monkey_patch()

from tests.fixtures.overcooked_hh_factory import make_hh_config, run_from_main

stager, default_port, experiment_id = make_hh_config(
    experiment_id="overcooked_multiplayer_hh_test",
    default_port=5713,
    max_steps=450,
)

if __name__ == "__main__":
    run_from_main(stager, default_port, experiment_id)
