"""A proposed author surface for study activities, as a working prototype.

Scratch code. Nothing in ``mug/`` imports it. Run ``python scratch/api/study.py``.

Two ideas, and the second is the one that matters.

**An activity says what it is.** Today a study writes ``Game("play")`` and the
environment arrives from a keyword on the application builder, so reading a study
tells you nothing about the task and a study can hold only one environment however
many game activities it writes.

**The author hands over the environment they trained in, and nothing else.** No
``BrowserGameSpec``, no ``source_bundle``, no ``MultiSeatGame``, no hand-written
package pin, no seat-to-index map. ``Game`` takes a Gymnasium or PettingZoo class, a
registered id, or a factory, and ``scratch/api/derive.py`` reads the rest off it: the
API, the agents, the action set, the frame rate, the episode bound, the drawing, the
key bindings where the environment declares them, and the pin a browser installs.

So ``runs=`` is a plain word rather than a specification type, and the eight game
mounts the platform has today reduce to **two executions and the seating**:

    server + one Human                     -> today's `game`
    server + Human and Bot seats           -> today's `server_game`
    server + Model seats                   -> today's `agent_game`
    server + a PettingZoo AEC environment  -> today's `turnbased_game`  (derived)
    browser + one Human                    -> today's `browser_game`
    browser + two or more Humans           -> today's `mesh_game` / `browser_p2p`

Nothing is left for the author to choose between. Which of those a study runs
follows from the environment it named and the seats it wrote.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scratch.api.derive import Derived, EnvFactory, derive

# Where a game activity runs. Two words, because there are two places an environment
# can step. It is a study decision rather than a deployment one: the participant
# feels a browser run as a download before the first round, and it changes what
# verification means -- a browser run is re-executed by the server rather than
# recorded as it is stepped.
Execution = Literal["server", "browser"]

# How each execution is said in a message an author reads. "in the server" is not
# English, and a refusal an author has to translate is a worse refusal.
WHERE: dict[str, str] = {
    "server": "on the server",
    "browser": "in the participant's browser",
}


# -- who plays a seat ---------------------------------------------------------------


@dataclass(frozen=True)
class Human:
    """A person plays this seat."""


@dataclass(frozen=True)
class Bot:
    """A local policy plays this seat: a heuristic, or an exported network.

    Where it is scored follows from the activity's execution and is never written
    here: on a server run the application scores it, and on a browser run the
    participant's own inference runtime does. It is the same seat either way, because
    it is the same teammate. Today those are two unrelated spellings -- a closure
    argument to the environment on the server, and a ``partner=`` field on the
    browser specification.
    """

    controller: Any
    decides_every: int = 1


@dataclass(frozen=True)
class Model:
    """A model plays this seat, and may talk on the conversation beside it."""

    agent: Any
    key: str | None = None


Seat = Human | Bot | Model
Seating = Mapping[Any, Seat]


# -- the activities -----------------------------------------------------------------


@dataclass(frozen=True)
class Activity:
    """One resolved study step. The platform reads this; an author does not write it."""

    key: str
    kind: Literal["form", "content", "game", "chat", "comparison"]
    env: Any = None
    found: Derived | None = None
    execution: Execution | None = None
    seats: Seating | None = None
    episodes: int = 1
    between: str | None = None
    caption: str | None = None
    chat: Any = None
    render: Any = None
    hud: Any = None
    assets: tuple[Any, ...] = ()
    detail: Any = None

    @property
    def mount(self) -> str:
        """Name which of today's eight game mounts this activity resolves to.

        It is derived here to make the point checkable: an author chooses between
        none of them, and the choice they do make -- the environment, and who is in
        it -- decides which one runs.
        """
        if self.kind != "game" or self.found is None:
            return self.kind
        people = sum(
            1 for seat in (self.seats or {}).values() if isinstance(seat, Human)
        )
        models = any(isinstance(seat, Model) for seat in (self.seats or {}).values())
        if self.execution == "browser":
            return "browser_game" if people <= 1 else "mesh_game"
        if models:
            return "agent_game"
        if "aec" in self.found.api:
            return "turnbased_game"
        if len(self.found.agents) > 1:
            return "server_game"
        return "game"


def Game(
    key: str,
    env: EnvFactory,
    *,
    runs: Execution = "server",
    seats: Seating | None = None,
    keys: Mapping[Any, int] | None = None,
    held_actions: bool | None = None,
    default_action: int | None = None,
    render: Any = None,
    hud: Any = None,
    assets: Sequence[Any] = (),
    episodes: int = 1,
    between: str | None = None,
    caption: str | None = None,
    chat: Any = None,
) -> Activity:
    """Play ``env``. Say where it runs, and who is in it.

    ``env`` is **something that takes no arguments and returns the environment the
    author trained in** -- a ``gymnasium.Env``, a PettingZoo ``ParallelEnv``, or a
    PettingZoo ``AECEnv``. An environment class is one of those. So is
    ``functools.partial(gymnasium.make, "MountainCar-v0")``. So is a study's own
    ``def kitchen(): ...``.

    Everything else is read off the environment: the agents, the action set, the frame
    rate, the episode bound, the drawing, and the package a browser must install. A
    study writes no specification of any kind.

    It takes **no arguments** on purpose. Whatever an environment needs to be built is
    bound inside the callable, by the author, where they are already constructing it --
    including ``render_mode="rgb_array"`` if they want the environment's own frames. So
    the platform passes nothing in, a configuration holding live objects needs no
    written form, and there is one kind of thing to hand over rather than three.

    ``runs`` is where the environment steps. ``seats`` says which of the
    environment's own agents each player takes, and it is a **map, never a list**:
    which agent somebody plays is a study's most consequential decision, so it is
    written down and not left to the order two lines happen to appear in. It is also
    the only place a study says somebody other than the participant is playing.

    ``keys`` maps a key -- or a **sequence of keys held together**, a chord -- to an
    action. It is the one thing no environment API can say. An environment that follows
    the ``gymnasium.utils.play`` convention declares its own, and a study that names
    such an environment writes none of the three input keywords.

    ``held_actions`` says whether a bound key acts on **every frame it is down**
    (``True``: a court, a car) or **once per press** (``False``: a grid, a card game).
    A grid and a court want opposite answers, so there is no default: the platform once
    shipped an input mode with no producer and no reader, every study read held keys,
    and a 100 ms tap became three actions.

    ``default_action`` is what a frame with no bound key takes. It is written for the
    same reason: action ``0`` is a reasonable no-op in some environments and "walk
    north" in CoGrid, so guessing it makes a chef walk upward for a whole round.

    ``render`` is a drawing better than the frames the environment hands over: sprites
    the study declared, drawn by name. Without one the environment's own ``rgb_array``
    frames are painted, which on a browser run costs nothing at all -- the pixels are
    drawn in the same browser that made them and never travel.

    ``assets`` are the pictures **this** activity draws: the sprite sheets its drawing
    names. They are declared here rather than on the study because this is where they
    are used, and that has a consequence a participant feels -- an asset is loaded
    before the activity that needs it, so a study with a kitchen and a court no longer
    makes somebody download both sets before the first round. A study-wide picture (one
    an instruction page shows) is still declared on the ``Study``.

    ``hud`` is the line a participant reads **on** the game while they play: the score
    they have, the time left, what they are carrying. It is a function of the step and
    returns one line; the platform draws the band across the top, so a study never
    writes the band. It is drawn onto the same surface as the game, so it is in the
    record and in a replay -- what a participant was told is part of what happened to
    them. ``caption`` is the different thing: markdown the participant reads *beside*
    the game, which does not change as they play.

    ``episodes``, ``between``, ``caption``, and ``chat`` are unchanged.
    """
    found = derive(env)
    _refuse_an_execution_it_cannot_run(key, runs, found)
    _refuse_an_unknown_agent(key, found, seats)
    _refuse_rounds_that_cannot_loop(key, runs, episodes)
    _refuse_a_model_that_cannot_reach_a_provider(key, runs, seats)
    _refuse_a_person_with_no_keys(key, found, seats, keys)
    _refuse_keys_that_do_not_say_how_they_act(key, keys, held_actions, default_action)
    _refuse_a_game_nobody_can_see(key, found, seats, render)
    return Activity(
        key=key,
        kind="game",
        env=env,
        found=found,
        execution=runs,
        seats=seats,
        episodes=episodes,
        between=between,
        caption=caption,
        chat=chat,
        render=render,
        hud=hud,
        assets=tuple(assets),
    )


def Chat(
    key: str,
    *speakers: Model,
    participants: int = 1,
    greeting: str | None = None,
    max_messages: int = 20,
    elicit: Any = None,
    **settings: Any,
) -> Activity:
    """Hold a conversation. It is an activity of its own, not a game with no game.

    Today a study writes ``Game("talk")`` and the application builder is passed a
    conversation, which replaces the whole game hook. So the study says "a game"
    where a conversation happens, the recorded activity kind is ``game``, and the
    screen that renders it is ``chat``.

    A conversation beside a game is still written on the game
    (``Game(..., chat=...)``), because it happens there.
    """
    return Activity(
        key=key,
        kind="chat",
        detail={
            "speakers": speakers,
            "participants": participants,
            "greeting": greeting,
            "max_messages": max_messages,
            "elicit": elicit,
            **settings,
        },
    )


def Form(key: str, *fields: Any) -> Activity:
    """Ask the participant a set of questions. Unchanged; here so this file runs."""
    return Activity(key=key, kind="form", detail=fields)


def Page(key: str, markdown: str) -> Activity:
    """Show the participant something to read. Unchanged; here so this file runs."""
    return Activity(key=key, kind="content", detail=markdown)


# -- the refusals, every one of which is silent today -------------------------------


def _refuse_an_execution_it_cannot_run(key: str, runs: str, found: Derived) -> None:
    """Refuse a browser run the environment's own packages cannot support.

    The reasons come from the environment: study code a browser cannot import,
    compiled code with no wheel for Pyodide's platform, a distribution that is not
    installed. Today this is a download that fails in front of a participant.
    """
    if runs == "browser" and found.blocks:
        raise ValueError(
            f"the activity {key!r} cannot run in a browser: {found.blocks[0]}"
        )


def _refuse_an_unknown_agent(key: str, found: Derived, seats: Any) -> None:
    """Refuse a seating that names an agent the environment does not have.

    The agents are read off the environment, so this needs nothing from the author.
    A mistyped seat key survives the build today and raises ``KeyError`` on the first
    frame of a participant's run, where the fault reads as the platform failing.
    """
    if seats is None:
        return
    if not isinstance(seats, Mapping):
        raise ValueError(
            f"the activity {key!r} must say which agent each player takes: "
            "seats={0: Human(), 1: Bot(chef)}"
        )
    written = cast("Seating", seats)
    unknown = sorted(str(one) for one in set(written) - set(found.agents))
    if unknown:
        has = ", ".join(repr(one) for one in found.agents)
        raise ValueError(
            f"the activity {key!r} seats {', '.join(unknown)}, which its environment "
            f"does not have; its agents are: {has}"
        )


def _refuse_rounds_that_cannot_loop(key: str, runs: str, episodes: int) -> None:
    """Refuse rounds an execution plays once and says nothing about.

    A browser run is written by the client and captured once. The platform refuses
    this today and needs the study and the builder's keywords together to do it; with
    the execution on the activity the activity knows.
    """
    if episodes < 1:
        raise ValueError(f"the activity {key!r} plays at least one round")
    if episodes > 1 and runs != "server":
        raise ValueError(
            f"the activity {key!r} asks for {episodes} rounds, and a browser run "
            "plays one: the client writes the whole episode and reports it once. "
            f"Write {episodes} game activities, or run it on the server."
        )


def _refuse_a_model_that_cannot_reach_a_provider(
    key: str, runs: str, seats: Any
) -> None:
    """Refuse a model seat in an execution that has no way to reach a provider.

    A participant's browser holds no credential and must never be given one, so a
    model seat needs the server in the loop. An exported network is a different kind
    of seat (``Bot``) and runs in either place.
    """
    if seats is None or runs == "server" or not isinstance(seats, Mapping):
        return
    written = cast("Seating", seats)
    models = sorted(
        str(one) for one, seat in written.items() if isinstance(seat, Model)
    )
    if models:
        raise ValueError(
            f"the activity {key!r} gives {', '.join(models)} to a model, and a "
            "browser run cannot reach a provider: a credential must not travel to a "
            "participant's browser. Run it on the server, or seat an exported "
            "network with Bot(...)."
        )


def _refuse_a_person_with_no_keys(
    key: str, found: Derived, seats: Any, keys: Any
) -> None:
    """Refuse a person at a keyboard that is bound to nothing.

    Nothing in either environment API says which key is which action, and the
    ``gymnasium.utils.play`` convention is the only place one is ever declared. An
    environment that declares none and a study that writes none leaves a participant
    pressing keys that do nothing.
    """
    if keys is not None or found.keys is not None:
        return
    if seats is None or not isinstance(seats, Mapping):
        return
    written = cast("Seating", seats)
    if not any(isinstance(seat, Human) for seat in written.values()):
        return
    raise ValueError(
        f"the activity {key!r} seats a person, and nothing says which key is which "
        "action: its environment declares no get_keys_to_action, so write keys={...} "
        f"with held_actions= and default_action=. Its action space is "
        f"{next(iter(found.actions.values()), 'unknown')}."
    )


def _refuse_keys_that_do_not_say_how_they_act(
    key: str,
    keys: Mapping[Any, int] | None,
    held_actions: bool | None,
    default_action: int | None,
) -> None:
    """Refuse a key binding that leaves how it acts, or what nothing does, unsaid.

    Both are refused rather than defaulted, and each for a concrete failure that has
    happened here: held keys turned a 100 ms tap into three actions, and an action
    ``0`` that is "walk north" rather than "do nothing" makes a chef walk upward for a
    whole round with nothing in the records to say why.
    """
    if keys is None:
        return
    if not keys:
        raise ValueError(f"the activity {key!r} binds no keys, so it binds nothing")
    missing: list[str] = []
    if held_actions is None:
        missing.append(
            "  held_actions=True if a bound key acts on every frame it is down (a "
            "court, a car),\n  held_actions=False if one press is worth one action "
            "however long it is held (a grid).\n  The two play completely differently, "
            "so neither is a safe guess."
        )
    if default_action is None:
        missing.append(
            "  default_action= what a frame with no bound key takes. Action 0 is a "
            "no-op in\n  some environments and a move in others, so guessing it makes "
            "a chef walk\n  north for a whole round."
        )
    if missing:
        raise ValueError(
            f"the activity {key!r} binds keys and does not say how they act:\n"
            + "\n".join(missing)
        )


def _refuse_a_game_nobody_can_see(
    key: str, found: Derived, seats: Any, render: Any
) -> None:
    """Refuse a game with a person in it and no picture of any kind.

    The environment's own frames are the default drawing, so this only fires when the
    environment hands over none *and* the study wrote none. Today that is a study
    that runs and shows a participant an empty canvas -- which is exactly what two
    shipped examples did.
    """
    if render is not None or found.draws:
        return
    if seats is None or not isinstance(seats, Mapping):
        return
    written = cast("Seating", seats)
    if not any(isinstance(seat, Human) for seat in written.values()):
        return
    raise ValueError(
        f"the activity {key!r} seats a person and has no picture: the environment "
        f"drew nothing ({found.draw_blocked_by}), so write render=. A participant "
        "cannot play a canvas that stays empty."
    )


# -- the study ----------------------------------------------------------------------


@dataclass(frozen=True)
class Study:
    """The ordered activities one participant walks through."""

    activities: tuple[Activity, ...]
    assets: tuple[Any, ...]
    _study_wide: tuple[Any, ...] = ()
    generate: Any = None
    state: tuple[Any, ...] = ()

    def __init__(
        self,
        *activities: Activity,
        assets: Sequence[Any] = (),
        generate: Any = None,
        state: Sequence[Any] = (),
    ) -> None:
        if not activities:
            raise ValueError("a study needs at least one activity")
        keys = [one.key for one in activities]
        if len(set(keys)) != len(keys):
            raise ValueError("a study names each activity once")
        object.__setattr__(self, "activities", tuple(activities))
        object.__setattr__(self, "_study_wide", tuple(assets))
        object.__setattr__(self, "assets", _gathered(activities, assets))
        object.__setattr__(self, "generate", generate)
        object.__setattr__(self, "state", tuple(state))

    def assets_for(self, key: str) -> tuple[Any, ...]:
        """Return the pictures that must be loaded before one activity.

        This is what declaring an asset on the activity buys. The current platform
        stages every picture a study ships and marks them all
        ``required_before_activity``, so a study with two environments makes a
        participant wait for both sets before the first round.
        """
        for one in self.activities:
            if one.key == key:
                return tuple(self.study_wide) + one.assets
        raise KeyError(key)

    @property
    def study_wide(self) -> tuple[Any, ...]:
        """Return the pictures the study itself ships, needed everywhere."""
        return self._study_wide

    @property
    def requires(self) -> tuple[str, ...]:
        """Return every package this study's environments need, pinned and merged.

        Derived, so a study with two environments cannot pin one and forget the
        other, and the pin a browser installs cannot drift from the version the
        server verifies against.
        """
        found: set[str] = set()
        for one in self.activities:
            if one.found is not None:
                found.update(one.found.requires)
        return tuple(sorted(found))

    def plan(self) -> list[str]:
        """Return one line per activity: what it is, where it runs, and who is in it.

        The right-hand column is which of today's eight game mounts the activity
        resolves to. An author chose none of them.
        """
        lines: list[str] = []
        for one in self.activities:
            if one.kind == "game" and one.found is not None:
                who = ", ".join(
                    f"{agent}={type(seat).__name__.lower()}"
                    for agent, seat in (one.seats or {}).items()
                )
                rounds = "" if one.episodes == 1 else f" x{one.episodes}"
                drawn = "sprites" if one.render is not None else "env frames"
                if one.hud is not None:
                    drawn += "+hud"
                beside = " +chat" if one.chat is not None else ""
                lines.append(
                    f"{one.key:<12} game  {WHERE[str(one.execution)]}{rounds}{beside}"
                    f"  [{who}]  {drawn}  -> {one.mount}"
                )
            elif one.kind == "chat":
                who = ", ".join(
                    speaker.key or type(speaker.agent).__name__.lower()
                    for speaker in one.detail["speakers"]
                )
                people = one.detail["participants"]
                lines.append(
                    f"{one.key:<12} chat  {people} participant(s) with [{who}]"
                )
            else:
                lines.append(f"{one.key:<12} {one.kind}")
        return lines


def _gathered(
    activities: Sequence[Activity], study_wide: Sequence[Any]
) -> tuple[Any, ...]:
    """Gather every picture the study serves, refusing one name that means two files.

    Two activities may share a sheet -- a practice round and a real one draw the same
    kitchen -- so the same asset declared twice is read once. What is refused is one
    **name** standing for two different files, which would make a drawing draw whichever
    happened to be staged last. The message names both activities, because an author
    whose two sheets are both called ``terrain`` has to be told which two.
    """
    where: dict[str, tuple[str, str]] = {}
    gathered: list[Any] = []
    sources: list[tuple[str, Sequence[Any]]] = [("the study", study_wide)]
    sources += [(f"the activity {one.key!r}", one.assets) for one in activities]
    for source, assets in sources:
        for asset in assets:
            name = str(getattr(asset, "name", asset))
            path = str(getattr(asset, "image", None) or getattr(asset, "path", asset))
            held = where.get(name)
            if held is None:
                where[name] = (source, path)
                gathered.append(asset)
                continue
            if held[1] != path:
                raise ValueError(
                    f"the picture {name!r} is declared by {held[0]} as {held[1]!r} and "
                    f"by {source} as {path!r}; one study serves each picture by one "
                    "name, so rename one of them"
                )
    return tuple(gathered)


__all__ = [
    "Activity",
    "Bot",
    "Chat",
    "Execution",
    "Form",
    "Game",
    "Human",
    "Model",
    "Page",
    "Study",
]
