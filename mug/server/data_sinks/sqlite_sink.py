"""SQLite data sink — the reference implementation for custom sinks.

This sink writes MUG participant data to a SQLite database file, one row per
write-method call. It's intentionally minimal so it can serve as a template
for users writing their own sinks (``PostgresSink``, ``S3Sink``, etc.).

Usage::

    from mug.server.data_sink import MultiSink, FilesystemSink, AsyncSinkWrapper
    from mug.server.data_sinks import SQLiteSink

    config = (
        experiment_config.ExperimentConfig()
        .experiment(
            stager=...,
            experiment_id="mystudy",
            data_sink=MultiSink([
                FilesystemSink(),                              # durability floor
                AsyncSinkWrapper(SQLiteSink("mystudy.db")),    # queryable store
            ]),
        )
    )

Schema is created on first write. All dict payloads are stored as JSON text
columns; users who want structured columns should subclass and override the
relevant ``write_*`` methods.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time

from mug.server.data_sink import DataSink

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS scene_metadata (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    scene_id      TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    metadata      TEXT NOT NULL,
    written_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS static_scene_data (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    scene_id      TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    data          TEXT NOT NULL,
    written_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS episode_data (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    scene_id      TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    episode_num   INTEGER NOT NULL,
    data          TEXT NOT NULL,
    written_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS mug_globals (
    experiment_id TEXT NOT NULL,
    scene_id      TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    mug_globals   TEXT NOT NULL,
    written_at    REAL NOT NULL,
    PRIMARY KEY (experiment_id, scene_id, subject_id)
);

CREATE TABLE IF NOT EXISTS multiplayer_metrics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    scene_id      TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    metrics       TEXT NOT NULL,
    written_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS aggregated_multiplayer_metrics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL,
    scene_id      TEXT NOT NULL,
    game_id       TEXT NOT NULL,
    metrics       TEXT NOT NULL,
    written_at    REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episode_subject
    ON episode_data (experiment_id, subject_id, scene_id, episode_num);
CREATE INDEX IF NOT EXISTS idx_metadata_subject
    ON scene_metadata (experiment_id, subject_id);
"""


class SQLiteSink(DataSink):
    """A single-file SQLite ``DataSink``.

    Thread-safe via a single connection + lock. Good for experiments up to a
    few hundred thousand records; for anything larger, point a real database
    at this as a template.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _insert(self, sql: str, params: tuple) -> None:
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    def write_metadata(self, experiment_id, scene_id, subject_id, metadata):
        self._insert(
            "INSERT INTO scene_metadata "
            "(experiment_id, scene_id, subject_id, metadata, written_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                experiment_id,
                scene_id,
                subject_id,
                json.dumps(metadata),
                time.time(),
            ),
        )

    def write_static_scene_data(
        self, experiment_id, scene_id, subject_id, data
    ):
        self._insert(
            "INSERT INTO static_scene_data "
            "(experiment_id, scene_id, subject_id, data, written_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                experiment_id,
                scene_id,
                subject_id,
                json.dumps(data),
                time.time(),
            ),
        )

    def write_episode(
        self, experiment_id, scene_id, subject_id, episode_num, data
    ):
        self._insert(
            "INSERT INTO episode_data "
            "(experiment_id, scene_id, subject_id, episode_num, data, written_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                experiment_id,
                scene_id,
                subject_id,
                episode_num,
                json.dumps(data),
                time.time(),
            ),
        )

    def write_globals(self, experiment_id, scene_id, subject_id, mug_globals):
        # Upsert — keep only the latest snapshot per (subject, scene).
        self._insert(
            "INSERT INTO mug_globals "
            "(experiment_id, scene_id, subject_id, mug_globals, written_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(experiment_id, scene_id, subject_id) DO UPDATE SET "
            "mug_globals = excluded.mug_globals, written_at = excluded.written_at",
            (
                experiment_id,
                scene_id,
                subject_id,
                json.dumps(mug_globals),
                time.time(),
            ),
        )

    def write_multiplayer_metrics(
        self, experiment_id, scene_id, subject_id, metrics
    ):
        self._insert(
            "INSERT INTO multiplayer_metrics "
            "(experiment_id, scene_id, subject_id, metrics, written_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                experiment_id,
                scene_id,
                subject_id,
                json.dumps(metrics),
                time.time(),
            ),
        )

    def write_aggregated_multiplayer_metrics(
        self, experiment_id, scene_id, game_id, metrics
    ):
        self._insert(
            "INSERT INTO aggregated_multiplayer_metrics "
            "(experiment_id, scene_id, game_id, metrics, written_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                experiment_id,
                scene_id,
                game_id,
                json.dumps(metrics),
                time.time(),
            ),
        )

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception as e:
                logger.warning(f"[SQLiteSink] close raised: {e}")
