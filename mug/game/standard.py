"""Adapt the two standard environment APIs onto the seams the loops step.

``mug.game.environments`` reads what an environment **is**. This module is what turns
one into something the platform can step: a PettingZoo parallel environment behind the
``MultiSeatEnv`` seam, and the same environment behind the peer-to-peer replica seam.

**Nothing here knows any environment.** It knows the two standard APIs -- which is the
whole point, because a study then names the environment it trained in and writes no
adapter at all. Every study that plays a multi-agent environment on this platform has
written one of these by hand, and each hand-written copy carried the same three
mechanical parts: key one result set back under the agent names, make an observation
into data a record can hold, and count the frames.

A single-agent Gymnasium environment needs nothing here: ``GymEnv`` (``mug.game.env``)
already steps it, and a factory that returns one satisfies ``GameSpec.make_env``
directly. A PettingZoo AEC environment needs nothing either: ``AecEnv``
(``mug.agents.turnbased_episode``) is its adapter, and ``TurnBasedGameSpec`` reaches
for it by default.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

from mug.game.env import EnvFactory as GymFactory
from mug.game.multiseat import MultiSeatEnv, MultiStepResult

# Build one environment and hand it over. It takes no arguments: whatever the
# environment needs is bound inside it by the author (``mug.game.environments``).
BuildEnv = Callable[[], Any]

# Read a picture's worth of state off the environment, once a frame.
#
# An observation is what a **policy** is given, and it is often not what a **picture**
# needs: a kitchen's pots and counters, a court's ball, a board's pieces. Those sit on
# the environment, and a drawing is handed a stepped frame rather than the environment.
# So a study says what a picture needs, and the platform calls it each frame and puts
# the answer in that frame's own metrics.
#
# Putting it in the record rather than passing the environment to the drawing is the
# whole point: what was drawn is then part of what happened, so a replay and an export
# read the same picture the participant saw. A drawing handed the live environment would
# draw from state nothing kept.
Scene = Callable[[Any], Mapping[str, Any]]

# Where a scene sits in a frame's metrics. It is nested under one key so that a study's
# own words can never collide with the platform's (``frame``, ``reward_total``).
SCENE = "scene"


def _scene_of(scene: Scene | None, env: Any) -> dict[str, Any]:
    """Return the scene one frame carries, as data a record can hold."""
    if scene is None:
        return {}
    return {SCENE: jsonable(dict(scene(env)))}


def jsonable(value: Any) -> Any:
    """Return one observation as data a record can hold.

    An observation is whatever the environment hands over -- most often a numpy array,
    sometimes a nest of them. A record holds data, so it is flattened here rather than
    in each study that writes one.
    """
    listed = getattr(value, "tolist", None)
    if callable(listed):
        return cast("Any", listed())
    if isinstance(value, dict):
        held = cast("dict[Any, Any]", value)
        return {str(key): jsonable(item) for key, item in held.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in cast("Sequence[Any]", value)]
    return value


def _per_agent(value: Any, agents: Sequence[Any], zero: Any) -> dict[str, Any]:
    """Read one value per agent from whatever the environment returned for all.

    A parallel environment answers a map keyed by its own agents. One that answers a
    single value for the whole step -- a shared reward, one terminal flag -- is read as
    that value for every agent, which is what a shared value means.
    """
    if isinstance(value, dict):
        held = cast("dict[Any, Any]", value)
        return {str(agent): held.get(agent, zero) for agent in agents}
    return {str(agent): (zero if value is None else value) for agent in agents}


def _ended(value: Any, agents: Sequence[Any]) -> bool:
    """Say whether the episode ended, from a flag that may be one or one per agent.

    The loop records one shared timeline, so every seat's timeline closes on the same
    frame. An environment that ends one agent at a time ends the episode when **any**
    agent is done, because a seat that has no environment left to step cannot go on.
    """
    if isinstance(value, dict):
        held = cast("dict[Any, bool]", value)
        return any(bool(held.get(agent, False)) for agent in agents)
    return bool(value)


class ParallelSeats:
    """One PettingZoo parallel environment behind the multi-seat loop's seam.

    The loop steps one action set and records one shared result. The agents are the
    environment's own, so a study keeps no map from its seat names to the
    environment's -- which is what every multi-agent study here used to carry, and
    what turned a mistyped seat into a ``KeyError`` on a participant's first frame.

    Each frame's metrics carry ``frame`` and ``reward_total``, so a study's status line
    has something to read without the study having to count for itself. They carry the
    study's own ``scene`` beside those, for a picture that needs more than an
    observation.
    """

    def __init__(
        self, build: BuildEnv, *, seed: int | None = None, scene: Scene | None = None
    ) -> None:
        self._env = build()
        self._seed = seed
        self._scene = scene
        self._agents: tuple[Any, ...] = tuple(
            getattr(self._env, "possible_agents", None) or ()
        )
        self._frame = 0
        self._earned = 0.0

    @property
    def env(self) -> Any:
        """Return the environment itself, for a drawing that reads more than a frame.

        A study's own drawing is handed the step result, and some environments hold
        what a picture needs on the environment rather than in the observation. So the
        environment is reachable, and reading it is the study's own decision.
        """
        return self._env

    @property
    def agents(self) -> tuple[Any, ...]:
        """Return the agents this environment acts, in the environment's own order."""
        return self._agents

    def reset(self) -> MultiStepResult:
        """Reset the environment and return the opening state for every seat."""
        observed = self._reset()
        self._frame = 0
        self._earned = 0.0
        return self._result(observed, None, False, False)

    def step(self, actions: Mapping[str, int]) -> MultiStepResult:
        """Step every seat's action at once and return the one shared result."""
        stepped = cast("Callable[[Mapping[Any, int]], Any]", self._env.step)
        result = stepped(self._actions(actions))
        observed, rewards, terminated, truncated = _unpack(result)
        self._frame += 1
        self._earned += _total(rewards)
        return self._result(
            observed,
            rewards,
            _ended(terminated, self._agents),
            _ended(truncated, self._agents),
        )

    def _actions(self, actions: Mapping[str, int]) -> dict[Any, int]:
        """Key the loop's seat actions back under the environment's own agents.

        The loop names a seat with text, because every identifier in the records is
        text. An environment may name its agents with numbers, so the two are matched
        by the agent's own written form -- never by position, which is what would make
        a reordered seating silently swap two roles.
        """
        by_name = {str(agent): agent for agent in self._agents}
        return {
            by_name.get(seat, seat): int(action) for seat, action in actions.items()
        }

    def _reset(self) -> Any:
        """Reset with the shared seed, for an environment that takes one."""
        reset = cast("Callable[..., Any]", self._env.reset)
        try:
            result = reset(seed=self._seed)
        except TypeError:
            result = reset()
        if not self._agents:
            # An environment that names its agents only once it has been reset.
            self._agents = tuple(getattr(self._env, "agents", None) or ())
        # A parallel reset answers (observations, infos); one that answers the
        # observations alone is read as it stands.
        if isinstance(result, tuple):
            return cast("Sequence[Any]", result)[0]
        return result

    def _result(
        self, observed: Any, rewards: Any, terminated: bool, truncated: bool
    ) -> MultiStepResult:
        """Return one stepped frame keyed by the environment's own agents."""
        return MultiStepResult(
            observations={
                seat: jsonable(value)
                for seat, value in _per_agent(observed, self._agents, None).items()
            },
            rewards={
                seat: float(value or 0.0)
                for seat, value in _per_agent(rewards, self._agents, 0.0).items()
            },
            terminated=terminated,
            truncated=truncated,
            info={
                "frame": self._frame,
                "reward_total": self._earned,
                **_scene_of(self._scene, self._env),
            },
        )


def _unpack(result: Any) -> tuple[Any, Any, Any, Any]:
    """Read one parallel step's return, whichever of the two lengths it is.

    PettingZoo returns five values (observations, rewards, terminations,
    truncations, infos). Some environments return four, with one ``done``. Both are
    read rather than one being insisted on, because refusing an environment over the
    shape of its tuple is refusing it for nothing.
    """
    parts = cast("Sequence[Any]", result)
    if len(parts) >= 5:
        return parts[0], parts[1], parts[2], parts[3]
    if len(parts) == 4:
        return parts[0], parts[1], parts[2], False
    raise TypeError(
        "a parallel environment's step returns observations, rewards, terminations, "
        f"and truncations; this one returned {len(parts)} values"
    )


def _total(rewards: Any) -> float:
    """Return what the whole step earned, from one reward or one per agent."""
    if isinstance(rewards, dict):
        held = cast("dict[Any, Any]", rewards)
        return float(sum(float(one or 0.0) for one in held.values()))
    return float(rewards or 0.0)


def seated_env(
    build: BuildEnv, *, seed: int | None = None, scene: Scene | None = None
) -> Callable[[], MultiSeatEnv]:
    """Return the factory the multi-seat loop takes, over a parallel environment."""

    def make() -> MultiSeatEnv:
        return ParallelSeats(build, seed=seed, scene=scene)

    return make


class _SceneInFrame:
    """One Gymnasium environment with the study's scene added to each frame.

    Every attribute but the two stepping methods is the environment's own, so whatever
    else reaches for the environment -- a determinism hook, a state hash, an unwrapped
    attribute -- finds what it would have found.
    """

    def __init__(self, env: Any, scene: Scene) -> None:
        self._env = env
        self._scene = scene

    def __getattr__(self, name: str) -> Any:
        return getattr(self._env, name)

    def reset(self, **named: Any) -> tuple[Any, dict[str, Any]]:
        """Reset, and report the opening scene with the opening frame."""
        reset = cast("Callable[..., Any]", self._env.reset)
        observed, info = cast("tuple[Any, Any]", reset(**named))
        return observed, self._with_scene(info)

    def step(self, action: Any) -> tuple[Any, Any, Any, Any, dict[str, Any]]:
        """Step one action, and report the scene it left behind."""
        stepped = cast("Callable[[Any], Any]", self._env.step)
        observed, reward, terminated, truncated, info = cast(
            "tuple[Any, Any, Any, Any, Any]", stepped(action)
        )
        return observed, reward, terminated, truncated, self._with_scene(info)

    def _with_scene(self, info: Any) -> dict[str, Any]:
        """Add this frame's scene to whatever the environment reported itself."""
        held = dict(cast("dict[str, Any]", info)) if isinstance(info, dict) else {}
        held.update(_scene_of(self._scene, self._env))
        return held


def solo_factory(build: BuildEnv, *, scene: Scene | None = None) -> GymFactory:
    """Return the factory the single-seat loop takes, over a Gymnasium environment.

    With no ``scene`` it is a rename and nothing else: the loop's own adapter already
    steps a Gymnasium environment, so a study that named one has already handed over
    what the loop wants. The function exists so that every execution reaches its
    environment the same way, and so a reader can see that this path adapts nothing.

    With one, the environment is wrapped so that its frames carry the scene -- because
    a keyword that works on a game with two seats and quietly does nothing on a game
    with one is worse than no keyword at all.
    """
    if scene is None:
        return cast("GymFactory", build)

    def make() -> Any:
        return _SceneInFrame(build(), scene)

    return cast("GymFactory", make)


__all__ = [
    "SCENE",
    "BuildEnv",
    "ParallelSeats",
    "Scene",
    "jsonable",
    "seated_env",
    "solo_factory",
]
