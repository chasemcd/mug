"""Declare the pictures a study draws, and serve them by their own digest.

An environment that draws ``surface.image(image_name="ball", ...)`` needs the study
to have said what ``ball`` is. Nothing in the authoring or content layers said so,
so an image was either impossible or a path the browser was trusted to fetch.

A study declares its assets by name::

    study = Study(
        Game("play"),
        assets=[
            Image("ball", "assets/ball.png"),
            Atlas("hero", "assets/hero.png", frames=[(0, 0, 16, 16), (16, 0, 16, 16)]),
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
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

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


@dataclass(frozen=True)
class Asset:
    """One declared picture: the name an environment draws it by, and its file."""

    name: str
    path: str
    frames: tuple[AtlasFrame, ...] = ()
    media_type: str | None = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("an asset needs a name to be drawn by")
        if self.media_type is None and _media_type_of(self.path) is None:
            raise ValueError(
                f"the asset {self.name!r} has an unknown file type; name its "
                "media_type"
            )

    def kind(self) -> str:
        """Return whether this asset is one picture or a sheet of them."""
        return "atlas" if self.frames else "image"

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
    *,
    frames: Sequence[tuple[int, int, int, int]],
    media_type: str | None = None,
) -> Asset:
    """Declare one sprite sheet and the rectangles its frames occupy.

    ``surface.image(image_name=name, frame=2, ...)`` then draws the third frame.
    An atlas with no frames is a picture, and it is refused here rather than
    drawing frame zero of nothing.
    """
    if not frames:
        raise ValueError(f"the atlas {name!r} declares no frames")
    return Asset(
        name=name,
        path=path,
        frames=tuple(AtlasFrame(*frame) for frame in frames),
        media_type=media_type,
    )


def _media_type_of(path: str) -> str | None:
    """Return the media type one file suffix means, or None for an unknown one."""
    return _MEDIA_TYPES.get(Path(path).suffix.lower())


@dataclass(frozen=True)
class StagedAsset:
    """One declared asset, read and addressed by the digest of its own bytes."""

    name: str
    digest: Digest
    media_type: str
    frames: tuple[AtlasFrame, ...]
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
            frames=asset.frames,
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
            "frames": [frame.as_json() for frame in one.frames],
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
    "StagedAsset",
    "asset_manifest",
    "asset_url",
    "by_digest",
    "read_assets",
    "resource_slots",
    "stage_assets",
]
