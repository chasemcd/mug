"""The deterministic peer-to-peer rollback engine for one mesh replica (API-07).

A peer-to-peer game runs no authoritative server env. Every peer steps its own
deterministic replica of the same environment and exchanges one input per frame
over a lossy, unordered mesh. This module is one peer's engine. It buffers inputs,
predicts a missing peer input, steps its replica, and -- when a late real input
contradicts a prediction -- rolls the replica back to a snapshot and replays the
frames with the corrected input. The recorded canonical trajectory is therefore
identical on every peer, even though each peer predicts and rolls back on its own
schedule.

The engine owns the GGPO rollback contract the frozen records pin (``mug.game.types``):

- ``P2PFrameFinality`` is the per-frame state machine. A frame is ``speculative``
  until every peer's real input is known (``confirmed``); it is ``verified`` once
  every peer's state hash is known and unanimous, or ``disputed`` when the hashes
  disagree.
- ``EpisodeBoundary.p2p_barrier`` ends the episode on the exclusive minimum of the
  peer end frames, so every peer exports the same frame range.
- ``GameTransition`` carries the per-replica writer identity (``replica_actor_id``,
  the frozen mesh digest, and its generation) under ``authority == "peer"``.

The engine is environment-neutral and transport-neutral. The study supplies the
replica behind three callables (step, snapshot, restore); the mesh transport
supplies the packets. A test drives it with a scripted input, a deterministic
fake replica, and an in-process mesh, with no real clock and no socket.

Two invariants make the canonical trajectory peer-identical, and they are the
correctness core:

- prediction only ever affects the speculative buffer, which is client-local and
  never exported. A frame reaches the canonical buffer only after it is confirmed
  (every peer's real input is known), by which point any wrong prediction has
  already forced a rollback that re-recorded it from the real inputs.
- a snapshot restores the whole replica -- the environment and every random-number
  generator -- so a replay reproduces the exact state the confirmed inputs imply
  (API-07 ``P2PSnapshotCoverage``). The study's snapshot callable owns that
  coverage; the engine only decides when to snapshot and when to restore.

Bot seats, the designated-peer bot authority, and desync repair stay out of this
slice. The engine records a ``disputed`` frame when peer hashes disagree; it does
not yet repair one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from mug.game.determinism import state_hash
from mug.game.types import (
    EpisodeBoundary,
    GameTransition,
    P2PEpisodeBarrier,
    P2PFrameFinality,
    P2PPeerAction,
    P2PPeerEndFrame,
    P2PPeerHashEvidence,
)
from mug.kernel import Digest, UtcInstant

Prediction = Literal["repeat-last", "default-action"]


@dataclass(frozen=True)
class ReplicaFrame:
    """The outcome of stepping the replica one frame: state, rewards, and flags.

    ``observation`` is a json-able value the engine hashes for the mesh agreement.
    ``rewards`` and ``info`` are recorded on the canonical trajectory. The replica
    reports its own terminal and truncation, so the engine never names an
    environment.
    """

    observation: Any
    rewards: Mapping[str, float]
    terminated: bool
    truncated: bool
    info: Any = None


# The replica seam: step one action set, snapshot the whole replica, restore it.
# A snapshot is opaque to the engine; the study's snapshot must cover the
# environment and every random-number generator so a replay is exact.
StepFn = Callable[[Mapping[str, int]], ReplicaFrame]
SnapshotFn = Callable[[], object]
RestoreFn = Callable[[object], None]


@dataclass(frozen=True)
class InputPacket:
    """One peer's inputs for recent frames, sent every frame with redundancy.

    The packet repeats the last few frames of the sender's input, so a dropped
    packet is recovered by the next one without a request. ``current_frame`` is the
    sender's frame at send time; the engine reads only ``inputs``.
    """

    sender: str
    current_frame: int
    inputs: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class HashPacket:
    """One peer's state hash for one confirmed frame, for mesh verification."""

    sender: str
    frame_number: int
    state_hash: Digest


@dataclass(frozen=True)
class EndPacket:
    """One peer's proposed episode end frame, for the minimum-end-frame barrier."""

    sender: str
    end_frame_exclusive: int


@dataclass(frozen=True)
class FrameRecord:
    """One recorded frame of the trajectory: its canonical and client-local parts.

    The canonical parts (``frame_number``, ``actions``, ``rewards``, ``terminated``,
    ``truncated``, ``info``, ``state_hash``) are the consequence of the confirmed
    inputs and the deterministic replica, so they are identical on every peer. The
    client-local parts (``was_speculative``, ``predicted_peers``) record this peer's
    own rollback perspective and are excluded from the parity comparison.
    """

    frame_number: int
    actions: dict[str, int]
    rewards: dict[str, float]
    terminated: bool
    truncated: bool
    info: Any
    state_hash: Digest
    was_speculative: bool = False
    predicted_peers: frozenset[str] = frozenset()

    def canonical(self) -> dict[str, Any]:
        """Return only the peer-identical fields, for the parity comparison."""
        return {
            "frame_number": self.frame_number,
            "actions": dict(sorted(self.actions.items())),
            "rewards": {k: self.rewards[k] for k in sorted(self.rewards)},
            "terminated": self.terminated,
            "truncated": self.truncated,
            "info": self.info,
            "state_hash": self.state_hash.hex,
        }


def _action_digest(action: int) -> Digest:
    """Return the mesh-comparable digest of one peer's action for a frame."""
    return state_hash(action)


class PeerEngine:
    """One peer's rollback engine over a deterministic replica of the mesh env.

    The engine drives one peer: it schedules the local input with the symmetric
    input delay, predicts the missing peer inputs, steps the replica, and rolls
    back and replays when a late real input contradicts a prediction. It records
    the speculative frames as they step and promotes them to the canonical
    trajectory once they are confirmed. The frozen peer set and the mesh digest are
    fixed for the episode.
    """

    def __init__(
        self,
        *,
        actor_id: str,
        peer_actor_ids: tuple[str, ...],
        interaction_id: str,
        episode_id: str,
        channel_key: str,
        mesh_membership_digest: Digest,
        membership_generation: int,
        step: StepFn,
        snapshot: SnapshotFn,
        restore: RestoreFn,
        recorded_at: UtcInstant,
        input_delay: int = 0,
        snapshot_interval: int = 5,
        default_action: int = 0,
        prediction: Prediction = "repeat-last",
        redundancy: int = 10,
        max_steps: int = 200,
    ) -> None:
        if actor_id not in peer_actor_ids:
            raise ValueError("the peer must appear in its own frozen peer set")
        if tuple(sorted(peer_actor_ids)) != peer_actor_ids:
            raise ValueError("the frozen peer set must be in canonical sorted order")
        if snapshot_interval < 1:
            raise ValueError("the snapshot interval must be at least one frame")

        self._actor_id = actor_id
        self._peers = peer_actor_ids
        self._interaction_id = interaction_id
        self._episode_id = episode_id
        self._channel_key = channel_key
        self._mesh_digest = mesh_membership_digest
        self._generation = membership_generation
        self._step = step
        self._snapshot = snapshot
        self._restore = restore
        self._recorded_at = recorded_at
        self._input_delay = input_delay
        self._snapshot_interval = snapshot_interval
        self._default_action = default_action
        self._prediction = prediction
        self._redundancy = redundancy
        self._max_steps = max_steps

        self._frame = 0
        self._inputs: dict[int, dict[str, int]] = {}
        self._predicted_actions: dict[int, dict[str, int]] = {}
        self._snapshots: dict[int, object] = {}
        self._last_real: dict[str, int] = {}
        self._local_history: dict[str, list[tuple[int, int]]] = {}
        self._speculative: dict[int, FrameRecord] = {}
        self._canonical: dict[int, FrameRecord] = {}
        self._confirmed = -1
        self._promoted = -1
        self._pending_rollback: int | None = None
        self._ended = False
        self._end_frame: int | None = None
        self._peer_ends: dict[str, int] = {}
        self._hash_evidence: dict[int, dict[str, Digest]] = {}
        self._sent_hashes: set[int] = set()
        self._rollback_count = 0
        self._max_rollback_depth = 0
        self._repair_count = 0
        self._final_end_frame: int | None = None

        # The symmetric input delay leaves the opening frames with no real input on
        # any peer. Every peer seeds those frames with the default action, so they
        # are agreed, not predicted, and confirmation can advance past them.
        for frame in range(self._input_delay):
            self._inputs[frame] = dict.fromkeys(self._peers, self._default_action)

    # -- local input and the outbound packets ----------------------------------

    def submit_local(self, action: int) -> InputPacket:
        """Schedule the local input at ``frame + input_delay`` and build a packet.

        The delayed input reaches the peers before the delayed frame steps, so a
        peer with a round trip inside the delay never predicts. The packet repeats
        the last ``redundancy`` local inputs, so a single dropped packet recovers.
        """
        return self._submit_input(self._actor_id, action)

    def submit_for(self, actor_id: str, action: int) -> InputPacket:
        """Schedule a bot seat's input this node holds authority over, and pack it.

        A bot seat has no human and no engine of its own: exactly one peer -- the one
        the ``P2PBotAuthority`` record designates -- produces its action each frame
        and broadcasts it, and every other peer applies the broadcast action rather
        than recomputing it. That single source is what keeps the bot's contribution
        deterministic across the mesh, even when the authority decides from its own
        speculative view. The caller enforces the authority; the engine records the
        input for the named seat exactly as it records a peer's.
        """
        if actor_id == self._actor_id:
            raise ValueError("use submit_local for the node's own seat")
        if actor_id not in self._peers:
            raise ValueError("submit_for a seat in the frozen peer set")
        return self._submit_input(actor_id, action)

    def _submit_input(self, actor: str, action: int) -> InputPacket:
        """Schedule one locally-sourced seat's input and build its redundant packet."""
        target = self._frame + self._input_delay
        self._inputs.setdefault(target, {})[actor] = action
        self._last_real[actor] = action
        history = self._local_history.setdefault(actor, [])
        history.append((target, action))
        recent = tuple(history[-self._redundancy :])
        return InputPacket(sender=actor, current_frame=self._frame, inputs=recent)

    def receive_input(self, packet: InputPacket) -> None:
        """Store a peer's inputs and arm a rollback if one contradicts a prediction.

        A duplicate input is ignored. A real input for a frame this peer already
        stepped with a prediction, and that differs from the prediction, arms a
        rollback to the earliest such frame. The rollback runs at the next step.
        """
        if packet.sender == self._actor_id:
            return
        for frame, action in packet.inputs:
            known = self._inputs.setdefault(frame, {})
            if packet.sender in known:
                continue
            known[packet.sender] = action
            predicted = self._predicted_actions.get(frame, {})
            if (
                frame < self._frame
                and packet.sender in predicted
                and predicted[packet.sender] != action
            ):
                self._pending_rollback = (
                    frame
                    if self._pending_rollback is None
                    else min(self._pending_rollback, frame)
                )

    # -- the per-frame step ----------------------------------------------------

    def advance(self) -> None:
        """Roll back if armed, confirm, promote, then step one frame.

        The engine executes any pending rollback first, so the replay corrects the
        speculative frames before this frame steps. It then advances the confirmed
        frame and promotes every newly confirmed frame to the canonical trajectory.
        The confirm, promote, and rollback work runs every call, even after the
        local episode has ended, so the tail frames promote as their late inputs
        arrive. Only the step is gated on the episode still running.
        """
        if self._pending_rollback is not None:
            self._perform_rollback(self._pending_rollback)
            self._pending_rollback = None

        self._update_confirmed()
        self._promote_confirmed()

        if self._ended:
            return
        if self._frame >= self._max_steps:
            self._finish(self._frame)
            return

        actions, predicted = self._resolve_actions(self._frame)
        self._maybe_snapshot(self._frame)
        result = self._step(actions)
        self._speculative[self._frame] = self._record(
            self._frame, actions, predicted, result
        )
        if result.terminated or result.truncated:
            self._finish(self._frame + 1)
        self._frame += 1

    def _finish(self, end_frame_exclusive: int) -> None:
        """Mark the local episode ended at the given exclusive end frame."""
        if self._ended:
            return
        self._ended = True
        self._end_frame = end_frame_exclusive
        self._peer_ends[self._actor_id] = end_frame_exclusive

    def _resolve_actions(self, frame: int) -> tuple[dict[str, int], frozenset[str]]:
        """Resolve every peer's action for a frame, predicting the missing ones."""
        known = self._inputs.get(frame, {})
        resolved: dict[str, int] = {}
        predicted: set[str] = set()
        for peer in self._peers:
            if peer in known:
                resolved[peer] = known[peer]
            else:
                resolved[peer] = self._predict(peer)
                predicted.add(peer)
        if predicted:
            self._predicted_actions[frame] = {
                peer: resolved[peer] for peer in predicted
            }
        else:
            self._predicted_actions.pop(frame, None)
        for peer, action in known.items():
            self._last_real[peer] = action
        return resolved, frozenset(predicted)

    def _predict(self, peer: str) -> int:
        """Predict a missing peer input: repeat its last real input, or default."""
        if self._prediction == "repeat-last":
            return self._last_real.get(peer, self._default_action)
        return self._default_action

    def _maybe_snapshot(self, frame: int) -> None:
        """Snapshot the whole replica before a step on the snapshot cadence."""
        if frame % self._snapshot_interval == 0:
            self._snapshots[frame] = self._snapshot()

    def _record(
        self,
        frame: int,
        actions: dict[str, int],
        predicted: frozenset[str],
        result: ReplicaFrame,
    ) -> FrameRecord:
        """Build the frame record from a step result and the resolved actions."""
        return FrameRecord(
            frame_number=frame,
            actions=dict(actions),
            rewards={key: float(value) for key, value in result.rewards.items()},
            terminated=result.terminated,
            truncated=result.truncated,
            info=result.info,
            state_hash=state_hash(result.observation),
            predicted_peers=predicted,
        )

    # -- rollback --------------------------------------------------------------

    def _perform_rollback(self, target: int) -> None:
        """Restore the best snapshot at or before the target and replay to now.

        The replay re-steps every already-stepped frame from the snapshot to the
        current frame in one pass, with no await, so no new input interleaves it. It
        refreshes the on-cadence snapshots and re-records the speculative frames
        with the corrected inputs, so a later rollback anchors on a correct state.
        """
        anchor = max(f for f in self._snapshots if f <= target)
        self._restore(self._snapshots[anchor])
        current = self._frame
        for frame in range(anchor, current):
            self._speculative.pop(frame, None)
        actions_for_replay = current - anchor
        for frame in range(anchor, current):
            actions, predicted = self._resolve_actions(frame)
            self._maybe_snapshot(frame)
            result = self._step(actions)
            self._speculative[frame] = self._record(
                frame, actions, predicted, result
            )
        self._rollback_count += 1
        self._max_rollback_depth = max(self._max_rollback_depth, actions_for_replay)

    # -- confirmation, promotion, and hashing ----------------------------------

    def _update_confirmed(self) -> None:
        """Advance the confirmed frame over the highest run of all-real frames."""
        frame = self._confirmed + 1
        while frame < self._frame:
            known = self._inputs.get(frame, {})
            if all(peer in known for peer in self._peers):
                frame += 1
            else:
                break
        self._confirmed = frame - 1

    def _promote_confirmed(self) -> None:
        """Promote every newly confirmed speculative frame to the canonical buffer."""
        for frame in range(self._promoted + 1, self._confirmed + 1):
            record = self._speculative.get(frame)
            if record is None:
                break
            self._canonical[frame] = FrameRecord(
                frame_number=record.frame_number,
                actions=record.actions,
                rewards=record.rewards,
                terminated=record.terminated,
                truncated=record.truncated,
                info=record.info,
                state_hash=record.state_hash,
                was_speculative=True,
                predicted_peers=record.predicted_peers,
            )
            self._promoted = frame

    def outbound_hashes(self) -> list[HashPacket]:
        """Return the state-hash packets for confirmed frames not yet announced."""
        packets: list[HashPacket] = []
        for frame in range(self._promoted + 1):
            if frame in self._sent_hashes:
                continue
            record = self._canonical.get(frame)
            if record is None:
                continue
            self._sent_hashes.add(frame)
            self._hash_evidence.setdefault(frame, {})[self._actor_id] = (
                record.state_hash
            )
            packets.append(
                HashPacket(
                    sender=self._actor_id,
                    frame_number=frame,
                    state_hash=record.state_hash,
                )
            )
        return packets

    def receive_hash(self, packet: HashPacket) -> None:
        """Store one peer's state hash for a frame, for the finality verdict."""
        if packet.sender == self._actor_id:
            return
        self._hash_evidence.setdefault(packet.frame_number, {})[packet.sender] = (
            packet.state_hash
        )

    # -- episode barrier -------------------------------------------------------

    def announce_end(self) -> EndPacket | None:
        """Return this peer's end packet once the local episode has ended."""
        if self._end_frame is None:
            return None
        return EndPacket(sender=self._actor_id, end_frame_exclusive=self._end_frame)

    def receive_end(self, packet: EndPacket) -> None:
        """Store one peer's proposed end frame for the minimum-end barrier."""
        self._peer_ends[packet.sender] = packet.end_frame_exclusive

    def finalize(self) -> None:
        """Close the episode on the exclusive minimum end frame across the peers.

        Once every peer's end frame is known, the barrier is the minimum, so every
        peer exports the same frame range. The engine force-promotes the remaining
        speculative frames inside the barrier and truncates the canonical buffer to
        it, so the exported trajectory ends on the agreed frame.
        """
        if len(self._peer_ends) != len(self._peers):
            raise ValueError("every peer must announce its end frame to finalize")
        end = min(self._peer_ends.values())
        self._final_end_frame = end
        for frame in range(self._promoted + 1, end):
            record = self._speculative.get(frame)
            if record is None:
                continue
            self._canonical[frame] = FrameRecord(
                frame_number=record.frame_number,
                actions=record.actions,
                rewards=record.rewards,
                terminated=record.terminated,
                truncated=record.truncated,
                info=record.info,
                state_hash=record.state_hash,
                was_speculative=True,
                predicted_peers=record.predicted_peers,
            )
            self._promoted = max(self._promoted, frame)
        for frame in list(self._canonical):
            if frame >= end:
                del self._canonical[frame]

    # -- outputs ---------------------------------------------------------------

    def ended(self) -> bool:
        """Return whether the local episode has ended."""
        return self._ended

    def all_ends_known(self) -> bool:
        """Return whether every peer's end frame has arrived, so finalize is ready.

        A wire-tier node reads this to decide when the minimum-end-frame barrier can
        close: the synchronous coordinator settles the packets itself, but an
        autonomous node over a real link must wait for every peer's end packet.
        """
        return len(self._peer_ends) == len(self._peers)

    def rollback_count(self) -> int:
        """Return how many rollbacks the engine has run this episode."""
        return self._rollback_count

    def max_rollback_depth(self) -> int:
        """Return the deepest rollback replay, in frames, this episode."""
        return self._max_rollback_depth

    def repair_count(self) -> int:
        """Return how many desync repairs this engine has applied this episode."""
        return self._repair_count

    # -- desync detection and repair -------------------------------------------

    def disputed_frames(self) -> list[int]:
        """Return the canonical frames whose peer state hashes disagree.

        A rollback engine over agreed inputs can only diverge if a replica draws
        from state a snapshot does not cover, so a disputed frame is the mesh's
        signal that one peer's replica has desynchronized. The engine records the
        disputed status (``P2PFrameFinality``); repair is the separate step below.
        """
        return [
            frame
            for frame in sorted(self._canonical)
            if self._finality(frame).status == "disputed"
        ]

    def local_state_hash(self, frame: int) -> Digest | None:
        """Return this peer's own canonical state hash for a frame, if promoted."""
        record = self._canonical.get(frame)
        return record.state_hash if record is not None else None

    def repair_snapshot(self, target_frame: int) -> tuple[int, object]:
        """Return an authority snapshot at or before a frame, for a diverged peer.

        The authority serves the nearest cadence snapshot it still holds at or below
        the target frame, with the frame it anchors. A diverged peer restores it and
        replays forward, so the transfer resynchronizes the replica exactly.
        """
        candidates = [frame for frame in self._snapshots if frame <= target_frame]
        if not candidates:
            raise ValueError("no snapshot is held at or before the target frame")
        anchor = max(candidates)
        return anchor, self._snapshots[anchor]

    def apply_repair(self, anchor: int, snapshot: object) -> None:
        """Adopt an authority snapshot at an anchor and rewind to re-derive forward.

        The engine restores its replica to the authority's snapshot, drops every
        speculative and canonical frame from the anchor on, and rewinds the frame,
        confirmation, and hash bookkeeping to the anchor. A subsequent ``advance``
        re-steps the anchor frames from the repaired state with the already-agreed
        inputs, so the peer re-derives the authority's trajectory and its later
        state hashes now agree. The repair clears the local hashes it had already
        announced for the repaired range, so it re-announces the corrected ones.
        """
        self._restore(snapshot)
        self._snapshots = {
            frame: held for frame, held in self._snapshots.items() if frame < anchor
        }
        self._snapshots[anchor] = snapshot
        self._speculative = {
            frame: rec for frame, rec in self._speculative.items() if frame < anchor
        }
        self._canonical = {
            frame: rec for frame, rec in self._canonical.items() if frame < anchor
        }
        self._predicted_actions = {
            frame: act
            for frame, act in self._predicted_actions.items()
            if frame < anchor
        }
        self._sent_hashes = {frame for frame in self._sent_hashes if frame < anchor}
        self._hash_evidence = {
            frame: ev for frame, ev in self._hash_evidence.items() if frame < anchor
        }
        self._frame = anchor
        self._confirmed = min(self._confirmed, anchor - 1)
        self._promoted = min(self._promoted, anchor - 1)
        if self._ended and (self._end_frame is None or self._end_frame > anchor):
            self._ended = False
            self._end_frame = None
            self._final_end_frame = None
            self._peer_ends.pop(self._actor_id, None)
        self._repair_count += 1

    def canonical_trajectory(self) -> list[FrameRecord]:
        """Return the canonical frames in order, the parity-comparable trajectory."""
        return [self._canonical[frame] for frame in sorted(self._canonical)]

    def game_transitions(self) -> list[GameTransition]:
        """Return one ``GameTransition`` per canonical frame under peer authority."""
        transitions: list[GameTransition] = []
        for frame in sorted(self._canonical):
            record = self._canonical[frame]
            transitions.append(
                GameTransition(
                    interaction_id=self._interaction_id,
                    channel_key=self._channel_key,
                    episode_id=self._episode_id,
                    frame_number=record.frame_number,
                    action_digest=state_hash(record.canonical()["actions"]),
                    state_digest=record.state_hash,
                    authority="peer",
                    applied_decisions=[],
                    replica_actor_id=self._actor_id,
                    mesh_membership_digest=self._mesh_digest,
                    membership_generation=self._generation,
                    recorded_at=self._recorded_at,
                )
            )
        return transitions

    def frame_finalities(self) -> list[P2PFrameFinality]:
        """Return the finality record per canonical frame, keyed by its status."""
        finalities: list[P2PFrameFinality] = []
        for frame in sorted(self._canonical):
            finalities.append(self._finality(frame))
        return finalities

    def _finality(self, frame: int) -> P2PFrameFinality:
        """Build the finality record for one confirmed frame from its evidence."""
        record = self._canonical[frame]
        actions = [
            P2PPeerAction(
                peer_actor_id=peer, action_digest=_action_digest(record.actions[peer])
            )
            for peer in sorted(record.actions)
        ]
        evidence_by_peer = self._hash_evidence.get(frame, {})
        evidence = [
            P2PPeerHashEvidence(peer_actor_id=peer, state_hash=evidence_by_peer[peer])
            for peer in sorted(evidence_by_peer)
        ]
        complete_hashes = set(evidence_by_peer) == set(self._peers)
        agreed: Digest | None = None
        if complete_hashes:
            values = {digest.hex for digest in evidence_by_peer.values()}
            if len(values) == 1:
                status: Literal["confirmed", "verified", "disputed"] = "verified"
                agreed = next(iter(evidence_by_peer.values()))
            else:
                status = "disputed"
        else:
            status = "confirmed"
        return P2PFrameFinality(
            interaction_id=self._interaction_id,
            channel_key=self._channel_key,
            episode_id=self._episode_id,
            frame_number=frame,
            mesh_membership_digest=self._mesh_digest,
            membership_generation=self._generation,
            status=status,
            frozen_peer_actor_ids=list(self._peers),
            actions=actions,
            hash_evidence=evidence,
            agreed_state_hash=agreed,
            recorded_at=self._recorded_at,
        )

    def episode_boundary(self) -> EpisodeBoundary:
        """Return the closing boundary bound to the minimum-end-frame barrier."""
        if self._final_end_frame is None:
            raise ValueError("finalize the episode before reading its boundary")
        end = self._final_end_frame
        peer_end_frames = [
            P2PPeerEndFrame(
                peer_actor_id=peer, end_frame_exclusive=self._peer_ends[peer]
            )
            for peer in sorted(self._peers)
        ]
        barrier = P2PEpisodeBarrier(
            mesh_membership_digest=self._mesh_digest,
            membership_generation=self._generation,
            frozen_peer_actor_ids=list(self._peers),
            rule="minimum-end-frame-exclusive",
            peer_end_frames=peer_end_frames,
        )
        last = self._canonical.get(end - 1)
        state = last.state_hash if last is not None else state_hash(None)
        kind: Literal["reset", "terminal"] = (
            "terminal" if last is not None and last.terminated else "reset"
        )
        return EpisodeBoundary(
            episode_id=self._episode_id,
            interaction_id=self._interaction_id,
            kind=kind,
            end_frame_exclusive=end,
            authority="peer",
            state_hash=state,
            p2p_barrier=barrier,
        )


__all__ = [
    "EndPacket",
    "FrameRecord",
    "HashPacket",
    "InputPacket",
    "PeerEngine",
    "ReplicaFrame",
]
