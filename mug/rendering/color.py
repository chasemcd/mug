"""Color normalization utilities for the rendering pipeline.

All Surface draw methods accept colors in three formats:
  - RGB tuples: ``(255, 0, 0)``
  - Hex strings: ``'#FF0000'`` or shorthand ``'#F00'``
  - Named strings: ``'red'``

``normalize_color`` converts any of these to a canonical lowercase
``#rrggbb`` hex string suitable for the wire format.
"""

from __future__ import annotations

import re

# ~20 common CSS named colors mapped to #rrggbb hex strings.
NAMED_COLORS: dict[str, str] = {
    "red": "#ff0000",
    "green": "#008000",
    "blue": "#0000ff",
    "white": "#ffffff",
    "black": "#000000",
    "yellow": "#ffff00",
    "cyan": "#00ffff",
    "magenta": "#ff00ff",
    "orange": "#ffa500",
    "purple": "#800080",
    "pink": "#ffc0cb",
    "brown": "#a52a2a",
    "gray": "#808080",
    "grey": "#808080",
    "lime": "#00ff00",
    "navy": "#000080",
    "teal": "#008080",
    "maroon": "#800000",
    "olive": "#808000",
    "aqua": "#00ffff",
}

_HEX6_RE = re.compile(r"^#[0-9a-f]{6}$")
_HEX3_RE = re.compile(r"^#[0-9a-f]{3}$")


def normalize_color(color: tuple[int, int, int] | str) -> str:
    """Normalize a color value to a lowercase ``#rrggbb`` hex string.

    :param color: An RGB tuple ``(r, g, b)`` with ints 0-255, a hex string
        ``'#rrggbb'`` or ``'#rgb'``, or a CSS named color string.
    :returns: Lowercase ``#rrggbb`` hex string.
    :raises TypeError: If *color* is not a tuple or str.
    :raises ValueError: If the value cannot be interpreted as a valid color.
    """
    if isinstance(color, tuple):
        if len(color) != 3:
            raise ValueError(
                f"RGB tuple must have exactly 3 elements, got {len(color)}"
            )
        r, g, b = color
        if not all(isinstance(c, int) for c in (r, g, b)):
            raise ValueError(
                f"RGB tuple elements must be ints, got {tuple(type(c).__name__ for c in color)}"
            )
        if not all(0 <= c <= 255 for c in (r, g, b)):
            raise ValueError(
                f"RGB values must be 0-255, got ({r}, {g}, {b})"
            )
        return f"#{r:02x}{g:02x}{b:02x}"

    if isinstance(color, str):
        lower = color.lower().strip()

        # Check named colors first.
        if lower in NAMED_COLORS:
            return NAMED_COLORS[lower]

        # Check #rrggbb hex.
        if _HEX6_RE.match(lower):
            return lower

        # Check #rgb shorthand and expand.
        if _HEX3_RE.match(lower):
            r_ch, g_ch, b_ch = lower[1], lower[2], lower[3]
            return f"#{r_ch}{r_ch}{g_ch}{g_ch}{b_ch}{b_ch}"

        raise ValueError(f"Unrecognized color string: {color!r}")

    raise TypeError(
        f"color must be a tuple or str, got {type(color).__name__}"
    )
