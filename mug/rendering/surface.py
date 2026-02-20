"""PyGame-inspired imperative rendering surface.

The ``Surface`` class is the primary user-facing API for building render
frames.  Researchers call draw methods (``rect``, ``circle``, ``line``, etc.)
to accumulate draw commands during a step, then call ``commit()`` to produce a
``RenderPacket`` ready for the wire.

Persistent objects are tracked across commits so that only new or changed
objects are retransmitted (delta computation).  Ephemeral objects are sent
every commit and cleared afterward.
"""

from __future__ import annotations

import uuid as _uuid

from .color import normalize_color
from .types import DrawCommand, RenderPacket


class Surface:
    """Accumulates draw commands and produces delta-compressed render packets.

    :param width: Logical width of the rendering area in pixels.
    :param height: Logical height of the rendering area in pixels.
    """

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._ephemeral_buffer: list[DrawCommand] = []
        self._persistent_current: dict[str, DrawCommand] = {}
        self._committed_persistent: dict[str, dict] = {}
        self._pending_removals: set[str] = set()
        self._asset_specs: list[dict] = []

    # ------------------------------------------------------------------
    # Asset registration
    # ------------------------------------------------------------------

    def register_atlas(self, name: str, *, img_path: str, json_path: str) -> None:
        """Register a sprite atlas for preloading.

        :param name: Logical name used to reference this atlas in draw calls.
        :param img_path: Path to the atlas image file.
        :param json_path: Path to the atlas JSON descriptor.
        """
        self._asset_specs.append({
            "object_type": "atlas_spec",
            "name": name,
            "img_path": img_path,
            "atlas_path": json_path,
        })

    def register_image(self, name: str, *, path: str) -> None:
        """Register a standalone image for preloading.

        :param name: Logical name used to reference this image.
        :param path: Path to the image file.
        """
        self._asset_specs.append({
            "object_type": "img_spec",
            "name": name,
            "img_path": path,
        })

    def get_asset_specs(self) -> list[dict]:
        """Return registered asset specs for the ``assets_to_preload`` config.

        Each entry is a dict with at minimum ``name`` and ``img_path`` keys.
        Atlas entries also include an ``atlas_path`` key.

        :returns: A shallow copy of the internal asset spec list.
        """
        return list(self._asset_specs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_command(
        self,
        object_type: str,
        *,
        id: str | None = None,
        persistent: bool = False,
        relative: bool = False,
        depth: int = 0,
        tween_duration: int | float | None = None,
        **params: object,
    ) -> DrawCommand:
        """Create a ``DrawCommand`` from draw-method arguments."""
        if persistent and id is None:
            raise ValueError("persistent=True requires an id= parameter")
        if id is None:
            id = _uuid.uuid4().hex[:8]
        params["relative"] = relative
        params["depth"] = depth
        params["tween_duration"] = tween_duration
        return DrawCommand(
            object_type=object_type,
            id=id,
            params=params,
            persistent=persistent,
        )

    def _add_command(self, cmd: DrawCommand) -> None:
        """Route *cmd* to the ephemeral buffer or persistent store."""
        if cmd.persistent:
            self._persistent_current[cmd.id] = cmd
        else:
            self._ephemeral_buffer.append(cmd)

    def _to_wire(self, cmd: DrawCommand) -> dict:
        """Convert a ``DrawCommand`` to the wire-format dict.

        Coordinates are converted from pixel space to relative (0-1) unless
        the draw call specified ``relative=True``.
        """
        p = dict(cmd.params)  # shallow copy so we don't mutate the frozen DC

        relative = p.pop("relative", False)
        depth = p.pop("depth", 0)
        tween_duration = p.pop("tween_duration", None)

        # -- coordinate conversion ----------------------------------------
        if not relative:
            obj_type = cmd.object_type
            if obj_type == "rect":
                p["x"] = p["x"] / self.width
                p["y"] = p["y"] / self.height
                p["w"] = p["w"] / self.width
                p["h"] = p["h"] / self.height
            elif obj_type == "circle":
                p["x"] = p["x"] / self.width
                p["y"] = p["y"] / self.height
                p["radius"] = p["radius"] / max(self.width, self.height)
            elif obj_type in ("line", "polygon"):
                p["points"] = [
                    (px / self.width, py / self.height)
                    for px, py in p["points"]
                ]
            elif obj_type == "text":
                p["x"] = p["x"] / self.width
                p["y"] = p["y"] / self.height
            elif obj_type == "sprite":
                p["x"] = p["x"] / self.width
                p["y"] = p["y"] / self.height
                p["w"] = p["w"] / self.width
                p["h"] = p["h"] / self.height
            elif obj_type == "arc":
                p["x"] = p["x"] / self.width
                p["y"] = p["y"] / self.height
                p["radius"] = p["radius"] / max(self.width, self.height)
            elif obj_type == "ellipse":
                p["x"] = p["x"] / self.width
                p["y"] = p["y"] / self.height
                p["rx"] = p["rx"] / self.width
                p["ry"] = p["ry"] / self.height

        # -- assemble wire dict -------------------------------------------
        wire: dict = {
            "uuid": cmd.id,
            "object_type": cmd.object_type,
            "depth": depth,
            "tween": tween_duration is not None,
            "tween_duration": tween_duration if tween_duration is not None else 0,
            "permanent": cmd.persistent,
        }
        wire.update(p)
        return wire

    # ------------------------------------------------------------------
    # Draw methods (all keyword-only after self)
    # ------------------------------------------------------------------

    def rect(
        self,
        *,
        x: float | int,
        y: float | int,
        w: float | int,
        h: float | int,
        color: tuple[int, int, int] | str = "white",
        border_radius: float | int | None = None,
        stroke_color: tuple[int, int, int] | str | None = None,
        stroke_width: float | int | None = None,
        **common: object,
    ) -> None:
        """Draw a rectangle."""
        color = normalize_color(color)
        params: dict = {"x": x, "y": y, "w": w, "h": h, "color": color}
        if border_radius is not None:
            params["border_radius"] = border_radius
        if stroke_color is not None:
            params["stroke_color"] = normalize_color(stroke_color)
        if stroke_width is not None:
            params["stroke_width"] = stroke_width
        cmd = self._build_command("rect", **common, **params)
        self._add_command(cmd)

    def circle(
        self,
        *,
        x: float | int,
        y: float | int,
        radius: float | int,
        color: tuple[int, int, int] | str = "white",
        stroke_color: tuple[int, int, int] | str | None = None,
        stroke_width: float | int | None = None,
        **common: object,
    ) -> None:
        """Draw a circle (center-origin)."""
        color = normalize_color(color)
        params: dict = {"x": x, "y": y, "radius": radius, "color": color}
        if stroke_color is not None:
            params["stroke_color"] = normalize_color(stroke_color)
        if stroke_width is not None:
            params["stroke_width"] = stroke_width
        cmd = self._build_command("circle", **common, **params)
        self._add_command(cmd)

    def line(
        self,
        *,
        points: list[tuple[float | int, float | int]],
        color: tuple[int, int, int] | str = "white",
        width: int = 1,
        **common: object,
    ) -> None:
        """Draw a multi-segment line."""
        color = normalize_color(color)
        cmd = self._build_command(
            "line", **common, points=points, color=color, width=width,
        )
        self._add_command(cmd)

    def polygon(
        self,
        *,
        points: list[tuple[float | int, float | int]],
        color: tuple[int, int, int] | str = "white",
        stroke_color: tuple[int, int, int] | str | None = None,
        stroke_width: float | int | None = None,
        **common: object,
    ) -> None:
        """Draw a filled polygon."""
        color = normalize_color(color)
        params: dict = {"points": points, "color": color}
        if stroke_color is not None:
            params["stroke_color"] = normalize_color(stroke_color)
        if stroke_width is not None:
            params["stroke_width"] = stroke_width
        cmd = self._build_command("polygon", **common, **params)
        self._add_command(cmd)

    def text(
        self,
        *,
        text: str,
        x: float | int,
        y: float | int,
        size: int = 16,
        color: tuple[int, int, int] | str = "black",
        font: str = "Arial",
        **common: object,
    ) -> None:
        """Draw a text label."""
        color = normalize_color(color)
        cmd = self._build_command(
            "text", **common, text=text, x=x, y=y, size=size, color=color, font=font,
        )
        self._add_command(cmd)

    def image(
        self,
        *,
        image_name: str,
        x: float | int,
        y: float | int,
        w: float | int,
        h: float | int,
        frame: str | int | None = None,
        angle: float | int | None = None,
        **common: object,
    ) -> None:
        """Draw a sprite image (top-left origin).

        The wire-format ``object_type`` is ``"sprite"`` for backward
        compatibility with the existing JS Phaser renderer.
        """
        params: dict = {
            "image_name": image_name,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
        }
        if frame is not None:
            params["frame"] = frame
        if angle is not None:
            params["angle"] = angle
        cmd = self._build_command("sprite", **common, **params)
        self._add_command(cmd)

    def arc(
        self,
        *,
        x: float | int,
        y: float | int,
        radius: float | int,
        start_angle: float,
        end_angle: float,
        color: tuple[int, int, int] | str = "white",
        **common: object,
    ) -> None:
        """Draw an arc."""
        color = normalize_color(color)
        cmd = self._build_command(
            "arc",
            **common,
            x=x,
            y=y,
            radius=radius,
            start_angle=start_angle,
            end_angle=end_angle,
            color=color,
        )
        self._add_command(cmd)

    def ellipse(
        self,
        *,
        x: float | int,
        y: float | int,
        rx: float | int,
        ry: float | int,
        color: tuple[int, int, int] | str = "white",
        **common: object,
    ) -> None:
        """Draw an ellipse."""
        color = normalize_color(color)
        cmd = self._build_command(
            "ellipse", **common, x=x, y=y, rx=rx, ry=ry, color=color,
        )
        self._add_command(cmd)

    # ------------------------------------------------------------------
    # Frame lifecycle
    # ------------------------------------------------------------------

    def commit(self) -> RenderPacket:
        """Finalize the current frame and return a delta-compressed packet.

        Ephemeral objects are always included.  Persistent objects are only
        included when new or changed since the last commit.  The ephemeral
        buffer is cleared after each commit; persistent objects remain until
        explicitly removed.

        :returns: A ``RenderPacket`` ready for serialization.
        """
        objects: list[dict] = []
        removed: list[str] = list(self._pending_removals)

        # Ephemeral: always included
        for cmd in self._ephemeral_buffer:
            objects.append(self._to_wire(cmd))

        # Persistent: only if new or changed
        for obj_id, cmd in self._persistent_current.items():
            wire = self._to_wire(cmd)
            prev = self._committed_persistent.get(obj_id)
            if prev is None or prev != wire:
                objects.append(wire)
                self._committed_persistent[obj_id] = wire

        # Process removals
        for obj_id in self._pending_removals:
            self._committed_persistent.pop(obj_id, None)
            self._persistent_current.pop(obj_id, None)

        # Clear frame state
        self._ephemeral_buffer.clear()
        self._pending_removals.clear()

        return RenderPacket(objects=objects, removed=removed)

    def remove(self, id: str) -> None:
        """Mark a persistent object for removal in the next ``commit()``.

        :param id: The identifier of the persistent object to remove.
        """
        self._pending_removals.add(id)

    def reset(self) -> None:
        """Clear all internal state.

        After a reset, persistent objects will be retransmitted in the next
        ``commit()`` because the committed-state cache is empty.  Useful at
        episode boundaries.
        """
        self._ephemeral_buffer.clear()
        self._persistent_current.clear()
        self._committed_persistent.clear()
        self._pending_removals.clear()
