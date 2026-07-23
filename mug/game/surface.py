"""A small imperative drawing target that builds surface commands.

An environment draws itself onto a ``Surface`` with a few primitive calls, and the
surface accumulates the backend-neutral ``SurfaceCommand`` list that a render
packet ships to a seat. Every coordinate is relative (0 to 1), so the drawing does
not depend on the seat canvas size. The renderer is the most swappable layer: it is
a pure downstream view of this command list.

The demo pushes a full command list every frame, so the surface keeps no delta
state; ``clear`` resets it before each frame.
"""

from __future__ import annotations

from mug.game.types import SurfaceCommand

_Number = int | float
_Point = tuple[_Number, _Number]


class Surface:
    """Accumulate surface commands in relative coordinates for one frame."""

    def __init__(self) -> None:
        self._commands: list[SurfaceCommand] = []

    def clear(self) -> None:
        """Drop the accumulated commands before drawing the next frame."""
        self._commands.clear()

    def commands(self) -> list[SurfaceCommand]:
        """Return the commands drawn so far, in draw order."""
        return list(self._commands)

    def circle(
        self,
        *,
        x: _Number,
        y: _Number,
        radius: _Number,
        color: str,
        object_id: str | None = None,
        depth: _Number = 0,
    ) -> None:
        """Draw one filled circle at a relative centre and radius."""
        self._commands.append(
            SurfaceCommand(
                op="circle",
                id=object_id,
                x=x,
                y=y,
                radius=radius,
                color=color,
                fill=True,
                relative=True,
                depth=depth,
            )
        )

    def line(
        self,
        *,
        points: list[_Point],
        color: str,
        object_id: str | None = None,
        depth: _Number = 0,
    ) -> None:
        """Draw one open polyline through relative points."""
        self._commands.append(
            SurfaceCommand(
                op="line",
                id=object_id,
                points=points,
                color=color,
                relative=True,
                depth=depth,
            )
        )

    def polygon(
        self,
        *,
        points: list[_Point],
        color: str,
        fill: bool = True,
        object_id: str | None = None,
        depth: _Number = 0,
    ) -> None:
        """Draw one closed polygon through relative points."""
        self._commands.append(
            SurfaceCommand(
                op="polygon",
                id=object_id,
                points=points,
                color=color,
                fill=fill,
                relative=True,
                depth=depth,
            )
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
        depth: _Number = 0,
    ) -> None:
        """Draw one text label anchored at a relative point."""
        self._commands.append(
            SurfaceCommand(
                op="text",
                id=object_id,
                x=x,
                y=y,
                text=text,
                color=color,
                font_size=font_size,
                relative=True,
                depth=depth,
            )
        )
