"""A game activity names its environment, and the study reads the rest off it.

``mug.game.environments`` is tested on its own (``tests/unit/game``); what is tested
here is the author's surface over it -- what ``Game`` accepts, what it refuses, and
what a ``Study`` then knows that it could not know before.

Every refusal below is silent today. The study builds, the participant arrives, and
the fault reads as the platform failing: a mistyped seat is a ``KeyError`` on the
first frame, a person with no bindings presses keys that do nothing, and a game with
no picture is a canvas that stays empty. So each one has a test that provokes it, and
each message says what to write.
"""

from __future__ import annotations

import functools
from typing import Any, ClassVar

import pytest

from mug.content import Game, Page, Study
from mug.content.assets import Atlas, Image
from mug.content.players import Bot, Human, Model
from mug.game.environments import EnvironmentRefused

gymnasium = pytest.importorskip("gymnasium", reason="the game extra is not installed")


def _hill() -> Any:
    """Return the environment a study names: a bound call that rebuilds itself."""
    return functools.partial(gymnasium.make, "MountainCar-v0", render_mode="rgb_array")


def _drawn(_surface: Any, _frame: Any) -> None:
    """Stand in for a study's own drawing. What it paints does not matter here."""


def _where_the_car_is(env: Any) -> dict[str, float]:
    """Return a scene a drawing could read: something only the environment holds."""
    return {"where": float(env.unwrapped.state[0])}


def _nothing(env: Any) -> dict[str, Any]:
    """Return a scene nothing reads. What it holds does not matter here."""
    del env
    return {}


class _AlwaysLeft:
    """A local policy that plays a seat. What it decides does not matter here."""

    def decide(self, observation: object) -> int:
        del observation
        return 0


# -- what the study no longer writes ------------------------------------------------


def test_the_activity_carries_what_was_read_off_its_environment() -> None:
    """One ``Game`` line replaces a whole written specification.

    The agents, the action set, the frame rate, and the episode bound were four
    hand-written fields on a specification per execution, and every one of them is a
    fact about the environment rather than a decision about the study.
    """
    study = Study(
        Page("intro", "# Ready"),
        Game("drive", _hill(), seats={"agent": Human()}, render=_drawn),
    )

    plays = study.game_activities["drive"]
    assert plays.found.api == "gymnasium"
    assert plays.found.agents == ("agent",)
    assert plays.found.fps == 30
    assert plays.found.max_steps == 200


def test_an_environment_that_declares_its_bindings_needs_none_written() -> None:
    """``gymnasium.utils.play`` already speaks the platform's own binding shape.

    The convention is a map from the keys **held** on a frame to that frame's action,
    with the empty tuple as the default -- so taking the environment's bindings means
    taking held keys and the environment's own default with them.
    """
    plays = Study(Game("drive", _hill(), render=_drawn)).game_activities["drive"]

    assert plays.bindings == {
        "ArrowLeft": 0,
        "ArrowRight": 2,
        "ArrowRight+ArrowLeft": 1,
    }
    assert plays.held
    assert plays.idle_action == 1


def test_a_study_that_writes_its_own_keys_says_how_they_act() -> None:
    """A study's own bindings win, and they answer both questions themselves."""
    plays = Study(
        Game(
            "drive",
            _hill(),
            keys={"w": 2},
            held_actions=False,
            default_action=0,
            render=_drawn,
        )
    ).game_activities["drive"]

    assert plays.bindings == {"w": 2}
    assert not plays.held
    assert plays.idle_action == 0


def test_the_package_pin_is_merged_across_every_environment() -> None:
    """A study with two environments cannot pin one and forget the other.

    It matters more than it reads. A browser run is verified by the server
    re-executing it, so the browser pin and the server package must be one version.
    Written by hand in two places they were once allowed to drift, and the consequence
    is that every honest run is refused.
    """
    study = Study(
        Game("one", _hill(), render=_drawn),
        Game("two", _hill(), render=_drawn),
    )

    assert study.requires == (f"gymnasium=={gymnasium.__version__}",)


def test_a_study_that_names_no_environment_reads_as_it_always_did() -> None:
    """The older form still runs, so a study is ported when its author ports it."""
    mounted = object()
    study = Study(Page("intro", "# Ready"), Game("play", mounted))

    assert study.game_activities == {}
    assert study.games == {"play": mounted}
    assert study.requires == ()


# -- the pictures each activity draws -----------------------------------------------


def test_a_picture_is_needed_before_the_activity_that_draws_it() -> None:
    """Declaring a sheet on the activity is what stops one download paying for two.

    Every picture a study ships is marked "needed before the activity". With all of
    them at study level that means every picture must load before *any* activity, so a
    study with a kitchen and a court makes somebody download both sets before the
    first round.
    """
    kitchen = Image("kitchen", "assets/kitchen.png")
    court = Image("court", "assets/court.png")
    logo = Image("logo", "assets/logo.png")
    study = Study(
        Game("cook", _hill(), assets=[kitchen], render=_drawn),
        Game("rally", _hill(), assets=[court], render=_drawn),
        assets=[logo],
    )

    assert [one.name for one in study.assets_for("cook")] == ["logo", "kitchen"]
    assert [one.name for one in study.assets_for("rally")] == ["logo", "court"]
    # Everything the study serves is still staged and served, whoever declared it.
    assert [one.name for one in study.assets] == ["logo", "kitchen", "court"]


def test_two_activities_may_draw_the_same_sheet() -> None:
    """A practice round and a real one draw one kitchen, and it is read once."""
    kitchen = Image("kitchen", "assets/kitchen.png")
    study = Study(
        Game("practice", _hill(), assets=[kitchen], render=_drawn),
        Game("play", _hill(), assets=[kitchen], render=_drawn),
    )

    assert [one.name for one in study.assets] == ["kitchen"]


def test_one_name_for_two_files_names_both_activities() -> None:
    """An author whose two sheets are both called terrain is told which two."""
    with pytest.raises(ValueError, match=r"'cook'.*'rally'|'rally'.*'cook'"):
        Study(
            Game("cook", _hill(), assets=[Image("t", "a.png")], render=_drawn),
            Game("rally", _hill(), assets=[Image("t", "b.png")], render=_drawn),
        )


def test_an_activity_sheet_is_read_against_the_study_root(tmp_path: Any) -> None:
    """A sheet declared on an activity is read where the study's pictures are read.

    The frames are what a drawing addresses and what the study version is computed
    from, so a sheet still unread at that point would give one version for two
    packings -- which is the whole reason a frame is named rather than numbered.
    """
    (tmp_path / "sheet.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "sheet.json").write_text(
        '{"frames": {"counter.png": {"frame": {"x": 1, "y": 2, "w": 3, "h": 4}}}}',
        encoding="utf-8",
    )
    study = Study(
        Game(
            "cook",
            _hill(),
            assets=[Atlas("sheet", "sheet.png", "sheet.json")],
            render=_drawn,
        ),
        asset_root=str(tmp_path),
    )

    assert set(study.assets[0].frames) == {"counter.png"}
    assert set(study.assets_for("cook")[0].frames) == {"counter.png"}


# -- what a game activity is refused for --------------------------------------------


def test_a_seat_the_environment_does_not_have_is_refused() -> None:
    """The agents are read off the environment, so this needs nothing declared."""
    with pytest.raises(ValueError, match="does not have; its agents are: 'agent'"):
        Game("drive", _hill(), seats={"car": Human()})


def test_rounds_a_browser_run_plays_once_are_refused() -> None:
    """The author said what they wanted and nothing would say it was dropped."""
    with pytest.raises(ValueError, match="a browser run plays one"):
        Game("drive", _hill(), runs="browser", episodes=3, render=_drawn)


def test_a_model_seat_in_a_browser_is_refused() -> None:
    """A participant's browser holds no credential and must never be given one."""
    with pytest.raises(ValueError, match="must not travel to a participant's browser"):
        Game(
            "drive",
            _hill(),
            runs="browser",
            seats={"agent": Model(agent=None)},  # pyright: ignore[reportArgumentType]
            render=_drawn,
        )


def test_keys_written_without_saying_how_they_act_are_refused() -> None:
    """A grid and a court want opposite answers, so neither is a safe guess."""
    with pytest.raises(ValueError, match="does not say how they act"):
        Game("drive", _hill(), keys={"w": 2}, render=_drawn)


def test_keys_written_without_a_default_action_are_refused() -> None:
    """Action 0 is a no-op in some environments and a move in others."""
    with pytest.raises(ValueError, match="default_action="):
        Game("drive", _hill(), keys={"w": 2}, held_actions=True, render=_drawn)


def test_a_person_at_a_keyboard_bound_to_nothing_is_refused() -> None:
    """Neither environment API says which key is which action."""
    from gymnasium.envs.classic_control.cartpole import CartPoleEnv

    with pytest.raises(ValueError, match="nothing says which key is which action"):
        Game("balance", CartPoleEnv, seats={"agent": Human()}, render=_drawn)


def test_a_person_with_no_picture_at_all_is_refused() -> None:
    """Two shipped examples were unplayable while the gate was green.

    One of them was a multi-seat game with no drawing at all, which is a canvas that
    stays empty.
    """
    from gymnasium.envs.classic_control.cartpole import CartPoleEnv

    with pytest.raises(ValueError, match="drew nothing"):
        Game(
            "balance",
            CartPoleEnv,
            seats={"agent": Human()},
            keys={"a": 1},
            held_actions=True,
            default_action=0,
        )


def test_an_environment_that_draws_its_own_frames_is_still_refused() -> None:
    """The platform paints shapes, text, and named sprites -- never a bitmap.

    An environment that draws and a platform that cannot paint what it drew is the
    worst possible silence, so it is said out loud. It is the one place the design's
    "your trained environment needs no drawing code" story does not hold yet, and the
    refusal is what keeps that from being discovered by a participant.
    """
    drawing = pytest.importorskip(
        "pygame", reason="an environment that really draws is needed here"
    )
    del drawing
    with pytest.raises(ValueError, match="cannot paint a bitmap yet"):
        Game(
            "drive",
            _hill(),
            seats={"agent": Human()},
        )


def test_a_game_with_nobody_watching_needs_no_picture() -> None:
    """Two policies playing with nobody reading draw nothing, and that is right."""
    from gymnasium.envs.classic_control.cartpole import CartPoleEnv

    plays = Study(
        Game("balance", CartPoleEnv, seats={"agent": Bot(controller=_AlwaysLeft())})
    ).game_activities["balance"]

    assert not plays.found.draws
    assert plays.render is None


def test_a_registered_id_is_refused_where_an_author_writes_it() -> None:
    """A name is neither an environment nor a specification, so it is told apart.

    It reaches the author as advice rather than as a specification that fails much
    further on, because the registered id is exactly what somebody who has read the
    older documentation writes.
    """
    with pytest.raises(EnvironmentRefused, match=r"functools\.partial"):
        Game("drive", "MountainCar-v0")


def test_a_seating_written_as_a_list_is_still_refused() -> None:
    """A list states which agent somebody plays only by accident of order."""
    with pytest.raises(ValueError, match="must say which agent each player takes"):
        Game("drive", _hill(), seats=[Human()], render=_drawn)


# -- how fast it is played, and what a picture is drawn from -------------------------


def test_the_study_says_how_fast_it_is_played_and_the_environment_is_the_default():
    """The rate is an experiment's decision; the environment only supplies a default.

    The same task is a training environment at one rate and a study at another, and a
    frame rate a participant plays at changes what the task **is**. So a study's own
    ``fps`` outranks whatever the environment declares.
    """
    written = Study(
        Game("drive", _hill(), seats={"agent": Human()}, render=_drawn, fps=12)
    ).game_activities["drive"]
    read = Study(
        Game("drive", _hill(), seats={"agent": Human()}, render=_drawn)
    ).game_activities["drive"]

    assert written.found.fps == 30, "the environment declares its own rate"
    assert written.rate == 12, "and the study outranks it"
    assert read.rate == 30, "with none written, the environment's rate stands"


def test_only_the_specified_frame_rate_key_is_read() -> None:
    """An environment that declares a rate somewhere else has declared none.

    ``render_fps`` is the key Gymnasium specifies, and it is the only one read. An
    environment that ships another spelling falls to the platform's own default, which
    a study fixes by saying what it wants -- rather than the platform guessing from a
    key that means whatever each package decided it means.
    """
    from mug.game.environments import derive

    class _OldSpelling(gymnasium.Env[Any, Any]):
        """An environment with the pre-Gymnasium metadata key and nothing else."""

        metadata: ClassVar[dict[str, Any]] = {"video.frames_per_second": 50}

        def __init__(self) -> None:
            self.action_space = gymnasium.spaces.Discrete(2)

    assert derive(_OldSpelling).fps is None


def test_a_scene_is_what_a_picture_needs_and_an_observation_does_not_carry() -> None:
    """The study says what to read off the environment, and it lands in the frame.

    A drawing is handed a stepped frame, and a frame holds an observation -- which is
    what a policy is given, not what a picture needs. So the platform calls the
    study's ``scene`` on the live environment once a frame and puts the answer in that
    frame's own metrics, where it is recorded.
    """
    from mug.game.env import GymEnv
    from mug.gateway import Gateway
    from mug.mounts import mount_for

    plays = Study(
        Game(
            "drive",
            _hill(),
            seats={"agent": Human()},
            render=_drawn,
            scene=_where_the_car_is,
        )
    ).game_activities["drive"]

    game = mount_for(plays, derived_id=Gateway().derived_id).game
    assert game is not None
    stepped = GymEnv(game.make_env)
    opening = stepped.reset()
    moved = stepped.step(2)

    assert "where" in opening.info["scene"]
    assert isinstance(moved.info["scene"]["where"], float)


def test_a_scene_nothing_would_read_is_refused() -> None:
    """A turn-based episode carries no per-frame metrics, so a scene has no reader.

    A keyword that works on one runtime and silently does nothing on another is the
    failure this platform keeps finding in itself: a field with no reader looks
    exactly like a field that works.
    """
    pettingzoo = pytest.importorskip("pettingzoo", reason="the game extra is needed")

    class _TakingTurns(pettingzoo.utils.env.AECEnv[Any, Any, Any]):
        """The smallest turn-based environment. What it does does not matter here."""

        possible_agents: ClassVar[list[str]] = ["first", "second"]

        def __init__(self) -> None:
            self.agents = list(self.possible_agents)
            self.action_spaces = {
                agent: gymnasium.spaces.Discrete(2) for agent in self.agents
            }

        def observe(self, agent: str) -> Any:
            del agent
            return [0.0]

    with pytest.raises(ValueError, match="carries no per-frame metrics"):
        Game(
            "move",
            _TakingTurns,
            seats={"first": Human()},
            keys={"ArrowLeft": 0},
            held_actions=False,
            default_action=0,
            render=_drawn,
            scene=_nothing,
        )
