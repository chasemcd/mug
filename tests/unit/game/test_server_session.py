"""The server-authoritative session seats a bot beside a human on one timeline.

These tests drive ``mug.game.server_session.ServerSeatSession`` with a fake
multi-seat environment, a scripted bot controller, and a scripted human input, with
no socket and no clock. They prove the session owns the server-authoritative
counterpart of the mesh session:

- a bot controller and a human input share one authoritative environment; the
  server steps every seat once per frame, records one shared transition per frame,
  and reports one ``EpisodeSummary`` per seat over that timeline;
- the channel declares the ``ExecutionMode.server`` contract (single writer, no
  per-replica rollback), so a server-authoritative interaction is distinct from a
  peer-to-peer mesh;
- the bot seat is genuinely server-sourced: its controller decides once per frame.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from mug.game.multiseat import MultiStepResult
from mug.game.server_session import ServerSeat, ServerSeatSession, server_execution_mode

_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000010f"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000010e"
_RECORDED_AT = "2026-07-21T00:00:00.000000Z"


def _now() -> str:
    """Return the fixed recorded-at instant, the session's injected clock."""
    return _RECORDED_AT


class FakeMultiSeatEnv:
    """A deterministic two-agent environment that truncates at a horizon."""

    def __init__(self, *, agent_ids: tuple[str, ...], horizon: int) -> None:
        self._agent_ids = agent_ids
        self._horizon = horizon
        self._t = 0
        self._pos: dict[str, int] = {}

    def reset(self) -> MultiStepResult:
        self._t = 0
        self._pos = dict.fromkeys(self._agent_ids, 0)
        return MultiStepResult(
            observations=dict(self._pos),
            rewards=dict.fromkeys(self._agent_ids, 0.0),
            terminated=False,
            truncated=False,
        )

    def step(self, actions: Mapping[str, int]) -> MultiStepResult:
        self._t += 1
        for agent in self._agent_ids:
            self._pos[agent] += int(actions.get(agent, 0)) - 1
        truncated = self._t >= self._horizon
        return MultiStepResult(
            observations=dict(self._pos),
            rewards=dict.fromkeys(self._agent_ids, -1.0),
            terminated=False,
            truncated=truncated,
        )


class ScriptedSource:
    """A seat source that returns a scripted action and counts its decisions."""

    def __init__(self, action: int) -> None:
        self._action = action
        self.calls = 0

    def decide(self, observation: Any) -> int:
        self.calls += 1
        return self._action


def _session(
    *, horizon: int, bot: ScriptedSource, human: ScriptedSource
) -> ServerSeatSession:
    """Build a two-seat server session: a bot seat beside a human seat."""
    env = FakeMultiSeatEnv(agent_ids=("player_0", "player_1"), horizon=horizon)
    seats = [
        ServerSeat(
            seat_key="seat-1",
            actor_id="actor_019b6000-0000-7000-8000-000000000101",
            agent_id="player_0",
            source=human,
            kind="human",
        ),
        ServerSeat(
            seat_key="seat-2",
            actor_id="actor_019b6000-0000-7000-8000-000000000102",
            agent_id="player_1",
            source=bot,
            kind="bot",
        ),
    ]
    return ServerSeatSession(
        seats=seats,
        env=env,
        channel_key="server-game",
        interaction_id=_INTERACTION,
        episode_id=_EPISODE,
        now=_now,
        fps=0,
        max_steps=horizon + 20,
    )


@pytest.mark.asyncio
async def test_a_bot_seats_beside_a_human_on_one_authoritative_timeline() -> None:
    """One shared timeline: one transition per frame, one summary per seat."""
    bot, human = ScriptedSource(2), ScriptedSource(0)
    session = _session(horizon=15, bot=bot, human=human)

    episode = await session.run()

    assert episode.frames == 15
    assert set(episode.summaries) == {
        "actor_019b6000-0000-7000-8000-000000000101",
        "actor_019b6000-0000-7000-8000-000000000102",
    }
    # Both seats share the one authoritative timeline.
    reference = episode.reference_summary()
    assert len(reference.transitions) == 15
    for summary in episode.summaries.values():
        assert summary.transitions == reference.transitions
        assert summary.boundary == reference.boundary
    # The bot is genuinely server-sourced: it decides once per frame.
    assert bot.calls == 15
    assert human.calls == 15


@pytest.mark.asyncio
async def test_the_channel_declares_the_server_execution_mode() -> None:
    """The session runs under the single-writer server contract, not a mesh."""
    bot, human = ScriptedSource(1), ScriptedSource(1)
    session = _session(horizon=5, bot=bot, human=human)

    mode = session.execution_mode()

    assert mode.mode == "server"
    assert mode.writer == "single"
    assert mode.p2p_contract is None


def test_the_free_function_builds_the_server_mode() -> None:
    """The standalone factory yields the same single-writer server contract."""
    mode = server_execution_mode(snapshot_contract="none")
    assert mode.mode == "server"
    assert mode.writer == "single"
    assert mode.snapshot_contract == "none"


def test_distinct_seats_are_required() -> None:
    """Two seats may not share an actor id or an environment agent."""
    env = FakeMultiSeatEnv(agent_ids=("player_0", "player_1"), horizon=5)
    clash = [
        ServerSeat("seat-1", "actor_1", "player_0", ScriptedSource(0)),
        ServerSeat("seat-2", "actor_1", "player_1", ScriptedSource(0)),
    ]
    with pytest.raises(ValueError, match="distinct actor id"):
        ServerSeatSession(
            seats=clash,
            env=env,
            channel_key="server-game",
            interaction_id=_INTERACTION,
            episode_id=_EPISODE,
            now=_now,
        )
