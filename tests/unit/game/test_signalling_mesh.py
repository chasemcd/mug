"""The signalling bootstrap opens the real links that a peer mesh plays over.

The unit tests in ``test_signalling.py`` prove the handshake state machine. This
test proves the promised end-to-end path: a fake ``RTCPeerConnection`` pair
negotiates through a real ``SignalRelay``, the bootstrap returns a real
``DataChannelLink`` for each pair, a real ``PeerNode`` drives one rollback engine
over those links, and every peer reaches a byte-identical canonical trajectory.

The data channels add a small delivery delay, so a peer input arrives after the
engine has already predicted it. The engine must roll back, exactly as it does
over a real WebRTC channel. The test also proves the separation of the two
paths: the signal relay carries only handshake messages, and every game packet
goes over the negotiated data channel.

There is no socket, no ICE server, and no vendor SDK: the connections and the
channels are in-process fakes that duck-type the two seams the runtime names.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, cast

import pytest

from mug.game.mesh import PeerEngine, ReplicaFrame
from mug.game.signal_relay import SignalRelay
from mug.game.signalling import SignalChannel, open_peer_links
from mug.game.wire import DataChannelLink, PeerLink, PeerNode
from mug.kernel import Digest

_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000020f"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000020e"
_RECORDED_AT = "2026-07-24T00:00:00.000000Z"
_MESH_DIGEST = Digest(algorithm="sha-256", hex="c" * 64)
_HANDSHAKE_KINDS = frozenset({"offer", "answer", "candidate", "end_of_candidates"})

_Handler = Callable[..., Any]
_Snapshot = tuple[tuple[tuple[str, int], ...], int, int]


def _actor(index: int) -> str:
    """Return the canonical actor id for one peer index."""
    return f"actor_019b6000-0000-7000-8000-0000000002{index:02x}"


class _LineWorld:
    """A deterministic multi-seat replica whose state depends on a generator."""

    def __init__(self, actors: tuple[str, ...], *, seed: int, episode_len: int) -> None:
        self._actors = tuple(sorted(actors))
        self._episode_len = episode_len
        self._t = 0
        self._rng = seed & 0x7FFFFFFF
        self._pos: dict[str, int] = dict.fromkeys(self._actors, 0)

    def step(self, actions: Mapping[str, int]) -> ReplicaFrame:
        self._t += 1
        self._rng = (self._rng * 1103515245 + 12345) & 0x7FFFFFFF
        noise = self._rng % 3 - 1
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


def _engine(actor: str, actors: tuple[str, ...], *, episode_len: int) -> PeerEngine:
    """Build one peer engine over a fresh line-world replica."""
    replica = _LineWorld(actors, seed=2024, episode_len=episode_len)
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


# -- the fake WebRTC tier ------------------------------------------------------


class _MeshChannel:
    """A paired data channel that delivers text to its remote after a delay."""

    def __init__(self, label: str, delay: float) -> None:
        self.label = label
        self.readyState = "connecting"
        self.sent = 0
        self._delay = delay
        self._handlers: dict[str, list[_Handler]] = {}
        self._other: _MeshChannel | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    def pair_with(self, other: _MeshChannel) -> None:
        """Connect this channel to its remote end."""
        self._other = other

    def on(self, event: str, handler: _Handler) -> _Handler:
        self._handlers.setdefault(event, []).append(handler)
        return handler

    def send(self, data: str) -> None:
        other = self._other
        if other is None:
            raise RuntimeError("the data channel has no remote end")
        self.sent += 1
        task = asyncio.create_task(other._deliver(data, self._delay))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver(self, data: str, delay: float) -> None:
        await asyncio.sleep(delay)
        for handler in list(self._handlers.get("message", [])):
            handler(data)

    def open(self) -> None:
        """Raise the open event once."""
        if self.readyState == "open":
            return
        self.readyState = "open"
        for handler in self._handlers.get("open", []):
            handler()

    async def aclose(self) -> None:
        """Cancel every delivery still in flight."""
        for task in list(self._tasks):
            task.cancel()


class _MeshPair:
    """Own the shared negotiation state of two fake RTC connections."""

    def __init__(self, first: str, second: str, delay: float) -> None:
        self.delay = delay
        self.first = _MeshConnection(first, self)
        self.second = _MeshConnection(second, self)
        self.channels: tuple[_MeshChannel, _MeshChannel] | None = None

    def create_channels(self, owner: _MeshConnection, label: str) -> _MeshChannel:
        """Create and pair the offerer's local and the answerer's remote channel."""
        local = _MeshChannel(label, self.delay)
        remote = _MeshChannel(label, self.delay)
        local.pair_with(remote)
        remote.pair_with(local)
        self.channels = (local, remote)
        owner.data_channel = local
        self.other(owner).data_channel = remote
        return local

    def other(self, connection: _MeshConnection) -> _MeshConnection:
        """Return the other connection in this pair."""
        return self.second if connection is self.first else self.first

    def remote_description_set(
        self, connection: _MeshConnection, description: Mapping[str, Any]
    ) -> None:
        """Deliver the incoming channel and check whether ICE can open the pair."""
        if description.get("type") == "offer":
            channel = connection.data_channel
            if channel is None:
                raise AssertionError("an offer arrived before channel creation")
            connection.emit("datachannel", channel)
        self.maybe_open()

    def maybe_open(self) -> None:
        """Open both ends after descriptions and one candidate reach each peer."""
        if (
            self.first.remote_description
            and self.second.remote_description
            and self.first.remote_candidates
            and self.second.remote_candidates
        ):
            if self.channels is None:
                raise AssertionError("negotiation has no data channels")
            for channel in self.channels:
                channel.open()


class _MeshConnection:
    """A deterministic connection that exchanges descriptions through a pair."""

    def __init__(self, name: str, pair: _MeshPair) -> None:
        self.name = name
        self.connectionState = "new"
        self.remote_description: dict[str, Any] | None = None
        self.remote_candidates: list[dict[str, Any]] = []
        self.data_channel: _MeshChannel | None = None
        self._pair = pair
        self._handlers: dict[str, _Handler] = {}

    def on(self, event: str, handler: _Handler) -> _Handler:
        self._handlers[event] = handler
        return handler

    def emit(self, event: str, *args: object) -> None:
        """Raise one registered RTC event."""
        self._handlers[event](*args)

    def createDataChannel(self, label: str, options: Mapping[str, Any]) -> _MeshChannel:
        del options
        return self._pair.create_channels(self, label)

    async def createOffer(self) -> Mapping[str, Any]:
        return {"type": "offer", "sdp": f"offer:{self.name}"}

    async def createAnswer(self) -> Mapping[str, Any]:
        return {"type": "answer", "sdp": f"answer:{self.name}"}

    async def setLocalDescription(self, description: Mapping[str, Any]) -> None:
        del description
        self.emit("icecandidate", {"candidate": f"ice:{self.name}"})

    async def setRemoteDescription(self, description: Mapping[str, Any]) -> None:
        self.remote_description = dict(description)
        self._pair.remote_description_set(self, description)

    async def addIceCandidate(self, candidate: Mapping[str, Any] | None) -> None:
        if self.remote_description is None:
            raise AssertionError("ICE was applied before the remote description")
        if candidate is None:
            return
        self.remote_candidates.append(dict(candidate))
        self._pair.maybe_open()

    async def close(self) -> None:
        """Close this connection."""
        self.connectionState = "closed"


class _RecordingSignal:
    """Record the kind of every message one peer sends through the relay."""

    def __init__(self, inner: SignalChannel, kinds: set[str]) -> None:
        self._inner = inner
        self._kinds = kinds

    async def send(self, message: Mapping[str, Any]) -> None:
        self._kinds.add(str(message.get("kind")))
        await self._inner.send(message)

    async def recv(self) -> dict[str, Any] | None:
        return await self._inner.recv()


# -- the bootstrap-then-play run ------------------------------------------------


class _MeshRun:
    """Everything one bootstrapped mesh run produced, for its assertions."""

    def __init__(
        self,
        nodes: dict[str, PeerNode],
        links: dict[str, dict[str, DataChannelLink]],
        signal_kinds: set[str],
        channels: list[_MeshChannel],
    ) -> None:
        self.nodes = nodes
        self.links = links
        self.signal_kinds = signal_kinds
        self.channels = channels


async def _run_bootstrapped_mesh(
    actors: tuple[str, ...], *, episode_len: int, delay: float
) -> _MeshRun:
    """Negotiate every pair through the relay, then play one episode over them."""
    actors = tuple(sorted(actors))
    relay = SignalRelay(actors)
    signal_kinds: set[str] = set()
    pairs: list[_MeshPair] = []
    connections: dict[str, dict[str, _MeshConnection]] = {actor: {} for actor in actors}
    for index, low in enumerate(actors):
        for high in actors[index + 1 :]:
            pair = _MeshPair(low, high, delay)
            pairs.append(pair)
            connections[low][high] = pair.first
            connections[high][low] = pair.second

    async def open_for(local: str) -> dict[str, DataChannelLink]:
        def signal_for(remote: str) -> SignalChannel:
            return _RecordingSignal(
                relay.channel(local=local, remote=remote), signal_kinds
            )

        return await open_peer_links(
            local=local,
            connections=connections[local],
            signal_for=signal_for,
            timeout_seconds=1.0,
        )

    opened = await asyncio.gather(*(open_for(actor) for actor in actors))
    links = dict(zip(actors, opened, strict=True))
    relay.close()

    scripts = {
        actor: [((i * 5 + index * 2 + 1) % 3) for i in range(episode_len + 60)]
        for index, actor in enumerate(actors)
    }
    cursors = dict.fromkeys(actors, 0)

    def action_of(actor: str) -> int:
        value = scripts[actor][cursors[actor]]
        cursors[actor] += 1
        return value

    nodes = {
        actor: PeerNode(
            engine=_engine(actor, actors, episode_len=episode_len),
            actor_id=actor,
            links=cast("Mapping[str, PeerLink]", links[actor]),
            action=lambda actor=actor: action_of(actor),
        )
        for actor in actors
    }

    async def drive(node: PeerNode) -> None:
        node.start()
        for _ in range(episode_len + 60):
            await node.tick()
            await asyncio.sleep(delay / 2)

    await asyncio.gather(*(drive(node) for node in nodes.values()))
    for node in nodes.values():
        assert node.ready_to_finalize()
        node.finalize()
    for node in nodes.values():
        await node.stop()
    channels: list[_MeshChannel] = []
    for pair in pairs:
        assert pair.channels is not None
        channels.extend(pair.channels)
    for channel in channels:
        await channel.aclose()
    return _MeshRun(nodes, links, signal_kinds, channels)


def _canonical_rows(node: PeerNode) -> list[object]:
    """Return one node's parity-comparable canonical rows."""
    return [record.canonical() for record in node.engine.canonical_trajectory()]


@pytest.mark.asyncio
async def test_two_bootstrapped_peers_reach_identical_trajectories() -> None:
    """A relay-negotiated pair plays one episode to byte-identical canonical rows."""
    actors = (_actor(1), _actor(2))
    run = await _run_bootstrapped_mesh(actors, episode_len=20, delay=0.004)

    for local, remotes in run.links.items():
        assert set(remotes) == set(actors) - {local}
        for link in remotes.values():
            assert isinstance(link, DataChannelLink)

    rows = {actor: _canonical_rows(node) for actor, node in run.nodes.items()}
    reference = rows[min(rows)]
    assert len(reference) == 20
    for actor, actor_rows in rows.items():
        assert actor_rows == reference, f"peer {actor} diverged"
    # The channel round trip past the input delay forces at least one rollback.
    assert any(node.engine.rollback_count() > 0 for node in run.nodes.values())


@pytest.mark.asyncio
async def test_the_relay_carries_no_game_packet() -> None:
    """The handshake goes through the relay; every game packet goes peer to peer."""
    run = await _run_bootstrapped_mesh(
        (_actor(1), _actor(2)), episode_len=12, delay=0.003
    )

    assert run.signal_kinds
    assert run.signal_kinds <= _HANDSHAKE_KINDS
    assert sum(channel.sent for channel in run.channels) > 0


@pytest.mark.asyncio
async def test_three_bootstrapped_peers_keep_parity() -> None:
    """A three-peer bootstrap opens all three pairs and keeps one trajectory."""
    actors = (_actor(1), _actor(2), _actor(3))
    run = await _run_bootstrapped_mesh(actors, episode_len=16, delay=0.003)

    assert len(run.channels) == 6  # three pairs, two ends each
    rows = {actor: _canonical_rows(node) for actor, node in run.nodes.items()}
    reference = rows[min(rows)]
    for actor, actor_rows in rows.items():
        assert actor_rows == reference, f"peer {actor} diverged"
