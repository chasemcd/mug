"""Who plays a seat: the three kinds a study writes, and nothing else.

These are the author's own words for who is in an environment -- a person, a local
policy, or a model -- and they are kept apart from what they compile into
(``mug.content.seats``) for one reason: the study surface names them. ``Game`` has
to know whether a seat is a person to refuse a keyboard bound to nothing, and
whether it is a model to refuse a browser run that cannot reach a provider. Written
here, that costs an import of three dataclasses; written beside the compilation it
would cost the whole agent stack on every ``from mug.content import Study``.

Every field is an annotation only, so this module imports nothing at run time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mug.agents.multiseat_episode import TextView
    from mug.authoring import LLMAgent
    from mug.game.seams import SeatActionSource
    from mug.providers.runtime import ProviderAdapter, SecretResolver


@dataclass(frozen=True)
class Human:
    """A person plays this seat.

    Which agent they play is the key this is written under, so a person's seat
    holds nothing of its own.
    """


@dataclass(frozen=True)
class Model:
    """A model plays this seat, and talks on the conversation beside it (W7).

    ``agent`` is the author's ``LLMAgent`` and is the only thing a study must
    write: the provider adapter is the one its declared provider names, and the
    pinned build is derived from the activity and the seat.

    ``key`` names the agent in the records; with none it is read from the class
    name. ``text_view`` renders the game for this seat's prompt, and
    ``resolve_secret`` resolves its credential (a keyless local runner needs none).
    """

    agent: LLMAgent
    key: str | None = None
    adapter: ProviderAdapter | None = None
    text_view: TextView | None = None
    resolve_secret: SecretResolver | None = None


@dataclass(frozen=True)
class Bot:
    """A local policy plays this seat: a heuristic, or an exported network.

    ``controller`` decides the action from an observation. It reaches no provider
    and keeps no thoughts, which is what makes it a different kind of seat from a
    ``Model`` rather than a model with the provider left out.

    Where it is scored is never written here: on a server run the application scores
    it, and on a browser run the participant's own inference runtime does. It is the
    same seat either way, because it is the same teammate.
    """

    controller: SeatActionSource


# One player of a game activity, and the seating that says which agent each plays.
#
# The seating is a map, never a list. Which agent somebody plays is a study's most
# consequential decision -- driving the car and running the traffic light are
# different tasks with different data -- so it is written down, not inferred from the
# order the seats happen to appear in. A list would make a study that reorders two
# lines silently swap two roles, and nothing in the records would say it had happened.
#
# The key is the environment's own agent, whatever the environment calls it: a string
# for a PettingZoo environment that names its agents, an integer for one that numbers
# them. It is never a name of the study's own invention, because a name the environment
# does not know is a name the platform cannot check.
Seat = Human | Model | Bot
Seating = Mapping[Any, Seat]


__all__ = [
    "Bot",
    "Human",
    "Model",
    "Seat",
    "Seating",
]
