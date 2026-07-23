"""The designated-peer bot authority for a peer-to-peer mesh (API-12).

A peer-to-peer game runs no authoritative server, so a bot seat -- a seat with no
human -- has no natural home: if every peer ran the bot's policy, a policy that
read a peer's speculative view would produce a different action on each peer and
split the trajectory. The ``P2PBotAuthority`` record resolves this by naming one
peer -- the highest eligible peer actor id -- as the authority for the whole
episode. That peer, and only that peer, produces the bot's action each frame and
broadcasts it; every other peer applies the broadcast action.

This module is the runtime seam for that rule. A ``BotSeat`` binds a bot actor id,
the authority actor id the record designates, and the controller that decides the
bot's action. A node asks ``holds_authority`` whether it is the authority; if it is,
it reads ``decide`` and submits the action for the bot seat through the engine's
``submit_for`` path, which packs it as the bot seat's input. A non-authority node
never calls ``decide``; it receives the bot's input over the mesh like any peer's.

The seat holds no engine and no environment. It never reads a clock or names a
provider; the controller is the study's, injected. So the authority is a pure
routing decision over the frozen record, and a test drives a two-peer mesh with a
scripted controller and asserts only the authority peer ever produced the bot's
action, yet both peers stepped the identical bot input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mug.game.seams import SeatActionSource


@dataclass(frozen=True)
class BotSeat:
    """One bot seat and the peer that holds authority over its decisions.

    ``bot_actor_id`` is the seat the mesh reserves for the bot; ``authority_actor_id``
    is the peer the ``P2PBotAuthority`` record designates to produce its action;
    ``controller`` decides the action from an observation, the same ``decide`` seam a
    human seat's input and a local controller satisfy.
    """

    bot_actor_id: str
    authority_actor_id: str
    controller: SeatActionSource

    def holds_authority(self, local_actor_id: str) -> bool:
        """Return whether the given peer is this bot's decision authority."""
        return local_actor_id == self.authority_actor_id

    def decide(self, observation: Any) -> int:
        """Return the bot's action for a frame, from the study's controller.

        Only the authority peer calls this; every other peer applies the action the
        authority broadcasts, so the bot's contribution stays single-sourced.
        """
        return int(self.controller.decide(observation))


__all__ = ["BotSeat"]
