"""Declare the pictures a study draws, and serve them by their own digest.

An environment that draws ``surface.image(image_name="ball", ...)`` needs the study
to have said what ``ball`` is. Nothing in the authoring or content layers said so,
so an image was either impossible or a path the browser was trusted to fetch.

A study declares its assets by name::

    study = Study(
        Game("play"),
        assets=[
            Image("ball", "assets/ball.png"),
            Atlas("hero", "assets/hero.png", "assets/hero.json"),
        ],
    )

**The name is the whole contract.** An environment names a picture; it never names
a path, a URL, or a build directory. That is what lets the same environment run in
the browser, on the server, and in a replay, and it is what keeps a study from
depending on where its files happen to sit at run time.

**The address is the digest.** Each declared file is read once, digested, and staged
through the artifact layer; the client is given the digest, fetches
``/assets/<digest>``, and the server serves the bytes that hash to it. So a picture
cannot be swapped under a running study, a cache can hold it forever, and two
studies that use the same picture use the same bytes.

**A frame is a rectangle, not a convention.** A sprite atlas declares its frames
explicitly. Guessing a grid from an image size is how an atlas silently draws the
wrong sprite when someone re-exports it one pixel wider.

**A frame is reached by the name it was packed under.** ``Atlas`` is given the sheet
and the atlas file beside it, and the platform reads the file:

    Atlas("terrain", "sprites/terrain.png", "sprites/terrain.json")
    surface.image(image_name="terrain", frame="counter.png", ...)

The name is the contract, the same way it is for a whole picture. An **index** would
not be: an index means nothing on its own, so re-packing a sheet with one more sprite
moves every index after it, the study still runs, and it draws the wrong pictures with
nothing to say so. A name that is not in the sheet is refused instead, at publication,
with what the sheet does hold.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, cast

from mug.authoring.types import ClientResourceSlot
from mug.kernel import DataHandlingRef, Digest
from mug.storage import ArtifactStore, stage_artifact
from mug.storage.store import digest_of

# What a suffix means. A study that ships something else names its media type
# itself: guessing is how a font ends up served as an image.
_MEDIA_TYPES: Final[Mapping[str, str]] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}

# An asset is loaded before the activity that draws it, so the game never opens on
# a scene with holes in it.
_PRESENTATION_POLICY: Final[str] = "required_before_activity"

# A declared picture is authored material a participant is shown, so it is public:
# nothing about it is derived from anybody.
_PUBLIC = DataHandlingRef(privacy_labels=["public"])


@dataclass(frozen=True)
class AtlasFrame:
    """One rectangle of a sprite atlas, in the atlas image's own pixels."""

    sx: int
    sy: int
    sw: int
    sh: int

    def as_json(self) -> dict[str, int]:
        """Return the frame in the shape a renderer reads."""
        return {"sx": self.sx, "sy": self.sy, "sw": self.sw, "sh": self.sh}


def _no_frames() -> dict[str, AtlasFrame]:
    """Return an empty, typed frame map for a picture that is not a sheet."""
    return {}


@dataclass(frozen=True)
class Asset:
    """One declared picture: the name an environment draws it by, and its file.

    ``atlas`` is the packer's file beside the sheet, when this asset is a sheet. It is
    read where the image is read -- at publication, against the study's own asset root
    -- so that both paths mean the same thing and a study never has to make one of them
    absolute.

    ``frames`` maps the name each frame was packed under to the rectangle it occupies.
    A study may write it directly (``Sheet``), and otherwise it is read from ``atlas``.
    """

    name: str
    path: str
    atlas: str | None = None
    frames: Mapping[str, AtlasFrame] = field(default_factory=_no_frames)
    media_type: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("an asset needs a name to be drawn by")
        if self.media_type is None and _media_type_of(self.path) is None:
            raise ValueError(
                f"the asset {self.name!r} has an unknown file type; name its media_type"
            )

    def kind(self) -> str:
        """Return whether this asset is one picture or a sheet of them."""
        return "atlas" if self.atlas is not None or self.frames else "image"

    def sheet(self, *, root: Path) -> Mapping[str, AtlasFrame]:
        """Return this asset's frames, reading its atlas file if it has one."""
        if self.atlas is None:
            return self.frames
        return read_atlas(root / self.atlas, self.name)

    def resolved(self, *, root: Path) -> Asset:
        """Return this asset with its atlas read, so the frames are part of it.

        A study resolves its assets when it is built, because that is the one place
        that knows both the declaration and the asset root. It matters for more than
        convenience: the study version is computed from what an asset **is**
        (``mug.content.publish``), so a sheet whose frames were still unread would give
        one version for two different packings -- re-pack the sheet and every drawing
        changes while the published study says nothing happened.
        """
        if self.atlas is None:
            return self
        return Asset(
            name=self.name,
            path=self.path,
            atlas=None,
            frames=read_atlas(root / self.atlas, self.name),
            media_type=self.media_type,
        )

    def resolved_media_type(self) -> str:
        """Return the media type this asset is served as."""
        return self.media_type or (
            _media_type_of(self.path) or "application/octet-stream"
        )


def Image(name: str, path: str, *, media_type: str | None = None) -> Asset:
    """Declare one whole picture, drawn by ``name``."""
    return Asset(name=name, path=path, media_type=media_type)


def Atlas(
    name: str,
    path: str,
    atlas: str,
    *,
    media_type: str | None = None,
) -> Asset:
    """Declare one sprite sheet by its image and the atlas file beside it.

    The platform reads the atlas, so a study parses nothing and counts nothing:

        Atlas("terrain", "sprites/terrain.png", "sprites/terrain.json")
        surface.image(image_name="terrain", frame="counter.png", ...)

    ``atlas`` is a path against the same root as ``path``, and it is read at
    publication where the image is read. A sheet whose atlas cannot be read, or which
    declares no frames, is refused there -- before any participant, and with the
    sheet's name in the message.
    """
    return Asset(name=name, path=path, atlas=atlas, media_type=media_type)


def read_atlas(path: Path, name: str) -> dict[str, AtlasFrame]:
    """Read one atlas file into a map from packed name to rectangle.

    Two shapes are written by the packers in use, so both are read: a mapping of name
    to rectangle, and a list of textures each holding a list of named frames. A file
    that is neither is refused rather than read as empty -- an atlas with no frames
    would otherwise declare a sheet that fails at the first draw.
    """
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError as problem:
        raise ValueError(
            f"the sheet {name!r} names the atlas {str(path)!r}, which cannot be read"
        ) from problem
    packed = cast("dict[str, Any]", loaded) if isinstance(loaded, dict) else {}
    listed: list[tuple[str, dict[str, Any]]] = []
    declared = packed.get("frames")
    if isinstance(declared, dict):
        # One shape: a mapping of packed name to the rectangle it occupies.
        held = cast("dict[str, dict[str, Any]]", declared)
        listed = [(one, rectangle["frame"]) for one, rectangle in held.items()]
    elif isinstance(packed.get("textures"), list):
        # The other: a list of textures, each holding a list of named frames.
        textures = cast("list[dict[str, Any]]", packed["textures"])
        listed = [
            (cast("str", one["filename"]), cast("dict[str, Any]", one["frame"]))
            for texture in textures
            for one in cast("list[dict[str, Any]]", texture["frames"])
        ]
    if not listed:
        raise ValueError(
            f"the sheet {name!r} names the atlas {path.name!r}, which declares no "
            "frames: it is neither a frame mapping nor a texture list, so nothing can "
            "be drawn from it"
        )
    return {
        one: AtlasFrame(
            sx=int(rectangle["x"]),
            sy=int(rectangle["y"]),
            sw=int(rectangle["w"]),
            sh=int(rectangle["h"]),
        )
        for one, rectangle in listed
    }


def Sheet(
    name: str,
    path: str,
    *,
    frames: Mapping[str, tuple[int, int, int, int]],
    media_type: str | None = None,
) -> Asset:
    """Declare one sprite sheet whose frames are written out rather than packed.

    For a sheet with no atlas file: a study says the name of each frame and the
    rectangle it occupies. ``Atlas`` is the usual way, because a packer has already
    written that down.
    """
    if not frames:
        raise ValueError(f"the sheet {name!r} declares no frames")
    return Asset(
        name=name,
        path=path,
        frames={one: AtlasFrame(*rectangle) for one, rectangle in frames.items()},
        media_type=media_type,
    )


def _media_type_of(path: str) -> str | None:
    """Return the media type one file suffix means, or None for an unknown one."""
    return _MEDIA_TYPES.get(Path(path).suffix.lower())


def resolve_sheets(assets: Sequence[Asset], *, root: str | None) -> tuple[Asset, ...]:
    """Read every declared atlas, so each sheet carries the frames it was packed with.

    Called when a study is built. ``root`` is the study's own asset root, and with none
    the paths are read from the working directory the study runs from, which is the same
    rule the images follow.
    """
    where = Path(root) if root is not None else Path()
    return tuple(asset.resolved(root=where) for asset in assets)


@dataclass(frozen=True)
class StagedAsset:
    """One declared asset, read and addressed by the digest of its own bytes."""

    name: str
    digest: Digest
    media_type: str
    frames: Mapping[str, AtlasFrame]
    artifact_id: str
    size_bytes: int


def resource_slots(
    assets: Sequence[Asset], *, activation_slot: str
) -> list[ClientResourceSlot]:
    """Return the client resource slots a study's assets declare.

    ``ClientManifest.resource_slots`` was always empty, so a published study said
    nothing about what its clients must load. The slot is the asset name, which is
    the same name the environment draws by, and it carries no identifier -- the
    manifest is checked for internal ids, and a digest is not one.
    """
    return [
        ClientResourceSlot(
            slot=asset.name,  # pyright: ignore[reportArgumentType]
            activation_slot=activation_slot,  # pyright: ignore[reportArgumentType]
            media_type=asset.resolved_media_type(),
            presentation_policy=_PRESENTATION_POLICY,  # pyright: ignore[reportArgumentType]
        )
        for asset in assets
    ]


def read_assets(assets: Sequence[Asset], *, root: Path) -> dict[str, bytes]:
    """Read every declared file, and say which one is missing when one is.

    A study whose picture is not where it said is a study that would draw nothing
    and never say why, so it fails here instead -- at publication, with the name and
    the path in the message.
    """
    found: dict[str, bytes] = {}
    for asset in assets:
        path = root / asset.path
        if not path.is_file():
            raise FileNotFoundError(
                f"the asset {asset.name!r} names {asset.path!r}, which is not a file"
            )
        found[asset.name] = path.read_bytes()
    return found


async def stage_assets(
    assets: Sequence[Asset],
    *,
    root: Path,
    artifacts: ArtifactStore,
    new_artifact_id: Callable[[str], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
) -> dict[str, StagedAsset]:
    """Read, digest, and store every declared asset, keyed by the drawing name.

    ``new_artifact_id`` is given the digest of the bytes, so the address a picture
    is stored at is a function of the picture: a restart re-reaches it rather than
    storing a second copy, and two studies that ship the same file share one.
    """
    data = read_assets(assets, root=root)
    staged: dict[str, StagedAsset] = {}
    for asset in assets:
        blob = data[asset.name]
        # The atlas is read here, against the same root as the image, and it is not
        # staged: the platform has read it, so the frames travel in the manifest and
        # the participant's browser never fetches a packer file.
        frames = asset.sheet(root=root)
        blob_digest = digest_of(blob)
        reference = await stage_artifact(
            artifacts,
            data=blob,
            media_type=asset.resolved_media_type(),
            new_artifact_id=lambda hex=blob_digest.hex: new_artifact_id(hex),
            new_upload_id=new_upload_id,
            now=now,
            data_handling=_PUBLIC,
        )
        staged[asset.name] = StagedAsset(
            name=asset.name,
            digest=blob_digest,
            media_type=asset.resolved_media_type(),
            frames=frames,
            artifact_id=reference.artifact_id,
            size_bytes=len(blob),
        )
    return staged


def asset_manifest(staged: Mapping[str, StagedAsset]) -> dict[str, Any]:
    """Return what a client is told about the study's pictures.

    Each name carries the digest that addresses it, the media type it is served as,
    and the atlas frames when it has any. There is no artifact identifier in it: a
    client fetches by digest, which is a public address, and an internal identifier
    is not something a participant's browser is ever given.
    """
    return {
        name: {
            "digest": one.digest.hex,
            "media_type": one.media_type,
            "url": asset_url(one.digest.hex),
            # Keyed by the name each frame was packed under, so a drawing asks for
            # "counter.png" and the client looks it up. A list would make the order
            # the contract, and an order is what a re-packed sheet changes.
            "frames": {
                frame: rectangle.as_json()
                for frame, rectangle in sorted(one.frames.items())
            },
        }
        for name, one in sorted(staged.items())
    }


def asset_url(digest_hex: str) -> str:
    """Return the public address one asset digest is served at."""
    return f"/assets/{digest_hex}"


def by_digest(staged: Mapping[str, StagedAsset]) -> dict[str, StagedAsset]:
    """Index the staged assets by digest, which is how a request arrives."""
    return {one.digest.hex: one for one in staged.values()}


__all__ = [
    "Asset",
    "Atlas",
    "AtlasFrame",
    "Image",
    "Sheet",
    "StagedAsset",
    "asset_manifest",
    "asset_url",
    "by_digest",
    "read_assets",
    "read_atlas",
    "resolve_sheets",
    "resource_slots",
    "stage_assets",
]
