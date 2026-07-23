"""``build_p2p_replay_bundle`` closes a mesh episode into a p2p replay bundle.

This test drives a real two-peer rollback mesh (``mug.game.mesh.PeerEngine``) over
a tiny deterministic replica with zero latency, so every frame confirms and its
peer hashes agree -- a verified episode. It then assembles a p2p replay bundle from
the engine's own evidence (the frame finalities and the episode boundary) plus the
frozen mesh membership and an empty decision tape, and proves the bundle: the
manifest carries its ``P2PReplayEvidence``, every evidence artifact closes over the
manifest's artifact set, the derived finality outcome is ``verified``, the manifest
validates against the frozen API-16 schema, and the whole bundle re-reads as valid.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from mug.game.mesh import HashPacket, InputPacket, PeerEngine, ReplicaFrame
from mug.interactions.types import P2PMeshMembership
from mug.kernel import DataHandlingRef, Digest, VersionStamp, etag
from mug.replay import (
    build_p2p_replay_bundle,
    replay_schema,
    validate_replay_bundle,
)
from mug.replay.tape import build_decision_tape
from mug.storage import InMemoryStore

_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000010f"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000010e"
_GROUP = "group_019b6000-0000-7000-8000-00000000010d"
_RECORDED_AT = "2026-07-22T00:00:00.000000Z"
_MESH_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_UUID = "019b6000-0000-7000-8000-{:012x}"


def _actor(index: int) -> str:
    return f"actor_019b6000-0000-7000-8000-0000000001{index:02x}"


class _Counter:
    """A trivial deterministic two-seat replica: it steps a shared counter."""

    def __init__(self, actors: tuple[str, ...], *, episode_len: int) -> None:
        self._actors = tuple(sorted(actors))
        self._len = episode_len
        self._t = 0
        self._sum = 0

    def step(self, actions: Mapping[str, int]) -> ReplicaFrame:
        self._t += 1
        self._sum += sum(int(actions.get(actor, 0)) for actor in self._actors)
        return ReplicaFrame(
            observation=[self._sum, self._t],
            rewards={actor: -1.0 for actor in self._actors},
            terminated=self._t >= self._len,
            truncated=False,
            info={},
        )

    def snapshot(self) -> object:
        return (self._t, self._sum)

    def restore(self, state: object) -> None:
        self._t, self._sum = cast("tuple[int, int]", state)


def _run_verified_mesh(episode_len: int = 6) -> PeerEngine:
    """Run a zero-latency two-peer mesh; return one finalized, verified engine."""
    actors = (_actor(1), _actor(2))
    replicas = {actor: _Counter(actors, episode_len=episode_len) for actor in actors}
    engines = {
        actor: PeerEngine(
            actor_id=actor,
            peer_actor_ids=actors,
            interaction_id=_INTERACTION,
            episode_id=_EPISODE,
            channel_key="p2p-game",
            mesh_membership_digest=_MESH_DIGEST,
            membership_generation=1,
            step=replicas[actor].step,
            snapshot=replicas[actor].snapshot,
            restore=replicas[actor].restore,
            recorded_at=_RECORDED_AT,
            input_delay=1,
            default_action=1,
            max_steps=episode_len + 50,
        )
        for actor in actors
    }

    input_q: list[tuple[int, str, InputPacket]] = []
    hash_q: list[tuple[int, str, HashPacket]] = []
    for tick in range(episode_len + 40):
        for due, receiver, packet in input_q:
            if due == tick:
                engines[receiver].receive_input(packet)
        for due, receiver, hpacket in hash_q:
            if due == tick:
                engines[receiver].receive_hash(hpacket)
        for sender in actors:
            packet = engines[sender].submit_local(1)
            for receiver in actors:
                if receiver != sender:
                    input_q.append((tick + 1, receiver, packet))
        for sender in actors:
            engines[sender].advance()
        for sender in actors:
            for hpacket in engines[sender].outbound_hashes():
                for receiver in actors:
                    if receiver != sender:
                        hash_q.append((tick + 1, receiver, hpacket))

    ends = {actor: engines[actor].announce_end() for actor in actors}
    for actor in actors:
        for other in actors:
            end = ends[other]
            if other != actor and end is not None:
                engines[actor].receive_end(end)
    for engine in engines.values():
        engine.finalize()
    return engines[actors[0]]


def _membership(peers: tuple[str, ...]) -> P2PMeshMembership:
    return P2PMeshMembership(
        interaction_id=_INTERACTION,
        group_id=_GROUP,
        channel_key="p2p-game",
        peer_actor_ids=list(peers),
        topology="full-mesh",
        membership_generation=1,
        version=VersionStamp(revision=1, etag=etag({"peers": list(peers)})),
    )


async def test_a_verified_mesh_episode_assembles_a_valid_p2p_bundle() -> None:
    """The engine's evidence closes into a p2p bundle that validates."""
    engine = _run_verified_mesh()
    finalities = engine.frame_finalities()
    # Guard the premise: a zero-latency mesh verifies every canonical frame.
    assert {final.status for final in finalities} == {"verified"}

    store = InMemoryStore()
    ids = iter(_UUID.format(n) for n in range(1, 100))
    tape = build_decision_tape(interaction_id=_INTERACTION, results=[])

    bundle = await build_p2p_replay_bundle(
        artifacts=store,
        interaction_id=_INTERACTION,
        mesh_membership=_membership((_actor(1), _actor(2))),
        frame_finalities=finalities,
        episode_boundaries=[engine.episode_boundary()],
        decision_tape=tape,
        new_artifact_id=lambda: "artifact_" + next(ids),
        new_upload_id=lambda: "upload_" + next(ids),
        now=lambda: _RECORDED_AT,
        data_handling=DataHandlingRef(privacy_labels=["research"]),
    )

    manifest = bundle.manifest
    assert manifest.execution_mode == "p2p"
    evidence = manifest.p2p_replay_evidence
    assert evidence is not None
    # The derived episode outcome is verified through the last frame.
    assert evidence.finality_outcome.status == "verified"
    # The mesh digest binds the persisted membership artifact.
    assert evidence.mesh_membership_digest == evidence.mesh_membership.artifact.digest
    # The manifest validates against the frozen API-16 schema.
    instance = manifest.model_dump(mode="json", exclude_none=True)
    assert replay_schema().is_valid("ReplayManifest", instance)
    # The whole bundle re-reads byte-identically.
    verdict = await validate_replay_bundle(artifacts=store, manifest=manifest)
    assert verdict.valid is True
