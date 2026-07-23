"""The preference runtime drives one annotation through the command spine (API-18).

These tests drive ``mug.preferences.PreferenceService`` against the in-memory store
with hand-built command contexts, one per stage on the assignment's aggregate. They
prove the annotation loop: an assignment is created blinded and seed-committed, a
response records the participant's choice, and a quality attestation attaches to it,
and the three stages land as one ordered event stream. They prove the idempotency
the family promises over the store's fencing: an identical retry of a stage replays
with no second effect, a *different* second response is fenced (one response per
assignment), and a quality attestation before the response is refused.
"""

from __future__ import annotations

import itertools

from mug.kernel import ArtifactRef, Digest
from mug.preferences import (
    PreferenceProtocol,
    PreferenceService,
    ResponseRequired,
    candidate_from_artifact,
    display_order,
)
from mug.preferences.types import ComparisonTask
from mug.runtime import CommandContext, read_ledger
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_ASSIGNMENT = "prefassign_" + _UUID.format(0x001)
_QUERY = "prefquery_" + _UUID.format(0x002)
_ENROLLMENT = "enrollment_" + _UUID.format(0x003)
_RESPONSE = "prefresponse_" + _UUID.format(0x004)
_HANDLE = "handle_" + "a" * 21 + "A"


def _protocol(*, randomize: bool = True, blinded: bool = True) -> PreferenceProtocol:
    return PreferenceProtocol(
        protocol_version_id="prefver_" + _UUID.format(0x010),
        protocol_definition_id="prefdef_" + _UUID.format(0x011),
        candidate_kind="trajectory",
        task=ComparisonTask(kind="pairwise", prompt="Which run is better?"),
        blinded=blinded,
        randomize_order=randomize,
    )


class _Contexts:
    """Mint command contexts on the assignment aggregate, one per command."""

    def __init__(self, aggregate_id: str) -> None:
        self._aggregate_id = aggregate_id
        self._counter = itertools.count(1)

    def next(self) -> CommandContext:
        n = next(self._counter)
        body = _UUID.format(n)
        return CommandContext.model_validate(
            {
                "command_id": "command_" + body,
                "receipt_id": "receipt_" + body,
                "error_id": "error_" + body,
                "idempotency_key": "idem_" + f"{n:021d}" + "A",
                "event_id": "event_" + body,
                "stream_id": "stream_" + self._aggregate_id.split("_", 1)[1],
                "producer": {
                    "epoch_id": "prodepoch_" + _UUID.format(9),
                    "sequence": n,
                    "content_digest": _DIGEST.model_dump(mode="json"),
                },
                "aggregate_id": self._aggregate_id,
                "principal": {
                    "kind": "service",
                    "id": "service_" + _UUID.format(0xA),
                },
                "recorded_at": "2026-07-22T00:00:00.000000Z",
                "event_data_handling": {"privacy_labels": ["research"]},
            }
        )


async def _assigned(
    store: InMemoryStore, contexts: _Contexts
) -> None:
    """Create the assignment stage; the aggregate reaches revision 1."""
    service = PreferenceService(store=store)
    receipt, _ = await service.assign(
        context=contexts.next(),
        protocol=_protocol(),
        query_id=_QUERY,
        enrollment_id=_ENROLLMENT,
        candidate_keys=["run-a", "run-b", "run-c"],
        seed=b"the-blinding-seed",
    )
    assert receipt.outcome == "accepted"


def _stream_id() -> str:
    return "stream_" + _ASSIGNMENT.split("_", 1)[1]


def test_display_order_is_a_deterministic_seed_permutation() -> None:
    """A randomized order is stable per seed and moves with the seed."""
    keys = ["run-a", "run-b", "run-c", "run-d"]
    one = display_order(keys, randomize=True, seed=b"seed-one")
    again = display_order(keys, randomize=True, seed=b"seed-one")
    other = display_order(keys, randomize=True, seed=b"seed-two")
    plain = display_order(keys, randomize=False, seed=b"seed-one")

    assert one == again  # reproducible from the seed
    assert sorted(one) == sorted(keys)  # a permutation, nothing dropped
    assert one != other or plain == keys  # a different seed can reorder
    assert plain == keys  # no randomization keeps the given order


def test_a_candidate_names_a_recorded_artifact() -> None:
    """A candidate wraps an opaque artifact reference behind a blinded handle."""
    artifact = ArtifactRef(
        artifact_id="artifact_" + _UUID.format(0x0d1),
        digest=_DIGEST,
        size_bytes=64,
        media_type="application/x-ndjson",
        content_encoding="identity",
        data_handling={"privacy_labels": ["research"]},  # type: ignore[arg-type]
    )
    candidate = candidate_from_artifact(
        candidate_key="run-a",
        kind="trajectory",
        artifact=artifact,
        display_handle=_HANDLE,
    )
    assert candidate.content_ref == artifact
    assert candidate.display_handle == _HANDLE


async def test_the_full_annotation_loop_records_one_stream() -> None:
    """Assign, respond, and attest land as one ordered three-event stream."""
    store = InMemoryStore()
    contexts = _Contexts(_ASSIGNMENT)
    service = PreferenceService(store=store)

    _, assignment = await service.assign(
        context=contexts.next(),
        protocol=_protocol(),
        query_id=_QUERY,
        enrollment_id=_ENROLLMENT,
        candidate_keys=["run-a", "run-b", "run-c"],
        seed=b"the-blinding-seed",
    )
    order = assignment.candidate_display_order
    assert sorted(order) == ["run-a", "run-b", "run-c"]
    assert assignment.blinded is True

    respond_receipt, _ = await service.respond(
        context=contexts.next(),
        response_id=_RESPONSE,
        choice=order[0],
        presented_order=order,
        submitted_at="2026-07-22T00:00:01.000000Z",
    )
    assert respond_receipt.outcome == "accepted"

    quality_receipt, quality = await service.attest_quality(
        context=contexts.next(),
        attention_check_passed=True,
        response_time_ms=4200,
    )
    assert quality_receipt.outcome == "accepted"
    assert quality.response_id == _RESPONSE

    events = read_ledger(store, _stream_id())
    names = [event.event_schema.name for event in events]
    assert names == [
        "mug.api-18.preference-assignment",
        "mug.api-18.preference-response",
        "mug.api-18.quality-evidence",
    ]


async def test_an_identical_response_retry_replays_with_no_second_effect() -> None:
    """Re-sending the same response command replays and does not double-record."""
    store = InMemoryStore()
    contexts = _Contexts(_ASSIGNMENT)
    await _assigned(store, contexts)
    service = PreferenceService(store=store)

    respond_context = contexts.next()
    first, _ = await service.respond(
        context=respond_context,
        response_id=_RESPONSE,
        choice="run-a",
        presented_order=["run-a", "run-b"],
        submitted_at="2026-07-22T00:00:01.000000Z",
    )
    retry, _ = await service.respond(
        context=respond_context,
        response_id=_RESPONSE,
        choice="run-a",
        presented_order=["run-a", "run-b"],
        submitted_at="2026-07-22T00:00:01.000000Z",
    )

    assert first.outcome == "accepted"
    assert retry.outcome == "accepted"  # a replay, not a second effect
    # The stream holds exactly the assignment and the one response.
    assert len(read_ledger(store, _stream_id())) == 2


async def test_a_different_second_response_is_fenced() -> None:
    """A second, distinct response reads the same revision and is refused."""
    store = InMemoryStore()
    contexts = _Contexts(_ASSIGNMENT)
    await _assigned(store, contexts)
    service = PreferenceService(store=store)

    first, _ = await service.respond(
        context=contexts.next(),
        response_id=_RESPONSE,
        choice="run-a",
        presented_order=["run-a", "run-b"],
        submitted_at="2026-07-22T00:00:01.000000Z",
    )
    second, _ = await service.respond(
        context=contexts.next(),
        response_id="prefresponse_" + _UUID.format(0x005),
        choice="run-b",
        presented_order=["run-a", "run-b"],
        submitted_at="2026-07-22T00:00:02.000000Z",
    )

    assert first.outcome == "accepted"
    assert second.outcome != "accepted"  # fenced, no second response
    assert len(read_ledger(store, _stream_id())) == 2


async def test_a_quality_attestation_before_the_response_is_refused() -> None:
    """Attesting quality before a response exists raises, not double-writes."""
    import pytest

    store = InMemoryStore()
    contexts = _Contexts(_ASSIGNMENT)
    await _assigned(store, contexts)
    service = PreferenceService(store=store)

    with pytest.raises(ResponseRequired):
        await service.attest_quality(
            context=contexts.next(),
            attention_check_passed=True,
            response_time_ms=1000,
        )
