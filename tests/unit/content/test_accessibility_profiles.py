"""What each shipped screen delivers, and what a study may therefore claim.

`AccessibilityProfile` and `PresentationComponent` were frozen records with a
validator and no producer, while `quality-attributes.md` required keyboard-only and
screen-reader use across navigation, forms, preference controls, and chat, and
`ClientManifest.accessibility_profile` required a profile key. So the requirement
had no place to be true or false.

These tests check the declaration is honest: an `aa` claim meets the floor the
frozen record enforces, the game canvas does not claim what a canvas cannot do, and
a study reports the least capable screen it uses rather than the best one.
"""

from __future__ import annotations

import pytest

from mug.content.components import (
    PROFILE_ORDER,
    accessibility_profiles,
    component_for,
    presentation_components,
    profile_floor,
)


def test_every_shipped_screen_declares_a_profile() -> None:
    """A screen with no declared profile is a screen nobody promised anything for."""
    declared = {one.component_key for one in presentation_components()}
    assert declared == {
        "form",
        "content",
        "comparison",
        "chat",
        "game",
        "game-chat",
    }
    keys = {one.profile_key for one in accessibility_profiles()}
    for component in presentation_components():
        assert component.accessibility_profile in keys


def test_the_html_screens_claim_keyboard_and_screen_reader_use() -> None:
    """The `aa` claim is a commitment the frozen record refuses to let us fake."""
    profiles = {one.profile_key: one for one in accessibility_profiles()}
    aa = profiles["wcag-aa"]
    assert aa.wcag_level == "aa"
    assert aa.keyboard_navigable is True
    assert aa.screen_reader is True
    for kind in ("form", "content", "comparison", "chat"):
        assert component_for(kind).accessibility_profile == "wcag-aa"


def test_a_game_with_a_conversation_delivers_the_floor_of_the_two() -> None:
    """One screen of two panes claims the worse of them, not the better.

    The conversation beside the canvas is screen-reader usable and the canvas is
    not. A participant who cannot use the canvas cannot finish the activity, so
    claiming `aa` for the pair would be claiming something nobody can do.
    """
    assert component_for("chat").accessibility_profile == "wcag-aa"
    assert component_for("game-chat").accessibility_profile == "wcag-a"
    assert profile_floor(["form", "game-chat"]) == "wcag-a"


def test_the_game_canvas_does_not_claim_what_a_canvas_cannot_do() -> None:
    """A screen reader has nothing to read in a canvas, so the game says so."""
    profiles = {one.profile_key: one for one in accessibility_profiles()}
    assert component_for("game").accessibility_profile == "wcag-a"
    game = profiles["wcag-a"]
    assert game.keyboard_navigable is True
    assert game.screen_reader is False


def test_a_study_reports_the_least_capable_screen_it_uses() -> None:
    """Reporting the best would make the manifest marketing rather than a record."""
    assert profile_floor(["form", "content", "comparison"]) == "wcag-aa"
    assert profile_floor(["form", "game", "comparison"]) == "wcag-a"
    assert profile_floor(["game"]) == "wcag-a"


def test_an_aa_profile_that_misses_the_access_floor_is_refused() -> None:
    """The frozen validator is what makes the claim worth reading."""
    from mug.content.types import AccessibilityProfile

    with pytest.raises(ValueError, match="access floor"):
        AccessibilityProfile(
            profile_key="pretend-aa",
            wcag_level="aa",
            keyboard_navigable=True,
            screen_reader=False,
        )


def test_the_profile_order_runs_from_least_to_most_capable() -> None:
    """``profile_floor`` is only meaningful if the order is."""
    assert PROFILE_ORDER == ("wcag-a", "wcag-aa", "wcag-aaa")
    assert min(("wcag-aa", "wcag-a"), key=PROFILE_ORDER.index) == "wcag-a"
