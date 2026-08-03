"""The drawing surface offers every primitive, and ships objects as deltas.

Parity asks for rectangles, circles, lines, polygons, text, images, arcs, and
ellipses, plus stable object identity, updates, removal, depth, persistence, and
tweening. The frozen ``SurfaceCommand`` has always carried all of it; the drawing
surface offered four primitives and no object model, so half of the rendering API
could not be reached from an environment at all.

These tests are the surface's half of that. What the two clients do with the
commands is proven in a real browser (``tests/e2e_native``); what is proven here is
that the commands say what the environment meant.
"""

from __future__ import annotations

import math

from mug.game.surface import Surface
from mug.game.types import SurfaceCommand


def _ops(commands: list[SurfaceCommand]) -> list[str]:
    return [one.op for one in commands]


# -- every primitive -------------------------------------------------------------


def test_the_surface_draws_all_eight_primitives() -> None:
    """The logical rendering API names eight shapes; all eight are reachable."""
    surface = Surface()
    surface.rect(x=0.1, y=0.1, w=0.2, h=0.2, color="#111111")
    surface.circle(x=0.5, y=0.5, radius=0.05, color="#222222")
    surface.ellipse(x=0.5, y=0.2, rx=0.1, ry=0.05, color="#333333")
    surface.arc(
        x=0.3, y=0.7, radius=0.1, start_angle=0.0, end_angle=math.pi, color="#444444"
    )
    surface.line(points=[(0.0, 0.0), (1.0, 1.0)], color="#555555")
    surface.polygon(points=[(0.1, 0.9), (0.2, 0.8), (0.3, 0.9)], color="#666666")
    surface.text(x=0.5, y=0.9, text="hello", color="#777777")
    surface.image(image_name="ball", x=0.8, y=0.8, w=0.1, h=0.1)

    assert _ops(surface.commands()) == [
        "rect",
        "circle",
        "ellipse",
        "arc",
        "line",
        "polygon",
        "text",
        "image",
    ]


def test_a_command_carries_what_the_drawing_said_and_nothing_else() -> None:
    """An unset optional field is absent, not zero: sparse is what the wire wants."""
    surface = Surface()
    surface.arc(
        x=0.5,
        y=0.5,
        radius=0.2,
        start_angle=0.0,
        end_angle=math.pi / 2,
        color="#abcdef",
    )
    drawn = surface.commands()[0].model_dump(mode="json", exclude_none=True)

    assert drawn["op"] == "arc"
    assert drawn["start_angle"] == 0.0
    assert drawn["end_angle"] == math.pi / 2
    assert "points" not in drawn
    assert "image_name" not in drawn


def test_an_atlas_frame_travels_with_the_image_command() -> None:
    """A sprite sheet draws one frame, so the frame is part of the drawing.

    The frame is the name it was packed under. An index would mean nothing on its own:
    re-pack the sheet and every index after the change moves, while every drawing goes
    on working and draws something else.
    """
    surface = Surface()
    surface.image(
        image_name="hero",
        x=0.1,
        y=0.1,
        w=0.1,
        h=0.1,
        frame="walk-2.png",
        angle=1.5,
    )
    drawn = surface.commands()[0]

    assert drawn.image_name == "hero"
    assert drawn.frame == "walk-2.png"
    assert drawn.angle == 1.5


def test_a_drawing_may_use_pixels_instead_of_relative_coordinates() -> None:
    """Parity keeps both coordinate systems, and the command declares which."""
    surface = Surface()
    surface.rect(x=10, y=20, w=30, h=40, color="#000000", relative=False)

    assert surface.commands()[0].relative is False


# -- the object model ------------------------------------------------------------


def test_an_ephemeral_drawing_lasts_one_frame() -> None:
    """What is drawn without an identity belongs to the frame it was drawn in."""
    surface = Surface()
    surface.circle(x=0.5, y=0.5, radius=0.1, color="#000000")
    first, keyframe = surface.frame()
    assert keyframe is True
    assert len(first) == 1

    surface.clear()
    second, _ = surface.frame()
    assert second == []


def test_a_persistent_object_is_sent_once_and_kept() -> None:
    """A background that never changes costs one frame, not every frame."""
    surface = Surface()
    for _ in range(3):
        surface.clear()
        surface.rect(
            x=0, y=0, w=1, h=1, color="#eeeeee", object_id="floor", persistent=True
        )
        surface.frame()

    surface.clear()
    surface.rect(
        x=0, y=0, w=1, h=1, color="#eeeeee", object_id="floor", persistent=True
    )
    sent, keyframe = surface.frame()

    assert keyframe is False
    assert sent == []


def test_a_persistent_object_is_sent_again_when_it_changes() -> None:
    """An object that moved is an update, which is the whole point of the identity."""
    surface = Surface()
    surface.circle(
        x=0.1, y=0.5, radius=0.05, color="#ff0000", object_id="ball", persistent=True
    )
    surface.frame()

    surface.clear()
    surface.circle(
        x=0.2, y=0.5, radius=0.05, color="#ff0000", object_id="ball", persistent=True
    )
    sent, keyframe = surface.frame()

    assert keyframe is False
    assert [one.id for one in sent] == ["ball"]
    assert sent[0].x == 0.2


def test_a_removed_object_is_gone_and_the_frame_is_a_keyframe() -> None:
    """The packet carries no removal list, so a frame that drops one is sent whole."""
    surface = Surface()
    surface.rect(
        x=0, y=0, w=1, h=1, color="#eeeeee", object_id="floor", persistent=True
    )
    surface.circle(
        x=0.5, y=0.5, radius=0.1, color="#ff0000", object_id="ball", persistent=True
    )
    surface.frame()

    surface.clear()
    surface.remove("ball")
    surface.rect(
        x=0, y=0, w=1, h=1, color="#eeeeee", object_id="floor", persistent=True
    )
    sent, keyframe = surface.frame()

    assert keyframe is True
    assert [one.id for one in sent] == ["floor"]


def test_removing_an_object_that_was_never_drawn_changes_nothing() -> None:
    """An environment that removes twice must not force a keyframe for nothing."""
    surface = Surface()
    surface.rect(
        x=0, y=0, w=1, h=1, color="#eeeeee", object_id="floor", persistent=True
    )
    surface.frame()

    surface.clear()
    surface.remove("never-drawn")
    surface.rect(
        x=0, y=0, w=1, h=1, color="#eeeeee", object_id="floor", persistent=True
    )
    _, keyframe = surface.frame()

    assert keyframe is False


def test_a_reset_makes_the_next_frame_a_keyframe_of_nothing_kept() -> None:
    """An episode that starts again starts from an empty scene."""
    surface = Surface()
    surface.rect(
        x=0, y=0, w=1, h=1, color="#eeeeee", object_id="floor", persistent=True
    )
    surface.frame()

    surface.reset()
    surface.circle(x=0.5, y=0.5, radius=0.1, color="#000000")
    sent, keyframe = surface.frame()

    assert keyframe is True
    assert _ops(sent) == ["circle"]


def test_objects_keep_the_order_they_were_introduced_in() -> None:
    """Draw order is stable, so depth decides what covers what and nothing else."""
    surface = Surface()
    surface.rect(x=0, y=0, w=1, h=1, color="#111111", object_id="a", persistent=True)
    surface.rect(x=0, y=0, w=1, h=1, color="#222222", object_id="b", persistent=True)
    surface.frame()

    surface.clear()
    surface.rect(x=0, y=0, w=1, h=1, color="#333333", object_id="b", persistent=True)
    surface.rect(x=0, y=0, w=1, h=1, color="#111111", object_id="a", persistent=True)

    assert [one.id for one in surface.commands()] == ["a", "b"]


def test_depth_and_tween_travel_with_the_command() -> None:
    """The environment states the intent; how it is honoured is the client's."""
    surface = Surface()
    surface.circle(
        x=0.5,
        y=0.5,
        radius=0.1,
        color="#000000",
        object_id="ball",
        persistent=True,
        depth=3,
        tween_duration=250,
        alpha=0.5,
    )
    drawn = surface.commands()[0]

    assert drawn.depth == 3
    assert drawn.tween_duration == 250
    assert drawn.alpha == 0.5
    assert drawn.persistent is True


def test_an_object_id_without_persistence_is_still_ephemeral() -> None:
    """Naming a drawing does not make it an object; asking for it to persist does."""
    surface = Surface()
    surface.circle(x=0.5, y=0.5, radius=0.1, color="#000000", object_id="ball")
    surface.frame()

    surface.clear()
    sent, _ = surface.frame()

    assert sent == []
