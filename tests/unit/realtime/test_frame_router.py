"""One socket, two activities: the reader that hands each frame to its owner.

A composed activity runs a game and a conversation over one connection, and both
want to read frames. Two readers calling ``receive_text`` race for every frame and
whichever wins keeps it, so a message typed during a round can land in the game's
reader and never be seen again.

These hold what the router owes: each frame reaches the activity that claimed its
type and no other, a frame that arrives **before** its activity subscribed is held
rather than dropped, and every waiting activity is woken when the connection ends.
The held frame is the one worth being careful about -- a composed mount starts its
panes one after the other, so there is a real window where a message is in flight
and nobody has claimed ``chat`` yet.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from mug.realtime import FrameRouter, read_frames


class _Socket:
    """A socket that answers a scripted list of frames, then blocks forever."""

    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self._frames = list(frames)
        self.closed = False

    async def receive_text(self) -> str:
        if self._frames:
            return json.dumps(self._frames.pop(0))
        # Nothing more to say, and the connection stays open. The router must not
        # treat a quiet socket as a closed one.
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def _router(frames: list[dict[str, Any]]) -> FrameRouter:
    return FrameRouter(_Socket(frames))  # pyright: ignore[reportArgumentType]


async def test_each_frame_reaches_the_activity_that_claimed_its_type() -> None:
    """The game reads input, the conversation reads chat, and neither reads both."""
    router = _router(
        [
            {"type": "input", "keys": ["ArrowLeft"]},
            {"type": "chat", "text": "hello"},
            {"type": "input", "keys": []},
        ]
    )
    game = router.subscribe("input", "interval_done")
    talk = router.subscribe("chat", "chat_end")
    reader = asyncio.create_task(router.run())
    try:
        assert (await game.get()) == {"type": "input", "keys": ["ArrowLeft"]}
        assert (await talk.get()) == {"type": "chat", "text": "hello"}
        assert (await game.get()) == {"type": "input", "keys": []}
    finally:
        reader.cancel()


async def test_a_frame_that_arrives_before_its_activity_subscribed_is_held() -> None:
    """A message typed while the other pane is still starting must not vanish.

    The router reads as soon as the connection is shared, and a composed mount
    starts its panes one after another. Dropping what arrives in that window would
    lose a participant's own words, which nothing downstream could ever recover.
    """
    router = _router([{"type": "chat", "text": "early"}])
    # Only the game has claimed anything yet, and the reader is already going.
    router.subscribe("input")
    reader = asyncio.create_task(router.run())
    try:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        talk = router.subscribe("chat")
        assert (await talk.get()) == {"type": "chat", "text": "early"}
    finally:
        reader.cancel()


async def test_a_frame_nobody_ever_claims_is_held_within_a_bound() -> None:
    """A client that sends a type nothing reads can not grow the hold without end."""
    router = _router([{"type": "junk", "n": n} for n in range(80)])
    reader = asyncio.create_task(router.run())
    try:
        await asyncio.sleep(0.05)
        held = router.subscribe("junk")
        seen: list[int] = []
        while True:
            try:
                frame = await asyncio.wait_for(held.get(), 0.05)
            except TimeoutError:
                break
            assert frame is not None
            seen.append(int(frame["n"]))
    finally:
        reader.cancel()
    # The most recent are kept, and the count is bounded rather than the whole 80.
    assert len(seen) <= 32
    assert seen[-1] == 79


async def test_the_end_of_the_connection_wakes_every_activity() -> None:
    """An activity learns the participant went away without watching the socket."""
    router = _router([])
    game = router.subscribe("input")
    talk = router.subscribe("chat")
    router.close()
    assert (await game.get()) is None
    assert (await talk.get()) is None


async def test_an_activity_that_subscribes_after_the_end_is_told_at_once() -> None:
    """A pane that starts late on a closed connection is not left waiting forever."""
    router = _router([])
    router.close()
    assert (await router.subscribe("chat").get()) is None


async def test_the_reader_stops_when_the_body_leaves() -> None:
    """``read_frames`` owns the reading task, so no reader outlives its activity."""
    socket = _Socket([{"type": "chat", "text": "hi"}])
    async with read_frames(socket) as router:  # pyright: ignore[reportArgumentType]
        talk = router.subscribe("chat")
        assert (await talk.get()) == {"type": "chat", "text": "hi"}
    # Leaving closes every channel, so an activity still reading is woken.
    assert (await talk.get()) is None


@pytest.mark.parametrize("skipped", ['"a string"', "42", "[1, 2]"])
async def test_a_frame_that_is_not_an_object_is_skipped_and_costs_nothing(
    skipped: str,
) -> None:
    """A frame that is not an object is passed over, and the next one still lands.

    A client that sends one odd frame must not lose its activity's reading for the
    rest of the connection.
    """
    router = FrameRouter(_Raw([skipped, json.dumps({"type": "chat", "text": "hi"})]))  # pyright: ignore[reportArgumentType]
    talk = router.subscribe("chat")
    reader = asyncio.create_task(router.run())
    try:
        assert (await talk.get()) == {"type": "chat", "text": "hi"}
    finally:
        reader.cancel()


class _Raw:
    """A socket that answers a scripted list of raw strings, then blocks."""

    def __init__(self, raw: list[str]) -> None:
        self._raw = list(raw)

    async def receive_text(self) -> str:
        if self._raw:
            return self._raw.pop(0)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")
