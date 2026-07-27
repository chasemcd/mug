"""What an author may write, and what the compiler refuses to publish.

A study whose design is wrong still runs. It collects data for weeks and the
mistake surfaces in the analysis, which is the worst possible place for it. These
tests cover the two lines of defence in front of that: the author's objects refuse
at import time what they can see is wrong, and the compiler refuses to publish the
rest.

They also hold the study version to the design: two studies that differ only in
what they manipulate are two versions, because they are two different studies.
"""

from __future__ import annotations

import pytest

from mug.content import (
    Assign,
    Choice,
    Design,
    Form,
    Game,
    Order,
    Page,
    Study,
    Treatment,
)
from mug.content.plan import declared_treatments, spec_for, treatments_at
from mug.content.publish import diagnose, study_digest
from mug.visits.design import Scope

_EASY = "Take your time."
_HARD = "You have thirty seconds."


def _codes(study: Study) -> set[str]:
    return {one.code for one in diagnose(study)}


# -- what the author's objects refuse --------------------------------------------


def test_a_map_that_misses_a_level_is_refused_where_it_is_written() -> None:
    """A level nobody mapped is a condition nobody would ever be shown."""
    difficulty = Treatment("difficulty", ["easy", "hard"])
    with pytest.raises(ValueError, match="must name each level once"):
        difficulty.map({"easy": _EASY})


def test_a_map_that_invents_a_level_is_refused_too() -> None:
    """A typo'd level is silent otherwise: it would simply never be chosen."""
    difficulty = Treatment("difficulty", ["easy", "hard"])
    with pytest.raises(ValueError, match="must name each level once"):
        difficulty.map({"easy": _EASY, "hard": _HARD, "medium": "?"})


def test_a_treatment_with_one_level_is_not_a_manipulation() -> None:
    """One level varies nothing, so it is a constant written the long way."""
    with pytest.raises(ValueError, match="two levels at least"):
        Treatment("difficulty", ["easy"])


def test_a_design_that_crosses_one_factor_is_refused() -> None:
    """Crossing is a relationship between factors, so it needs two."""
    difficulty = Treatment("difficulty", ["easy", "hard"])
    with pytest.raises(ValueError, match="two treatments at least"):
        Design(cross=[difficulty])


def test_a_within_subject_factor_always_has_an_order() -> None:
    """It delivers every level, so the sequence is a decision either way."""
    rounds = Treatment("rounds", ["a", "b"], within=True)
    assert rounds.order == Order.RANDOMIZED
    named = Treatment("rounds", ["a", "b"], within=True, order=Order.COUNTERBALANCED)
    assert named.order == Order.COUNTERBALANCED


# -- one object, several effects --------------------------------------------------


def test_the_same_treatment_placed_twice_is_one_factor() -> None:
    """Python identity ties the effects: one assignment drives both sites."""
    difficulty = Treatment("difficulty", {"easy": "short", "hard": "long"})
    study = Study(
        Page("intro", difficulty.map({"easy": _EASY, "hard": _HARD})),
        Game("play", difficulty),
    )

    assert len(declared_treatments(study)) == 1
    assert treatments_at(study, "intro") == treatments_at(study, "play")
    assert spec_for(study, "play", {"difficulty": "hard"}) == "long"


def test_two_treatments_that_read_alike_are_still_two_factors() -> None:
    """Equal fields are not the same manipulation; the author placed two."""
    first = Treatment("a", ["x", "y"])
    second = Treatment("b", ["x", "y"])
    study = Study(
        Page("one", first.map({"x": "1", "y": "2"})),
        Page("two", second.map({"x": "3", "y": "4"})),
    )

    assert [one.key for one in declared_treatments(study)] == ["a", "b"]


def test_a_site_with_no_treatment_delivers_what_the_author_wrote() -> None:
    """A study that manipulates nothing reads exactly as it did before."""
    study = Study(Page("intro", _EASY), Game("play", "the mounted spec"))
    assert declared_treatments(study) == ()
    assert spec_for(study, "play", {}) == "the mounted spec"


# -- what the compiler refuses ----------------------------------------------------


def test_a_factor_stratified_on_an_answer_that_comes_later_is_refused() -> None:
    """It could never be assigned in time, so it would silently never assign."""
    later = Form("post", Choice("handedness", "Which hand?", ["left", "right"]))
    layout = Treatment(
        "layout",
        ["wide", "narrow"],
        assign=Assign.stratified(by=later.field("handedness")),
    )
    study = Study(Page("intro", layout.map({"wide": "w", "narrow": "n"})), later)

    assert "study.treatment.stratifies_on_a_later_answer" in _codes(study)


def test_a_factor_stratified_on_a_field_nobody_asks_is_refused() -> None:
    """A pointer to a question the study does not ask resolves to nothing."""
    pre = Form("pre", Choice("handedness", "Which hand?", ["left", "right"]))
    layout = Treatment(
        "layout",
        ["wide", "narrow"],
        assign=Assign.stratified(by=pre.field("eyesight")),
    )
    study = Study(pre, Page("intro", layout.map({"wide": "w", "narrow": "n"})))

    assert "study.treatment.stratifies_on_an_unknown_field" in _codes(study)


def test_a_factor_stratified_on_an_activity_nobody_runs_is_refused() -> None:
    """The activity key has to name a step of this study."""
    absent = Form("elsewhere", Choice("handedness", "Which hand?", ["left", "right"]))
    layout = Treatment(
        "layout",
        ["wide", "narrow"],
        assign=Assign.stratified(by=absent.field("handedness")),
    )
    study = Study(Page("intro", layout.map({"wide": "w", "narrow": "n"})))

    assert "study.treatment.stratifies_on_an_unknown_activity" in _codes(study)


def test_a_design_that_crosses_a_factor_placed_nowhere_is_refused() -> None:
    """A factor with no effect site manipulates nothing to balance."""
    placed = Treatment("placed", ["x", "y"])
    orphan = Treatment("orphan", ["x", "y"])
    study = Study(
        Page("intro", placed.map({"x": "1", "y": "2"})),
        design=Design(cross=[placed, orphan]),
    )

    assert "study.design.unplaced_factor" in _codes(study)


def test_a_group_scoped_factor_is_refused_while_no_group_exists() -> None:
    """A condition a group shares needs a group, and this platform forms none."""
    shared = Treatment("layout", ["wide", "narrow"], scope=Scope.GROUP)
    study = Study(Page("intro", shared.map({"wide": "w", "narrow": "n"})))

    assert "study.treatment.group_scope_without_a_group" in _codes(study)


def test_two_within_subject_factors_on_two_activities_raise_nothing() -> None:
    """Each activity is repeated by its own factor, which is a fine study."""
    first = Treatment("first", ["a", "b"], within=True)
    second = Treatment("second", ["c", "d"], within=True)
    study = Study(
        Game("play", first),
        Page("intro", second.map({"c": "3", "d": "4"})),
    )

    assert _codes(study) == set()


def test_a_well_formed_design_raises_nothing() -> None:
    """The refusals above are about mistakes, not about manipulating at all."""
    pre = Form("pre", Choice("handedness", "Which hand?", ["left", "right"]))
    layout = Treatment(
        "layout",
        ["wide", "narrow"],
        assign=Assign.stratified(by=pre.field("handedness")),
    )
    difficulty = Treatment("difficulty", ["easy", "hard"], assign=Assign.balanced())
    study = Study(
        pre,
        Page("intro", difficulty.map({"easy": _EASY, "hard": _HARD})),
        Page("layout", layout.map({"wide": "w", "narrow": "n"})),
    )

    assert _codes(study) == set()


# -- the design is part of what the study is --------------------------------------


def test_two_studies_that_differ_only_in_a_level_are_two_versions() -> None:
    """The version has to change, or one identifier covers two studies."""
    plain = Study(Page("intro", _EASY))
    manipulated = Study(
        Page(
            "intro",
            Treatment("difficulty", ["easy", "hard"]).map(
                {"easy": _EASY, "hard": _HARD}
            ),
        )
    )
    other = Study(
        Page(
            "intro",
            Treatment("difficulty", ["easy", "hard"]).map(
                {"easy": _EASY, "hard": "You have ten seconds."}
            ),
        )
    )

    assert study_digest(plain).hex != study_digest(manipulated).hex
    assert study_digest(manipulated).hex != study_digest(other).hex


def test_adding_a_crossing_changes_the_version_too() -> None:
    """Balanced jointly and balanced separately are different studies."""

    def _build(crossed: bool) -> Study:
        first = Treatment("a", ["x", "y"])
        second = Treatment("b", ["x", "y"])
        return Study(
            Page("one", first.map({"x": "1", "y": "2"})),
            Page("two", second.map({"x": "3", "y": "4"})),
            design=Design(cross=[first, second]) if crossed else None,
        )

    assert study_digest(_build(False)).hex != study_digest(_build(True)).hex
    # And one study is always one version, however many times it is built.
    assert study_digest(_build(True)).hex == study_digest(_build(True)).hex
