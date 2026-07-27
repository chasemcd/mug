"""What an author writes to manipulate something: treatments, policies, designs.

A study that does not manipulate anything is an observation. This module is the
surface an author uses to say what varies between participants, and it follows one
rule settled for the platform (R-15): **a treatment is declared inline, at its
point of effect**. The manipulation and the thing manipulated are never separated,
so a reader of the study sees the condition where the condition happens::

    difficulty = Treatment("difficulty", {"easy": easy_spec, "hard": hard_spec})

    study = Study(
        Page("intro", difficulty.map({"easy": "Take your time.",
                                      "hard": "You have 30 seconds."})),
        Game("play", difficulty),
    )

The same object placed twice is one factor with two effects, because Python
identity ties them: the participant assigned ``hard`` reads the hard instructions
AND plays the hard game. ``map`` gives the per-site values, and it refuses a
mapping that misses a level or invents one, so a typo is a failure at import time
rather than a condition nobody was ever assigned to.

An author never writes ``random.choice``. The policy is a closed set --
``Assign.random``, ``Assign.balanced``, ``Assign.blocked``, ``Assign.stratified``
-- and the platform samples, balances, and records. Balance holds across the whole
study-version lifetime, not per process, because the counts are durable state
(``mug.visits.assignment``).

Two treatments assign independently unless the study declares the crossing::

    Study(..., design=Design(cross=[difficulty, partner]))

which asks for jointly balanced cells rather than two separately balanced factors.

**Within subjects.** ``within=True`` means the participant meets every level rather
than one, so the activity it is placed on repeats once per level and the order is
itself recorded (randomized, or counterbalanced against the durable counts). That is
where repeated activities and randomized order come from: one declaration, not a
second mechanism.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from mug.visits.types import (
    AssignBalanced,
    AssignBlocked,
    AssignPolicy,
    AssignRandom,
    AssignStratified,
    FieldRef,
)
from mug.visits.types import Treatment as TreatmentSpec


class Scope:
    """Who shares one assignment: the participant, or the whole group."""

    PARTICIPANT: Final[str] = "participant"
    GROUP: Final[str] = "group"


class Unit:
    """What a balanced assignment counts when it keeps the cells even."""

    PARTICIPANTS: Final[str] = "participants"
    GROUPS: Final[str] = "groups"


class Order:
    """How a within-subject treatment orders the levels it delivers."""

    RANDOMIZED: Final[str] = "randomized"
    COUNTERBALANCED: Final[str] = "counterbalanced"


class Assign:
    """The assignment policies, as a closed set (D06-2).

    An author picks one; none of them is a callback and none of them is a string,
    so a study can not hand-roll its own allocator and a typo is not a policy.
    """

    @staticmethod
    def random() -> AssignPolicy:
        """Draw a level at random for each unit, with no balancing constraint."""
        return AssignRandom(policy="random")

    @staticmethod
    def balanced(unit: str = Unit.PARTICIPANTS) -> AssignPolicy:
        """Keep the cells even across the study version's whole lifetime.

        ``unit`` says what is counted. A participant-scoped treatment counts
        participants, which is the default; a group-scoped one counts groups
        unless the author asks for participants, because groups of unequal size
        make the two different questions.
        """
        return AssignBalanced(policy="balanced", unit=unit)  # pyright: ignore[reportArgumentType]

    @staticmethod
    def blocked() -> AssignPolicy:
        """Fill one shuffled block of levels before starting the next.

        Balance is never worse than one block, so a study stopped early still has
        even cells. The shuffle inside each block is the difference from
        ``balanced``, which fills the emptiest cell.
        """
        return AssignBlocked(policy="blocked")

    @staticmethod
    def stratified(by: FieldRef) -> AssignPolicy:
        """Balance the levels separately inside each answer to one form field.

        Use it when a participant property must not end up unevenly spread -- a
        pre-test score, handedness, which language they read in. The assignment
        waits until that answer exists, and is then recorded once and never
        revised.
        """
        return AssignStratified(policy="stratified", by=by)


# The author's objects compare and hash by identity (``eq=False``), because that
# is what ties one factor's several effects together: the same ``Treatment``
# object placed at the game AND at the instructions is one manipulation, and two
# separately written treatments with equal fields are two factors.
@dataclass(frozen=True, eq=False)
class Placement:
    """One treatment's values at one site, from ``treatment.map({...})``."""

    treatment: Treatment
    values: Mapping[str, Any]

    def value_for(self, level: str) -> Any:
        """Return what this site delivers for one assigned level."""
        return self.values[level]


@dataclass(frozen=True, eq=False)
class Treatment:
    """One manipulated factor, written where it takes effect.

    ``levels`` is either a mapping from level label to what that level delivers at
    this site, or a plain sequence of labels when the label IS the value (an env
    argument named ``"easy"``, say). Every other site the same object is placed at
    supplies its own values with ``map``.
    """

    key: str
    levels: Mapping[str, Any] | Sequence[str]
    assign: AssignPolicy = field(default_factory=Assign.balanced)
    scope: str = Scope.PARTICIPANT
    within: bool = False
    order: str | None = None

    def __post_init__(self) -> None:
        if len(self.level_keys) < 2:
            raise ValueError(
                f"the treatment {self.key!r} needs two levels at least; "
                "one level is not a manipulation"
            )
        if self.within and self.order is None:
            # A within-subject treatment delivers every level, so an order is
            # always chosen. Saying nothing means "any order", not "the order I
            # wrote them in", because the written order would confound the factor
            # with the position.
            object.__setattr__(self, "order", Order.RANDOMIZED)

    @property
    def level_keys(self) -> tuple[str, ...]:
        """Return this factor's level labels, in the order the author wrote."""
        return tuple(self.levels)

    def value_for(self, level: str) -> Any:
        """Return what this site delivers for one assigned level.

        With levels written as a plain sequence the label is the value, which is
        what an author means by ``levels=["easy", "hard"]``.
        """
        if isinstance(self.levels, Mapping):
            return self.levels[level]
        return level

    def map(self, values: Mapping[str, Any]) -> Placement:
        """Place this same factor at another site, with that site's values."""
        missing = [key for key in self.level_keys if key not in values]
        invented = [key for key in values if key not in self.level_keys]
        if missing or invented:
            raise ValueError(
                f"the map of the treatment {self.key!r} must name each level once: "
                f"missing {sorted(missing)}, unknown {sorted(invented)}"
            )
        return Placement(treatment=self, values=dict(values))

    def spec(self) -> TreatmentSpec:
        """Return the frozen API-04 declaration of this factor."""
        return TreatmentSpec(
            key=self.key,
            levels=list(self.level_keys),
            assign=self.assign,
            scope=self.scope,  # pyright: ignore[reportArgumentType]
            within=self.within or None,
            order=self.order,  # pyright: ignore[reportArgumentType]
        )


@dataclass(frozen=True, eq=False)
class Design:
    """The crossing a study asks to be balanced jointly rather than separately.

    Without it every treatment is balanced on its own, which keeps each factor even
    and says nothing about their combinations. ``Design(cross=[a, b])`` balances the
    cells of the whole crossing, which is what a factorial study means by balanced.
    """

    cross: Sequence[Treatment]
    assign: AssignPolicy = field(default_factory=Assign.balanced)

    def __post_init__(self) -> None:
        if len(self.cross) < 2:
            raise ValueError("a design crosses two treatments at least")


def placed(value: Any) -> Placement | None:
    """Return the placement one authored value is, or None when it is plain.

    A site holds a ``Treatment`` (its own levels are the values), a ``Placement``
    (``treatment.map({...})``), or an ordinary value that does not vary.
    """
    if isinstance(value, Placement):
        return value
    if isinstance(value, Treatment):
        return Placement(
            treatment=value,
            values={level: value.value_for(level) for level in value.level_keys},
        )
    return None


__all__ = [
    "Assign",
    "Design",
    "Order",
    "Placement",
    "Scope",
    "Treatment",
    "Unit",
    "placed",
]
