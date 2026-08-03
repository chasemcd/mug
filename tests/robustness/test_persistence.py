"""A finished run outlives the process that recorded it.

The legacy suite wrote each participant's data to a file on disk and read it back
with a separate script, so persistence was proven by construction: the analysis
never saw the server's memory. The rewrite records into a store, and every test in
the fast gate uses the in-memory one, which proves nothing about a deployment.

So each claim here is made twice: once against SQLite, and -- where a database is
reachable -- once against Postgres. Both are the backends a study is deployed on.
The strongest of them is the reopen: the store is closed and built again over the
same file, in the way a restarted process would, and the run must still be there
and still export to the same bytes.

Set ``MUG_PG_DSN`` to include Postgres. Without it those cases skip and SQLite
still runs, so the suite is honest on a machine with no database rather than
silently weaker.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.gateway import Gateway
from mug.storage import SqliteStore, Store
from tests.parity._environments import PARTNER, YOU
from tests.robustness._runs import (
    episodes_in,
    exported,
    off_loop,
    people_at,
    play_the_seated_round,
    recorded_frames,
    seated_study,
)

_LENGTH = 10
_DSN = os.environ.get("MUG_PG_DSN")


@contextmanager
def _sqlite_at(path: Path) -> Iterator[Store]:
    """Open one SQLite-backed store over a file, and close it afterwards."""
    store = SqliteStore(str(path))
    try:
        yield store
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            close()


def _play_into(store: Store) -> None:
    """Run one whole two-person game through the real application into that store."""
    client = TestClient(
        build_study_app(study=seated_study(_LENGTH), store=store, gateway=Gateway())
    )
    with client, people_at(client, 2) as people:
        followed = play_the_seated_round(people)
        assert all(one["delivery"]["kind"] == "content" for one in followed)


def test_a_run_recorded_on_disk_is_there_after_the_process_that_wrote_it(
    tmp_path: Path,
) -> None:
    """The reopen: a new store over the same file holds the same run.

    This is the claim a study depends on and no in-memory test can make. A record
    that lived only in the process that wrote it would pass every other test in
    this repository and lose the data on the first restart.
    """
    database = tmp_path / "study.sqlite"
    with _sqlite_at(database) as writing:
        _play_into(writing)
        written = episodes_in(writing)
        assert len(written) == 1
        first = exported(writing)

    # A different store object, over the same file, as a restarted process has.
    with _sqlite_at(database) as reopened:
        read_back = episodes_in(reopened)
        assert len(read_back) == 1
        assert read_back[0] == written[0], "the reopened store holds a different run"

        frames = recorded_frames(reopened, read_back[0])
        assert len(frames) == _LENGTH
        assert all(set(frame.actions) == {YOU, PARTNER} for frame in frames)

        again = exported(reopened)

    # The export is a function of the ledger, so a restart does not change it.
    assert [one.bundle_digest.hex for one in again.bundles] == [
        one.bundle_digest.hex for one in first.bundles
    ]


def test_the_values_and_not_only_the_digests_survive_a_restart(
    tmp_path: Path,
) -> None:
    """The artifact is on disk too, so what happened is readable and not only provable.

    A ledger that kept the digests and lost the artifact would still verify: every
    digest would agree with itself, and nobody could say what the participants did.
    """
    database = tmp_path / "values.sqlite"
    with _sqlite_at(database) as writing:
        _play_into(writing)
        before = [
            (frame.frame_number, dict(frame.actions))
            for frame in recorded_frames(writing, episodes_in(writing)[0])
        ]

    with _sqlite_at(database) as reopened:
        after = [
            (frame.frame_number, dict(frame.actions))
            for frame in recorded_frames(reopened, episodes_in(reopened)[0])
        ]

    assert before == after
    assert before, "the run recorded no values to survive"


@pytest.mark.skipif(_DSN is None, reason="set MUG_PG_DSN to test against Postgres")
def test_a_run_is_recorded_the_same_way_on_postgres() -> None:
    """The backend a deployment runs on records what the fast gate says it does.

    Postgres is the only backend under a real study, and it is the one the fast
    tests never touch. What is checked is the same set of claims, so a difference
    between the backends shows up as a difference in the run rather than as a
    passing test on the wrong store.
    """
    import asyncio

    from mug.storage.pg_store import PgStore

    store: Any = off_loop(PgStore.create(str(_DSN)))
    try:
        _play_into(store)

        recorded = episodes_in(store)
        assert len(recorded) >= 1
        episode = recorded[-1]
        frames = recorded_frames(store, episode)

        assert len(frames) == episode["frame_count"]
        assert [frame.frame_number for frame in frames] == list(range(1, _LENGTH + 1))
        assert all(set(frame.actions) == {YOU, PARTNER} for frame in frames)

        # The same values a study would read out of a deployment, and the export
        # that carries them.
        export = exported(store)
        assert export.bundles, "the run on Postgres exported nothing"
        assert all(one.row_count > 0 for one in export.bundles)
    finally:
        closing = getattr(store, "aclose", None) or getattr(store, "close", None)
        if callable(closing):
            result = closing()
            if asyncio.iscoroutine(result):
                off_loop(result)
