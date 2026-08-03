"""Resolve which runtime one game activity runs, from what the study said.

``build_study_app`` takes nine mutually exclusive keywords for this -- ``game``,
``server_game``, ``agent_game``, ``turnbased_game``, ``browser_game``, ``mesh_game``,
``browser_p2p``, ``concurrent_mesh``, ``chat`` -- and not one of them is a decision a
study author should be making. Each follows from the environment the study named and
who it seated in it:

===================  ============================================================
today's keyword      is just
===================  ============================================================
``game``             a server run, one agent, one person
``server_game``      a server run, several agents, one person and local policies
``agent_game``       a server run with a model seat, or with several people
``turnbased_game``   a server run of an **AEC** environment -- read off the base
                     class, never written
``browser_game``     a browser run, one person
``mesh_game``        a browser run, two or more people
``browser_p2p``      the same, with entry gated: a deployment concern
``concurrent_mesh``  how many rooms run at once -- many, always
``chat``             not a game at all (``Chat``, an activity of its own)
===================  ============================================================

So a study writes ``runs="server"`` or ``runs="browser"`` and a seating, and this
module resolves the rest. There is also nothing left for two activities to disagree
about: each is resolved on its own, so a practice round with one person and a real
round with two are two mounts in one study rather than one mount used twice.

**Every identifier a seat carries is derived**, through the gateway, so two processes
over one ledger compile the same seats and a replay names what the run named.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from mug.agents import AgentGameSpec, TurnBasedGameSpec
from mug.content.players import Bot, Human, Model
from mug.content.seats import (
    DeriveId,
    MultiSeatGame,
    Seating,
    seat_game,
    seat_name,
)
from mug.content.study import Conversation, GameActivity, Study
from mug.game.spec import GameSpec
from mug.game.standard import seated_env, solo_factory
from mug.participant import ServerBotSeat, ServerGameSpec
from mug.participant_chat import ChatSpec, with_speakers

# Which of the platform's runtimes one activity resolved to. It is named rather than
# only constructed, so a study can be asked what it will run before anybody plays it
# -- and so a test can assert the resolution rather than the whole run.
MountKind = Literal[
    "game",
    "server_game",
    "agent_game",
    "turnbased_game",
    "browser_game",
    "mesh_game",
]

# The channel every game activity records on. It is one word because an activity is
# one game; what tells two activities apart is the activity key, which is on every
# record already.
CHANNEL: str = "game"

# What the loop reads a key press as. The two words are the platform's own, and which
# one an activity uses is the study's ``held_actions`` and nothing else -- the field
# once shipped with no producer and no reader, so every study read held keys and a
# 100 ms tap became three actions.
HELD = "pressed_keys"
TAPPED = "single_keystroke"

# The rate a real-time game falls back to, when neither the study nor the environment
# said one. A game with several seats falls back to nought instead: there the loop steps
# as soon as every seat has acted rather than on a clock, and nought is what says so.
REALTIME_FPS = 30
WHEN_SEATS_ACT = 0


def _fps(plays: GameActivity, fallback: int) -> int:
    """Return the rate to play at: the study's, else the environment's, else ours."""
    rate = plays.rate
    return rate if rate is not None else fallback


class MountRefused(ValueError):
    """What a study wrote resolves to no runtime this platform has."""


@dataclass(frozen=True)
class Mount:
    """One game activity's resolved runtime: which kind, and the built specification.

    Exactly one of the specification fields is set, and ``kind`` says which. It is
    written this way rather than as one union so that the resolution is readable on
    its own: a reader can see that ``browser`` plus two people is a mesh without
    following what a mesh specification holds.
    """

    key: str
    kind: MountKind
    game: GameSpec | None = None
    server_game: ServerGameSpec | None = None
    agent_game: AgentGameSpec | None = None
    turnbased_game: TurnBasedGameSpec | None = None

    @property
    def runs_on_the_server(self) -> bool:
        """Say whether the environment steps in this process."""
        return self.kind in ("game", "server_game", "agent_game", "turnbased_game")


def mount_kind(plays: GameActivity) -> MountKind:
    """Name which runtime this activity resolves to, without building it.

    This is the whole claim of the redesign in one function: nine keywords, and every
    one of them derivable from two words and a seating.
    """
    if plays.runs == "browser":
        return "browser_game" if plays.people <= 1 else "mesh_game"
    if plays.found.takes_turns:
        return "turnbased_game"
    if plays.models:
        return "agent_game"
    if plays.people > 1:
        # Several people at one environment is one table: one interaction, one
        # episode, captured once and recorded on every participant's own flow.
        return "agent_game"
    if plays.found.is_multi_agent:
        return "server_game"
    return "game"


def mount_for(plays: GameActivity, *, derived_id: DeriveId) -> Mount:
    """Build the runtime one game activity runs.

    A browser execution is resolved but not built here: what a browser run needs is a
    Python program carried into the participant's browser, and a study that runs in a
    browser still writes that program itself for now. The resolution is returned so
    that the application can say which mount an activity is, and refuse honestly.
    """
    kind = mount_kind(plays)
    if kind == "game":
        return Mount(key=plays.key, kind=kind, game=_solo(plays))
    if kind == "server_game":
        return Mount(
            key=plays.key,
            kind=kind,
            server_game=_beside_bots(plays, derived_id=derived_id),
        )
    if kind == "agent_game":
        return Mount(
            key=plays.key, kind=kind, agent_game=_seated(plays, derived_id=derived_id)
        )
    if kind == "turnbased_game":
        return Mount(
            key=plays.key,
            kind=kind,
            turnbased_game=_taking_turns(plays, derived_id=derived_id),
        )
    raise MountRefused(
        f"the game {plays.key!r} runs in a participant's browser, and the platform "
        "cannot yet write the browser program for a named environment: the client "
        "runs a Python program that builds the environment and draws each frame, and "
        "a study that runs in a browser still supplies that program itself. Run this "
        'activity on the server (runs="server"), or mount it with browser_game=.'
    )


def mounts_for(study: Study, *, derived_id: DeriveId) -> dict[str, Mount]:
    """Resolve every game activity in one study, by its own key."""
    return {
        key: mount_for(plays, derived_id=derived_id)
        for key, plays in study.game_activities.items()
    }


# -- what each runtime is built from ------------------------------------------------


def _solo(plays: GameActivity) -> GameSpec:
    """Build the single-seat game: one Gymnasium environment, one person at it."""
    render = plays.render
    if render is None:
        raise MountRefused(
            f"the game {plays.key!r} runs on the server with nobody able to see it: "
            "write render=."
        )
    return GameSpec(
        channel_key=CHANNEL,
        make_env=solo_factory(plays.env, scene=plays.scene),
        render=render,
        action_bindings=dict(plays.bindings),
        default_action=plays.idle_action,
        fps=_fps(plays, REALTIME_FPS),
        max_steps=plays.found.max_steps or 200,
        input_mode=HELD if plays.held else TAPPED,
        hud=plays.hud,
    )


def _beside_bots(plays: GameActivity, *, derived_id: DeriveId) -> ServerGameSpec:
    """Build the server-authoritative game: one person, local policies beside them.

    A bot's recorded actor is derived from the activity and the agent it plays, the
    same way a compiled seating derives one, so the same study run twice records the
    same actor and a replay names what the run named.
    """
    person = _the_person(plays)
    return ServerGameSpec(
        channel_key=CHANNEL,
        make_env=seated_env(plays.env, scene=plays.scene),
        human_agent_id=person,
        human_seat_key=seat_name(person),
        bots=tuple(
            ServerBotSeat(
                agent_id=str(agent),
                seat_key=seat_name(agent),
                actor_id=derived_id("actor", f"{plays.key}:{seat_name(agent)}"),
                controller=seat.controller,
            )
            for agent, seat in _written(plays).items()
            if isinstance(seat, Bot)
        ),
        render=plays.render,
        hud=plays.hud,
        input_mode=HELD if plays.held else TAPPED,
        action_bindings=dict(plays.bindings),
        default_action=plays.idle_action,
        fps=_fps(plays, REALTIME_FPS),
        max_steps=plays.found.max_steps or 200,
    )


def _seated(plays: GameActivity, *, derived_id: DeriveId) -> AgentGameSpec:
    """Build the multi-seat game: any mix of people, models, and local policies.

    The seating compiles through ``mug.content.seats``, which is where every derived
    identifier a seat carries already comes from. So a study that named its
    environment and a study that wrote a ``MultiSeatGame`` reach the same records.
    """
    return seat_game(
        _multiseat(plays),
        _written(plays),
        activity_key=plays.key,
        derived_id=derived_id,
    )


def _taking_turns(plays: GameActivity, *, derived_id: DeriveId) -> TurnBasedGameSpec:
    """Build the turn-based game, for an environment whose agents act one at a time.

    Which it is comes from the base class and never from the study: ``AECEnv`` means
    turns. The seats compile exactly as the simultaneous game's do, so the two differ
    only in how the environment is stepped -- which is the only way they do differ.
    """
    compiled = _seated(plays, derived_id=derived_id)
    return TurnBasedGameSpec(
        channel_key=CHANNEL,
        make_env=plays.env,
        seats=compiled.seats,
        human=compiled.human_seats[0] if compiled.human_seats else None,
        action_bindings=dict(plays.bindings),
        default_action=plays.idle_action,
        fps=_fps(plays, WHEN_SEATS_ACT),
        max_steps=plays.found.max_steps or 50,
    )


def _multiseat(plays: GameActivity) -> MultiSeatGame:
    """Return the environment and cadence one seating sits in."""
    return MultiSeatGame(
        make_env=seated_env(plays.env, scene=plays.scene),
        render=plays.render,
        hud=plays.hud,
        input_mode=HELD if plays.held else TAPPED,
        channel_key=CHANNEL,
        action_bindings=dict(plays.bindings),
        default_action=plays.idle_action,
        fps=_fps(plays, WHEN_SEATS_ACT),
        max_steps=plays.found.max_steps or 50,
    )


def _written(plays: GameActivity) -> Seating:
    """Return the seating a study wrote, refusing an activity that wrote none.

    Every mount but the single-seat one needs to know who is where, and an activity
    with a multi-agent environment and no seating has not said. It is refused rather
    than guessed at: seating somebody positionally is the one thing the map exists to
    prevent.
    """
    if plays.seats:
        return plays.seats
    named = ", ".join(repr(one) for one in plays.found.agents)
    raise MountRefused(
        f"the game {plays.key!r} plays an environment with more than one agent and "
        f"does not say who plays each: write seats={{...}} over its agents ({named})."
    )


def _the_person(plays: GameActivity) -> str:
    """Return the one agent a person plays in a game beside local policies."""
    people = [
        str(agent) for agent, seat in _written(plays).items() if isinstance(seat, Human)
    ]
    if len(people) != 1:
        raise MountRefused(
            f"the game {plays.key!r} seats {len(people)} people beside local "
            "policies, and a server-authoritative game seats one: the others are "
            "either people at their own connections (which is a table) or policies."
        )
    return people[0]


# -- the conversation activity -------------------------------------------------------


# What ``Chat`` writes on the specification itself. Anything an author passes
# through as a setting must not be one of these, or the two would be two answers to
# one question -- and the collision would otherwise surface as a TypeError from
# inside the mount, which names the runtime field and not the line they wrote.
_WRITTEN_ON_CHAT = frozenset(
    {
        "speakers",
        "channel_key",
        "participants",
        "greeting",
        "max_messages",
        "placement",
        "elicit_preference",
    }
)


def chat_for(talk: Conversation, *, derived_id: DeriveId) -> ChatSpec:
    """Compile one authored conversation into the specification its mount runs.

    Every identifier a model seat carries -- its pinned build, its recorded actor, the
    provider adapter it reaches -- is derived from the conversation's own channel, the
    same way a game seat's is. So an author writes which model speaks and nothing else.
    """
    said_twice = sorted(set(talk.settings) & _WRITTEN_ON_CHAT)
    if said_twice:
        named = ", ".join(said_twice)
        raise MountRefused(
            f"the conversation {talk.key!r} says {named} twice. A conversation's "
            f'key is its channel and its own keywords are the rest: Chat("{talk.key}"'
            ", greeting=..., participants=...)."
        )
    return with_speakers(
        ChatSpec(
            speakers=tuple(talk.speakers),
            channel_key=talk.key,
            participants=talk.participants,
            greeting=talk.greeting,
            max_messages=talk.max_messages,
            placement=talk.placement,
            elicit_preference=talk.elicit,
            **dict(talk.settings),
        ),
        derived_id,
    )


def chats_beside_games(study: Study, *, derived_id: DeriveId) -> dict[str, ChatSpec]:
    """Compile every conversation a study wrote **on** a game activity, by its key.

    It is the same compilation as a conversation that is a whole activity, because
    it is the same authored thing in a different place. Which one it is changes what
    runs it, not what it is.
    """
    return {
        key: chat_for(talk, derived_id=derived_id) for key, talk in study.chats.items()
    }


def chats_for(study: Study, *, derived_id: DeriveId) -> dict[str, ChatSpec]:
    """Compile every conversation activity in one study, by its own key.

    A study may hold several, and it may hold a conversation **and** a game -- which
    the nine mutually exclusive builder keywords could not express at all: the chat arm
    of the chain won and the game was dropped with nothing said.
    """
    return {
        key: chat_for(talk, derived_id=derived_id) for key, talk in study.talks.items()
    }


def describe(study: Study) -> list[str]:
    """Return one line per game activity: what it runs, where, and who is in it.

    It exists so the resolution is readable rather than only exercised. An author who
    wants to know what their study will do reads this; a test that wants to assert the
    collapse of nine keywords into two words reads the same thing.
    """
    lines: list[str] = []
    for key, talk in study.talks.items():
        who = ", ".join(_who(one) for one in talk.speakers)
        people = talk.participants
        lines.append(f"{key:<12} a conversation, {people} person(s) with [{who}]")
    for key, plays in study.game_activities.items():
        who = ", ".join(
            f"{agent}={_who(seat)}" for agent, seat in (plays.seats or {}).items()
        )
        rounds = "" if plays.episodes == 1 else f" x{plays.episodes}"
        where = "in the browser" if plays.runs == "browser" else "on the server"
        lines.append(f"{key:<12} {where}{rounds}  [{who}]  -> {mount_kind(plays)}")
    return lines


def _who(seat: Any) -> str:
    """Name one seat's kind in a line an author reads."""
    if isinstance(seat, Human):
        return "human"
    if isinstance(seat, Bot):
        return "bot"
    if isinstance(seat, Model):
        return "model"
    return type(seat).__name__.lower()


__all__ = [
    "CHANNEL",
    "HELD",
    "TAPPED",
    "Mount",
    "MountKind",
    "MountRefused",
    "chat_for",
    "chats_for",
    "describe",
    "mount_for",
    "mount_kind",
    "mounts_for",
]
