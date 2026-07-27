"""The WebRTC data-channel adapter presents a real channel as a ``PeerLink``.

These tests drive ``mug.game.wire.DataChannelLink`` with a fake channel that
duck-types a WebRTC ``RTCDataChannel`` -- it records each sent text and pushes an
arrived message (or a close) to the registered handler. They prove the adapter:

- sends one json-able message as compact text, and receives an arrived message the
  channel pushed, so a codec-produced packet survives the channel unchanged;
- reports ``None`` once the channel closes, so the driving node's receive loop ends;
- drops a malformed or non-object message, so a stray frame never becomes a
  half-formed packet.

There is no socket and no vendor SDK: the fake channel is an in-process object with
the two methods the adapter names, so the adapter that reaches a real peer process
in production stays deterministic under test.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from mug.game.mesh import InputPacket
from mug.game.wire import DataChannelLink, encode_input


class FakeDataChannel:
    """An in-process stand-in for a WebRTC data channel.

    ``send`` records the text the adapter emits; ``on`` registers the message and
    terminal handlers; ``push``, ``close``, and ``fail`` simulate its events.
    """

    def __init__(self) -> None:
        self.readyState = "open"
        self.sent: list[str] = []
        self._handlers: dict[str, Callable[..., Any]] = {}

    def send(self, data: str) -> None:
        self.sent.append(data)

    def on(self, event: str, handler: Callable[..., Any]) -> Callable[..., Any]:
        self._handlers[event] = handler
        return handler

    def push(self, data: str | bytes) -> None:
        """Deliver one arrived message to the registered message handler."""
        self._handlers["message"](data)

    def close(self) -> None:
        """Raise the close event to the registered close handler."""
        self.readyState = "closed"
        self._handlers["close"]()

    def fail(self) -> None:
        """Raise an error while the channel still reports an open ready state."""
        self._handlers["error"]()


@pytest.mark.asyncio
async def test_send_frames_one_message_as_compact_text() -> None:
    """The adapter sends one json-able message as compact text over the channel."""
    channel = FakeDataChannel()
    link = DataChannelLink(channel)
    packet = InputPacket(sender="actor-1", current_frame=3, inputs=((1, 2), (2, 0)))

    await link.send(encode_input(packet))

    assert len(channel.sent) == 1
    assert " " not in channel.sent[0]  # compact separators, no whitespace
    assert json.loads(channel.sent[0]) == {
        "kind": "input",
        "sender": "actor-1",
        "current_frame": 3,
        "inputs": [[1, 2], [2, 0]],
    }


@pytest.mark.asyncio
async def test_recv_returns_the_message_the_channel_pushed() -> None:
    """An arrived message the channel pushes is returned by ``recv`` unchanged."""
    channel = FakeDataChannel()
    link = DataChannelLink(channel)
    message = {"kind": "end", "sender": "actor-2", "end_frame_exclusive": 12}

    channel.push(json.dumps(message))

    assert await link.recv() == message


@pytest.mark.asyncio
async def test_recv_reads_a_binary_message() -> None:
    """A binary message is decoded as UTF-8 text before it is delivered."""
    channel = FakeDataChannel()
    link = DataChannelLink(channel)
    message = {"kind": "hash", "sender": "actor-3", "frame_number": 4}

    channel.push(json.dumps(message).encode("utf-8"))

    assert await link.recv() == message


@pytest.mark.asyncio
async def test_recv_reports_none_once_the_channel_closes() -> None:
    """A closed or failed channel ends the receive loop and is not open."""
    for terminal in ("close", "fail"):
        channel = FakeDataChannel()
        link = DataChannelLink(channel)

        if terminal == "close":
            channel.close()
        else:
            channel.fail()

        assert await link.recv() is None
        assert not link.is_open


@pytest.mark.asyncio
async def test_a_malformed_or_non_object_message_is_dropped() -> None:
    """A malformed or non-object frame never reaches ``recv`` as a packet."""
    channel = FakeDataChannel()
    link = DataChannelLink(channel)

    channel.push("not json{")  # malformed
    channel.push(b"\xff")  # invalid UTF-8
    channel.push("[1, 2, 3]")  # a json array, not an object
    good = {"kind": "end", "sender": "actor-4", "end_frame_exclusive": 1}
    channel.push(json.dumps(good))

    assert await link.recv() == good  # only the object survived the two bad frames


@pytest.mark.asyncio
async def test_an_oversized_data_channel_message_fails_closed() -> None:
    """The adapter bounds both trusted sends and untrusted received bytes."""
    channel = FakeDataChannel()
    link = DataChannelLink(channel)

    with pytest.raises(ValueError, match="exceeds 65536 bytes"):
        await link.send({"payload": "x" * 65_537})
    channel.push(json.dumps({"payload": "x" * 65_537}))

    assert await link.recv() is None
    assert not link.is_open
