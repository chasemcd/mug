"""What a study declares about connection quality, and what the ladder does.

`mug/interactions/types.py` declared bounds, a warn-then-exclude ladder, and a
researcher callback with a fail-closed rule. Nothing compared a measurement to any
of it, so a study could state a latency bound that was never enforced.

These tests are the pure half: the declaration a study writes, the comparison the
server makes, and the rung the count reaches. Every one of them states an answer
rather than asserting that something happened, because none of this touches a
clock, a store, or a socket.
"""

from __future__ import annotations

import pytest

from mug.interactions.monitoring import (
    Screen,
    action_at,
    callback_action,
    handler_name,
    over_bounds,
)


def note_violation(state: object) -> None:
    """A module-level researcher hook, which is what a record can address."""


def raise_on_violation(state: object) -> None:
    """A researcher hook that fails, which is what the fail rule is about."""
    raise RuntimeError("the study's own hook is broken")


# -- what a study declares -------------------------------------------------------


def test_a_screen_becomes_the_policy_it_means() -> None:
    """The author writes four numbers; the record carries the frozen policy."""
    policy = Screen(max_rtt_ms=250, max_hidden_ms=5000, warn_after=2, exclude_after=5)
    built = policy.policy()

    assert built.enforcement == "server-authoritative"
    assert built.max_rtt.microseconds == 250_000
    assert built.max_hidden.microseconds == 5_000_000
    assert [(one.at_violations, one.action) for one in built.ladder] == [
        (2, "warn"),
        (5, "exclude"),
    ]
    assert built.callback is None


def test_a_screen_that_excludes_before_it_warns_is_refused() -> None:
    """A ladder that falls is not a ladder, and the frozen record refuses it too."""
    with pytest.raises(ValueError, match="more violations than it warns"):
        Screen(warn_after=4, exclude_after=2)


def test_a_screen_with_a_zero_bound_is_refused() -> None:
    """Every connection is over a bound of zero, so it screens nobody in."""
    with pytest.raises(ValueError, match="positive number of ms"):
        Screen(max_rtt_ms=0)


def test_a_callback_that_can_not_be_addressed_is_refused_at_declaration() -> None:
    """A record names its callback, so a hook with no name can not be recorded."""
    def local_hook(state: object) -> None:
        """A hook defined inside a function, which no record can address."""

    with pytest.raises(ValueError, match="module-level function"):
        Screen(on_violation=local_hook)


def test_a_module_level_callback_reaches_the_policy_by_name() -> None:
    """The record addresses the hook, so an analysis can find what was run."""
    built = Screen(on_violation=note_violation, on_error="fail_open").policy()

    assert built.callback is not None
    assert built.callback.handler == handler_name(note_violation)
    assert built.callback.on_error == "fail_open"


# -- what the server decides -----------------------------------------------------


def test_a_sample_over_one_bound_names_that_metric_alone() -> None:
    """A slow connection is not a hidden page, and the record says which it was."""
    policy = Screen(max_rtt_ms=250, max_hidden_ms=5000).policy()

    assert over_bounds(policy, {"rtt": 300_000, "hidden": 1_000_000}) == ("rtt",)
    assert over_bounds(policy, {"rtt": 100_000, "hidden": 9_000_000}) == ("hidden",)
    assert over_bounds(policy, {"rtt": 300_000, "hidden": 9_000_000}) == (
        "rtt",
        "hidden",
    )


def test_a_sample_exactly_at_the_bound_is_within_it() -> None:
    """A bound is what is allowed, not the first thing refused."""
    policy = Screen(max_rtt_ms=250).policy()

    assert over_bounds(policy, {"rtt": 250_000}) == ()
    assert over_bounds(policy, {"rtt": 250_001}) == ("rtt",)


def test_a_metric_the_policy_does_not_name_is_not_judged() -> None:
    """The server judges what it declared; anything else is not a violation."""
    policy = Screen().policy()

    assert over_bounds(policy, {"framerate": 9_999_999}) == ()


def test_the_ladder_warns_then_excludes_and_never_steps_back() -> None:
    """The highest rung reached is the one that applies."""
    policy = Screen(warn_after=2, exclude_after=4).policy()

    assert action_at(policy, 0) is None
    assert action_at(policy, 1) is None
    assert action_at(policy, 2) == "warn"
    assert action_at(policy, 3) == "warn"
    assert action_at(policy, 4) == "exclude"
    assert action_at(policy, 40) == "exclude"


# -- what happens when the study's own hook fails --------------------------------


def test_a_fail_closed_callback_that_raises_excludes() -> None:
    """A screen nobody can evaluate must not quietly keep everybody."""
    policy = Screen(on_violation=raise_on_violation).policy()

    assert callback_action(policy, lambda: raise_on_violation(None)) == "exclude"


def test_a_fail_open_callback_that_raises_keeps_the_participant() -> None:
    """Explicitly asked for, and therefore explicitly the study's decision."""
    policy = Screen(on_violation=raise_on_violation, on_error="fail_open").policy()

    assert callback_action(policy, lambda: raise_on_violation(None)) is None


def test_a_callback_that_runs_decides_nothing() -> None:
    """The hook observes. What it decides is what happens when it can not run."""
    policy = Screen(on_violation=note_violation).policy()

    assert callback_action(policy, lambda: note_violation(None)) is None


def test_a_policy_with_no_callback_runs_nothing() -> None:
    """A study that declared no hook must not have one invented for it."""
    calls: list[int] = []
    policy = Screen().policy()

    assert callback_action(policy, lambda: calls.append(1)) is None
    assert calls == []
