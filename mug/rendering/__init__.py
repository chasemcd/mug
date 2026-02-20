"""PyGame-inspired imperative rendering API for MUG environments."""

from __future__ import annotations

from .color import NAMED_COLORS, normalize_color
from .types import DrawCommand, RenderPacket

# from .surface import Surface  # TODO: Plan 02 will add the Surface class

__all__ = [
    "DrawCommand",
    "NAMED_COLORS",
    "RenderPacket",
    "normalize_color",
]
