"""The P2P wire tier drives each engine over a real duplex link, and keeps parity.

These tests move each peer engine to its own ``PeerNode`` and connect the nodes
with in-process duplex links that inject a real round-trip latency and drop input
packets. Now the round trip is genuine -- a peer's input arrives several frames
late -- so each engine predicts the missing input and rolls back when the real
input contradicts the prediction. The test proves the two things the tier owns:

- the codec round-trips every engine packet through a json-able wire message, so an
  input, a hash, and an end packet survive the link unchanged;
- a full mesh of nodes over lossy, latent links still reaches a byte-identical
  canonical trajectory on every peer, and the latency forces at least one rollback,
  so the distributed tier reproduces the synchronous coordinator's parity result.

There is no socket and no real network: the links are ``asyncio`` channels that
delay delivery and drop a fraction of the input packets, the deterministic model of
a WebRTC data channel. The engine's own input redundancy recovers the dropped
packets; the end path recovers through the node's per-tick re-announcement.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, cast

import pytest

from mug.game.mesh import EndPacket, HashPacket, InputPacket, PeerEngine, ReplicaFrame
from mug.game.wire import (
    PeerLink,
    PeerLinkClosed,
    PeerNode,
    decode,
    encode_end,
    encode_hash,
    encode_input,
)
from mug.kernel import Digest

_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000010f"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000010e"
_RECORDED_AT = "2026-07-21T00:00:00.000000Z"
_MESH_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)

_Snapshot = tuple[tuple[tuple[str, int], ...], int, int]


def _actor(index: int) -> str:
    """Return the canonical actor id for one peer index."""
    return f"actor_019b6000-0000-7000-8000-0000000001{index:02x}"


class LineWorld:
    """A deterministic multi-seat replica whose state depends on a generator.

    Each step moves every seat by its action and a shared generator noise term, so
    the state hash depends on the whole action history and on the generator; the
    snapshot captures the positions, the step count, and the generator, so a
    rollback replay reproduces the exact state.
    """

    def __init__(self, actors: tuple[str, ...], *, seed: int, episode_len: int) -> None:
        self._actors = tuple(sorted(actors))
        self._seed = seed
        self._episode_len = episode_len
        self._t = 0
        self._rng = seed & 0x7FFFFFFF
        self._pos: dict[str, int] = dict.fromkeys(self._actors, 0)

    def _noise(self) -> int:
        self._rng = (self._rng * 1103515245 + 12345) & 0x7FFFFFFF
        return self._rng % 3 - 1

    def step(self, actions: Mapping[str, int]) -> ReplicaFrame:
        self._t += 1
        noise = self._noise()
        for actor in self._actors:
            self._pos[actor] += (int(actions.get(actor, 1)) - 1) + noise
        observation = [self._pos[actor] for actor in self._actors]
        observation.extend((self._t, self._rng))
        return ReplicaFrame(
            observation=observation,
            rewards=dict.fromkeys(self._actors, -1.0),
            terminated=self._t >= self._episode_len,
            truncated=False,
            info={},
        )

    def snapshot(self) -> object:
        return (tuple(sorted(self._pos.items())), self._t, self._rng)

    def restore(self, state: object) -> None:
        positions, step, rng = cast("_Snapshot", state)
        self._pos = dict(positions)
        self._t = step
        self._rng = rng


# -- the in-process latency-and-loss duplex link -------------------------------


class _Pipe:
    """One direction of a link: deliver each message after a fixed tick delay.

    Every input packet after the first ``drop_every`` is dropped, the deterministic
    model of a lossy data channel; the engine's input redundancy recovers it. The
    control messages (hash, end) are delivered reliably.
    """

    def __init__(self, *, delay: float, drop_every: int) -> None:
        self._delay = delay
        self._drop_every = drop_every
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._sent = 0
        self._tasks: set[asyncio.Task[None]] = set()

    async def send(self, message: Mapping[str, Any]) -> None:
        if message.get("kind") == "input" and self._drop_every:
            self._sent += 1
            if self._sent % self._drop_every == 0:
                return
        task = asyncio.create_task(self._deliver(dict(message)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver(self, message: dict[str, Any]) -> None:
        await asyncio.sleep(self._delay)
        await self._queue.put(message)

    async def recv(self) -> dict[str, Any] | None:
        return await self._queue.get()

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()


class _DuplexEnd:
    """One end of a duplex link: send on the outbound pipe, receive on the inbound."""

    def __init__(self, out: _Pipe, inbound: _Pipe) -> None:
        self._out = out
        self._in = inbound

    async def send(self, message: Mapping[str, Any]) -> None:
        await self._out.send(message)

    async def recv(self) -> dict[str, Any] | None:
        return await self._in.recv()


def _duplex(
    *, delay: float, drop_every: int
) -> tuple[_DuplexEnd, _DuplexEnd, list[_Pipe]]:
    """Build one duplex link and return its two ends and its pipes, for teardown."""
    ab = _Pipe(delay=delay, drop_every=drop_every)
    ba = _Pipe(delay=delay, drop_every=drop_every)
    return _DuplexEnd(ab, ba), _DuplexEnd(ba, ab), [ab, ba]


def _engine(actor: str, actors: tuple[str, ...], *, episode_len: int) -> PeerEngine:
    """Build one peer engine over a fresh line-world replica."""
    replica = LineWorld(actors, seed=2024, episode_len=episode_len)
    return PeerEngine(
        actor_id=actor,
        peer_actor_ids=actors,
        interaction_id=_INTERACTION,
        episode_id=_EPISODE,
        channel_key="p2p-game",
        mesh_membership_digest=_MESH_DIGEST,
        membership_generation=1,
        step=replica.step,
        snapshot=replica.snapshot,
        restore=replica.restore,
        recorded_at=_RECORDED_AT,
        input_delay=1,
        snapshot_interval=5,
        default_action=1,
        max_steps=episode_len + 40,
    )


def _canonical_rows(node: PeerNode) -> list[object]:
    """Return one node's parity-comparable canonical rows."""
    return [record.canonical() for record in node.engine.canonical_trajectory()]


# -- the codec round-trips every packet ----------------------------------------


def test_the_codec_round_trips_every_packet() -> None:
    """An input, a hash, and an end packet survive the wire encoding unchanged."""
    digest = Digest(algorithm="sha-256", hex="b" * 64)
    packets = [
        InputPacket(sender=_actor(1), current_frame=7, inputs=((5, 2), (6, 1))),
        HashPacket(sender=_actor(2), frame_number=6, state_hash=digest),
        EndPacket(sender=_actor(1), end_frame_exclusive=40),
    ]
    encoders = [encode_input, encode_hash, encode_end]
    for packet, encode in zip(packets, encoders, strict=True):
        assert decode(encode(packet)) == packet  # type: ignore[arg-type]


def test_an_unknown_wire_message_is_refused() -> None:
    """A message with no known kind raises rather than becoming an empty packet."""
    with pytest.raises(ValueError, match="unknown wire message kind"):
        decode({"kind": "gossip"})


@pytest.mark.parametrize(
    "message",
    [
        {"kind": "end", "sender": 7, "end_frame_exclusive": 1},
        {
            "kind": "end",
            "sender": _actor(1),
            "end_frame_exclusive": 1,
            "extra": True,
        },
        {
            "kind": "input",
            "sender": _actor(1),
            "current_frame": 1,
            "inputs": [[1, 0], [1, 2]],
        },
        {
            "kind": "input",
            "sender": _actor(1),
            "current_frame": 1,
            "inputs": [[index, 0] for index in range(33)],
        },
    ],
)
def test_malformed_or_unbounded_peer_packets_are_refused(
    message: dict[str, Any],
) -> None:
    """The data-channel codec accepts only its closed bounded packet shapes."""
    with pytest.raises(ValueError):
        decode(message)


@pytest.mark.asyncio
async def test_a_packet_cannot_claim_another_channels_sender() -> None:
    """The authenticated data channel, not packet JSON, determines the sender."""
    local, remote = _actor(1), _actor(2)

    class InboundLink:
        def __init__(self, message: dict[str, Any]) -> None:
            self.inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            self.inbound.put_nowait(message)

        async def send(self, message: Mapping[str, Any]) -> None:
            del message

        async def recv(self) -> dict[str, Any] | None:
            return await self.inbound.get()

    link = InboundLink(
        encode_input(InputPacket(sender=_actor(3), current_frame=0, inputs=((0, 1),)))
    )
    node = PeerNode(
        engine=_engine(local, (local, remote), episode_len=2),
        actor_id=local,
        links={remote: link},
        action=lambda: 1,
    )
    node.start()
    try:
        await asyncio.sleep(0)
        with pytest.raises(ValueError, match="does not match its data channel"):
            await node.tick()
    finally:
        await node.stop()


@pytest.mark.asyncio
async def test_a_closed_peer_link_fails_the_mesh_node() -> None:
    """A peer cannot disappear while the replica continues speculatively."""
    local, remote = _actor(1), _actor(2)

    class ClosedLink:
        async def send(self, message: Mapping[str, Any]) -> None:
            del message

        async def recv(self) -> dict[str, Any] | None:
            return None

    node = PeerNode(
        engine=_engine(local, (local, remote), episode_len=2),
        actor_id=local,
        links={remote: ClosedLink()},
        action=lambda: 1,
    )
    node.start()
    try:
        await asyncio.sleep(0)
        with pytest.raises(PeerLinkClosed):
            await node.tick()
    finally:
        await node.stop()


# -- a lossy, latent mesh still reaches parity ---------------------------------


async def _run_wire_mesh(
    actors: tuple[str, ...], *, episode_len: int, delay: float, drop_every: int
) -> dict[str, PeerNode]:
    """Wire a full mesh of nodes over lossy, latent links and run to the barrier."""
    actors = tuple(sorted(actors))
    scripts = {
        actor: [((i * 5 + index * 2 + 1) % 3) for i in range(episode_len + 60)]
        for index, actor in enumerate(actors)
    }
    cursors = dict.fromkeys(actors, 0)

    def action_of(actor: str) -> int:
        value = scripts[actor][cursors[actor]]
        cursors[actor] += 1
        return value

    links: dict[str, dict[str, PeerLink]] = {actor: {} for actor in actors}
    pipes: list[_Pipe] = []
    for i, low in enumerate(actors):
        for high in actors[i + 1 :]:
            end_low, end_high, made = _duplex(delay=delay, drop_every=drop_every)
            links[low][high] = end_low
            links[high][low] = end_high
            pipes.extend(made)

    nodes = {
        actor: PeerNode(
            engine=_engine(actor, actors, episode_len=episode_len),
            actor_id=actor,
            links=links[actor],
            action=lambda actor=actor: action_of(actor),
        )
        for actor in actors
    }

    ticks = episode_len + 60

    async def drive(node: PeerNode) -> None:
        node.start()
        for _ in range(ticks):
            await node.tick()
            await asyncio.sleep(delay / 2)

    await asyncio.gather(*(drive(node) for node in nodes.values()))
    for node in nodes.values():
        assert node.ready_to_finalize()
        node.finalize()
    for node in nodes.values():
        await node.stop()
    for pipe in pipes:
        await pipe.aclose()
    return nodes


@pytest.mark.asyncio
async def test_a_two_peer_wire_mesh_reaches_identical_trajectories() -> None:
    """Two nodes over lossy, latent links export byte-identical canonical rows."""
    actors = (_actor(1), _actor(2))
    nodes = await _run_wire_mesh(actors, episode_len=30, delay=0.004, drop_every=4)

    rows = {actor: _canonical_rows(node) for actor, node in nodes.items()}
    reference = rows[min(rows)]
    assert len(reference) == 30
    for actor, actor_rows in rows.items():
        assert actor_rows == reference, f"peer {actor} diverged"
    # The round-trip latency past the input delay forces at least one rollback.
    assert any(node.engine.rollback_count() > 0 for node in nodes.values())


@pytest.mark.asyncio
async def test_a_three_peer_wire_mesh_keeps_parity() -> None:
    """Three nodes over lossy, latent links reach one identical trajectory."""
    actors = (_actor(1), _actor(2), _actor(3))
    nodes = await _run_wire_mesh(actors, episode_len=24, delay=0.003, drop_every=5)

    rows = {actor: _canonical_rows(node) for actor, node in nodes.items()}
    reference = rows[min(rows)]
    for actor_rows in rows.values():
        assert actor_rows == reference
