"""Pluggable data sinks for MUG experiment data.

A ``DataSink`` is the backend MUG writes participant data to. The default
``FilesystemSink`` writes CSV + JSON to ``data/{experiment_id}/{scene_id}/``.
Users can plug in their own sinks (Postgres,
SQLite, S3, etc.) by subclassing ``DataSink``.

Three patterns are supported:

- **A single sink.** Drop-in replacement for the filesystem default.
- **Fan-out.** ``MultiSink([FilesystemSink(), PostgresSink(...)])`` writes to
  both. Keeps the filesystem as a durability floor even when using a database.
- **Async drain with spillover.** ``AsyncSinkWrapper`` puts records on an
  in-memory queue drained by a background thread, so slow sinks never block
  the eventlet hub. If the queue fills up or the underlying sink raises,
  records are spilled to ``data/{experiment_id}/.pending/{sink}/`` and replayed
  later. No record is ever dropped.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import queue
import threading
import time
import uuid
from abc import ABC, abstractmethod
from typing import Iterable

import flatten_dict
import pandas as pd

logger = logging.getLogger(__name__)


class DataSink(ABC):
    """Abstract data sink.

    Implement any subset of the ``write_*`` methods you care about. The base
    class provides no-op defaults so a sink targeting only gym episode data
    doesn't have to stub every method.

    All write methods must tolerate being called from a background thread.
    Concrete sinks are responsible for their own retry logic — raise to signal
    failure, and the async wrapper (if wrapping this sink) will spill the
    record to disk for later replay.
    """

    def write_metadata(
        self,
        experiment_id: str,
        scene_id: str,
        subject_id: str,
        metadata: dict,
    ) -> None:
        """Persist scene metadata (headers, form answers, completion codes)."""

    def write_static_scene_data(
        self,
        experiment_id: str,
        scene_id: str,
        subject_id: str,
        data: dict,
    ) -> None:
        """Persist a static scene's end-of-scene data (form answers, etc.)."""

    def write_episode(
        self,
        experiment_id: str,
        scene_id: str,
        subject_id: str,
        episode_num: int,
        data: dict,
    ) -> None:
        """Persist one episode of gym gameplay.

        ``data`` is the decoded msgpack payload: a dict of lists where each
        list is a per-timestep stream (observations, actions, rewards, ``t``,
        ``terminateds``, etc.). Nested dicts may be present — sinks are free
        to flatten them however they like.
        """

    def write_globals(
        self,
        experiment_id: str,
        scene_id: str,
        subject_id: str,
        mug_globals: dict,
    ) -> None:
        """Persist the latest ``mugGlobals`` snapshot for this participant."""

    def write_multiplayer_metrics(
        self,
        experiment_id: str,
        scene_id: str,
        subject_id: str,
        metrics: dict,
    ) -> None:
        """Persist per-participant P2P / sync validation metrics."""

    def write_aggregated_multiplayer_metrics(
        self,
        experiment_id: str,
        scene_id: str,
        game_id: str,
        metrics: dict,
    ) -> None:
        """Persist fan-in aggregated P2P metrics for a completed game.

        Unlike the other ``write_*`` methods this is keyed by ``game_id``
        instead of ``subject_id`` because the aggregated record is per-game,
        produced once when both players' individual metrics have arrived.
        """

    def flush(self, timeout: float | None = None) -> bool:
        """Block until all pending records are persisted or spilled.

        Called at experiment-end scenes and on graceful shutdown. The default
        is a no-op for synchronous sinks. Async wrappers override this to
        drain their queues.

        Returns ``True`` if the flush completed cleanly, ``False`` if it timed
        out. The caller is expected to log and continue either way — a stuck
        sink must never block participant completion.
        """
        return True

    def close(self) -> None:
        """Release any open resources. Called once on server shutdown."""


# ---------------------------------------------------------------------------
# FilesystemSink — the default, drop-in for today's behavior
# ---------------------------------------------------------------------------


class FilesystemSink(DataSink):
    """Writes CSV + JSON files under ``{base_dir}/{experiment_id}/{scene_id}/``.

    This is a lift-and-shift of the direct ``df.to_csv(...)`` / ``json.dump``
    calls that used to live in ``mug/server/app.py``. Output layout is
    identical to pre-sink MUG.
    """

    def __init__(self, base_dir: str = "data"):
        self.base_dir = base_dir

    def _scene_dir(self, experiment_id: str, scene_id: str) -> str:
        path = os.path.join(self.base_dir, experiment_id, scene_id)
        os.makedirs(path, exist_ok=True)
        return path

    def write_metadata(self, experiment_id, scene_id, subject_id, metadata):
        path = os.path.join(
            self._scene_dir(experiment_id, scene_id),
            f"{subject_id}_metadata.json",
        )
        with open(path, "w") as f:
            json.dump(metadata, f)

    def write_static_scene_data(
        self, experiment_id, scene_id, subject_id, data
    ):
        path = os.path.join(
            self._scene_dir(experiment_id, scene_id),
            f"{subject_id}.csv",
        )
        # Static scene data is a flat dict of scalars; wrap each value in a
        # single-row list so DataFrame construction works uniformly.
        rows = {k: [v] for k, v in data.items()}
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime("now")
        df.to_csv(path, index=False)

    def write_episode(
        self, experiment_id, scene_id, subject_id, episode_num, data
    ):
        df = _episode_dict_to_dataframe(data)
        if df is None:
            return
        path = os.path.join(
            self._scene_dir(experiment_id, scene_id),
            f"{subject_id}_ep{episode_num}.csv",
        )
        df.to_csv(path, index=False)

    def write_globals(self, experiment_id, scene_id, subject_id, mug_globals):
        path = os.path.join(
            self._scene_dir(experiment_id, scene_id),
            f"{subject_id}_globals.json",
        )
        with open(path, "w") as f:
            json.dump(mug_globals, f)

    def write_multiplayer_metrics(
        self, experiment_id, scene_id, subject_id, metrics
    ):
        path = os.path.join(
            self._scene_dir(experiment_id, scene_id),
            f"{subject_id}_multiplayer_metrics.json",
        )
        with open(path, "w") as f:
            json.dump(metrics, f, indent=2)

    def write_aggregated_multiplayer_metrics(
        self, experiment_id, scene_id, game_id, metrics
    ):
        path = os.path.join(
            self._scene_dir(experiment_id, scene_id),
            f"{game_id}_aggregated_metrics.json",
        )
        with open(path, "w") as f:
            json.dump(metrics, f, indent=2)


def _episode_dict_to_dataframe(data: dict) -> pd.DataFrame | None:
    """Convert a decoded episode payload into a padded DataFrame.

    Returns ``None`` if the payload is empty (no timesteps to save).
    """
    if not data or not data.get("t"):
        return None
    flattened = flatten_dict.flatten(data, reducer="dot")
    max_length = max(
        len(v) if isinstance(v, list) else 1 for v in flattened.values()
    )
    padded = {}
    for key, value in flattened.items():
        if not isinstance(value, list):
            padded[key] = [value] + [None] * (max_length - 1)
        else:
            padded[key] = value + [None] * (max_length - len(value))
    return pd.DataFrame(padded)


# ---------------------------------------------------------------------------
# MultiSink — fan-out
# ---------------------------------------------------------------------------


class MultiSink(DataSink):
    """Fan-out to multiple sinks.

    Failures in one sink never affect the others. Each child sink sees every
    write. Typical usage keeps ``FilesystemSink`` as the durability floor and
    pairs it with one or more remote sinks::

        config.data_sink(MultiSink([
            FilesystemSink(),
            AsyncSinkWrapper(PostgresSink("postgres://...")),
        ]))
    """

    def __init__(self, sinks: Iterable[DataSink]):
        self.sinks = list(sinks)

    def _each(self, method_name: str, *args, **kwargs):
        for sink in self.sinks:
            try:
                getattr(sink, method_name)(*args, **kwargs)
            except Exception as e:
                logger.warning(
                    f"[MultiSink] {sink.__class__.__name__}.{method_name} "
                    f"raised: {e}. Other sinks unaffected."
                )

    def write_metadata(self, *args, **kwargs):
        self._each("write_metadata", *args, **kwargs)

    def write_static_scene_data(self, *args, **kwargs):
        self._each("write_static_scene_data", *args, **kwargs)

    def write_episode(self, *args, **kwargs):
        self._each("write_episode", *args, **kwargs)

    def write_globals(self, *args, **kwargs):
        self._each("write_globals", *args, **kwargs)

    def write_multiplayer_metrics(self, *args, **kwargs):
        self._each("write_multiplayer_metrics", *args, **kwargs)

    def write_aggregated_multiplayer_metrics(self, *args, **kwargs):
        self._each("write_aggregated_multiplayer_metrics", *args, **kwargs)

    def flush(self, timeout: float | None = None) -> bool:
        ok = True
        for sink in self.sinks:
            try:
                if not sink.flush(timeout=timeout):
                    ok = False
            except Exception as e:
                logger.warning(
                    f"[MultiSink] {sink.__class__.__name__}.flush raised: {e}"
                )
                ok = False
        return ok

    def close(self):
        for sink in self.sinks:
            try:
                sink.close()
            except Exception as e:
                logger.warning(
                    f"[MultiSink] {sink.__class__.__name__}.close raised: {e}"
                )


# ---------------------------------------------------------------------------
# AsyncSinkWrapper — background drain + dead-letter spillover
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _SinkRecord:
    """A single pending write, uniform across write_* method types.

    ``kwargs`` is the full argument dict passed to the underlying sink's
    method, so the record is self-contained and doesn't need to know which
    kwargs a given method takes (subject_id vs game_id, episode_num, etc.).
    """

    method: str  # "write_metadata", "write_episode", ...
    kwargs: dict
    attempts: int = 0

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self))

    @classmethod
    def from_json(cls, line: str) -> _SinkRecord:
        return cls(**json.loads(line))


class AsyncSinkWrapper(DataSink):
    """Run any sink on a background thread with a bounded queue.

    Handler calls return immediately after enqueueing. A drain thread pops
    records off the queue and dispatches them to the wrapped sink.

    **No record is ever dropped.** If the queue is full or the wrapped sink
    raises, the record is serialized to
    ``{spillover_dir}/{experiment_id}/.pending/{sink_class}/<uuid>.json``.
    A low-priority replay pass picks spilled records up the next time the
    drain thread is idle and tries to push them through the sink. Successful
    replays delete the spillover file; failures leave it for the next attempt.

    This means the only thing that can grow unboundedly is disk usage, and
    only when the underlying sink is permanently broken (wrong DSN, bad
    credentials, missing schema). Those cases log a warning on every retry.
    """

    def __init__(
        self,
        sink: DataSink,
        max_queue_size: int = 10_000,
        spillover_base_dir: str = "data",
        replay_interval_s: float = 5.0,
        sink_name: str | None = None,
    ):
        self.sink = sink
        self.spillover_base_dir = spillover_base_dir
        self.replay_interval_s = replay_interval_s
        self._sink_name = sink_name or sink.__class__.__name__
        self._queue: queue.Queue[_SinkRecord] = queue.Queue(
            maxsize=max_queue_size
        )
        self._shutdown = threading.Event()
        self._worker: threading.Thread | None = None
        self._worker_started = False
        self._last_replay_attempt = 0.0

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Spawn the drain worker. Idempotent."""
        if self._worker_started:
            return
        self._worker_started = True
        self._worker = threading.Thread(
            target=self._drain_loop,
            name=f"AsyncSink[{self._sink_name}]",
            daemon=True,
        )
        self._worker.start()
        logger.info(f"[AsyncSink] Started drain worker for {self._sink_name}")

    def close(self) -> None:
        self._shutdown.set()
        if self._worker is not None:
            self._worker.join(timeout=5.0)
        try:
            self.sink.close()
        except Exception as e:
            logger.warning(f"[AsyncSink] {self._sink_name}.close raised: {e}")

    def flush(self, timeout: float | None = None) -> bool:
        """Block until the in-memory queue is empty (or timeout)."""
        deadline = time.monotonic() + timeout if timeout else None
        while not self._queue.empty():
            if deadline and time.monotonic() >= deadline:
                logger.warning(
                    f"[AsyncSink] {self._sink_name} flush timed out with "
                    f"{self._queue.qsize()} record(s) remaining. Any stuck "
                    f"records will be spilled to .pending/ for later replay."
                )
                return False
            time.sleep(0.05)
        return True

    # -- public write methods --------------------------------------------

    def write_metadata(self, experiment_id, scene_id, subject_id, metadata):
        self._enqueue(
            _SinkRecord(
                method="write_metadata",
                kwargs={
                    "experiment_id": experiment_id,
                    "scene_id": scene_id,
                    "subject_id": subject_id,
                    "metadata": metadata,
                },
            )
        )

    def write_static_scene_data(
        self, experiment_id, scene_id, subject_id, data
    ):
        self._enqueue(
            _SinkRecord(
                method="write_static_scene_data",
                kwargs={
                    "experiment_id": experiment_id,
                    "scene_id": scene_id,
                    "subject_id": subject_id,
                    "data": data,
                },
            )
        )

    def write_episode(
        self, experiment_id, scene_id, subject_id, episode_num, data
    ):
        self._enqueue(
            _SinkRecord(
                method="write_episode",
                kwargs={
                    "experiment_id": experiment_id,
                    "scene_id": scene_id,
                    "subject_id": subject_id,
                    "episode_num": episode_num,
                    "data": data,
                },
            )
        )

    def write_globals(self, experiment_id, scene_id, subject_id, mug_globals):
        self._enqueue(
            _SinkRecord(
                method="write_globals",
                kwargs={
                    "experiment_id": experiment_id,
                    "scene_id": scene_id,
                    "subject_id": subject_id,
                    "mug_globals": mug_globals,
                },
            )
        )

    def write_multiplayer_metrics(
        self, experiment_id, scene_id, subject_id, metrics
    ):
        self._enqueue(
            _SinkRecord(
                method="write_multiplayer_metrics",
                kwargs={
                    "experiment_id": experiment_id,
                    "scene_id": scene_id,
                    "subject_id": subject_id,
                    "metrics": metrics,
                },
            )
        )

    def write_aggregated_multiplayer_metrics(
        self, experiment_id, scene_id, game_id, metrics
    ):
        self._enqueue(
            _SinkRecord(
                method="write_aggregated_multiplayer_metrics",
                kwargs={
                    "experiment_id": experiment_id,
                    "scene_id": scene_id,
                    "game_id": game_id,
                    "metrics": metrics,
                },
            )
        )

    # -- internals -------------------------------------------------------

    def _enqueue(self, record: _SinkRecord) -> None:
        if not self._worker_started:
            self.start()
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            logger.warning(
                f"[AsyncSink] {self._sink_name} queue full "
                f"({self._queue.maxsize}). Spilling record to .pending/."
            )
            self._spill(record)

    def _drain_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                record = self._queue.get(timeout=0.1)
            except queue.Empty:
                self._maybe_replay_spillover()
                continue

            self._dispatch(record)
            self._queue.task_done()

    def _dispatch(self, record: _SinkRecord) -> None:
        method = getattr(self.sink, record.method)
        try:
            method(**record.kwargs)
        except Exception as e:
            logger.warning(
                f"[AsyncSink] {self._sink_name}.{record.method} failed "
                f"(attempt {record.attempts + 1}): {e}. Spilling to .pending/."
            )
            record.attempts += 1
            self._spill(record)

    def _spillover_dir(self, experiment_id: str) -> str:
        path = os.path.join(
            self.spillover_base_dir, experiment_id, ".pending", self._sink_name
        )
        os.makedirs(path, exist_ok=True)
        return path

    def _spill(self, record: _SinkRecord) -> None:
        experiment_id = record.kwargs.get("experiment_id", "_unknown")
        try:
            spill_dir = self._spillover_dir(experiment_id)
            filename = f"{time.time():.6f}_{uuid.uuid4().hex}.json"
            path = os.path.join(spill_dir, filename)
            with open(path, "w") as f:
                f.write(record.to_json())
        except Exception as e:
            logger.error(
                f"[AsyncSink] {self._sink_name} failed to spill record: {e}. "
                f"This is a disk failure — the record for "
                f"scene={record.kwargs.get('scene_id')} is lost."
            )

    def _maybe_replay_spillover(self) -> None:
        """Attempt to replay spilled records for known experiments.

        Rate-limited to ``replay_interval_s`` so a broken sink doesn't pin a
        CPU spinning on failing replays. Walks the spillover base dir and
        tries each file; successes are deleted, failures stay put.
        """
        now = time.monotonic()
        if now - self._last_replay_attempt < self.replay_interval_s:
            return
        self._last_replay_attempt = now

        if not os.path.isdir(self.spillover_base_dir):
            return

        # Walk data/*/.pending/{sink_name}/ for spilled records.
        for experiment_id in os.listdir(self.spillover_base_dir):
            pending_dir = os.path.join(
                self.spillover_base_dir,
                experiment_id,
                ".pending",
                self._sink_name,
            )
            if not os.path.isdir(pending_dir):
                continue
            for filename in sorted(os.listdir(pending_dir)):
                if self._shutdown.is_set():
                    return
                path = os.path.join(pending_dir, filename)
                try:
                    with open(path) as f:
                        record = _SinkRecord.from_json(f.read())
                except Exception as e:
                    logger.warning(
                        f"[AsyncSink] Failed to load spillover file {path}: {e}"
                    )
                    continue

                # Retry the sink call directly — don't go through _dispatch
                # because we want to delete the file on success, not spill
                # again.
                try:
                    method = getattr(self.sink, record.method)
                    method(**record.kwargs)
                    os.remove(path)
                    logger.info(
                        f"[AsyncSink] {self._sink_name} replayed "
                        f"{record.method} from {os.path.basename(path)}"
                    )
                except Exception:
                    # Leave the file for the next replay pass. Log at debug
                    # so permanent failures don't flood the log.
                    logger.debug(
                        f"[AsyncSink] {self._sink_name} replay still failing "
                        f"for {path}; leaving spillover in place."
                    )
                    # Stop trying other files this pass — if one failed, the
                    # sink is probably still down and we'd just loop over
                    # more failures.
                    return
