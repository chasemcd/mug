"""The Overcooked sprite sheets, the pictures its pages show, and its policy file.

Each sheet is declared by its image and the atlas file beside it, and the platform
reads the atlas. The drawing then says ``frame="counter.png"`` -- the name the sheet
was packed under -- so this module parses nothing and counts nothing.

It used to. The platform drew a frame by its **index**, so this module read every
``.json``, kept the order the file listed its frames in, and handed back a
name-to-index map that each browser bundle then carried in its header. All of that is
gone: a name is the contract, the same way it is for a whole picture.
"""

from __future__ import annotations

from pathlib import Path

from mug.content.assets import Asset, Atlas, Image

ASSET_ROOT = Path(__file__).resolve().parent / "assets/overcooked"
SPRITE_ROOT = ASSET_ROOT / "sprites"
SHARED_ROOT = Path(__file__).resolve().parents[1] / "shared/assets"

# The sheets the Overcooked drawing uses, in the order a study declares them.
SHEETS = ("terrain", "chefs", "objects", "soups")

# The trained policy a human-AI study plays against. It is declared like every
# other file the study ships: named here, served by its own digest, and asked for
# by name. A study that runs it in the browser names this and nothing else -- no
# path and no address reaches the participant's machine.
POLICY_ASSET = "overcooked-policy"

# The pictures the written pages show: which chef is whose, and which keys move
# it. A page names one of these, the same way the drawing names a sprite sheet.
PAGE_PICTURES = {
    "blue-chef": ASSET_ROOT / "blue_chef.png",
    "green-chef": ASSET_ROOT / "green_chef.png",
    "arrow-keys": SHARED_ROOT / "keys/arrow_keys_2.png",
    "w-key": SHARED_ROOT / "keys/icons8-w-key-50.png",
    "cramped-room": ASSET_ROOT / "cramped_room.png",
}


def atlas(name: str) -> Asset:
    """Declare one sprite sheet for a study to serve, image and atlas together."""
    return Atlas(
        name,
        str(SPRITE_ROOT / f"{name}.png"),
        str(SPRITE_ROOT / f"{name}.json"),
    )


def policy_asset() -> Asset:
    """Declare the trained policy, for a study whose partner runs in the browser.

    It is not a picture, so it names its own media type: guessing one from a file
    ending is how a model gets served as an image and fails to load with no reason
    given.
    """
    return Asset(
        name=POLICY_ASSET,
        path=str(ASSET_ROOT / "models/cogrid-0.2.1-cramped-room.onnx"),
        media_type="application/octet-stream",
    )


def overcooked_assets(*, policy: bool = False) -> list[Asset]:
    """Return everything an Overcooked study serves: sprites, pictures, and model.

    ``policy`` adds the trained network, which only a study that runs the partner
    in the participant's own browser needs. A server-run study reads the same file
    from disk and never ships it.
    """
    declared = [atlas(name) for name in SHEETS]
    declared += [Image(name, str(path)) for name, path in PAGE_PICTURES.items()]
    if policy:
        declared.append(policy_asset())
    return declared


__all__ = [
    "ASSET_ROOT",
    "PAGE_PICTURES",
    "POLICY_ASSET",
    "SHEETS",
    "SPRITE_ROOT",
    "atlas",
    "overcooked_assets",
    "policy_asset",
]
