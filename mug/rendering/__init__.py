"""PyGame-inspired imperative rendering API for MUG environments."""

from __future__ import annotations

from .color import NAMED_COLORS, normalize_color
from .surface import Surface
from .types import DrawCommand, RenderPacket

__all__ = [
    "DrawCommand",
    "NAMED_COLORS",
    "RenderPacket",
    "Surface",
    "normalize_color",
]
