"""The author writes one ``Comparison``; MUG runs the whole annotation from it.

These tests prove the author surface: a study author declares a `Comparison` with a
question and two labelled recorded runs -- no ids, seeds, handles, or protocol
objects -- and `compile_comparison` turns it into the blinded, randomized records
the annotation loop drives. The compiled protocol carries the author's question and
blind/shuffle choices, each option becomes a blinded candidate over its artifact,
and the author's labels are kept for analysis while the participant sees only
handles. A final test drives a whole participant through the compiled comparison.
"""

from __future__ import annotations

import itertools

from mug.authoring import Comparison
from mug.kernel import ArtifactRef, Digest
from mug.preferences import (
    ComparisonIds,
    PreferenceService,
    compile_comparison,
)
from mug.runtime import CommandContext, read_ledger
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_ASSIGNMENT = "prefassign_" + _UUID.format(0x001)


def _artifact(tag: int) -> ArtifactRef:
    return ArtifactRef(
        artifact_id="artifact_" + _UUID.format(0xD00 + tag),
        digest=_DIGEST,
        size_bytes=64,
        media_type="application/x-ndjson",
        content_encoding="identity",
        data_handling={"privacy_labels": ["research"]},  # type: ignore[arg-type]
    )


def _ids() -> ComparisonIds:
    return ComparisonIds(
        protocol_version_id="prefver_" + _UUID.format(0x010),
        protocol_definition_id="prefdef_" + _UUID.format(0x011),
    )


def _handle_minter() -> object:
    counter = itertools.count(1)

    def mint() -> str:
        n = next(counter)
        return "handle_" + f"{n:021d}"[:21] + "A"

    return mint


def test_a_comparison_needs_only_a_question_and_two_runs() -> None:
    """The author writes one object; the defaults blind and shuffle it."""
    comparison = Comparison(
        key="which-chef",
        ask="Which chef cooked better?",
        options={"Policy A": _artifact(1), "Policy B": _artifact(2)},
    )
    assert comparison.blind is True  # blinded by default
    assert comparison.shuffle is True  # shuffled by default
    assert comparison.style == "compare"


def test_compile_turns_the_comparison_into_blinded_records() -> None:
    """One author object compiles into a protocol and one candidate per option."""
    runs = {"Policy A": _artifact(1), "Policy B": _artifact(2)}
    comparison = Comparison(
        key="which-chef", ask="Which chef cooked better?", options=runs
    )

    compiled = compile_comparison(
        comparison,
        ids=_ids(),
        resolve=lambda run: run,  # type: ignore[arg-type,return-value]
        new_handle=_handle_minter(),  # type: ignore[arg-type]
    )

    # The protocol carries the author's question and their blind/shuffle choices.
    assert compiled.protocol.task.prompt == "Which chef cooked better?"
    assert compiled.protocol.task.kind == "pairwise"  # 'compare' -> pairwise
    assert compiled.protocol.blinded is True
    # One candidate per option, keyed by an id-safe slug of the author's label.
    assert compiled.candidate_keys == ["policy-a", "policy-b"]
    assert compiled.labels == {"policy-a": "Policy A", "policy-b": "Policy B"}
    # The participant sees a blinded handle, not the author's label.
    for candidate in compiled.candidates:
        assert candidate.display_handle.startswith("handle_")
    # Each candidate names the artifact its recorded run lives in.
    assert compiled.candidates[0].content_ref == runs["Policy A"]


async def test_a_participant_runs_the_compiled_comparison_end_to_end() -> None:
    """The compiled comparison drives a whole assign -> respond -> attest loop."""
    comparison = Comparison(
        key="which-chef",
        ask="Which chef cooked better?",
        options={"Policy A": _artifact(1), "Policy B": _artifact(2)},
    )
    compiled = compile_comparison(
        comparison,
        ids=_ids(),
        resolve=lambda run: run,  # type: ignore[arg-type,return-value]
        new_handle=_handle_minter(),  # type: ignore[arg-type]
    )

    store = InMemoryStore()
    contexts = _Contexts(_ASSIGNMENT)
    service = PreferenceService(store=store)

    _, assignment = await service.assign(
        context=contexts.next(),
        protocol=compiled.protocol,
        query_id="prefquery_" + _UUID.format(0x002),
        enrollment_id="enrollment_" + _UUID.format(0x003),
        candidate_keys=compiled.candidate_keys,
        seed=b"per-participant-seed",
    )
    order = assignment.candidate_display_order
    respond_receipt, _ = await service.respond(
        context=contexts.next(),
        response_id="prefresponse_" + _UUID.format(0x004),
        choice=order[0],
        presented_order=order,
        submitted_at="2026-07-22T00:00:05.000000Z",
    )
    quality_receipt, _ = await service.attest_quality(
        context=contexts.next(),
        attention_check_passed=True,
        response_time_ms=4200,
    )

    assert respond_receipt.outcome == "accepted"
    assert quality_receipt.outcome == "accepted"
    stream_id = "stream_" + _ASSIGNMENT.split("_", 1)[1]
    assert len(read_ledger(store, stream_id)) == 3


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
