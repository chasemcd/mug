"""A study declares its pictures, and the browser loads them by digest.

Nothing in the authoring or content layers declared assets, so an environment that
wanted to draw an image had no way to say what the image was, and
``ClientManifest.resource_slots`` was always empty -- a published study said nothing
about what its clients must load.

These tests hold three promises: an environment names a picture and never a path,
the address is the digest of the bytes so nothing can be swapped under a running
study, and a study whose file is missing is refused at publication rather than
drawing nothing at run time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.content import Choice, Form, Page, Study
from mug.content.assets import (
    Atlas,
    AtlasFrame,
    Image,
    Sheet,
    asset_manifest,
    read_assets,
    resource_slots,
    stage_assets,
)
from mug.content.publish import client_manifest, normalized_study
from mug.gateway import Gateway
from mug.storage import InMemoryStore
from mug.storage.store import digest_of

_BALL = b"\x89PNG\r\n\x1a\n a round thing"
_SHEET = b"\x89PNG\r\n\x1a\n four little heroes"


# What a packer writes beside a sheet: the name of each frame, and its rectangle.
_HERO_ATLAS = {
    "frames": {
        "stand.png": {"frame": {"x": 0, "y": 0, "w": 16, "h": 16}},
        "walk.png": {"frame": {"x": 16, "y": 0, "w": 16, "h": 16}},
    }
}

# The other shape in use: a list of textures, each with a list of named frames.
_TEXTURE_ATLAS = {
    "textures": [
        {"frames": [{"filename": "one.png", "frame": {"x": 0, "y": 0, "w": 8, "h": 8}}]}
    ]
}


@pytest.fixture
def study_root(tmp_path: Path) -> Path:
    """A study directory with the files its assets name, sheet and atlas both."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "ball.png").write_bytes(_BALL)
    (tmp_path / "assets" / "hero.png").write_bytes(_SHEET)
    (tmp_path / "assets" / "hero.json").write_text(json.dumps(_HERO_ATLAS))
    return tmp_path


def _get(client: TestClient, path: str) -> httpx.Response:
    """Fetch one path, typed, so an assertion reads a known response.

    The test client's own ``get`` is loosely typed, so the one cast is here rather
    than at every call site.
    """
    fetch = cast("Any", client).get
    return cast("httpx.Response", fetch(path))


def _study(root: Path) -> Study:
    return Study(
        Form("consent", Choice("agree", "Do you consent?", ["yes", "no"])),
        Page("debrief", "# Thank you"),
        assets=[
            Image("ball", "assets/ball.png"),
            Atlas("hero", "assets/hero.png", "assets/hero.json"),
        ],
        asset_root=str(root),
    )


# -- what an author declares -----------------------------------------------------


def test_a_sheet_with_no_frames_is_refused() -> None:
    """A sheet with no rectangles is a sheet nothing can be drawn from."""
    with pytest.raises(ValueError, match="declares no frames"):
        Sheet("hero", "hero.png", frames={})


def test_the_platform_reads_the_atlas_so_a_study_does_not(study_root: Path) -> None:
    """A study says where the two files are; the frames come out of the atlas.

    This is the whole point of naming a frame. A study that had to hand over
    rectangles had to parse the packer's file itself, and every browser bundle then
    carried the resulting name-to-index map in its header.
    """
    sheet = _study(study_root).assets[1]

    assert sheet.name == "hero"
    assert dict(sheet.frames) == {
        "stand.png": AtlasFrame(sx=0, sy=0, sw=16, sh=16),
        "walk.png": AtlasFrame(sx=16, sy=0, sw=16, sh=16),
    }


def test_both_packer_shapes_are_read(tmp_path: Path) -> None:
    """Two shapes appear in real assets, so both are read rather than one guessed."""
    (tmp_path / "sheet.png").write_bytes(_SHEET)
    (tmp_path / "sheet.json").write_text(json.dumps(_TEXTURE_ATLAS))

    resolved = Atlas("s", "sheet.png", "sheet.json").resolved(root=tmp_path)

    assert dict(resolved.frames) == {"one.png": AtlasFrame(sx=0, sy=0, sw=8, sh=8)}


def test_an_atlas_that_declares_no_frames_is_refused(tmp_path: Path) -> None:
    """A file that is neither shape would declare a sheet nothing can be drawn from."""
    (tmp_path / "sheet.png").write_bytes(_SHEET)
    (tmp_path / "sheet.json").write_text(json.dumps({"meta": {"app": "something"}}))

    with pytest.raises(ValueError, match="declares no frames"):
        Atlas("s", "sheet.png", "sheet.json").resolved(root=tmp_path)


def test_an_atlas_that_cannot_be_read_is_refused(tmp_path: Path) -> None:
    """A missing atlas is the author's own mistake, said with the sheet's name."""
    (tmp_path / "sheet.png").write_bytes(_SHEET)

    with pytest.raises(ValueError, match=r"'s'.*cannot be read"):
        Atlas("s", "sheet.png", "missing.json").resolved(root=tmp_path)


def test_a_file_type_nobody_can_serve_is_refused_at_declaration() -> None:
    """A study must say what it ships rather than have it guessed at."""
    with pytest.raises(ValueError, match="unknown file type"):
        Image("ball", "assets/ball.bin")


def test_one_name_may_not_stand_for_two_files() -> None:
    """The name is how a drawing reaches the picture, so two files is ambiguous.

    It is refused rather than resolved because either answer is wrong: the study
    would draw whichever picture happened to be staged last, and nothing in the
    records would say which one a participant saw.
    """
    with pytest.raises(ValueError, match=r"'ball'.*'a\.png'.*'b\.png'"):
        Study(Page("x", "hi"), assets=[Image("ball", "a.png"), Image("ball", "b.png")])


def test_a_missing_file_is_named_in_the_failure(tmp_path: Path) -> None:
    """A picture that is not where the study said fails loudly, with both names."""
    with pytest.raises(FileNotFoundError, match=r"'ball'.*'assets/ball\.png'"):
        read_assets([Image("ball", "assets/ball.png")], root=tmp_path)


# -- what the platform does with it ----------------------------------------------


async def test_each_asset_is_addressed_by_the_digest_of_its_own_bytes(
    study_root: Path,
) -> None:
    """The address is the content, so nothing can be swapped under a running study."""
    store = InMemoryStore()
    gateway = Gateway(secret=b"a-shared-deployment-secret------")
    staged = await stage_assets(
        _study(study_root).assets,
        root=study_root,
        artifacts=store,
        new_artifact_id=lambda digest_hex: gateway.derived_id("artifact", digest_hex),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=lambda: "2026-07-27T00:00:00.000000Z",
    )

    assert staged["ball"].digest == digest_of(_BALL)
    assert staged["hero"].digest == digest_of(_SHEET)
    assert await store.read_artifact(staged["ball"].artifact_id) == _BALL


async def test_the_manifest_gives_a_client_a_name_a_digest_and_frames(
    study_root: Path,
) -> None:
    """What a browser is told: how to fetch it, and where the frames are."""
    store = InMemoryStore()
    gateway = Gateway(secret=b"a-shared-deployment-secret------")
    staged = await stage_assets(
        _study(study_root).assets,
        root=study_root,
        artifacts=store,
        new_artifact_id=lambda digest_hex: gateway.derived_id("artifact", digest_hex),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=lambda: "2026-07-27T00:00:00.000000Z",
    )
    manifest = asset_manifest(staged)

    assert manifest["ball"]["url"] == f"/assets/{digest_of(_BALL).hex}"
    assert manifest["ball"]["media_type"] == "image/png"
    assert manifest["ball"]["frames"] == {}
    # Keyed by the name the frame was packed under, so a drawing asks for it by name
    # and no order is part of the contract.
    assert manifest["hero"]["frames"] == {
        "stand.png": {"sx": 0, "sy": 0, "sw": 16, "sh": 16},
        "walk.png": {"sx": 16, "sy": 0, "sw": 16, "sh": 16},
    }
    assert "artifact_id" not in manifest["ball"]


def test_a_declared_asset_becomes_a_client_resource_slot(study_root: Path) -> None:
    """A published study says what its clients must load, which it never did."""
    slots = resource_slots(_study(study_root).assets, activation_slot="play")

    assert [one.slot for one in slots] == ["ball", "hero"]
    assert all(one.activation_slot == "play" for one in slots)
    assert all(one.presentation_policy == "required_before_activity" for one in slots)


def test_the_client_manifest_carries_the_slots_and_no_internal_id(
    study_root: Path,
) -> None:
    """The frozen manifest refuses internal ids, and a slot is not one."""
    manifest = client_manifest(_study(study_root))

    assert [one.slot for one in manifest.resource_slots] == ["ball", "hero"]


def test_two_studies_that_ship_different_pictures_are_two_versions(
    study_root: Path,
) -> None:
    """A study that redraws its sprite sheet is not the same study."""
    first = normalized_study(_study(study_root))
    # The same two files, re-packed: same sheet image, different rectangles. The
    # published study must not say nothing happened, which is what it would say if the
    # frames were still unread when the version was computed.
    (study_root / "assets" / "hero.json").write_text(
        json.dumps(
            {"frames": {"stand.png": {"frame": {"x": 0, "y": 0, "w": 32, "h": 32}}}}
        )
    )
    second = normalized_study(_study(study_root))

    assert first != second


# -- what a browser gets ----------------------------------------------------------


def test_the_application_serves_each_asset_at_its_own_digest(study_root: Path) -> None:
    """The proof: a browser fetches the declared picture by digest and gets it."""
    store = InMemoryStore()
    gateway = Gateway(secret=b"a-shared-deployment-secret------")
    client = TestClient(
        build_study_app(study=_study(study_root), store=store, gateway=gateway)
    )

    response = _get(client, f"/assets/{digest_of(_BALL).hex}")

    assert response.status_code == 200
    assert response.content == _BALL
    assert response.headers["content-type"] == "image/png"
    assert "immutable" in response.headers["cache-control"]


def test_a_digest_the_study_did_not_declare_is_not_served(study_root: Path) -> None:
    """The object store holds far more than the pictures, and none of it is public."""
    client = TestClient(
        build_study_app(
            study=_study(study_root),
            store=InMemoryStore(),
            gateway=Gateway(secret=b"a-shared-deployment-secret------"),
        )
    )

    missing = _get(client, "/assets/" + "0" * 64)
    assert missing.status_code == 404


def test_the_handshake_tells_the_client_what_to_load(study_root: Path) -> None:
    """The pictures load while the participant is on the forms."""
    client = TestClient(
        build_study_app(
            study=_study(study_root),
            store=InMemoryStore(),
            gateway=Gateway(secret=b"a-shared-deployment-secret------"),
        )
    )

    with client.websocket_connect("/ws") as socket:
        handshake = socket.receive_json()

    assert set(handshake["assets"]) == {"ball", "hero"}
    assert handshake["assets"]["ball"]["url"].endswith(digest_of(_BALL).hex)


def test_a_study_with_no_assets_serves_no_asset_route() -> None:
    """A study that declares none costs no route and tells its clients nothing."""
    client = TestClient(
        build_study_app(
            study=Study(Page("debrief", "# Thank you")),
            store=InMemoryStore(),
            gateway=Gateway(secret=b"a-shared-deployment-secret------"),
        )
    )

    missing = _get(client, "/assets/" + "0" * 64)
    assert missing.status_code == 404
    with client.websocket_connect("/ws") as socket:
        assert "assets" not in socket.receive_json()
