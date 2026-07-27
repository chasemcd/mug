"""Adapt a PettingZoo environment to the P2P replica seam (API-07).

The peer-to-peer rollback engine (``mug.game.mesh``) steps a deterministic replica
behind three callables: step one action set, snapshot the whole replica, and
restore it. This module builds those callables from a PettingZoo environment, the
shape the multi-agent CoGrid Overcooked suite exposes. It never names an
environment; the study supplies the factory, and the adapter maps the PettingZoo
API onto the seam.

``MultiAgentReplica`` consumes the *parallel* API, where every agent acts each
frame, so it fits a real-time game such as Overcooked. ``AecReplica`` consumes the
*agent-environment-cycle* (turn-based) API, where one agent acts per turn; it maps
one mesh frame onto one turn of the selected agent, so a turn-based multi-agent env
runs over the same rollback engine. Both duck-type the environment, so PettingZoo
is never an import dependency.

The parallel API this adapter consumes (it duck-types the object, so PettingZoo is
not an import dependency):

- ``reset(seed=...) -> (observations, infos)``, each a mapping keyed by agent id;
- ``step(actions) -> (observations, rewards, terminations, truncations, infos)``,
  each a mapping keyed by agent id, with ``actions`` a mapping the same way;
- ``agents`` -- the currently active agent ids, which shrink as agents finish;
- ``get_state()`` / ``set_state(state)`` -- the snapshot-restore hook a p2p env
  declares (``EnvFactory`` requires it), so the whole environment restores exactly.

Two rules make the replica deterministic across peers, which is what P2P parity
needs:

- one seed drives ``reset(seed=...)`` and both global random-number generators
  (``random`` and ``numpy.random``), so every peer starts identical;
- a snapshot captures the environment state and both generator states, so a
  rollback replay reproduces the exact state the confirmed inputs imply (API-07
  ``P2PSnapshotCoverage`` -- environment, python rng, numpy rng). A study env that
  draws from a global generator is therefore covered without an env-specific hook.

The engine hashes ``ReplicaFrame.observation`` for the mesh agreement. The adapter
puts the whole environment state there, not the per-agent partial observations, so
the state hash detects a divergence in any hidden state, not only in what a seat
can see. The rewards are keyed by actor id so every peer records the same key set.

One caveat is only about running many replicas in one process, as a test does:
capturing the *global* generators means the replicas share them. Production runs
one replica per peer process, so the capture is exact there; a test keeps its fake
environment's randomness inside ``get_state`` so the shared globals do not perturb
parity. See ``tests/unit/game/test_multiagent_replica.py``.
"""

from __future__ import annotations

import copy
import random
from collections.abc import Callable, Mapping
from typing import Any, cast

import numpy as np

from mug.game.mesh import ReplicaFrame

# A study supplies a factory that builds its parallel environment; the adapter
# never names an environment itself.
ParallelEnvFactory = Callable[[], Any]


def _jsonable(value: Any) -> Any:
    """Normalize a value to json-able data (numpy arrays and scalars included)."""
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


# The opaque snapshot the replica hands the engine: the environment state, the
# active agents, and both global generator states.
_Snapshot = tuple[Any, tuple[str, ...], object, object]


class MultiAgentReplica:
    """Step a PettingZoo parallel environment as one deterministic mesh replica.

    The replica maps the frozen peer actor ids onto the environment's agent ids,
    steps every active agent's action in one parallel step, and reports one
    ``ReplicaFrame`` for the engine. The episode ends when every agent that was
    active at the start of a step has finished. The ``step``, ``snapshot``, and
    ``restore`` bound methods are the callables the engine takes.
    """

    def __init__(
        self,
        factory: ParallelEnvFactory,
        *,
        actor_agents: Mapping[str, str],
        seed: int,
    ) -> None:
        if len(set(actor_agents.values())) != len(actor_agents):
            raise ValueError("each actor must map to a distinct environment agent")
        self._env = factory()
        for method in ("reset", "step", "get_state", "set_state"):
            if not callable(getattr(self._env, method, None)):
                raise TypeError(f"a p2p parallel environment must expose {method}()")
        self._actor_agents = dict(actor_agents)
        self._seed = seed
        self._active: tuple[str, ...] = ()
        self.reset()

    def reset(self) -> ReplicaFrame:
        """Reset the environment and both global generators to the seed.

        One seed drives the environment reset and both generators, so every peer
        starts from the identical state. The returned frame carries the whole
        environment state as its observation, for the mesh state hash.
        """
        random.seed(self._seed)
        np.random.seed(self._seed & 0xFFFFFFFF)
        self._env.reset(seed=self._seed)
        self._active = tuple(self._env.agents)
        return self._frame(rewards={}, terminated=False, truncated=False)

    def step(self, actions: Mapping[str, int]) -> ReplicaFrame:
        """Step one action set: apply every active agent's action, report a frame.

        Only the agents still active take an action; a finished agent has left the
        environment. The episode terminates or truncates once every agent that was
        active at the start of this step has finished.
        """
        before = self._active
        active_agents = set(self._env.agents)
        env_actions = {
            self._actor_agents[actor]: int(action)
            for actor, action in actions.items()
            if self._actor_agents[actor] in active_agents
        }
        _, rewards, terminations, truncations, _ = self._env.step(env_actions)
        terminated = bool(before) and all(
            bool(terminations.get(agent)) for agent in before
        )
        truncated = bool(before) and all(
            bool(truncations.get(agent)) for agent in before
        )
        reward_by_actor = {
            actor: float(rewards.get(agent, 0.0))
            for actor, agent in self._actor_agents.items()
        }
        self._active = tuple(self._env.agents)
        return self._frame(
            rewards=reward_by_actor, terminated=terminated, truncated=truncated
        )

    def snapshot(self) -> object:
        """Return the whole replica state: the env, the agents, both generators."""
        return (
            copy.deepcopy(self._env.get_state()),
            self._active,
            random.getstate(),
            np.random.get_state(),
        )

    def restore(self, state: object) -> None:
        """Restore the whole replica state, so a replay reproduces it exactly."""
        env_state, active, py_rng, np_rng = cast("_Snapshot", state)
        self._env.set_state(copy.deepcopy(env_state))
        self._active = active
        random.setstate(cast("Any", py_rng))
        np.random.set_state(cast("Any", np_rng))

    def _frame(
        self, *, rewards: Mapping[str, float], terminated: bool, truncated: bool
    ) -> ReplicaFrame:
        """Build a replica frame whose observation is the whole env state."""
        return ReplicaFrame(
            observation=_jsonable(self._env.get_state()),
            rewards=dict(rewards),
            terminated=terminated,
            truncated=truncated,
            info=None,
        )


# The opaque AEC snapshot: env state, the selected agent, the seen-terminal flag,
# and both global generator states.
_AecSnapshot = tuple[Any, str, bool, object, object]


class AecReplica:
    """Step a PettingZoo agent-environment-cycle env as one mesh replica.

    A turn-based environment steps one agent at a time, in a cycle, and a seat sees
    the moves made before its own. This replica maps one mesh frame onto one turn:
    it reads the whole confirmed action set the engine resolves, applies the
    *selected* agent's action, and clears any finished agent with the ``step(None)``
    the AEC contract requires, so every frame advances the turn by one live seat. It
    then reports one ``ReplicaFrame`` whose observation is the whole environment
    state, for the mesh state hash. The episode ends when no agent is still active.

    Every peer resolves the identical confirmed action set and applies the identical
    selected action, so every replica walks the identical turn cycle. The engine
    still confirms a frame only when every peer's input is known, which over-
    synchronizes a turn-based game (only one seat moves a frame) but keeps the
    canonical trajectory peer-identical, the property the mesh needs.

    The AEC API this adapter consumes (it duck-types the object):

    - ``reset(seed=...)`` -- start a new episode;
    - ``agent_selection`` -- the agent whose turn it is now;
    - ``agents`` -- the currently active agents, which shrink as agents finish;
    - ``step(action)`` -- apply the current agent's action and advance the
      selection; a finished agent takes ``step(None)``;
    - ``terminations`` / ``truncations`` -- mappings keyed by agent;
    - ``get_state()`` / ``set_state(state)`` -- the snapshot-restore hook a p2p env
      declares, so the whole environment restores exactly.

    The snapshot covers the environment state and both global generators, so a
    rollback replay reproduces the exact state the confirmed inputs imply (API-07
    ``P2PSnapshotCoverage``), exactly as ``MultiAgentReplica`` does.
    """

    _REQUIRED = ("reset", "step", "get_state", "set_state")

    def __init__(
        self,
        factory: ParallelEnvFactory,
        *,
        actor_agents: Mapping[str, str],
        seed: int,
    ) -> None:
        if len(set(actor_agents.values())) != len(actor_agents):
            raise ValueError("each actor must map to a distinct environment agent")
        self._env = factory()
        for method in self._REQUIRED:
            if not callable(getattr(self._env, method, None)):
                raise TypeError(f"a p2p turn-based environment must expose {method}()")
        self._actor_agents = dict(actor_agents)
        self._agent_actors = {agent: actor for actor, agent in actor_agents.items()}
        self._seed = seed
        self._terminated_any = False
        self.reset()

    def reset(self) -> ReplicaFrame:
        """Reset the environment and both global generators to the seed.

        One seed drives the environment reset and both generators, so every peer
        starts from the identical state. The reset lands on the first live seat's
        turn, and the returned frame carries the whole environment state.
        """
        random.seed(self._seed)
        np.random.seed(self._seed & 0xFFFFFFFF)
        self._env.reset(seed=self._seed)
        self._terminated_any = False
        self._land()
        return self._frame(rewards=self._rewards(), terminated=False, truncated=False)

    def step(self, actions: Mapping[str, int]) -> ReplicaFrame:
        """Apply the selected seat's action from the set, then land the next turn.

        The engine resolves one action per peer; only the seat whose turn it is
        acts, so the replica reads that seat's action from the set and steps it. It
        then clears any finished agent, and ends the episode once no agent is active.
        """
        if self._env.agents:
            agent = str(self._env.agent_selection)
            actor = self._agent_actors[agent]
            self._env.step(int(actions[actor]))
        self._land()
        ended = not self._env.agents
        terminated = ended and self._solved()
        truncated = ended and not terminated
        return self._frame(
            rewards=self._rewards(), terminated=terminated, truncated=truncated
        )

    def snapshot(self) -> object:
        """Return the whole replica state: the env, the turn flag, both generators."""
        return (
            copy.deepcopy(self._env.get_state()),
            str(self._env.agent_selection) if self._env.agents else "",
            self._terminated_any,
            random.getstate(),
            np.random.get_state(),
        )

    def restore(self, state: object) -> None:
        """Restore the whole replica state, so a replay reproduces it exactly."""
        env_state, _selection, terminated_any, py_rng, np_rng = cast(
            "_AecSnapshot", state
        )
        self._env.set_state(copy.deepcopy(env_state))
        self._terminated_any = terminated_any
        random.setstate(cast("Any", py_rng))
        np.random.set_state(cast("Any", np_rng))

    # -- internals --------------------------------------------------------------

    def _land(self) -> None:
        """Clear finished agents with ``step(None)`` until a live seat is selected."""
        guard = len(self._actor_agents) + 1
        while self._env.agents and self._is_dead(str(self._env.agent_selection)):
            if self._terminations().get(str(self._env.agent_selection)):
                self._terminated_any = True
            self._env.step(None)
            guard -= 1
            if guard < 0:  # pragma: no cover - a guard against a broken env
                break

    def _is_dead(self, agent: str) -> bool:
        """Return whether the agent has terminated or truncated (needs clearing)."""
        return bool(self._terminations().get(agent)) or bool(
            self._truncations().get(agent)
        )

    def _solved(self) -> bool:
        """Return whether the ended episode closed by a termination, not a cap."""
        if self._terminated_any:
            return True
        return any(bool(value) for value in self._terminations().values())

    def _rewards(self) -> dict[str, float]:
        """Return every actor's reward from the environment's per-agent rewards."""
        rewards = cast("Mapping[str, Any]", getattr(self._env, "rewards", {}))
        return {
            actor: float(rewards.get(agent, 0.0))
            for actor, agent in self._actor_agents.items()
        }

    def _terminations(self) -> Mapping[str, Any]:
        return cast("Mapping[str, Any]", getattr(self._env, "terminations", {}))

    def _truncations(self) -> Mapping[str, Any]:
        return cast("Mapping[str, Any]", getattr(self._env, "truncations", {}))

    def _frame(
        self, *, rewards: Mapping[str, float], terminated: bool, truncated: bool
    ) -> ReplicaFrame:
        """Build a replica frame whose observation is the whole env state."""
        return ReplicaFrame(
            observation=_jsonable(self._env.get_state()),
            rewards=dict(rewards),
            terminated=terminated,
            truncated=truncated,
            info=None,
        )


__all__ = ["AecReplica", "MultiAgentReplica", "ParallelEnvFactory"]
