"""A study is what the author writes, not what the platform assumes.

Before this, the activities a participant walked through were a constant in the
flow service: consent, one survey, the game, a debrief. Every study got that
shape whatever it was studying. These tests cover the surface that replaced it --
the author names the activities and their order, and the platform runs them.

The builders are checked against what they actually produce (the frozen API-17
records), because that is what the contract validates and the ledger records.
"""

from __future__ import annotations

from typing import Any

import pytest

from mug.content import (
    Choice,
    Form,
    Game,
    Likert,
    Page,
    Study,
    Text,
    demo_study,
)
from mug.content.service import FlowActivity, FlowState, present
from mug.kernel import VersionStamp, etag

_VISIT = "visit_019b6000-0000-7000-8000-0000000000a1"
_PLAN = "visitplan_019b6000-0000-7000-8000-0000000000a2"


def _flow(study: Study, pointer: int = 0, status: str = "in-progress") -> FlowState:
    """Build the runtime flow one study is at, for the presentation tests."""
    body: dict[str, Any] = {
        "visitplan_id": _PLAN,
        "visit_id": _VISIT,
        "activities": [
            FlowActivity(
                key=activity.key,
                activity_key=activity.key,
                kind=activity.kind,
            ).model_dump(mode="json")
            for activity in study.activities
        ],
        "pointer": pointer,
        "status": status,
        "captured_streams": [],
    }
    return FlowState(**body, version=VersionStamp(revision=1, etag=etag(body)))


# -- what an author writes ------------------------------------------------------


def test_a_study_keeps_the_activities_in_the_order_they_are_written() -> None:
    """The order is the author's, and the platform does not rearrange it."""
    study = Study(
        Form("consent", Choice("agree", "Do you consent?", ["yes", "no"])),
        Page("instructions", "# What you will do"),
        Form("pre", Likert("mood", "How do you feel?", scale=5)),
        Game("play"),
        Form("post", Text("comments", "Anything else?")),
        Page("debrief", "# Thank you"),
    )

    assert [activity.key for activity in study.activities] == [
        "consent",
        "instructions",
        "pre",
        "play",
        "post",
        "debrief",
    ]
    assert [activity.kind for activity in study.activities] == [
        "form",
        "content",
        "form",
        "game",
        "form",
        "content",
    ]
    assert study.game_keys == ("play",)


def test_a_study_needs_no_game_at_all() -> None:
    """A questionnaire is a study. The game is one activity, not the point."""
    study = Study(
        Form("consent", Choice("agree", "Do you consent?", ["yes", "no"])),
        Form("survey", Likert("mood", "How do you feel?", scale=7)),
    )

    assert study.game_keys == ()
    assert len(study.activities) == 2


def test_a_study_may_play_more_than_one_game() -> None:
    """A practice round and then the real one is two game activities, in order."""
    study = Study(
        Page("instructions", "# Read this"),
        Game("practice"),
        Form("check", Choice("ready", "Ready for the real round?", ["yes", "no"])),
        Game("play"),
    )

    assert study.game_keys == ("practice", "play")
    assert [activity.key for activity in study.activities] == [
        "instructions",
        "practice",
        "check",
        "play",
    ]


def test_each_game_activity_may_name_its_own_settings() -> None:
    """A practice round is shorter than the real one, so it runs its own spec."""
    practice, real = object(), object()
    study = Study(Game("practice", practice), Game("play", real))

    assert study.games == {"practice": practice, "play": real}


def test_a_game_activity_that_names_nothing_runs_what_is_mounted() -> None:
    """The common case: one game, configured on the application, played twice."""
    study = Study(Game("practice"), Game("play"))

    assert study.games == {}
    assert study.game_keys == ("practice", "play")


def test_the_builders_produce_the_records_the_contract_validates() -> None:
    """What the author writes is what the ledger records, not a loose dictionary."""
    study = Study(
        Form(
            "screening",
            Choice("handedness", "Which hand do you write with?", ["left", "right"]),
            Likert("experience", "How experienced are you?", scale=7),
            Text("notes", "Anything to add?"),
        ),
        Page("brief", "# Read this"),
    )

    form = study.activity("screening").form
    assert form is not None
    assert form.form_key == "screening"
    assert [field.field_key for field in form.fields] == [
        "handedness",
        "experience",
        "notes",
    ]
    handedness, experience, notes = form.fields
    assert handedness.options == ["left", "right"]
    assert experience.scale == 7
    # Text is optional unless the author says otherwise: a required free-text box
    # that a participant cannot answer is a dead end.
    assert notes.required is False
    assert handedness.required is True

    content = study.activity("brief").content
    assert content is not None
    assert content.body.text == "# Read this"
    assert content.body.executable is False


def test_a_required_text_field_is_the_author_saying_so() -> None:
    """The default is optional; the author may still insist."""
    form = Form("q", Text("why", "Why did you do that?", required=True))
    assert form.activity.form is not None
    assert form.activity.form.fields[0].required is True


# -- what a study refuses -------------------------------------------------------


def test_a_study_with_no_activities_is_refused() -> None:
    """An empty study has nothing to show a participant."""
    with pytest.raises(ValueError, match="at least one activity"):
        Study()


def test_a_study_that_names_an_activity_twice_is_refused() -> None:
    """Two activities with one key would share a record. Say so at build time."""
    with pytest.raises(ValueError, match="names each activity once"):
        Study(Page("brief", "# One"), Page("brief", "# Two"))


def test_a_form_that_asks_nothing_is_refused() -> None:
    """A form with no fields advances on nothing and records nothing."""
    with pytest.raises(ValueError, match="asks nothing"):
        Form("empty")


def test_two_game_activities_that_share_one_key_are_refused() -> None:
    """Two games are fine; two games under one key are not.

    The key is how a run is presented, identified, and recorded, so two activities
    behind one key would record one episode over the other. This is the refusal
    that used to cover every second game activity.
    """
    with pytest.raises(ValueError, match="names each activity once"):
        Study(Game("play"), Game("play"))


# -- how the flow presents it ---------------------------------------------------


def test_the_flow_presents_the_author_activity_at_the_pointer() -> None:
    """Each step renders the author's own content, in their own order."""
    study = Study(
        Form("consent", Choice("agree", "Do you consent?", ["yes", "no"])),
        Page("instructions", "# What you will do"),
        Game("play"),
    )

    first = present(_flow(study, pointer=0), study)
    assert first["kind"] == "form"
    assert first["form"]["form_key"] == "consent"

    second = present(_flow(study, pointer=1), study)
    assert second["kind"] == "content"
    assert second["content"]["body"]["text"] == "# What you will do"

    third = present(_flow(study, pointer=2), study)
    assert third == {
        "kind": "game",
        "activity_key": "play",
        "occurrence_key": "play",
    }


def test_two_studies_present_different_activities_from_one_platform() -> None:
    """The study is a value, so two of them run side by side without conflict."""
    one = Study(Form("a", Choice("pick", "Pick one", ["x", "y"])))
    two = Study(Form("b", Likert("rate", "Rate it", scale=3)))

    assert present(_flow(one), one)["form"]["form_key"] == "a"
    assert present(_flow(two), two)["form"]["form_key"] == "b"


def test_the_demo_study_is_one_study_among_others() -> None:
    """It still exists, and it is no longer the only shape a study may have."""
    demo = demo_study()

    assert [activity.key for activity in demo.activities] == [
        "consent",
        "survey",
        "play",
        "debrief",
    ]
    assert demo.game_keys == ("play",)
