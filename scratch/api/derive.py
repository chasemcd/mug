"""Derive a whole game activity from the environment class, and nothing else.

Scratch. Nothing in ``mug/`` imports it. Run it::

    uv run python scratch/api/derive.py

The requirement this answers: **an author gives MUG the Gymnasium or PettingZoo
environment they trained in, and MUG does the rest.** No ``BrowserGameSpec``, no
``source_bundle``, no ``MultiSeatGame``, no hand-written package pin. The whole
appeal of the platform is that the step from "my agent trains against this" to "a
participant plays this in a browser" is short, and every specification an author
writes by hand is a piece of that step they have to do themselves.

So this module asks what can actually be read off a real environment. Everything
below is read from the **installed** packages, not assumed: run it and see.

**What is derived.** The environment API (Gymnasium, PettingZoo parallel, or
PettingZoo AEC) from the base classes; the agents from ``possible_agents``; the
action set from ``action_space``; the frame rate from ``metadata["render_fps"]``;
the episode limit from the spec or the environment's own bound; the drawing from
``render_mode="rgb_array"``; the key bindings from
``get_keys_to_action`` where the environment follows the ``gymnasium.utils.play``
convention; and the package pin for a browser run from the distribution that
provides the class.

**Why the pin matters more than it looks.** A browser run is verified by the server
re-executing it, so the two must step identically. The browser pin and the server
package are written in different places today, they were allowed to drift once
(the browser asked for cogrid 0.2.1 while the server had 0.3.1), and the result is
that every honest run is refused. Derived from the installed class, one cannot
drift from the other.

**What is not derived, and why.** Which agent a person plays (a study decision, and
the most consequential one). Where the environment runs (a study decision the
participant feels). Whether a key is held or tapped, when the environment does not
say. A drawing better than the frames the environment renders. Everything else is
plumbing, and plumbing is the platform's.
"""

from __future__ import annotations

import importlib
import importlib.metadata as metadata
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# What Pyodide ships itself, so a browser run needs no wheel for it. This is a
# short, checkable list rather than a guess: anything else must be a pure-Python
# wheel, which is a property of the installed distribution and is read below.
PYODIDE_CARRIES: frozenset[str] = frozenset(
    {"numpy", "scipy", "pandas", "micropip", "packaging", "setuptools"}
)

# A file suffix that says a distribution holds compiled code. Compiled code needs a
# wheel built for Pyodide's own platform, which a study cannot assume exists, so a
# distribution holding any of these blocks a browser run until somebody says
# otherwise.
COMPILED = (".so", ".pyd", ".dylib")

# The pygame key codes ``gymnasium.utils.play`` uses, and the browser key names the
# platform's bindings are written in. Only the keys an environment actually binds
# have to be here; an unknown code is reported rather than guessed.
BROWSER_KEY: dict[int, str] = {
    32: " ",
    97: "a",
    100: "d",
    115: "s",
    119: "w",
    273: "ArrowUp",
    274: "ArrowDown",
    275: "ArrowRight",
    276: "ArrowLeft",
}


def _env_bases() -> tuple[type, ...]:
    """Return the three environment base classes, for the ones that are installed.

    A study may have Gymnasium and not PettingZoo, or the other way round, so the
    check is built from what is here. A machine with neither cannot run any study, and
    says so plainly rather than accepting anything with a ``step`` method.
    """
    found = [
        _maybe("gymnasium", "Env"),
        _maybe("pettingzoo.utils.env", "ParallelEnv"),
        _maybe("pettingzoo.utils.env", "AECEnv"),
    ]
    bases = tuple(one for one in found if isinstance(one, type))
    if not bases:
        raise RuntimeError(
            "neither gymnasium nor pettingzoo is installed, so no environment can be "
            "read: install one of them"
        )
    return bases


# What a game activity names: something that takes no arguments and returns one of the
# three environment APIs. A class is one, ``functools.partial(gymnasium.make, "id")`` is
# one, and a study's own ``def kitchen(): ...`` is one.
#
# It takes **no arguments**, which is the strict part. Everything an environment needs
# to be built is bound inside the callable, by the author, in the place they are already
# constructing it -- including ``render_mode="rgb_array"`` if they want the
# environment's own frames. So the platform injects nothing, and a configuration holding
# live objects (CoGrid's reward instances) needs no written form at all.
EnvFactory = Callable[[], Any]


@dataclass(frozen=True)
class Derived:
    """Everything one game activity needs, read off the environment itself.

    ``blocks`` is the list of reasons this environment cannot run in a participant's
    browser. It is empty when it can. It exists because the answer must arrive while
    the author reads their own code, and not as a failed download in front of a
    participant.

    ``asks`` is what the environment cannot say and a study must: it is short, and
    every line in it is a genuine study decision rather than a gap.
    """

    api: str
    build: str
    requires: tuple[str, ...]
    agents: tuple[Any, ...]
    actions: Mapping[Any, str]
    default_action: int | None
    keys: Mapping[str, int] | None
    fps: int | None
    max_steps: int | None
    draws: bool
    # Why the environment handed over no frame, when it did not. An environment that
    # declares ``rgb_array`` and then cannot draw is the common case, and the reason
    # is always worth reading: it is usually a missing package rather than a missing
    # capability.
    draw_blocked_by: str | None = None
    blocks: tuple[str, ...] = ()
    asks: tuple[str, ...] = ()

    @property
    def runs_in_a_browser(self) -> bool:
        """Say whether this environment can step in a participant's own browser."""
        return not self.blocks

    @property
    def is_multi_agent(self) -> bool:
        """Say whether more than one agent acts in this environment."""
        return len(self.agents) > 1


def derive(source: EnvFactory, /) -> Derived:
    """Read one whole game activity off the environment the author named.

    ``source`` takes no arguments and returns a ``gymnasium.Env``, a PettingZoo
    ``ParallelEnv``, or a PettingZoo ``AECEnv``. Three things are:

    - an environment **class** -- ``derive(MountainCarEnv)``;
    - a bound call -- ``derive(partial(gymnasium.make, "MountainCar-v0"))``;
    - a study's own **factory** -- ``derive(kitchen)``.

    Anything else is refused, and so is an environment that turns out not to be one of
    the three APIs. There is no duck-typed fallback: a study that has an environment of
    its own wraps it, which is a small and well-understood wrapper, and the platform
    then has one path it always tests.
    """
    built, build, module = _build(source)
    api = _api_of(built)
    agents = _agents_of(built, api)
    spaces = {agent: _space_of(built, agent, api) for agent in agents}
    keys, default = _keys_of(built)
    requires, blocks = _travels(source, module)
    draws, why = _draws(built)
    return Derived(
        api=api,
        build=build,
        requires=requires,
        agents=agents,
        actions={agent: str(space) for agent, space in spaces.items()},
        default_action=default,
        keys=keys,
        fps=_fps_of(built),
        max_steps=_max_steps_of(built),
        draws=draws,
        draw_blocked_by=why,
        blocks=blocks,
        asks=_asks(draws, keys, agents),
    )


# -- what the environment is --------------------------------------------------------


def _build(source: EnvFactory) -> tuple[Any, str, str]:
    """Build the environment once, and return the call that rebuilds it elsewhere.

    It is built because almost nothing useful is on the class: ``possible_agents``,
    ``action_space``, and the episode bound are all set in ``__init__``. So the platform
    builds one at publication, reads it, and throws it away -- which is also the moment
    an environment that cannot be built at all says so, rather than at the first
    participant.
    """
    if isinstance(source, str):
        raise TypeError(
            f"a game activity is given something callable, not the registered id "
            f"{source!r}: write functools.partial(gymnasium.make, {source!r}) instead, "
            "so that what builds an environment is one kind of thing everywhere"
        )
    if not callable(source):
        raise TypeError(
            "a game activity names something that builds its environment and takes no "
            "arguments: an environment class, "
            'functools.partial(gymnasium.make, "SomeEnv-v0"), or a function of your '
            f"own. A {type(source).__name__} is none of those."
        )
    built = source()
    _refuse_a_thing_that_is_not_an_environment(source, built)
    return built, _rebuilt_by(source), _module_of(source)


def _refuse_a_thing_that_is_not_an_environment(source: Any, built: Any) -> None:
    """Refuse anything that is not one of the three environment APIs.

    Checked on what was **returned**, by base class, not by what it answers to. An
    object with ``step`` and ``reset`` may be an environment or may be a wrapper, a
    replay, or a mistake, and the difference decides how every other derivation below
    is read -- which agents there are, how an action is passed, whether a turn is
    taken.
    """
    if isinstance(built, _env_bases()):
        return
    named = getattr(source, "__qualname__", None) or type(source).__name__
    raise TypeError(
        f"{named} returned a {type(built).__module__}.{type(built).__name__}, which is "
        "not a gymnasium.Env, a pettingzoo ParallelEnv, or a pettingzoo AECEnv. Wrap "
        "it in one of the three -- the wrapper is small, and it is what lets the "
        "platform read the agents, the actions, and the drawing off it."
    )


def _rebuilt_by(source: Any) -> str:
    """Return the call that rebuilds this environment somewhere else.

    A class and a ``functools.partial`` both write themselves down: a class is its own
    import path, and a partial is its function's path with its bound arguments. A
    study's own function writes itself as a call, and its **source** is what travels
    (see ``_travels``).
    """
    import functools

    if isinstance(source, functools.partial):
        where = f"{source.func.__module__}.{source.func.__qualname__}"
        written = [repr(one) for one in source.args]
        written += [f"{key}={value!r}" for key, value in source.keywords.items()]
        return f"{where}({', '.join(written)})"
    where = getattr(source, "__qualname__", type(source).__name__)
    return f"{_module_of(source)}.{where}()"


def _module_of(source: Any) -> str:
    """Return the module the callable came from, following a partial to its function."""
    import functools

    if isinstance(source, functools.partial):
        return str(source.func.__module__)
    return str(getattr(source, "__module__", ""))


def _api_of(built: Any) -> str:
    """Name the environment API from what the environment actually inherits.

    Read rather than declared: an author who says "PettingZoo" and hands over a
    Gymnasium environment has said something the platform can check.
    """
    for module, name, api in (
        # ParallelEnv and AECEnv first: a PettingZoo environment is not a gymnasium.Env,
        # but the order is fixed anyway so that one machine's answer is every machine's.
        ("pettingzoo.utils.env", "ParallelEnv", "pettingzoo-parallel"),
        ("pettingzoo.utils.env", "AECEnv", "pettingzoo-aec"),
        ("gymnasium", "Env", "gymnasium"),
    ):
        base = _maybe(module, name)
        if base is not None and isinstance(built, base):
            return api
    # Unreachable: _refuse_a_thing_that_is_not_an_environment has already run. It is
    # here so that a change to one and not the other is a failure rather than a
    # silently-wrong api name.
    raise AssertionError("an environment passed the base-class check and matched none")


def _maybe(module: str, name: str) -> Any:
    """Return one class if its package is installed, and nothing if it is not."""
    try:
        return getattr(importlib.import_module(module), name)
    except Exception:
        return None


def _agents_of(built: Any, api: str) -> tuple[Any, ...]:
    """Return the agents that act in this environment, in the environment's order.

    This replaces the ``agents=(...)`` an author would otherwise write and the
    seat-to-index map every multi-agent example keeps by hand. CoGrid's Overcooked
    answers ``[0, 1]``, which is the map.
    """
    if api == "gymnasium":
        return ("agent",)
    for name in ("possible_agents", "agents"):
        found = getattr(built, name, None)
        if found:
            return tuple(found)
    # A parallel environment that names its agents only after a reset.
    reset = getattr(built, "reset", None)
    if callable(reset):
        reset(seed=0)
        found = getattr(built, "agents", None)
        if found:
            return tuple(found)
    return ("agent",)


def _space_of(built: Any, agent: Any, api: str) -> Any:
    """Return one agent's action space, whichever way this API spells it."""
    space = getattr(built, "action_space", None)
    if callable(space) and "gymnasium" not in api:
        try:
            return space(agent)
        except TypeError:
            return space
    return space


def _keys_of(built: Any) -> tuple[dict[str, int] | None, int | None]:
    """Read the key bindings the environment declares, if it declares any.

    ``gymnasium.utils.play`` has a convention for this -- ``get_keys_to_action``
    returns a map from a tuple of held keys to an action, and the empty tuple is
    what the environment does when nothing is held. It is the platform's own
    binding shape, chords included, so an environment that follows it needs no
    bindings written at all. MountainCar follows it; CoGrid does not.
    """
    read = getattr(getattr(built, "unwrapped", built), "get_keys_to_action", None)
    if not callable(read):
        return None, None
    try:
        declared = read()
    except Exception:
        return None, None
    bindings: dict[str, int] = {}
    default: int | None = None
    for held, action in dict(declared).items():
        codes = tuple(held) if isinstance(held, tuple) else (held,)
        if not codes:
            default = int(action)
            continue
        named = [BROWSER_KEY.get(int(code)) for code in codes]
        if any(one is None for one in named):
            # Reported rather than guessed. A key bound to the wrong action is worse
            # than a key bound to nothing.
            continue
        bindings["+".join(str(one) for one in named)] = int(action)
    return bindings or None, default


def _fps_of(built: Any) -> int | None:
    """Return the frame rate the environment says it draws at."""
    declared = getattr(built, "metadata", None) or {}
    rate = declared.get("render_fps")
    return int(rate) if rate else None


def _max_steps_of(built: Any) -> int | None:
    """Return the episode limit, from wherever this environment keeps it."""
    spec = getattr(built, "spec", None)
    limit = getattr(spec, "max_episode_steps", None)
    if limit:
        return int(limit)
    for name in ("max_steps", "_max_steps", "max_cycles"):
        found = getattr(getattr(built, "unwrapped", built), name, None)
        if isinstance(found, int) and found > 0:
            return found
    return None


def _draws(built: Any) -> tuple[bool, str | None]:
    """Say whether the environment hands over a frame, and why not when it does not.

    Asked by drawing one, not by reading ``metadata``. An environment that lists
    ``rgb_array`` and then needs a package it does not declare answers yes to the
    declaration and no to the question, and the question is the one that matters.
    Both Gymnasium classic-control environments here are that case: they list
    ``rgb_array`` and draw with pygame.
    """
    render = getattr(built, "render", None)
    if not callable(render):
        return False, "the environment has no render()"
    try:
        built.reset(seed=0)
    except Exception as problem:
        return False, f"reset() raised {type(problem).__name__}: {problem}"
    try:
        frame = render()
    except Exception as problem:
        return False, f"render() raised {type(problem).__name__}: {problem}"
    if getattr(frame, "ndim", 0) == 3:
        return True, None
    return False, f"render() returned {type(frame).__name__}, not an image"


# -- what a browser run needs -------------------------------------------------------


def _travels(source: Any, module: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the pins a browser run installs, and what stops it if anything does.

    Every pin is the version installed **here**, which is the whole point: the server
    verifies a browser run by re-executing it, so the two step identically only if
    the pin is the installed version rather than a number somebody typed. The pin
    that drifted once (browser 0.2.1, server 0.3.1) cannot drift from a derivation.

    Where the roots come from depends on what the author named. A class or a
    registered id comes from its own module. A factory is study code, so what has to
    be installed is what the **factory imports** -- and a factory that imports the
    study itself is refused, because a browser cannot install the study.
    """
    import functools

    # A class or a partial names its own package, so nothing of the study travels. A
    # study's own function is study code, so what has to be installed is what the
    # function imports -- and a function that imports the study itself is refused.
    roots = (
        {module.split(".")[0]}
        if isinstance(source, (type, functools.partial))
        else _imports_of(source)
    )
    pins: list[str] = []
    blocks: list[str] = []
    local: list[str] = []
    for root in sorted(roots):
        if root in sys.stdlib_module_names:
            continue
        names = metadata.packages_distributions().get(root)
        if not names:
            local.append(root)
            continue
        for name in names:
            pins.append(f"{name}=={metadata.version(name)}")
            why = _cannot_travel(name)
            if why is not None:
                blocks.append(why)
    if local:
        blocks.append(_refuse_local(source, sorted(set(local))))
    return tuple(sorted(set(pins))), tuple(blocks)


def _refuse_local(source: Any, local: Sequence[str]) -> str:
    """Say that what builds the environment reaches code a browser cannot install."""
    import functools

    named = ", ".join(local)
    if isinstance(source, (type, functools.partial)):
        return (
            f"the environment comes from {named}, which is not an installed "
            "distribution, so a browser run has nothing to install: publish it, or "
            "name a class from a package that is installed."
        )
    return (
        f"the factory {getattr(source, '__name__', 'that builds it')!r} imports "
        f"{named}, which is the study's own code and a participant's browser cannot "
        "install it. Move what the factory needs into a published package, keep the "
        "factory to imports the browser can resolve, or run this activity on the "
        "server."
    )


def _imports_of(source: Any) -> set[str]:
    """Return the root packages a factory imports, read from its own source.

    A factory that builds an environment is usually four imports and a constructor,
    so reading its imports is enough to know what a browser has to install. It is
    also how a factory that reaches the study's own code is caught.
    """
    import ast
    import inspect
    import textwrap

    try:
        text = inspect.getsource(source)
    except (OSError, TypeError):
        return set()
    tree = ast.parse(textwrap.dedent(text))
    found: set[str] = set()
    for node in ast.walk(tree):
        found.update(_imported_roots(node))
    return found


def _cannot_travel(name: str) -> str | None:
    """Say why one distribution cannot be installed in a participant's browser.

    Compiled code needs a wheel built for Pyodide's own platform. A study cannot
    assume one exists, and the place to find out is here rather than in a download
    that fails in front of somebody.
    """
    if name in PYODIDE_CARRIES:
        return None
    try:
        files = metadata.distribution(name).files or []
    except metadata.PackageNotFoundError:
        return None
    compiled = sorted({one.name for one in files if one.name.endswith(COMPILED)})
    if not compiled:
        return None
    return (
        f"{name} holds compiled code ({compiled[0]} and {len(compiled) - 1} more), "
        "so a participant's browser cannot install it: run this activity on the "
        "server, or name an environment that is pure Python."
    )


def _imported_roots(node: Any) -> list[str]:
    """Return the root packages one statement imports, if it imports anything."""
    import ast

    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module and not node.level:
        return [node.module.split(".")[0]]
    return []


def _installed(root: str) -> bool:
    """Say whether one root module is provided by an installed distribution."""
    if root in sys.stdlib_module_names:
        return True
    return bool(metadata.packages_distributions().get(root))


def _asks(
    draws: bool, keys: Mapping[str, int] | None, agents: Sequence[Any]
) -> tuple[str, ...]:
    """Return what the environment cannot say and the study must.

    Kept short on purpose. Every line here is a genuine study decision; a line that
    turned out to be derivable belongs above this function instead.
    """
    asks: list[str] = []
    if keys is None:
        asks.append(
            "keys= : which key is which action. Nothing in either API says that, and "
            "this environment does not follow the gymnasium.utils.play convention."
        )
        asks.append(
            "held_actions= : True if a key acts on every frame it is down (a court), "
            "False if one press is one action (a grid)."
        )
        asks.append(
            "default_action= : what a frame with no bound key takes. Action 0 is a "
            "no-op in some environments and a move in others."
        )
    if len(agents) > 1:
        asks.append(
            "seats= : which agent each player takes. It is the study's most "
            "consequential decision, so it is written rather than derived."
        )
    if not draws:
        asks.append(
            "render= : this environment hands over no frame, so the activity needs "
            "a drawing of its own."
        )
    return tuple(asks)


# -- the bundle the browser runs ----------------------------------------------------

# The generic bundle. It is the platform's, one copy for every environment, and it
# is what replaces the two hundred lines of hand-written Python each browser example
# ships today. The environment's own frames are painted as one image command, so a
# study that writes no drawing still gets the picture its environment draws.
_BUNDLE = '''
from __future__ import annotations

{carried}

_env = None


def make_env():
    """Build this study's environment in the participant's own browser."""
    global _env
    _env = {build}
    return _env


def draw(_observation):
    """Paint the frame the environment drew. No study code is involved."""
    return [{{"op": "frame", "id": "env", "relative": True,
             "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}}]
'''


def bundle_for(source: Any, found: Derived) -> str:
    """Return the Python one browser runs for this environment.

    One generic bundle for every environment, because the environment is named rather
    than reimplemented. Compare ``examples/cogrid/env.py``, which carries two
    hand-written bundles of about two hundred lines each, one per execution, with the
    drawing written twice over.

    A class or a registered id becomes an import line. A factory is study code, so
    the factory's **own source** is carried into the bundle -- which is why it must
    import nothing of the study, and why that is checked before this is reached.
    """
    import functools

    if isinstance(source, (type, functools.partial)):
        root = found.build.split("(")[0]
        module, _, name = root.rpartition(".")
        carried = f"from {module} import {name}" if module else ""
        build = f"{name}({found.build.split('(', 1)[1]}" if module else found.build
        return _BUNDLE.format(carried=carried, build=build)
    import inspect
    import textwrap

    carried = textwrap.dedent(inspect.getsource(source))
    return _BUNDLE.format(carried=carried, build=f"{source.__name__}()")


# -- run it against real environments ------------------------------------------------


@dataclass(frozen=True)
class Probe:
    """One thing an author could hand to ``Game``, and how it is obtained.

    ``named`` returns **the thing itself** -- a class, a partial, or a factory function
    -- and never the built environment. The distinction matters: handing over a built
    environment is what an author must not have to do, because a built environment
    cannot travel to a browser.
    """

    what: str
    named: Callable[[], Any]


def _kitchen_factory() -> Any:
    """Build the Overcooked kitchen, as a study author's own factory would.

    This is the spelling that always works: the environment is configured with live
    reward objects, so it cannot travel as settings, and it does not have to. What
    travels is this function.
    """
    import contextlib
    import functools

    from cogrid.cogrid_env import CoGridEnv
    from cogrid.envs import registry
    from cogrid.envs.overcooked.agent import OvercookedAgent

    from examples.cogrid.env import kitchen_config

    identifier = "Overcooked-derive-probe"
    with contextlib.suppress(Exception):
        registry.register(
            environment_id=identifier,
            env_class=functools.partial(
                CoGridEnv,
                config=kitchen_config("cramped_room", 400),
                agent_class=OvercookedAgent,
            ),
        )
    return registry.make(identifier, render_mode="rgb_array")


def kitchen() -> Any:
    """Build the Overcooked kitchen, importing nothing but the environment package.

    The same kitchen as ``_kitchen_factory``, written so that it can travel. The one
    difference is that it reaches nothing of the study: every name it uses it imports
    itself, from a package a browser can install. That is the whole rule, and this
    function is what satisfying it looks like -- a study author's own env builder,
    with its configuration inline instead of imported.
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
        # The live object that stops a class-and-settings spelling from travelling,
        # and that costs nothing here: it is built where it is used.
        "rewards": [DeliveryReward(coefficient=1.0, common_reward=True)],
        "grid": {"layout": "overcooked_cramped_room_v0"},
        "scope": "overcooked",
        "max_steps": 600,
        "pickupable_types": ["onion", "onion_soup", "plate", "tomato", "tomato_soup"],
    }
    identifier = "Overcooked-travels"
    with contextlib.suppress(Exception):
        # Registering twice is refused, and registering once is all this needs.
        registry.register(
            environment_id=identifier,
            env_class=functools.partial(
                CoGridEnv, config=config, agent_class=OvercookedAgent
            ),
        )
    return registry.make(identifier, render_mode="rgb_array")


def probes() -> list[Probe]:
    """Return the environments to read, newest API surface first."""

    def mountain_car() -> Any:
        from gymnasium.envs.classic_control.mountain_car import MountainCarEnv

        return MountainCarEnv

    def registered() -> Any:
        import functools

        import gymnasium

        # What a registered id becomes now that the environment must be a callable.
        # A partial writes itself down, so nothing of the study travels. `render_mode`
        # is bound here, by the author, because the platform injects nothing into a
        # callable it was told takes no arguments.
        return functools.partial(
            gymnasium.make, "MountainCar-v0", render_mode="rgb_array"
        )

    def not_an_environment() -> Any:
        def looks_like_one() -> Any:
            """Return something with step and reset that is not an environment."""

            class Pretender:
                def reset(self, **_kwargs: Any) -> Any:
                    return None, {}

                def step(self, _action: Any) -> Any:
                    return None, 0.0, False, False, {}

            return Pretender()

        return looks_like_one

    def cartpole() -> Any:
        from gymnasium.envs.classic_control.cartpole import CartPoleEnv

        return CartPoleEnv

    return [
        Probe(
            'Game("cook", kitchen)  -- a self-contained factory (CoGrid Overcooked)',
            lambda: kitchen,
        ),
        Probe(
            'Game("cook", kitchen)  -- the same, importing the study\'s own config',
            lambda: _kitchen_factory,
        ),
        Probe(
            'Game("drive", partial(gymnasium.make, "MountainCar-v0"))  -- a partial',
            registered,
        ),
        Probe('Game("drive", MountainCarEnv)  -- a Gymnasium class', mountain_car),
        Probe('Game("balance", CartPoleEnv)  -- draws with pygame', cartpole),
        Probe(
            'Game("x", something)  -- has step and reset, is not an environment',
            not_an_environment,
        ),
    ]


def _report(probe: Probe) -> None:
    """Read one environment and print everything that came off it."""
    print(f"  {probe.what}")
    try:
        found = derive(probe.named())
    except (TypeError, ValueError, RuntimeError) as problem:
        print(f"    refused: {type(problem).__name__}: {problem}")
        print()
        return
    print(f"    api            {found.api}")
    print(f"    agents         {list(found.agents)}")
    print(f"    actions        {dict(found.actions)}")
    print(f"    fps            {found.fps}")
    print(f"    max_steps      {found.max_steps}")
    drawn = "yes" if found.draws else f"no -- {found.draw_blocked_by}"
    print(f"    draws itself   {drawn}")
    print(f"    keys           {dict(found.keys) if found.keys else 'not declared'}")
    print(f"    default action {found.default_action}")
    print(f"    requires       {list(found.requires)}")
    print(f"    rebuilt by     {found.build}")
    print(f"    in a browser   {'yes' if found.runs_in_a_browser else 'NO'}")
    for why in found.blocks:
        print(f"      - {why}")
    for ask in found.asks:
        print(f"    the study says {ask}")
    print()


def main() -> None:
    """Read every probe, then print the bundle one of them produces."""
    print("what MUG can read off an environment nobody wrote a specification for")
    print("=" * 78)
    for probe in probes():
        _report(probe)

    print("the browser bundle, generated (compare examples/cogrid/env.py)")
    print("=" * 78)
    print(bundle_for(kitchen, derive(kitchen)))


if __name__ == "__main__":
    main()
