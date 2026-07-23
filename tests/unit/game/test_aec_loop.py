"""The turn-based loop steps one seat per turn on one shared timeline.

These tests drive ``mug.game.aec.run_turnbased_episode`` over the ``AecEnv``
adapter with scripted seat sources, no socket and no real clock. They use tiny
fake environments that duck-type the PettingZoo AEC API (PettingZoo is not a
dependency), so the tests prove the adapter and the loop honor the turn-based
discipline: one seat acts per turn, the loop waits for the active seat, a finished
seat is cleared with the ``step(None)`` the AEC contract requires, and a
single-seat game is the one-agent case of the same loop.
"""

from __future__ import annotations

from mug.game.aec import (
    AecEnv,
    TurnState,
    run_turnbased_episode,
)


class _PingPongAec:
    """A two-seat AEC game: the seats alternate, and both finish at ``turns``.

    It duck-types the AEC API: ``agent_selection`` names whose turn it is,
    ``agents`` shrinks as seats finish, and a finished seat takes a ``step(None)``
    that removes it. It records the real moves, so a test reads the turn order.
    """

    def __init__(self, *, turns: int) -> None:
        self._turns = turns
        self._order = ("a", "b")
        self.agents: list[str] = []
        self.agent_selection = "a"
        self.rewards: dict[str, float] = {}
        self.terminations: dict[str, bool] = {}
        self.truncations: dict[str, bool] = {}
        self.moves: list[tuple[str, int]] = []
        self._count = 0

    def reset(self, *, seed: int | None = None) -> None:
        self.agents = list(self._order)
        self.agent_selection = "a"
        self._count = 0
        self.rewards = {a: 0.0 for a in self._order}
        self.terminations = {a: False for a in self._order}
        self.truncations = {a: False for a in self._order}
        self.moves = []

    def observe(self, agent: str) -> list[float]:
        return [float(self._count)]

    def step(self, action: int | None) -> None:
        agent = self.agent_selection
        if self.terminations[agent] or self.truncations[agent]:
            self._clear_dead()
            return
        self.moves.append((agent, int(action or 0)))
        self._count += 1
        self.rewards = {a: 0.0 for a in self._order}
        self.rewards[agent] = 1.0
        if self._count >= self._turns:
            self.terminations = {a: True for a in self.agents}
        self._advance()

    def _advance(self) -> None:
        index = self._order.index(self.agent_selection)
        self.agent_selection = self._order[(index + 1) % len(self._order)]

    def _clear_dead(self) -> None:
        self.rewards = {a: 0.0 for a in self._order}
        dead = self.agent_selection
        self.agents = [a for a in self.agents if a != dead]
        live = [a for a in self._order if a in self.agents]
        if live:
            self.agent_selection = live[0]


class _SoloAec:
    """A one-seat AEC game: the sole seat moves until it terminates at ``turns``."""

    def __init__(self, *, turns: int) -> None:
        self._turns = turns
        self.agents: list[str] = []
        self.agent_selection = "only"
        self.rewards: dict[str, float] = {}
        self.terminations: dict[str, bool] = {}
        self.truncations: dict[str, bool] = {}
        self.actions: list[int] = []
        self._count = 0

    def reset(self, *, seed: int | None = None) -> None:
        self.agents = ["only"]
        self.agent_selection = "only"
        self._count = 0
        self.rewards = {"only": 0.0}
        self.terminations = {"only": False}
        self.truncations = {"only": False}
        self.actions = []

    def observe(self, agent: str) -> list[float]:
        return [float(self._count)]

    def step(self, action: int | None) -> None:
        if self.terminations["only"] or self.truncations["only"]:
            self.agents = []
            return
        self.actions.append(int(action or 0))
        self._count += 1
        self.rewards = {"only": 1.0}
        if self._count >= self._turns:
            self.terminations = {"only": True}


class _DropoutAec:
    """A three-seat AEC game where ``b`` finishes early and ``a``/``c`` play on.

    It proves the loop skips a seat that has left: once ``b`` terminates, the loop
    only ever reads ``a`` and ``c`` on their turns, and the episode ends on the
    step cap the caller sets, not on ``b``'s exit.
    """

    def __init__(self, *, b_leaves_after: int) -> None:
        self._order = ("a", "b", "c")
        self._b_leaves_after = b_leaves_after
        self.agents: list[str] = []
        self.agent_selection = "a"
        self.rewards: dict[str, float] = {}
        self.terminations: dict[str, bool] = {}
        self.truncations: dict[str, bool] = {}
        self.moves: list[tuple[str, int]] = []
        self._b_moves = 0

    def reset(self, *, seed: int | None = None) -> None:
        self.agents = list(self._order)
        self.agent_selection = "a"
        self.rewards = {a: 0.0 for a in self._order}
        self.terminations = {a: False for a in self._order}
        self.truncations = {a: False for a in self._order}
        self.moves = []
        self._b_moves = 0

    def observe(self, agent: str) -> list[float]:
        return [float(len(self.moves))]

    def step(self, action: int | None) -> None:
        agent = self.agent_selection
        if self.terminations[agent] or self.truncations[agent]:
            self.agents = [a for a in self.agents if a != agent]
            live = [a for a in self._order if a in self.agents]
            if live:
                self.agent_selection = live[0]
            return
        self.moves.append((agent, int(action or 0)))
        self.rewards = {a: 0.0 for a in self._order}
        self.rewards[agent] = 1.0
        if agent == "b":
            self._b_moves += 1
            if self._b_moves >= self._b_leaves_after:
                self.terminations["b"] = True
        self._advance()

    def _advance(self) -> None:
        live = [a for a in self._order if a in self.agents]
        index = live.index(self.agent_selection)
        self.agent_selection = live[(index + 1) % len(live)]


class _Fixed:
    """A seat source that always supplies one action, ignoring the observation."""

    def __init__(self, action: int) -> None:
        self._action = action

    def decide(self, observation: object) -> int:
        return self._action


def _now() -> str:
    return "2026-07-22T00:00:00.000000Z"


async def test_the_seats_alternate_one_move_per_turn() -> None:
    """Each turn steps exactly the active seat, in the environment's turn order."""
    game = _PingPongAec(turns=4)
    turns: list[str] = []

    async def on_turn(state: TurnState) -> None:
        turns.append(state.agent)

    summary = await run_turnbased_episode(
        AecEnv(game),
        channel_key="ttt",
        episode_id="episode_019b6000-0000-7000-8000-000000000001",
        interaction_id="interaction_019b6000-0000-7000-8000-000000000002",
        agent_ids=["a", "b"],
        sources={"a": _Fixed(1), "b": _Fixed(2)},
        now=_now,
        on_turn=on_turn,
    )

    # One transition per turn; the seats alternated a, b, a, b.
    assert summary.frames == 4
    assert summary.solved is True
    assert summary.seat_keys == ("a", "b")
    assert len(summary.transitions) == 4
    assert turns == ["a", "b", "a", "b"]
    assert game.moves == [("a", 1), ("b", 2), ("a", 1), ("b", 2)]


async def test_a_turn_records_only_the_mover_s_action() -> None:
    """The turn's action digest commits to the one seat that moved, not a set."""
    from mug.kernel import compute_digest

    game = _PingPongAec(turns=2)
    summary = await run_turnbased_episode(
        AecEnv(game),
        channel_key="ttt",
        episode_id="episode_019b6000-0000-7000-8000-000000000003",
        interaction_id="interaction_019b6000-0000-7000-8000-000000000004",
        agent_ids=["a", "b"],
        sources={"a": _Fixed(7), "b": _Fixed(9)},
        now=_now,
    )

    assert summary.transitions[0].action_digest == compute_digest({"a": 7})
    assert summary.transitions[1].action_digest == compute_digest({"b": 9})


async def test_a_single_seat_game_is_the_one_agent_case() -> None:
    """A one-seat AEC game runs on the same turn-based loop."""
    game = _SoloAec(turns=3)
    summary = await run_turnbased_episode(
        AecEnv(game),
        channel_key="solo",
        episode_id="episode_019b6000-0000-7000-8000-000000000005",
        interaction_id="interaction_019b6000-0000-7000-8000-000000000006",
        agent_ids=["only"],
        sources={"only": _Fixed(1)},
        now=_now,
    )

    assert game.actions == [1, 1, 1]
    assert summary.frames == 3
    assert summary.solved is True


async def test_a_finished_seat_is_skipped_and_the_rest_play_on() -> None:
    """Once a seat leaves, the loop only reads the seats still in the game."""
    game = _DropoutAec(b_leaves_after=1)
    seen: list[str] = []

    async def on_turn(state: TurnState) -> None:
        seen.append(state.agent)

    summary = await run_turnbased_episode(
        AecEnv(game),
        channel_key="drop",
        episode_id="episode_019b6000-0000-7000-8000-000000000007",
        interaction_id="interaction_019b6000-0000-7000-8000-000000000008",
        agent_ids=["a", "b", "c"],
        sources={"a": _Fixed(0), "b": _Fixed(0), "c": _Fixed(0)},
        now=_now,
        on_turn=on_turn,
        max_steps=7,
    )

    # b moves once, then leaves; every later turn is a or c, never b.
    assert seen[:3] == ["a", "b", "c"]
    assert "b" not in seen[3:]
    assert summary.frames == 7
    assert summary.solved is False


async def test_the_step_cap_truncates_a_game_that_never_ends() -> None:
    """The step cap closes a turn-based game whose env never terminates."""
    game = _PingPongAec(turns=999)
    summary = await run_turnbased_episode(
        AecEnv(game),
        channel_key="ttt",
        episode_id="episode_019b6000-0000-7000-8000-000000000009",
        interaction_id="interaction_019b6000-0000-7000-8000-00000000000a",
        agent_ids=["a", "b"],
        sources={"a": _Fixed(0), "b": _Fixed(0)},
        now=_now,
        max_steps=5,
    )

    assert summary.frames == 5
    assert summary.solved is False
