"""The mesh session drives a mesh of peer engines through one episode.

These tests drive ``mug.game.mesh_session.MeshSession`` with a self-contained
replica and a scripted per-seat action, with no socket and no real clock. They
prove the coordinator wires one peer engine per seat, relays the inputs across the
mesh, and reports one identical canonical trajectory per seat, closed on the shared
end-frame barrier. One test drives a ``MultiAgentReplica`` over a fake PettingZoo
parallel environment through the coordinator, so the whole peer-to-peer path runs
end to end for the multi-agent shape the CoGrid Overcooked suite exposes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from mug.game.mesh import ReplicaFrame
from mug.game.mesh_session import (
    MeshGameSpec,
    MeshSession,
    SeatWiring,
)
from mug.game.multiagent import MultiAgentReplica
from mug.kernel import Digest

_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000010f"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000010e"
_RECORDED_AT = "2026-07-22T00:00:00.000000Z"
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


def _actor(index: int) -> str:
    """Return the canonical actor id for one seat index."""
    return f"actor_019b6000-0000-7000-8000-0000000001{index:02x}"


# -- a self-contained replica -------------------------------------------------

_LineSnapshot = tuple[tuple[tuple[str, int], ...], int, int]


class LineReplica:
    """A deterministic multi-seat replica whose state depends on a generator.

    Each step moves every seat by its action and by a shared linear-congruential
    noise term, and ends the episode after a fixed length. The snapshot captures
    the positions, the step count, and the generator, so a restore reproduces the
    exact state a replay implies. The generator lives inside the replica, so many
    replicas in one process do not perturb one another.
    """

    def __init__(self, peers: tuple[str, ...], *, seed: int, episode_len: int) -> None:
        self._peers = tuple(sorted(peers))
        self._seed = seed
        self._episode_len = episode_len
        self._t = 0
        self._rng = seed & 0x7FFFFFFF
        self._pos: dict[str, int] = dict.fromkeys(self._peers, 0)

    def _noise(self) -> int:
        self._rng = (self._rng * 1103515245 + 12345) & 0x7FFFFFFF
        return self._rng % 3 - 1

    def step(self, actions: Mapping[str, int]) -> ReplicaFrame:
        self._t += 1
        noise = self._noise()
        for actor in self._peers:
            self._pos[actor] += (int(actions.get(actor, 0)) - 1) + noise
        observation = [self._pos[actor] for actor in self._peers]
        observation.extend((self._t, self._rng))
        return ReplicaFrame(
            observation=observation,
            rewards={actor: -1.0 for actor in self._peers},
            terminated=self._t >= self._episode_len,
            truncated=False,
            info={},
        )

    def snapshot(self) -> object:
        return (tuple(sorted(self._pos.items())), self._t, self._rng)

    def restore(self, state: object) -> None:
        positions, step, rng = cast("_LineSnapshot", state)
        self._pos = dict(positions)
        self._t = step
        self._rng = rng


def _line_spec(*, size: int, episode_len: int) -> MeshGameSpec:
    """Build a mesh game spec over the self-contained line replica."""
    return MeshGameSpec(
        channel_key="p2p-game",
        size=size,
        make_replica=lambda peers, seed: LineReplica(
            peers, seed=seed, episode_len=episode_len
        ),
        action_bindings={"a": 0, "d": 2},
        default_action=1,
        seed=12345,
        fps=0,
        max_steps=episode_len + 10,
        input_delay=2,
        snapshot_interval=5,
    )


class _Script:
    """A per-seat scripted action source: return the next action each tick."""

    def __init__(self, actions: list[int], default: int) -> None:
        self._actions = actions
        self._default = default
        self._i = 0

    def __call__(self) -> int:
        at_end = self._i >= len(self._actions)
        value = self._default if at_end else self._actions[self._i]
        self._i += 1
        return value


class _Sink:
    """A collecting frame sink that records the frames pushed to one seat."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def __call__(self, frame: dict[str, Any]) -> None:
        self.frames.append(frame)


def _seats(spec_size: int, scripts: list[list[int]], default: int) -> list[SeatWiring]:
    """Build the seat wirings for a mesh of the given size."""
    return [
        SeatWiring(
            seat_key=f"seat-{index + 1}",
            actor_id=_actor(index + 1),
            action=_Script(scripts[index], default),
            send=_Sink(),
        )
        for index in range(spec_size)
    ]


def _session(seats: list[SeatWiring], spec: MeshGameSpec) -> MeshSession:
    """Build a mesh session over the seats and the spec."""
    return MeshSession(
        seats=seats,
        spec=spec,
        interaction_id=_INTERACTION,
        episode_id=_EPISODE,
        mesh_membership_digest=_DIGEST,
        membership_generation=1,
        recorded_at=_RECORDED_AT,
    )


# -- the coordinator ----------------------------------------------------------


async def test_two_seats_reach_one_identical_trajectory() -> None:
    """Two seats run their own engines and export the identical canonical run."""
    spec = _line_spec(size=2, episode_len=20)
    scripts = [[0, 2, 1, 0, 2] * 8, [2, 0, 1, 2, 0] * 8]
    seats = _seats(2, scripts, spec.default_action)
    episode = await _session(seats, spec).run()

    assert episode.verified
    assert episode.frames == 20
    reference = episode.reference_summary()
    assert reference.channel_key == "p2p-game"
    assert reference.boundary.kind == "terminal"
    assert reference.boundary.p2p_barrier is not None
    assert reference.boundary.end_frame_exclusive == 20
    # Every seat's transitions carry the peer authority and the mesh identity.
    for actor, summary in episode.summaries.items():
        assert len(summary.transitions) == 20
        first = summary.transitions[0]
        assert first.authority == "peer"
        assert first.replica_actor_id == actor
        assert first.mesh_membership_digest == _DIGEST


async def test_every_seat_receives_a_frame_per_step() -> None:
    """The coordinator pushes one frame to every seat each tick until the end."""
    spec = _line_spec(size=2, episode_len=12)
    scripts = [[1] * 20, [1] * 20]
    seats = _seats(2, scripts, spec.default_action)
    await _session(seats, spec).run()

    for seat in seats:
        sink = cast("_Sink", seat.send)
        assert len(sink.frames) == 12
        assert sink.frames[0]["seat_key"] == seat.seat_key
        assert [frame["frame_number"] for frame in sink.frames] == list(range(12))


async def test_three_seats_keep_parity_and_share_the_barrier() -> None:
    """A three-seat mesh exports one identical trajectory on the shared barrier."""
    spec = _line_spec(size=3, episode_len=15)
    scripts = [[0, 2, 1] * 10, [2, 1, 0] * 10, [1, 0, 2] * 10]
    seats = _seats(3, scripts, spec.default_action)
    episode = await _session(seats, spec).run()

    assert episode.verified
    assert episode.frames == 15
    ends = {
        summary.boundary.end_frame_exclusive for summary in episode.summaries.values()
    }
    assert ends == {15}


async def test_a_session_needs_at_least_two_seats() -> None:
    """A single-seat mesh is refused; a mesh needs at least two peers."""
    spec = _line_spec(size=1, episode_len=10)
    seats = _seats(1, [[1] * 10], spec.default_action)
    try:
        _session(seats, spec)
    except ValueError as error:
        assert "two seats" in str(error)
    else:  # pragma: no cover - the guard must raise
        raise AssertionError("a single-seat mesh must be refused")


# -- the PettingZoo parallel path through the coordinator ---------------------


class FakeParallelEnv:
    """A minimal PettingZoo-parallel multi-agent environment for the adapter.

    Two agents move along a line. The whole state (including a self-contained
    generator) lives in ``get_state`` / ``set_state``, the declared snapshot-restore
    hook, so the ``MultiAgentReplica`` snapshot reproduces it exactly and many
    replicas in one process keep parity.
    """

    def __init__(self, *, episode_len: int) -> None:
        self._episode_len = episode_len
        self.agents: list[str] = ["agent_0", "agent_1"]
        self._t = 0
        self._rng = 0
        self._pos = {"agent_0": 0, "agent_1": 0}

    def reset(self, *, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
        self._t = 0
        self._rng = seed & 0x7FFFFFFF
        self._pos = {"agent_0": 0, "agent_1": 0}
        self.agents = ["agent_0", "agent_1"]
        return dict(self._pos), {}

    def step(
        self, actions: Mapping[str, int]
    ) -> tuple[
        dict[str, Any],
        dict[str, float],
        dict[str, bool],
        dict[str, bool],
        dict[str, Any],
    ]:
        self._t += 1
        self._rng = (self._rng * 1103515245 + 12345) & 0x7FFFFFFF
        noise = self._rng % 3 - 1
        for agent in list(self.agents):
            self._pos[agent] += (int(actions.get(agent, 0)) - 1) + noise
        done = self._t >= self._episode_len
        rewards = {agent: -1.0 for agent in self.agents}
        terms = {agent: done for agent in self.agents}
        truncs = {agent: False for agent in self.agents}
        if done:
            self.agents = []
        return dict(self._pos), rewards, terms, truncs, {}

    def get_state(self) -> dict[str, Any]:
        return {"t": self._t, "rng": self._rng, "pos": dict(self._pos)}

    def set_state(self, state: Mapping[str, Any]) -> None:
        self._t = int(state["t"])
        self._rng = int(state["rng"])
        self._pos = dict(cast("dict[str, int]", state["pos"]))


def _multiagent_spec(*, episode_len: int) -> MeshGameSpec:
    """Build a mesh spec whose replica is a MultiAgentReplica over the fake env."""

    def make_replica(peers: tuple[str, ...], seed: int) -> MultiAgentReplica:
        mapping = {peers[0]: "agent_0", peers[1]: "agent_1"}
        return MultiAgentReplica(
            lambda: FakeParallelEnv(episode_len=episode_len),
            actor_agents=mapping,
            seed=seed,
        )

    return MeshGameSpec(
        channel_key="overcooked-p2p",
        size=2,
        make_replica=make_replica,
        action_bindings={"a": 0, "d": 2},
        default_action=1,
        seed=999,
        fps=0,
        max_steps=episode_len + 10,
        input_delay=2,
        snapshot_interval=4,
    )


async def test_a_pettingzoo_parallel_mesh_runs_end_to_end() -> None:
    """A MultiAgentReplica mesh forms, runs, and exports one identical trajectory.

    This proves the whole peer-to-peer path -- the coordinator, the peer engines,
    and the parallel adapter -- runs end to end for the multi-agent shape the CoGrid
    Overcooked suite exposes, with no PettingZoo import and no environment named.
    """
    spec = _multiagent_spec(episode_len=16)
    scripts = [[0, 2, 1, 2] * 6, [2, 0, 2, 1] * 6]
    seats = _seats(2, scripts, spec.default_action)
    episode = await _session(seats, spec).run()

    assert episode.verified
    assert episode.frames == 16
    assert episode.reference_summary().boundary.kind == "terminal"
