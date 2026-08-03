"""Fixture 8: the Surface-rendering conformance scene, every primitive and rule.

``examples/render_conformance/scene.py`` is the scene itself -- a study anybody can
run, written so that a machine can read it: every shape is a flat block of one
colour at a stated place. This fixture drives that study through the running
application and reads the render packets a participant is actually pushed.

The parity document names six things, and each has a test here:

- **every logical primitive** -- all eight ops draw;
- **assets** -- the declared image and one frame of the declared atlas draw by
  name, never by path;
- **deltas** -- a persistent object that did not change is not sent again;
- **removal** -- an object that goes away makes its frame a keyframe, because a
  delta cannot say "this is no longer here";
- **depth** -- two overlapping blocks are ordered by what they declared;
- **animation** -- the moving object carries the tween the scene asked for.

A real browser draws this same scene and the pixels are sampled in
``tests/e2e_native/test_render_parity_browser.py``. That needs Chromium, so it is
not this fixture's job; this one proves what the server sends, which is what the
browser is given to draw.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

from _participant import Participant
from fastapi.testclient import TestClient

from examples.render_conformance.scene import (
    MARKER_END,
    MARKER_START,
    OVER,
    UNDER,
    conformance_spec,
    conformance_study,
)
from mug.app import build_study_app
from mug.game.types import SurfaceCommand
from mug.gateway import Gateway
from mug.storage import InMemoryStore

_EVERY_PRIMITIVE = {
    "rect",
    "circle",
    "ellipse",
    "line",
    "polygon",
    "arc",
    "text",
    "image",
}


@lru_cache(maxsize=1)
def _packets() -> tuple[dict[str, Any], ...]:
    """Walk a participant into the scene and return every render packet they get.

    The scene is played once for the whole module. It is deterministic and nothing
    here writes to what it returns, so playing it again per test would only make
    the fixture slower.
    """
    client = TestClient(
        build_study_app(
            study=conformance_study(),
            store=InMemoryStore(),
            gateway=Gateway(),
            game=conformance_spec(),
        )
    )
    collected: list[dict[str, Any]] = []
    with client, client.websocket_connect("/ws") as socket:
        person = Participant(socket).handshake()
        assert person.delivery("form")["form"]["form_key"] == "consent"
        person.advance({"agree": "yes"})
        assert person.delivery("game")["kind"] == "game"
        for _ in range(200):
            message = person.read()
            if message.get("type") == "render":
                collected.append(cast("dict[str, Any]", message["packet"]))
                continue
            if message.get("type") == "delivery":
                break
    assert collected, "the participant reached the scene and was pushed nothing"
    return tuple(collected)


def _commands(packet: dict[str, Any]) -> list[SurfaceCommand]:
    """Return one packet's drawing commands, validated against the frozen record."""
    return [
        SurfaceCommand.model_validate(one)
        for one in cast("list[Any]", packet["commands"])
    ]


def _named(commands: list[SurfaceCommand], object_id: str) -> SurfaceCommand | None:
    """Return the command that draws one named object, if the frame draws it."""
    for command in commands:
        if command.id == object_id:
            return command
    return None


def test_every_logical_primitive_draws() -> None:
    """All eight ops the contract names are emitted by the scene."""
    first = _commands(_packets()[0])
    assert {command.op for command in first} == _EVERY_PRIMITIVE


def test_the_declared_assets_draw_by_name() -> None:
    """A study names an image; the packet carries the name, never a path.

    This is what makes an asset servable by its own digest: the scene says
    ``badge``, and what a client fetches is decided by the manifest rather than by
    a string the environment made up.
    """
    first = _commands(_packets()[0])
    images = [command for command in first if command.op == "image"]

    assert {command.image_name for command in images} == {"badge", "sprites"}
    # One of them is a frame of an atlas rather than a whole picture, and the frame is
    # the name it was packed under. An index would mean nothing on its own: re-pack the
    # sheet and every index after the change moves, silently.
    atlas = next(command for command in images if command.image_name == "sprites")
    assert atlas.frame == "second.png"
    # Nothing in the packet is a file path.
    assert not any("/" in str(command.image_name or "") for command in images)


def test_depth_decides_what_covers_what() -> None:
    """Two overlapping blocks are ordered by what they declared, not by luck."""
    first = _commands(_packets()[0])
    blocks = {
        command.color: command.depth
        for command in first
        if command.op == "rect" and command.color in {UNDER, OVER}
    }

    assert blocks[UNDER] == 1
    assert blocks[OVER] == 2
    assert cast("float", blocks[OVER]) > cast("float", blocks[UNDER])


def test_a_persistent_object_that_did_not_change_is_not_sent_again() -> None:
    """This is what a delta is, and it is the only test that can tell.

    A delta carries the ephemeral shapes -- which are redrawn every frame by
    definition -- plus the **persistent** objects that changed. So a frame where
    the marker moved carries it, and the very next frame, where it stayed where it
    was, must not. Without a frame in which nothing moved, a stream that redrew the
    whole scene every time would pass every other test here.
    """
    packets = _packets()
    assert packets[0]["keyframe"] is True

    deltas = [one for one in packets[1:] if one["keyframe"] is False]
    assert deltas, "every frame was a keyframe, so nothing was ever a delta"

    moved = next(one for one in deltas if _named(_commands(one), "marker") is not None)
    held = next(
        one
        for one in deltas[deltas.index(moved) + 1 :]
        if _named(_commands(one), "marker") is None
    )

    assert len(_commands(held)) < len(_commands(moved))
    assert len(_commands(held)) < len(_commands(packets[0]))


def test_the_moving_object_moves_and_carries_its_tween() -> None:
    """Animation is declared by the scene and carried to the client."""
    packets = _packets()
    start = _named(_commands(packets[0]), "marker")
    assert start is not None
    assert (start.x, start.y) == MARKER_START
    assert start.tween_duration == 120
    assert start.persistent is True

    moved = None
    for packet in packets[1:]:
        found = _named(_commands(packet), "marker")
        if found is not None and (found.x, found.y) != MARKER_START:
            moved = found
            break

    assert moved is not None, "the marker never moved"
    assert (moved.x, moved.y) == MARKER_END
    assert moved.tween_duration == 120


def test_removing_an_object_makes_the_frame_a_keyframe() -> None:
    """A delta can say what changed; it cannot say what is no longer there.

    So a removal is a keyframe. Without that rule a client that joined late, or
    that dropped one packet, would keep drawing an object the scene had taken
    away, and nothing in the stream would ever correct it.
    """
    packets = _packets()
    assert _named(_commands(packets[0]), "marker") is not None

    # The scene's only later keyframe is the one the removal forced. Every frame
    # between the first and it is a delta, so nothing else could have caused it.
    keyframes = [
        index for index, packet in enumerate(packets[1:], start=1) if packet["keyframe"]
    ]
    assert keyframes, "the removal never forced a keyframe"
    removal = packets[keyframes[0]]

    assert _named(_commands(removal), "marker") is None
    # It is the whole scene again, minus the object that went away.
    assert len(_commands(removal)) == len(_commands(packets[0])) - 1
    # And it never comes back.
    for later in packets[keyframes[0] :]:
        assert _named(_commands(later), "marker") is None


def test_every_packet_validates_against_the_frozen_render_contract() -> None:
    """The scene draws nothing the API-07 record cannot carry."""
    for packet in _packets():
        commands = _commands(packet)
        assert commands, "a packet with no commands is not a frame"
        assert isinstance(packet["render_digest"], dict)
        assert packet["seat_key"]
