"""The visit lifecycle gate: the pure rule for a status transition.

A visit starts ``created``, runs ``in-progress``, and ends ``completed`` or
``abandoned``. The two end states are terminal. The gate reads the current status
and the target and returns a refusal reason, or None when the move is allowed.
The service turns a refusal into a rejected receipt.
"""

from __future__ import annotations

_ALLOWED: dict[str, frozenset[str]] = {
    "created": frozenset({"in-progress", "abandoned"}),
    "in-progress": frozenset({"completed", "abandoned"}),
    "completed": frozenset(),
    "abandoned": frozenset(),
}


def transition_refusal(current: str, target: str) -> str | None:
    """Return a refusal reason for a status move, or None when it is allowed."""
    if target not in _ALLOWED.get(current, frozenset()):
        return "illegal_transition"
    return None
