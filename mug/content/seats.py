"""What an author's seating compiles into: the seats, actors, and builds it names.

The three kinds a study writes -- ``Human``, ``Model``, ``Bot`` -- are in
``mug.content.players``, so the study surface can name them without this module's
whole agent stack. They are re-exported here, because a seating and what it compiles
to read as one thing.

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
from typing import Any

from mug.agents import (
    AgentGameSpec,
    AgentIds,
    AgentSeatSpec,
    BotSeatSpec,
    HumanSeatSpec,
    adapter_for,
)
from mug.authoring import LLMAgent
from mug.content.players import Bot, Human, Model, Seat, Seating
from mug.game.keys import Bindings
from mug.game.multiseat import MultiSeatEnv
from mug.game.spec import HudFn, RenderFn

# What a derived identifier is minted through: a kind and the words that fix it.
DeriveId = Callable[[str, str], str]

_KEY = re.compile(r"[^a-z0-9]+")

# The seat-key rule, as the contract states it (``mug.kernel.SeatKey``). It is matched
# here rather than assumed, so a name this module hands on is one a record can hold.
_SEAT_NAME = re.compile(r"^[a-z0-9][a-z0-9]*(?:[-_.][a-z0-9]+)*$")


def _no_bindings() -> Mapping[str, int]:
    """Return an empty, typed key-to-action binding map for a game default."""
    return {}


@dataclass(frozen=True)
class MultiSeatGame:
    """The environment a game activity runs, with nobody in it yet.

    ``make_env`` builds the multi-seat environment the loop steps and every seat
    reads. It names no agents: the seating on the activity does, because that is
    where a study says who plays what.

    ``render`` draws one frame for the people watching. It is the same drawing a
    one-person ``GameSpec`` writes, because it is the same environment: everybody at
    the table watches one board. A game with none pushes the stepped frames and
    draws nothing, which is right for two models playing with nobody reading.

    ``action_bindings`` maps a held key to a discrete action for the people at it,
    and ``default_action`` is what a seat holding no key does. ``fps`` and
    ``max_steps`` shape the loop; ``decision_timeout`` bounds one model decision.
    """

    make_env: Callable[[], MultiSeatEnv]
    render: RenderFn | None = None
    hud: HudFn | None = None
    input_mode: str = "pressed_keys"
    channel_key: str = "game"
    action_bindings: Bindings = field(default_factory=_no_bindings)
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


def seat_name(agent: Any) -> str:
    """Return the name records give one of the environment's agents.

    **A name the contract accepts is kept exactly.** An environment's own word for an
    agent is the best name a record can carry, so ``0`` stays ``0`` and ``agent_left``
    stays ``agent_left``. A seat key admits a leading digit, because numbering agents is
    ordinary in both standard environment APIs and a seat name is not a name a study
    invented (``mug.kernel.SeatKey``).

    Anything the contract cannot carry -- a capital, a space -- is folded until it can,
    rather than refused: a study should not have to rename its environment's agents to
    seat people in them.
    """
    written = str(agent).strip().lower()
    if _SEAT_NAME.match(written):
        return written
    folded = "".join(one if one.isalnum() else "-" for one in written).strip("-")
    while "--" in folded:
        folded = folded.replace("--", "-")
    return folded or "agent"


def agent_ids_for(
    agent: LLMAgent, key: str, scope: str, derived_id: DeriveId
) -> AgentIds:
    """Derive the pinned build one model seat's records name.

    It is public because a conversation needs it too: a model that only talks is
    the same kind of seat as one that plays, and it must not be the one an author
    has to write six identifiers for.

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
    for written_agent, seat in seats.items():
        # The agent is whatever the environment calls it, so it may be a number: a
        # PettingZoo environment that numbers its agents answers ``[0, 1]``. The
        # records name it as text, because every identifier in the contract is text,
        # and the seat is named for the part it plays -- so a record of "the traffic
        # light did this" reads as one rather than as "seat 3 did this".
        agent_id = str(written_agent)
        seat_key = seat_name(written_agent)
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
                    ids=agent_ids_for(seat.agent, key, scope, derived_id),
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
        render=game.render,
        hud=game.hud,
        input_mode=game.input_mode,
        seats=tuple(models),
        humans=tuple(people),
        bots=tuple(bots),
        # The bindings pass through as written: a chord is a sequence of keys,
        # and copying them into a narrower map would flatten one back to a name.
        action_bindings=game.action_bindings,
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
    "agent_ids_for",
    "seat_game",
    "seat_name",
]
