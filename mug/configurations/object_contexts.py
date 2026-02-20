"""Legacy ObjectContext classes — DEPRECATED.

These classes have been replaced by the Surface draw-call API.
Use :class:`mug.rendering.Surface` instead.

All classes in this module raise ``NotImplementedError`` on instantiation
to guide callers toward the new API.
"""


from __future__ import annotations


class _DeprecatedObjectContext:
    """Base stub that blocks instantiation with a migration message."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            f"{type(self).__name__} is removed. Migrate to Surface API "
            f"(see mug.rendering.Surface)."
        )

    def as_dict(self):
        raise NotImplementedError(
            f"{type(self).__name__} is removed. Migrate to Surface API "
            f"(see mug.rendering.Surface)."
        )


Sprite = type("Sprite", (_DeprecatedObjectContext,), {})
Line = type("Line", (_DeprecatedObjectContext,), {})
Circle = type("Circle", (_DeprecatedObjectContext,), {})
Polygon = type("Polygon", (_DeprecatedObjectContext,), {})
Text = type("Text", (_DeprecatedObjectContext,), {})
AtlasSpec = type("AtlasSpec", (_DeprecatedObjectContext,), {})
MultiAtlasSpec = type("MultiAtlasSpec", (_DeprecatedObjectContext,), {})
ImgSpec = type("ImgSpec", (_DeprecatedObjectContext,), {})
