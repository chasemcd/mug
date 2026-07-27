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
from dataclasses import dataclass
from typing import Annotated, Any, Literal, cast

from pydantic import Field

from mug.authoring import Comparison
from mug.content.assets import Asset
from mug.content.types import ContentBody, ContentSpec, FormField, FormSpec
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
ActivityKind = Literal["form", "content", "game", "comparison"]


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
    # The conversation this activity also carries, when it carries one. It is held
    # as an opaque value for the same reason the game specification is: what a
    # conversation needs to run lives well above the written study.
    chat: Any = None
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


def Game(
    key: str,
    spec: Any = None,
    *,
    episodes: int = 1,
    between: str | None = None,
    chat: Any = None,
    seats: Any = None,
) -> Step:
    """Play a game. ``spec`` is the settings for this one, when they differ.

    ``episodes`` plays the activity that many times over, each as its own episode
    with its own identity and its own recorded trajectory. Three rounds of one game
    is one activity that plays three times, not three activities: the participant
    meets one task, and the data says which round each trajectory was.
    ``between`` is what they read between rounds; with none they go straight on.

    A study may hold more than one game activity -- a practice round and then the
    real one is the common case -- and each is recorded as its own episode under
    its own key. ``spec`` is the specification that activity runs: a shorter
    practice round is ``Game("practice", replace(game, max_steps=20))``. With
    ``spec`` unset the activity runs whatever the application mounted, so a study
    that plays the same game twice writes ``Game("practice")`` and ``Game("play")``
    and configures it once.

    ``spec`` may be a treatment instead of a specification --
    ``Game("play", Treatment("difficulty", {"easy": easy, "hard": hard}))`` -- and
    the activity then runs the specification the participant's assigned level names.
    A within-subject treatment repeats the activity once per level.

    ``chat`` gives the activity a conversation beside the game, in one interaction:
    the participants play and talk at once, and a model seat may take part in
    either. The conversation is written here rather than mounted beside the study,
    because it happens here.

    **The conversation's own identity is its scope.** Pass the same value to two
    game activities and they share one conversation, so a pair who talked in the
    practice round carry that transcript into the real one; write ``Chat(...)``
    twice and they are two conversations that start fresh. What is shared is the
    authored channel; each activity is still its own interaction.

    ``seats`` says who plays each of the environment's agents --
    ``seats={"car": Human(), "traffic-light": Model(controller)}``. It is a **map,
    never a list**: which agent somebody plays is a study's most consequential
    decision, so it is written down rather than inferred from the order the seats
    appear in. A list would let a study that reorders two lines silently swap two
    roles, with nothing in the records to say it had happened. ``spec`` is then the
    environment alone (a ``MultiSeatGame``), because who plays belongs to the
    activity and the environment does not.
    """
    return Step(
        Activity(key=key, kind="game"),
        game=spec,
        rounds=Rounds(count=episodes, between=between),
        chat=chat,
        seats=_seating(key, seats),
    )


def _seating(key: str, seats: Any) -> dict[str, Any] | None:
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
            'Game(key, spec, seats={"car": Human(), "traffic-light": Model(x)})'
        )
    written = cast("Mapping[str, Any]", seats)
    if not written:
        raise ValueError(f"the game {key!r} names a seating with nobody in it")
    return dict(written)


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

    ``assets`` are the pictures the study's environments draw (``Image``, ``Atlas``).
    Each is read, digested, and served by its own digest, and an environment draws
    it by name alone. ``asset_root`` is the directory the paths are relative to; it
    defaults to the working directory the study runs from.

    ``state`` declares what a participant carries from one activity to the next
    (``State``): each namespace is versioned on its own and says who may read it
    and who may write it. A namespace nobody declared cannot be written, and a
    later part of a study receives only the namespaces it declares itself.
    """

    activities: tuple[Activity, ...]
    games: Mapping[str, Any]
    seats: Mapping[str, Mapping[str, Any]]
    chats: Mapping[str, Any]
    conversations: Mapping[str, str]
    comparisons: Mapping[str, Comparison]
    contents: Mapping[str, Placement]
    rounds: Mapping[str, Rounds]
    design: Design | None
    screen: Screen | None
    admit: EligibilityRule | None
    assets: tuple[Asset, ...]
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
            {
                step.activity.key: step.chat
                for step in written
                if step.chat is not None
            },
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
        object.__setattr__(self, "design", design)
        object.__setattr__(self, "screen", screen)
        if admit is not None:
            # Refused while the author is still reading their own code, rather than
            # at the first participant: a rule with no addressable name can not be
            # recorded, and a screen nobody can find again is not evidence.
            rule_name(admit)
        object.__setattr__(self, "admit", admit)
        names = [asset.name for asset in assets]
        if len(set(names)) != len(names):
            raise ValueError("a study names each asset once")
        object.__setattr__(self, "assets", tuple(assets))
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


__all__ = [
    "Activity",
    "ActivityKind",
    "Assign",
    "AuthoringKey",
    "Choice",
    "Comparison",
    "Design",
    "Form",
    "Game",
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
