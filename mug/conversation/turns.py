"""The pure turn-policy decision: may a model activate on this turn (API-08)?

A ``TurnPolicy`` governs how and how often a model speaks in a channel. This module
holds the pure decision the policy implies: given the policy and the turn's state,
may the model activate now? It takes data and returns a boolean, with no I/O, so a
test drives every activation mode with plain values.

The four modes:

- ``free`` -- the model may speak whenever it has something to add;
- ``mention`` -- the model speaks only when a message mentions it;
- ``round-robin`` -- the model speaks only on its own turn in the rotation;
- ``moderated`` -- the model speaks only when a moderator has cleared the turn.

Every mode is capped: a model may not exceed ``max_model_activations_per_turn`` in
one turn, whatever the mode allows.
"""

from __future__ import annotations

from mug.conversation.types import TurnPolicy


def may_activate(
    policy: TurnPolicy,
    *,
    activations_so_far: int,
    mentioned: bool = False,
    is_my_turn: bool = True,
    moderator_cleared: bool = False,
) -> bool:
    """Return whether a model may activate now under the policy and turn state.

    The activation cap binds every mode: once the model has activated
    ``max_model_activations_per_turn`` times this turn, it may not activate again.
    Below the cap, the mode decides: ``free`` always allows, ``mention`` needs a
    mention, ``round-robin`` needs the model's own turn, and ``moderated`` needs a
    moderator to clear the turn.
    """
    if activations_so_far >= policy.max_model_activations_per_turn:
        return False
    if policy.activation == "free":
        return True
    if policy.activation == "mention":
        return mentioned
    if policy.activation == "round-robin":
        return is_my_turn
    return moderator_cleared


__all__ = ["may_activate"]
