"""What a study binds: one key, or a sequence of keys held together.

A key binding is the smallest thing a participant does, and the two shapes it
takes are different in kind rather than in degree: one key pressed, or several
held at once. This module owns both, so the game specification and the stepping
loop can each read them without either having to know about the other.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# What a study writes: one key, or a **sequence of keys held together**, mapped to
# the action it means.
#
#     ACTION_BINDINGS = {
#         "ArrowLeft": LEFT,
#         ("ArrowUp", "ArrowLeft"): UPLEFT,
#     }
#
# A chord is a sequence because that is what it is. It was once written as one
# name with a ``+`` in it, which made a chord a string a reader had to parse, put a
# character with a meaning inside a key name, and could not say what the platform's
# own key-name rule already forbids.
Chord = tuple[str, ...]

# A study writes one of three shapes, and all three are bindings: only single keys,
# only chords, or a mixture. They are spelled out because a mapping is invariant in
# its key, so a plain ``dict[str, int]`` -- what most studies write -- is not a
# ``Mapping[str | Chord, int]`` to a type checker.
Bindings = Mapping[str, int] | Mapping[Chord, int] | Mapping[str | Chord, int]


def chord_of(binding: str | Chord) -> Chord:
    """Return one binding as the sequence of keys it is, single or chorded."""
    return (binding,) if isinstance(binding, str) else tuple(binding)


def single_keys(bindings: Bindings) -> dict[str, int]:
    """Return the bindings that are one key, by that key."""
    return {
        chord_of(binding)[0]: action
        for binding, action in bindings.items()
        if len(chord_of(binding)) == 1
    }


def chords(bindings: Bindings) -> list[dict[str, Any]]:
    """Return the bindings that are several keys held together, for the wire.

    A chord travels as its own thing rather than as a key name, because a JSON
    object cannot be keyed by a sequence and a key name is not a place to hide one.
    """
    return [
        {"keys": list(chord_of(binding)), "action": action}
        for binding, action in bindings.items()
        if len(chord_of(binding)) > 1
    ]


__all__ = ["Bindings", "Chord", "chord_of", "chords", "single_keys"]
