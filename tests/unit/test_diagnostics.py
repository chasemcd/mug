"""The notes a run keeps about itself: bounded, ordered, and plain.

A note is written from inside a frame loop, a provider call, and a room watcher.
None of those is a place to raise, none is a place to wait, and none is a place to
grow without a bound. So what is asked here is the three properties that make it
safe to write a note from anywhere:

- it is **bounded**, in count and in the length of one field, so a study left
  running all day holds the last few minutes rather than the whole day;
- it is **plain**, so whatever a call site had in its hand renders as JSON and a
  live environment is never walked into a reader's screen;
- it **cannot fail**, so a field that fights back costs a note and never a run.

And the fourth, which is not about safety but about honesty: a reader that has
fallen behind the ring is **told**, rather than left to read the gap as a run that
went quiet.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import json
from typing import Any

from mug.diagnostics import NullDiagnostics, RecordingDiagnostics


def test_the_default_sink_keeps_nothing() -> None:
    """A run nobody is watching writes nothing down and says so.

    Every call site writes a note unconditionally, so the do-nothing case is what
    almost every run takes. It must also say it is not watched, so a call site does
    not build a costly field for a reader that does not exist.
    """
    quiet = NullDiagnostics()
    quiet.note("model.call", subject="chef", payload={"messages": []})

    assert quiet.watching is False


def test_the_notes_are_ordered_and_asked_for_by_sequence() -> None:
    """A reader asks for what came after what it has seen, and gets that.

    It is what makes a panel that polls twice a second cheap: the answer holds the
    notes written between the polls and never the whole run again.
    """
    watching = RecordingDiagnostics()
    for index in range(5):
        watching.note("agent.turn", subject="chef", index=index)

    read = watching.since(3)

    assert [one["fields"]["index"] for one in read["notes"]] == [3, 4]
    assert read["written"] == 5


def test_the_ring_is_bounded_and_says_what_it_dropped() -> None:
    """Past the bound the oldest notes fall out, and a reader is told they did.

    A reader that asks for everything after sequence 2 and is given notes from 99
    onward must be able to see that it missed some. Without ``first_held`` it
    renders the gap as a run that went quiet, which is the one reading a debugging
    aid must never invite.
    """
    watching = RecordingDiagnostics(keep=10)
    for index in range(100):
        watching.note("agent.turn", index=index)

    read = watching.since(2)

    assert len(read["notes"]) == 10, "the ring kept more than it was told to keep"
    assert read["first_held"] > 3, (
        "a reader that asked for everything after note 2 was given notes from "
        f"{read['first_held']} and nothing said so"
    )
    assert read["written"] == 100


def test_a_long_field_is_cut_and_the_cut_is_said() -> None:
    """A prompt is cut to a length a person reads, and never silently.

    A prompt carries a whole transcript and an environment view. A few hundred of
    them at full length is tens of megabytes in a process that is only watching. But
    a cut prompt that reads as a whole one is worse than no prompt at all: somebody
    would read a truncated conversation as the conversation the model was given.
    """
    watching = RecordingDiagnostics(field_limit=100)
    watching.note("model.call", payload="x" * 500)

    written = watching.since(0)["notes"][0]["fields"]["payload"]

    assert len(written) < 200
    assert "400 more characters" in written


def test_every_field_renders_as_json() -> None:
    """Whatever a call site had in its hand comes out as plain data.

    A call site passes what it has, and what it has includes a live environment, an
    exception, and a study's own objects. None of those is JSON, and a panel that
    receives one gets nothing at all -- so they become their own text here rather
    than at the moment the reader asks.
    """

    class Kitchen:
        def __repr__(self) -> str:
            return "<a live environment>"

    watching = RecordingDiagnostics()
    watching.note(
        "round.start",
        subject="interaction_1",
        env=Kitchen(),
        seats=["chef", "partner"],
        usage={"input_tokens": 12, "output_tokens": 3},
        frames=40,
        ended=False,
        nothing=None,
    )

    fields: dict[str, Any] = watching.since(0)["notes"][0]["fields"]

    json.dumps(fields)  # it renders, or this raises
    assert fields["env"] == "<a live environment>"
    assert fields["seats"] == ["chef", "partner"]
    assert fields["usage"]["input_tokens"] == 12
    assert fields["nothing"] is None


def test_a_field_that_fights_back_costs_a_note_and_not_the_run() -> None:
    """A note is written from inside a frame loop, so it may never raise.

    A study must not fail because the thing watching it did. What is kept is the
    fact that a note could not be read, which is more than the run would have if
    the exception had been allowed out.
    """

    class Awkward:
        def __repr__(self) -> str:
            raise RuntimeError("no")

    watching = RecordingDiagnostics()
    watching.note("model.call", payload=Awkward())

    read = watching.since(0)["notes"]
    assert len(read) == 1
    assert "unreadable" in read[0]["fields"]


def test_a_cleared_panel_never_reads_two_notes_under_one_number() -> None:
    """Forgetting what is held does not reset the numbering.

    Two readers of one process -- a panel somebody cleared and a script that did not
    -- must never be given two different notes under one sequence, or the one that
    polls by sequence silently skips whatever the other one caused.
    """
    watching = RecordingDiagnostics()
    watching.note("agent.turn", index=0)
    watching.clear()
    watching.note("agent.turn", index=1)

    read = watching.since(0)["notes"]

    assert [one["sequence"] for one in read] == [2]
