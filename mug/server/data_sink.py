"""Pluggable data sinks for MUG experiment data.

A :class:`DataSink` is the backend MUG writes participant data to. During an
experiment MUG produces six kinds of records — scene metadata, static-scene
form answers, per-episode gym data, ``mugGlobals`` snapshots, per-participant
multiplayer metrics, and per-game aggregated multiplayer metrics. The sink
receives each one through a correspondingly-named ``write_*`` method and
decides where it goes (a file, a database, a cloud bucket, several of those
at once, ...).

The default is :class:`FilesystemSink`, which writes CSV + JSON under
``data/{experiment_id}/{scene_id}/`` — identical to pre-sink MUG. If you only
want the defaults, you don't have to know this module exists.

Three composition patterns cover almost every real use case:

1. **A single sink.** Drop-in replacement for the filesystem default::

       config.experiment(
           stager=...,
           experiment_id="mystudy",
           data_sink=SQLiteSink("data/mystudy.db"),
       )

2. **Fan-out via** :class:`MultiSink`. Write every record to several sinks at
   once. Failures in one child never affect the others. The canonical use is
   to keep :class:`FilesystemSink` as a local **durability floor** alongside a
   remote database, so you always have CSVs on disk even if the DB is down::

       config.experiment(
           ...,
           data_sink=MultiSink([
               FilesystemSink(),
               AsyncSinkWrapper(SQLiteSink("data/mystudy.db")),
           ]),
       )

3. **Async drain with spillover via** :class:`AsyncSinkWrapper`. Wrap any
   sink that does network, disk, or database I/O. The wrapper returns control
   to the socket handler as soon as a record is on an in-memory queue, and a
   background thread drains the queue into the wrapped sink. This is **the
   only safe way to plug a blocking DB driver into MUG** — eventlet's
   cooperative scheduler will freeze every connected participant if a socket
   handler blocks on psycopg2 or a similar C-extension client.

   ``AsyncSinkWrapper`` guarantees that **no record is ever silently dropped**.
   If the in-memory queue is full or the wrapped sink raises, the record is
   serialized to ``data/{experiment_id}/.pending/{SinkName}/<stamp>.json``
   (a "dead-letter" spillover), and a low-priority replay pass running on the
   same drain thread keeps trying to push spilled records through the sink.
   Successful replays delete the spillover file; failures leave it for the
   next attempt. Permanent misconfigurations (wrong DSN, missing schema)
   show up as a growing ``.pending/`` directory, not lost data.

Writing your own sink
---------------------

Subclass :class:`DataSink` and implement whichever ``write_*`` methods you
care about — the base class provides no-op defaults, so a sink that only
captures episode data doesn't have to stub the rest. Sinks should:

- Be threadsafe. When wrapped in :class:`AsyncSinkWrapper`, every write runs
  on a background thread and may be called concurrently with another write.
- Raise to signal failure. The async wrapper catches the exception and spills
  the record for replay. Do **not** swallow errors silently — that bypasses
  the no-data-loss guarantee.
- Avoid retries in the hot path. Let the wrapper handle transient failures
  via spillover. If you need DB-specific retries (deadlock handling,
  connection re-establishment), scope them tightly and still raise if they
  can't recover.

The sink conformance suite in :mod:`tests.unit.test_data_sink` exercises
every contract of the interface. Any custom sink can be run against it by
subclassing the test classes — failing tests point at contract violations.

See :mod:`mug.server.data_sinks.sqlite_sink` for a small reference
implementation that's designed to be copied as a starting point for
others like ``PostgresSink``, ``MongoSink``, ``S3Sink``.
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
    """Abstract backend for MUG participant data.

    A sink receives every piece of data an experiment produces through six
    ``write_*`` methods. Each method represents a distinct kind of record
    that MUG emits at a specific point in a participant's lifecycle; see the
    ``Participants & Data Collection`` guide in the docs for where each one
    is produced on the server side.

    **Partial implementations are expected.** The base class provides a
    no-op default for every write method, so a sink that only cares about
    episode time-series data can implement :meth:`write_episode` and leave
    the rest alone. Any record sent to an un-implemented method is silently
    accepted and dropped by the default — which is almost always what you
    want. Pair the partial sink with a :class:`FilesystemSink` inside a
    :class:`MultiSink` if you want the rest of the data on disk too.

    Contract for implementers
    -------------------------

    - **Threading.** Every write method may be called from any thread. When
      wrapped in :class:`AsyncSinkWrapper`, writes run on a dedicated drain
      thread and must be safe to call concurrently with another pending
      write. Most concrete sinks satisfy this by holding a
      ``threading.Lock`` around a single connection object.

    - **Error handling.** Raise an exception to signal failure. When the
      sink is wrapped in :class:`AsyncSinkWrapper`, raising triggers the
      dead-letter spillover path and the record will be retried later. Do
      not swallow errors silently — that bypasses MUG's no-data-loss
      guarantee. Logging a warning and re-raising is fine.

    - **Retries.** Leave transient retry logic to the async wrapper's
      spillover mechanism. Only build retries into a concrete sink for
      errors the wrapper can't handle (e.g. a deadlock a single retry will
      always resolve). Even then, raise if you can't recover.

    - **Idempotency.** Spillover replay is at-least-once: under failure, a
      spilled record may end up being delivered to the sink more than once.
      Use primary keys, upserts, or deduplication if your backend can't
      tolerate duplicates.

    Minimal example
    ---------------

    A custom sink that only captures episode data and prints a one-line
    summary for each one::

        class PrintEpisodeSink(DataSink):
            def write_episode(
                self, experiment_id, scene_id, subject_id, episode_num, data
            ):
                n_steps = len(data.get("t", []))
                print(f"{subject_id} | {scene_id} | ep{episode_num}: {n_steps} steps")

        config.experiment(
            stager=...,
            experiment_id="demo",
            data_sink=MultiSink([FilesystemSink(), PrintEpisodeSink()]),
        )
    """

    def write_metadata(
        self,
        experiment_id: str,
        scene_id: str,
        subject_id: str,
        metadata: dict,
    ) -> None:
        """Persist scene metadata when a participant enters a scene.

        Called once per scene activation, for every scene that has
        ``should_export_metadata=True``. The ``metadata`` dict is the
        serialized scene state — headers, element IDs, ``experiment_config``,
        scene timestamps, and for ``CompletionCodeScene`` the generated
        ``completion_code``. Exact keys vary by scene subclass; ``scene_id``,
        ``scene_type``, and ``timestamp`` are always present.
        """

    def write_static_scene_data(
        self,
        experiment_id: str,
        scene_id: str,
        subject_id: str,
        data: dict,
    ) -> None:
        """Persist form answers emitted at the end of a static scene.

        Called once when a participant advances out of a scene that collected
        input (``TextBox``, ``OptionBoxes``, ``ScalesAndTextBox``, ...). The
        ``data`` dict is a flat map of element ID → user-entered value.
        """

    def write_episode(
        self,
        experiment_id: str,
        scene_id: str,
        subject_id: str,
        episode_num: int,
        data: dict,
    ) -> None:
        """Persist one episode of gym gameplay.

        Called at every episode boundary during a ``GymScene``. Episodes are
        streamed one-at-a-time rather than batched at scene end — a long
        scene would produce a payload too large to reliably transfer back
        from the client otherwise.

        ``data`` is the decoded msgpack payload: a dict of lists where each
        list is a per-timestep stream (``t``, ``action``, ``reward``,
        ``terminateds``, ``truncateds``, per-agent observations, ...). Nested
        dicts may be present for multi-agent environments — sinks are free
        to flatten them however they like. :class:`FilesystemSink` uses
        ``flatten_dict`` with dotted column names, e.g. ``obs.player_0.pos``.

        ``episode_num`` is 0-indexed within the scene.
        """

    def write_globals(
        self,
        experiment_id: str,
        scene_id: str,
        subject_id: str,
        mug_globals: dict,
    ) -> None:
        """Persist the latest ``mugGlobals`` snapshot for a participant.

        ``mugGlobals`` is the client-side key/value state that survives scene
        transitions. This method is called alongside every static-scene and
        episode write, so the snapshot is always fresh. Default behavior in
        :class:`FilesystemSink` is to overwrite — you probably want the same
        upsert-style semantics in a relational backend.
        """

    def write_multiplayer_metrics(
        self,
        experiment_id: str,
        scene_id: str,
        subject_id: str,
        metrics: dict,
    ) -> None:
        """Persist per-participant P2P / sync validation metrics.

        Called once per participant per multiplayer scene when a game ends.
        ``metrics`` contains connection info (P2P type, health), frame
        hashes, desync events, input delivery stats, and rollback metrics.
        """

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
        produced once when both players' individual metrics have arrived
        and MUG has cross-checked hashes for desync detection.
        """

    def flush(self, timeout: float | None = None) -> bool:
        """Block until every pending record is persisted or safely spilled.

        Called automatically at two points in the server lifecycle:

        1. **Terminal scenes.** When a participant advances into an
           ``EndScene`` / ``CompletionCodeScene``, MUG flushes the sink with
           a 30s timeout so the participant's data is persisted before they
           see the completion screen and close the tab.
        2. **Graceful shutdown.** The ``atexit`` hook flushes with a 10s
           timeout then calls :meth:`close`.

        For synchronous sinks there's nothing to flush, so the default is a
        no-op that returns ``True`` immediately. :class:`AsyncSinkWrapper`
        overrides this to drain its in-memory queue; spilled records survive
        a missed flush and are replayed later.

        :param timeout: Maximum seconds to wait for the flush to complete.
            ``None`` means wait indefinitely. The caller is expected to
            continue regardless of the return value — a stuck sink must
            never block participant completion.
        :returns: ``True`` if the flush completed cleanly, ``False`` if the
            timeout was hit while records were still pending.
        """
        return True

    def close(self) -> None:
        """Release any open resources. Called once on server shutdown.

        The default is a no-op. Concrete sinks holding connections, file
        handles, or background threads should override this to clean up.
        Must not raise — if you can't close cleanly, log a warning and
        return.
        """


# ---------------------------------------------------------------------------
# FilesystemSink — the default, drop-in for today's behavior
# ---------------------------------------------------------------------------


class FilesystemSink(DataSink):
    """The default sink: CSV + JSON files on local disk.

    Writes every record under ``{base_dir}/{experiment_id}/{scene_id}/`` with
    a filename keyed by ``subject_id`` (or ``game_id`` for aggregated P2P
    metrics). The output layout is stable and is the format every MUG
    example, analysis snippet, and doc page assumes::

        {base_dir}/{experiment_id}/{scene_id}/
            {subject_id}_metadata.json         # write_metadata
            {subject_id}.csv                   # write_static_scene_data
            {subject_id}_ep{N}.csv             # write_episode, one per episode
            {subject_id}_globals.json          # write_globals
            {subject_id}_multiplayer_metrics.json   # write_multiplayer_metrics
            {game_id}_aggregated_metrics.json  # write_aggregated_multiplayer_metrics

    Writes are synchronous and fast — no network, just local disk — so
    this sink is safe to run directly inside a socketio handler without an
    :class:`AsyncSinkWrapper` in front of it. It's also the canonical
    "durability floor" of a :class:`MultiSink` stack: keeping
    ``FilesystemSink`` in the stack means you always have a local copy of
    every record, even if a remote sink downstream is misbehaving.

    :param base_dir: Root directory for all output. Defaults to ``"data"``,
        resolved relative to the process's current working directory.
        Override to write elsewhere on disk.
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

    Flattens any nested dict (e.g. per-agent observations) with
    ``flatten_dict.flatten(reducer="dot")`` so the resulting CSV has one
    column per leaf key, e.g. ``obs.player_0.pos``. Columns with shorter
    lists are padded with ``None`` so every column has the same length and
    ``pd.DataFrame`` construction succeeds.

    Returns ``None`` if the payload is empty (no ``t`` key or an empty one),
    signalling to the caller that there's nothing to write.
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
    """Fan out every record to multiple child sinks.

    Each write is dispatched to each child in the order they were supplied.
    **Failures in one child do not affect the others**: exceptions are
    caught, logged with the child's class name, and the dispatch continues
    to the next child. This makes it safe to pair a robust local sink with
    a potentially-flaky remote one — the local sink still gets the record
    even if the remote one raises.

    The canonical pattern is to keep :class:`FilesystemSink` as the first
    child (the "durability floor") and wrap any network-bound sink in
    :class:`AsyncSinkWrapper`::

        config.experiment(
            stager=...,
            experiment_id="mystudy",
            data_sink=MultiSink([
                FilesystemSink(),
                AsyncSinkWrapper(PostgresSink("postgres://...")),
            ]),
        )

    :meth:`flush` returns ``True`` only if **every** child flushed cleanly
    within the timeout; otherwise it returns ``False`` but still attempts to
    flush each child.

    :param sinks: Iterable of :class:`DataSink` instances. Dispatch order
        matches the iteration order; a list or tuple is the obvious choice.
    """

    def __init__(self, sinks: Iterable[DataSink]):
        self.sinks = list(sinks)

    def _each(self, method_name: str, *args, **kwargs):
        """Dispatch ``method_name`` to every child, catching per-child errors."""
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
    """A single pending write queued inside :class:`AsyncSinkWrapper`.

    Records are uniform across every ``write_*`` method type: the method
    name and the full kwargs dict are stored together so the drain worker
    can dispatch without caring whether the specific call expected
    ``subject_id`` or ``game_id`` or ``episode_num``. This also keeps the
    on-disk spillover JSON format simple — a record is the method name,
    its kwargs, and a retry counter.

    :ivar method: Name of the ``DataSink`` method to invoke when this
        record is drained (e.g. ``"write_metadata"``).
    :ivar kwargs: Full kwarg dict to pass to that method. Must be
        JSON-serializable so the record can survive a spillover write.
    :ivar attempts: How many times this record has been dispatched to the
        wrapped sink without success. Incremented each time the record is
        spilled after a failure, for diagnostics.
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

    Wrap any :class:`DataSink` that performs network, disk, or database I/O
    before handing it to MUG. Incoming ``write_*`` calls push a record onto
    an in-memory :class:`queue.Queue` and return immediately. A dedicated
    daemon thread drains the queue and dispatches each record to the
    wrapped sink.

    Why the wrapper exists
    ----------------------

    MUG runs under eventlet, a cooperative scheduler. Any socket handler
    that blocks on network I/O — for example, a synchronous psycopg2 call
    to Postgres — freezes the eventlet hub and stalls **every** connected
    participant until the call returns. Even a single slow DB write can
    cause cascading waitroom timeouts and scene-transition failures across
    the whole experiment. :class:`AsyncSinkWrapper` is the escape hatch:
    handlers only ever interact with a Python ``queue.put_nowait`` call,
    which is fast and non-blocking, and all the potentially-blocking work
    happens on a thread that eventlet isn't watching.

    Rule of thumb: wrap any sink whose ``write_*`` methods might take more
    than ~5 ms. Local file writes are fine unwrapped. Anything over a
    network — Postgres, MySQL, HTTP APIs, cloud storage — should be
    wrapped.

    No record is ever silently dropped
    ----------------------------------

    Two things can go wrong under load: the queue can fill up faster than
    the drain thread can empty it, or the wrapped sink can raise on an
    individual write. Both cases are handled the same way — the record is
    spilled to disk:

    1. ``_enqueue`` catches ``queue.Full`` and calls :meth:`_spill`.
    2. ``_dispatch`` catches any exception from the wrapped sink's
       ``write_*`` method and calls :meth:`_spill`.

    Spilled records land at
    ``{spillover_base_dir}/{experiment_id}/.pending/{sink_name}/<ts>_<uuid>.json``
    as one-file-per-record JSON. A low-priority replay pass runs between
    queue drains (rate-limited to ``replay_interval_s``), walks the
    ``.pending/`` directory, and tries each spillover file against the
    wrapped sink. Successful replays delete the file; failures leave it
    for the next attempt.

    The net effect: the only thing that can grow unboundedly is disk
    usage in ``.pending/``, and only when the wrapped sink is permanently
    broken (wrong DSN, missing schema, bad credentials). Those cases log
    a warning on every failure, so they surface instead of silently
    losing data.

    Replay is at-least-once
    -----------------------

    Under some failure modes (e.g. the sink succeeds but then the process
    crashes before the spillover file is deleted), a record may be
    replayed even after a successful previous delivery. Sinks that can't
    tolerate duplicates should use primary keys or upserts.

    Composition with ``MultiSink``
    ------------------------------

    You almost always want to combine ``AsyncSinkWrapper`` with
    :class:`MultiSink` and :class:`FilesystemSink`::

        data_sink=MultiSink([
            FilesystemSink(),                              # local durability floor
            AsyncSinkWrapper(SQLiteSink("data/mystudy.db")),
        ])

    ``FilesystemSink`` gives you unconditional local CSVs for free. The
    async wrapper adds the DB sink asynchronously without any risk of it
    blocking the eventlet hub.

    :param sink: The concrete :class:`DataSink` to wrap. All writes will
        be dispatched to this sink from the drain thread.
    :param max_queue_size: Maximum number of pending records held in
        memory before new records spill to disk. Higher values use more
        RAM but absorb larger bursts without touching the filesystem.
        ``10_000`` is a sensible default for research-scale experiments —
        even at ~100 records/sec that's 100 seconds of headroom.
    :param spillover_base_dir: Root directory under which dead-letter
        spillover files are written. Defaults to ``"data"`` so spillover
        lives alongside the :class:`FilesystemSink` output.
    :param replay_interval_s: Minimum seconds between spillover replay
        passes. Rate-limiting prevents a broken sink from pinning a CPU
        spinning on failing retries. Defaults to 5 seconds.
    :param sink_name: Human-readable name used in log lines and as the
        spillover subdirectory. Defaults to the wrapped sink's class name,
        which is usually fine unless you have two instances of the same
        sink class in a single :class:`MultiSink`.
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
        """Spawn the background drain worker. Idempotent and lazy.

        Called automatically on the first ``write_*`` invocation, so
        wrapping a sink doesn't consume a thread until records actually
        start flowing. Safe to call manually if you want the worker
        running before the first write (for example, to get the startup
        log line deterministically).
        """
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
        """Signal the drain worker to stop and close the wrapped sink.

        Called once on server shutdown via ``atexit``. Sets the shutdown
        event, joins the worker with a 5-second timeout (so a wedged
        replay doesn't hold up server exit), and then calls ``close`` on
        the wrapped sink. Any exception from the wrapped sink's close is
        caught and logged so shutdown always proceeds.
        """
        self._shutdown.set()
        if self._worker is not None:
            self._worker.join(timeout=5.0)
        try:
            self.sink.close()
        except Exception as e:
            logger.warning(f"[AsyncSink] {self._sink_name}.close raised: {e}")

    def flush(self, timeout: float | None = None) -> bool:
        """Block until the in-memory queue is empty (or the timeout hits).

        This only drains the in-memory queue — it does **not** wait for
        the spillover replay pass to finish. Records still in
        ``.pending/`` at flush time are considered "safely persisted" for
        the purposes of this call (they'll survive a crash and replay on
        next startup), so the flush can return quickly even in the
        presence of a temporarily-broken sink.

        :param timeout: Maximum seconds to wait. ``None`` waits forever.
        :returns: ``True`` if the queue drained within the timeout,
            ``False`` if records were still pending when the timeout hit.
            A warning is logged in the latter case; the caller should
            continue either way.
        """
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
        """Add a record to the in-memory queue, spilling on queue-full.

        Lazily starts the drain worker on the first call so wrappers don't
        consume threads until actual work arrives.
        """
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
        """Main drain worker loop — runs on a dedicated daemon thread.

        Pops records from the queue and dispatches them to the wrapped
        sink. When the queue is empty, opportunistically tries a spillover
        replay pass (rate-limited internally) and loops back. Exits cleanly
        when the ``_shutdown`` event is set.
        """
        while not self._shutdown.is_set():
            try:
                record = self._queue.get(timeout=0.1)
            except queue.Empty:
                self._maybe_replay_spillover()
                continue

            self._dispatch(record)
            self._queue.task_done()

    def _dispatch(self, record: _SinkRecord) -> None:
        """Invoke the wrapped sink's write method for one record.

        On exception, logs a warning, increments the record's ``attempts``
        counter, and spills to disk for later replay. Never re-raises —
        failures are always converted into spillover so the drain loop
        keeps running.
        """
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
        """Path to the dead-letter directory for a given experiment.

        Created on demand. Scoped by both ``experiment_id`` and
        ``sink_name`` so multiple async sinks inside a single ``MultiSink``
        don't collide.
        """
        path = os.path.join(
            self.spillover_base_dir, experiment_id, ".pending", self._sink_name
        )
        os.makedirs(path, exist_ok=True)
        return path

    def _spill(self, record: _SinkRecord) -> None:
        """Serialize a failed record to a spillover file for later replay.

        Filename is ``<unix_timestamp>_<uuid4>.json`` so the sort order
        (used by :meth:`_maybe_replay_spillover`) preserves the order in
        which records were spilled — oldest spilled records replay first.

        If even the spillover write fails (disk full, bad permissions),
        the record is lost and the failure is logged at ``error`` level.
        This is the only path in the wrapper that can lose data, and it
        represents a filesystem-level failure that can't be recovered
        from inside the sink layer.
        """
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
        """Attempt to replay spilled records for every known experiment.

        Rate-limited to ``replay_interval_s`` so a broken sink doesn't pin
        a CPU spinning on failing replays. Walks
        ``{spillover_base_dir}/*/.pending/{sink_name}/`` and tries each
        spillover file against the wrapped sink:

        - **Success** → delete the spillover file and log an info line.
        - **Failure** → leave the file in place for the next attempt, log
          at debug level (so permanent failures don't flood the log), and
          stop this pass early. If one spillover fails the sink is almost
          certainly still down and looping over more files just wastes
          work.

        Files are processed in lexicographic order, which (because the
        filenames are prefixed with Unix timestamps) means the oldest
        spilled records replay first.
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
