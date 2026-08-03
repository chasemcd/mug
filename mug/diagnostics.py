"""What a run says about itself while it is running: the notes behind a decision.

``mug.observability`` is what an **operator** reads: counts, gauges, and one log line
per event, labelled with nothing that identifies anybody. This is what the person
**running the study** reads, and it is a different thing. When a model partner stands
still for a whole round, the counters say a decision was made and say nothing about
why the kitchen did not move. The question is always one of these:

- was the seat asked at all, or did its cadence not come round?
- what was it asked? A prompt with an empty transcript is a different fault from a
  prompt the model refused.
- what came back, how long did it take, and what did it cost?
- could an action be read out of the reply, or did the seat fall back?
- did it say anything, or was silence the answer?

None of that is in the ledger in a form anybody can read while the game is on, and by
the time it is, the round is over. So a run keeps its own notes.

**A note is not a record.** Nothing here is persisted, exported, replayed, or
digested; no note enters a canonical event and no schema names one. It is a debugging
aid, so its shape may change whenever a better one is found -- the same rule
``mug.observability`` follows for a trace context. What is in the ledger stays the
evidence; this is what a person watches.

**A note never carries a credential.** The one field a model call has that must not
be read is the resolved secret, and the rule that keeps it out is the one the whole
platform follows: a note names a credential and never values it. The call sites hold
a resolver rather than a value, so there is no value at hand to write down by
accident, and a test asserts it.

**Off unless a process is told otherwise.** A note holds prompts, replies, and what a
participant said, so the notes of a running study are not a participant's to read: a
deception study's prompt says what the deception is. Nothing is kept and nothing is
served until a process is started in debug mode (``build_study_app(debug=True)`` or
``MUG_DEBUG=1``), and the default sink discards everything it is given.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"

# How many notes one process keeps. A note is small, and the count is what bounds the
# memory: past this the oldest are dropped, so a study left running all day holds the
# last few minutes rather than the whole day.
KEEP = 2000

# How long one field may be. A prompt carries a whole transcript and an environment
# view, and a few hundred of them at full length is tens of megabytes. What is cut is
# said, so a reader never mistakes a cut prompt for a short one.
FIELD_LIMIT = 8000

# How deep a structured field is copied before it becomes its own text. It is the
# depth of the shapes a call site really passes -- a usage record, a mapping of seats
# to actions -- and it stops a live environment from being walked.
_DEPTH = 4


@dataclass(frozen=True)
class Note:
    """One thing that happened, as the person running the study would ask about it.

    ``kind`` names it in a dotted form (``model.call``, ``agent.action``), so a reader
    filters on a family. ``subject`` is what it is about -- a seat, an activity, a
    channel -- and is empty when it is about the process. ``fields`` is plain data:
    every value is a string, a number, a boolean, ``None``, or a list or mapping of
    those, so the whole note renders as JSON with nothing to escape it.
    """

    sequence: int
    at: str
    kind: str
    subject: str
    fields: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        """Render the note as the plain object a reader receives."""
        return {
            "sequence": self.sequence,
            "at": self.at,
            "kind": self.kind,
            "subject": self.subject,
            "fields": self.fields,
        }


class Diagnostics(Protocol):
    """The sink a call site writes a note to. One verb, and it cannot fail.

    A note is written from inside a frame loop, a provider call, and a room watcher.
    None of those is a place to raise and none is a place to wait, so writing a note
    must never do either: a study must not fail because the thing watching it did.
    """

    def note(self, kind: str, /, subject: str = "", **fields: Any) -> None:
        """Write down one thing that happened."""
        ...

    @property
    def watching(self) -> bool:
        """Say whether anybody is reading, so a costly field is not built for nobody.

        Almost every field a call site writes is already in its hand. A few are not:
        naming an action means asking the study for its action names, and rendering a
        seat's view means asking the study to render one. Those are asked for only
        when somebody is going to read the answer.
        """
        ...


class NullDiagnostics:
    """A sink that discards everything: the default, so nothing has to check.

    Every call site takes a ``Diagnostics`` and writes unconditionally. Making the
    do-nothing case an object rather than a ``None`` check keeps the watched path the
    same shape as the unwatched one, which is what keeps the two from drifting apart.
    """

    def note(self, kind: str, /, subject: str = "", **fields: Any) -> None:
        return None

    @property
    def watching(self) -> bool:
        return False


class RecordingDiagnostics:
    """Keep the last notes in the process, and hand them to a reader in order.

    The notes are a ring: the newest ``keep`` of them are held and the oldest fall
    out. A reader asks for what it has not seen by sequence, so a panel that polls
    twice a second is told what happened between the polls and nothing again.

    **What was dropped is said.** A reader that asks for everything after sequence 40
    and is given notes from 900 onward must be told, or it renders a gap as though
    the run went quiet. ``since`` answers with the first sequence it still holds.
    """

    def __init__(self, *, keep: int = KEEP, field_limit: int = FIELD_LIMIT) -> None:
        self._notes: deque[Note] = deque(maxlen=keep)
        self._limit = field_limit
        self._written = 0

    @property
    def watching(self) -> bool:
        """A recording sink is always read: it exists because somebody asked for it."""
        return True

    def note(self, kind: str, /, subject: str = "", **fields: Any) -> None:
        """Write down one thing that happened, with its fields made plain.

        Nothing here raises. A field that cannot be made plain becomes its own text,
        which is worth more to a reader than an exception thrown out of a frame loop.
        """
        self._written += 1
        try:
            plain = {name: _plain(value, self._limit) for name, value in fields.items()}
        except Exception as error:  # pragma: no cover - a field that fights back
            plain = {"unreadable": f"{type(error).__name__}"}
        self._notes.append(
            Note(
                sequence=self._written,
                at=datetime.now(timezone.utc).strftime(_INSTANT),
                kind=kind,
                subject=subject,
                fields=plain,
            )
        )

    def since(self, sequence: int) -> dict[str, Any]:
        """Return every note after one sequence, and say what is no longer held.

        ``first_held`` is the oldest sequence still in the ring. A reader whose
        ``sequence`` is below it has missed notes, and reads that from the answer
        rather than from a gap it cannot see.
        """
        held = list(self._notes)
        return {
            "notes": [one.as_json() for one in held if one.sequence > sequence],
            "first_held": held[0].sequence if held else self._written + 1,
            "written": self._written,
        }

    def snapshot(self) -> dict[str, Any]:
        """Return every note now held, oldest first."""
        return self.since(0)

    def clear(self) -> None:
        """Forget every note held, and keep counting from where the sequence is.

        The sequence goes on rising, so a reader that clears the panel and one that
        did not are never given two different notes under one number.
        """
        self._notes.clear()


def _plain(value: Any, limit: int, depth: int = 0) -> Any:
    """Return one field value as plain data, bounded in both depth and length.

    A live environment, a controller, and an exception all reach this, because a call
    site passes what it has. Anything that is not already plain becomes its own text,
    and every text is bounded: a note is read by a person, and the first eight
    thousand characters of a prompt is what they read.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _short(value, limit)
    if depth >= _DEPTH:
        return _short(str(value), limit)
    if isinstance(value, dict):
        return {
            str(name): _plain(one, limit, depth + 1)
            for name, one in list(value.items())[:64]  # pyright: ignore[reportUnknownArgumentType]
        }
    if isinstance(value, (list, tuple)):
        return [_plain(one, limit, depth + 1) for one in list(value)[:64]]  # pyright: ignore[reportUnknownArgumentType]
    return _short(str(value), limit)


def _short(text: str, limit: int) -> str:
    """Cut one text to the limit, and say how much was cut."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... [{len(text) - limit} more characters]"


__all__ = [
    "FIELD_LIMIT",
    "KEEP",
    "Diagnostics",
    "Note",
    "NullDiagnostics",
    "RecordingDiagnostics",
]
