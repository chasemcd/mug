"""Comprehensive unit tests for mug.rendering.Surface.

Covers requirements: SURF-01 through SURF-10 (draw methods and wire format),
COORD-01/02 (coordinate conversion), IDENT-01/03 (identity and tweening),
DELTA-01 through DELTA-04 (persistence, deltas, tracking, reset).
"""

from __future__ import annotations

import pytest

from mug.rendering import RenderPacket, Surface

# ======================================================================
# Helpers
# ======================================================================


def _first_obj(packet: RenderPacket) -> dict:
    """Return the first wire-format object from a RenderPacket."""
    assert len(packet.objects) >= 1, "Expected at least 1 object in packet"
    return packet.objects[0]


# ======================================================================
# SURF-01 through SURF-10: Draw methods produce correct wire format
# ======================================================================


class TestDrawMethods:
    """Each draw method produces the correct object_type and params in wire format."""

    def test_rect_basic(self) -> None:
        s = Surface(800, 600)
        s.rect(x=100, y=200, w=50, h=30, color="red")
        pkt = s.commit()
        obj = _first_obj(pkt)
        assert obj["object_type"] == "rect"
        assert obj["color"] == "#ff0000"
        # Pixel coords should be converted to relative
        assert obj["x"] == pytest.approx(100 / 800)
        assert obj["y"] == pytest.approx(200 / 600)
        assert obj["w"] == pytest.approx(50 / 800)
        assert obj["h"] == pytest.approx(30 / 600)

    def test_circle_basic(self) -> None:
        s = Surface(800, 600)
        s.circle(x=400, y=300, radius=25, color=(0, 255, 0))
        pkt = s.commit()
        obj = _first_obj(pkt)
        assert obj["object_type"] == "circle"
        assert obj["color"] == "#00ff00"
        assert obj["x"] == pytest.approx(400 / 800)
        assert obj["y"] == pytest.approx(300 / 600)
        assert obj["radius"] == pytest.approx(25 / 800)  # max(800, 600) = 800

    def test_line_basic(self) -> None:
        s = Surface(800, 600)
        s.line(points=[(0, 0), (800, 600)], color="#fff")
        pkt = s.commit()
        obj = _first_obj(pkt)
        assert obj["object_type"] == "line"
        assert obj["color"] == "#ffffff"
        assert obj["points"] == pytest.approx([(0.0, 0.0), (1.0, 1.0)])

    def test_polygon_basic(self) -> None:
        s = Surface(800, 600)
        s.polygon(points=[(0, 0), (100, 0), (50, 100)], color="blue")
        pkt = s.commit()
        obj = _first_obj(pkt)
        assert obj["object_type"] == "polygon"
        assert obj["color"] == "#0000ff"

    def test_text_basic(self) -> None:
        s = Surface(800, 600)
        s.text(text="Hello", x=10, y=10, size=24, color="white")
        pkt = s.commit()
        obj = _first_obj(pkt)
        assert obj["object_type"] == "text"
        assert obj["text"] == "Hello"
        assert obj["color"] == "#ffffff"
        assert obj["size"] == 24
        assert obj["x"] == pytest.approx(10 / 800)
        assert obj["y"] == pytest.approx(10 / 600)

    def test_image_basic(self) -> None:
        s = Surface(800, 600)
        s.image(image_name="player", x=0, y=0, w=64, h=64)
        pkt = s.commit()
        obj = _first_obj(pkt)
        assert obj["object_type"] == "sprite"
        assert obj["image_name"] == "player"
        assert obj["x"] == pytest.approx(0.0)
        assert obj["y"] == pytest.approx(0.0)
        assert obj["width"] == pytest.approx(64 / 800)
        assert obj["height"] == pytest.approx(64 / 600)

    def test_arc_basic(self) -> None:
        s = Surface(800, 600)
        s.arc(x=100, y=100, radius=50, start_angle=0, end_angle=3.14)
        pkt = s.commit()
        obj = _first_obj(pkt)
        assert obj["object_type"] == "arc"
        assert obj["start_angle"] == 0
        assert obj["end_angle"] == pytest.approx(3.14)
        assert obj["x"] == pytest.approx(100 / 800)
        assert obj["y"] == pytest.approx(100 / 600)
        assert obj["radius"] == pytest.approx(50 / 800)

    def test_ellipse_basic(self) -> None:
        s = Surface(800, 600)
        s.ellipse(x=200, y=200, rx=30, ry=20)
        pkt = s.commit()
        obj = _first_obj(pkt)
        assert obj["object_type"] == "ellipse"
        assert obj["x"] == pytest.approx(200 / 800)
        assert obj["y"] == pytest.approx(200 / 600)
        assert obj["rx"] == pytest.approx(30 / 800)
        assert obj["ry"] == pytest.approx(20 / 600)


class TestDrawOptionsBorderAndStroke:
    """border_radius, stroke_color, stroke_width appear in wire format."""

    def test_rect_border_radius(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=100, h=100, color="white", border_radius=10)
        obj = _first_obj(s.commit())
        assert obj["border_radius"] == 10

    def test_rect_stroke(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=100, h=100, color="white", stroke_color="black", stroke_width=2)
        obj = _first_obj(s.commit())
        assert obj["stroke_color"] == "#000000"
        assert obj["stroke_width"] == 2

    def test_circle_stroke(self) -> None:
        s = Surface(800, 600)
        s.circle(x=100, y=100, radius=50, color="white", stroke_color="red", stroke_width=1)
        obj = _first_obj(s.commit())
        assert obj["stroke_color"] == "#ff0000"
        assert obj["stroke_width"] == 1

    def test_polygon_stroke(self) -> None:
        s = Surface(800, 600)
        s.polygon(
            points=[(0, 0), (100, 0), (50, 100)],
            color="white",
            stroke_color="blue",
            stroke_width=3,
        )
        obj = _first_obj(s.commit())
        assert obj["stroke_color"] == "#0000ff"
        assert obj["stroke_width"] == 3


# ======================================================================
# COORD-01 and COORD-02: Coordinate handling
# ======================================================================


class TestCoordinateConversion:
    """Pixel coordinates converted to relative (0-1); relative=True passes through."""

    def test_pixel_coords_converted(self) -> None:
        s = Surface(800, 600)
        s.rect(x=400, y=300, w=100, h=100)
        obj = _first_obj(s.commit())
        assert obj["x"] == pytest.approx(0.5)
        assert obj["y"] == pytest.approx(0.5)

    def test_relative_coords_passthrough(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0.5, y=0.5, w=0.1, h=0.1, relative=True)
        obj = _first_obj(s.commit())
        assert obj["x"] == pytest.approx(0.5)
        assert obj["y"] == pytest.approx(0.5)
        assert obj["w"] == pytest.approx(0.1)
        assert obj["h"] == pytest.approx(0.1)

    def test_mixed_coords_in_one_frame(self) -> None:
        s = Surface(800, 600)
        s.rect(x=800, y=600, w=100, h=100)  # pixel
        s.rect(x=0.25, y=0.25, w=0.1, h=0.1, relative=True)  # relative
        pkt = s.commit()
        assert len(pkt.objects) == 2
        pixel_obj = pkt.objects[0]
        rel_obj = pkt.objects[1]
        assert pixel_obj["x"] == pytest.approx(1.0)
        assert pixel_obj["y"] == pytest.approx(1.0)
        assert rel_obj["x"] == pytest.approx(0.25)
        assert rel_obj["y"] == pytest.approx(0.25)

    def test_line_points_converted(self) -> None:
        s = Surface(800, 600)
        s.line(points=[(400, 300), (800, 0)])
        obj = _first_obj(s.commit())
        assert obj["points"] == pytest.approx([(0.5, 0.5), (1.0, 0.0)])

    def test_polygon_points_converted(self) -> None:
        s = Surface(800, 600)
        s.polygon(points=[(0, 0), (800, 0), (400, 600)])
        obj = _first_obj(s.commit())
        assert obj["points"] == pytest.approx([(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)])


# ======================================================================
# IDENT-01: Optional id parameter
# ======================================================================


class TestIdentity:
    """Auto-generated and explicit IDs."""

    def test_auto_id(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10)
        obj = _first_obj(s.commit())
        assert "uuid" in obj
        assert isinstance(obj["uuid"], str)
        assert len(obj["uuid"]) > 0

    def test_explicit_id(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10, id="myobj")
        obj = _first_obj(s.commit())
        assert obj["uuid"] == "myobj"

    def test_unique_auto_ids(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10)
        s.rect(x=0, y=0, w=20, h=20)
        pkt = s.commit()
        assert len(pkt.objects) == 2
        assert pkt.objects[0]["uuid"] != pkt.objects[1]["uuid"]


# ======================================================================
# IDENT-03: Tween duration
# ======================================================================


class TestTweenDuration:
    """tween_duration produces tween=True in wire format."""

    def test_tween_duration_sets_tween_true(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10, tween_duration=100)
        obj = _first_obj(s.commit())
        assert obj["tween"] is True
        assert obj["tween_duration"] == 100

    def test_no_tween_by_default(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10)
        obj = _first_obj(s.commit())
        assert obj["tween"] is False


# ======================================================================
# DELTA-01: Persistence
# ======================================================================


class TestPersistence:
    """Persistent objects stay; ephemeral objects are one-shot."""

    def test_persistent_object_stays(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10, id="bg", persistent=True)
        pkt1 = s.commit()
        assert len(pkt1.objects) == 1
        # Second commit without redrawing -- persistent already sent
        pkt2 = s.commit()
        assert len(pkt2.objects) == 0

    def test_ephemeral_object_gone(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10)  # ephemeral
        pkt1 = s.commit()
        assert len(pkt1.objects) == 1
        # Second commit -- ephemeral was cleared
        pkt2 = s.commit()
        assert len(pkt2.objects) == 0

    def test_persistent_requires_id(self) -> None:
        s = Surface(800, 600)
        with pytest.raises(ValueError, match="persistent.*id"):
            s.rect(x=0, y=0, w=10, h=10, persistent=True)


# ======================================================================
# DELTA-02: Delta computation
# ======================================================================


class TestDeltaComputation:
    """Only new or changed persistent objects are retransmitted."""

    def test_unchanged_persistent_empty_delta(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10, id="bg", persistent=True, color="red")
        s.commit()
        # Redraw identical persistent object
        s.rect(x=0, y=0, w=10, h=10, id="bg", persistent=True, color="red")
        pkt2 = s.commit()
        assert len(pkt2.objects) == 0

    def test_changed_persistent_retransmits(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10, id="bg", persistent=True, color="red")
        s.commit()
        # Redraw with different color
        s.rect(x=0, y=0, w=10, h=10, id="bg", persistent=True, color="blue")
        pkt2 = s.commit()
        assert len(pkt2.objects) == 1
        assert pkt2.objects[0]["color"] == "#0000ff"

    def test_mixed_ephemeral_persistent(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10, id="bg", persistent=True, color="red")
        s.circle(x=50, y=50, radius=5, color="blue")  # ephemeral
        pkt1 = s.commit()
        assert len(pkt1.objects) == 2

        # Only draw ephemeral next frame
        s.circle(x=60, y=60, radius=5, color="green")
        pkt2 = s.commit()
        # Only the ephemeral object; persistent unchanged so not retransmitted
        assert len(pkt2.objects) == 1
        assert pkt2.objects[0]["object_type"] == "circle"


# ======================================================================
# DELTA-03: Tracking
# ======================================================================


class TestDeltaTracking:
    """Committed persistent state is tracked internally."""

    def test_committed_state_tracks(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10, id="bg", persistent=True)
        s.commit()
        assert "bg" in s._committed_persistent


# ======================================================================
# DELTA-04: Reset
# ======================================================================


class TestReset:
    """reset() clears all internal state, forcing retransmission."""

    def test_reset_clears_everything(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10, id="bg", persistent=True)
        s.commit()
        s.reset()
        assert len(s._ephemeral_buffer) == 0
        assert len(s._persistent_current) == 0
        assert len(s._committed_persistent) == 0
        assert len(s._pending_removals) == 0

    def test_reset_causes_retransmission(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10, id="bg", persistent=True, color="red")
        s.commit()
        s.reset()
        # Redraw same persistent object after reset
        s.rect(x=0, y=0, w=10, h=10, id="bg", persistent=True, color="red")
        pkt = s.commit()
        # Should be retransmitted because tracking was cleared
        assert len(pkt.objects) == 1

    def test_reset_across_3_episodes(self) -> None:
        """Simulate 3 episodes: reset clears tracking each time, forcing retransmission."""
        s = Surface(800, 600)

        # Episode 1
        s.rect(x=0, y=0, w=800, h=600, id="bg", persistent=True, color="gray")
        s.circle(x=100, y=100, radius=10, color="red")  # ephemeral ball
        pkt1 = s.commit()
        assert len(pkt1.objects) == 2  # bg + ball

        # Episode 2
        s.reset()
        s.rect(x=0, y=0, w=800, h=600, id="bg", persistent=True, color="gray")
        s.circle(x=200, y=200, radius=10, color="green")  # new ball
        pkt2 = s.commit()
        # bg retransmitted (tracking cleared by reset) + ball
        assert len(pkt2.objects) == 2

        # Episode 3
        s.reset()
        s.rect(x=0, y=0, w=800, h=600, id="bg", persistent=True, color="gray")
        s.circle(x=300, y=300, radius=10, color="blue")  # new ball
        pkt3 = s.commit()
        # bg retransmitted again + ball
        assert len(pkt3.objects) == 2

        # Verify persistent object present in each episode
        for pkt in [pkt1, pkt2, pkt3]:
            bg_objs = [o for o in pkt.objects if o["uuid"] == "bg"]
            assert len(bg_objs) == 1, "Persistent bg should be in every post-reset commit"


# ======================================================================
# Remove
# ======================================================================


class TestRemove:
    """remove() produces correct removed list in the next commit."""

    def test_remove_in_next_commit(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10, id="obj", persistent=True)
        s.commit()
        s.remove("obj")
        pkt = s.commit()
        assert "obj" in pkt.removed

    def test_remove_nonexistent_no_error(self) -> None:
        s = Surface(800, 600)
        s.remove("doesnotexist")
        pkt = s.commit()
        assert "doesnotexist" in pkt.removed


# ======================================================================
# RenderPacket serialization
# ======================================================================


class TestRenderPacketSerialization:
    """to_dict() has the expected wire-format keys."""

    def test_to_dict_format(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10)
        pkt = s.commit()
        d = pkt.to_dict()
        assert "game_state_objects" in d
        assert "removed" in d
        assert isinstance(d["game_state_objects"], list)
        assert isinstance(d["removed"], list)


# ======================================================================
# Multiple objects and depth
# ======================================================================


class TestMultipleObjectsAndDepth:
    """Multiple objects in one frame and depth parameter."""

    def test_multiple_objects_in_frame(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10)
        s.circle(x=50, y=50, radius=5)
        s.line(points=[(0, 0), (100, 100)])
        s.text(text="hi", x=10, y=10)
        s.polygon(points=[(0, 0), (10, 0), (5, 10)])
        pkt = s.commit()
        assert len(pkt.objects) == 5

    def test_depth_in_wire(self) -> None:
        s = Surface(800, 600)
        s.rect(x=0, y=0, w=10, h=10, depth=5)
        obj = _first_obj(s.commit())
        assert obj["depth"] == 5
