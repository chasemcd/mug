"""A study names its environment; the platform reads the rest off it.

These tests are what make the author surface honest. A study used to write a
specification per execution -- the agents, the action bindings, the frame rate, the
episode bound, the drawing, and a pinned package list, twice over for a browser run --
and every one of those is a fact about the environment rather than a decision about the
study. So each test below names one thing a study no longer writes.

Two are about refusing rather than reading, and they matter as much: what a game
activity may be given is narrow on purpose, because whether an object is a Gymnasium
environment or a PettingZoo one decides how everything else here is understood.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, cast

import pytest

from mug.game.environments import (
    SINGLE_AGENT,
    Derived,
    EnvironmentRefused,
    bundle_for,
    derive,
)

gymnasium = pytest.importorskip("gymnasium", reason="the game extra is not installed")


# -- what a game activity may be given ----------------------------------------------


def test_a_registered_id_is_refused_and_says_what_to_write() -> None:
    """An id names an environment; it does not build one.

    It is worth its own refusal because it used to be accepted. An author who writes
    the old spelling is told the new one rather than left with a type error.
    """
    with pytest.raises(EnvironmentRefused, match=r"functools\.partial"):
        derive("MountainCar-v0")  # pyright: ignore[reportArgumentType]


def test_something_that_is_not_callable_is_refused() -> None:
    """A built environment cannot travel to a browser, so one is never handed over."""
    with pytest.raises(EnvironmentRefused, match="takes no arguments"):
        derive({"env": "kitchen"})  # pyright: ignore[reportArgumentType]


def test_a_look_alike_with_step_and_reset_is_refused() -> None:
    """There is no duck-typed fallback, and that is deliberate.

    Research code is full of objects that step and reset. Whether one is a Gymnasium
    environment, a PettingZoo parallel one, or a PettingZoo AEC one decides which agents
    there are, how an action is passed, and whether a turn is taken -- so it is read
    from the base class and never guessed.
    """

    class Pretender:
        def reset(self, **_kwargs: Any) -> Any:
            return None, {}

        def step(self, _action: Any) -> Any:
            return None, 0.0, False, False, {}

    with pytest.raises(EnvironmentRefused, match=r"not a gymnasium\.Env"):
        derive(Pretender)


# -- what is read instead of written -------------------------------------------------


def _hill() -> Derived:
    """Read the MountainCar a study would name, with its own frames asked for."""
    return derive(
        functools.partial(gymnasium.make, "MountainCar-v0", render_mode="rgb_array")
    )


def test_the_api_and_the_agents_are_read_from_a_single_agent_environment() -> None:
    """A Gymnasium environment has one agent, and a seating still has to name it."""
    found = _hill()

    assert found.api == "gymnasium"
    assert found.agents == (SINGLE_AGENT,)
    assert not found.is_multi_agent
    assert not found.takes_turns


def test_the_action_space_is_read_so_a_study_does_not_declare_one() -> None:
    """The action set is the environment's, and a refusal can quote it."""
    assert dict(_hill().actions) == {SINGLE_AGENT: "Discrete(3)"}


def test_the_frame_rate_and_episode_bound_are_read() -> None:
    """Both were written by hand on every specification, and both are declared."""
    found = _hill()

    assert found.fps == 30
    assert found.max_steps == 200


def test_the_key_bindings_come_from_the_play_convention() -> None:
    """``gymnasium.utils.play`` already speaks the platform's own binding shape.

    A map from held keys to an action, with the empty tuple as the default: that is
    chords and a default action. An environment that follows it needs no bindings
    written at all, and the convention means held keys.
    """
    found = _hill()

    assert found.keys == {
        "ArrowLeft": 0,
        "ArrowRight": 2,
        "ArrowRight+ArrowLeft": 1,
    }
    assert found.default_action == 1


def test_an_environment_that_declares_no_bindings_asks_the_study_for_them() -> None:
    """What cannot be read is asked for, by name, and the list stays short."""
    from gymnasium.envs.classic_control.cartpole import CartPoleEnv

    found = derive(CartPoleEnv)

    assert found.keys is None
    asked = " ".join(found.asks)
    assert "keys=" in asked
    assert "held_actions=" in asked
    assert "default_action=" in asked


def test_the_package_pin_is_the_installed_version() -> None:
    """The pin cannot drift from what the server verifies against.

    Written by hand in two places, a browser pin and a server package were once allowed
    to differ, and a browser run is verified by the server re-executing it -- so every
    honest run would be refused. Derived from the installed environment, they are one
    fact.
    """
    found = _hill()

    assert found.requires == (f"gymnasium=={gymnasium.__version__}",)


def test_the_drawing_is_answered_by_drawing_one_not_by_reading_metadata() -> None:
    """An environment can declare ``rgb_array`` and still hand over nothing.

    Both Gymnasium classic-control environments are that case: they list it and draw
    with pygame. Reading the declaration would say yes; drawing a frame says no, and
    says why, so the study is asked for a drawing rather than showing an empty canvas.
    """
    found = _hill()

    if found.draws:
        pytest.skip("pygame is installed here, so the environment draws its own frames")
    assert found.draw_blocked_by is not None
    assert "render=" in " ".join(found.asks)


# -- what a browser run needs --------------------------------------------------------


def test_a_partial_travels_because_it_writes_itself_down() -> None:
    """A bound call rebuilds itself elsewhere, so nothing of the study has to travel."""
    found = _hill()

    assert found.runs_in_a_browser
    assert "MountainCar-v0" in found.build
    assert "from gymnasium" in bundle_for(
        functools.partial(gymnasium.make, "MountainCar-v0"), found
    )


def test_a_factory_that_reaches_the_study_cannot_travel() -> None:
    """A factory's source is carried, so it must import nothing of the study.

    The rule is small -- every name it uses is a literal or something it imports inside
    itself -- and it is checked here rather than discovered as a failed download in
    front of a participant. The message names the import that failed it.
    """

    def reaches_the_study() -> Any:
        import gymnasium

        from examples.cogrid import sprites

        assert sprites is not None  # study code, which cannot travel to a browser
        make = cast("Callable[..., Any]", gymnasium.make)  # pyright: ignore[reportUnknownMemberType]
        return make("MountainCar-v0")

    found = derive(reaches_the_study)

    assert not found.runs_in_a_browser
    assert any("examples" in one for one in found.blocks)


def test_a_self_contained_factory_travels_and_names_its_own_packages() -> None:
    """The rule is satisfiable, and satisfying it is what a study author writes."""

    def travels() -> Any:
        import gymnasium

        make = cast("Callable[..., Any]", gymnasium.make)  # pyright: ignore[reportUnknownMemberType]
        return make("MountainCar-v0")

    found = derive(travels)

    assert found.runs_in_a_browser
    assert found.requires == (f"gymnasium=={gymnasium.__version__}",)
    # The factory's own source is what the browser runs, so it is carried whole.
    assert "def travels()" in bundle_for(travels, found)


# -- the multi-agent case, which is what replaces a seat-to-index map ----------------


def test_a_pettingzoo_parallel_environment_names_its_own_agents() -> None:
    """The agents come from ``possible_agents``, so a study keeps no map of its own.

    Every multi-agent study used to carry one -- ``{CHEF_ONE: 0, CHEF_TWO: 1}`` in the
    Overcooked example -- and a mistyped seat then raised on a participant's first
    frame. Read from the environment, an unknown seat is something the platform can
    refuse while the author is still reading their own code.
    """
    pytest.importorskip("pettingzoo", reason="the game extra is not installed")
    pytest.importorskip("cogrid", reason="the example environment is not installed")

    found = derive(_kitchen)

    assert found.api == "pettingzoo-parallel"
    assert found.agents == (0, 1)
    assert found.is_multi_agent
    assert not found.takes_turns
    assert dict(found.actions) == {0: "Discrete(7)", 1: "Discrete(7)"}
    assert "seats=" in " ".join(found.asks)


def test_an_environment_that_draws_itself_needs_no_drawing_from_the_study() -> None:
    """``render_mode="rgb_array"`` is a working picture with no study code at all.

    On a browser run it costs nothing: the pixels are drawn in the same browser that
    made them and never travel. So the cheapest path is also the one that needs the
    least written.
    """
    pytest.importorskip("cogrid", reason="the example environment is not installed")

    found = derive(_kitchen)

    assert found.draws
    assert found.draw_blocked_by is None
    assert "render=" not in " ".join(found.asks)


def _kitchen() -> Any:
    """Build the Overcooked kitchen, as a study author's own factory would.

    Self-contained: every name it uses it imports itself, from a package a participant's
    browser can install. That is the rule a carried factory has to meet.
    """
    import contextlib
    import functools

    from cogrid.cogrid_env import CoGridEnv
    from cogrid.envs import registry
    from cogrid.envs.overcooked.agent import OvercookedAgent
    from cogrid.envs.overcooked.rewards import DeliveryReward

    config = {
        "name": "overcooked",
        "num_agents": 2,
        "action_set": "cardinal_actions",
        "features": ["agent_dir", "overcooked_inventory", "agent_position"],
        # The live object that no written form could rebuild, and that costs nothing
        # here because it is built where it is used.
        "rewards": [DeliveryReward(coefficient=1.0, common_reward=True)],
        "grid": {"layout": "overcooked_cramped_room_v0"},
        "scope": "overcooked",
        "max_steps": 600,
        "pickupable_types": ["onion", "onion_soup", "plate", "tomato", "tomato_soup"],
    }
    with contextlib.suppress(Exception):
        registry.register(
            environment_id="Overcooked-derivation-test",
            env_class=functools.partial(  # pyright: ignore[reportArgumentType]
                CoGridEnv,
                config=config,
                agent_class=OvercookedAgent,  # pyright: ignore[reportArgumentType]
            ),
        )
    return registry.make(  # pyright: ignore[reportUnknownMemberType]
        "Overcooked-derivation-test", render_mode="rgb_array"
    )
