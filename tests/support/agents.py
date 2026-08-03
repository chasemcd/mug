"""Shared help for a test that stands in for a model provider.

A study's adapter is handed every call the platform makes, and not all of them are
decisions. Before a round starts, the platform reaches each model seat once: it
loads the model into the runner and finds out that the provider answers, so an
unreachable provider is known before a participant is looking at a game rather than
drawn as a partner that never moves.

An adapter for a real provider does not care -- a call is a call. An adapter that
answers **by sequence** does, and every double here is one: a warm-up would take the
first scripted answer, and every answer after it would be one behind. So a double
answers a warm-up trivially and counts only what the study asked for.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from mug.providers import ModelCall, ModelCompletion, Usage

_NO_USAGE = Usage(input_tokens=0, output_tokens=0, cost_micros=0)


def warming(call: ModelCall) -> bool:
    """Return whether this call is the platform warming the model up."""
    return call.purpose == "warm-up"


def warmed(model: str = "fake-local") -> ModelCompletion:
    """Return the trivial answer a double gives a warm-up.

    Nothing reads it: the platform asks only whether the provider answered, and it
    reflects on nothing and takes nothing from the reply.
    """
    return ModelCompletion(
        outcome="completed",
        resolved_model=model,
        usage=_NO_USAGE,
        output={"text": "READY"},
    )


__all__ = ["warmed", "warming"]
