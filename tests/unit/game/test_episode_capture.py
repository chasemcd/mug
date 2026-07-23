"""Canonical capture: a played episode becomes ordered events on its stream.

These tests run the environment-neutral loop over a fake environment, then commit
the run through the real gateway, runtime spine, and in-memory store. The episode
stream must carry one event per transition and then the boundary, in order, each
binding its own record digest. A replay of the same capture is idempotent.
"""

from __future__ import annotations

from typing import Any, cast

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
    compute_digest,
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


def _factory() -> Any:
    return _FakeEnv()


def _render(surface: Surface, state: StepResult) -> None:
    surface.circle(x=0.5, y=0.5, radius=0.02, color="#f00", object_id="dot")


def _now() -> str:
    return "2026-07-21T00:00:00.000000Z"


def _mint(gateway: Gateway, idem: str) -> CommandContext:
    envelope = {
        "schema": {
            "name": "mug.command-envelope",
            "version": 0,
            "digest": _A_DIGEST.model_dump(mode="json"),
        },
        "protocol_version": "0.1.0",
        "command": {"name": "episode.capture", "version": 0},
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


async def _run() -> EpisodeSummary:
    inputs = InputState({"Go": 1}, 0)

    async def sink(_packet: Any) -> None:
        return None

    return await run_episode(
        GymEnv(cast("EnvFactory", _factory)),
        render=_render,
        channel_key="fake-game",
        episode_id=_EPISODE,
        interaction_id=_INTERACTION,
        seat_key="player",
        input_state=inputs,
        sink=sink,
        now=_now,
        fps=0,
        max_steps=10,
    )


async def test_capture_writes_a_transition_per_frame_then_the_boundary() -> None:
    """The episode stream is the ordered lineage: three frames plus a boundary."""
    store = InMemoryStore()
    summary = await _run()
    context = _mint(Gateway(), "idem_" + "cap".ljust(21, "0") + "A")

    receipt = await capture_episode(
        summary, visit_id=_VISIT, context=context, store=store
    )
    assert receipt.outcome == "accepted"

    events = read_ledger(store, context.stream_id)
    assert len(events) == 4
    assert [event.stream_position.sequence for event in events] == [1, 2, 3, 4]
    assert len({event.event_id for event in events}) == 4

    transition_digest = compute_digest(
        summary.transitions[0].model_dump(mode="json", exclude_none=True)
    )
    assert events[0].payload_digest == transition_digest
    boundary_digest = compute_digest(
        summary.boundary.model_dump(mode="json", exclude_none=True)
    )
    assert events[3].payload_digest == boundary_digest


async def test_capture_is_idempotent_on_replay() -> None:
    """The same capture content replays to the same positions, no second effect."""
    store = InMemoryStore()
    summary = await _run()
    gateway = Gateway()

    idem = "idem_" + "r".ljust(21, "0") + "A"
    first = await capture_episode(
        summary, visit_id=_VISIT, context=_mint(gateway, idem), store=store
    )
    second = await capture_episode(
        summary, visit_id=_VISIT, context=_mint(gateway, idem), store=store
    )
    assert first.outcome == "accepted"
    assert second.outcome == "accepted"
    assert first.stream_positions == second.stream_positions
    stream_id = next(iter(first.stream_positions))
    assert len(read_ledger(store, stream_id)) == 4
