"""The pooled matchmaker forms and runs many peer meshes at once.

These tests drive ``mug.participant.PooledMeshMatchmaker`` directly: several
connections join at once, each through its own ``play`` call, and the pool forms
every room it can and runs them concurrently. Where the single ``MeshMatchmaker``
forms and runs one mesh at a time, the pool:

- forms two rooms from four concurrent connections, runs both, and resolves every
  seat with the shared, verified outcome of its own room;
- leaves a lone connection waiting until a later connection completes its room, then
  resolves it too.

There is no socket and no real clock: the replica is self-contained, the frames land
in an in-memory list, and the loop runs at ``fps=0``, so the whole rendezvous is
deterministic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, cast

from mug.game.mesh import ReplicaFrame
from mug.game.mesh_session import MeshGameSpec
from mug.gateway import Gateway
from mug.kernel import PrincipalRef
from mug.participant import PooledMeshMatchmaker
from mug.storage import InMemoryStore

_EPISODE_LEN = 4


class _LineReplica:
    """A deterministic two-seat replica whose state depends on a generator."""

    def __init__(self, peers: tuple[str, ...], *, seed: int) -> None:
        self._peers = tuple(sorted(peers))
        self._t = 0
        self._rng = seed & 0x7FFFFFFF
        self._pos: dict[str, int] = dict.fromkeys(self._peers, 0)

    def step(self, actions: Mapping[str, int]) -> ReplicaFrame:
        self._t += 1
        self._rng = (self._rng * 1103515245 + 12345) & 0x7FFFFFFF
        noise = self._rng % 3 - 1
        for actor in self._peers:
            self._pos[actor] += (int(actions.get(actor, 0)) - 1) + noise
        observation = [self._pos[actor] for actor in self._peers]
        observation.extend((self._t, self._rng))
        return ReplicaFrame(
            observation=observation,
            rewards={actor: -1.0 for actor in self._peers},
            terminated=self._t >= _EPISODE_LEN,
            truncated=False,
            info={},
        )

    def snapshot(self) -> object:
        return (tuple(sorted(self._pos.items())), self._t, self._rng)

    def restore(self, state: object) -> None:
        positions, step, rng = cast(
            "tuple[tuple[tuple[str, int], ...], int, int]", state
        )
        self._pos = dict(positions)
        self._t = step
        self._rng = rng


def _spec() -> MeshGameSpec:
    """Build a two-seat mesh game over the self-contained line replica."""
    return MeshGameSpec(
        channel_key="p2p-game",
        size=2,
        make_replica=lambda peers, seed: _LineReplica(peers, seed=seed),
        action_bindings={"a": 0, "d": 2},
        default_action=1,
        seed=12345,
        fps=0,
        max_steps=_EPISODE_LEN + 5,
        input_delay=2,
        snapshot_interval=3,
    )


def _principal(index: int) -> PrincipalRef:
    """Return a well-formed participant principal for one connection."""
    return PrincipalRef(
        kind="participant",
        id=f"participant_019b6000-0000-7000-8000-0000000004{index:02x}",
    )


def _visit(index: int) -> str:
    """Return a well-formed visit id for one connection."""
    return f"visit_019b6000-0000-7000-8000-0000000005{index:02x}"


def _join(matchmaker: PooledMeshMatchmaker, index: int) -> asyncio.Task[Any]:
    """Start one connection's ``play`` as a task with its own frame collector."""
    frames: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        frames.append(frame)

    task = asyncio.ensure_future(
        matchmaker.play(
            visit_id=_visit(index),
            activity_key="play",
            principal=_principal(index),
            action=lambda: 1,
            send=send,
        )
    )
    task.frames = frames  # type: ignore[attr-defined]
    return task


async def _settle(tasks: list[asyncio.Task[Any]]) -> None:
    """Yield the loop enough times for the runnable rooms to finish."""
    for _ in range(200):
        await asyncio.sleep(0)


async def test_four_concurrent_connections_form_two_rooms() -> None:
    """Four connections form two rooms, both run, and every seat resolves verified."""
    matchmaker = PooledMeshMatchmaker(Gateway(), InMemoryStore(), _spec())
    tasks = [_join(matchmaker, index) for index in range(4)]

    outcomes = await asyncio.gather(*tasks)

    assert all(outcome.verified for outcome in outcomes)
    # Two rooms formed: two distinct shared episode streams, each shared by a pair.
    streams = [outcome.stream_id for outcome in outcomes]
    assert len(set(streams)) == 2
    for stream_id in set(streams):
        assert streams.count(stream_id) == 2
    # Every seat received its room's frames.
    for task in tasks:
        assert len(task.frames) == _EPISODE_LEN  # type: ignore[attr-defined]


async def test_a_lone_connection_waits_until_a_partner_joins() -> None:
    """A third connection waits until a fourth completes its room, then resolves."""
    matchmaker = PooledMeshMatchmaker(Gateway(), InMemoryStore(), _spec())
    tasks = [_join(matchmaker, index) for index in range(3)]

    await _settle(tasks)

    done = [task for task in tasks if task.done()]
    waiting = [task for task in tasks if not task.done()]
    assert len(done) == 2  # one room formed and ran
    assert len(waiting) == 1  # the odd connection is still waiting

    tasks.append(_join(matchmaker, 3))  # a partner arrives
    outcomes = await asyncio.gather(*tasks)

    assert all(outcome.verified for outcome in outcomes)
    # The two rooms are two distinct shared streams; the once-waiting seat is paired.
    streams = [outcome.stream_id for outcome in outcomes]
    assert len(set(streams)) == 2
