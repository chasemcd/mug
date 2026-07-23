"""Build the API-16 decision tape from an episode's recorded model calls.

The ``DecisionTape`` (``mug.replay.types``) is the ordered manifest of the model
outputs a replay applies: one ``ModelOutputTapeEntry`` per completed model call,
naming the call and the digest of its output. It is the frozen record that binds a
replay bundle's decisions; the verbatim outputs it references live on the durable
output tape (``mug.providers.OutputTape``), keyed by the same digest.

This builder assembles the tape from the recorded ``ModelCallResult`` of each call,
in the order the episode made them. It lives in ``mug.replay`` (above the provider),
so it is built at export or replay time from recorded data, not during the episode.

A model call may drive one or more tool calls (API-14). The builder takes an optional
map from a model-call id to the tool-call ids that call produced, so a tape names the
tools a decision used. A call that drove no tool -- every call on the current agent
path -- names an empty list, which is the honest empty case, not a stub.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from mug.providers import ModelCallResult
from mug.replay.types import DecisionTape, ModelOutputTapeEntry, TapeEntry

# A map from one model-call id to the tool-call ids that call produced.
ToolCallsByModelCall = Mapping[str, Sequence[str]]


def model_output_entry(
    result: ModelCallResult,
    *,
    tool_calls: ToolCallsByModelCall | None = None,
) -> ModelOutputTapeEntry | None:
    """Return the tape entry for one completed model call, or None for the rest.

    A call with no recorded completed response -- an error, a refusal, or a call
    that recorded no output -- contributes no model-output entry. ``tool_calls`` maps
    a model-call id to the tools that call drove; a call absent from the map, or a
    ``None`` map, names no tool call.
    """
    response = result.response
    if response is None or response.output_digest is None:
        return None
    ids = list(tool_calls.get(result.modelcall_id, ())) if tool_calls else []
    return ModelOutputTapeEntry(
        kind="model-output",
        modelcall_id=result.modelcall_id,
        output_digest=response.output_digest,
        tool_call_ids=ids,
    )


def build_decision_tape(
    *,
    interaction_id: str,
    results: Sequence[ModelCallResult],
    tool_calls: ToolCallsByModelCall | None = None,
) -> DecisionTape:
    """Assemble the ordered API-16 decision tape for one interaction's model calls.

    Each completed call becomes one model-output entry, in call order; a call that
    recorded no output is skipped. ``tool_calls`` maps a model-call id to the tools
    that call drove, so a tape names a decision's tool use; it defaults to none. The
    result validates against the frozen API-16 ``decision-tape`` schema, so it drops
    straight into a replay bundle.
    """
    entries: list[TapeEntry] = [
        entry
        for result in results
        if (entry := model_output_entry(result, tool_calls=tool_calls)) is not None
    ]
    return DecisionTape(interaction_id=interaction_id, entries=entries)


__all__ = ["ToolCallsByModelCall", "build_decision_tape", "model_output_entry"]
