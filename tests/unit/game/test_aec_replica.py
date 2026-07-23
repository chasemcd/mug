"""The AEC replica adapts a PettingZoo turn-based env to the P2P engine.

These tests drive ``mug.game.multiagent.AecReplica`` with a fake PettingZoo
agent-environment-cycle environment, with no real environment and no socket. They
prove the three things the adapter owns:

- it maps the frozen peer actor ids onto the environment agent ids, applies the
  *selected* agent's action from the confirmed set each frame, walks the turn
  cycle, and ends the episode when every agent has finished;
- its snapshot covers the whole replica, including both global random-number
  generators, so a restore-and-replay reproduces the exact state (API-07
  ``P2PSnapshotCoverage``);
- a full mesh of adapters, driven through the real ``PeerEngine`` over an
  in-process transport that injects latency, reaches a byte-identical canonical
  trajectory on every peer, even when the latency forces rollbacks.

The fake environment keeps its own randomness inside ``get_state`` so many
replicas in one process do not perturb one another; the global-generator test uses
a fake that draws from the global generators, to exercise that coverage.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import cast

import numpy as np

from mug.game.mesh import EndPacket, HashPacket, InputPacket, PeerEngine
from mug.game.multiagent import AecReplica
from mug.kernel import Digest

_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000010f"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000010e"
_RECORDED_AT = "2026-07-21T00:00:00.000000Z"

_AecState = tuple[
    dict[str, int], int, int, list[str], str, dict[str, bool], dict[str, bool]
]


def _actor(index: int) -> str:
    """Return the canonical actor id for one peer index."""
    return f"actor_019b6000-0000-7000-8000-0000000001{index:02x}"


class FakeAecEnv:
    """A deterministic turn-based PettingZoo-style environment.

    The agents take turns in a fixed cycle. On its turn an agent moves along a line
    by its action and a shared self-contained generator noise term. Every agent
    truncates together once a fixed number of turns has been taken. The generator
    lives inside ``get_state`` / ``set_state``, so the env is deterministic without
    touching a global generator.
    """

    def __init__(self, *, agent_ids: tuple[str, ...], horizon: int) -> None:
        self._agent_ids = list(agent_ids)
        self._horizon = horizon
        self._t = 0
        self._rng = 0
        self._pos: dict[str, int] = {}
        self.agents: list[str] = []
        self.agent_selection: str = ""
        self.rewards: dict[str, float] = {}
        self.terminations: dict[str, bool] = {}
        self.truncations: dict[str, bool] = {}

    def reset(self, *, seed: int | None = None) -> None:
        """Reset positions, the turn count, and the generator from the seed."""
        self._t = 0
        self._rng = (seed or 0) & 0x7FFFFFFF
        self._pos = dict.fromkeys(self._agent_ids, 0)
        self.agents = list(self._agent_ids)
        self.agent_selection = self.agents[0]
        self.rewards = dict.fromkeys(self._agent_ids, 0.0)
        self.terminations = dict.fromkeys(self._agent_ids, False)
        self.truncations = dict.fromkeys(self._agent_ids, False)

    def _noise(self) -> int:
        """Advance the linear-congruential generator and return a -1..1 term."""
        self._rng = (self._rng * 1103515245 + 12345) & 0x7FFFFFFF
        return self._rng % 3 - 1

    def observe(self, agent: str) -> int:
        """Return one agent's position."""
        return self._pos[agent]

    def step(self, action: int | None) -> None:
        """Apply the current agent's action, or clear it on ``step(None)``."""
        agent = self.agent_selection
        if action is None:
            self.agents = [a for a in self.agents if a != agent]
            self._advance()
            return
        self._t += 1
        self._pos[agent] += (int(action) - 1) + self._noise()
        self.rewards = dict.fromkeys(self._agent_ids, 0.0)
        self.rewards[agent] = -1.0
        if self._t >= self._horizon:
            self.truncations = dict.fromkeys(self._agent_ids, True)
        self._advance()

    def _advance(self) -> None:
        """Land on the next agent still present, in the fixed cyclic order."""
        if not self.agents:
            self.agent_selection = ""
            return
        order = self._agent_ids
        current = self.agent_selection
        start = order.index(current) if current in order else -1
        for step in range(1, len(order) + 1):
            candidate = order[(start + step) % len(order)]
            if candidate in self.agents:
                self.agent_selection = candidate
                return
        self.agent_selection = ""

    def get_state(self) -> object:
        """Return the whole environment state, including the generator."""
        return (
            dict(self._pos),
            self._t,
            self._rng,
            list(self.agents),
            self.agent_selection,
            dict(self.terminations),
            dict(self.truncations),
        )

    def set_state(self, state: object) -> None:
        """Restore the whole environment state from a snapshot."""
        pos, turn, rng, agents, selection, terms, truncs = cast("_AecState", state)
        self._pos = dict(pos)
        self._t = turn
        self._rng = rng
        self.agents = list(agents)
        self.agent_selection = selection
        self.terminations = dict(terms)
        self.truncations = dict(truncs)


class GlobalRngAecEnv:
    """A one-agent turn-based env whose step draws from the global generators.

    It exercises the adapter's coverage of the global ``random`` and
    ``numpy.random`` state: its observation depends on a draw from each, so a
    replay that did not restore them would diverge.
    """

    def __init__(self, *, agent_id: str) -> None:
        self._agent_id = agent_id
        self._value = 0.0
        self.agents: list[str] = []
        self.agent_selection: str = ""
        self.rewards: dict[str, float] = {}
        self.terminations: dict[str, bool] = {}
        self.truncations: dict[str, bool] = {}

    def reset(self, *, seed: int | None = None) -> None:
        self._value = 0.0
        self.agents = [self._agent_id]
        self.agent_selection = self._agent_id
        self.rewards = {self._agent_id: 0.0}
        self.terminations = {self._agent_id: False}
        self.truncations = {self._agent_id: False}

    def observe(self, agent: str) -> float:
        return self._value

    def step(self, action: int | None) -> None:
        draw = random.random() + float(np.random.random())
        self._value += draw + float(action or 0)
        self.rewards = {self._agent_id: draw}

    def get_state(self) -> object:
        return self._value

    def set_state(self, state: object) -> None:
        self._value = cast("float", state)


def _replica(actors: tuple[str, ...], *, horizon: int, seed: int) -> AecReplica:
    """Build one AEC replica whose actors map to fake env agents."""
    agent_ids = tuple(f"player_{i}" for i in range(len(actors)))
    mapping = dict(zip(actors, agent_ids, strict=True))
    return AecReplica(
        lambda: FakeAecEnv(agent_ids=agent_ids, horizon=horizon),
        actor_agents=mapping,
        seed=seed,
    )


# -- unit: the adapter maps the AEC API onto the seam --------------------------


def test_the_adapter_applies_the_selected_seats_action() -> None:
    """One frame applies only the seat whose turn it is, keyed back to the actors."""
    actors = (_actor(1), _actor(2))
    replica = _replica(actors, horizon=10, seed=5)

    frame = replica.step({actors[0]: 2, actors[1]: 0})

    assert set(frame.rewards) == set(actors)
    assert not frame.terminated and not frame.truncated


def test_the_episode_truncates_when_every_agent_finishes() -> None:
    """The single episode outcome aggregates the per-agent truncation flags.

    Two agents alternate turns, so a horizon of four turns is reached on the fourth
    frame; the trailing frames clear the two truncated agents, and the frame that
    empties the roster reports the truncation.
    """
    actors = (_actor(1), _actor(2))
    replica = _replica(actors, horizon=4, seed=5)

    outcomes = [replica.step({actors[0]: 1, actors[1]: 1}).truncated for _ in range(4)]

    assert outcomes[-1] is True
    assert True in outcomes


def test_a_distinct_agent_mapping_is_required() -> None:
    """Two actors may not map to the same environment agent."""
    actors = (_actor(1), _actor(2))
    try:
        AecReplica(
            lambda: FakeAecEnv(agent_ids=("player_0",), horizon=5),
            actor_agents={actors[0]: "player_0", actors[1]: "player_0"},
            seed=1,
        )
    except ValueError:
        return
    raise AssertionError("a duplicate agent mapping must raise")


def test_a_non_turn_based_environment_is_rejected() -> None:
    """An object missing the snapshot hooks is refused at construction."""

    class NoSnapshot:
        def __init__(self) -> None:
            self.agents: list[str] = []
            self.agent_selection = ""

        def reset(self, *, seed: int | None = None) -> None:
            return None

        def step(self, action: int | None) -> None:
            return None

    try:
        AecReplica(NoSnapshot, actor_agents={_actor(1): "a", _actor(2): "b"}, seed=1)
    except TypeError:
        return
    raise AssertionError("an env without get_state/set_state must raise")


def test_the_snapshot_covers_the_global_generators() -> None:
    """A restore reproduces a global-generator env exactly, replay for replay.

    This is the load-bearing guard: an adapter that dropped the generator capture
    from its snapshot would draw different values on replay and fail this assertion.
    """
    actor = _actor(1)
    replica = AecReplica(
        lambda: GlobalRngAecEnv(agent_id="player_0"),
        actor_agents={actor: "player_0"},
        seed=99,
    )
    snapshot = replica.snapshot()
    first = [replica.step({actor: 1}).observation for _ in range(4)]

    replica.restore(snapshot)
    second = [replica.step({actor: 1}).observation for _ in range(4)]

    assert first == second


# -- integration: a mesh of AEC replicas reaches parity under rollback ---------


def _build_engine(
    actor: str, actors: tuple[str, ...], replica: AecReplica, *, max_steps: int
) -> PeerEngine:
    """Build one peer engine over an AEC replica for the mesh run."""
    return PeerEngine(
        actor_id=actor,
        peer_actor_ids=actors,
        interaction_id=_INTERACTION,
        episode_id=_EPISODE,
        channel_key="p2p-game",
        mesh_membership_digest=Digest(algorithm="sha-256", hex="a" * 64),
        membership_generation=1,
        step=replica.step,
        snapshot=replica.snapshot,
        restore=replica.restore,
        recorded_at=_RECORDED_AT,
        input_delay=1,
        snapshot_interval=5,
        default_action=1,
        prediction="repeat-last",
        redundancy=10,
        max_steps=max_steps,
    )


def _run_latency_mesh(
    actors: tuple[str, ...], *, horizon: int, latency: int
) -> dict[str, PeerEngine]:
    """Run a full-mesh episode with a fixed transport latency and finalize."""
    actors = tuple(sorted(actors))
    engines = {
        actor: _build_engine(
            actor,
            actors,
            _replica(actors, horizon=horizon, seed=2024),
            max_steps=horizon + 50,
        )
        for actor in actors
    }
    input_q: list[tuple[int, str, InputPacket]] = []
    hash_q: list[tuple[int, str, HashPacket]] = []
    end_q: list[tuple[int, str, EndPacket]] = []
    announced: set[str] = set()
    ticks = horizon + latency + 60

    for tick in range(ticks):
        for due, receiver, packet in input_q:
            if due == tick:
                engines[receiver].receive_input(packet)
        for due, receiver, hpacket in hash_q:
            if due == tick:
                engines[receiver].receive_hash(hpacket)
        for due, receiver, epacket in end_q:
            if due == tick:
                engines[receiver].receive_end(epacket)

        for index, sender in enumerate(actors):
            engine = engines[sender]
            action = 1 if engine.ended() else (tick * 5 + index * 2 + 1) % 3
            packet = engine.submit_local(action)
            for receiver in actors:
                if receiver != sender:
                    input_q.append((max(tick + 1, tick + latency), receiver, packet))

        for sender in actors:
            engines[sender].advance()

        for sender in actors:
            engine = engines[sender]
            reliable = tick + max(1, latency)
            for hpacket in engine.outbound_hashes():
                for receiver in actors:
                    if receiver != sender:
                        hash_q.append((reliable, receiver, hpacket))
            epacket = engine.announce_end()
            if epacket is not None and sender not in announced:
                announced.add(sender)
                for receiver in actors:
                    if receiver != sender:
                        end_q.append((reliable, receiver, epacket))

    for engine in engines.values():
        engine.finalize()
    return engines


def _canonical_rows(engines: Mapping[str, PeerEngine]) -> dict[str, list[object]]:
    """Return each peer's parity-comparable canonical rows."""
    return {
        actor: [record.canonical() for record in engine.canonical_trajectory()]
        for actor, engine in engines.items()
    }


def test_a_mesh_of_aec_replicas_reaches_identical_trajectories() -> None:
    """Two peers stepping the same turn-based env export byte-identical canon rows."""
    actors = (_actor(1), _actor(2))
    engines = _run_latency_mesh(actors, horizon=40, latency=5)

    rows = _canonical_rows(engines)
    reference = rows[min(rows)]
    assert len(reference) > 0
    for actor, actor_rows in rows.items():
        assert actor_rows == reference, f"peer {actor} diverged"
    # The latency past the input delay forces at least one corrective rollback.
    assert any(engine.rollback_count() > 0 for engine in engines.values())


def test_a_three_peer_aec_mesh_keeps_parity() -> None:
    """A three-agent turn-based env reaches one identical trajectory under latency."""
    actors = (_actor(1), _actor(2), _actor(3))
    engines = _run_latency_mesh(actors, horizon=36, latency=4)

    rows = _canonical_rows(engines)
    reference = rows[min(rows)]
    for actor_rows in rows.values():
        assert actor_rows == reference
