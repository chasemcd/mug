"""The six records that API-12 owns: controllers, decisions, and p2p authority.

You construct each object with its data alone; the ``schema`` envelope fills
itself from the frozen bundle. The frozen JSON-Schema corpus stays the authority,
and ``scheduling_schema`` loads it for the conformance test.

This family models the automated-controller policies, the decision request and
result records, the scheduler state, and the peer-to-peer bot authority. It adds
no runtime. The scheduler loop, the decision worker, and lease acquisition stay
deferred.

Several invariants are not expressible in JSON Schema and live here as
validators:

- a p2p bot authority lists its peers in sorted order and selects the highest;
- a decision request carries a p2p authority claim if, and only if, its
  execution mode is p2p, and the claim agrees with the request identity;
- a decision result carries the p2p fields (authority, origin, producer) if, and
  only if, its execution mode is p2p, and a produced p2p result also names its
  replay behavior;
- a produced result names its action digest and is fresh;
- a p2p result's producer digest equals its action digest.

A p2p claim must also copy the fields of the bound bot authority record. That
rule compares two records, so it belongs to the scheduler runtime that holds the
live authority, not to a single record. A standalone record cannot decide it and
does not try.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mug.kernel import (
    Digest,
    Duration,
    LeaseRef,
    ProducerPosition,
    SchemaBundle,
    SchemaRef,
    UtcInstant,
    VersionStamp,
    load_family_schema,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import (
    ActorInstanceId,
    DecisionId,
    EpisodeId,
    InteractionId,
)
from mug.kernel.refs import NonNegativeSafeInteger, PositiveSafeInteger

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/architecture/phase-0/api-12/schemas/v0/scheduler.schema.json"
)

@lru_cache(maxsize=1)
def scheduling_schema() -> SchemaBundle:
    """Return the loaded API-12 bundle (with the shared kernel registered)."""
    return load_family_schema(str(_SCHEMA_PATH))


def _schema_ref(name: str) -> SchemaRef:
    """Build the pinned schema reference for one object from the frozen bundle."""
    digest = Digest(algorithm="sha-256", hex=scheduling_schema().bundle_digest)
    return SchemaRef(name=name, version=0, digest=digest)


_AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]

ExecutionModeName = Literal["server", "browser", "p2p"]
"""How a decision runs: on the server, in the browser, or peer-to-peer."""

Fallback = Literal["repeat-last", "default-action"]
"""What a seat does when a decision times out or arrives stale."""


class MeshMembershipSchemaRef(KernelModel):
    """A pinned reference to the API-06 mesh membership schema at version 0."""

    name: Literal["mug.api-06.p2p-mesh-membership"]
    version: Literal[0]
    digest: Digest


class P2PAuthorityClaim(KernelModel):
    """A copy of the bot authority binding, carried by a p2p decision record."""

    authority_assignment_digest: Digest
    interaction_id: InteractionId
    channel_key: _AuthoringKey
    episode_id: EpisodeId
    episode_generation: PositiveSafeInteger
    target_frame: NonNegativeSafeInteger
    bot_actor_id: ActorInstanceId
    authority_actor_id: ActorInstanceId
    mesh_membership_digest: Digest
    membership_generation: PositiveSafeInteger
    authority_fence: LeaseRef


class P2PBotAuthority(KernelModel):
    """Which peer holds the bot decision authority for one episode."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-12.p2p-bot-authority")
    )
    interaction_id: InteractionId
    channel_key: _AuthoringKey
    episode_id: EpisodeId
    episode_generation: PositiveSafeInteger
    bot_actor_id: ActorInstanceId
    mesh_membership_schema: MeshMembershipSchemaRef
    mesh_membership_digest: Digest
    membership_generation: PositiveSafeInteger
    eligible_peer_actor_ids: Annotated[
        list[ActorInstanceId], Field(min_length=2, max_length=64)
    ]
    authority_actor_id: ActorInstanceId
    authority_fence: LeaseRef
    authority_scope: Literal["episode"]
    selection_policy: Literal["highest-eligible-peer-actor-id"]
    mid_episode_failover: Literal[False]
    version: VersionStamp

    @model_validator(mode="after")
    def _authority_is_highest_sorted_peer(self) -> P2PBotAuthority:
        peers = self.eligible_peer_actor_ids
        if list(peers) != sorted(peers):
            raise ValueError("eligible peer actor ids must be in sorted order")
        if len(set(peers)) != len(peers):
            raise ValueError("eligible peer actor ids must be unique")
        if self.authority_actor_id != peers[-1]:
            raise ValueError("authority must be the highest eligible peer")
        return self


class DecisionRequest(KernelModel):
    """A request for one automated decision at a deadline for a seat."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-12.decision-request")
    )
    decision_id: DecisionId
    actor_id: ActorInstanceId
    channel_key: _AuthoringKey
    execution_mode: ExecutionModeName
    episode_generation: PositiveSafeInteger
    source_observation_digest: Digest
    deadline: UtcInstant
    validity_window: Duration
    submitted_at: UtcInstant
    p2p_authority: P2PAuthorityClaim | None = None

    @model_validator(mode="after")
    def _p2p_authority_agrees(self) -> DecisionRequest:
        is_p2p = self.execution_mode == "p2p"
        claim = self.p2p_authority
        if is_p2p and claim is None:
            raise ValueError("a p2p request must carry its authority claim")
        if not is_p2p and claim is not None:
            raise ValueError("only a p2p request may carry an authority claim")
        if claim is not None:
            if claim.bot_actor_id != self.actor_id:
                raise ValueError("claim bot actor must match the request actor")
            if claim.channel_key != self.channel_key:
                raise ValueError("claim channel must match the request channel")
            if claim.episode_generation != self.episode_generation:
                raise ValueError("claim generation must match the request")
        return self


class DecisionResult(KernelModel):
    """The outcome of one decision request: an action, a timeout, or a failure."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-12.decision-result")
    )
    decision_id: DecisionId
    execution_mode: ExecutionModeName
    outcome: Literal["produced", "timed-out", "cancelled", "failed"]
    staleness: Literal["fresh", "stale"]
    action_digest: Digest | None = None
    produced_at: UtcInstant | None = None
    p2p_authority: P2PAuthorityClaim | None = None
    decision_origin: Literal["server-scheduler", "authority-local"] | None = None
    producer: ProducerPosition | None = None
    replay_behavior: Literal["apply-recorded-action"] | None = None

    @model_validator(mode="after")
    def _outcome_and_p2p_fields_agree(self) -> DecisionResult:
        produced = self.outcome == "produced"
        if produced and self.action_digest is None:
            raise ValueError("a produced result must name its action digest")
        if produced and self.staleness == "stale":
            raise ValueError("a produced result must be fresh")

        is_p2p = self.execution_mode == "p2p"
        p2p_fields = (self.p2p_authority, self.decision_origin, self.producer)
        if is_p2p:
            if any(field is None for field in p2p_fields):
                raise ValueError("a p2p result must carry its authority evidence")
            if produced and self.replay_behavior is None:
                raise ValueError("a produced p2p result must name its replay behavior")
            producer = self.producer
            assert producer is not None
            if produced and producer.content_digest != self.action_digest:
                raise ValueError("producer digest must equal the action digest")
        else:
            if any(field is not None for field in p2p_fields):
                raise ValueError("only a p2p result may carry authority evidence")
            if self.replay_behavior is not None:
                raise ValueError("only a p2p result may name a replay behavior")
        return self


class SchedulerState(KernelModel):
    """The per-seat scheduler state: idle, requested, running, or cancelling."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-12.scheduler-state")
    )
    actor_id: ActorInstanceId
    status: Literal["idle", "requested", "running", "cancelling"]
    in_flight_decision_id: DecisionId | None = None


class FallbackRule(KernelModel):
    """A seat's timeout and staleness fallback, without its own envelope."""

    on_timeout: Fallback
    on_stale: Fallback


class FallbackPolicy(KernelModel):
    """A reusable, envelope-carrying seat fallback for timeout and staleness."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-12.fallback-policy")
    )
    on_timeout: Fallback
    on_stale: Fallback


class ControllerPolicy(KernelModel):
    """How often an automated controller decides, and its realtime fallback."""

    schema: SchemaRef = Field(  # pyright: ignore[reportIncompatibleMethodOverride]
        default_factory=lambda: _schema_ref("mug.api-12.controller-policy")
    )
    policy_key: _AuthoringKey
    decides_every: PositiveSafeInteger
    realtime_seat: bool
    fallback: FallbackRule | None = None

    @model_validator(mode="after")
    def _realtime_seat_names_fallback(self) -> ControllerPolicy:
        if self.realtime_seat and self.fallback is None:
            raise ValueError("a realtime seat must name its fallback")
        return self
