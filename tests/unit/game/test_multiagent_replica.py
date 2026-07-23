"""The multi-agent replica adapts a PettingZoo parallel env to the P2P engine.

These tests drive ``mug.game.multiagent.MultiAgentReplica`` with a fake PettingZoo
parallel environment, with no real environment and no socket. They prove the three
things the adapter owns:

- it maps the frozen peer actor ids onto the environment agent ids, steps every
  active agent in one parallel step, and aggregates the per-agent terminal and
  truncation flags into the single episode outcome the engine reads;
- its snapshot covers the whole replica, including both global random-number
  generators, so a restore-and-replay reproduces the exact state; the positive
  coverage test is the load-bearing guard, because an adapter that dropped the
  generator capture would replay differently and fail it (API-07
  ``P2PSnapshotCoverage``). A separate test shows why: the environment state alone
  is not enough to reproduce a replay.
- a full mesh of adapters, driven through the real ``PeerEngine`` over an
  in-process transport that injects latency, reaches a byte-identical canonical
  trajectory on every peer, even when the latency forces deep rollbacks.

The fake environment keeps its own randomness inside ``get_state`` so that many
replicas in one test process do not perturb one another through the shared global
generators (production runs one replica per peer process). The global-generator
test uses a fake that draws from the global generators, to exercise that coverage.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from typing import Any, cast

import numpy as np

from mug.game.mesh import EndPacket, HashPacket, InputPacket, PeerEngine
from mug.game.multiagent import MultiAgentReplica
from mug.kernel import Digest

_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000010f"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000010e"
_RECORDED_AT = "2026-07-21T00:00:00.000000Z"

_ParallelStep = tuple[
    dict[str, Any],
    dict[str, float],
    dict[str, bool],
    dict[str, bool],
    dict[str, Any],
]
_FakeSnapshot = tuple[dict[str, int], int, int, list[str]]


def _actor(index: int) -> str:
    """Return the canonical actor id for one peer index."""
    return f"actor_019b6000-0000-7000-8000-0000000001{index:02x}"


class FakeParallelEnv:
    """A deterministic multi-agent PettingZoo-style parallel environment.

    Each step moves every agent along a line by its action and a shared
    self-contained generator noise term, and truncates every agent together at a
    fixed horizon. The generator lives inside ``get_state`` / ``set_state``, so the
    environment is deterministic without touching a global generator.
    """

    def __init__(self, *, agent_ids: tuple[str, ...], horizon: int) -> None:
        self._agent_ids = agent_ids
        self._horizon = horizon
        self._t = 0
        self._rng = 0
        self._pos: dict[str, int] = {}
        self.agents: list[str] = []

    def reset(
        self, *, seed: int | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Reset positions, the step count, and the generator from the seed."""
        self._t = 0
        self._rng = (seed or 0) & 0x7FFFFFFF
        self._pos = dict.fromkeys(self._agent_ids, 0)
        self.agents = list(self._agent_ids)
        return ({a: self._pos[a] for a in self.agents}, {a: {} for a in self.agents})

    def _noise(self) -> int:
        """Advance the linear-congruential generator and return a -1..1 term."""
        self._rng = (self._rng * 1103515245 + 12345) & 0x7FFFFFFF
        return self._rng % 3 - 1

    def step(self, actions: Mapping[str, int]) -> _ParallelStep:
        """Step every active agent one action and report the parallel five-tuple."""
        self._t += 1
        noise = self._noise()
        for agent in self.agents:
            self._pos[agent] += (int(actions.get(agent, 1)) - 1) + noise
        truncated = self._t >= self._horizon
        obs = {a: self._pos[a] for a in self.agents}
        rewards = {a: -1.0 for a in self.agents}
        terms = {a: False for a in self.agents}
        truncs = {a: truncated for a in self.agents}
        infos: dict[str, Any] = {a: {} for a in self.agents}
        if truncated:
            self.agents = []
        return obs, rewards, terms, truncs, infos

    def get_state(self) -> object:
        """Return the whole environment state: positions, step, and generator."""
        return (dict(self._pos), self._t, self._rng, list(self.agents))

    def set_state(self, state: object) -> None:
        """Restore the whole environment state from a snapshot."""
        positions, step, rng, agents = cast("_FakeSnapshot", state)
        self._pos = dict(positions)
        self._t = step
        self._rng = rng
        self.agents = list(agents)


class GlobalRngEnv:
    """A one-agent parallel env whose step draws from the global generators.

    It exists to exercise the adapter's coverage of the global ``random`` and
    ``numpy.random`` state: its observation depends on a draw from each, so a
    replay that did not restore them would diverge.
    """

    def __init__(self, *, agent_id: str) -> None:
        self._agent_id = agent_id
        self._value = 0.0
        self.agents: list[str] = []

    def reset(
        self, *, seed: int | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self._value = 0.0
        self.agents = [self._agent_id]
        return ({self._agent_id: self._value}, {self._agent_id: {}})

    def step(self, actions: Mapping[str, int]) -> _ParallelStep:
        draw = random.random() + float(np.random.random())
        self._value += draw + float(actions.get(self._agent_id, 0))
        return (
            {self._agent_id: self._value},
            {self._agent_id: draw},
            {self._agent_id: False},
            {self._agent_id: False},
            {self._agent_id: {}},
        )

    def get_state(self) -> object:
        return self._value

    def set_state(self, state: object) -> None:
        self._value = cast("float", state)


def _replica(
    actors: tuple[str, ...], *, horizon: int, seed: int
) -> MultiAgentReplica:
    """Build one multi-agent replica whose actors map to fake env agents."""
    agent_ids = tuple(f"player_{i}" for i in range(len(actors)))
    mapping = dict(zip(actors, agent_ids, strict=True))
    return MultiAgentReplica(
        lambda: FakeParallelEnv(agent_ids=agent_ids, horizon=horizon),
        actor_agents=mapping,
        seed=seed,
    )


# -- unit: the adapter maps and aggregates the parallel API --------------------


def test_the_adapter_maps_actors_to_agents_and_steps_all_seats() -> None:
    """One parallel step applies every seat's action, keyed back to the actors."""
    actors = (_actor(1), _actor(2))
    replica = _replica(actors, horizon=10, seed=5)

    frame = replica.step({actors[0]: 2, actors[1]: 0})

    assert set(frame.rewards) == set(actors)
    assert frame.rewards[actors[0]] == -1.0
    assert not frame.terminated and not frame.truncated


def test_the_episode_truncates_when_every_agent_finishes() -> None:
    """The single episode outcome aggregates the per-agent truncation flags."""
    actors = (_actor(1), _actor(2))
    replica = _replica(actors, horizon=3, seed=5)

    outcomes = [replica.step({actors[0]: 1, actors[1]: 1}).truncated for _ in range(3)]

    assert outcomes == [False, False, True]


def test_a_distinct_agent_mapping_is_required() -> None:
    """Two actors may not map to the same environment agent."""
    actors = (_actor(1), _actor(2))
    try:
        MultiAgentReplica(
            lambda: FakeParallelEnv(agent_ids=("player_0",), horizon=5),
            actor_agents={actors[0]: "player_0", actors[1]: "player_0"},
            seed=1,
        )
    except ValueError:
        return
    raise AssertionError("a duplicate agent mapping must raise")


def test_a_non_parallel_environment_is_rejected() -> None:
    """An object missing the parallel snapshot hooks is refused at construction."""

    class NoSnapshot:
        def reset(
            self, *, seed: int | None = None
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            return {}, {}

        def step(self, actions: Mapping[str, int]) -> _ParallelStep:
            return {}, {}, {}, {}, {}

    try:
        MultiAgentReplica(
            NoSnapshot, actor_agents={_actor(1): "a", _actor(2): "b"}, seed=1
        )
    except TypeError:
        return
    raise AssertionError("an env without get_state/set_state must raise")


# -- the snapshot covers the global generators ---------------------------------


def test_the_snapshot_covers_the_global_generators() -> None:
    """A restore reproduces a global-generator env exactly, replay for replay.

    This is the load-bearing guard: an adapter that dropped the generator capture
    from its snapshot would not reset the generators on restore, so the replay
    would draw different values and this assertion would fail.
    """
    actor = _actor(1)
    replica = MultiAgentReplica(
        lambda: GlobalRngEnv(agent_id="player_0"),
        actor_agents={actor: "player_0"},
        seed=99,
    )
    snapshot = replica.snapshot()
    first = [replica.step({actor: 1}).observation for _ in range(4)]

    replica.restore(snapshot)
    second = [replica.step({actor: 1}).observation for _ in range(4)]

    assert first == second


def test_the_environment_state_alone_cannot_reproduce_a_replay() -> None:
    """Why the coverage matters: env state without the generators diverges.

    Restoring only the environment state, and leaving the global generators
    advanced, replays a different trajectory. This is what the adapter avoids by
    capturing the generators as well.
    """
    random.seed(3)
    np.random.seed(3)
    env = GlobalRngEnv(agent_id="player_0")
    env.reset(seed=3)
    env_state = env.get_state()
    first = [env.step({"player_0": 1})[0]["player_0"] for _ in range(4)]

    env.set_state(env_state)  # restore the env only, not the global generators
    second = [env.step({"player_0": 1})[0]["player_0"] for _ in range(4)]

    assert first != second


# -- integration: a mesh of adapters reaches parity under rollback -------------


def _build_engine(
    actor: str, actors: tuple[str, ...], replica: MultiAgentReplica, *, max_steps: int
) -> PeerEngine:
    """Build one peer engine over a multi-agent replica for the mesh run."""
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


def test_a_mesh_of_multi_agent_replicas_reaches_identical_trajectories() -> None:
    """Two peers stepping the same parallel env export byte-identical canon rows."""
    actors = (_actor(1), _actor(2))
    engines = _run_latency_mesh(actors, horizon=40, latency=5)

    rows = _canonical_rows(engines)
    reference = rows[min(rows)]
    assert len(reference) == 40
    for actor, actor_rows in rows.items():
        assert actor_rows == reference, f"peer {actor} diverged"
    # The latency past the input delay forces at least one corrective rollback.
    assert any(engine.rollback_count() > 0 for engine in engines.values())


def test_a_three_peer_multi_agent_mesh_keeps_parity() -> None:
    """A three-agent parallel env reaches one identical trajectory under latency."""
    actors = (_actor(1), _actor(2), _actor(3))
    engines = _run_latency_mesh(actors, horizon=35, latency=4)

    rows = _canonical_rows(engines)
    reference = rows[min(rows)]
    assert len(reference) == 35
    for actor_rows in rows.values():
        assert actor_rows == reference
