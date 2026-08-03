"""Nine mutually exclusive keywords, resolved from two words and a seating.

``build_study_app`` takes ``game``, ``server_game``, ``agent_game``,
``turnbased_game``, ``browser_game``, ``mesh_game``, ``browser_p2p``,
``concurrent_mesh``, and ``chat``. Not one of them is a decision a study author should
be making, and this is where that claim is checked: every test below writes an
environment and a seating, and asserts which runtime the platform resolved.

Two faults it closes are worth naming, because both are silent today.

**A study could hold only one environment.** The application resolved the builder's
keywords through one ``if / elif`` chain to **one** game hook, and one hook is all a
session had. So a study with a practice round in one environment and a real round in
another ran one of them twice, and nothing in the records said so.

**The keywords are not mutually exclusive.** ``build_study_app(study=s, game=g,
chat=...)`` is accepted: the chat arm wins and the game is dropped in silence.
"""

from __future__ import annotations

import functools
from typing import Any, ClassVar

import pytest

from mug.authoring import LLMAgent, Provider
from mug.content import Game, Page, Study
from mug.content.players import Bot, Human, Model
from mug.content.study import GameActivity
from mug.game.environments import Derived
from mug.mounts import MountRefused, describe, mount_kind, mounts_for

gymnasium = pytest.importorskip("gymnasium", reason="the game extra is not installed")


def _derived(kind: str, words: str) -> str:
    """Stand in for the gateway's derived identifier: same words, same answer."""
    return f"{kind}_{words}"


def _hill() -> Any:
    """Return a single-agent environment, as a study names one."""
    return functools.partial(gymnasium.make, "MountainCar-v0", render_mode="rgb_array")


def _drawn(_surface: Any, _step: Any) -> None:
    """Stand in for the study's own drawing."""


class _AlwaysLeft:
    """A local policy that plays a seat."""

    def decide(self, observation: object) -> int:
        del observation
        return 0


class _Table:
    """A two-agent environment behind the PettingZoo parallel API.

    It is written here rather than imported so the test says what it needs: the
    resolution reads ``possible_agents`` and the base class, and nothing else.
    """

    metadata: ClassVar[dict[str, Any]] = {"render_fps": 10}

    def __init__(self) -> None:
        self.possible_agents = ["north", "south"]
        self.agents = list(self.possible_agents)
        self.max_steps = 40

    def reset(self, seed: int | None = None) -> Any:
        del seed
        return {one: [0.0] for one in self.possible_agents}, {}

    def step(self, actions: Any) -> Any:
        del actions
        return (
            {one: [1.0] for one in self.possible_agents},
            {one: 0.0 for one in self.possible_agents},
            {one: False for one in self.possible_agents},
            {one: False for one in self.possible_agents},
            {},
        )

    def action_space(self, agent: str) -> Any:
        del agent
        return gymnasium.spaces.Discrete(4)

    def render(self) -> None:
        return None


def _table() -> Any:
    """Return the two-agent environment as a PettingZoo parallel environment."""
    pettingzoo = pytest.importorskip("pettingzoo", reason="the game extra is missing")

    class Parallel(_Table, pettingzoo.utils.env.ParallelEnv):  # pyright: ignore[reportUntypedBaseClass]
        """The same environment, declared as what it is."""

    return Parallel


# -- what each writing resolves to ---------------------------------------------------


def test_one_agent_and_one_person_on_the_server_is_the_single_seat_loop() -> None:
    """Today's ``game`` keyword, and nothing had to say so."""
    study = Study(
        Game("drive", _hill(), seats={"agent": Human()}, render=_drawn),
    )

    assert mount_kind(study.game_activities["drive"]) == "game"
    resolved = mounts_for(study, derived_id=_derived)
    assert resolved["drive"].game is not None
    assert resolved["drive"].runs_on_the_server


def test_the_frame_rate_and_episode_bound_reach_the_runtime() -> None:
    """They were hand-written on every specification, and both are the environment's."""
    study = Study(Game("drive", _hill(), seats={"agent": Human()}, render=_drawn))

    game = mounts_for(study, derived_id=_derived)["drive"].game
    assert game is not None
    assert game.fps == 30
    assert game.max_steps == 200
    # The bindings come from the environment's own play convention, held keys and all.
    assert game.input_mode == "pressed_keys"
    assert game.default_action == 1
    bound: dict[Any, int] = dict(game.action_bindings)
    assert bound["ArrowLeft"] == 0


def test_held_actions_false_reaches_the_loop_as_one_press_one_action() -> None:
    """The field once shipped with no producer and no reader, so it is asserted."""
    study = Study(
        Game(
            "drive",
            _hill(),
            seats={"agent": Human()},
            keys={"w": 2},
            held_actions=False,
            default_action=0,
            render=_drawn,
        )
    )

    game = mounts_for(study, derived_id=_derived)["drive"].game
    assert game is not None
    assert game.input_mode == "single_keystroke"
    assert game.action_bindings == {"w": 2}
    assert game.default_action == 0


def test_a_person_beside_a_local_policy_is_the_server_authoritative_game() -> None:
    """Today's ``server_game``, resolved from the seating alone."""
    study = Study(
        Game(
            "play",
            _table(),
            seats={"north": Human(), "south": Bot(controller=_AlwaysLeft())},
            keys={"w": 1},
            held_actions=True,
            default_action=0,
            render=_drawn,
        )
    )

    resolved = mounts_for(study, derived_id=_derived)["play"]
    assert resolved.kind == "server_game"
    assert resolved.server_game is not None
    assert resolved.server_game.human_agent_id == "north"
    assert [one.agent_id for one in resolved.server_game.bots] == ["south"]
    # The bot's recorded actor is derived, so the same study run twice records one.
    assert resolved.server_game.bots[0].actor_id == "actor_play:south"


def test_a_model_seat_is_the_multi_seat_agent_game() -> None:
    """Today's ``agent_game``. What makes it one is a model being seated."""
    study = Study(
        Game(
            "play",
            _table(),
            seats={
                "north": Human(),
                "south": Model(agent=_Partner(), key="partner"),
            },
            keys={"w": 1},
            held_actions=True,
            default_action=0,
            render=_drawn,
        )
    )

    resolved = mounts_for(study, derived_id=_derived)["play"]
    assert resolved.kind == "agent_game"
    assert resolved.agent_game is not None
    assert [one.agent_id for one in resolved.agent_game.seats] == ["south"]
    assert [one.agent_id for one in resolved.agent_game.human_seats] == ["north"]


def test_two_people_at_one_environment_is_one_table() -> None:
    """Several people is one interaction and one episode, not several runs."""
    study = Study(
        Game(
            "play",
            _table(),
            seats={"north": Human(), "south": Human()},
            keys={"w": 1},
            held_actions=True,
            default_action=0,
            render=_drawn,
        )
    )

    resolved = mounts_for(study, derived_id=_derived)["play"]
    assert resolved.kind == "agent_game"
    assert resolved.agent_game is not None
    assert len(resolved.agent_game.human_seats) == 2


def test_a_browser_run_is_resolved_and_refused_rather_than_run_wrongly() -> None:
    """The resolution is right and the platform says what it cannot do yet.

    A browser run needs a Python program carried into the participant's browser that
    builds the environment and draws each frame. Writing that program from a named
    environment is not built, so the refusal says so and names the two ways out. It
    is said out loud rather than resolved to a server run behind the author's back:
    a browser run and a server run are verified differently, and a study that asked
    for one and got the other would not know.
    """
    study = Study(
        Game("drive", _hill(), runs="browser", seats={"agent": Human()}, render=_drawn)
    )

    assert mount_kind(study.game_activities["drive"]) == "browser_game"
    with pytest.raises(MountRefused, match="cannot yet write the browser program"):
        mounts_for(study, derived_id=_derived)


def test_two_people_in_a_browser_resolve_to_a_mesh() -> None:
    """Today's ``mesh_game`` and ``browser_p2p``, from the count of people.

    The activity is written directly rather than through ``Game``, because an
    environment declared inside a test file cannot travel to a browser and ``Game``
    refuses it for exactly that (which is its own test, in ``tests/unit/game``). What
    is under test here is the resolution, so it is given the two facts it reads.
    """
    plays = _plays(
        runs="browser",
        agents=("north", "south"),
        api="pettingzoo-parallel",
        seats={"north": Human(), "south": Human()},
    )

    assert mount_kind(plays) == "mesh_game"


def test_one_person_in_a_browser_is_the_single_browser_run() -> None:
    """Today's ``browser_game``, from the same two facts."""
    plays = _plays(runs="browser", agents=("agent",), seats={"agent": Human()})

    assert mount_kind(plays) == "browser_game"


def test_an_environment_that_takes_turns_is_read_not_written() -> None:
    """Today's ``turnbased_game`` comes from the base class and nowhere else."""
    plays = _plays(
        agents=("north", "south"),
        api="pettingzoo-aec",
        seats={"north": Human(), "south": Model(agent=_Partner())},
    )

    assert mount_kind(plays) == "turnbased_game"


def _plays(
    *,
    agents: tuple[Any, ...],
    seats: Any,
    runs: Any = "server",
    api: str = "gymnasium",
) -> GameActivity:
    """Build one resolved activity from the facts the resolution actually reads.

    The resolution reads four things: where it runs, which API the environment is,
    how many people are seated, and whether a model is. So those are what this
    supplies, and a test of the resolution then tests the resolution.
    """
    return GameActivity(
        key="play",
        env=lambda: None,
        found=Derived(
            api=api,
            build="",
            requires=(),
            agents=agents,
            actions=dict.fromkeys(agents, "Discrete(4)"),
            default_action=0,
            keys={"w": 1},
            fps=10,
            max_steps=40,
            draws=False,
        ),
        runs=runs,
        seats=seats,
        keys={"w": 1},
        held_actions=True,
        default_action=0,
        render=_drawn,
    )


# -- what one study holding several environments resolves to -------------------------


def test_one_study_holds_two_environments_and_runs_both() -> None:
    """The fault this closes: a study could hold only one environment.

    The application resolved one game hook for the whole study, so a practice round in
    one environment and a real round in another ran the same one twice with nothing in
    the records to say it.
    """
    study = Study(
        Page("intro", "# Ready"),
        Game("drive", _hill(), seats={"agent": Human()}, render=_drawn),
        Game(
            "play",
            _table(),
            seats={"north": Human(), "south": Bot(controller=_AlwaysLeft())},
            keys={"w": 1},
            held_actions=True,
            default_action=0,
            render=_drawn,
        ),
    )

    resolved = mounts_for(study, derived_id=_derived)
    assert [one.kind for one in resolved.values()] == ["game", "server_game"]
    assert resolved["drive"].game is not None
    assert resolved["play"].server_game is not None


def test_a_study_can_be_asked_what_it_will_run() -> None:
    """The resolution is readable, so an author never has to run it to find out."""
    study = Study(
        Game("drive", _hill(), seats={"agent": Human()}, render=_drawn, episodes=2),
    )

    assert describe(study) == ["drive        on the server x2  [agent=human]  -> game"]


# -- what the resolution refuses -----------------------------------------------------


def test_a_multi_agent_environment_with_no_seating_is_refused() -> None:
    """Seating somebody positionally is the one thing the map exists to prevent."""
    study = Study(Game("play", _table(), render=_drawn))

    with pytest.raises(MountRefused, match="does not say who plays each"):
        mounts_for(study, derived_id=_derived)


def test_two_people_beside_a_local_policy_is_not_a_server_authoritative_game() -> None:
    """One server-authoritative game seats one person; two people is a table."""
    study = Study(
        Game(
            "play",
            _three(),
            seats={
                "one": Human(),
                "two": Human(),
                "three": Bot(controller=_AlwaysLeft()),
            },
            keys={"w": 1},
            held_actions=True,
            default_action=0,
            render=_drawn,
        )
    )

    # Two people resolve to a table, which is right, so the refusal is not reached
    # from here -- it guards the one-person path against being handed two.
    assert mounts_for(study, derived_id=_derived)["play"].kind == "agent_game"


def _three() -> Any:
    """Return a three-agent parallel environment."""
    pettingzoo = pytest.importorskip("pettingzoo", reason="the game extra is missing")

    class Three(_Table, pettingzoo.utils.env.ParallelEnv):  # pyright: ignore[reportUntypedBaseClass]
        """Three agents at one environment."""

        def __init__(self) -> None:
            super().__init__()
            self.possible_agents = ["one", "two", "three"]
            self.agents = list(self.possible_agents)

    return Three


class _Partner(LLMAgent):
    """The smallest model a study can seat. What it decides does not matter here."""

    provider = Provider.OSS
    model = "fake-local"
