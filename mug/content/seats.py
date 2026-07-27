"""Who plays a game activity: the author's seating, and what it compiles to.

A study says who is in an environment by naming the environment's own agents and
who plays each one::

    junction = MultiSeatGame(make_env=make_junction)
    Study(
        Page("instructions", INSTRUCTIONS),
        Game(
            "play",
            junction,
            seats={
                "car": Human(),
                "pedestrian": Human(),
                "traffic-light": Model(controller),
            },
        ),
    )

**The seating is a map, never a list.** Which agent somebody plays is a study's
most consequential decision -- driving the car and running the traffic light are
different tasks with different data -- so it is written down, not inferred from the
order the seats happen to appear in. A list would make a study that reorders two
lines silently swap two roles, and nothing in the records would say it had
happened.

The environment is one thing and who is in it is another, so they are written
apart. ``MultiSeatGame`` is the environment and its cadence; the seating is written
on the activity, where it takes effect (R-15). One map holds every kind of player,
so a study that gives the traffic light to a model instead of a person changes one
value rather than which specification it constructs.

**Everything else is derived.** The recorded seat and actor, the provider adapter a
model reaches, and the pinned build the record names are all computed from the
activity and the agent the seat plays. An author writes which agent and who plays
it; none of the rest is a study decision, so none of it is a study's to write.

What is **not** written is which person gets which human seat, because people are
interchangeable in a way roles are not: the room casts them in the order they
arrive, and the first cast person plays the first human seat in the map. A study
that cares which person drives makes that a treatment
(``mug.visits.design``), so the assignment is randomized and recorded rather than
left to who clicked first.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from mug.agents import (
    AgentGameSpec,
    AgentIds,
    AgentSeatSpec,
    BotSeatSpec,
    HumanSeatSpec,
    adapter_for,
)
from mug.agents.multiseat_episode import TextView
from mug.authoring import LLMAgent
from mug.game.multiseat import MultiSeatEnv
from mug.game.seams import SeatActionSource
from mug.providers.runtime import ProviderAdapter, SecretResolver

# What a derived identifier is minted through: a kind and the words that fix it.
DeriveId = Callable[[str, str], str]

_KEY = re.compile(r"[^a-z0-9]+")


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
    """

    controller: SeatActionSource


# One player of a game activity, and the seating that says which agent each plays.
Seat = Human | Model | Bot
Seating = Mapping[str, Seat]


def _no_bindings() -> Mapping[str, int]:
    """Return an empty, typed key-to-action binding map for a game default."""
    return {}


@dataclass(frozen=True)
class MultiSeatGame:
    """The environment a game activity runs, with nobody in it yet.

    ``make_env`` builds the multi-seat environment the loop steps and every seat
    reads. It names no agents: the seating on the activity does, because that is
    where a study says who plays what.

    ``action_bindings`` maps a held key to a discrete action for the people at it,
    and ``default_action`` is what a seat holding no key does. ``fps`` and
    ``max_steps`` shape the loop; ``decision_timeout`` bounds one model decision.
    """

    make_env: Callable[[], MultiSeatEnv]
    channel_key: str = "game"
    action_bindings: Mapping[str, int] = field(default_factory=_no_bindings)
    default_action: int = 0
    decision_timeout: float = 1.0
    fps: int = 0
    max_steps: int = 200


def _slug(name: str) -> str:
    """Return one authoring key read from a class name, or a safe fallback.

    A study that does not name its agent gets the class name in the records, which
    is what the author already calls it. The frozen authoring-key pattern admits
    only lower-case words joined by one separator, so anything else is folded out.
    """
    key = _KEY.sub("-", name.lower()).strip("-")
    return key or "agent"


def _ids_for(agent: LLMAgent, key: str, scope: str, derived_id: DeriveId) -> AgentIds:
    """Derive the pinned build one model seat's records name.

    A study that has not published a catalogue still records a build, and the same
    study run twice records the same one, because every identifier here is derived
    from the activity, the seat, and the agent's own key. Nothing is minted, so a
    replay names what the run named.
    """
    return AgentIds(
        agent_version_id=derived_id("agentver", f"{scope}:{key}"),
        agent_definition_id=derived_id("agentdef", key),
        agent_key=key,
        version_number=1,
        prompt_version_id=derived_id("promptver", f"{scope}:{key}"),
        fallback_policy_key=agent.on_timeout.value,
    )


def seat_game(
    game: MultiSeatGame,
    seats: Seating,
    *,
    activity_key: str,
    derived_id: DeriveId,
) -> AgentGameSpec:
    """Compile one activity's environment and seating into the game it runs.

    Each seat is recorded under the agent it plays, so the seat key in every record
    says which part of the environment it was. The people keep the order they were
    written in, which is what the room's cast lines up against when several of them
    sit down.
    """
    if not seats:
        raise ValueError(
            "a game activity's seating names at least one agent and who plays it"
        )
    models: list[AgentSeatSpec] = []
    people: list[HumanSeatSpec] = []
    bots: list[BotSeatSpec] = []
    for agent_id, seat in seats.items():
        # The seat is named for the part it plays, so a record of "the traffic
        # light did this" reads as one rather than as "seat 3 did this".
        seat_key = agent_id
        scope = f"{activity_key}:{seat_key}"
        if isinstance(seat, Human):
            people.append(HumanSeatSpec(agent_id=agent_id, seat_key=seat_key))
        elif isinstance(seat, Bot):
            bots.append(
                BotSeatSpec(
                    agent_id=agent_id,
                    seat_key=seat_key,
                    controller=seat.controller,
                    actor_id=derived_id("actor", scope),
                )
            )
        else:
            key = seat.key or _slug(type(seat.agent).__name__)
            models.append(
                AgentSeatSpec(
                    agent=seat.agent,
                    adapter=seat.adapter or adapter_for(seat.agent.provider.value),
                    ids=_ids_for(seat.agent, key, scope, derived_id),
                    agent_id=agent_id,
                    seat_key=seat_key,
                    actor_id=derived_id("actor", scope),
                    resolve_secret=seat.resolve_secret,
                    text_view=seat.text_view,
                )
            )
    return AgentGameSpec(
        channel_key=game.channel_key,
        make_env=game.make_env,
        seats=tuple(models),
        humans=tuple(people),
        bots=tuple(bots),
        action_bindings=dict(game.action_bindings),
        default_action=game.default_action,
        decision_timeout=game.decision_timeout,
        fps=game.fps,
        max_steps=game.max_steps,
    )


__all__ = [
    "Bot",
    "Human",
    "Model",
    "MultiSeatGame",
    "Seat",
    "Seating",
    "seat_game",
]
