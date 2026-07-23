"""The peer-to-peer rollback engine keeps every peer's canonical trajectory equal.

These tests drive the deterministic rollback engine (``mug.game.mesh``) with a
fake deterministic replica and an in-process mesh, with no socket, no WebRTC, and
no real clock. They reproduce the legacy end-to-end parity suite as deterministic
unit tests: two or more peers step their own replicas, exchange inputs over a mesh
that injects latency, packet loss, and a long silence, and each peer's exported
canonical trajectory must be byte-identical to every other peer's.

The parity oracle mirrors the legacy ``validate_action_sequences`` comparison: it
compares only the canonical fields (actions, rewards, terminal and truncation
flags, info, and the state hash) and excludes the client-local fields (whether a
frame was speculative and which peers it predicted), because each peer has its own
rollback perspective. The trajectories must still be identical.

The replica is a small line world whose observation depends on both the actions
and a random-number generator whose state the snapshot captures. So a rollback
that failed to restore the generator would diverge the state hash and break
parity. Parity holding under deep rollback therefore also proves the snapshot
covers the generator (API-07 ``P2PSnapshotCoverage``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from mug.game.mesh import (
    EndPacket,
    HashPacket,
    InputPacket,
    PeerEngine,
    Prediction,
    ReplicaFrame,
)
from mug.kernel import Digest

_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000010f"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000010e"
_RECORDED_AT = "2026-07-21T00:00:00.000000Z"


def _actor(index: int) -> str:
    """Return the canonical actor id for one peer index."""
    return f"actor_019b6000-0000-7000-8000-0000000001{index:02x}"


# The opaque snapshot the replica hands the engine: positions, step, and the rng.
_Snapshot = tuple[tuple[tuple[str, int], ...], int, int]


class LineWorld:
    """A deterministic multi-seat replica: each seat moves along a line.

    Each step moves every seat by its action and by a shared random-number-generator
    noise term, so the observation depends on the whole action history and on the
    generator. The snapshot captures the positions, the step count, and the
    generator state, so a restore reproduces the exact state a replay implies.
    """

    def __init__(self, actors: tuple[str, ...], *, seed: int, episode_len: int) -> None:
        self._actors = tuple(sorted(actors))
        self._seed = seed
        self._episode_len = episode_len
        self._t = 0
        self._rng = 0
        self._pos: dict[str, int] = {}
        self.reset()

    def reset(self) -> None:
        """Reset the positions, the step count, and the generator to the seed."""
        self._t = 0
        self._rng = self._seed & 0x7FFFFFFF
        self._pos = dict.fromkeys(self._actors, 0)

    def _noise(self) -> int:
        """Advance the linear-congruential generator and return a -1..1 term."""
        self._rng = (self._rng * 1103515245 + 12345) & 0x7FFFFFFF
        return self._rng % 3 - 1

    def step(self, actions: Mapping[str, int]) -> ReplicaFrame:
        """Step one action set: move every seat and report the new observation."""
        self._t += 1
        noise = self._noise()
        for actor in self._actors:
            self._pos[actor] += (int(actions.get(actor, 1)) - 1) + noise
        observation = [self._pos[actor] for actor in self._actors]
        observation.extend((self._t, self._rng))
        rewards = {actor: -1.0 for actor in self._actors}
        return ReplicaFrame(
            observation=observation,
            rewards=rewards,
            terminated=self._t >= self._episode_len,
            truncated=False,
            info={},
        )

    def snapshot(self) -> object:
        """Return the whole replica state: positions, step count, and generator."""
        return (tuple(sorted(self._pos.items())), self._t, self._rng)

    def restore(self, state: object) -> None:
        """Restore the whole replica state from a snapshot."""
        positions, step, rng = cast("_Snapshot", state)
        self._pos = dict(positions)
        self._t = step
        self._rng = rng


class _Rng:
    """A small deterministic generator for the mesh loss and jitter decisions."""

    def __init__(self, seed: int) -> None:
        self._state = seed & 0x7FFFFFFF

    def unit(self) -> float:
        """Return the next value in the half-open unit interval."""
        self._state = (self._state * 1103515245 + 12345) & 0x7FFFFFFF
        return self._state / 0x7FFFFFFF


def _build_engine(
    actor: str,
    actors: tuple[str, ...],
    world: LineWorld,
    *,
    input_delay: int,
    snapshot_interval: int,
    default_action: int,
    prediction: Prediction,
    max_steps: int,
) -> PeerEngine:
    """Build one peer engine over its own replica for the mesh run."""
    digest = Digest(algorithm="sha-256", hex="a" * 64)
    return PeerEngine(
        actor_id=actor,
        peer_actor_ids=actors,
        interaction_id=_INTERACTION,
        episode_id=_EPISODE,
        channel_key="p2p-game",
        mesh_membership_digest=digest,
        membership_generation=1,
        step=world.step,
        snapshot=world.snapshot,
        restore=world.restore,
        recorded_at=_RECORDED_AT,
        input_delay=input_delay,
        snapshot_interval=snapshot_interval,
        default_action=default_action,
        prediction=prediction,
        redundancy=10,
        max_steps=max_steps,
    )


def run_mesh(
    *,
    actors: tuple[str, ...],
    scripts: Mapping[str, list[int]],
    episode_len: int,
    input_delay: int = 1,
    snapshot_interval: int = 5,
    latency: int = 0,
    loss: float = 0.0,
    jitter: int = 0,
    silent: Mapping[str, tuple[int, int]] | None = None,
    prediction: Prediction = "repeat-last",
    default_action: int = 1,
    extra_ticks: int = 80,
    seed: int = 12345,
) -> dict[str, PeerEngine]:
    """Run one full-mesh episode over the in-process transport and return the peers.

    Each peer submits its scripted action every tick and steps once. The transport
    delivers each input packet after ``latency`` ticks (plus jitter), drops it with
    probability ``loss`` (the redundant packets recover it), or -- inside a peer's
    ``silent`` window -- withholds the peer's packets and flushes them at the window
    end, which forces a deep rollback on the other peers. Hashes and end packets
    deliver reliably. After the run every peer finalizes on the minimum end frame.
    """
    actors = tuple(sorted(actors))
    worlds = {
        actor: LineWorld(actors, seed=seed, episode_len=episode_len)
        for actor in actors
    }
    engines = {
        actor: _build_engine(
            actor,
            actors,
            worlds[actor],
            input_delay=input_delay,
            snapshot_interval=snapshot_interval,
            default_action=default_action,
            prediction=prediction,
            max_steps=episode_len + 50,
        )
        for actor in actors
    }
    rng = _Rng(seed ^ 0x9E3779B9)
    silent = silent or {}

    input_q: list[tuple[int, str, InputPacket]] = []
    hash_q: list[tuple[int, str, HashPacket]] = []
    end_q: list[tuple[int, str, EndPacket]] = []
    ended_announced: set[str] = set()

    silent_end = max((window[1] for window in silent.values()), default=0)
    ticks = episode_len + latency + silent_end + extra_ticks

    def jit() -> int:
        if jitter <= 0:
            return 0
        return int(rng.unit() * (2 * jitter + 1)) - jitter

    for tick in range(ticks):
        for due_tick, receiver, packet in input_q:
            if due_tick == tick:
                engines[receiver].receive_input(packet)
        for due_tick, receiver, hash_packet in hash_q:
            if due_tick == tick:
                engines[receiver].receive_hash(hash_packet)
        for due_tick, receiver, end_packet in end_q:
            if due_tick == tick:
                engines[receiver].receive_end(end_packet)

        for sender in actors:
            engine = engines[sender]
            if engine.ended():
                action = default_action
            else:
                script = scripts[sender]
                action = script[tick] if tick < len(script) else default_action
            packet = engine.submit_local(action)
            window = silent.get(sender)
            hidden = window is not None and window[0] <= tick < window[1]
            for receiver in actors:
                if receiver == sender:
                    continue
                if hidden:
                    assert window is not None
                    input_q.append((window[1] + latency, receiver, packet))
                    continue
                if loss > 0.0 and rng.unit() < loss:
                    continue
                deliver = max(tick + 1, tick + latency + jit())
                input_q.append((deliver, receiver, packet))

        for sender in actors:
            engines[sender].advance()

        for sender in actors:
            engine = engines[sender]
            reliable = tick + max(1, latency)
            for hash_packet in engine.outbound_hashes():
                for receiver in actors:
                    if receiver != sender:
                        hash_q.append((reliable, receiver, hash_packet))
            end_packet = engine.announce_end()
            if end_packet is not None and sender not in ended_announced:
                ended_announced.add(sender)
                for receiver in actors:
                    if receiver != sender:
                        end_q.append((reliable, receiver, end_packet))

    for engine in engines.values():
        engine.finalize()
    return engines


def canonical_rows(engine: PeerEngine) -> list[dict[str, object]]:
    """Return the parity-comparable canonical rows of one peer's trajectory."""
    return [record.canonical() for record in engine.canonical_trajectory()]


def assert_parity(engines: Mapping[str, PeerEngine]) -> list[dict[str, object]]:
    """Assert every peer exported the same canonical trajectory, and return it."""
    rows = {actor: canonical_rows(engine) for actor, engine in engines.items()}
    reference_actor = min(rows)
    reference = rows[reference_actor]
    for actor, actor_rows in rows.items():
        assert actor_rows == reference, f"peer {actor} diverged from {reference_actor}"
    return reference


def _script(actor_index: int, length: int) -> list[int]:
    """Build a deterministic, varying action sequence for one peer."""
    return [(tick * 7 + actor_index * 3 + 1) % 3 for tick in range(length)]


# -- the reproduced legacy parity suite ---------------------------------------


def test_two_peers_reach_identical_trajectories_without_loss() -> None:
    """DATA-01. With the delay covering the transport, no peer ever rolls back."""
    actors = (_actor(1), _actor(2))
    scripts = {actors[0]: _script(0, 200), actors[1]: _script(1, 200)}
    engines = run_mesh(
        actors=actors,
        scripts=scripts,
        episode_len=40,
        input_delay=1,
        latency=0,
    )
    trajectory = assert_parity(engines)

    assert len(trajectory) == 40
    for engine in engines.values():
        assert engine.rollback_count() == 0
    # Every frame confirms and its peer hashes agree, so every finality verifies.
    for engine in engines.values():
        statuses = {final.status for final in engine.frame_finalities()}
        assert statuses == {"verified"}


def test_latency_triggers_rollbacks_yet_keeps_parity() -> None:
    """DATA-02 / NET-01. A round trip past the delay predicts and rolls back."""
    actors = (_actor(1), _actor(2))
    scripts = {actors[0]: _script(0, 200), actors[1]: _script(1, 200)}
    engines = run_mesh(
        actors=actors,
        scripts=scripts,
        episode_len=50,
        input_delay=1,
        latency=5,
    )
    trajectory = assert_parity(engines)

    assert len(trajectory) == 50
    assert any(engine.rollback_count() > 0 for engine in engines.values())


def test_input_delay_absorbs_latency_without_rollback() -> None:
    """A delay at least as long as the round trip predicts nothing, so no rollback."""
    actors = (_actor(1), _actor(2))
    scripts = {actors[0]: _script(0, 200), actors[1]: _script(1, 200)}
    engines = run_mesh(
        actors=actors,
        scripts=scripts,
        episode_len=40,
        input_delay=3,
        latency=2,
    )
    assert_parity(engines)
    for engine in engines.values():
        assert engine.rollback_count() == 0


def test_packet_loss_is_recovered_and_parity_holds() -> None:
    """NET-02. Redundant inputs recover the drops, and the exports still match."""
    actors = (_actor(1), _actor(2))
    scripts = {actors[0]: _script(0, 200), actors[1]: _script(1, 200)}
    engines = run_mesh(
        actors=actors,
        scripts=scripts,
        episode_len=60,
        input_delay=2,
        latency=2,
        loss=0.3,
    )
    trajectory = assert_parity(engines)
    assert len(trajectory) == 60


def test_jitter_reorders_inputs_yet_parity_holds() -> None:
    """NET-05. Jittered, reordered delivery is drained in order, so parity holds."""
    actors = (_actor(1), _actor(2))
    scripts = {actors[0]: _script(0, 200), actors[1]: _script(1, 200)}
    engines = run_mesh(
        actors=actors,
        scripts=scripts,
        episode_len=60,
        input_delay=2,
        latency=4,
        jitter=3,
    )
    assert_parity(engines)


def test_a_long_silence_forces_a_deep_rollback_and_still_parity() -> None:
    """The deep-rollback stress test: a silenced peer forces a large replay.

    One peer's inputs are withheld for a long window and flushed at once. The other
    peer predicts through the gap and, on the flush, rolls back deep into the past
    and replays with the corrected inputs. The two exports must still be identical,
    and the rollback perspective (its depth and count) is each peer's own -- proof
    the parity comparison excludes the client-local view, not the canonical data.
    """
    actors = (_actor(1), _actor(2))
    scripts = {actors[0]: _script(0, 200), actors[1]: _script(1, 200)}
    engines = run_mesh(
        actors=actors,
        scripts=scripts,
        episode_len=80,
        input_delay=1,
        latency=1,
        silent={actors[1]: (10, 55)},
    )
    trajectory = assert_parity(engines)

    assert len(trajectory) == 80
    depth = max(engine.max_rollback_depth() for engine in engines.values())
    assert depth >= 40, f"expected a deep rollback, got {depth} frames"
    # The two peers rolled back on their own schedules -- a client-local difference
    # that the identical canonical trajectory rides above.
    counts = {engine.rollback_count() for engine in engines.values()}
    assert len(counts) > 1


def test_focus_loss_at_the_episode_boundary_keeps_parity() -> None:
    """FOCUS-02. A silence straddling the episode end still exports identically.

    The silenced peer's tail inputs arrive after the local episode has already
    ended. The engine keeps confirming and rolling back after its own end, so the
    tail promotes correctly and both peers close on the same minimum end frame.
    """
    actors = (_actor(1), _actor(2))
    scripts = {actors[0]: _script(0, 200), actors[1]: _script(1, 200)}
    engines = run_mesh(
        actors=actors,
        scripts=scripts,
        episode_len=50,
        input_delay=1,
        latency=1,
        silent={actors[1]: (40, 52)},
    )
    trajectory = assert_parity(engines)

    assert len(trajectory) == 50
    boundaries = [engine.episode_boundary() for engine in engines.values()]
    assert {boundary.end_frame_exclusive for boundary in boundaries} == {50}
    assert all(boundary.kind == "terminal" for boundary in boundaries)
    assert all(boundary.p2p_barrier is not None for boundary in boundaries)


def test_three_peer_full_mesh_keeps_parity_under_latency() -> None:
    """A three-peer full mesh reaches one identical trajectory under latency."""
    actors = (_actor(1), _actor(2), _actor(3))
    scripts = {
        actors[0]: _script(0, 200),
        actors[1]: _script(1, 200),
        actors[2]: _script(2, 200),
    }
    engines = run_mesh(
        actors=actors,
        scripts=scripts,
        episode_len=50,
        input_delay=1,
        latency=4,
        loss=0.1,
    )
    trajectory = assert_parity(engines)
    assert len(trajectory) == 50
    assert any(engine.rollback_count() > 0 for engine in engines.values())


def test_the_peer_transitions_and_boundary_carry_the_mesh_identity() -> None:
    """The produced records name the writer, the mesh, and the peer authority."""
    actors = (_actor(1), _actor(2))
    scripts = {actors[0]: _script(0, 200), actors[1]: _script(1, 200)}
    engines = run_mesh(
        actors=actors,
        scripts=scripts,
        episode_len=30,
        input_delay=1,
        latency=3,
    )
    engine = engines[actors[0]]
    transitions = engine.game_transitions()

    assert len(transitions) == 30
    first = transitions[0]
    assert first.authority == "peer"
    assert first.replica_actor_id == actors[0]
    assert first.mesh_membership_digest is not None
    assert first.membership_generation == 1

    boundary = engine.episode_boundary()
    barrier = boundary.p2p_barrier
    assert barrier is not None
    assert barrier.rule == "minimum-end-frame-exclusive"
    assert [entry.peer_actor_id for entry in barrier.peer_end_frames] == list(actors)


# -- the finality state machine, driven directly ------------------------------


def _two_peer_engine() -> tuple[PeerEngine, str, str]:
    """Build one two-peer engine and step two fully confirmed frames."""
    actors = (_actor(1), _actor(2))
    world = LineWorld(actors, seed=7, episode_len=10)
    engine = _build_engine(
        actors[0],
        actors,
        world,
        input_delay=0,
        snapshot_interval=5,
        default_action=1,
        prediction="repeat-last",
        max_steps=10,
    )
    other = actors[1]
    # Deliver the other peer's real inputs for frames 0 and 1 up front, so both
    # frames confirm the moment they step.
    engine.receive_input(InputPacket(sender=other, current_frame=0, inputs=((0, 1),)))
    engine.receive_input(InputPacket(sender=other, current_frame=1, inputs=((1, 2),)))
    engine.submit_local(1)
    engine.advance()
    engine.submit_local(2)
    engine.advance()
    engine.advance()  # confirm and promote frames 0 and 1
    return engine, actors[0], other


def test_a_frame_verifies_when_the_peer_hashes_agree() -> None:
    """A confirmed frame with unanimous peer hashes reaches the verified status."""
    engine, _, other = _two_peer_engine()
    engine.outbound_hashes()  # this peer records its own hash for the frames
    trajectory = engine.canonical_trajectory()
    assert trajectory, "expected at least one confirmed frame"
    frame = trajectory[0]
    engine.receive_hash(
        HashPacket(
            sender=other,
            frame_number=frame.frame_number,
            state_hash=frame.state_hash,
        )
    )

    finality = next(
        final
        for final in engine.frame_finalities()
        if final.frame_number == frame.frame_number
    )
    assert finality.status == "verified"
    assert finality.agreed_state_hash == frame.state_hash


def test_a_frame_disputes_when_the_peer_hashes_disagree() -> None:
    """A confirmed frame with a divergent peer hash reaches the disputed status."""
    engine, _, other = _two_peer_engine()
    engine.outbound_hashes()
    frame = engine.canonical_trajectory()[0]
    engine.receive_hash(
        HashPacket(
            sender=other,
            frame_number=frame.frame_number,
            state_hash=Digest(algorithm="sha-256", hex="0" * 64),
        )
    )

    finality = next(
        final
        for final in engine.frame_finalities()
        if final.frame_number == frame.frame_number
    )
    assert finality.status == "disputed"
    assert finality.agreed_state_hash is None
