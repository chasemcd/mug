"""``build_decision_tape`` assembles a valid API-16 tape from recorded calls.

These tests build the decision tape from the ``ModelCallResult`` of each model call
an episode made, and prove it: one ordered model-output entry per completed call, a
call that recorded no output skipped, and the whole record valid against the frozen
API-16 ``decision-tape`` schema so it drops straight into a replay bundle.
"""

from __future__ import annotations

from mug.kernel import Digest
from mug.providers import ModelCallResult, ProviderError, ProviderResponse, Usage
from mug.replay import DecisionTape, build_decision_tape, replay_schema
from mug.replay.types import ModelOutputTapeEntry

_UUID = "019b6000-0000-7000-8000-{:012x}"
_INTERACTION = "interaction_" + _UUID.format(0x420)


def _entries(tape: DecisionTape) -> list[ModelOutputTapeEntry]:
    """Narrow the tape to its model-output entries (the only kind built here)."""
    return [e for e in tape.entries if isinstance(e, ModelOutputTapeEntry)]


def _digest(tag: int) -> Digest:
    return Digest(algorithm="sha-256", hex=f"{tag:02x}" * 32)


def _completed(tag: int) -> ModelCallResult:
    modelcall_id = "modelcall_" + _UUID.format(0xC00 + tag)
    response = ProviderResponse(
        modelcall_id=modelcall_id,
        generation_id="generation_" + _UUID.format(tag),
        outcome="completed",
        resolved_model="fake",
        usage=Usage(input_tokens=1, output_tokens=1, cost_micros=1),
        output_digest=_digest(tag),
        completed_at="2026-07-22T00:00:00.000000Z",
    )
    return ModelCallResult(
        modelcall_id=modelcall_id,
        request=None,
        response=response,
        error=None,
        output={"text": f"reply {tag}"},
    )


def _errored(tag: int) -> ModelCallResult:
    modelcall_id = "modelcall_" + _UUID.format(0xC00 + tag)
    return ModelCallResult(
        modelcall_id=modelcall_id,
        request=None,
        response=None,
        error=ProviderError(
            modelcall_id=modelcall_id, error_class="rate-limit", retryable=True
        ),
    )


def test_the_tape_has_one_ordered_entry_per_completed_call() -> None:
    """Each completed call is a model-output entry, in call order."""
    tape = build_decision_tape(
        interaction_id=_INTERACTION,
        results=[_completed(1), _completed(2), _completed(3)],
    )

    assert [entry.modelcall_id for entry in _entries(tape)] == [
        "modelcall_" + _UUID.format(0xC01),
        "modelcall_" + _UUID.format(0xC02),
        "modelcall_" + _UUID.format(0xC03),
    ]
    assert [entry.output_digest for entry in _entries(tape)] == [
        _digest(1),
        _digest(2),
        _digest(3),
    ]


def test_a_call_with_no_output_is_skipped() -> None:
    """An error (or a call that recorded no output) contributes no entry."""
    tape = build_decision_tape(
        interaction_id=_INTERACTION,
        results=[_completed(1), _errored(2), _completed(3)],
    )

    assert len(tape.entries) == 2
    assert [entry.modelcall_id for entry in _entries(tape)] == [
        "modelcall_" + _UUID.format(0xC01),
        "modelcall_" + _UUID.format(0xC03),
    ]


def test_the_tape_validates_against_the_frozen_api16_schema() -> None:
    """The built record drops into a replay bundle: it is schema-valid."""
    tape = build_decision_tape(
        interaction_id=_INTERACTION, results=[_completed(1), _completed(2)]
    )

    instance = tape.model_dump(mode="json", exclude_none=True)
    assert replay_schema().is_valid("DecisionTape", instance)


def test_a_call_names_the_tools_it_drove() -> None:
    """A model call maps to its tool-call ids; a call with no tools stays empty."""
    tool_id = "toolcall_" + _UUID.format(0xD01)
    tape = build_decision_tape(
        interaction_id=_INTERACTION,
        results=[_completed(1), _completed(2)],
        tool_calls={"modelcall_" + _UUID.format(0xC01): [tool_id]},
    )

    entries = _entries(tape)
    assert entries[0].tool_call_ids == [tool_id]
    assert entries[1].tool_call_ids == []
    assert replay_schema().is_valid(
        "DecisionTape", tape.model_dump(mode="json", exclude_none=True)
    )
