"""A small imperative drawing target that builds surface commands.

An environment draws itself onto a ``Surface`` with a few primitive calls, and the
surface accumulates the backend-neutral ``SurfaceCommand`` list that a render
packet ships to a seat. Every coordinate is relative (0 to 1) unless the drawing
says otherwise, so the drawing does not depend on the seat canvas size. The
renderer is the most swappable layer: it is a pure downstream view of this list.

**Every primitive the logical rendering API names.** Rectangle, circle, ellipse,
line, polygon, arc, text, and image. The frozen ``SurfaceCommand`` has always
carried all eight; the drawing surface offered four, so half of them could not be
reached from an environment.

**Objects, not only pictures.** A command drawn with ``object_id`` and
``persistent`` is an object with a life: it is sent once, sent again when it
changes, kept by the renderer between frames, and dropped when ``remove`` says so.
A command with neither is ephemeral -- it belongs to the frame it was drawn in and
nothing else. That is the whole delta protocol, and it is what makes a scene of a
thousand static tiles cost one frame rather than every frame.

**Removal is a keyframe.** ``RenderPacket`` is a frozen record and it carries no
removal list, so a frame that drops an object is sent as a keyframe: the whole
scene, and the renderer keeps nothing that is not in it. A removal therefore costs
one full frame. That is the honest trade for not inventing a wire field, and it is
cheap because removals are rare where redraws are not.

``depth`` orders what covers what, and ``tween_duration`` asks the renderer to move
an object to its new position over that many milliseconds rather than jumping.
Both travel with the command, so the environment states intent and the renderer
decides how to honour it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mug.game.types import SurfaceCommand

_Number = int | float
_Point = tuple[_Number, _Number]


class Surface:
    """Accumulate surface commands in relative coordinates, frame by frame.

    One surface lives for a whole episode, because that is what an object model
    needs: it remembers which persistent objects the seat already holds, so each
    frame ships what changed rather than everything.
    """

    def __init__(self) -> None:
        self._ephemeral: list[SurfaceCommand] = []
        self._objects: dict[str, SurfaceCommand] = {}
        self._order: list[str] = []
        self._sent: dict[str, SurfaceCommand] = {}
        self._removed: set[str] = set()
        self._opened = True

    def clear(self) -> None:
        """Drop the ephemeral commands before drawing the next frame.

        Persistent objects are not cleared: they are what persists. An object goes
        away when ``remove`` says it does.
        """
        self._ephemeral.clear()

    def reset(self) -> None:
        """Forget every object, so the next frame is drawn from nothing.

        An episode reset uses this: the next frame is a keyframe and the renderer
        holds nothing from the round that just ended.
        """
        self._ephemeral.clear()
        self._objects.clear()
        self._order.clear()
        self._sent.clear()
        self._removed.clear()
        self._opened = True

    def commands(self) -> list[SurfaceCommand]:
        """Return everything currently drawn, in draw order.

        Persistent objects come first, in the order they were introduced, then the
        ephemeral commands of this frame. This is the whole scene rather than the
        delta, so a caller that ships every frame in full reads this one.
        """
        return [self._objects[key] for key in self._order] + list(self._ephemeral)

    def frame(self) -> tuple[list[SurfaceCommand], bool]:
        """Return what to send this frame, and whether it is a keyframe.

        A keyframe is the whole scene: the first frame, and any frame that removed
        an object. Every other frame carries the ephemeral commands plus the
        persistent objects that are new or have changed since they were last sent.
        """
        if self._opened or self._removed:
            self._opened = False
            self._removed.clear()
            self._sent = dict(self._objects)
            return self.commands(), True
        changed = [
            self._objects[key]
            for key in self._order
            if self._sent.get(key) != self._objects[key]
        ]
        self._sent = dict(self._objects)
        return changed + list(self._ephemeral), False

    def remove(self, object_id: str) -> None:
        """Drop one persistent object. The next frame is a keyframe without it."""
        if object_id in self._objects:
            del self._objects[object_id]
            self._order.remove(object_id)
            self._removed.add(object_id)

    # -- the primitives ---------------------------------------------------------

    def rect(
        self,
        *,
        x: _Number,
        y: _Number,
        w: _Number,
        h: _Number,
        color: str,
        fill: bool = True,
        object_id: str | None = None,
        **common: Any,
    ) -> None:
        """Draw one rectangle from a relative top-left corner."""
        self._draw(
            "rect", object_id, x=x, y=y, w=w, h=h, color=color, fill=fill, **common
        )

    def circle(
        self,
        *,
        x: _Number,
        y: _Number,
        radius: _Number,
        color: str,
        fill: bool = True,
        object_id: str | None = None,
        **common: Any,
    ) -> None:
        """Draw one circle at a relative centre and radius."""
        self._draw(
            "circle",
            object_id,
            x=x,
            y=y,
            radius=radius,
            color=color,
            fill=fill,
            **common,
        )

    def ellipse(
        self,
        *,
        x: _Number,
        y: _Number,
        rx: _Number,
        ry: _Number,
        color: str,
        fill: bool = True,
        object_id: str | None = None,
        **common: Any,
    ) -> None:
        """Draw one ellipse at a relative centre with two relative radii."""
        self._draw(
            "ellipse",
            object_id,
            x=x,
            y=y,
            rx=rx,
            ry=ry,
            color=color,
            fill=fill,
            **common,
        )

    def arc(
        self,
        *,
        x: _Number,
        y: _Number,
        radius: _Number,
        start_angle: _Number,
        end_angle: _Number,
        color: str,
        fill: bool = False,
        object_id: str | None = None,
        **common: Any,
    ) -> None:
        """Draw one arc, with both angles in radians clockwise from east."""
        self._draw(
            "arc",
            object_id,
            x=x,
            y=y,
            radius=radius,
            start_angle=start_angle,
            end_angle=end_angle,
            color=color,
            fill=fill,
            **common,
        )

    def line(
        self,
        *,
        points: list[_Point],
        color: str,
        object_id: str | None = None,
        **common: Any,
    ) -> None:
        """Draw one open polyline through relative points."""
        self._draw("line", object_id, points=points, color=color, **common)

    def polygon(
        self,
        *,
        points: list[_Point],
        color: str,
        fill: bool = True,
        object_id: str | None = None,
        **common: Any,
    ) -> None:
        """Draw one closed polygon through relative points."""
        self._draw(
            "polygon", object_id, points=points, color=color, fill=fill, **common
        )

    def text(
        self,
        *,
        x: _Number,
        y: _Number,
        text: str,
        color: str,
        font_size: _Number = 16,
        object_id: str | None = None,
        **common: Any,
    ) -> None:
        """Draw one text label anchored at a relative point."""
        self._draw(
            "text",
            object_id,
            x=x,
            y=y,
            text=text,
            color=color,
            font_size=font_size,
            **common,
        )

    def image(
        self,
        *,
        image_name: str,
        x: _Number,
        y: _Number,
        w: _Number,
        h: _Number,
        frame: int | None = None,
        angle: _Number | None = None,
        object_id: str | None = None,
        **common: Any,
    ) -> None:
        """Draw one declared image, or one frame of a declared sprite atlas.

        ``image_name`` names an asset the study declared (``mug.content.assets``).
        The renderer resolves it against the collection in the client manifest, so
        the environment names a picture and never a path or a URL.
        """
        self._draw(
            "image",
            object_id,
            image_name=image_name,
            x=x,
            y=y,
            w=w,
            h=h,
            frame=frame,
            angle=angle,
            **common,
        )

    # -- building one command ----------------------------------------------------

    def _draw(self, op: str, object_id: str | None, **fields: Any) -> None:
        """Build one command and file it as an object or as this frame's drawing."""
        persistent = bool(fields.pop("persistent", False))
        depth = fields.pop("depth", 0)
        relative = fields.pop("relative", True)
        alpha = fields.pop("alpha", None)
        tween_duration = fields.pop("tween_duration", None)
        command = SurfaceCommand(
            op=op,  # pyright: ignore[reportArgumentType]
            id=object_id,
            persistent=persistent or None,
            relative=relative,
            depth=depth,
            alpha=alpha,
            tween_duration=tween_duration,
            **_present(fields),
        )
        if persistent and object_id is not None:
            if object_id not in self._objects:
                self._order.append(object_id)
            self._objects[object_id] = command
            return
        self._ephemeral.append(command)


def _present(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Drop the optional fields a caller left unset, so the record stays sparse."""
    return {key: value for key, value in fields.items() if value is not None}
