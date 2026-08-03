"""Define a whole study: the ordered activities a participant walks through.

This is the study author's surface. A study is a list of steps in the order the
participant meets them -- a consent form, a survey, the game, another survey, a
debrief -- and the game is one step among the others, not the thing everything
else is arranged around.

    study = Study(
        Form("consent", Choice("agree", "Do you consent to take part?", YES_NO)),
        Form("pre", Likert("mood", "How do you feel right now?", scale=5)),
        Game("play"),
        Form("post", Likert("teamwork", "How well did you work together?", 7)),
        Page("debrief", "# Thank you\\n\\nYou have finished the study."),
    )

The builders return the frozen API-17 records (``FormSpec``, ``ContentSpec``), so
what an author writes here is what the contract validates and what the ledger
records. They exist because writing those records by hand is a lot of ceremony
for "ask one question", and ceremony in the author's way is how studies end up
copied from a demo instead of written.

A ``Comparison`` (``mug.authoring``) is a step too, written directly in the list.
It asks the participant about runs they made earlier in the same study, so each
option names one of the study's own game activities:

    study = Study(
        Game("practice"),
        Game("play"),
        Comparison(
            key="which-was-better",
            ask="Which round went better?",
            options={"Practice": "practice", "Real round": "play"},
        ),
    )

The author's labels are for their own analysis and the participant never sees
them; the platform shows the two runs blinded, in an order it randomizes and
commits to (see ``mug.participant_comparison``).

A comparison may also be about model outputs rather than runs. Each option then
names one of the generations the study recorded before its participants arrived,
and the participant reads the two answers with no provider contacted and no
provider named:

    Comparison(
        key="which-answer",
        ask="Which answer is better?",
        of="model_output",
        options={"Warm": "warm-answer", "Dry": "dry-answer"},
    )

The generations themselves are the deployment's own, because a study can not
import a vendor: ``build_study_app(..., generate=GenerationSet(...))`` records
them once (see ``mug.agents.generation``).

A study that manipulates something writes the manipulation where it takes effect,
and the platform assigns, balances, and records it (see ``mug.visits.design``):

    difficulty = Treatment("difficulty", {"easy": easy_spec, "hard": hard_spec})

    study = Study(
        Page("intro", difficulty.map({"easy": "Take your time.",
                                      "hard": "You have 30 seconds."})),
        Game("play", difficulty),
    )
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, cast

from pydantic import Field

from mug.authoring import Comparison
from mug.content.assets import Asset, resolve_sheets
from mug.content.players import Human, Model, Seating
from mug.content.types import ContentBody, ContentSpec, FormField, FormSpec
from mug.game.environments import Derived, EnvFactory, derive
from mug.interactions.monitoring import Screen
from mug.kernel._base import KernelModel
from mug.visits.design import (
    Assign,
    Design,
    Order,
    Placement,
    Scope,
    Treatment,
    Unit,
    placed,
)
from mug.visits.eligibility import EligibilityRule, rule_name
from mug.visits.state import State, declared
from mug.visits.types import FieldRef

AuthoringKey = Annotated[
    str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=128)
]
ActivityKind = Literal["form", "content", "game", "chat", "comparison"]

# Where a game activity's environment steps. Two words, because there are two places
# it can: the server the study runs on, or the participant's own browser.
#
# It is written rather than derived, and it stays on the activity rather than moving to
# the application, because it is a study decision the participant feels. A browser run
# is a Python runtime downloaded before the first round, and it changes what
# verification means -- the server re-executes the reported run instead of recording it
# as it is stepped. So it is never acquired silently.
Execution = Literal["server", "browser"]

# How each execution is said in a message an author reads. "in the server" is not
# English, and a refusal an author has to translate is a worse refusal.
WHERE: Mapping[str, str] = {
    "server": "on the server",
    "browser": "in the participant's browser",
}


class Activity(KernelModel):
    """One authored study step: a key, a kind, and the content it presents.

    A comparison activity holds no content here: what it presents is the runs the
    participant made earlier in this visit, which exist only once they play. The
    study keeps the author's ``Comparison`` beside the activities and the mount
    resolves it per participant.
    """

    key: AuthoringKey
    kind: ActivityKind
    form: FormSpec | None = None
    content: ContentSpec | None = None


# -- the fields a form asks -----------------------------------------------------


def Choice(
    key: str, label: str, options: Sequence[str], *, required: bool = True
) -> FormField:
    """Ask the participant to pick one of the named options."""
    return FormField(
        field_key=key,
        kind="choice",
        label=label,
        required=required,
        options=list(options),
    )


def Likert(key: str, label: str, scale: int = 5, *, required: bool = True) -> FormField:
    """Ask the participant to rate something from one to ``scale``."""
    return FormField(
        field_key=key, kind="likert", label=label, required=required, scale=scale
    )


def Text(key: str, label: str, *, required: bool = False) -> FormField:
    """Ask the participant to write something. Optional unless you say otherwise."""
    return FormField(field_key=key, kind="text", label=label, required=required)


# -- the steps a study is made of -----------------------------------------------


@dataclass(frozen=True)
class Step:
    """One step of a study: the activity it records and any runtime it needs.

    ``content`` is set instead of ``activity.content`` when the page a participant
    reads depends on their condition: it holds one written page per level, and the
    platform picks the one their assignment names.
    """

    activity: Activity
    game: Any = None
    comparison: Comparison | None = None
    content: Placement | None = None
    rounds: Rounds | None = None
    # What this activity plays, and everything read off it. Set when the study named
    # its own environment rather than leaving the application to mount one.
    plays: GameActivity | None = None
    # The conversation this activity **is**, when it is one. Distinct from ``chat``,
    # which is a conversation beside a game: this is the whole activity.
    talk: Conversation | None = None
    # What the participant reads beside the game while they play it: the controls,
    # which chef is theirs, what a delivered dish is worth. It is written material
    # like any page, so it is markdown and it may name the study's own pictures.
    caption: str | None = None
    # How large the picture this game draws is, in pixels.
    size: tuple[int, int] | None = None
    # The conversation this activity also carries, when it carries one, as the
    # author wrote it. What it compiles to lives well above the written study, so
    # what is held here is ``Chat(...)`` and never the runtime's own specification.
    chat: Conversation | None = None
    # Who is in this activity's environment, when the study says: one map from the
    # environment's own agent to the ``Human`` / ``Model`` / ``Bot`` that plays it.
    # Opaque here for the same reason the game specification is -- what a seat needs
    # to run lives well above the study.
    seats: Any = None

    def field(self, field_key: str) -> FieldRef:
        """Return a pointer to one of this form's fields.

        It is what ``Assign.stratified(by=...)`` names, so a study writes
        ``Assign.stratified(by=pre.field("handedness"))`` rather than repeating the
        two keys as strings.
        """
        return FieldRef(activity_key=self.activity.key, field_key=field_key)


def Form(key: str, *fields: FormField, version: int = 1) -> Step:
    """Ask the participant a set of questions before they may continue."""
    if not fields:
        raise ValueError(f"the form {key!r} asks nothing")
    return Step(
        Activity(
            key=key,
            kind="form",
            form=FormSpec(form_key=key, fields=list(fields), version=version),
        )
    )


def _page(key: str, markdown: str, version: int) -> ContentSpec:
    """Build one written page."""
    return ContentSpec(
        content_key=key,
        body=ContentBody(
            origin="author",
            source="inline",
            format="markdown",
            executable=False,
            text=markdown,
        ),
        response_required=False,
        version=version,
    )


def Page(key: str, markdown: Any, *, version: int = 1) -> Step:
    """Show the participant something to read: instructions, a debrief, a notice.

    ``markdown`` is usually the text. It may instead be a treatment placed here --
    ``Page("intro", difficulty.map({"easy": ..., "hard": ...}))`` -- and then the
    participant reads the page their assigned level names.
    """
    placement = placed(markdown)
    if placement is None:
        return Step(
            Activity(key=key, kind="content", content=_page(key, markdown, version))
        )
    return Step(
        Activity(key=key, kind="content"),
        content=Placement(
            treatment=placement.treatment,
            values={
                level: _page(key, placement.value_for(level), version)
                for level in placement.treatment.level_keys
            },
        ),
    )


@dataclass(frozen=True)
class Rounds:
    """How many times one game activity is played, and what sits between rounds.

    ``count`` is the episode limit: the activity ends after that many rounds
    whatever the environment does. ``between`` is the screen a participant reads
    between them -- the interval, where they rest, read their score, or simply
    press on when they are ready.
    """

    count: int = 1
    between: str | None = None

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError("a game activity plays at least one round")


@dataclass(frozen=True)
class GameActivity:
    """One game activity's whole play: what it runs, where, and who is in it.

    An author writes none of this directly. It is what ``Game`` holds once it has read
    the environment the study named -- the agents, the action set, the frame rate, the
    episode bound, the drawing, and the packages a browser must install are all on
    ``found``. So a mount is chosen from what the study said and what its environment
    is, rather than from a keyword the author had to pick.
    """

    key: str
    env: EnvFactory
    found: Derived
    runs: Execution
    seats: Seating | None = None
    keys: Mapping[str, int] | None = None
    held_actions: bool | None = None
    default_action: int | None = None
    fps: int | None = None
    render: Any = None
    scene: Any = None
    hud: Any = None
    assets: tuple[Asset, ...] = ()
    episodes: int = 1
    between: str | None = None
    caption: str | None = None
    size: tuple[int, int] | None = None
    chat: Conversation | None = None

    @property
    def rate(self) -> int | None:
        """Return the frame rate to play at, or ``None`` for the mount's own default.

        The study's ``fps=`` outranks the environment, because how fast a person plays
        is a study decision: the same environment is a training task at one rate and an
        experiment at another. With none written, the environment's declared
        ``render_fps`` stands.
        """
        if self.fps is not None:
            return self.fps
        return self.found.fps

    @property
    def people(self) -> int:
        """Count the seats a person plays."""
        return sum(1 for seat in (self.seats or {}).values() if isinstance(seat, Human))

    @property
    def models(self) -> int:
        """Count the seats a model plays."""
        return sum(1 for seat in (self.seats or {}).values() if isinstance(seat, Model))

    @property
    def bindings(self) -> Mapping[str, int]:
        """Return the key bindings this activity plays with, written or read.

        A study's own ``keys=`` wins, because a study that writes them has said the
        environment's are not the ones it wants. With none, the environment's own
        ``get_keys_to_action`` bindings are used, and with neither there are none --
        which only a game with no person in it may have.
        """
        return self.keys or self.found.keys or {}

    @property
    def held(self) -> bool:
        """Say whether a bound key acts on every frame it is down.

        A study that binds its own keys says this itself, because a grid and a court
        want opposite answers. A study that takes the environment's bindings takes
        ``True`` with them: the ``gymnasium.utils.play`` convention those come from is
        a map from the keys **held** on a frame to the action for that frame.
        """
        if self.held_actions is not None:
            return self.held_actions
        return self.keys is None and self.found.keys is not None

    @property
    def idle_action(self) -> int:
        """Return what a frame with no bound key takes."""
        if self.default_action is not None:
            return self.default_action
        if self.keys is None and self.found.default_action is not None:
            return self.found.default_action
        return 0


def Game(
    key: str,
    env: Any = None,
    *,
    runs: Execution = "server",
    seats: Any = None,
    keys: Mapping[str, int] | None = None,
    held_actions: bool | None = None,
    default_action: int | None = None,
    fps: int | None = None,
    render: Any = None,
    scene: Any = None,
    hud: Any = None,
    assets: Sequence[Asset] = (),
    episodes: int = 1,
    between: str | None = None,
    caption: str | None = None,
    size: tuple[int, int] | None = None,
    chat: Any = None,
) -> Step:
    """Play a game. ``env`` is the environment, and ``runs`` says where it steps.

    ``env`` is **something that takes no arguments and returns the environment the
    author trained in** -- a ``gymnasium.Env``, a PettingZoo ``ParallelEnv``, or a
    PettingZoo ``AECEnv``. An environment class is one of those. So is
    ``functools.partial(gymnasium.make, "MountainCar-v0")``. So is a study's own
    ``def kitchen(): ...``.

    It takes **no arguments** on purpose. Whatever an environment needs to be built is
    bound inside the callable, by the author, where they are already constructing it --
    including ``render_mode="rgb_array"`` if they want the environment's own frames. So
    the platform passes nothing in, a configuration holding live objects needs no
    written form to travel, and there is one kind of thing to hand over rather than
    three specification types.

    Everything else about the environment is read off it (``mug.game.environments``):
    the agents, the action set, the frame rate, the episode bound, the drawing, and the
    packages a browser must install. A study writes no specification of any kind, and
    the pin a browser installs cannot drift from the version the server verifies
    against, because both are the version installed here.

    ``runs`` is where the environment steps: ``"server"`` (the default) or
    ``"browser"``.

    ``seats`` says which of the environment's own agents each player takes --
    ``seats={"car": Human(), "traffic-light": Model(controller)}``. It is a **map,
    never a list**: which agent somebody plays is a study's most consequential
    decision, so it is written down rather than inferred from the order the seats
    appear in. A list would let a study that reorders two lines silently swap two
    roles, with nothing in the records to say it had happened. It is also the only
    place a study says somebody other than the participant is playing.

    ``keys`` maps a key -- or a chord, several keys held together -- to an action. It
    is the one thing no environment API can say. An environment that follows the
    ``gymnasium.utils.play`` convention declares its own, and a study naming such an
    environment writes none of the three input keywords.

    ``held_actions`` says whether a bound key acts on **every frame it is down**
    (``True``: a court, a car) or **once per press** (``False``: a grid, a card game).
    A grid and a court want opposite answers, so there is no default: the platform once
    shipped an input mode with no producer and no reader, every study read held keys,
    and a 100 ms tap became three actions.

    ``default_action`` is what a frame with no bound key takes, written for the same
    reason: action ``0`` is a reasonable no-op in some environments and "walk north" in
    others, so guessing it makes a chef walk upward for a whole round.

    ``fps`` is how many frames a second the participant plays at, and it outranks the
    environment: how fast somebody plays is a study decision, not a property of the
    task. Without one the environment's declared ``render_fps`` is used, and with
    neither the platform's own default stands.

    ``render`` is a drawing better than the frames the environment hands over: the
    study's own sprites, drawn by the name each was packed under. Without one the
    environment's own ``rgb_array`` frames are painted, which on a browser run costs
    nothing at all -- the pixels are drawn in the same browser that made them and never
    travel.

    ``scene`` is what a picture needs and an observation does not carry: a kitchen's
    pots and counters, a court's ball, a board's pieces. It is a function of the
    environment, called once a frame, and what it returns rides in that frame's own
    metrics -- so ``render`` reads ``step.info["scene"]``, and a replay and an export
    read the picture the participant actually saw. A drawing handed the live environment
    instead would draw from state that nothing kept.

    ``hud`` is the line a participant reads **on** the game while they play: the score
    they have, the time left, what they are carrying. It is a function of the step and
    returns one line; the platform draws the band, so a study never writes the band. It
    is drawn onto the same surface as the game, so it is in the record and in a replay
    -- what a participant was told is part of what happened to them.

    ``assets`` are the pictures **this** activity draws, declared where they are used
    rather than on the study. That has a consequence a participant feels: a picture is
    needed before the activity that draws it, so a study with a kitchen and a court no
    longer makes somebody download both sets before the first round. A picture the whole
    study needs (one an instruction page shows) is still declared on the ``Study``.

    ``episodes`` plays the activity that many times over, each as its own episode
    with its own identity and its own recorded trajectory. Three rounds of one game
    is one activity that plays three times, not three activities: the participant
    meets one task, and the data says which round each trajectory was.
    ``between`` is what they read between rounds; with none they go straight on.

    ``caption`` is what the participant reads beside the game **while they play**:
    which chef is theirs, which keys move it, what a delivered dish is worth. It is
    markdown, so it may show the study's own declared pictures -- a study whose
    controls are keys can show the keys. Without one the game stands on its own.

    ``size`` is how large the picture is, in pixels: ``size=(225, 180)`` for a
    kitchen of five squares by four drawn at forty-five pixels a square. A drawing
    is made of **relative** coordinates, so it has no size of its own -- it fills
    whatever it is given, and only the study knows how large that should be. A
    kitchen drawn into somebody else's 600 by 400 is a picture larger than the
    game in it, with every square stretched to a shape the sprites are not.

    The picture is never drawn larger than this. It is drawn **smaller**, in
    proportion, when there is not room for it -- a narrow window, a pane beside a
    conversation -- and it is fitted again when the window changes, so it is never
    wider than what it is in. Without one, 600 by 400 stands, which is what every
    game was drawn at before a study could say.

    ``chat`` gives the activity a conversation beside the game, in one interaction:
    the participants play and talk at once, and a model seat may take part in
    either. It is written as the author's own ``Chat(...)`` and nothing else --
    ``Game("cook", kitchen, chat=Chat("kitchen-talk"))``. The conversation is
    written here rather than mounted beside the study, because it happens here.

    **The conversation's own identity is its scope.** Pass the same value to two
    game activities and they share one conversation, so a pair who talked in the
    practice round carry that transcript into the real one; write ``Chat(...)``
    twice and they are two conversations that start fresh. What is shared is the
    authored channel; each activity is still its own interaction.

    Several rounds of one activity are always one conversation, because they are
    one interaction. What each model seat carries across the rest between rounds is
    the transcript and its own plan, and not the round's transitions: a round is
    its own episode.

    A study may hold more than one game activity -- a practice round and then the real
    one is the common case -- and each is recorded as its own episode under its own key.

    ``env`` may also be a written specification, or a treatment over written
    specifications, which is how a study said what it played before an environment
    could be named directly. That form is going away; a study being written now names
    its environment.
    """
    seating = _seating(key, seats)
    talk = _talked(key, chat)
    _refuse_a_size_that_is_not_one(key, size)
    found = _read_environment(env)
    if found is None:
        return Step(
            Activity(key=key, kind="game"),
            game=env,
            rounds=Rounds(count=episodes, between=between),
            caption=caption,
            size=size,
            chat=talk,
            seats=seating,
        )
    plays = GameActivity(
        key=key,
        env=cast("EnvFactory", env),
        found=found,
        runs=runs,
        seats=cast("Seating | None", seating),
        keys=keys,
        held_actions=held_actions,
        default_action=default_action,
        fps=fps,
        render=render,
        scene=scene,
        hud=hud,
        assets=tuple(assets),
        episodes=episodes,
        between=between,
        caption=caption,
        size=size,
        chat=talk,
    )
    _refuse_what_cannot_be_played(plays)
    return Step(
        Activity(key=key, kind="game"),
        rounds=Rounds(count=episodes, between=between),
        caption=caption,
        size=size,
        chat=talk,
        seats=seating,
        plays=plays,
    )


def _refuse_a_size_that_is_not_one(key: str, size: tuple[int, int] | None) -> None:
    """Refuse a picture size that describes no picture.

    It is refused while the author reads their own code rather than on the screen,
    where a nought or a negative number is a canvas of no height and a game nobody
    can see.
    """
    if size is None:
        return
    if len(size) != 2 or any(one <= 0 for one in size):
        raise ValueError(
            f"the game {key!r} says its picture is {size!r}. A size is a width and "
            "a height in pixels, both above nought: size=(225, 180)."
        )


def _no_settings() -> Mapping[str, Any]:
    """Return an empty, typed settings map for a conversation's default."""
    return {}


@dataclass(frozen=True)
class Conversation:
    """One conversation activity, as its author wrote it.

    An author writes ``Chat(...)`` and this is what it holds. It is the author's own
    words and nothing derived: the pinned build each model seat records, the actor it
    is recorded as, and the provider adapter it reaches are all computed where the
    conversation is mounted, because none of them is a study decision.
    """

    key: str
    speakers: tuple[Any, ...] = ()
    participants: int = 1
    greeting: str | None = None
    max_messages: int = 20
    placement: Literal["beside", "below", "drawer"] = "beside"
    elicit: Any = None
    settings: Mapping[str, Any] = field(default_factory=_no_settings)


def Chat(
    key: str,
    *speakers: Any,
    participants: int = 1,
    greeting: str | None = None,
    max_messages: int = 20,
    placement: Literal["beside", "below", "drawer"] = "beside",
    elicit: Any = None,
    **settings: Any,
) -> Step:
    """Hold a conversation. It is an activity of its own, not a game with no game.

    A study used to write ``Game("talk")`` and hand the application a conversation,
    which replaced the whole game hook. Three things were wrong with that at once: the
    study said "a game" where a conversation happens, the recorded activity kind said
    the participant played a game, and a study could hold a conversation **or** a game
    but never one of each.

    ``speakers`` are the models in the room, written exactly as a game activity's
    seating writes one: ``Chat("interview", Model(interviewer))``. A conversation with
    no model in it is a conversation between participants, which is what
    ``participants=2`` and no speaker means.

    ``participants`` is how many people share one room, so two people and one model is
    ``participants=2``. ``greeting`` is what the room opens with. ``max_messages``
    bounds it, so a participant who never leaves still reaches the next activity.
    ``elicit`` asks them to choose between candidate replies on the turns the study
    elicits, and the conversation goes on from the reply they chose.

    A conversation **beside a game** is written the same way and handed to the game
    (``Game(..., chat=Chat(...))``), because it happens there: the participants play
    and talk in one interaction. ``placement`` is where it sits against the game --
    ``beside`` it (the default), ``below`` it, or in a ``drawer`` that opens over it.
    It is a design variable rather than decoration, because a transcript below the
    fold is read less than one beside the canvas. An activity that is only a
    conversation ignores it, because there is nothing to place it against.
    """
    return Step(
        Activity(key=key, kind="chat"),
        talk=Conversation(
            key=key,
            speakers=speakers,
            participants=participants,
            greeting=greeting,
            max_messages=max_messages,
            placement=placement,
            elicit=elicit,
            settings=settings,
        ),
    )


def _talked(key: str, chat: Any) -> Conversation | None:
    """Return the conversation an activity carries, from what the author wrote.

    An author writes ``Chat(...)``, which is a whole step, and hands it here. What
    is kept is the conversation inside it, because the step's activity is not this
    activity: this activity is the game, and the conversation happens in it.

    Anything else is refused by name. It used to be that the runtime's own
    ``ChatSpec`` was what this keyword took -- a dataclass of twenty fields, none of
    them a decision an author should be making -- and a study that passed the
    author's own ``Chat(...)`` instead got no conversation and no complaint.
    """
    if chat is None:
        return None
    if isinstance(chat, Step) and chat.talk is not None:
        return chat.talk
    if isinstance(chat, Conversation):
        return chat
    raise ValueError(
        f"the game {key!r} must say its conversation as the author's own: "
        f'Game(key, env, chat=Chat("talk")). It was given a '
        f"{type(chat).__name__}."
    )


def _read_environment(env: Any) -> Derived | None:
    """Read the environment a study named, or answer None for what is not one.

    Two things reach here, and they are told apart by whether they can be **called**.
    An environment is something that builds one and takes no arguments, so it is
    callable; a written specification and a treatment over written specifications are
    values, so they are not. Nothing that has ever been passed as a specification is
    callable, and nothing that builds an environment is not, so the question has one
    answer for each.

    A **name** is neither, and is sent to be refused rather than read as a
    specification: a registered id is what an author who has read the older
    documentation writes, so they are told what to write instead of being left with a
    failure much further on.
    """
    if env is None or (not callable(env) and not isinstance(env, str)):
        return None
    return derive(cast("EnvFactory", env))


def _seating(key: str, seats: Any) -> dict[Any, Any] | None:
    """Return the activity's seating, refusing anything that does not name agents.

    A sequence of players is refused rather than accepted positionally: the point
    of the map is that the environment agent each player takes is stated, and a
    list states it only by accident of order.
    """
    if seats is None:
        return None
    if not isinstance(seats, Mapping):
        raise ValueError(
            f"the game {key!r} must say which agent each player takes: "
            'Game(key, env, seats={"car": Human(), "traffic-light": Model(x)})'
        )
    written = cast("Mapping[Any, Any]", seats)
    if not written:
        raise ValueError(f"the game {key!r} names a seating with nobody in it")
    return dict(written)


# -- what a game activity is refused for ----------------------------------------


def _refuse_what_cannot_be_played(plays: GameActivity) -> None:
    """Refuse a game activity that cannot be played as it is written.

    Every one of these is silent today: the study builds, the participant arrives, and
    the fault reads as the platform failing. They are asked here, where the author is
    still reading their own code, and each is asked of the environment rather than of
    something the author had to declare -- which is what reading the environment buys.
    """
    _refuse_an_execution_it_cannot_run(plays)
    _refuse_an_unknown_agent(plays)
    _refuse_rounds_that_cannot_loop(plays)
    _refuse_a_model_that_cannot_reach_a_provider(plays)
    _refuse_a_person_with_no_keys(plays)
    _refuse_keys_that_do_not_say_how_they_act(plays)
    _refuse_a_game_nobody_can_see(plays)
    _refuse_a_scene_with_no_reader(plays)


def _refuse_an_execution_it_cannot_run(plays: GameActivity) -> None:
    """Refuse a browser run the environment's own packages cannot support.

    The reasons come from the environment: study code a browser cannot import,
    compiled code with no wheel for the browser runtime's platform, a distribution
    that is not installed at all. Today this is a download that fails in front of a
    participant.
    """
    if plays.runs == "browser" and plays.found.blocks:
        raise ValueError(
            f"the game {plays.key!r} cannot run in a browser: {plays.found.blocks[0]}"
        )


def _refuse_an_unknown_agent(plays: GameActivity) -> None:
    """Refuse a seating that names an agent the environment does not have.

    The agents are read off the environment, so this needs nothing from the author. A
    mistyped seat survives the build today and raises ``KeyError`` on the first frame
    of a participant's run.
    """
    if plays.seats is None:
        return
    unknown = sorted(str(one) for one in set(plays.seats) - set(plays.found.agents))
    if unknown:
        has = ", ".join(repr(one) for one in plays.found.agents)
        raise ValueError(
            f"the game {plays.key!r} seats {', '.join(unknown)}, which its environment "
            f"does not have; its agents are: {has}"
        )


def _refuse_rounds_that_cannot_loop(plays: GameActivity) -> None:
    """Refuse rounds the execution plays once and says nothing about.

    A browser run is written by the client and reported once, so ``episodes=5`` would
    play **one** round and move on. That is the worst kind of fault: the author said
    what they wanted, the platform read it, and nothing in the records would say it had
    been dropped.
    """
    if plays.episodes > 1 and plays.runs != "server":
        raise ValueError(
            f"the game {plays.key!r} asks for {plays.episodes} rounds, and a browser "
            "run plays one: the client writes the whole episode and reports it once. "
            f"Write {plays.episodes} game activities, or run it on the server."
        )


def _refuse_a_model_that_cannot_reach_a_provider(plays: GameActivity) -> None:
    """Refuse a model seat in an execution that has no way to reach a provider.

    A participant's browser holds no credential and must never be given one, so a
    model seat needs the server in the loop. An exported network is a different kind
    of seat (``Bot``) and runs in either place.
    """
    if plays.seats is None or plays.runs == "server":
        return
    models = sorted(
        str(one) for one, seat in plays.seats.items() if isinstance(seat, Model)
    )
    if models:
        raise ValueError(
            f"the game {plays.key!r} gives {', '.join(models)} to a model, and a "
            "browser run cannot reach a provider: a credential must not travel to a "
            "participant's browser. Run it on the server, or seat an exported network "
            "with Bot(...)."
        )


def _refuse_a_person_with_no_keys(plays: GameActivity) -> None:
    """Refuse a person at a keyboard that is bound to nothing.

    Neither environment API says which key is which action, and the
    ``gymnasium.utils.play`` convention is the only place one is ever declared. An
    environment that declares none and a study that writes none leaves a participant
    pressing keys that do nothing.
    """
    if plays.bindings or not plays.people:
        return
    raise ValueError(
        f"the game {plays.key!r} seats a person, and nothing says which key is which "
        "action: its environment declares no get_keys_to_action, so write keys={...} "
        "with held_actions= and default_action=. Its action space is "
        f"{next(iter(plays.found.actions.values()), 'unknown')}."
    )


def _refuse_keys_that_do_not_say_how_they_act(plays: GameActivity) -> None:
    """Refuse a key binding that leaves how it acts, or what nothing does, unsaid.

    Both are refused rather than defaulted, and each for a failure that has happened
    here: held keys turned a 100 ms tap into three actions, and an action ``0`` that is
    "walk north" rather than "do nothing" makes a chef walk upward for a whole round
    with nothing in the records to say why.
    """
    if plays.keys is None:
        return
    if not plays.keys:
        raise ValueError(f"the game {plays.key!r} binds no keys, so it binds nothing")
    missing: list[str] = []
    if plays.held_actions is None:
        missing.append(
            "  held_actions=True if a bound key acts on every frame it is down (a "
            "court, a car),\n  held_actions=False if one press is worth one action "
            "however long it is held (a grid).\n  The two play completely "
            "differently, so neither is a safe guess."
        )
    if plays.default_action is None:
        missing.append(
            "  default_action= what a frame with no bound key takes. Action 0 is a "
            "no-op in\n  some environments and a move in others, so guessing it makes "
            "a chef walk\n  north for a whole round."
        )
    if missing:
        raise ValueError(
            f"the game {plays.key!r} binds keys and does not say how they act:\n"
            + "\n".join(missing)
        )


def _refuse_a_game_nobody_can_see(plays: GameActivity) -> None:
    """Refuse a game with a person in it and no picture the platform can paint.

    Today a study with no drawing runs and shows a participant an empty canvas, which
    is exactly what two shipped examples did.

    An environment that hands over its own ``rgb_array`` frames does **not** satisfy
    this, and the message says so rather than pretending otherwise: the eight surface
    commands are shapes, text, and a named sprite, and none of them paints a bitmap.
    So a frame the environment drew has nowhere to go, and until it has one, a picture
    means a drawing the study wrote. It is said out loud here, because an environment
    that draws and a platform that cannot paint it is the worst possible silence.
    """
    if plays.render is not None or not plays.people:
        return
    why = (
        "the environment hands over its own rgb_array frames, and the platform "
        "cannot paint a bitmap yet: the surface commands are shapes, text, and "
        "named sprites"
        if plays.found.draws
        else f"the environment drew nothing ({plays.found.draw_blocked_by})"
    )
    raise ValueError(
        f"the game {plays.key!r} seats a person and has no picture it can show: "
        f"{why}. Write render= to draw the game from what a step returns. A "
        "participant cannot play a canvas that stays empty."
    )


def _refuse_a_scene_with_no_reader(plays: GameActivity) -> None:
    """Refuse a scene on an activity whose runtime carries no per-frame metrics.

    A turn-based episode records a move and the observations it produced, and nothing
    else: ``TurnState`` has no metrics field, and a turn-based game draws no picture on
    this platform at all. So a scene written here would be computed on every turn and
    read by nobody.

    It is refused rather than accepted, because a keyword that silently does nothing is
    the failure this platform keeps finding in itself: a field with no reader looks
    exactly like a field that works.
    """
    if plays.scene is None or not plays.found.takes_turns:
        return
    raise ValueError(
        f"the game {plays.key!r} writes scene= and takes turns, and a turn-based "
        "episode carries no per-frame metrics for a scene to ride in -- nothing would "
        "read it. Record what a turn produced in the environment's own observation."
    )


def _conversations(written: list[Step]) -> dict[str, str]:
    """Name the conversation each activity takes part in, by the author's own value.

    The author decides the scope by writing one value or two: the same
    conversation passed to two activities is one conversation that carries across
    them, and two written conversations are two. So the grouping is by **identity**
    and not by equality -- ``Chat(...)`` written twice makes two equal values that
    are meant to be two separate conversations.

    The name is the first activity that used it, never the object's address, which
    would differ between the process that published the study and the process that
    runs it.
    """
    named: dict[int, str] = {}
    conversations: dict[str, str] = {}
    for step in written:
        if step.chat is None:
            continue
        conversations[step.activity.key] = named.setdefault(
            id(step.chat), step.activity.key
        )
    return conversations


def _as_step(step: Step | Comparison) -> Step:
    """Read one written step, turning an author's comparison into its activity."""
    if isinstance(step, Comparison):
        return Step(Activity(key=step.key, kind="comparison"), comparison=step)
    return step


def _gathered_assets(
    study_wide: Sequence[Asset], written: Sequence[Step]
) -> tuple[Asset, ...]:
    """Gather every picture the study serves, refusing one name that means two files.

    Two activities may declare the same sheet -- a practice round and a real one draw
    the same kitchen -- and it is read and served once. What is refused is one **name**
    standing for two different files, which would make a drawing paint whichever
    happened to be staged last. The message names both places, because an author whose
    two sheets are both called ``terrain`` has to be told which two.

    The order is the study's own pictures first and then each activity's in the order
    they are written, so one study always gathers to one list -- and therefore to one
    study version.
    """
    where: dict[str, tuple[str, str]] = {}
    gathered: list[Asset] = []
    sources: list[tuple[str, Sequence[Asset]]] = [("the study", study_wide)]
    sources += [
        (f"the game {step.plays.key!r}", step.plays.assets)
        for step in written
        if step.plays is not None
    ]
    for source, assets in sources:
        for asset in assets:
            held = where.get(asset.name)
            if held is None:
                where[asset.name] = (source, asset.path)
                gathered.append(asset)
                continue
            if held[1] != asset.path:
                raise ValueError(
                    f"the picture {asset.name!r} is declared by {held[0]} as "
                    f"{held[1]!r} and by {source} as {asset.path!r}; one study serves "
                    "each picture by one name, so rename one of them"
                )
    return tuple(gathered)


# -- the study ------------------------------------------------------------------


@dataclass(frozen=True)
class Study:
    """The ordered activities one participant walks through, start to finish.

    The order is the order they are written. A study needs at least one step, and
    the platform holds it as data: the same value materializes each visit's flow,
    presents each activity, and checks each answer.

    A study may play more than one game -- a practice round, then the real one --
    and each game activity is one episode with its own identity. The only rule is
    that each activity has its own key, because the key is how a step is presented,
    answered, and recorded.

    A ``Comparison`` is written straight into the list, with no wrapper: it is the
    author's whole definition of that step, so the study reads it as one.

    ``design`` is the optional crossing: with none, every treatment the study places
    is balanced on its own, which is what independent factors mean. With one, the
    named factors are balanced jointly, cell by cell.

    ``screen`` is the connection quality the study needs (``Screen``): the platform
    measures it, warns, and then excludes, and records every step. ``admit`` is the
    study's own entry rule -- a plain module-level function that reads what the
    server knows about the connection and returns True or a reason to refuse. Both
    are optional, and a study that declares neither is screened on nothing.

    ``assets`` are the pictures the **whole study** needs (``Image``, ``Atlas``): the
    ones a page shows, or that every activity draws. The pictures one game activity
    draws are declared on that activity (``Game(..., assets=[...])``), so they are
    needed before it and not before everything. Each is read, digested, and served by
    its own digest, and a drawing names it by name alone. ``asset_root`` is the
    directory the paths are relative to; it defaults to the working directory the study
    runs from.

    ``state`` declares what a participant carries from one activity to the next
    (``State``): each namespace is versioned on its own and says who may read it
    and who may write it. A namespace nobody declared cannot be written, and a
    later part of a study receives only the namespaces it declares itself.
    """

    activities: tuple[Activity, ...]
    games: Mapping[str, Any]
    game_activities: Mapping[str, GameActivity]
    talks: Mapping[str, Conversation]
    seats: Mapping[str, Mapping[str, Any]]
    chats: Mapping[str, Conversation]
    conversations: Mapping[str, str]
    comparisons: Mapping[str, Comparison]
    contents: Mapping[str, Placement]
    rounds: Mapping[str, Rounds]
    captions: Mapping[str, str]
    sizes: Mapping[str, tuple[int, int]]
    design: Design | None
    screen: Screen | None
    admit: EligibilityRule | None
    assets: tuple[Asset, ...]
    study_assets: tuple[Asset, ...]
    asset_root: str | None
    state: Mapping[str, State]

    def __init__(
        self,
        *steps: Step | Comparison,
        design: Design | None = None,
        screen: Screen | None = None,
        admit: EligibilityRule | None = None,
        assets: Sequence[Asset] = (),
        asset_root: str | None = None,
        state: Sequence[State] = (),
    ) -> None:
        if not steps:
            raise ValueError("a study needs at least one activity")
        written = [_as_step(step) for step in steps]
        keys = [step.activity.key for step in written]
        if len(set(keys)) != len(keys):
            raise ValueError("a study names each activity once")
        object.__setattr__(self, "activities", tuple(step.activity for step in written))
        object.__setattr__(
            self,
            "games",
            {
                step.activity.key: step.game
                for step in written
                if step.activity.kind == "game" and step.game is not None
            },
        )
        object.__setattr__(
            self,
            "game_activities",
            {
                step.activity.key: step.plays
                for step in written
                if step.plays is not None
            },
        )
        object.__setattr__(
            self,
            "talks",
            {
                step.activity.key: step.talk
                for step in written
                if step.talk is not None
            },
        )
        object.__setattr__(
            self,
            "seats",
            {
                step.activity.key: step.seats
                for step in written
                if step.seats is not None
            },
        )
        object.__setattr__(
            self,
            "chats",
            {step.activity.key: step.chat for step in written if step.chat is not None},
        )
        object.__setattr__(self, "conversations", _conversations(written))
        object.__setattr__(
            self,
            "comparisons",
            {
                step.activity.key: step.comparison
                for step in written
                if step.comparison is not None
            },
        )
        object.__setattr__(
            self,
            "contents",
            {
                step.activity.key: step.content
                for step in written
                if step.content is not None
            },
        )
        object.__setattr__(
            self,
            "rounds",
            {
                step.activity.key: step.rounds
                for step in written
                if step.rounds is not None and step.rounds.count > 1
            },
        )
        object.__setattr__(
            self,
            "captions",
            {
                step.activity.key: step.caption
                for step in written
                if step.caption is not None
            },
        )
        object.__setattr__(
            self,
            "sizes",
            {
                step.activity.key: step.size
                for step in written
                if step.size is not None
            },
        )
        object.__setattr__(self, "design", design)
        object.__setattr__(self, "screen", screen)
        if admit is not None:
            # Refused while the author is still reading their own code, rather than
            # at the first participant: a rule with no addressable name can not be
            # recorded, and a screen nobody can find again is not evidence.
            rule_name(admit)
        object.__setattr__(self, "admit", admit)
        # A sheet's frames are read here, because this is the one place that knows
        # both the declaration and the asset root. The study version is computed from
        # what an asset is, so an unread sheet would give one version for two packings.
        object.__setattr__(
            self, "study_assets", resolve_sheets(assets, root=asset_root)
        )
        object.__setattr__(
            self,
            "assets",
            resolve_sheets(_gathered_assets(assets, written), root=asset_root),
        )
        object.__setattr__(self, "asset_root", asset_root)
        object.__setattr__(self, "state", declared(state))

    def comparison(self, key: str) -> Comparison:
        """Return the author's comparison for one comparison activity."""
        return self.comparisons[key]

    def activity(self, key: str) -> Activity:
        """Return the authored activity for one key."""
        for activity in self.activities:
            if activity.key == key:
                return activity
        raise KeyError(key)

    def assets_for(self, key: str) -> tuple[Asset, ...]:
        """Return the pictures that must be loaded before one activity.

        This is what declaring a picture on the activity buys. Every picture a study
        ships is marked "needed before the activity", so with all of them at study
        level a study with two environments makes a participant wait for both sets
        before the first round.

        The pictures come from the study's own gathered list rather than from the
        activity's declaration, so each is the one whose frames were read against the
        asset root -- one value, read once, wherever it is asked for.
        """
        found = self.game_activities.get(key)
        wanted = {one.name for one in self.study_assets}
        if found is not None:
            wanted.update(one.name for one in found.assets)
        return tuple(one for one in self.assets if one.name in wanted)

    @property
    def game_keys(self) -> tuple[str, ...]:
        """Return the keys of the study's game activities, in their own order.

        A study may have none (a questionnaire), one, or several. Each one is a
        separate episode with its own identity, so a practice round and the real
        round are recorded beside each other rather than one over the other.
        """
        return tuple(
            activity.key for activity in self.activities if activity.kind == "game"
        )

    @property
    def requires(self) -> tuple[str, ...]:
        """Return every package this study's environments need, pinned and merged.

        Derived, so a study with two environments cannot pin one and forget the other,
        and the pin a participant's browser installs cannot drift from the version the
        server verifies its run against. Written by hand in two places, those two were
        once allowed to differ, and the consequence is that every honest run is
        refused.
        """
        found: set[str] = set()
        for plays in self.game_activities.values():
            found.update(plays.found.requires)
        return tuple(sorted(found))


__all__ = [
    "Activity",
    "ActivityKind",
    "Assign",
    "AuthoringKey",
    "Chat",
    "Choice",
    "Comparison",
    "Conversation",
    "Design",
    "Execution",
    "Form",
    "Game",
    "GameActivity",
    "Likert",
    "Order",
    "Page",
    "Placement",
    "Rounds",
    "Scope",
    "Screen",
    "Step",
    "Study",
    "Text",
    "Treatment",
    "Unit",
]
