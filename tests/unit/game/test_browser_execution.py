"""Browser execution: a public manifest, a validated run, a fenced commit.

These tests cover the server side of the browser (Pyodide) mode. The client
manifest is a public projection that never carries private server data. A
client-reported episode must meet the normalized transition contract and claim
browser authority. The commit records the run under browser authority and
installs a producer generation, so a superseded client cannot rewrite it.
"""

from __future__ import annotations

from typing import Any

import pytest

from examples.mountain_car.browser_env import mountain_car_browser_spec
from mug.game.browser import (
    BrowserGameSpec,
    ClientEpisodeError,
    capture_browser_episode,
    client_manifest,
    parse_client_episode,
)
from mug.gateway import Gateway
from mug.kernel import (
    DataHandlingRef,
    Digest,
    PrincipalRef,
    WireCommandEnvelope,
)
from mug.runtime import CommandContext, read_ledger
from mug.storage import InMemoryStore

_PARTICIPANT = PrincipalRef(
    kind="participant", id="participant_019b6000-0000-7000-8000-0000000000aa"
)
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_EPISODE = "episode_019b6000-0000-7000-8000-00000000000e"
_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000000f"
_VISIT = "visit_019b6000-0000-7000-8000-00000000000b"
_CHANNEL = "mountain-car"


def _spec(**changes: Any) -> BrowserGameSpec:
    base = mountain_car_browser_spec()
    from dataclasses import replace

    return replace(base, **changes)


def _transition(frame: int, *, authority: str = "browser") -> dict[str, Any]:
    return {
        "interaction_id": _INTERACTION,
        "channel_key": _CHANNEL,
        "episode_id": _EPISODE,
        "frame_number": frame,
        "action_digest": _A_DIGEST.model_dump(mode="json"),
        "state_digest": _A_DIGEST.model_dump(mode="json"),
        "authority": authority,
        "applied_decisions": [],
        "recorded_at": "2026-07-21T00:00:00.000000Z",
    }


def _boundary(*, authority: str = "browser", frames: int = 3) -> dict[str, Any]:
    return {
        "episode_id": _EPISODE,
        "interaction_id": _INTERACTION,
        "kind": "terminal",
        "end_frame_exclusive": frames,
        "authority": authority,
        "state_hash": _A_DIGEST.model_dump(mode="json"),
    }


def _episode(**overrides: Any) -> dict[str, Any]:
    payload = {
        "transitions": [_transition(1), _transition(2), _transition(3)],
        "boundary": _boundary(),
    }
    payload.update(overrides)
    return payload


def _mint(gateway: Gateway, idem: str) -> CommandContext:
    envelope = {
        "schema": {
            "name": "mug.command-envelope",
            "version": 0,
            "digest": _A_DIGEST.model_dump(mode="json"),
        },
        "protocol_version": "0.1.0",
        "command": {"name": "game.capture", "version": 0},
        "request_id": "request_019b6000-0000-7000-8000-000000000001",
        "idempotency_key": idem,
        "target": {"id": _EPISODE},
        "payload": {
            "schema": {
                "name": "mug.edge.payload",
                "version": 0,
                "digest": _A_DIGEST.model_dump(mode="json"),
            },
            "data": {"episode_id": _EPISODE},
        },
    }
    return gateway.mint(
        WireCommandEnvelope.model_validate(envelope),
        principal=_PARTICIPANT,
        data_handling=_RESEARCH,
    )


def _parse(payload: dict[str, Any]) -> Any:
    return parse_client_episode(
        payload,
        expected_channel_key=_CHANNEL,
        expected_episode_id=_EPISODE,
        seat_key="player",
    )


def test_the_client_manifest_hides_private_server_data() -> None:
    """The manifest ships the public bundle and never the private server field."""
    spec = _spec(server_notes="internal-only manifest data")
    manifest = client_manifest(
        spec, episode_id=_EPISODE, interaction_id=_INTERACTION, seat_key="player"
    )
    assert manifest["mode"] == "browser"
    assert manifest["source_bundle"] == spec.source_bundle
    assert manifest["episode_id"] == _EPISODE
    assert "server_notes" not in manifest
    assert "internal-only manifest data" not in str(manifest)


def test_a_well_formed_browser_episode_parses_to_the_contract() -> None:
    """A browser run validates into the same transition and boundary records."""
    summary = _parse(_episode())
    assert summary.frames == 3
    assert summary.channel_key == _CHANNEL
    assert all(t.authority == "browser" for t in summary.transitions)
    assert summary.boundary.authority == "browser"
    assert summary.solved


def test_a_server_authority_claim_is_refused() -> None:
    """A browser writer must claim browser authority, never server authority."""
    bad = {
        "transitions": [_transition(1, authority="server")],
        "boundary": _boundary(frames=1),
    }
    with pytest.raises(ClientEpisodeError):
        _parse(bad)


def test_a_wrong_episode_id_is_refused() -> None:
    """A transition that names a different episode than the server minted fails."""
    with pytest.raises(ClientEpisodeError):
        parse_client_episode(
            _episode(),
            expected_channel_key=_CHANNEL,
            expected_episode_id="episode_019b6000-0000-7000-8000-000000000099",
            seat_key="player",
        )


def test_a_non_contiguous_run_is_refused() -> None:
    """The frames must be a contiguous run, so a gap is refused."""
    gapped = {
        "transitions": [_transition(1), _transition(3)],
        "boundary": _boundary(frames=3),
    }
    with pytest.raises(ClientEpisodeError):
        _parse(gapped)


async def test_capture_records_the_run_under_browser_authority_and_fences() -> None:
    """The commit lands four events, names browser authority, installs the fence."""
    store = InMemoryStore()
    gateway = Gateway()
    context = _mint(gateway, "idem_" + "b".ljust(21, "0") + "A")
    summary = _parse(_episode())

    receipt = await capture_browser_episode(
        summary,
        visit_id=_VISIT,
        context=context,
        epoch_id=gateway.new_id("prodepoch"),
        generation=5,
        store=store,
    )
    assert receipt.outcome == "accepted"
    assert store.installed_generation(context.stream_id) == 5

    events = read_ledger(store, context.stream_id)
    assert len(events) == 4
    aggregate = store.load_aggregate(_EPISODE)
    assert aggregate is not None
    assert aggregate["authority"] == "browser"


async def test_a_superseded_generation_cannot_rewrite_the_episode() -> None:
    """After a newer client writes the episode, an older one cannot overwrite it."""
    store = InMemoryStore()
    gateway = Gateway()
    summary = _parse(_episode())

    newer = await capture_browser_episode(
        summary,
        visit_id=_VISIT,
        context=_mint(gateway, "idem_" + "new".ljust(21, "0") + "A"),
        epoch_id=gateway.new_id("prodepoch"),
        generation=2,
        store=store,
    )
    older = await capture_browser_episode(
        summary,
        visit_id=_VISIT,
        context=_mint(gateway, "idem_" + "old".ljust(21, "0") + "A"),
        epoch_id=gateway.new_id("prodepoch"),
        generation=1,
        store=store,
    )
    assert newer.outcome == "accepted"
    assert older.outcome == "rejected"
    stream_id = next(iter(newer.stream_positions))
    assert len(read_ledger(store, stream_id)) == 4
