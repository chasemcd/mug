"""Sprites as assets, addressed by filename. The legacy shape, kept.

Scratch. Nothing in ``mug/`` imports it. Run it::

    uv run python scratch/api/sprites.py

It reads this repository's own Overcooked sheets, so every number below is real.

**What the legacy package did, and did right.** A study registered a sheet by its two
files and Phaser loaded them::

    surface.register_atlas("terrain", img_path=".../terrain.png",
                                      json_path=".../terrain.json")
    # mug/server/static/js/phaser_gym_graphics.js:353
    this.load.atlas(obj_config.name, obj_config.img_path, obj_config.atlas_path)

Phaser read the JSON itself, so every frame was known **by the name it was packed
under**, and a drawing said ``frame="counter.png"``. The legacy surface took
``frame: str | int`` and the renderer passed it straight through
(``sprite.setTexture(image_name, frame)``).

**What the rewrite does instead.** ``Atlas(name, path, frames=[(x, y, w, h), ...])``
makes the **study** parse the JSON and hand over an ordered list of rectangles, and a
drawing addresses a frame by its **integer index**. Three costs follow, and all three
are paid in this repository today:

1. ``examples/cogrid/sprites.py`` exists only to read the JSON and hand back a
   name-to-index map (``_sheet``, ``frames_of``).
2. Every browser bundle carries that map serialized into its header --
   ``TERRAIN_FRAMES``, ``OBJECT_FRAMES``, ``CHEF_FRAMES`` in
   ``examples/cogrid/env.py`` -- so the drawing can turn a name back into a number.
3. An index means nothing on its own. Re-pack a sheet with one more sprite and every
   index after it moves, the study still runs, and it draws the wrong pictures.

So this module puts the platform back where the legacy package was: **the platform
reads the JSON, and a frame is named by its filename.**
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# One rectangle of a sheet, in the sheet image's own pixels. The same record the
# platform already has; only how it is *reached* changes.
Rect = tuple[int, int, int, int]


@dataclass(frozen=True)
class Sheet:
    """One sprite sheet a study ships: two files, and the frames read out of them.

    ``frames`` is a map from the name the sheet was packed under to the rectangle it
    occupies. It is read by the platform at publication, so a study writes neither.
    """

    name: str
    image: str
    atlas: str
    frames: dict[str, Rect]

    def rect(self, frame: str) -> Rect:
        """Return one frame's rectangle, refusing a name this sheet does not hold.

        The refusal lists what the sheet does have, because a frame name is almost
        always a typing mistake or a sheet re-packed under different names, and an
        author needs to see the difference rather than go looking.
        """
        found = self.frames.get(frame)
        if found is None:
            near = ", ".join(sorted(self.frames)[:6])
            raise ValueError(
                f"the sheet {self.name!r} has no frame {frame!r}; it holds "
                f"{len(self.frames)} frames, including: {near}"
            )
        return found


def Atlas(name: str, image: str, atlas: str) -> Sheet:
    """Declare one sprite sheet by its image and the atlas file beside it.

    This is the legacy call in the platform's own vocabulary. The author says where
    the two files are; the platform reads the atlas, stages both by the digest of
    their own bytes, and puts the frame **names** in the client manifest. A drawing
    then says ``frame="counter.png"`` and neither side counts anything.
    """
    return Sheet(name=name, image=image, atlas=atlas, frames=_read(Path(atlas), name))


def _read(path: Path, name: str) -> dict[str, Rect]:
    """Read one atlas file, whichever shape the packer wrote.

    Two shapes appear in this repository's own assets, so both are read: a mapping of
    name to rectangle, and a list of textures each holding a list of named frames. A
    third file holds neither, and that is reported rather than read as empty -- an
    atlas with no frames is a sheet nothing can be drawn from, and today it would
    declare zero frames and fail at the first draw.
    """
    packed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    listed: list[tuple[str, dict[str, int]]] = []
    frames = packed.get("frames")
    if isinstance(frames, dict):
        listed = [(one, held["frame"]) for one, held in frames.items()]
    elif "textures" in packed:
        listed = [
            (one["filename"], one["frame"])
            for texture in packed["textures"]
            for one in texture["frames"]
        ]
    if not listed:
        raise ValueError(
            f"the sheet {name!r} names {path.name}, which declares no frames: it is "
            "neither a frame mapping nor a texture list, so nothing can be drawn "
            "from it"
        )
    return {
        one: (
            int(rectangle["x"]),
            int(rectangle["y"]),
            int(rectangle["w"]),
            int(rectangle["h"]),
        )
        for one, rectangle in listed
    }


def manifest_of(sheets: list[Sheet]) -> dict[str, Any]:
    """Return what a client is told about the study's sheets.

    The change from ``mug.content.assets.asset_manifest`` is one word: ``frames`` is
    an **object keyed by name** rather than a list whose order is the contract. A
    client resolves ``frame="counter.png"`` by looking it up, which is what both
    shipped clients already do behind ``assets.frame(image_name, frame)`` -- the
    lookup is by name instead of by index and nothing else moves.
    """
    return {
        sheet.name: {
            # The digest goes here in the real thing; the shape is the point.
            "url": f"/assets/<digest of {Path(sheet.image).name}>",
            "media_type": "image/png",
            "frames": {
                one: {"sx": r[0], "sy": r[1], "sw": r[2], "sh": r[3]}
                for one, r in sorted(sheet.frames.items())
            },
        }
        for sheet in sheets
    }


# -- what the Overcooked drawing becomes --------------------------------------------


def draw_kitchen(surface: Any, scene: dict[str, Any]) -> None:
    """Draw one frame of the kitchen. This is the whole drawing, once.

    Compare ``examples/cogrid/env.py``, where the same drawing is written **three
    times**: ``draw_kitchen`` for a server run, ``draw`` inside ``_MESH_BUNDLE``, and
    ``draw`` inside ``_BROWSER_BUNDLE``. The two bundled copies exist because the
    server's version reaches into ``examples/cogrid/sprites.py`` for ``frames_of``,
    which cannot travel, so each bundle got the map injected into its header and a
    drawing written around it.

    Naming a frame by its filename removes the reason for all of that. This function
    references asset **names** and literals and nothing else, so its source travels
    as it stands -- one drawing, on the server and in the browser both.
    """
    cols, rows = int(scene["cols"]), int(scene["rows"])
    width, height = 1.0 / cols, 1.0 / rows

    def at(sheet: str, sprite: str, pos: list[int], ident: str, **extra: Any) -> None:
        row, column = pos
        surface.image(
            image_name=sheet,
            frame=sprite,
            x=column / cols,
            y=row / rows,
            w=width,
            h=height,
            object_id=ident,
            **extra,
        )

    for one in scene["tiles"]:
        at("terrain", one["sprite"], one["pos"], one["id"], persistent=True, depth=-2)
    for one in scene["things"]:
        at("objects", one["sprite"], one["pos"], one["id"], depth=1)
    for index, chef in enumerate(scene["chefs"]):
        facing, carrying = chef["facing"], chef["carrying"]
        at("chefs", f"{facing}{carrying}.png", chef["pos"], f"chef-{index}")


# -- run it against this repository's own sheets -------------------------------------

_SPRITES = (
    Path(__file__).resolve().parents[2] / "examples/cogrid/assets/overcooked/sprites"
)


def sheets() -> list[Sheet]:
    """Declare the Overcooked sheets the way a study would."""
    return [
        Atlas(name, str(_SPRITES / f"{name}.png"), str(_SPRITES / f"{name}.json"))
        for name in ("terrain", "objects", "chefs", "soups")
    ]


def main() -> None:
    """Read the real sheets, resolve a frame by name, and show what deletes."""
    print("the sheets this repository ships, read by the platform")
    print("=" * 78)
    declared = sheets()
    for sheet in declared:
        named = ", ".join(sorted(sheet.frames)[:3])
        print(f"  {sheet.name:10} {len(sheet.frames):3} frames   e.g. {named}")
    print()

    print("a frame addressed by name")
    print("=" * 78)
    terrain = declared[0]
    print(f"  terrain / counter.png     -> {terrain.rect('counter.png')}")
    chefs = next(one for one in declared if one.name == "chefs")
    print(f"  chefs   / EAST-onion.png  -> {chefs.rect('EAST-onion.png')}")
    print()

    print("a frame name the sheet does not have")
    print("=" * 78)
    try:
        terrain.rect("counter.PNG")
    except ValueError as refused:
        print(f"  {refused}")
    print()

    print("a sheet whose atlas declares no frames")
    print("=" * 78)
    try:
        Atlas("tiles", str(_SPRITES / "tiles.png"), str(_SPRITES / "tiles.json"))
    except ValueError as refused:
        print(f"  {refused}")
    print()

    print("what deletes")
    print("=" * 78)
    print("  examples/cogrid/sprites.py   _sheet(), frames_of(), atlas()  -- the whole")
    print("                               reason this module exists")
    print("  examples/cogrid/env.py       TERRAIN_FRAMES, OBJECT_FRAMES, CHEF_FRAMES")
    print("                               injected into _BROWSER_BUNDLE's header")
    print("                               (env.py:1008-1010), and the second and third")
    print("                               copies of the drawing written around them")
    print("  mug/content/assets.py        Atlas(..., frames=[(x, y, w, h), ...]) and")
    print("                               every study's obligation to parse an atlas")
    print()
    print("  the manifest shape a client reads:")
    one = manifest_of([terrain])["terrain"]
    listed = list(one["frames"])[:3]
    print(
        f"    terrain.frames is an object keyed by name, {len(one['frames'])} entries"
    )
    print(f"    {listed} ...")


if __name__ == "__main__":
    main()
