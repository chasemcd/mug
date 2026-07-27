"""The preference-annotation runtime: assign, respond, and attest quality (API-18).

The API-18 family (``mug.preferences``) owns five records -- the
``PreferenceProtocol`` that declares a blinded, randomized comparison, the
``CandidateRef`` that names an opaque candidate, the ``PreferenceAssignment`` one
participant receives, the ``PreferenceResponse`` they return, and the per-response
``QualityEvidence`` -- but adds no runtime. This module is that runtime. It drives
the annotation loop through the shared command spine (``mug.runtime``), so one
annotation's lineage is a canonical event stream like any other aggregate.

**One record, one aggregate, and the identifiers say how they join.** A store holds
one state per aggregate, so two records written to one aggregate are one record and
a lost one -- and what would be lost here is exactly what a study needs: the
enrollment that answered, the seed the order was committed under, and the choice
itself. So the protocol, the assignment, the response, and the quality evidence each
head their own aggregate, and the response's identifier body **is** the
assignment's (``response_id_for``).

That shared body keeps the annotation's lineage on **one stream** -- a stream is
named by the aggregate's own identifier body, so the assignment and its answer land
on the same one and reading it gives the annotation in order. The quality evidence
is separate on both counts, because it is separate evidence.

That shared body is also the whole of the family's idempotency. One assignment can
address one response aggregate, so a participant responds once: an identical retry
replays to the same receipt (the store coalesces the command id), and a different
second answer finds the aggregate taken and is refused with no effect. A dropped
connection that retries never double-records, and nothing has to remember whether
this participant has answered -- the identifier already says.

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
from typing import Any, Literal

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
    DimensionRating,
    PreferenceAssignment,
    PreferenceProtocol,
    PreferenceResponse,
    QualityEvidence,
)
from mug.runtime import CommandContext, commit_command
from mug.storage import Store, digest_of

_PreferenceRecord = (
    PreferenceAssignment
    | PreferenceResponse
    | QualityEvidence
    | CandidateRef
    | PreferenceProtocol
)

_DECLARE = CommandTypeRef(name="preference.declare", version=0)
_ASSIGN = CommandTypeRef(name="preference.assign", version=0)
_RESPOND = CommandTypeRef(name="preference.respond", version=0)
_ATTEST = CommandTypeRef(name="preference.attest-quality", version=0)



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


def response_id_for(assignment_id: str) -> str:
    """Return the one response identifier an assignment can ever have.

    It shares the assignment's identifier body, so one assignment has one response
    without anything having to remember which, and a reader joins the two with no
    index beside the ledger. It is the same convention that puts an aggregate's
    events on the stream that shares its body.
    """
    return "prefresponse_" + assignment_id.split("_", 1)[1]


class PreferenceService:
    """Drive one annotation's records through the command spine.

    The service holds only the store; the caller mints a ``CommandContext`` per
    record -- the assignment's aggregate for the assignment and the response, and
    the quality evidence's own for the attestation. Each method commits one record
    and returns the commit receipt beside it, so the caller reads ``receipt.outcome``
    to tell an accepted write from a fenced, no-effect one.
    """

    def __init__(self, *, store: Store) -> None:
        self._store = store

    async def declare(
        self,
        *, context: CommandContext, protocol: PreferenceProtocol
    ) -> tuple[CommandReceipt, PreferenceProtocol]:
        """Record the protocol a set of annotations is answered under.

        The protocol is what the study asked: whether the candidates were blinded,
        whether their order was shuffled, whether a tie was on offer, and which
        dimensions each answer carries. None of that is in an assignment or a
        response, so without this record an analysis could read the answers and not
        the question -- and a dataset with no ties would be unreadable, because
        "none was chosen" and "none was offered" would look the same.

        The aggregate is the protocol version, so a study declares it once however
        many participants answer under it: the first declaration is accepted and
        every later one is a no-effect rejection of the same bytes.
        """
        receipt = await commit_command(
            context,
            command=_DECLARE,
            new_state=_state(protocol),
            result=_typed(protocol),
            store=self._store,
        )
        return receipt, protocol

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
        assignment_id: str,
        choice: str,
        presented_order: Sequence[str],
        submitted_at: UtcInstant,
        receipt_required: bool = False,
        verdict: str | None = None,
        ratings: Sequence[DimensionRating] = (),
    ) -> tuple[CommandReceipt, PreferenceResponse]:
        """Record the participant's choice over the order they were shown.

        The response is its own aggregate, and its identifier body is the
        assignment's, so one assignment has one response and a reader joins the two
        by name. That existence guard is what makes a participant respond once: an
        identical retry replays to the same receipt, and a different second response
        finds the aggregate taken and is refused with no effect. Keeping it off the
        assignment is what keeps the assignment readable -- a store holds one state
        per aggregate, and a response written over it would take the enrollment, the
        seed commitment, and the blinding with it. The record enforces that the
        choice was one of the presented candidates.

        ``verdict`` says what the participant meant by the choice. A tie or a
        both-bad verdict still names a choice, because the choice is what the
        response resolves to -- in a live conversation, the reply the thread went
        on with. ``ratings`` are the per-dimension answers the protocol asked for,
        each naming the candidate it is about.
        """
        if self._store.load_aggregate(assignment_id) is None:
            raise UnknownAssignment(assignment_id)
        response = PreferenceResponse(
            response_id=context.aggregate_id,
            assignment_id=assignment_id,
            choice=choice,
            presented_order=list(presented_order),
            verdict=_verdict_of(verdict),
            ratings=list(ratings) or None,
            receipt_required=receipt_required,
            submitted_at=submitted_at,
        )
        receipt = await commit_command(
            context,
            command=_RESPOND,
            new_state=_state(response),
            result=_typed(response),
            store=self._store,
        )
        return receipt, response

    async def attest_quality(
        self,
        *,
        context: CommandContext,
        assignment_id: str,
        attention_check_passed: bool,
        response_time_ms: int,
        flagged: bool = False,
    ) -> tuple[CommandReceipt, QualityEvidence]:
        """Record the per-response quality signals, on the evidence's own aggregate.

        The attestation names the response by the assignment it answers, so the
        caller does not repeat it, and writes to the aggregate the caller's context
        names -- **which is neither of them**. A store holds the latest state of an
        aggregate, so an attestation written over the response would overwrite the
        recorded choice, and the judgement would leave the platform as a digest of
        something nobody holds. Every record heads its own aggregate, and they are
        joined by identifier exactly as every other pair of records is.

        One attestation is recorded per response, which the aggregate's own
        existence guard gives: a retry of the same command replays, and a second,
        different attestation is refused. An attestation before the response exists
        is refused too.
        """
        if self._store.load_aggregate(assignment_id) is None:
            raise UnknownAssignment(assignment_id)
        response_id = response_id_for(assignment_id)
        if self._store.load_aggregate(response_id) is None:
            raise ResponseRequired(assignment_id)
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
        )
        return receipt, quality


def _verdict_of(verdict: str | None) -> Literal["choice", "tie", "both-bad"] | None:
    """Return the verdict a response records, leaving the plain choice unstated.

    ``choice`` is what an absent verdict means, so a plain preference writes no
    field and every response recorded before verdicts existed still reads right.
    """
    if verdict is None or verdict == "choice":
        return None
    if verdict in ("tie", "both-bad"):
        return verdict
    raise ValueError(f"unknown verdict: {verdict!r}")


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
    "response_id_for",
]
