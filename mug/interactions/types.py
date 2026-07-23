"""The objects that API-06 owns: interactions, channels, groups, and leases.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``interactions_schema`` loads it for the conformance test.

This family models the runtime membership records -- who is cast into an
interaction, which channels carry their traffic, how groups form, how the server
monitors in-play conduct, and how a peer mesh proves its latency. It adds no
runtime; matchmaking, lease acquisition, and mesh probing stay deferred.

Several invariants are not expressible in JSON Schema and live here as validators:

- a channel's ordering agrees with its kind (game is per-producer; chat and
  annotation are total);
- a formed group holds exactly its declared size;
- mesh peers appear in canonical sorted order, with no duplicate peer;
- a monitoring ladder escalates by strictly increasing violation count;
- a latency mesh probe covers every peer pair, each within the bound;
- a latency match strategy bounds the estimated or the peer-to-peer round trip.
"""

from __future__ import annotations

import itertools
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from mug.kernel import (
    Digest,
    Duration,
    LeaseRef,
    SchemaBundle,
    SchemaRef,
    UtcInstant,
    VersionStamp,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import (
    ActorInstanceId,
    ChannelDefinitionId,
    ChannelInstanceId,
    EnrollmentId,
    GroupId,
    InteractionId,
    VisitId,
)
from mug.kernel.refs import PositiveSafeInteger, StudyVersionRef

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-06/schemas/v0/interaction.schema.json"
)


@lru_cache(maxsize=1)
def interactions_schema() -> SchemaBundle:
    """Return the loaded API-06 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=interactions_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]
_QualifiedName = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$",
        max_length=512,
    ),
]


def _unique(values: list[str]) -> list[str]:
    """Reject a list that repeats any peer identifier."""
    if len(set(values)) != len(values):
        raise ValueError("peer identifiers must be unique")
    return values


_PeerActorIds = Annotated[
    list[ActorInstanceId], Field(min_length=2, max_length=64), AfterValidator(_unique)
]
_Cast = Annotated[
    dict[_AuthoringKey, ActorInstanceId], Field(min_length=1, max_length=64)
]

# Each channel kind carries its own ordering guarantee (D08-2): the author picks
# the kind, never the ordering mechanics.
_KIND_ORDERING = {"game": "per-producer", "chat": "total", "annotation": "total"}


class MonitoringLadderStep(KernelModel):
    """One rung: at ``at_violations``, the server applies ``action``."""

    at_violations: PositiveSafeInteger
    action: Literal["warn", "exclude"]


class MonitoringCallback(KernelModel):
    """A researcher hook run server-side as an actor crosses a ladder step."""

    handler: _QualifiedName
    on_error: Literal["fail_closed", "fail_open"] = "fail_closed"


class MonitoringPolicy(KernelModel):
    """Server-authoritative in-play monitoring: bounds, a ladder, and a callback."""

    enforcement: Literal["server-authoritative"]
    max_rtt: Duration
    max_hidden: Duration
    ladder: Annotated[list[MonitoringLadderStep], Field(min_length=1, max_length=16)]
    callback: MonitoringCallback | None = None

    @model_validator(mode="after")
    def _ladder_escalates(self) -> MonitoringPolicy:
        thresholds = [step.at_violations for step in self.ladder]
        if thresholds != sorted(thresholds) or len(thresholds) != len(set(thresholds)):
            raise ValueError("ladder steps must escalate by strictly rising count")
        return self


class Interaction(KernelModel):
    """One runtime interaction: its cast, channels, group, and monitoring."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-06.interaction")
    )
    interaction_id: InteractionId
    study_version: StudyVersionRef
    visit_ids: Annotated[list[VisitId], Field(min_length=1, max_length=64)]
    cast: _Cast
    channels: Annotated[list[_AuthoringKey], Field(min_length=1, max_length=32)]
    status: Literal["forming", "active", "completed", "aborted"]
    version: VersionStamp
    group_id: GroupId | None = None
    on_missing: Literal["wait", "regroup"] | None = None
    monitoring: MonitoringPolicy | None = None

    @model_validator(mode="after")
    def _on_missing_names_group(self) -> Interaction:
        if self.on_missing is not None and self.group_id is None:
            raise ValueError("on_missing requires a group_id")
        return self


class ChannelInstance(KernelModel):
    """One live channel in an interaction: its kind and ordering guarantee."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-06.channel-instance")
    )
    channel_instance_id: ChannelInstanceId
    interaction_id: InteractionId
    channel_definition_id: ChannelDefinitionId
    channel_key: _AuthoringKey
    channel_type: Literal["game", "chat", "annotation"]
    ordering: Literal["total", "per-producer"]

    @model_validator(mode="after")
    def _ordering_matches_kind(self) -> ChannelInstance:
        if self.ordering != _KIND_ORDERING[self.channel_type]:
            raise ValueError("channel ordering must match the channel kind")
        return self


class Membership(KernelModel):
    """One actor's access to one channel of an interaction."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-06.membership")
    )
    interaction_id: InteractionId
    actor_id: ActorInstanceId
    channel_key: _AuthoringKey
    access: Literal["read_write", "read_only", "none"]


class P2PMeshMembership(KernelModel):
    """The peer set of a full-mesh group channel, in canonical order."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-06.p2p-mesh-membership")
    )
    interaction_id: InteractionId
    group_id: GroupId
    channel_key: _AuthoringKey
    peer_actor_ids: _PeerActorIds
    topology: Literal["full-mesh"]
    membership_generation: PositiveSafeInteger
    version: VersionStamp

    @model_validator(mode="after")
    def _peers_in_canonical_order(self) -> P2PMeshMembership:
        if self.peer_actor_ids != sorted(self.peer_actor_ids):
            raise ValueError("peer_actor_ids must be in canonical sorted order")
        return self


class MeshPairwiseRtt(KernelModel):
    """One unordered peer pair and the round trip probed between them."""

    peers: Annotated[list[ActorInstanceId], Field(min_length=2, max_length=2)]
    rtt: Duration


class MeshLatencyProbe(KernelModel):
    """All-pairs probe evidence that a latency-bounded mesh may form."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-06.mesh-latency-probe")
    )
    interaction_id: InteractionId
    group_id: GroupId
    channel_key: _AuthoringKey
    peer_actor_ids: _PeerActorIds
    max_p2p_rtt: Duration
    pairwise_rtts: Annotated[
        list[MeshPairwiseRtt], Field(min_length=1, max_length=2016)
    ]
    membership_generation: PositiveSafeInteger
    version: VersionStamp

    @model_validator(mode="after")
    def _all_pairs_within_bound(self) -> MeshLatencyProbe:
        max_us = self.max_p2p_rtt.microseconds
        peers = sorted(set(self.peer_actor_ids))
        observed = {frozenset(entry.peers) for entry in self.pairwise_rtts}
        expected = {frozenset(pair) for pair in itertools.combinations(peers, 2)}
        over_bound = any(
            entry.rtt.microseconds > max_us for entry in self.pairwise_rtts
        )
        if over_bound or observed != expected:
            raise ValueError("every peer pair must be probed within max_p2p_rtt")
        return self


class Group(KernelModel):
    """A matched group of enrollments, with its declared size and status."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-06.group")
    )
    group_id: GroupId
    study_version: StudyVersionRef
    group_key: _AuthoringKey
    size: Annotated[int, Field(ge=1, le=64)]
    members: Annotated[list[EnrollmentId], Field(min_length=1, max_length=64)]
    status: Literal["forming", "formed", "released"]
    version: VersionStamp
    formed_at: UtcInstant | None = None

    @model_validator(mode="after")
    def _formed_group_has_declared_size(self) -> Group:
        if self.status == "formed" and len(self.members) != self.size:
            raise ValueError("a formed group must hold exactly its declared size")
        return self


class FifoMatch(KernelModel):
    """First-in, first-out matchmaking."""

    kind: Literal["fifo"]


class LatencyMatch(KernelModel):
    """Latency-bounded matchmaking on estimated or peer-to-peer round trip."""

    kind: Literal["latency"]
    max_estimated_rtt: Duration | None = None
    max_p2p_rtt: Duration | None = None

    @model_validator(mode="after")
    def _bounds_a_round_trip(self) -> LatencyMatch:
        if self.max_estimated_rtt is None and self.max_p2p_rtt is None:
            raise ValueError("a latency strategy must bound a round trip")
        return self


class CustomMatch(KernelModel):
    """Matchmaking by a researcher-supplied matchmaker reference."""

    kind: Literal["custom"]
    matchmaker: _QualifiedName


MatchStrategy = Annotated[
    FifoMatch | LatencyMatch | CustomMatch, Field(discriminator="kind")
]


class MatchmakingTicket(KernelModel):
    """One enrollment's request to be matched into a group."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-06.matchmaking-ticket")
    )
    study_version: StudyVersionRef
    group_key: _AuthoringKey
    enrollment_id: EnrollmentId
    match: MatchStrategy
    enqueued_at: UtcInstant
    status: Literal["waiting", "probing", "matched", "released", "expired"]
    group_id: GroupId | None = None

    @model_validator(mode="after")
    def _matched_names_group(self) -> MatchmakingTicket:
        if self.status == "matched" and self.group_id is None:
            raise ValueError("a matched ticket must name its group")
        return self


class ConnectionLease(KernelModel):
    """A fenced lease that lets one actor connect to an interaction."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-06.connection-lease")
    )
    lease: LeaseRef
    interaction_id: InteractionId
    actor_id: ActorInstanceId
    expires_at: UtcInstant
