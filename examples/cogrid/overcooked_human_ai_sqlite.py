"""
Overcooked Human-AI Comparison — SQLite DataSink variant.

Identical to ``overcooked_human_ai.py`` except that participant data is
written to BOTH the default filesystem layout AND a SQLite database via a
``MultiSink``. Use this example to test the DataSink abstraction end-to-end.

What gets written where:

- ``data/overcooked_sqlite_test/{scene_id}/{subject_id}_*.csv|.json``
    The usual CSV + JSON files from ``FilesystemSink``. These are the
    durability floor — they are always written synchronously.

- ``data/overcooked_sqlite_test.db``
    The SQLite file written asynchronously via ``AsyncSinkWrapper``. Inspect
    it with ``sqlite3 data/overcooked_sqlite_test.db`` then e.g.
    ``SELECT * FROM episode_data;`` to verify per-episode streaming worked.

- ``data/overcooked_sqlite_test/.pending/SQLiteSink/``
    This directory should stay empty under normal conditions. If the SQLite
    sink ever fails to keep up, spillover records land here and the async
    wrapper replays them on the next drain pass.

Usage:
    python -m examples.cogrid.overcooked_human_ai_sqlite
"""

from __future__ import annotations

import eventlet

eventlet.monkey_patch()

import argparse
import os

from examples.cogrid.scenes import scenes as oc_scenes
from mug.configurations import experiment_config
from mug.scenes import stager
from mug.server import app
from mug.server.data_sink import AsyncSinkWrapper, FilesystemSink, MultiSink
from mug.server.data_sinks import SQLiteSink

EXPERIMENT_ID = "overcooked_sqlite_test"
DB_PATH = os.path.join("data", f"{EXPERIMENT_ID}.db")

stager = stager.Stager(
    scenes=[
        oc_scenes.start_scene,
        # oc_scenes.tutorial_gym_scene,
        oc_scenes.cramped_room_0,
        oc_scenes.feedback_scene,
        oc_scenes.end_scene,
    ]
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port", type=int, default=5702, help="Port number to listen on"
    )
    args = parser.parse_args()

    # Make sure the parent dir for the SQLite file exists before the sink
    # opens the connection.
    os.makedirs("data", exist_ok=True)

    # Fan-out sink: keep the filesystem CSVs as the durability floor and push
    # the same data through an AsyncSinkWrapper into SQLite. The wrapper
    # drains the write queue on a background thread so slow DB writes can
    # never block the eventlet socket worker, and any failed writes spill to
    # data/{experiment_id}/.pending/SQLiteSink/ for automatic replay.
    data_sink = MultiSink([
        FilesystemSink(),
        AsyncSinkWrapper(SQLiteSink(DB_PATH)),
    ])

    experiment_config = (
        experiment_config.ExperimentConfig()
        .experiment(
            stager=stager,
            experiment_id=EXPERIMENT_ID,
            data_sink=data_sink,
        )
        .hosting(port=args.port, host="0.0.0.0")
        .static_files(
            directories=["examples/cogrid/assets", "examples/shared/assets"]
        )
    )

    print(f"\n[SQLite sink] Writing to {DB_PATH}")
    print(
        "[SQLite sink] After the experiment, inspect with:\n"
        f"    sqlite3 {DB_PATH} 'SELECT scene_id, subject_id, episode_num, "
        "written_at FROM episode_data ORDER BY written_at;'\n"
    )

    app.run(experiment_config)
