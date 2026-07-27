"""Two participants on two processes meet, and play one mesh together.

``MeshMatchmaker`` and ``PooledMeshMatchmaker`` match the connections one process
holds. A deployment of two replicas therefore has two waiting rooms of one
participant each, and neither ever forms a group. These tests drive
``NodeMeshMatchmaker`` instead: two nodes, each with its own gateway, its own
matchmaker, and its own sockets, sharing nothing but the store and the bus.

A node here is what a node is in production: a process that holds some sockets and
none of the others. The two matchmakers hold **separate** ``_seats`` maps and
separate formation services, so a mesh only runs if the rendezvous matched across
them and the bus carried the seat's input and its frames. The store is one
``InMemoryStore`` and the bus is ``StoreBus`` over that same store, so every message
between the nodes is a durable write that a second process could equally have read.

The replica is the deterministic line replica the pooled-matchmaker tests use, the
loop runs at ``fps=0``, and no socket is opened.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from typing import Any, cast

import pytest

from mug.game.mesh import ReplicaFrame
from mug.game.mesh_session import MeshGameSpec
from mug.gateway import Gateway
from mug.interactions.bus import LocalBus, NodeLink, StoreBus
from mug.interactions.rendezvous import DurableRendezvous, Ticket
from mug.kernel import PrincipalRef
from mug.nodes import Node
from mug.participant import NodeMeshMatchmaker
from mug.storage import InMemoryStore

_EPISODE_LEN = 4

# One deployment secret, so two processes derive one command identity for one
# retried envelope. This is the topology rule, held here because the test is two
# processes in every way that matters.
_SECRET = b"w18-shared-deployment-secret"


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


def _spec(size: int = 2, make_replica: Any = None) -> MeshGameSpec:
    """Build a mesh game of the given size over the self-contained line replica."""
    return MeshGameSpec(
        channel_key="p2p-game",
        size=size,
        make_replica=make_replica
        or (lambda peers, seed: _LineReplica(peers, seed=seed)),
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


def _instant(gateway: Gateway) -> str:
    """Return the current instant in the canonical wire form."""
    return gateway.clock().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class _Racing(InMemoryStore):
    """A store whose commit yields, so two processes genuinely interleave.

    The in-memory store commits without ever awaiting, so two coroutines that
    claim at the same moment in fact run one after the other and the second reads
    what the first already wrote. A real store awaits its round trip, and that is
    where the race lives. Yielding once before the write puts it back.
    """

    async def commit(self, **written: Any) -> Any:
        await asyncio.sleep(0)
        return await super().commit(**written)


class _Process:
    """One process of the deployment: its own gateway, node, and matchmaker."""

    def __init__(
        self,
        node_id: str,
        store: InMemoryStore,
        bus: Any,
        spec: MeshGameSpec | None = None,
    ) -> None:
        self.gateway = Gateway(secret=_SECRET)
        self.store = store
        self.link = NodeLink(bus, node_id, new_id=self.gateway.new_id)
        self.node = Node(
            node_id=node_id,
            link=self.link,
            rendezvous=DurableRendezvous(
                store,
                new_id=self.gateway.new_id,
                now=lambda: _instant(self.gateway),
            ),
        )
        self.matchmaker = NodeMeshMatchmaker(
            self.gateway, store, spec or _spec(), self.node
        )
        self.frames: dict[int, list[dict[str, Any]]] = {}

    def start(self) -> None:
        """Start this process's bus pump."""
        self.link.start()

    async def stop(self) -> None:
        """Stop this process's bus pump."""
        await self.link.stop()

    def join(self, index: int, *, action: int = 1) -> asyncio.Task[Any]:
        """Start one of this process's sockets playing, holding one action."""
        frames: list[dict[str, Any]] = []
        self.frames[index] = frames

        async def send(frame: dict[str, Any]) -> None:
            frames.append(frame)

        return asyncio.ensure_future(
            self.matchmaker.play(
                visit_id=_visit(index),
                activity_key="play",
                principal=_principal(index),
                action=lambda: action,
                send=send,
            )
        )


def _deployment(
    count: int = 2, spec: MeshGameSpec | None = None
) -> tuple[InMemoryStore, list[_Process]]:
    """Build one store, one durable bus over it, and ``count`` processes."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    bus = StoreBus(store, new_id=gateway.new_id)
    return store, [
        _Process(f"node-{index}", store, bus, spec) for index in range(count)
    ]


async def _finish(tasks: list[asyncio.Task[Any]], seconds: float = 5.0) -> list[Any]:
    """Wait for every seat to resolve, and fail loudly rather than hang."""
    return list(await asyncio.wait_for(asyncio.gather(*tasks), seconds))


async def test_two_participants_on_two_processes_play_one_mesh() -> None:
    """The whole point: two nodes, one waiting room, one run, one shared episode."""
    _, processes = _deployment()
    for process in processes:
        process.start()
    tasks = [processes[0].join(0), processes[1].join(1)]
    outcomes = await _finish(tasks)
    for process in processes:
        await process.stop()

    assert len(outcomes) == 2
    # One mesh means one captured episode, so both seats name the same stream.
    assert outcomes[0].stream_id == outcomes[1].stream_id
    assert all(outcome.verified for outcome in outcomes)
    # Each node wrote frames to its own socket, so the frames crossed the bus in
    # one direction and the actions crossed it in the other.
    assert processes[0].frames[0]
    assert processes[1].frames[1]


async def test_the_second_node_is_the_one_that_did_not_claim() -> None:
    """Exactly one process runs the mesh; the other holds a socket and relays.

    The proof is the seat map: the process that claimed the group built a join for
    both members, and the process that did not built none. If both had claimed, two
    meshes would have run and the two seats would name two episodes.
    """
    store, processes = _deployment()
    for process in processes:
        process.start()
    tasks = [processes[0].join(0), processes[1].join(1)]
    await _finish(tasks)
    for process in processes:
        await process.stop()

    rooms: list[dict[str, Any]] = [
        cast("dict[str, Any]", state)
        for _, state in store.scan_aggregates()
        if isinstance(state, dict) and "owner_node" in state
    ]
    assert len(rooms) == 1
    assert rooms[0]["owner_node"] in {"node-0", "node-1"}
    members = cast("list[dict[str, Any]]", rooms[0]["members"])
    assert {member["node_id"] for member in members} == {
        "node-0",
        "node-1",
    }


async def test_a_remote_seat_plays_the_action_its_own_node_holds() -> None:
    """The action a participant holds reaches the process that runs the mesh.

    Both seats hold a non-default action. If the input did not cross, the remote
    seat would have played the game's default for the whole episode and the two
    replicas would still agree -- so the evidence is the recorded trajectory, not
    the parity verdict.
    """
    _, processes = _deployment()
    for process in processes:
        process.start()
    tasks = [processes[0].join(0, action=0), processes[1].join(1, action=2)]
    outcomes = await _finish(tasks)
    for process in processes:
        await process.stop()

    assert outcomes[0].verified
    # A frame carries the confirmed canonical step, which names the action every
    # seat played. Both held actions are in it, so both crossed to the process
    # that ran the mesh; a dropped input would show the game's default instead.
    played: list[list[int]] = []
    for frame in processes[1].frames[1]:
        confirmed = frame.get("confirmed")
        if isinstance(confirmed, dict):
            actions = cast("dict[str, Any]", confirmed).get("actions", {})
            played.append(
                sorted(int(value) for value in cast("dict[str, Any]", actions).values())
            )
    # The engine's input delay means the first steps run on the default before a
    # held action promotes, so the claim is about the settled step: each seat
    # played the action its own node holds, and neither played the default.
    assert played[-1] == [0, 2]


async def test_a_lone_participant_waits_in_the_shared_room() -> None:
    """One participant on one node waits, and is visible to the other node."""
    _, processes = _deployment()
    for process in processes:
        process.start()
    task = processes[0].join(0)
    for _ in range(50):
        await asyncio.sleep(0)
    # The other process reads the same waiting room, which is the whole point.
    waiting = await processes[1].node.rendezvous.waiting("p2p-game")
    assert [ticket.node_id for ticket in waiting] == ["node-0"]
    assert not task.done()

    partner = processes[1].join(1)
    await _finish([task, partner])
    for process in processes:
        await process.stop()
    assert not await processes[0].node.rendezvous.waiting("p2p-game")


async def test_a_claim_is_taken_by_exactly_one_process() -> None:
    """Two processes claiming at once do not both get the group.

    This is the fence. Both read the waiting list at the same revision and both
    write it back; the store refuses the second, which reads again and finds the
    tickets gone.
    """
    store = _Racing()
    gateway = Gateway(secret=_SECRET)
    now = lambda: _instant(gateway)  # noqa: E731
    one = DurableRendezvous(store, new_id=gateway.new_id, now=now)
    two = DurableRendezvous(store, new_id=gateway.new_id, now=now)
    for index in range(2):
        await one.submit(
            "p2p-game",
            Ticket(
                enrollment_id=f"enrollment_019b6000-0000-7000-8000-00000000060{index}",
                visit_id=_visit(index),
                node_id=f"node-{index}",
                connection_id=f"connection-{index}",
                enqueued_at=now(),
            ),
        )
    claims = await asyncio.gather(one.claim("p2p-game", 2), two.claim("p2p-game", 2))
    assert sorted(len(claim) for claim in claims) == [0, 2]


async def test_a_ticket_older_than_its_life_is_not_matched() -> None:
    """A node that went away does not leave a group forming around a dead socket."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    now = lambda: _instant(gateway)  # noqa: E731
    rendezvous = DurableRendezvous(
        store, new_id=gateway.new_id, now=now, ticket_ttl_seconds=60.0
    )
    live = DurableRendezvous(store, new_id=gateway.new_id, now=now)
    await rendezvous.submit(
        "p2p-game",
        Ticket(
            enrollment_id="enrollment_019b6000-0000-7000-8000-000000000610",
            visit_id=_visit(0),
            node_id="node-gone",
            connection_id="connection-gone",
            enqueued_at="2020-01-01T00:00:00.000000Z",
        ),
    )
    await rendezvous.submit(
        "p2p-game",
        Ticket(
            enrollment_id="enrollment_019b6000-0000-7000-8000-000000000611",
            visit_id=_visit(1),
            node_id="node-1",
            connection_id="connection-1",
            enqueued_at=now(),
        ),
    )
    assert await rendezvous.claim("p2p-game", 2) == ()
    # The stale ticket is gone, so it cannot be matched by a later sweep either.
    assert [ticket.node_id for ticket in await live.waiting("p2p-game")] == ["node-1"]


async def test_a_participant_who_leaves_is_out_of_the_shared_room() -> None:
    """A cancelled wait takes its ticket with it, on whichever node held it."""
    _, processes = _deployment()
    for process in processes:
        process.start()
    task = processes[0].join(0)
    for _ in range(50):
        await asyncio.sleep(0)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    for process in processes:
        await process.stop()
    assert not await processes[1].node.rendezvous.waiting("p2p-game")


async def test_one_process_still_forms_a_mesh_on_its_own() -> None:
    """A deployment of one process is unchanged: both seats are local."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    bus = LocalBus()
    process = _Process("node-only", store, bus)
    process.start()
    tasks = [process.join(0), process.join(1)]
    outcomes = await _finish(tasks)
    await process.stop()
    assert outcomes[0].stream_id == outcomes[1].stream_id
    assert all(outcome.verified for outcome in outcomes)
    assert gateway is not process.gateway


@pytest.mark.parametrize("count", [3])
async def test_a_third_participant_waits_for_the_next_group(count: int) -> None:
    """Three waiting for a two-seat game means one mesh and one still waiting."""
    _, processes = _deployment(count)
    for process in processes:
        process.start()
    tasks = [process.join(index) for index, process in enumerate(processes)]
    done, pending = await asyncio.wait(tasks, timeout=5.0)
    for process in processes:
        await process.stop()
    for task in pending:
        task.cancel()
    assert len(done) == 2
    assert len(pending) == 1


async def test_one_node_relaying_two_seats_keeps_them_apart() -> None:
    """A node that holds two seats of one room writes each frame to its own seat.

    A deployment does not hand out one socket per replica. The ordinary case is a
    process holding several of a room's participants and relaying for all of them,
    and a frame that reached the wrong one would be another participant's view of
    the game.
    """
    _, processes = _deployment(2, _spec(size=3))
    for process in processes:
        process.start()
    tasks = [
        processes[0].join(0),
        processes[0].join(1),
        processes[1].join(2),
    ]
    await _finish(tasks)
    for process in processes:
        await process.stop()

    # Each of the relaying node's two seats received frames, and each frame names
    # that seat and no other.
    for index in (0, 1):
        frames = [
            frame for frame in processes[0].frames[index] if "seat_key" in frame
        ]
        assert frames
        assert len({frame["seat_key"] for frame in frames}) == 1
    seats = {
        index: {frame["seat_key"] for frame in processes[0].frames[index]}
        for index in (0, 1)
    }
    assert seats[0] != seats[1]


async def test_a_mesh_that_cannot_run_frees_every_seat() -> None:
    """A run that fails tells every seat, wherever it is held.

    A seat that was never told would wait for a frame that is not coming, on a
    socket the participant is still looking at. The remote seat is the one that
    matters here: it has nothing of its own to fail on.
    """

    def refuse(peers: tuple[str, ...], seed: int) -> _LineReplica:
        raise RuntimeError("this environment cannot be built")

    _, processes = _deployment(2, _spec(make_replica=refuse))
    for process in processes:
        process.start()
    tasks = [processes[0].join(0), processes[1].join(1)]
    done, pending = await asyncio.wait(tasks, timeout=5.0)
    for process in processes:
        await process.stop()
    for task in pending:
        task.cancel()

    assert not pending
    assert len(done) == 2
    for task in done:
        assert isinstance(task.exception(), Exception)
