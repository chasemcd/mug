"""Data structures for the rendering pipeline.

DrawCommand is the immutable record produced by each Surface draw call.
RenderPacket is the serializable container sent over the wire to the JS renderer.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class DrawCommand:
    """Immutable record of a single draw call.

    Produced by Surface draw methods and consumed by the delta/serialization
    layer.  The ``params`` dict holds all draw parameters with colors already
    normalized to ``#rrggbb`` hex strings and coordinates stored as-is.

    :param object_type: Shape kind, e.g. "rect", "circle", "line", "polygon",
        "text", "sprite", "arc", "ellipse".
    :param id: User-provided identifier or auto-generated UUID.
    :param params: All draw parameters (color as hex, coordinates as-is).
    :param persistent: When ``True`` the object is transmitted once and only
        retransmitted when its params change.
    """

    object_type: str
    id: str
    params: dict
    persistent: bool = False

    def __post_init__(self) -> None:
        # frozen dataclass prevents direct assignment; use object.__setattr__
        # to coerce params to a plain dict if a subclass was passed in.
        if not isinstance(self.params, dict):
            object.__setattr__(self, "params", dict(self.params))


@dataclasses.dataclass
class RenderPacket:
    """Wire-format container for a single frame's rendering data.

    ``objects`` is a list of dicts ready for JSON serialization (each dict
    corresponds to one draw command in wire format).  ``removed`` lists the
    IDs of persistent objects that should be destroyed on the client.

    The ``to_dict()`` output uses the key ``game_state_objects`` to maintain
    backward compatibility with the existing JS Phaser renderer.
    """

    objects: list[dict] = dataclasses.field(default_factory=list)
    removed: list[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to the wire-format dict expected by the JS renderer."""
        return {
            "game_state_objects": self.objects,
            "removed": self.removed,
        }
