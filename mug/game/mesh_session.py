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
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mug.game.bot_authority import BotSeat
from mug.game.keys import Bindings
from mug.game.mesh import EndPacket, PeerEngine, ReplicaFrame
from mug.game.runtime import EpisodeSummary
from mug.game.seams import SeatActionSource
from mug.kernel import Digest, UtcInstant

# A study builds one replica per seat from the frozen peer set and the shared seed.
# The replica exposes ``step``/``snapshot``/``restore`` (a ``MultiAgentReplica``
# does); the coordinator reads those three, so it never names an environment.
MakeReplica = Callable[[tuple[str, ...], int], Any]

# The transport supplies, per seat, the currently held action and a frame sink.
SeatAction = Callable[[], int]
FrameSink = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class MeshBotSpec:
    """One seat in a mesh that no person plays: a study's own policy does.

    ``actor_id`` is the seat the mesh reserves in its frozen peer set, so every
    replica holds it while no engine is built for it. ``controller`` decides its
    action, and exactly one peer -- the authority the ``P2PBotAuthority`` rule
    designates -- ever calls it. That peer broadcasts what it produced, and every
    other peer applies it the way it applies a person's input.

    A peer-to-peer game runs no authoritative server, so a bot with no single
    source would split the trajectory: a policy reading each peer's own
    speculative view would produce a different action on each of them.
    """

    actor_id: str
    seat_key: str
    controller: SeatActionSource


def _no_bots() -> tuple[MeshBotSpec, ...]:
    """Return an empty, typed bot-seat tuple for a mesh default."""
    return ()


def _no_bindings() -> dict[str, int]:
    """Return an empty, typed key-to-action binding map for a mesh default."""
    return {}


@dataclass(frozen=True)
class MeshGameSpec:
    """One peer-to-peer game channel a study supplies for a mesh of seats.

    ``make_replica`` builds one deterministic replica for the frozen peer set and
    the shared seed, so every seat starts identical. ``bots`` are the seats no
    person plays: the mesh reserves each one in its frozen peer set and one
    designated peer produces its action. ``action_bindings`` maps a key to a
    discrete action and ``default_action`` fills a frame with no bound key, the
    same seam the single-seat loop uses. ``size`` is how many people the mesh waits
    for, which is **not** the number of seats once it holds a bot. The engine
    parameters set the input delay, the snapshot cadence, and the step cap the peer
    engines run under.
    """

    channel_key: str
    size: int
    make_replica: MakeReplica
    bots: tuple[MeshBotSpec, ...] = field(default_factory=_no_bots)
    action_bindings: Bindings = field(default_factory=_no_bindings)
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
        # The nodes are the peers that run an engine: one per person. The peer set
        # is the nodes **and** the bot seats, because every replica holds every
        # seat while only a person's node holds a rollback engine.
        self._nodes = tuple(sorted(seat.actor_id for seat in self._seats))
        if len(set(self._nodes)) != len(self._seats):
            raise ValueError("each seat must hold a distinct actor id")
        bot_actors = tuple(bot.actor_id for bot in spec.bots)
        if set(bot_actors) & set(self._nodes) or len(set(bot_actors)) != len(
            bot_actors
        ):
            raise ValueError("each bot seat must hold its own distinct actor id")
        self._peers = tuple(sorted([*self._nodes, *bot_actors]))
        # The authority is the highest eligible peer actor id, which is the rule the
        # frozen ``P2PBotAuthority`` record states. It is derived, so every node
        # agrees on it without being told.
        authority = self._nodes[-1]
        self._bots = tuple(
            BotSeat(
                bot_actor_id=bot.actor_id,
                authority_actor_id=authority,
                controller=bot.controller,
            )
            for bot in spec.bots
        )

        self._engines: dict[str, PeerEngine] = {}
        # What each node's replica last produced, so the authority decides a bot's
        # action from a real observation rather than from a hash of one.
        self._seen: dict[str, _Seen] = {}
        for seat in self._seats:
            replica = spec.make_replica(self._peers, spec.seed)
            seen = _Seen(replica.step)
            self._seen[seat.actor_id] = seen
            self._engines[seat.actor_id] = PeerEngine(
                actor_id=seat.actor_id,
                peer_actor_ids=self._peers,
                interaction_id=interaction_id,
                episode_id=episode_id,
                channel_key=spec.channel_key,
                mesh_membership_digest=mesh_membership_digest,
                membership_generation=membership_generation,
                step=seen,
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
                # The episode's length is fixed, so nothing new is scheduled -- but a
                # peer that has ended keeps repeating what it played until the
                # barrier closes, so a lost tail input can still arrive.
                repeat = engine.resend_recent()
                if repeat is not None:
                    for other in self._nodes:
                        if other != seat.actor_id:
                            self._engines[other].receive_input(repeat)
                continue
            packet = engine.submit_local(int(seat.action()))
            for other in self._nodes:
                if other != seat.actor_id:
                    self._engines[other].receive_input(packet)
        self._relay_bots()

    def _relay_bots(self) -> None:
        """Have the one authority peer produce each bot's action and broadcast it.

        Only the authority calls the study's controller, so a bot contributes one
        action to the mesh however many peers are in it, and every other peer
        applies the broadcast input the way it applies a person's. That single
        source is what keeps a bot from splitting the trajectory.
        """
        for bot in self._bots:
            node = bot.authority_actor_id
            engine = self._engines[node]
            if engine.ended():
                continue
            packet = engine.submit_for(
                bot.bot_actor_id, bot.decide(self._seen[node].observation)
            )
            for other in self._nodes:
                if other != node:
                    self._engines[other].receive_input(packet)

    def _relay_gossip(self) -> None:
        """Relay the confirmed-frame hashes and the end packets between the nodes."""
        for actor in self._nodes:
            engine = self._engines[actor]
            for hash_packet in engine.outbound_hashes():
                for other in self._nodes:
                    if other != actor:
                        self._engines[other].receive_hash(hash_packet)
            end_packet = engine.announce_end()
            if end_packet is not None:
                for other in self._nodes:
                    if other != actor:
                        self._engines[other].receive_end(end_packet)
                self._speak_for_bots(end_packet)

    def _speak_for_bots(self, packet: EndPacket) -> None:
        """Announce each bot's end frame on its authority peer's behalf.

        A bot has no engine, so it proposes no end frame of its own and the
        minimum-end barrier would never close. Its authority speaks for it, and
        says the only true thing there is to say: the bot sits in the authority's
        own replica, so its episode ends on the frame that replica's episode ends
        on. Every node is told, the authority included, because the barrier is a
        statement about the whole peer set rather than about the others.
        """
        for bot in self._bots:
            if bot.authority_actor_id != packet.sender:
                continue
            spoken = EndPacket(
                sender=bot.bot_actor_id,
                end_frame_exclusive=packet.end_frame_exclusive,
            )
            for node in self._nodes:
                self._engines[node].receive_end(spoken)

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
        for _ in range(len(self._nodes) + 2):
            moved = False
            for engine in self._engines.values():
                engine.advance()
            for actor in self._nodes:
                engine = self._engines[actor]
                for hash_packet in engine.outbound_hashes():
                    moved = True
                    for other in self._nodes:
                        if other != actor:
                            self._engines[other].receive_hash(hash_packet)
                end_packet = engine.announce_end()
                if end_packet is not None:
                    for other in self._nodes:
                        if other != actor:
                            self._engines[other].receive_end(end_packet)
                    self._speak_for_bots(end_packet)
            if not moved:
                break

    # -- outputs ----------------------------------------------------------------

    def _all_ended(self) -> bool:
        """Return whether every seat's local episode has ended."""
        return all(engine.ended() for engine in self._engines.values())

    def _build_episode(self) -> MeshEpisode:
        """Build the per-seat summaries and the cross-peer parity verdict."""
        summaries = {actor: self._summary(actor) for actor in self._nodes}
        reference_actor = self._nodes[0]
        reference_rows = _canonical_rows(self._engines[reference_actor])
        verified = all(
            _canonical_rows(self._engines[actor]) == reference_rows
            for actor in self._nodes
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


class _Seen:
    """Remember the observation one node's replica last produced.

    The engine hashes an observation and does not keep it, which is right for the
    parity comparison and wrong for a policy that has to read the game. This wraps
    the replica's step so the authority peer decides a bot's action from what its
    own replica just produced -- including a speculative frame, which is exactly
    why only one peer is allowed to decide.
    """

    def __init__(self, step: Callable[[Mapping[str, int]], ReplicaFrame]) -> None:
        self._step = step
        self.observation: Any = None

    def __call__(self, actions: Mapping[str, int]) -> ReplicaFrame:
        frame = self._step(actions)
        self.observation = frame.observation
        return frame


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
    "MeshBotSpec",
    "MeshEpisode",
    "MeshGameSpec",
    "MeshSession",
    "SeatAction",
    "SeatWiring",
    "make_replica_frame",
]
