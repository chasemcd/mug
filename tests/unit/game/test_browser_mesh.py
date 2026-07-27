"""The browser mesh manifest ships the platform's own code and checks what returns.

Two properties matter here and nothing else in the suite covers them.

The first is that the browser runs **this repository's** rollback engine and packet
codec, not a copy of them. A twin would be a second implementation of the
correctness core, and a drift between the two would split a mesh silently. So the
manifest carries the modules' own source bytes, and a test compares them with the
files on disk.

The second is that the server re-derives the trajectory identity from the frames a
peer submits, rather than believing the claim beside them. Every refusal below is
a way a peer could otherwise have named one run and submitted another.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from examples.tandem.browser_mesh_env import tandem_mesh_spec
from mug.game import browser_mesh_driver, mesh, wire
from mug.game.browser_mesh import (
    BrowserMeshSpec,
    MeshCaptureBinding,
    MeshCaptureError,
    browser_mesh_manifest,
    mesh_episode_summary,
    mesh_prelude_source,
    mesh_run_config,
    mesh_runtime_modules,
    trajectory_digest,
    verify_mesh_capture,
)
from mug.game.determinism import state_hash_source
from mug.kernel import Digest

_MESH_DIGEST = Digest(algorithm="sha-256", hex="c" * 64)


def _handle(index: int) -> str:
    return f"handle_00000000000000000000{index:02d}A"


def _binding(reference: str = "") -> MeshCaptureBinding:
    """Return the server-held identities one reported trajectory binds to."""
    handles = (_handle(1), _handle(2))
    return MeshCaptureBinding(
        interaction_id="interaction_019b6000-0000-7000-8000-0000000000a1",
        episode_id="episode_019b6000-0000-7000-8000-0000000000a2",
        channel_key="tandem",
        actor_by_handle={
            handles[0]: "actor_019b6000-0000-7000-8000-0000000000b1",
            handles[1]: "actor_019b6000-0000-7000-8000-0000000000b2",
        },
        seat_by_handle={handles[0]: "seat-1", handles[1]: "seat-2"},
        reference_handle=reference or handles[0],
        mesh_membership_digest=_MESH_DIGEST,
        membership_generation=1,
        recorded_at="2026-07-25T00:00:00.000000Z",
    )


def _payload(count: int = 3, **overrides: Any) -> dict[str, Any]:
    """Build one well-formed capture payload the tests then break in one way."""
    handles = (_handle(1), _handle(2))
    rows = [
        {
            "frame_number": index,
            "actions": {handles[0]: index % 5, handles[1]: (index + 2) % 5},
            "rewards": {handles[0]: 0.0, handles[1]: 1.0},
            "terminated": False,
            "truncated": False,
            "info": None,
            "state_hash": f"{index:064x}",
        }
        for index in range(count)
    ]
    payload: dict[str, Any] = {
        "schema": "mug.browser-mesh.capture",
        "version": 1,
        "channel_key": "tandem",
        "room_handle": "room_019b6000000000000000000000A",
        "negotiation_generation": 1,
        "frozen_peer_handles": list(handles),
        "frames": rows,
        "boundary": {
            "kind": "reset",
            "end_frame_exclusive": count,
            "state_hash": rows[-1]["state_hash"] if rows else None,
            "peer_end_frames": {handles[0]: count, handles[1]: count},
        },
    }
    payload.update(overrides)
    return payload


# -- the shipped runtime -------------------------------------------------------


def test_the_manifest_ships_the_platform_modules_byte_for_byte() -> None:
    """The browser runs this repository's engine and codec, not a copy of them."""
    shipped = {module["name"]: module["source"] for module in mesh_runtime_modules()}

    assert shipped["mug.game.mesh"] == inspect.getsource(mesh)
    assert shipped["mug.game.wire"] == inspect.getsource(wire)
    assert shipped["mug.game.browser_mesh_driver"] == inspect.getsource(
        browser_mesh_driver
    )
    assert list(shipped) == [
        "mug.game.mesh",
        "mug.game.wire",
        "mug.game.browser_mesh_driver",
    ]


def test_the_prelude_carries_the_one_shared_state_hash_hook() -> None:
    """The browser hashes state the exact way the server re-computes it."""
    assert mesh_prelude_source().startswith(state_hash_source())


def test_the_shipped_bundle_runs_with_no_platform_installed() -> None:
    """The bundle is self-contained: standard library only, as a browser has.

    Pyodide is CPython with no platform package and no wheels. This runs the
    shipped bundle in an isolated interpreter that cannot import ``mug`` at all,
    so a runtime module that grew a platform import would fail here rather than
    in a participant's browser.
    """
    bundle = {
        "prelude": mesh_prelude_source(),
        "modules": list(mesh_runtime_modules()),
        "study": tandem_mesh_spec().source_bundle,
        "handles": [_handle(1), _handle(2)],
    }
    script = Path(__file__).with_name("browser_mesh_isolated.py")
    result = subprocess.run(
        [sys.executable, "-I", str(script)],
        input=json.dumps(bundle),
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(script.parent),
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["agreed"] is True
    assert report["frames"] > 0
    assert report["platform_files"] == []


# -- the public projection -----------------------------------------------------


def test_the_manifest_holds_no_private_or_per_participant_field() -> None:
    """The projection is a whitelist, so a private note never reaches a browser."""
    spec = BrowserMeshSpec(
        channel_key="tandem",
        source_bundle="x = 1",
        action_bindings={"ArrowUp": 1},
        server_notes="the private server note",
    )

    manifest = browser_mesh_manifest(spec)
    text = json.dumps(manifest)

    assert "the private server note" not in text
    assert "server_notes" not in manifest
    for term in ("actor_", "visit_", "room_", "enrollment_", "seed"):
        assert term not in manifest


def test_the_run_configuration_freezes_the_sorted_peer_handles() -> None:
    """The frozen peer set is the room's handles, in one canonical order."""
    manifest = browser_mesh_manifest(tandem_mesh_spec())

    config = mesh_run_config(
        manifest,
        local_peer_handle=_handle(2),
        peer_handles=(_handle(3), _handle(1)),
        room_handle="room_019b6000000000000000000000A",
        negotiation_generation=4,
        seed=11,
    )

    assert config["peer_actor_ids"] == [_handle(1), _handle(2), _handle(3)]
    assert config["local_actor_id"] == _handle(2)
    assert config["negotiation_generation"] == 4
    assert config["input_delay"] == tandem_mesh_spec().input_delay


def test_a_specification_refuses_an_impossible_engine_setting() -> None:
    """The study learns at build time, not in a participant's browser."""
    with pytest.raises(ValueError, match="snapshot interval"):
        BrowserMeshSpec(
            channel_key="x",
            source_bundle="",
            action_bindings={},
            snapshot_interval=0,
        )
    with pytest.raises(ValueError, match="redundancy"):
        BrowserMeshSpec(
            channel_key="x", source_bundle="", action_bindings={}, redundancy=99
        )


# -- what the server checks ----------------------------------------------------


def test_the_trajectory_identity_comes_from_the_frames() -> None:
    """The digest is derived, so a claim beside the payload carries no weight."""
    payload = _payload(count=4)

    verified = verify_mesh_capture(json.dumps(payload))

    assert verified.frame_count == 4
    assert verified.trajectory_digest == trajectory_digest(payload["frames"])


def test_one_changed_reward_changes_the_trajectory_identity() -> None:
    """Every canonical field binds into the digest, not only the state hash."""
    original = _payload(count=3)
    altered = _payload(count=3)
    altered["frames"][1]["rewards"][_handle(1)] = 5.0

    assert verify_mesh_capture(json.dumps(original)) != verify_mesh_capture(
        json.dumps(altered)
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not json at all", "not valid json"),
        (json.dumps([1, 2]), "not an object"),
        (json.dumps(_payload(count=2, version=2)), "another contract"),
        (json.dumps(_payload(count=2, schema="other")), "another contract"),
        (json.dumps(_payload(count=2, frames="all of them")), "names no frames"),
        (json.dumps(_payload(count=2, frames=[1, 2])), "not an object"),
    ],
)
def test_a_payload_that_breaks_the_contract_is_refused(
    payload: str, message: str
) -> None:
    """A malformed capture is refused rather than half-read."""
    with pytest.raises(MeshCaptureError, match=message):
        verify_mesh_capture(payload)


def test_a_payload_whose_frames_skip_a_number_is_refused() -> None:
    """The frames must be one contiguous run from the first frame."""
    payload = _payload(count=3)
    payload["frames"][2]["frame_number"] = 9

    with pytest.raises(MeshCaptureError, match="contiguous run"):
        verify_mesh_capture(json.dumps(payload))


def test_a_frame_with_an_unknown_field_is_refused() -> None:
    """A closed frame shape leaves no room for a field the server ignores."""
    payload = _payload(count=2)
    payload["frames"][0]["extra"] = True

    with pytest.raises(MeshCaptureError, match="missing or unknown fields"):
        verify_mesh_capture(json.dumps(payload))


# -- the records the server writes ---------------------------------------------


def test_the_server_stamps_its_own_identities_on_the_records() -> None:
    """The browser reported handles; the ledger holds actors and an episode."""
    summary = mesh_episode_summary(json.dumps(_payload(count=5)), binding=_binding())

    assert summary.frames == 5
    assert summary.channel_key == "tandem"
    assert summary.seat_key == "seat-1"
    assert summary.boundary.authority == "peer"
    assert summary.boundary.end_frame_exclusive == 5
    assert summary.boundary.p2p_barrier is not None
    assert summary.boundary.p2p_barrier.rule == "minimum-end-frame-exclusive"
    assert summary.boundary.p2p_barrier.frozen_peer_actor_ids == [
        "actor_019b6000-0000-7000-8000-0000000000b1",
        "actor_019b6000-0000-7000-8000-0000000000b2",
    ]
    first = summary.transitions[0]
    assert first.authority == "peer"
    assert first.replica_actor_id == "actor_019b6000-0000-7000-8000-0000000000b1"
    assert first.mesh_membership_digest == _MESH_DIGEST
    assert first.episode_id == "episode_019b6000-0000-7000-8000-0000000000a2"


def test_the_barrier_keeps_the_peers_in_canonical_actor_order() -> None:
    """A handle sorts unlike its actor, so the order is taken after the mapping.

    The browser reports opaque handles whose order is meaningless. The record
    requires canonical actor order, so a boundary built from the handle order
    would be valid only when the two happened to agree -- which is the kind of
    defect that passes most of the time.
    """
    handles = (_handle(1), _handle(2))
    reversed_binding = replace(
        _binding(),
        actor_by_handle={
            handles[0]: "actor_019b6000-0000-7000-8000-0000000000ff",
            handles[1]: "actor_019b6000-0000-7000-8000-000000000011",
        },
    )

    summary = mesh_episode_summary(
        json.dumps(_payload(count=2)), binding=reversed_binding
    )

    barrier = summary.boundary.p2p_barrier
    assert barrier is not None
    named = [entry.peer_actor_id for entry in barrier.peer_end_frames]
    assert named == sorted(named)
    assert barrier.frozen_peer_actor_ids == sorted(named)


def test_a_payload_naming_another_peer_set_is_refused() -> None:
    """A frame may only name the peers the server formed the room from."""
    payload = _payload(count=2)
    payload["frames"][0]["actions"] = {_handle(1): 1, _handle(9): 1}

    with pytest.raises(MeshCaptureError, match="another peer set"):
        mesh_episode_summary(json.dumps(payload), binding=_binding())


def test_a_boundary_that_is_not_the_agreed_minimum_is_refused() -> None:
    """The barrier rule is checked, not taken on trust."""
    payload = _payload(count=3)
    payload["boundary"]["peer_end_frames"][_handle(2)] = 2

    with pytest.raises(MeshCaptureError, match="agreed minimum"):
        mesh_episode_summary(json.dumps(payload), binding=_binding())


def test_a_boundary_that_does_not_close_the_frames_is_refused() -> None:
    """A payload cannot report more frames than its boundary admits."""
    payload = _payload(count=3)
    payload["boundary"]["end_frame_exclusive"] = 2
    payload["boundary"]["peer_end_frames"] = {_handle(1): 2, _handle(2): 2}

    with pytest.raises(MeshCaptureError, match="close the frames"):
        mesh_episode_summary(json.dumps(payload), binding=_binding())


def test_a_boundary_that_contradicts_its_last_frame_is_refused() -> None:
    """A run that never terminated cannot be reported as terminal."""
    payload = _payload(count=3)
    payload["boundary"]["kind"] = "terminal"

    with pytest.raises(MeshCaptureError, match="contradicts its last frame"):
        mesh_episode_summary(json.dumps(payload), binding=_binding())


def test_a_non_integer_action_is_refused() -> None:
    """An action is a discrete integer; a float or a flag is not one."""
    payload = _payload(count=2)
    payload["frames"][0]["actions"][_handle(1)] = True

    with pytest.raises(MeshCaptureError, match="must be an integer"):
        mesh_episode_summary(json.dumps(payload), binding=_binding())
