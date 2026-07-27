"""The signalling bootstrap opens isolated WebRTC links for one frozen mesh.

These tests use small in-process RTC and data-channel fakes. They prove the
offer/answer state machine, ordered ICE handling, terminal failures, pairwise
relay isolation, and concurrent full-mesh opening without a socket, an ICE
server, or a vendor SDK.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from mug.game.signal_relay import SignalRelay
from mug.game.signalling import (
    SignallingClosed,
    SignallingTimeout,
    establish_data_channel,
    open_peer_links,
    role_for,
)
from mug.game.wire import DataChannelLink

_Handler = Callable[..., Any]


class _FakeDataChannel:
    """A paired push channel with the event API used by ``DataChannelLink``."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.readyState = "connecting"
        self._handlers: dict[str, list[_Handler]] = {}
        self._other: _FakeDataChannel | None = None

    def pair_with(self, other: _FakeDataChannel) -> None:
        """Connect this channel to its remote end."""
        self._other = other

    def on(self, event: str, handler: _Handler) -> _Handler:
        self._handlers.setdefault(event, []).append(handler)
        return handler

    def send(self, data: str) -> None:
        if self._other is None:
            raise RuntimeError("data channel has no remote end")
        for handler in self._other._handlers.get("message", []):
            handler(data)

    def open(self) -> None:
        """Raise the open event once."""
        if self.readyState == "open":
            return
        self.readyState = "open"
        for handler in self._handlers.get("open", []):
            handler()

    def close(self) -> None:
        """Raise the close event once."""
        if self.readyState == "closed":
            return
        self.readyState = "closed"
        for handler in self._handlers.get("close", []):
            handler()

    def fail(self) -> None:
        """Raise an error event without first changing the ready state."""
        for handler in self._handlers.get("error", []):
            handler()


class _RtcPair:
    """Own the shared state of two fake RTC connections."""

    def __init__(self, first: str, second: str) -> None:
        self.first = _FakeRtcConnection(first, self)
        self.second = _FakeRtcConnection(second, self)
        self._channels: tuple[_FakeDataChannel, _FakeDataChannel] | None = None

    def create_channels(
        self, owner: _FakeRtcConnection, label: str
    ) -> _FakeDataChannel:
        """Create and pair the offerer's local and answerer's remote channels."""
        local = _FakeDataChannel(label)
        remote = _FakeDataChannel(label)
        local.pair_with(remote)
        remote.pair_with(local)
        self._channels = (local, remote)
        owner.data_channel = local
        self.other(owner).data_channel = remote
        return local

    def other(self, connection: _FakeRtcConnection) -> _FakeRtcConnection:
        """Return the other connection in this pair."""
        return self.second if connection is self.first else self.first

    def remote_description_set(
        self, connection: _FakeRtcConnection, description: Mapping[str, Any]
    ) -> None:
        """Deliver the incoming channel and check whether ICE can open the pair."""
        if description.get("type") == "offer":
            channel = connection.data_channel
            if channel is None:
                raise AssertionError("offer arrived before channel creation")
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
            if self._channels is None:
                raise AssertionError("negotiation has no data channels")
            for channel in self._channels:
                channel.open()


class _FakeRtcConnection:
    """A deterministic connection that exchanges descriptions through a pair."""

    def __init__(self, name: str, pair: _RtcPair) -> None:
        self.name = name
        self.connectionState = "new"
        self.local_description: dict[str, Any] | None = None
        self.remote_description: dict[str, Any] | None = None
        self.remote_candidates: list[dict[str, Any]] = []
        self.channel_options: dict[str, Any] | None = None
        self.data_channel: _FakeDataChannel | None = None
        self._pair = pair
        self._handlers: dict[str, _Handler] = {}

    def on(self, event: str, handler: _Handler) -> _Handler:
        self._handlers[event] = handler
        return handler

    def emit(self, event: str, *args: object) -> None:
        """Raise one registered RTC event."""
        self._handlers[event](*args)

    def createDataChannel(
        self, label: str, options: Mapping[str, Any]
    ) -> _FakeDataChannel:
        self.channel_options = dict(options)
        return self._pair.create_channels(self, label)

    async def createOffer(self) -> Mapping[str, Any]:
        return {"type": "offer", "sdp": f"offer:{self.name}"}

    async def createAnswer(self) -> Mapping[str, Any]:
        return {"type": "answer", "sdp": f"answer:{self.name}"}

    async def setLocalDescription(self, description: Mapping[str, Any]) -> None:
        self.local_description = dict(description)
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
        """Close this connection and its local data channel."""
        self.connectionState = "closed"
        if self.data_channel is not None:
            self.data_channel.close()

    def fail(self) -> None:
        """Move to a failed connection state and raise its change event."""
        self.connectionState = "failed"
        self.emit("connectionstatechange")


class _QueueSignal:
    """A controllable signalling channel for one-sided state-machine tests."""

    def __init__(
        self,
        *incoming: Mapping[str, Any],
        delay_description_send: bool = False,
        fail_candidates: bool = False,
    ) -> None:
        self.sent: list[dict[str, Any]] = []
        self._incoming: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._delay_description_send = delay_description_send
        self._fail_candidates = fail_candidates
        for message in incoming:
            self._incoming.put_nowait(dict(message))

    async def send(self, message: Mapping[str, Any]) -> None:
        kind = message.get("kind")
        if kind in {"offer", "answer"} and self._delay_description_send:
            await asyncio.sleep(0)
        if kind == "candidate" and self._fail_candidates:
            raise RuntimeError("candidate relay failed")
        self.sent.append(dict(message))

    async def recv(self) -> dict[str, Any] | None:
        return await self._incoming.get()

    def push(self, message: Mapping[str, Any]) -> None:
        """Make one controlled inbound message ready."""
        self._incoming.put_nowait(dict(message))


class _ProbeConnection:
    """A one-sided RTC probe that records the order of remote operations."""

    def __init__(
        self, *, local_candidate: bool = False, local_end_of_candidates: bool = False
    ) -> None:
        self._connection_state = "new"
        self.state_reads = 0
        self.handoff_checked = asyncio.Event()
        self.closed = False
        self.channel = _FakeDataChannel("probe")
        self.created = asyncio.Event()
        self.remote_set = asyncio.Event()
        self.operations: list[str] = []
        self.close_calls = 0
        self._local_candidate = local_candidate
        self._local_end_of_candidates = local_end_of_candidates
        self._handlers: dict[str, _Handler] = {}

    @property
    def connectionState(self) -> str:
        self.state_reads += 1
        if self.state_reads >= 2:
            self.handoff_checked.set()
        return self._connection_state

    @connectionState.setter
    def connectionState(self, value: str) -> None:
        self._connection_state = value

    def on(self, event: str, handler: _Handler) -> _Handler:
        self._handlers[event] = handler
        return handler

    def createDataChannel(
        self, label: str, options: Mapping[str, Any]
    ) -> _FakeDataChannel:
        del options
        self.channel.label = label
        self.created.set()
        return self.channel

    async def createOffer(self) -> Mapping[str, Any]:
        return {"type": "offer", "sdp": "probe-offer"}

    async def createAnswer(self) -> Mapping[str, Any]:
        return {"type": "answer", "sdp": "probe-answer"}

    async def setLocalDescription(self, description: Mapping[str, Any]) -> None:
        del description
        if self._local_candidate:
            self._handlers["icecandidate"]({"candidate": "local-ice"})
        if self._local_end_of_candidates:
            self._handlers["icecandidate"](None)

    async def setRemoteDescription(self, description: Mapping[str, Any]) -> None:
        self.operations.append(f"description:{description['type']}")
        if description["type"] == "offer":
            self._handlers["datachannel"](self.channel)
        self.channel.open()
        self.remote_set.set()

    async def addIceCandidate(self, candidate: Mapping[str, Any] | None) -> None:
        if not self.operations:
            raise AssertionError("ICE was applied before the remote description")
        if candidate is None:
            self.operations.append("end-of-candidates")
            return
        self.operations.append(f"candidate:{candidate['candidate']}")

    async def close(self) -> None:
        """Close this connection and its data channel."""
        self.close_calls += 1
        self.closed = True
        self.connectionState = "closed"
        self.channel.close()

    def fail(self) -> None:
        """Move to a failed state and raise the connection change event."""
        self.connectionState = "failed"
        self._handlers["connectionstatechange"]()


class _HangingOfferConnection(_ProbeConnection):
    """Hold offer creation until the handshake deadline cancels it."""

    async def createOffer(self) -> Mapping[str, Any]:
        await asyncio.Event().wait()
        return {"type": "offer", "sdp": "unreachable"}


class _RegistrationFailureConnection(_ProbeConnection):
    """Reject one RTC event registration after ownership begins."""

    def on(self, event: str, handler: _Handler) -> _Handler:
        if event == "connectionstatechange":
            raise RuntimeError("event registration failed")
        return super().on(event, handler)


class _HandoffFailureConnection(_ProbeConnection):
    """Fail after the channel opens but before the caller receives the link."""

    def __init__(self, failure: str) -> None:
        super().__init__()
        self._failure = failure

    async def setRemoteDescription(self, description: Mapping[str, Any]) -> None:
        await super().setRemoteDescription(description)
        if self._failure == "channel":
            callback = self.channel.close
        elif self._failure == "channel-error":
            callback = self.channel.fail
        else:
            callback = self.fail
        asyncio.get_running_loop().call_soon(callback)


class _BarrierFailureConnection(_ProbeConnection):
    """Expose an RTC failure only when the full-mesh barrier reads state."""

    def __init__(self) -> None:
        super().__init__()

    @property
    def connectionState(self) -> str:
        self.state_reads += 1
        if self.state_reads >= 2:
            self.handoff_checked.set()
        if self.state_reads >= 3 and self._connection_state == "new":
            return "failed"
        return self._connection_state

    @connectionState.setter
    def connectionState(self, value: str) -> None:
        self._connection_state = value


def test_roles_are_deterministic_for_both_sides_of_a_pair() -> None:
    """The lower actor offers and the higher actor answers."""
    assert role_for("actor-a", "actor-b") == "offerer"
    assert role_for("actor-b", "actor-a") == "answerer"
    with pytest.raises(ValueError):
        role_for("actor-a", "actor-a")


@pytest.mark.asyncio
async def test_relay_isolates_pairs_stamps_endpoints_and_keeps_fifo_order() -> None:
    """Each pair receives only its own opaque messages in send order."""
    relay = SignalRelay(("actor-a", "actor-b", "actor-c"))
    a_to_b = relay.channel(local="actor-a", remote="actor-b")
    b_to_a = relay.channel(local="actor-b", remote="actor-a")
    c_to_a = relay.channel(local="actor-c", remote="actor-a")
    a_to_c = relay.channel(local="actor-a", remote="actor-c")

    await a_to_b.send({"kind": "opaque-1", "from": "spoofed", "body": {"x": 1}})
    await a_to_b.send({"kind": "opaque-2"})
    await c_to_a.send({"kind": "other-pair"})

    assert await b_to_a.recv() == {
        "kind": "opaque-1",
        "from": "actor-a",
        "to": "actor-b",
        "body": {"x": 1},
    }
    second = await b_to_a.recv()
    other_pair = await a_to_c.recv()
    assert second is not None
    assert other_pair is not None
    assert second["kind"] == "opaque-2"
    assert other_pair["kind"] == "other-pair"


def test_relay_rejects_an_invalid_membership_or_endpoint() -> None:
    """A relay fails closed for a one-peer room, a non-member, or a self-pair."""
    with pytest.raises(ValueError):
        SignalRelay(("actor-a",))
    with pytest.raises(ValueError):
        SignalRelay(("actor-a", "actor-a"))
    with pytest.raises(ValueError):
        SignalRelay("ab")
    with pytest.raises(ValueError):
        SignalRelay(("actor-a", ""))

    members = ["actor-a", "actor-b"]
    relay = SignalRelay(members)
    members.clear()
    relay.channel(local="actor-a", remote="actor-b")
    with pytest.raises(ValueError):
        relay.channel(local="actor-a", remote="actor-c")
    with pytest.raises(ValueError):
        relay.channel(local="actor-a", remote="actor-a")


@pytest.mark.asyncio
async def test_relay_close_wakes_existing_and_future_channels() -> None:
    """Room teardown releases every receiver, including one created after close."""
    relay = SignalRelay(("actor-a", "actor-b"))
    existing = relay.channel(local="actor-a", remote="actor-b")
    duplicate = relay.channel(local="actor-a", remote="actor-b")
    waiting = asyncio.create_task(existing.recv())
    also_waiting = asyncio.create_task(duplicate.recv())
    await asyncio.sleep(0)

    relay.close()

    assert await waiting is None
    assert await also_waiting is None
    with pytest.raises(SignallingClosed):
        await existing.send({"kind": "late"})
    future = relay.channel(local="actor-a", remote="actor-b")
    assert await future.recv() is None


@pytest.mark.asyncio
async def test_relay_bounds_message_bytes_and_pending_pair_work() -> None:
    """A peer cannot grow one room inbox without a fixed bound."""
    relay = SignalRelay(("actor-a", "actor-b"))
    channel = relay.channel(local="actor-a", remote="actor-b")

    with pytest.raises(ValueError, match="exceeds 65536 bytes"):
        await channel.send({"kind": "candidate", "payload": "x" * 65_537})

    for index in range(64):
        await channel.send({"kind": "candidate", "index": index})
    with pytest.raises(SignallingClosed, match="inbox is full"):
        await channel.send({"kind": "candidate", "index": 64})


@pytest.mark.asyncio
async def test_offer_answer_and_ice_open_a_bidirectional_data_channel() -> None:
    """Two peers negotiate one link and carry data in both directions."""
    relay = SignalRelay(("actor-a", "actor-b"))
    pair = _RtcPair("actor-a", "actor-b")
    offerer, answerer = await asyncio.gather(
        establish_data_channel(
            connection=pair.first,
            signal=relay.channel(local="actor-a", remote="actor-b"),
            role="offerer",
            timeout_seconds=1.0,
        ),
        establish_data_channel(
            connection=pair.second,
            signal=relay.channel(local="actor-b", remote="actor-a"),
            role="answerer",
            timeout_seconds=1.0,
        ),
    )

    assert pair.first.remote_description == {
        "type": "answer",
        "sdp": "answer:actor-b",
    }
    assert pair.second.remote_description == {
        "type": "offer",
        "sdp": "offer:actor-a",
    }
    assert pair.first.remote_candidates == [{"candidate": "ice:actor-b"}]
    assert pair.second.remote_candidates == [{"candidate": "ice:actor-a"}]
    assert pair.first.channel_options == {"ordered": False, "maxRetransmits": 0}

    await offerer.send({"kind": "probe", "value": 1})
    assert await answerer.recv() == {"kind": "probe", "value": 1}
    await answerer.send({"kind": "probe", "value": 2})
    assert await offerer.recv() == {"kind": "probe", "value": 2}
    assert pair.first.data_channel is not None
    pair.first.data_channel.close()
    assert await offerer.recv() is None


@pytest.mark.asyncio
async def test_remote_ice_waits_for_the_remote_description() -> None:
    """An early candidate is buffered and then applied in arrival order."""
    connection = _ProbeConnection()
    signal = _QueueSignal(
        {"kind": "candidate", "candidate": {"candidate": "early-ice"}},
        {"kind": "answer", "description": {"type": "answer", "sdp": "answer"}},
    )

    await establish_data_channel(
        connection=connection,
        signal=signal,
        role="offerer",
        timeout_seconds=1.0,
    )

    assert connection.operations == ["description:answer", "candidate:early-ice"]


@pytest.mark.asyncio
async def test_remote_end_of_candidates_waits_for_the_description() -> None:
    """The explicit ICE terminator is buffered behind the remote description."""
    connection = _ProbeConnection()
    signal = _QueueSignal(
        {"kind": "end_of_candidates"},
        {"kind": "answer", "description": {"type": "answer", "sdp": "answer"}},
    )

    await establish_data_channel(
        connection=connection,
        signal=signal,
        role="offerer",
        timeout_seconds=1.0,
    )

    assert connection.operations == ["description:answer", "end-of-candidates"]


@pytest.mark.asyncio
async def test_an_already_open_channel_is_observed_after_binding() -> None:
    """The ready-state check closes the race before listener registration."""
    connection = _ProbeConnection()
    connection.channel.readyState = "open"
    signal = _QueueSignal(
        {"kind": "answer", "description": {"type": "answer", "sdp": "answer"}}
    )

    await establish_data_channel(
        connection=connection,
        signal=signal,
        role="offerer",
        timeout_seconds=1.0,
    )


@pytest.mark.asyncio
async def test_answer_is_sent_before_an_open_answerer_returns() -> None:
    """An early channel-open event cannot cancel the pending answer send."""
    connection = _ProbeConnection()
    signal = _QueueSignal(
        {"kind": "offer", "description": {"type": "offer", "sdp": "offer"}},
        delay_description_send=True,
    )

    await establish_data_channel(
        connection=connection,
        signal=signal,
        role="answerer",
        timeout_seconds=1.0,
    )

    assert [message["kind"] for message in signal.sent] == ["answer"]


@pytest.mark.asyncio
async def test_local_description_is_sent_before_its_candidate() -> None:
    """A synchronous ICE callback cannot overtake the local offer."""
    connection = _ProbeConnection(local_candidate=True)
    signal = _QueueSignal(
        {"kind": "answer", "description": {"type": "answer", "sdp": "answer"}},
        delay_description_send=True,
    )

    await establish_data_channel(
        connection=connection,
        signal=signal,
        role="offerer",
        timeout_seconds=1.0,
    )

    assert [message["kind"] for message in signal.sent] == ["offer", "candidate"]


@pytest.mark.asyncio
async def test_local_end_of_candidates_is_relayed_explicitly() -> None:
    """A null ICE callback becomes a bounded protocol terminator."""
    connection = _ProbeConnection(local_end_of_candidates=True)
    signal = _QueueSignal(
        {"kind": "answer", "description": {"type": "answer", "sdp": "answer"}}
    )

    await establish_data_channel(
        connection=connection,
        signal=signal,
        role="offerer",
        timeout_seconds=1.0,
    )

    assert [message["kind"] for message in signal.sent] == [
        "offer",
        "end_of_candidates",
    ]


@pytest.mark.asyncio
async def test_candidate_send_failure_reaches_the_caller() -> None:
    """A failed relay send does not disappear in a detached task."""
    connection = _ProbeConnection(local_candidate=True)
    signal = _QueueSignal(
        {"kind": "answer", "description": {"type": "answer", "sdp": "answer"}},
        fail_candidates=True,
    )

    with pytest.raises(RuntimeError, match="candidate relay failed"):
        await establish_data_channel(
            connection=connection,
            signal=signal,
            role="offerer",
            timeout_seconds=1.0,
        )
    assert connection.closed


@pytest.mark.asyncio
async def test_a_malformed_signal_fails_closed() -> None:
    """A non-object candidate cannot enter the RTC adapter."""
    connection = _ProbeConnection()
    signal = _QueueSignal({"kind": "candidate", "candidate": ["not", "an", "object"]})

    with pytest.raises(ValueError, match="needs an object field"):
        await establish_data_channel(
            connection=connection,
            signal=signal,
            role="offerer",
            timeout_seconds=1.0,
        )
    assert connection.closed


@pytest.mark.asyncio
async def test_data_channel_close_and_rtc_failure_end_the_handshake() -> None:
    """A close or failed RTC state raises instead of leaving a pending wait."""
    for fail in ("channel", "connection"):
        connection = _ProbeConnection()
        signal = _QueueSignal()
        task = asyncio.create_task(
            establish_data_channel(
                connection=connection,
                signal=signal,
                role="offerer",
                timeout_seconds=1.0,
            )
        )
        await connection.created.wait()
        await asyncio.sleep(0)
        if fail == "channel":
            connection.channel.close()
        else:
            connection.fail()
        with pytest.raises(SignallingClosed):
            await task
        assert connection.closed


@pytest.mark.asyncio
async def test_handshake_timeout_raises_its_typed_error() -> None:
    """A peer that never answers fails at the finite handshake deadline."""
    connection = _ProbeConnection()
    with pytest.raises(SignallingTimeout):
        await establish_data_channel(
            connection=connection,
            signal=_QueueSignal(),
            role="offerer",
            timeout_seconds=0.01,
        )
    assert connection.closed


@pytest.mark.asyncio
async def test_handshake_timeout_covers_offer_creation() -> None:
    """The finite deadline covers setup before an offer is sent."""
    connection = _HangingOfferConnection()

    with pytest.raises(SignallingTimeout):
        await establish_data_channel(
            connection=connection,
            signal=_QueueSignal(),
            role="offerer",
            timeout_seconds=0.01,
        )

    assert connection.closed


@pytest.mark.asyncio
async def test_handoff_rejects_a_channel_or_connection_that_just_failed() -> None:
    """A terminal event during task cleanup cannot return a dead link."""
    for failure in ("channel", "channel-error", "connection"):
        connection = _HandoffFailureConnection(failure)
        signal = _QueueSignal(
            {"kind": "answer", "description": {"type": "answer", "sdp": "answer"}}
        )

        with pytest.raises(SignallingClosed):
            await establish_data_channel(
                connection=connection,
                signal=signal,
                role="offerer",
                timeout_seconds=1.0,
            )

        assert connection.closed


@pytest.mark.asyncio
async def test_three_peers_open_every_pair_concurrently() -> None:
    """Concurrent bootstrap returns one working link for every remote peer."""
    actors = ("actor-a", "actor-b", "actor-c")
    relay = SignalRelay(actors)
    connections: dict[str, dict[str, _FakeRtcConnection]] = {
        actor: {} for actor in actors
    }
    for index, low in enumerate(actors):
        for high in actors[index + 1 :]:
            pair = _RtcPair(low, high)
            connections[low][high] = pair.first
            connections[high][low] = pair.second

    async def open_for(local: str) -> dict[str, DataChannelLink]:
        return await open_peer_links(
            local=local,
            connections=connections[local],
            signal_for=lambda remote: relay.channel(local=local, remote=remote),
            timeout_seconds=1.0,
        )

    opened_values = await asyncio.gather(*(open_for(actor) for actor in actors))
    opened = dict(zip(actors, opened_values, strict=True))
    assert {actor: set(links) for actor, links in opened.items()} == {
        "actor-a": {"actor-b", "actor-c"},
        "actor-b": {"actor-a", "actor-c"},
        "actor-c": {"actor-a", "actor-b"},
    }

    message = {"kind": "mesh-probe", "sender": "actor-a"}
    await opened["actor-a"]["actor-c"].send(message)
    assert await opened["actor-c"]["actor-a"].recv() == message


@pytest.mark.asyncio
async def test_one_failed_mesh_leg_closes_every_connection() -> None:
    """A partial full-mesh bootstrap does not leave a successful leg open."""
    good = _ProbeConnection()
    failed = _ProbeConnection()
    failed_signal = _QueueSignal()
    signals = {
        "actor-b": _QueueSignal(
            {"kind": "answer", "description": {"type": "answer", "sdp": "answer"}}
        ),
        "actor-c": failed_signal,
    }

    opening = asyncio.create_task(
        open_peer_links(
            local="actor-a",
            connections={"actor-b": good, "actor-c": failed},
            signal_for=signals.__getitem__,
            timeout_seconds=1.0,
        )
    )
    await good.remote_set.wait()
    await asyncio.sleep(0)
    failed_signal.push({"kind": "invalid"})

    with pytest.raises(ValueError, match="unknown signalling message kind"):
        await opening

    assert good.close_calls == 1
    assert failed.closed


@pytest.mark.asyncio
async def test_mesh_rejects_a_link_that_closes_before_the_ready_barrier() -> None:
    """The full mesh cannot return a link that died while another leg opened."""
    closed = _ProbeConnection()
    delayed = _ProbeConnection()
    delayed_signal = _QueueSignal()
    signals = {
        "actor-b": _QueueSignal(
            {"kind": "answer", "description": {"type": "answer", "sdp": "answer"}}
        ),
        "actor-c": delayed_signal,
    }

    opening = asyncio.create_task(
        open_peer_links(
            local="actor-a",
            connections={"actor-b": closed, "actor-c": delayed},
            signal_for=signals.__getitem__,
            timeout_seconds=1.0,
        )
    )
    await closed.remote_set.wait()
    await closed.handoff_checked.wait()
    closed.channel.close()
    delayed_signal.push(
        {"kind": "answer", "description": {"type": "answer", "sdp": "answer"}}
    )

    with pytest.raises(SignallingClosed, match="mesh was ready"):
        await opening

    assert closed.close_calls == 1
    assert delayed.close_calls == 1


@pytest.mark.asyncio
async def test_mesh_ready_barrier_also_checks_the_rtc_connection_state() -> None:
    """An open channel on a failed RTC connection cannot pass the mesh barrier."""
    failed = _BarrierFailureConnection()
    other = _ProbeConnection()
    signals = {
        remote: _QueueSignal(
            {"kind": "answer", "description": {"type": "answer", "sdp": "answer"}}
        )
        for remote in ("actor-b", "actor-c")
    }

    with pytest.raises(SignallingClosed, match="mesh was ready"):
        await open_peer_links(
            local="actor-a",
            connections={"actor-b": failed, "actor-c": other},
            signal_for=signals.__getitem__,
            timeout_seconds=1.0,
        )

    assert failed.state_reads >= 3
    assert failed.close_calls == 1
    assert other.close_calls == 1


@pytest.mark.asyncio
async def test_event_registration_failure_closes_the_connection() -> None:
    """Ownership cleanup applies when RTC event setup fails."""
    connection = _RegistrationFailureConnection()
    with pytest.raises(RuntimeError, match="event registration failed"):
        await establish_data_channel(
            connection=connection,
            signal=_QueueSignal(),
            role="offerer",
            timeout_seconds=1.0,
        )

    assert connection.closed
