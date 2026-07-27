"""The server-authoritative stepping loop for a turn-based (AEC) environment.

The multi-seat loop (``mug.game.multiseat``) steps a *simultaneous-move*
environment: every seat acts each frame and one step resolves them together. A
turn-based game is the other discipline: the seats act one at a time, in a cycle,
and a seat sees the moves made before its own. PettingZoo calls this the
agent-environment-cycle (AEC) API. This module adapts that shape onto a small
turn-based seam and drives it with a loop the same seat sources feed -- a person's
``InputState``, a local controller, or an LLM seat's scheduled action.

Two things differ from the simultaneous loop, and both follow from the discipline:

- one seat acts per frame (the one whose turn it is), so a frame records that one
  seat's move, not a whole action set;
- the loop *waits* for the active seat before it steps. In a real-time game a slow
  model must never block the frame, so its seat holds a stale action; in a
  turn-based game the game genuinely waits for the player in turn, so the loop
  gives the active seat a chance to decide (the ``on_turn`` hook) before it reads
  the seat and steps. A single-seat turn-based game is the one-agent case of the
  same loop.

The ``AecEnv`` adapter duck-types the AEC API, so PettingZoo is never imported. It
wraps a *live* environment instance (not a factory), so the same instance an LLM
controller reads for its prompt is the instance the loop steps -- the model always
sees the live state the loop just produced. The adapter hides the AEC lifecycle
detail: it lands on the next live agent each turn, and it clears a finished agent
with the ``step(None)`` the AEC contract requires, so the loop only ever sees a
live seat's turn.

The AEC API this adapter consumes (it duck-types the object):

- ``reset(seed=...)`` -- start a new episode;
- ``agent_selection`` -- the agent whose turn it is now;
- ``agents`` -- the currently active agents, which shrink as agents finish;
- ``observe(agent)`` -- one agent's observation;
- ``step(action)`` -- apply the current agent's action and advance the selection;
  a finished agent takes ``step(None)``;
- ``rewards`` / ``terminations`` / ``truncations`` -- mappings keyed by agent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, NamedTuple, Protocol, cast

import numpy as np

from mug.game.seams import Clock, SeatActionSource
from mug.game.trajectory import TrajectoryFrame
from mug.game.types import EpisodeBoundary, GameTransition
from mug.kernel import compute_digest


def _jsonable(value: Any) -> Any:
    """Normalize an observation to json-able data (arrays and scalars included)."""
    if isinstance(value, np.ndarray):
        return cast("list[Any]", value.tolist())
    if isinstance(value, np.generic):
        return cast("Any", value.item())
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in cast("dict[Any, Any]", value).items()
        }
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in cast("list[Any]", value)]
    return value


class TurnState(NamedTuple):
    """The state at one point in a turn-based episode: whose turn, and the game.

    ``agent`` is the seat that acts next, or ``""`` when the episode is over.
    ``observation`` is that seat's raw observation, which its source reads to
    decide. ``observations`` is every active seat's json-able observation, for the
    recorded state hash. ``rewards`` is the reward each seat received on the step
    that reached this state. ``done`` is set when the whole episode has ended, and
    ``solved`` is set when it ended by a termination rather than a truncation.
    """

    agent: str
    observation: Any
    observations: dict[str, Any]
    rewards: dict[str, float]
    done: bool
    solved: bool


class TurnBasedEnv(Protocol):
    """The minimal turn-based environment the loop steps: reset and step one turn.

    ``reset`` starts the episode and returns the first live seat's turn; ``step``
    applies the active seat's action and returns the next live seat's turn (or a
    ``done`` state). ``AecEnv`` adapts a PettingZoo AEC environment to this seam.
    """

    def reset(self) -> TurnState: ...
    def step(self, action: int) -> TurnState: ...


class TurnStepInfo(NamedTuple):
    """One stepped turn handed to an ``on_step`` observer: frame, mover, result.

    ``agent`` is the seat that acted this turn and ``action`` its move; ``state``
    is the turn-state the move produced. A turn-based LLM runtime uses it to record
    the move into every seat's history, so each seat reads what the others played.
    """

    frame: int
    agent: str
    action: int
    state: TurnState


# The optional hooks the loop awaits. ``on_start`` runs once after the reset;
# ``on_turn`` runs before the active seat is read, so a runtime can let that seat
# decide (an LLM seat awaits its model here); ``on_step`` runs after each turn.
TurnBasedStart = Callable[[TurnState], Awaitable[None]]
TurnBasedTurn = Callable[[TurnState], Awaitable[None]]
TurnBasedObserver = Callable[[TurnStepInfo], Awaitable[None]]


class TurnBasedSummary(NamedTuple):
    """The result of one turn-based episode: the recorded turns and the outcome.

    Like the multi-seat summary, one turn-based episode holds many seats on one
    timeline, so the summary names every seat and carries the one transition per
    turn and the closing boundary.

    ``trajectory`` is what happened on each turn behind those digests: who moved,
    what they played, the resulting observations, and the rewards the move earned.
    """

    channel_key: str
    seat_keys: tuple[str, ...]
    frames: int
    transitions: list[GameTransition]
    boundary: EpisodeBoundary
    solved: bool
    trajectory: Sequence[TrajectoryFrame] = ()


class AecEnv:
    """Adapt a live PettingZoo AEC environment to the turn-based seam.

    The adapter wraps the environment instance, so the same object an LLM
    controller reads is the object the loop steps. Each turn it lands on the next
    live agent, clearing any finished agent with the ``step(None)`` the AEC
    contract requires, so the loop only ever reads a live seat.

    The reward it reports for a turn accumulates the environment's per-agent
    rewards over the acted step and any ``step(None)`` calls it made to clear
    finished agents, so a seat that finished on this turn is still credited.
    """

    _REQUIRED = ("reset", "step", "observe")

    def __init__(self, env: Any, *, seed: int = 0) -> None:
        for method in self._REQUIRED:
            if not callable(getattr(env, method, None)):
                raise TypeError(f"a turn-based environment must expose {method}()")
        self._env = env
        self._seed = seed
        self._agent_ids: tuple[str, ...] = ()
        self._terminated_any = False

    def reset(self) -> TurnState:
        """Reset the environment and land on the first live seat's turn."""
        self._env.reset(seed=self._seed)
        self._agent_ids = tuple(str(agent) for agent in self._env.agents)
        self._terminated_any = False
        return self._land({agent: 0.0 for agent in self._agent_ids})

    def step(self, action: int) -> TurnState:
        """Apply the active seat's action, then land on the next live seat's turn."""
        self._env.step(int(action))
        return self._land(self._rewards())

    # -- internals --------------------------------------------------------------

    def _land(self, accrued: dict[str, float]) -> TurnState:
        """Clear finished agents, then return the next live seat's turn state."""
        # A finished agent still appears once for a ``step(None)`` in the AEC
        # contract; drain those so the loop only reads a live seat. The guard
        # bounds the drain, so a misbehaving env cannot spin forever.
        guard = len(self._agent_ids) + 1
        while self._env.agents and self._is_dead(self._env.agent_selection):
            if self._terminations().get(str(self._env.agent_selection)):
                self._terminated_any = True
            self._env.step(None)
            self._absorb(accrued, self._rewards())
            guard -= 1
            if guard < 0:  # pragma: no cover - a guard against a broken env
                break
        if not self._env.agents:
            return TurnState("", None, {}, accrued, done=True, solved=self._solved())
        agent = str(self._env.agent_selection)
        return TurnState(
            agent=agent,
            observation=self._env.observe(agent),
            observations=self._all_observations(),
            rewards=accrued,
            done=False,
            solved=False,
        )

    def _is_dead(self, agent: object) -> bool:
        """Return whether the agent has terminated or truncated (needs clearing)."""
        key = str(agent)
        return bool(self._terminations().get(key)) or bool(self._truncations().get(key))

    def _solved(self) -> bool:
        """Return whether the ended episode closed by a termination, not a cap."""
        if self._terminated_any:
            return True
        return any(bool(value) for value in self._terminations().values())

    def _all_observations(self) -> dict[str, Any]:
        """Return every live agent's json-able observation, for the state hash."""
        return {
            str(agent): _jsonable(self._env.observe(str(agent)))
            for agent in self._env.agents
        }

    def _rewards(self) -> dict[str, float]:
        """Return the environment's per-agent rewards from the most recent step."""
        rewards = cast("Mapping[str, Any]", getattr(self._env, "rewards", {}))
        return {str(agent): float(value) for agent, value in rewards.items()}

    def _terminations(self) -> Mapping[str, Any]:
        return cast("Mapping[str, Any]", getattr(self._env, "terminations", {}))

    def _truncations(self) -> Mapping[str, Any]:
        return cast("Mapping[str, Any]", getattr(self._env, "truncations", {}))

    @staticmethod
    def _absorb(accrued: dict[str, float], step_rewards: Mapping[str, float]) -> None:
        """Add one step's rewards into the running per-agent accumulator."""
        for agent, value in step_rewards.items():
            accrued[agent] = accrued.get(agent, 0.0) + float(value)


def _transition(
    agent: str,
    action: int,
    state: TurnState,
    *,
    episode_id: str,
    interaction_id: str,
    channel_key: str,
    frame: int,
    now: Clock,
) -> GameTransition:
    """Build the server transition for one turn: the one mover's action and state.

    The action digest commits to the acting seat and its move, so a replay knows
    whose turn it was, and the state digest commits to the whole per-seat
    observation set after the move. ``applied_decisions`` stays empty, as the other
    loops do: a seat's decision is recorded on its own decision stream.
    """
    return GameTransition(
        interaction_id=interaction_id,
        channel_key=channel_key,
        episode_id=episode_id,
        frame_number=frame,
        action_digest=compute_digest({agent: int(action)}),
        state_digest=compute_digest(state.observations),
        authority="server",
        applied_decisions=[],
        recorded_at=now(),
    )


def _boundary(
    state: TurnState, *, episode_id: str, interaction_id: str, frame: int
) -> EpisodeBoundary:
    """Close the turn-based episode on the final per-seat observation set."""
    return EpisodeBoundary(
        episode_id=episode_id,
        interaction_id=interaction_id,
        kind="terminal",
        end_frame_exclusive=frame,
        authority="server",
        state_hash=compute_digest(state.observations),
    )


async def run_turnbased_episode(
    env: TurnBasedEnv,
    *,
    channel_key: str,
    episode_id: str,
    interaction_id: str,
    agent_ids: Sequence[str],
    sources: Mapping[str, SeatActionSource],
    now: Clock,
    fps: int = 0,
    max_steps: int = 200,
    on_start: TurnBasedStart | None = None,
    on_turn: TurnBasedTurn | None = None,
    on_step: TurnBasedObserver | None = None,
) -> TurnBasedSummary:
    """Run one turn-based episode: each turn, the active seat moves once.

    Each turn the loop reads whose turn it is, lets that seat decide (the
    ``on_turn`` hook, which an LLM runtime awaits its model in), reads the seat's
    action through the shared ``SeatActionSource`` seam, steps the one move, and
    records one ``GameTransition``. It ends when the episode is over or on the step
    cap, and closes with an ``EpisodeBoundary``. The server owns the authority: a
    seat supplies an action, never a state.

    The optional ``on_start`` observer runs once, after the reset and before the
    first turn; a render facade uses it to draw the opening frame. Unlike the
    simultaneous loop, the loop waits at ``on_turn`` for the active seat, because a
    turn-based game genuinely waits for the player in turn.
    """
    state = env.reset()
    if on_start is not None:
        await on_start(state)
    transitions: list[GameTransition] = []
    trajectory: list[TrajectoryFrame] = []
    frame = 0
    solved = False
    while frame < max_steps and not state.done:
        agent = state.agent
        if on_turn is not None:
            await on_turn(state)
        action = int(sources[agent].decide(state.observation))
        state = env.step(action)
        frame += 1
        transitions.append(
            _transition(
                agent,
                action,
                state,
                episode_id=episode_id,
                interaction_id=interaction_id,
                channel_key=channel_key,
                frame=frame,
                now=now,
            )
        )
        # One turn is one frame, and only the seat in turn acted, so the recorded
        # values are keyed by that seat exactly as the digests were taken.
        trajectory.append(
            TrajectoryFrame(
                frame_number=frame,
                actions={agent: int(action)},
                observations=dict(state.observations),
                rewards=dict(state.rewards),
                terminated=state.done and state.solved,
                truncated=state.done and not state.solved,
                info={},
            )
        )
        if on_step is not None:
            await on_step(TurnStepInfo(frame, agent, action, state))
        if state.done:
            solved = state.solved
            break
        if fps > 0:
            await asyncio.sleep(1 / fps)

    boundary = _boundary(
        state, episode_id=episode_id, interaction_id=interaction_id, frame=frame
    )
    return TurnBasedSummary(
        channel_key, tuple(agent_ids), frame, transitions, boundary, solved, trajectory
    )


__all__ = [
    "AecEnv",
    "TurnBasedEnv",
    "TurnBasedObserver",
    "TurnBasedStart",
    "TurnBasedSummary",
    "TurnBasedTurn",
    "TurnState",
    "TurnStepInfo",
    "run_turnbased_episode",
]
