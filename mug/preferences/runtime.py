"""The preference-annotation runtime: assign, respond, and attest quality (API-18).

The API-18 family (``mug.preferences``) owns five records -- the
``PreferenceProtocol`` that declares a blinded, randomized comparison, the
``CandidateRef`` that names an opaque candidate, the ``PreferenceAssignment`` one
participant receives, the ``PreferenceResponse`` they return, and the per-response
``QualityEvidence`` -- but adds no runtime. This module is that runtime. It drives
the annotation loop through the shared command spine (``mug.runtime``), so one
annotation's lineage is a canonical event stream like any other aggregate.

One identity rule keeps it simple: the aggregate is the assignment. Its id is the
``assignment_id`` and its stream is the ordered lineage of the annotation -- the
assignment, then the response, then the quality evidence. The three stages advance
the aggregate head in order, so the aggregate holds exactly three events at most
and each stage commits against a fixed revision:

- ``assign`` creates the aggregate (revision 1);
- ``respond`` commits the response against revision 1 (so the aggregate reaches
  revision 2);
- ``attest_quality`` commits the quality evidence against revision 2 (revision 3).

Those fixed revisions give the family its idempotency and its single-response rule
for free, over the store's own fencing and command-id coalescing: an identical
retry of any stage replays to the same receipt with no second effect (the store
coalesces the command id), and a *different* second response reads the same
expected revision and the store fences it as stale. So a participant is assigned
once, responds once, and one quality attestation is recorded -- and a dropped
connection that retries never double-records.

The candidates a participant compares come from recorded evidence -- a replay
bundle's trajectory artifact, a model-output artifact, a chat segment. So
``candidate_from_artifact`` builds a blinded ``CandidateRef`` over any recorded
artifact, and the assignment's display order is a deterministic, seed-committed
permutation of the candidate keys (blinded and, when the protocol asks, shuffled),
so the order a participant sees is reproducible from the revealed seed but carries
no signal about which candidate is which.

The runtime is a producer boundary, so the caller injects the impure parts: the
store and a per-stage ``CommandContext`` (the one entropy-and-clock boundary),
exactly as every other family service does. A test drives the whole loop with a
fixed clock and hand-built contexts, with no socket.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from mug.kernel import (
    ArtifactRef,
    CommandReceipt,
    CommandTypeRef,
    PublicHandle,
    TypedObject,
    UtcInstant,
)
from mug.preferences.types import (
    CandidateRef,
    PreferenceAssignment,
    PreferenceProtocol,
    PreferenceResponse,
    QualityEvidence,
)
from mug.runtime import CommandContext, commit_command
from mug.storage import Store, digest_of

_PreferenceRecord = (
    PreferenceAssignment | PreferenceResponse | QualityEvidence | CandidateRef
)

_ASSIGN = CommandTypeRef(name="preference.assign", version=0)
_RESPOND = CommandTypeRef(name="preference.respond", version=0)
_ATTEST = CommandTypeRef(name="preference.attest-quality", version=0)

# The assignment lifecycle is a fixed three-stage stream, so each stage commits
# against the revision the prior stage left behind. See the module docstring.
_ASSIGNMENT_REVISION = 1
_RESPONSE_REVISION = 2

_RESPONSE_SCHEMA = "mug.api-18.preference-response"
_QUALITY_SCHEMA = "mug.api-18.quality-evidence"


class UnknownAssignment(Exception):
    """A response or attestation named an assignment that was never created."""


class ResponseRequired(Exception):
    """A quality attestation ran before the response it attests to exists."""


def candidate_from_artifact(
    *,
    candidate_key: str,
    kind: str,
    artifact: ArtifactRef,
    display_handle: PublicHandle,
) -> CandidateRef:
    """Build one blinded candidate over a recorded artifact.

    The candidate names its content by an opaque ``ArtifactRef`` -- a replay
    bundle's trajectory, a model-output blob, a chat segment -- so a participant
    compares recorded evidence, not a live run. The ``display_handle`` is the
    blinded public handle the participant sees in place of the candidate's identity.
    """
    return CandidateRef(
        candidate_key=candidate_key,
        kind=kind,  # pyright: ignore[reportArgumentType]
        content_ref=artifact,
        display_handle=display_handle,
    )


def display_order(
    candidate_keys: Sequence[str], *, randomize: bool, seed: bytes
) -> list[str]:
    """Return the order a participant is shown, blinded and optionally shuffled.

    When the protocol does not randomize, the order is the given order. When it
    does, the order is a deterministic permutation derived from the seed: each key
    sorts by the digest of the seed and the key, so the order is reproducible from
    the revealed seed yet carries no signal about which candidate is which.
    """
    if not randomize:
        return list(candidate_keys)
    return sorted(
        candidate_keys,
        key=lambda key: hashlib.sha256(seed + key.encode("utf-8")).hexdigest(),
    )


class PreferenceService:
    """Drive one annotation's records through the command spine.

    The service holds only the store; the caller mints a ``CommandContext`` for each
    stage on the assignment's aggregate. Each method commits one record and returns
    the commit receipt beside it, so the caller reads ``receipt.outcome`` to tell an
    accepted stage from a fenced, no-effect one.
    """

    def __init__(self, *, store: Store) -> None:
        self._store = store

    async def assign(
        self,
        *,
        context: CommandContext,
        protocol: PreferenceProtocol,
        query_id: str,
        enrollment_id: str,
        candidate_keys: Sequence[str],
        seed: bytes,
    ) -> tuple[CommandReceipt, PreferenceAssignment]:
        """Create one participant's blinded, ordered assignment for a query.

        The display order is a seed-committed permutation of the candidate keys
        under the protocol (blinded, and shuffled when the protocol asks). The
        assignment commits to the seed by its digest, so a later reveal proves the
        order. A second assignment of the same aggregate is refused with a
        no-effect rejection; an identical retry replays.
        """
        order = display_order(
            candidate_keys, randomize=protocol.randomize_order, seed=seed
        )
        assignment = PreferenceAssignment(
            assignment_id=context.aggregate_id,
            query_id=query_id,
            enrollment_id=enrollment_id,
            candidate_display_order=order,
            blinded=protocol.blinded,
            seed_commitment=digest_of(seed),
        )
        receipt = await commit_command(
            context,
            command=_ASSIGN,
            new_state=_state(assignment),
            result=_typed(assignment),
            store=self._store,
        )
        return receipt, assignment

    async def respond(
        self,
        *,
        context: CommandContext,
        response_id: str,
        choice: str,
        presented_order: Sequence[str],
        submitted_at: UtcInstant,
        receipt_required: bool = False,
    ) -> tuple[CommandReceipt, PreferenceResponse]:
        """Record the participant's choice over the order they were shown.

        The response commits against the assignment revision, so a participant
        responds once: an identical retry replays to the same receipt, and a
        different second response reads the same expected revision and the store
        fences it as a no-effect rejection. The record enforces that the choice was
        one of the presented candidates.
        """
        if self._store.load_aggregate(context.aggregate_id) is None:
            raise UnknownAssignment(context.aggregate_id)
        response = PreferenceResponse(
            response_id=response_id,
            assignment_id=context.aggregate_id,
            choice=choice,
            presented_order=list(presented_order),
            receipt_required=receipt_required,
            submitted_at=submitted_at,
        )
        receipt = await commit_command(
            context,
            command=_RESPOND,
            new_state=_state(response),
            result=_typed(response),
            store=self._store,
            expected_revision=_ASSIGNMENT_REVISION,
        )
        return receipt, response

    async def attest_quality(
        self,
        *,
        context: CommandContext,
        attention_check_passed: bool,
        response_time_ms: int,
        flagged: bool = False,
    ) -> tuple[CommandReceipt, QualityEvidence]:
        """Attach the per-response quality signals to the response.

        The attestation reads the response id from the aggregate head (the response
        or, on a retry, the quality evidence already recorded -- both carry the
        response id), so the caller does not repeat it. It commits against the
        response revision, so one attestation is recorded: a retry replays and a
        different attestation is fenced. An attestation before the response exists
        is refused.
        """
        state = self._store.load_aggregate(context.aggregate_id)
        if state is None:
            raise UnknownAssignment(context.aggregate_id)
        response_id = _response_id_of(state)
        if response_id is None:
            raise ResponseRequired(context.aggregate_id)
        quality = QualityEvidence(
            response_id=response_id,
            attention_check_passed=attention_check_passed,
            response_time_ms=response_time_ms,
            flagged=flagged,
        )
        receipt = await commit_command(
            context,
            command=_ATTEST,
            new_state=_state(quality),
            result=_typed(quality),
            store=self._store,
            expected_revision=_RESPONSE_REVISION,
        )
        return receipt, quality


def _response_id_of(state: dict[str, Any]) -> str | None:
    """Return the response id from a response or quality-evidence head, else None.

    The response and the quality evidence both carry ``response_id``; an assignment
    head does not. So a missing id means the response stage has not run yet.
    """
    name = state.get("schema", {}).get("name")
    if name in (_RESPONSE_SCHEMA, _QUALITY_SCHEMA):
        value = state.get("response_id")
        return value if isinstance(value, str) else None
    return None


def _state(record: _PreferenceRecord) -> dict[str, Any]:
    """Dump one preference record to its canonical persisted form."""
    return record.model_dump(mode="json", exclude_none=True)


def _typed(record: _PreferenceRecord) -> TypedObject:
    """Wrap one preference record as the command result that carries its schema."""
    return TypedObject(schema=record.schema, data=_state(record))


__all__ = [
    "PreferenceService",
    "ResponseRequired",
    "UnknownAssignment",
    "candidate_from_artifact",
    "display_order",
]
