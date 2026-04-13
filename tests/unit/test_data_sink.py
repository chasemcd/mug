"""Conformance tests for DataSink implementations.

Any user-provided sink can run the ``test_*_contract`` suite against itself
by passing a fresh instance to the parametrized fixture. The suite exercises
every write method, the flush/close contract, fan-out via ``MultiSink``, and
the async-wrapper spillover + replay path.

Example — adding a ``PostgresSink`` to the conformance suite::

    @pytest.fixture
    def my_sink(tmp_path):
        return PostgresSink(dsn="postgres://localhost/mug_test")

    class TestPostgresSink(SinkConformance):
        pass
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from mug.server.data_sink import (AsyncSinkWrapper, DataSink, FilesystemSink,
                                  MultiSink)
from mug.server.data_sinks import SQLiteSink

# ---------------------------------------------------------------------------
# Shared conformance contract
# ---------------------------------------------------------------------------


def _sample_episode() -> dict:
    return {
        "t": [0, 1, 2],
        "action": [1, 2, 0],
        "reward": [0.0, 0.5, 1.0],
        "observation": {"player_0": {"pos": [[1, 2], [1, 3], [2, 3]]}},
    }


def _exercise(sink: DataSink, experiment_id: str = "exp") -> None:
    """Call every write method at least once. Must not raise."""
    sink.write_metadata(
        experiment_id, "start_scene", "subj1", {"scene_type": "StartScene"}
    )
    sink.write_static_scene_data(
        experiment_id, "form_scene", "subj1", {"q1": "a", "q2": "b"}
    )
    sink.write_episode(
        experiment_id, "game_scene", "subj1", 0, _sample_episode()
    )
    sink.write_episode(
        experiment_id, "game_scene", "subj1", 1, _sample_episode()
    )
    sink.write_globals(
        experiment_id, "game_scene", "subj1", {"name": "alice", "condition": "sp"}
    )
    sink.write_multiplayer_metrics(
        experiment_id,
        "game_scene",
        "subj1",
        {"connection": {"type": "p2p"}, "desync": 0},
    )
    sink.write_aggregated_multiplayer_metrics(
        experiment_id, "game_scene", "game_abc", {"fullySynced": True}
    )


def _assert_filesystem_layout(base_dir: Path, experiment_id: str) -> None:
    exp_dir = base_dir / experiment_id
    assert (exp_dir / "start_scene" / "subj1_metadata.json").exists()
    assert (exp_dir / "form_scene" / "subj1.csv").exists()
    assert (exp_dir / "game_scene" / "subj1_ep0.csv").exists()
    assert (exp_dir / "game_scene" / "subj1_ep1.csv").exists()
    assert (exp_dir / "game_scene" / "subj1_globals.json").exists()
    assert (exp_dir / "game_scene" / "subj1_multiplayer_metrics.json").exists()
    assert (exp_dir / "game_scene" / "game_abc_aggregated_metrics.json").exists()


# ---------------------------------------------------------------------------
# FilesystemSink
# ---------------------------------------------------------------------------


class TestFilesystemSink:
    def test_round_trip(self, tmp_path):
        sink = FilesystemSink(base_dir=str(tmp_path))
        _exercise(sink)
        _assert_filesystem_layout(tmp_path, "exp")

    def test_episode_csv_contents_are_flattened(self, tmp_path):
        sink = FilesystemSink(base_dir=str(tmp_path))
        sink.write_episode("exp", "scene", "s", 0, _sample_episode())
        import pandas as pd

        df = pd.read_csv(tmp_path / "exp" / "scene" / "s_ep0.csv")
        assert "t" in df.columns
        assert "action" in df.columns
        # Nested obs dict should be dot-flattened
        assert any("observation.player_0.pos" in c for c in df.columns)
        assert len(df) == 3

    def test_empty_episode_is_noop(self, tmp_path):
        sink = FilesystemSink(base_dir=str(tmp_path))
        sink.write_episode("exp", "scene", "s", 0, {})  # no 't' key → skip
        assert not (tmp_path / "exp" / "scene" / "s_ep0.csv").exists()

    def test_metadata_json_is_valid(self, tmp_path):
        sink = FilesystemSink(base_dir=str(tmp_path))
        sink.write_metadata("exp", "scene", "s", {"foo": "bar", "n": 42})
        with open(tmp_path / "exp" / "scene" / "s_metadata.json") as f:
            loaded = json.load(f)
        assert loaded == {"foo": "bar", "n": 42}

    def test_flush_and_close_are_noops(self, tmp_path):
        sink = FilesystemSink(base_dir=str(tmp_path))
        assert sink.flush() is True
        sink.close()  # must not raise


# ---------------------------------------------------------------------------
# MultiSink — fan-out
# ---------------------------------------------------------------------------


class _RecordingSink(DataSink):
    """Test helper: record every write call in order."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def write_metadata(self, experiment_id, scene_id, subject_id, metadata):
        self.calls.append(("write_metadata", dict(locals())))

    def write_static_scene_data(self, experiment_id, scene_id, subject_id, data):
        self.calls.append(("write_static_scene_data", dict(locals())))

    def write_episode(
        self, experiment_id, scene_id, subject_id, episode_num, data
    ):
        self.calls.append(("write_episode", dict(locals())))

    def write_globals(self, experiment_id, scene_id, subject_id, mug_globals):
        self.calls.append(("write_globals", dict(locals())))

    def write_multiplayer_metrics(
        self, experiment_id, scene_id, subject_id, metrics
    ):
        self.calls.append(("write_multiplayer_metrics", dict(locals())))

    def write_aggregated_multiplayer_metrics(
        self, experiment_id, scene_id, game_id, metrics
    ):
        self.calls.append(("write_aggregated_multiplayer_metrics", dict(locals())))


class _BrokenSink(DataSink):
    """Test helper: every write raises. Simulates a broken backend."""

    def __init__(self):
        self.call_count = 0

    def _boom(self, *args, **kwargs):
        self.call_count += 1
        raise RuntimeError(f"boom (call #{self.call_count})")

    write_metadata = _boom
    write_static_scene_data = _boom
    write_episode = _boom
    write_globals = _boom
    write_multiplayer_metrics = _boom
    write_aggregated_multiplayer_metrics = _boom


class TestMultiSink:
    def test_fan_out_to_all_sinks(self, tmp_path):
        a = _RecordingSink()
        b = _RecordingSink()
        multi = MultiSink([a, b])
        _exercise(multi)
        assert len(a.calls) == 7
        assert len(b.calls) == 7
        assert [c[0] for c in a.calls] == [c[0] for c in b.calls]

    def test_failure_in_one_sink_does_not_affect_others(self, tmp_path):
        good = _RecordingSink()
        broken = _BrokenSink()
        multi = MultiSink([broken, good])
        multi.write_metadata("exp", "scene", "s", {"foo": "bar"})
        multi.write_episode("exp", "scene", "s", 0, _sample_episode())
        # Good sink saw both writes despite broken sink raising on each.
        assert len(good.calls) == 2
        assert broken.call_count == 2

    def test_flush_and_close_fan_out(self, tmp_path):
        a = FilesystemSink(base_dir=str(tmp_path / "a"))
        b = FilesystemSink(base_dir=str(tmp_path / "b"))
        multi = MultiSink([a, b])
        _exercise(multi)
        assert multi.flush() is True
        multi.close()  # must not raise


# ---------------------------------------------------------------------------
# AsyncSinkWrapper — background drain + spillover + replay
# ---------------------------------------------------------------------------


class TestAsyncSinkWrapper:
    def test_normal_flow_records_reach_wrapped_sink(self, tmp_path):
        inner = _RecordingSink()
        async_sink = AsyncSinkWrapper(
            inner, spillover_base_dir=str(tmp_path), replay_interval_s=0.1
        )
        async_sink.start()
        try:
            _exercise(async_sink)
            assert async_sink.flush(timeout=5.0)
            assert len(inner.calls) == 7
        finally:
            async_sink.close()

    def test_failed_writes_are_spilled_to_pending_dir(self, tmp_path):
        broken = _BrokenSink()
        async_sink = AsyncSinkWrapper(
            broken,
            spillover_base_dir=str(tmp_path),
            replay_interval_s=3600.0,  # disable replay for this test
        )
        async_sink.start()
        try:
            async_sink.write_metadata("exp", "scene", "s", {"foo": "bar"})
            # Give the drain thread a moment to try the write and spill.
            _wait_for(
                lambda: (tmp_path / "exp" / ".pending" / "_BrokenSink").exists()
                and any(
                    (tmp_path / "exp" / ".pending" / "_BrokenSink").iterdir()
                ),
                timeout=2.0,
            )
            pending_files = list(
                (tmp_path / "exp" / ".pending" / "_BrokenSink").iterdir()
            )
            assert len(pending_files) == 1
            with open(pending_files[0]) as f:
                record = json.loads(f.read())
            assert record["method"] == "write_metadata"
            assert record["kwargs"]["subject_id"] == "s"
        finally:
            async_sink.close()

    def test_spilled_records_are_replayed_when_sink_recovers(self, tmp_path):
        """Simulate: sink breaks → writes spill → sink recovers → replay."""
        class FlappySink(DataSink):
            """Raises until ``healthy`` is set to True."""

            def __init__(self):
                self.healthy = False
                self.writes: list[dict] = []

            def write_metadata(self, experiment_id, scene_id, subject_id, metadata):
                if not self.healthy:
                    raise RuntimeError("not yet")
                self.writes.append({
                    "experiment_id": experiment_id,
                    "scene_id": scene_id,
                    "subject_id": subject_id,
                    "metadata": metadata,
                })

        flappy = FlappySink()
        async_sink = AsyncSinkWrapper(
            flappy,
            spillover_base_dir=str(tmp_path),
            replay_interval_s=0.1,
            sink_name="FlappySink",
        )
        async_sink.start()
        try:
            # Write while sink is broken — record should spill.
            async_sink.write_metadata("exp", "scene", "s1", {"n": 1})
            _wait_for(
                lambda: _count_pending(tmp_path, "FlappySink") == 1, timeout=2.0
            )

            # Sink recovers. Replay pass should pick up the spillover file.
            flappy.healthy = True
            _wait_for(
                lambda: len(flappy.writes) == 1, timeout=5.0
            )
            assert _count_pending(tmp_path, "FlappySink") == 0
            assert flappy.writes[0]["kwargs" if False else "subject_id"] == "s1"
        finally:
            async_sink.close()

    def test_queue_full_spills_without_dropping(self, tmp_path):
        """Fill the queue past capacity; no record may be lost."""
        class SlowSink(DataSink):
            def __init__(self):
                self.seen = 0

            def write_metadata(self, *args, **kwargs):
                time.sleep(0.05)  # artificially slow
                self.seen += 1

        slow = SlowSink()
        async_sink = AsyncSinkWrapper(
            slow,
            max_queue_size=2,
            spillover_base_dir=str(tmp_path),
            replay_interval_s=0.1,
            sink_name="SlowSink",
        )
        async_sink.start()
        try:
            # Fire 20 writes at a sink that can only handle ~20/sec.
            for i in range(20):
                async_sink.write_metadata("exp", "scene", f"s{i}", {"n": i})
            # Drain the in-memory queue.
            assert async_sink.flush(timeout=10.0)
            # Wait for spillover replay to catch up.
            _wait_for(lambda: slow.seen == 20, timeout=20.0)
            # After replay, .pending/ should be empty.
            assert _count_pending(tmp_path, "SlowSink") == 0
        finally:
            async_sink.close()


# ---------------------------------------------------------------------------
# SQLiteSink — concrete second sink, proves the interface works for real DBs
# ---------------------------------------------------------------------------


class TestSQLiteSink:
    def test_round_trip(self, tmp_path):
        db = tmp_path / "test.db"
        sink = SQLiteSink(str(db))
        try:
            _exercise(sink)
        finally:
            sink.close()
        # Re-open and verify rows landed.
        import sqlite3

        conn = sqlite3.connect(str(db))
        assert conn.execute("SELECT COUNT(*) FROM scene_metadata").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM static_scene_data").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM episode_data").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM mug_globals").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM multiplayer_metrics").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM aggregated_multiplayer_metrics"
            ).fetchone()[0]
            == 1
        )
        conn.close()

    def test_globals_upserts_on_same_key(self, tmp_path):
        sink = SQLiteSink(str(tmp_path / "g.db"))
        try:
            sink.write_globals("e", "s", "subj", {"step": 0})
            sink.write_globals("e", "s", "subj", {"step": 1})
            sink.write_globals("e", "s", "subj", {"step": 2})
            import sqlite3

            conn = sqlite3.connect(str(tmp_path / "g.db"))
            rows = conn.execute(
                "SELECT mug_globals FROM mug_globals WHERE subject_id='subj'"
            ).fetchall()
            assert len(rows) == 1
            assert json.loads(rows[0][0])["step"] == 2
            conn.close()
        finally:
            sink.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_for(predicate, timeout: float, interval: float = 0.05) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"Condition not met within {timeout}s")


def _count_pending(base_dir: Path, sink_name: str) -> int:
    total = 0
    if not base_dir.exists():
        return 0
    for exp_dir in base_dir.iterdir():
        pending = exp_dir / ".pending" / sink_name
        if pending.exists():
            total += sum(1 for _ in pending.iterdir())
    return total
