"""A mesh of peers, a network that misbehaves on purpose, and the true trajectory.

The existing rollback tests compare every peer against every other peer. That proves
the mesh **converges**, which is necessary and is not the same as being right: a
rollback that reconstructed the wrong frames in the same way on every replica would
satisfy it exactly.

So this adds the missing half -- what the run *should* have been. Because the input
schedule is known in full, the true trajectory can be computed by stepping one bare
replica with the complete, correct action set for every frame, using no engine, no
prediction, and no rollback at all. Every peer must then match that, under whatever
the network did.

The schedule is a property of the engine's symmetric input delay: frames before
``input_delay`` are seeded with the default action on every peer, and frame ``f``
afterwards carries the action each peer submitted at its own tick ``f - input_delay``.
Nothing here guesses that; it is what ``PeerEngine`` does, stated once.

The network is seeded, so a failure reproduces exactly rather than "sometimes".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mug.game.determinism import state_hash
from mug.game.mesh import (
    EndPacket,
    HashPacket,
    InputPacket,
    PeerEngine,
    ReplicaFrame,
)

DEFAULT_ACTION = 0

_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000020f"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000020e"
_RECORDED_AT = "2026-07-28T00:00:00.000000Z"


def actor(index: int) -> str:
    """Return the canonical actor id for one peer index."""
    return f"actor_019b6000-0000-7000-8000-0000000002{index:02x}"


def script_for(index: int, length: int) -> list[int]:
    """Return one peer's fixed action sequence, by the rule that defines it.

    Varying and co-prime-ish across peers, so two seats rarely submit the same
    action on the same tick -- a mesh where everyone always agrees would hide a
    rollback that resolved conflicts wrongly.
    """
    return [(tick * 7 + index * 3 + 1) % 3 for tick in range(length)]


class Rng:
    """A seeded generator, so a scenario that fails fails the same way next time."""

    def __init__(self, seed: int) -> None:
        self._state = (seed * 6364136223846793005 + 1442695040888963407) % (2**64)

    def unit(self) -> float:
        """Return the next value in [0, 1)."""
        self._state = (self._state * 6364136223846793005 + 1442695040888963407) % (
            2**64
        )
        return (self._state >> 11) / float(1 << 53)

    def below(self, bound: int) -> int:
        """Return the next whole number below ``bound``."""
        return int(self.unit() * bound) if bound > 0 else 0


class LineWorld:
    """A deterministic multi-seat replica whose state depends on all of history.

    Every step moves each seat by its own action and by a shared noise term drawn
    from a generator carried in the state. So a rollback that restored the positions
    but not the generator diverges immediately, which is what makes parity under deep
    rollback evidence that the snapshot covers what API-07 says it must.
    """

    def __init__(self, seats: Sequence[str]) -> None:
        self._seats = list(seats)
        self.positions = dict.fromkeys(self._seats, 0)
        self.step_count = 0
        self.noise = 12345

    def step(self, actions: Mapping[str, int]) -> ReplicaFrame:
        """Step one frame and return what the replica answered."""
        self.noise = (self.noise * 1103515245 + 12345) % 2147483648
        drift = self.noise % 3
        for seat in self._seats:
            self.positions[seat] = (
                self.positions[seat] + int(actions.get(seat, 0)) + drift
            ) % 1000
        self.step_count += 1
        return ReplicaFrame(
            observation=[float(self.positions[seat]) for seat in self._seats],
            rewards={seat: float(self.positions[seat] % 7) for seat in self._seats},
            terminated=False,
            truncated=False,
            info={"step": self.step_count, "drift": drift},
        )

    def snapshot(self) -> object:
        """Return an opaque snapshot covering the positions, the step, and the rng."""
        return (tuple(sorted(self.positions.items())), self.step_count, self.noise)

    def restore(self, snapshot: object) -> None:
        """Restore everything the snapshot covers."""
        positions, step_count, noise = snapshot  # type: ignore[misc]
        self.positions = dict(positions)
        self.step_count = int(step_count)
        self.noise = int(noise)


def true_actions(
    actors: Sequence[str],
    scripts: Mapping[str, Sequence[int]],
    frame: int,
    input_delay: int,
) -> dict[str, int]:
    """Return the action set frame ``frame`` must step, with perfect information."""
    if frame < input_delay:
        return dict.fromkeys(actors, DEFAULT_ACTION)
    tick = frame - input_delay
    return {
        one: (scripts[one][tick] if tick < len(scripts[one]) else DEFAULT_ACTION)
        for one in actors
    }


def oracle_rows(
    actors: Sequence[str],
    scripts: Mapping[str, Sequence[int]],
    frames: int,
    *,
    input_delay: int,
) -> list[dict[str, Any]]:
    """Return the trajectory the mesh must produce, computed without the mesh.

    One bare replica, stepped with the complete action set for every frame. No
    engine, no prediction, no rollback, no network -- so agreeing with this is a
    statement about what the run *was*, not about what the peers agreed on.
    """
    world = LineWorld(actors)
    rows: list[dict[str, Any]] = []
    for frame in range(frames):
        actions = true_actions(actors, scripts, frame, input_delay)
        result = world.step(actions)
        rows.append(
            {
                "frame_number": frame,
                "actions": dict(sorted(actions.items())),
                "rewards": {
                    key: float(result.rewards[key]) for key in sorted(result.rewards)
                },
                "terminated": result.terminated,
                "truncated": result.truncated,
                "info": result.info,
                "state_hash": state_hash(result.observation).hex,
            }
        )
    return rows


@dataclass(frozen=True)
class Conditions:
    """What the network does to the packets between the peers.

    Every field is a way a real peer-to-peer connection misbehaves. ``partitions``
    cuts a peer off entirely for a window of ticks, which is the shape of a laptop
    lid closing or a phone changing network -- its inputs arrive late and all at
    once, which is what forces the deepest rollbacks.
    """

    latency: int = 0
    jitter: int = 0
    loss: float = 0.0
    # (first tick, last tick exclusive) windows during which a peer sends nothing.
    partitions: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    seed: int = 20260728

    def label(self) -> str:
        """A short name for the scenario, for a test id."""
        parts = [f"latency={self.latency}", f"jitter={self.jitter}"]
        if self.loss:
            parts.append(f"loss={self.loss}")
        if self.partitions:
            parts.append(f"cut={len(self.partitions)}")
        return ",".join(parts)


@dataclass
class Outcome:
    """What one run of the bench produced."""

    engines: dict[str, PeerEngine]
    rows: dict[str, list[dict[str, Any]]]
    rollbacks: dict[str, int]
    deepest: dict[str, int]

    def any_rollback(self) -> int:
        """How many rollbacks the busiest peer performed."""
        return max(self.rollbacks.values(), default=0)


def run_mesh(
    peers: int,
    *,
    frames: int,
    conditions: Conditions,
    input_delay: int = 2,
    snapshot_interval: int = 5,
    extra_ticks: int = 40,
    corrupt: str | None = None,
) -> Outcome:
    """Play one episode across ``peers`` replicas over a misbehaving network.

    ``corrupt`` starts one peer's replica from a different generator state, the way a
    wrong seed or a restore that missed something would. That peer then plays a
    self-consistent run that is not the mesh's, which is what the hash exchange is
    for -- and what desync repair has to put right.
    """
    actors = [actor(index) for index in range(peers)]
    scripts = {one: script_for(index, frames) for index, one in enumerate(actors)}
    rng = Rng(conditions.seed)

    # Each engine drives its own replica, bound to its own three callables.
    engines: dict[str, PeerEngine] = {}
    for one in actors:
        world = LineWorld(actors)
        if one == corrupt:
            world.noise = 999983
        engines[one] = PeerEngine(
            actor_id=one,
            peer_actor_ids=tuple(actors),
            interaction_id=_INTERACTION,
            episode_id=_EPISODE,
            channel_key="bench",
            mesh_membership_digest=state_hash(list(actors)),
            membership_generation=1,
            recorded_at=_RECORDED_AT,
            max_steps=frames,
            step=world.step,
            snapshot=world.snapshot,
            restore=world.restore,
            input_delay=input_delay,
            snapshot_interval=snapshot_interval,
            default_action=DEFAULT_ACTION,
            prediction="repeat-last",
        )

    input_q: list[tuple[int, str, InputPacket]] = []
    hash_q: list[tuple[int, str, HashPacket]] = []
    end_q: list[tuple[int, str, EndPacket]] = []
    announced: set[str] = set()
    longest_cut = max(
        (window[1] for window in conditions.partitions.values()), default=0
    )
    ticks = frames + conditions.latency + longest_cut + extra_ticks

    for tick in range(ticks):
        for due, receiver, packet in input_q:
            if due == tick:
                engines[receiver].receive_input(packet)
        for due, receiver, hashes in hash_q:
            if due == tick:
                engines[receiver].receive_hash(hashes)
        for due, receiver, ending in end_q:
            if due == tick:
                engines[receiver].receive_end(ending)

        for sender in actors:
            engine = engines[sender]
            script = scripts[sender]
            # A peer that has ended schedules nothing new and repeats what it played,
            # which is exactly what every real driver does. The bench used to call
            # ``submit_local`` unconditionally, so it kept scheduling inputs past the
            # end of the episode -- and that made the tail **better** protected here
            # than in a browser. The one place the engine could export a prediction
            # was the one place this bench could not reach.
            if engine.ended():
                repeat = engine.resend_recent()
                if repeat is None:
                    continue
                packet = repeat
            else:
                action = DEFAULT_ACTION if tick >= len(script) else script[tick]
                packet = engine.submit_local(action)
            window = conditions.partitions.get(sender)
            cut = window is not None and window[0] <= tick < window[1]
            for receiver in actors:
                if receiver == sender:
                    continue
                if cut:
                    # Nothing leaves while the peer is away; it all arrives at once
                    # when the connection comes back.
                    assert window is not None
                    input_q.append((window[1] + conditions.latency, receiver, packet))
                    continue
                if conditions.loss > 0.0 and rng.unit() < conditions.loss:
                    continue
                wobble = (
                    rng.below(2 * conditions.jitter + 1) - conditions.jitter
                    if conditions.jitter
                    else 0
                )
                due = max(tick + 1, tick + conditions.latency + wobble)
                input_q.append((due, receiver, packet))

        for sender in actors:
            engines[sender].advance()

        for sender in actors:
            engine = engines[sender]
            reliable = tick + max(1, conditions.latency)
            for hashes in engine.outbound_hashes():
                for receiver in actors:
                    if receiver != sender:
                        hash_q.append((reliable, receiver, hashes))
            ending = engine.announce_end()
            if ending is not None and sender not in announced:
                announced.add(sender)
                for receiver in actors:
                    if receiver != sender:
                        end_q.append((reliable, receiver, ending))

    for engine in engines.values():
        engine.finalize()
    return Outcome(
        engines=engines,
        rows={
            one: [record.canonical() for record in engine.canonical_trajectory()]
            for one, engine in engines.items()
        },
        rollbacks={one: engine.rollback_count() for one, engine in engines.items()},
        deepest={one: engine.max_rollback_depth() for one, engine in engines.items()},
    )


def assert_agrees_with_the_oracle(
    outcome: Outcome, *, frames: int, input_delay: int
) -> None:
    """Every peer produced the same trajectory, and it is the true one."""
    actors = sorted(outcome.rows)
    scripts = {one: script_for(index, frames) for index, one in enumerate(actors)}

    reference = outcome.rows[actors[0]]
    for one in actors[1:]:
        assert outcome.rows[one] == reference, (
            f"peer {one} diverged from {actors[0]}: the mesh did not converge"
        )

    truth = oracle_rows(actors, scripts, len(reference), input_delay=input_delay)
    assert reference == truth, (
        "every peer agreed on a trajectory that is not the one the inputs imply; "
        "the mesh converged on the wrong answer"
    )


__all__ = [
    "DEFAULT_ACTION",
    "Conditions",
    "LineWorld",
    "Outcome",
    "Rng",
    "actor",
    "assert_agrees_with_the_oracle",
    "oracle_rows",
    "run_mesh",
    "script_for",
    "true_actions",
]
