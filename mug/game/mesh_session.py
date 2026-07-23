"""Drive a mesh of peer engines through one episode (API-07).

The rollback engine (``mug.game.mesh``) drives one peer. This module drives the
whole mesh: it holds one ``PeerEngine`` per seat over that seat's own replica, and
each tick it reads every seat's held action, relays the inputs across the mesh,
steps every engine, exchanges the hash and end packets, and pushes one frame to
each seat. When every seat's episode has ended it settles the mesh, closes the
barrier, and reports one ``EpisodeSummary`` per seat.

The module owns the server-hosted mesh. It hosts every peer's engine in one place
and relays the packets between them, so a real deployment runs it with no WebRTC
and no browser. The relay here delivers every packet the same tick, so no engine
predicts and no rollback fires; the rollback path is proven where latency and loss
are injected (``tests/unit/game/test_p2p_rollback.py``). A later tier moves each
engine to its own peer process and relays the packets over the wire, at which
point the round trip drives the prediction and rollback the engine already owns.

The coordinator is environment-neutral and transport-neutral. The study supplies a
``MeshGameSpec`` that builds one replica per seat (for a PettingZoo parallel
environment the replica is a ``MultiAgentReplica``); the transport supplies, per
seat, the held action and a frame sink. So a test drives the whole episode with a
scripted action and a collecting sink, with no socket and no real clock.

Every seat runs its own engine over its own replica, so the exported canonical
trajectories must be byte-identical. The coordinator verifies that before it
reports, and it names the reference peer whose run the caller captures once for the
whole mesh. A divergence (an environment that draws from an uncovered generator,
say) surfaces as ``verified == False`` rather than a silently split record.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from mug.game.mesh import PeerEngine, ReplicaFrame
from mug.game.runtime import EpisodeSummary
from mug.kernel import Digest, UtcInstant

# A study builds one replica per seat from the frozen peer set and the shared seed.
# The replica exposes ``step``/``snapshot``/``restore`` (a ``MultiAgentReplica``
# does); the coordinator reads those three, so it never names an environment.
MakeReplica = Callable[[tuple[str, ...], int], Any]

# The transport supplies, per seat, the currently held action and a frame sink.
SeatAction = Callable[[], int]
FrameSink = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class MeshGameSpec:
    """One peer-to-peer game channel a study supplies for a mesh of seats.

    ``make_replica`` builds one deterministic replica for the frozen peer set and
    the shared seed, so every seat starts identical. ``action_bindings`` maps a key
    to a discrete action and ``default_action`` fills a frame with no bound key, the
    same seam the single-seat loop uses. ``size`` is the number of seats the mesh
    forms. The engine parameters set the input delay, the snapshot cadence, and the
    step cap the peer engines run under.
    """

    channel_key: str
    size: int
    make_replica: MakeReplica
    action_bindings: dict[str, int]
    default_action: int = 0
    seed: int = 0
    fps: int = 30
    max_steps: int = 200
    input_delay: int = 2
    snapshot_interval: int = 5


@dataclass(frozen=True)
class SeatWiring:
    """One seat's binding into the mesh: its identity, its input, and its sink.

    ``action`` returns the seat's currently held action each tick (the transport
    updates it from the seat's input frames); ``send`` pushes one frame to the seat.
    """

    seat_key: str
    actor_id: str
    action: SeatAction
    send: FrameSink


@dataclass(frozen=True)
class MeshEpisode:
    """The outcome of one mesh episode: the per-seat runs and the parity verdict.

    ``summaries`` holds one ``EpisodeSummary`` per actor id. ``verified`` is true
    when every seat exported the identical canonical trajectory. ``reference_actor``
    names the peer whose summary the caller captures once for the whole mesh, and
    ``frames`` is the agreed frame count.
    """

    summaries: dict[str, EpisodeSummary]
    verified: bool
    reference_actor: str
    frames: int

    def reference_summary(self) -> EpisodeSummary:
        """Return the reference peer's summary, the one run the mesh captures."""
        return self.summaries[self.reference_actor]


class MeshSession:
    """Host one peer engine per seat and drive them through one episode.

    The session builds one ``PeerEngine`` over one replica per seat, all bound to
    the frozen mesh: the same peer set, mesh digest, interaction, episode, and
    channel. Its ``run`` steps the mesh to the shared end-frame barrier and returns
    the per-seat summaries.
    """

    def __init__(
        self,
        *,
        seats: Sequence[SeatWiring],
        spec: MeshGameSpec,
        interaction_id: str,
        episode_id: str,
        mesh_membership_digest: Digest,
        membership_generation: int,
        recorded_at: UtcInstant,
    ) -> None:
        if len(seats) < 2:
            raise ValueError("a peer mesh needs at least two seats")
        self._seats = tuple(seats)
        self._spec = spec
        self._channel_key = spec.channel_key
        self._episode_id = episode_id
        self._peers = tuple(sorted(seat.actor_id for seat in self._seats))
        if len(set(self._peers)) != len(self._seats):
            raise ValueError("each seat must hold a distinct actor id")

        self._engines: dict[str, PeerEngine] = {}
        for seat in self._seats:
            replica = spec.make_replica(self._peers, spec.seed)
            self._engines[seat.actor_id] = PeerEngine(
                actor_id=seat.actor_id,
                peer_actor_ids=self._peers,
                interaction_id=interaction_id,
                episode_id=episode_id,
                channel_key=spec.channel_key,
                mesh_membership_digest=mesh_membership_digest,
                membership_generation=membership_generation,
                step=replica.step,
                snapshot=replica.snapshot,
                restore=replica.restore,
                recorded_at=recorded_at,
                input_delay=spec.input_delay,
                snapshot_interval=spec.snapshot_interval,
                default_action=spec.default_action,
                max_steps=spec.max_steps,
            )

    async def run(self) -> MeshEpisode:
        """Step the mesh to the end-frame barrier and report the per-seat runs.

        Each tick relays every seat's input across the mesh, advances every engine,
        exchanges the hash and end packets, and pushes one frame to each seat. The
        loop ends once every engine's local episode has ended; a step cap bounds a
        replica that never terminates. It then settles the outstanding packets,
        finalizes the barrier, and builds the summaries.
        """
        fps = self._spec.fps
        frame = 0
        while not self._all_ended() and frame <= self._spec.max_steps:
            self._relay_inputs()
            for engine in self._engines.values():
                engine.advance()
            self._relay_gossip()
            await self._push_frame(frame)
            frame += 1
            if fps > 0:
                await asyncio.sleep(1 / fps)

        self._settle()
        for engine in self._engines.values():
            engine.finalize()
        return self._build_episode()

    # -- the per-tick mesh work -------------------------------------------------

    def _relay_inputs(self) -> None:
        """Submit each active seat's held action and relay the packet to the mesh."""
        for seat in self._seats:
            engine = self._engines[seat.actor_id]
            if engine.ended():
                continue
            packet = engine.submit_local(int(seat.action()))
            for other in self._peers:
                if other != seat.actor_id:
                    self._engines[other].receive_input(packet)

    def _relay_gossip(self) -> None:
        """Relay the confirmed-frame hashes and the end packets across the mesh."""
        for actor in self._peers:
            engine = self._engines[actor]
            for hash_packet in engine.outbound_hashes():
                for other in self._peers:
                    if other != actor:
                        self._engines[other].receive_hash(hash_packet)
            end_packet = engine.announce_end()
            if end_packet is not None:
                for other in self._peers:
                    if other != actor:
                        self._engines[other].receive_end(end_packet)

    async def _push_frame(self, frame: int) -> None:
        """Push one frame view to every seat from its own engine's perspective."""
        for seat in self._seats:
            engine = self._engines[seat.actor_id]
            trajectory = engine.canonical_trajectory()
            latest = trajectory[-1].canonical() if trajectory else None
            await seat.send(
                {
                    "type": "frame",
                    "episode_id": self._episode_id,
                    "seat_key": seat.seat_key,
                    "frame_number": frame,
                    "confirmed": latest,
                }
            )

    def _settle(self) -> None:
        """Relay the remaining hashes and end packets until the mesh is quiet.

        The final ticks leave a seat's last hashes and its end packet undelivered.
        This drains them, advancing every engine so a late input still promotes,
        until no engine emits a new packet, so every engine holds every peer's end
        frame before the barrier closes.
        """
        for _ in range(len(self._peers) + 2):
            moved = False
            for engine in self._engines.values():
                engine.advance()
            for actor in self._peers:
                engine = self._engines[actor]
                for hash_packet in engine.outbound_hashes():
                    moved = True
                    for other in self._peers:
                        if other != actor:
                            self._engines[other].receive_hash(hash_packet)
                end_packet = engine.announce_end()
                if end_packet is not None:
                    for other in self._peers:
                        if other != actor:
                            self._engines[other].receive_end(end_packet)
            if not moved:
                break

    # -- outputs ----------------------------------------------------------------

    def _all_ended(self) -> bool:
        """Return whether every seat's local episode has ended."""
        return all(engine.ended() for engine in self._engines.values())

    def _build_episode(self) -> MeshEpisode:
        """Build the per-seat summaries and the cross-peer parity verdict."""
        summaries = {
            actor: self._summary(actor) for actor in self._peers
        }
        reference_actor = self._peers[0]
        reference_rows = _canonical_rows(self._engines[reference_actor])
        verified = all(
            _canonical_rows(self._engines[actor]) == reference_rows
            for actor in self._peers
        )
        frames = len(reference_rows)
        return MeshEpisode(
            summaries=summaries,
            verified=verified,
            reference_actor=reference_actor,
            frames=frames,
        )

    def _summary(self, actor: str) -> EpisodeSummary:
        """Build one seat's episode summary from its finalized engine."""
        engine = self._engines[actor]
        boundary = engine.episode_boundary()
        transitions = engine.game_transitions()
        return EpisodeSummary(
            channel_key=self._channel_key,
            seat_key=actor,
            frames=len(transitions),
            transitions=transitions,
            boundary=boundary,
            solved=boundary.kind == "terminal",
        )


def _canonical_rows(engine: PeerEngine) -> list[dict[str, object]]:
    """Return the parity-comparable canonical rows of one peer's trajectory."""
    return [record.canonical() for record in engine.canonical_trajectory()]


def make_replica_frame(
    observation: Any,
    *,
    rewards: dict[str, float],
    terminated: bool,
    truncated: bool,
    info: Any = None,
) -> ReplicaFrame:
    """Build one replica frame; a convenience a study replica may reuse."""
    return ReplicaFrame(
        observation=observation,
        rewards=rewards,
        terminated=terminated,
        truncated=truncated,
        info=info,
    )


__all__ = [
    "FrameSink",
    "MakeReplica",
    "MeshEpisode",
    "MeshGameSpec",
    "MeshSession",
    "SeatAction",
    "SeatWiring",
    "make_replica_frame",
]
