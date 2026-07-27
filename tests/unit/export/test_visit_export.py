"""The visit export: the full single-participant slice runs and exports.

This drives the real flow and capture services over a shared store, then exports
the visit. The export is one JSONL document that carries the flow stream (the
form advances) and the episode stream (a transition per frame and the boundary),
in order. The HTTP export endpoint serves the same document for a known flow.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

import httpx
from fastapi.testclient import TestClient

from mug.app import build_demo_app
from mug.content import (
    AdvanceFlowCommand,
    MaterializeFlowCommand,
    advance_flow,
    demo_study,
    materialize_flow,
)
from mug.export import export_visit
from mug.game.capture import capture_episode
from mug.game.env import EnvFactory, GymEnv, StepResult
from mug.game.runtime import EpisodeSummary, InputState, run_episode
from mug.game.surface import Surface
from mug.gateway import Gateway
from mug.kernel import (
    DataHandlingRef,
    Digest,
    PrincipalRef,
    WireCommandEnvelope,
)
from mug.kernel.refs import StudyVersionRef
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_PARTICIPANT = PrincipalRef(
    kind="participant", id="participant_019b6000-0000-7000-8000-0000000000aa"
)
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_FLOW_ID = "visitplan_019b6000-0000-7000-8000-00000000000a"
_VISIT_ID = "visit_019b6000-0000-7000-8000-00000000000b"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000000e"


def _mint(
    gateway: Gateway, name: str, target: str, data: dict[str, Any], idem: str
) -> CommandContext:
    envelope = {
        "schema": {
            "name": "mug.command-envelope",
            "version": 0,
            "digest": _A_DIGEST.model_dump(mode="json"),
        },
        "protocol_version": "0.1.0",
        "command": {"name": name, "version": 0},
        "request_id": "request_019b6000-0000-7000-8000-000000000001",
        "idempotency_key": idem,
        "target": {"id": target},
        "payload": {
            "schema": {
                "name": "mug.edge.payload",
                "version": 0,
                "digest": _A_DIGEST.model_dump(mode="json"),
            },
            "data": data,
        },
    }
    return gateway.mint(
        WireCommandEnvelope.model_validate(envelope),
        principal=_PARTICIPANT,
        data_handling=_RESEARCH,
    )


def _idem(tag: str) -> str:
    return "idem_" + tag.ljust(21, "0") + "A"


class _FakeEnv:
    def __init__(self) -> None:
        self._t = 0

    def reset(self, *, seed: int | None = None) -> tuple[list[float], dict[str, Any]]:
        self._t = 0
        return [0.0], {}

    def step(
        self, action: int
    ) -> tuple[list[float], float, bool, bool, dict[str, Any]]:
        self._t += 1
        return [float(self._t)], -1.0, self._t >= 3, False, {}


def _render(surface: Surface, state: StepResult) -> None:
    surface.circle(x=0.5, y=0.5, radius=0.02, color="#f00", object_id="dot")


async def _play() -> EpisodeSummary:
    async def sink(_packet: Any) -> None:
        return None

    return await run_episode(
        GymEnv(cast("EnvFactory", lambda: _FakeEnv())),
        render=_render,
        channel_key="fake-game",
        episode_id=_EPISODE,
        interaction_id="interaction_019b6000-0000-7000-8000-00000000000f",
        seat_key="player",
        input_state=InputState({"Go": 1}, 0),
        sink=sink,
        now=lambda: "2026-07-21T00:00:00.000000Z",
        fps=0,
        max_steps=10,
    )


async def _advance(
    gateway: Gateway,
    store: InMemoryStore,
    revision: int,
    answers: dict[str, Any],
    idem: str,
    captured: list[str] | None = None,
) -> None:
    streams = captured or []
    context = _mint(
        gateway,
        "flow.advance",
        _FLOW_ID,
        {
            "answers": answers,
            "expected_revision": revision,
            "captured_streams": streams,
        },
        idem,
    )
    await advance_flow(
        AdvanceFlowCommand(
            answers=answers, expected_revision=revision, captured_streams=streams
        ),
        study=demo_study(),
        context=context,
        store=store,
    )


async def _run_full_visit(store: InMemoryStore) -> None:
    """Materialize, answer the forms, capture the episode, and complete."""
    gateway = Gateway()
    await materialize_flow(
        MaterializeFlowCommand(visit_id=_VISIT_ID),
        study=demo_study(),
        context=_mint(
            gateway, "flow.materialize", _FLOW_ID, {"visit_id": _VISIT_ID}, _idem("m")
        ),
        store=store,
        **_plan_args(gateway),  # pyright: ignore[reportArgumentType]
    )
    await _advance(gateway, store, 1, {"agree": "yes"}, _idem("c"))
    await _advance(gateway, store, 2, {"mood": 4}, _idem("s"))

    summary = await _play()
    capture_context = _mint(
        gateway, "episode.capture", _EPISODE, {"episode_id": _EPISODE}, _idem("e")
    )
    await capture_episode(
        summary, visit_id=_VISIT_ID, context=capture_context, store=store
    )
    await _advance(gateway, store, 3, {}, _idem("g"), [capture_context.stream_id])
    await _advance(gateway, store, 4, {}, _idem("d"))


async def test_the_export_carries_the_flow_and_episode_streams_in_order() -> None:
    """The visit exports five flow events and four episode events as JSONL."""
    store = InMemoryStore()
    await _run_full_visit(store)

    export = export_visit(store, _FLOW_ID)
    assert export.visit_id == _VISIT_ID
    assert len(export.stream_ids) == 2

    lines = export.jsonl.splitlines()
    assert len(lines) == 9
    assert export.event_count == 9

    records = [json.loads(line) for line in lines]
    assert all("stream_position" in record for record in records)
    assert all("payload_digest" in record for record in records)
    # The first stream is the flow (five advances), then the episode (four events).
    flow_stream = export.stream_ids[0]
    flow_events = [
        r for r in records if r["stream_position"]["stream_id"] == flow_stream
    ]
    assert len(flow_events) == 5


async def test_the_export_endpoint_serves_the_visit_jsonl() -> None:
    """A researcher downloads the visit lineage over HTTP as ndjson."""
    store = InMemoryStore()
    await _run_full_visit(store)

    # starlette's TestClient is an httpx.Client; the base type is fully typed.
    def _http() -> httpx.Client:
        return TestClient(build_demo_app(store=store, gateway=Gateway()))

    client = _http()
    response = client.get(f"/export/{_FLOW_ID}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert len(response.text.splitlines()) == 9

    missing = client.get("/export/visitplan_019b6000-0000-7000-8000-000000000999")
    assert missing.status_code == 404


def _seeding(gateway: Gateway) -> Callable[[str], bytes]:
    """The seed source a plan draws its orders from."""
    return lambda role: gateway.derived_seed("treatment", role)


def _plan_args(gateway: Gateway) -> dict[str, object]:
    """The identity and seed a plan is drafted with, for a study with no design."""
    return {
        "study_version": StudyVersionRef(
            study_id=gateway.derived_id("study", "test"),
            study_version_id=gateway.derived_id("studyver", "test"),
            version_number=1,
            manifest_digest=Digest(algorithm="sha-256", hex="0" * 64),
        ),
        "derive": gateway.derived_id,
        "seed": _seeding(gateway),
    }
