"""Read a whole game activity off the environment a study named.

A study hands the platform the environment it trained against and nothing else. This
module is what makes that enough: it builds the environment once, reads what it is,
and returns the facts every other part of the platform needs.

    Game("cook", kitchen, runs="browser", seats={0: Human(), 1: Bot(chef)})

What is read, and what it replaces a study having to write:

===========================  ==================================================
derived                      read from
===========================  ==================================================
the environment API          the base class: ``gymnasium.Env``, PettingZoo
                             ``ParallelEnv``, or PettingZoo ``AECEnv``
the agents                   ``possible_agents``, so a study never keeps a map
                             from its own seat names to the environment's
the action set               ``action_space`` for each agent
the frame rate               ``metadata["render_fps"]``
the episode limit            ``spec.max_episode_steps``, or the environment's own
the drawing                  ``render_mode="rgb_array"``, asked by drawing one
the key bindings             ``get_keys_to_action``, where an environment follows
                             the ``gymnasium.utils.play`` convention
the packages a browser needs  the distribution that provides the environment,
                             pinned at the version installed here
===========================  ==================================================

**The pin matters more than it looks.** A browser run is verified by the server
re-executing it, so the two must step identically. Written by hand in two places, the
browser pin and the server package were once allowed to drift -- the browser asked for
one version while the server had another -- and the result is that every honest run is
refused. Derived from the installed environment, one cannot differ from the other.

**Nothing here is environment-specific.** The platform recognizes two standard APIs;
it implements neither, and it holds no knowledge of any particular environment. Both
packages are optional (the ``game`` extra), because a study of forms and conversations
runs no environment at all.
"""

from __future__ import annotations

import ast
import functools
import importlib
import importlib.metadata as metadata
import inspect
import sys
import textwrap
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

# What a game activity is given: something that takes no arguments and returns one of
# the three environment APIs. An environment class is one. So is
# ``functools.partial(gymnasium.make, "MountainCar-v0")``. So is a study's own
# ``def kitchen(): ...``.
#
# It takes **no arguments**, and that is the point. Whatever an environment needs to be
# built is bound inside the callable, by the author, where they are already
# constructing it -- including ``render_mode="rgb_array"`` if they want the
# environment's own frames. So the platform passes nothing in, and a configuration
# holding live objects needs no written form to travel.
EnvFactory = Callable[[], Any]

# What Pyodide ships itself, so a browser run needs no wheel for it. Anything else must
# be a pure-Python wheel, which is a property of the installed distribution and is read
# rather than assumed.
PYODIDE_CARRIES: Final[frozenset[str]] = frozenset(
    {"numpy", "scipy", "pandas", "micropip", "packaging", "setuptools"}
)

# A file suffix that says a distribution holds compiled code. Compiled code needs a
# wheel built for Pyodide's own platform, which a study cannot assume exists.
COMPILED: Final[tuple[str, ...]] = (".so", ".pyd", ".dylib")

# The pygame key codes ``gymnasium.utils.play`` speaks, and the browser key names the
# platform's bindings are written in. A code that is not here is reported rather than
# guessed: a key bound to the wrong action is worse than a key bound to nothing.
BROWSER_KEY: Final[Mapping[int, str]] = {
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


class EnvironmentRefused(TypeError):
    """What a study named cannot be read as an environment."""


@dataclass(frozen=True)
class Derived:
    """What one game activity needs, read off the environment itself.

    ``blocks`` is why this environment cannot step in a participant's browser, and it
    is empty when it can. It exists so the answer arrives while an author reads their
    own code, rather than as a download that fails in front of a participant.

    ``asks`` is what the environment cannot say and a study must. It is short, and
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

    @property
    def takes_turns(self) -> bool:
        """Say whether the agents act one at a time rather than together."""
        return self.api == "pettingzoo-aec"


def derive(source: EnvFactory, /) -> Derived:
    """Read one whole game activity off the environment a study named.

    ``source`` takes no arguments and returns a ``gymnasium.Env``, a PettingZoo
    ``ParallelEnv``, or a PettingZoo ``AECEnv``. Anything else is refused, and so is a
    callable that returns something which is not one of the three.

    There is no duck-typed fallback. Which API an environment is decides how every
    other reading below is understood -- which agents there are, how an action is
    passed, whether a turn is taken -- so an object that merely answers to ``step`` and
    ``reset`` is refused rather than guessed at. A study with an environment of its own
    wraps it, which is a small wrapper, and the platform then has one path that is
    always tested.
    """
    built, build, module = _build(source)
    api = _api_of(built)
    _refuse_one_agent_that_is_really_several(built, api)
    agents = _agents_of(built, api)
    keys, default = _keys_of(built)
    requires, blocks = _travels(source, module)
    draws, why = _draws(built)
    return Derived(
        api=api,
        build=build,
        requires=requires,
        agents=agents,
        actions={agent: str(_action_space_of(built, agent, api)) for agent in agents},
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


def env_bases() -> tuple[type, ...]:
    """Return the environment base classes, for the ones that are installed.

    A deployment may have Gymnasium and not PettingZoo, or the other way round, so the
    check is built from what is here. One with neither cannot read any environment and
    says so, rather than accepting anything that answers to ``step``.
    """
    found = [
        _maybe("gymnasium", "Env"),
        _maybe("pettingzoo.utils.env", "ParallelEnv"),
        _maybe("pettingzoo.utils.env", "AECEnv"),
    ]
    bases = tuple(one for one in found if isinstance(one, type))
    if not bases:
        raise EnvironmentRefused(
            "neither gymnasium nor pettingzoo is installed, so no environment can be "
            'read: install the game extra (pip install "mug[game]")'
        )
    return bases


def _build(source: EnvFactory) -> tuple[Any, str, str]:
    """Build the environment once, and return the call that rebuilds it elsewhere.

    It is built because almost nothing useful is on the class: ``possible_agents``,
    ``action_space``, and the episode bound are all set in ``__init__``. So the platform
    builds one when the study is written, reads it, and throws it away -- which is also
    the moment an environment that cannot be built at all says so, rather than at the
    first participant.
    """
    if isinstance(source, str):
        raise EnvironmentRefused(
            f"a game activity is given something callable, not the registered id "
            f"{source!r}: write functools.partial(gymnasium.make, {source!r}) instead, "
            "so that what builds an environment is one kind of thing everywhere"
        )
    if not callable(source):
        raise EnvironmentRefused(
            "a game activity names something that builds its environment and takes no "
            "arguments: an environment class, "
            'functools.partial(gymnasium.make, "SomeEnv-v0"), or a function of your '
            f"own. A {type(source).__name__} is none of those."
        )
    built = source()
    _refuse_a_thing_that_is_not_an_environment(source, built)
    return built, _rebuilt_by(source), _module_of(source)


def _refuse_a_thing_that_is_not_an_environment(source: Any, built: Any) -> None:
    """Refuse anything that is not one of the environment APIs.

    Checked on what was **returned**, and by base class rather than by what it answers
    to. An object with ``step`` and ``reset`` may be an environment, or a wrapper, or a
    replay, or a mistake.
    """
    if isinstance(built, env_bases()):
        return
    named = getattr(source, "__qualname__", None) or type(source).__name__
    raise EnvironmentRefused(
        f"{named} returned a {type(built).__module__}.{type(built).__name__}, which is "
        "not a gymnasium.Env, a pettingzoo ParallelEnv, or a pettingzoo AECEnv. Wrap "
        "it in one of the three -- the wrapper is small, and it is what lets the "
        "platform read the agents, the actions, and the drawing off it."
    )


def _refuse_one_agent_that_is_really_several(built: Any, api: str) -> None:
    """Refuse an environment that says one agent and takes an action for each of many.

    A ``gymnasium.Env`` acts one agent, and its action space says what that one action
    is. An environment declaring ``gymnasium.Env`` with a **dictionary** action space
    over named agents is not that: it wants one action per agent, keyed by agent.

    Read as it declares itself, it derives as one agent whose action is a whole
    dictionary. Nothing about that is playable -- a key cannot bind to it and the loop
    would hand it an integer -- and every one of those failures happens later, in front
    of a participant. ``slime_volleyball.SlimeVolleyEnv`` is exactly this, and it is
    widely used, so it is worth saying rather than deriving something wrong.
    """
    if api != "gymnasium":
        return
    space = getattr(built, "action_space", None)
    named = getattr(space, "spaces", None)
    if not isinstance(named, dict) or len(cast("dict[Any, Any]", named)) < 2:
        return
    agents = ", ".join(repr(one) for one in cast("dict[Any, Any]", named))
    raise EnvironmentRefused(
        f"{type(built).__module__}.{type(built).__name__} declares gymnasium.Env, "
        f"which acts one agent, and its action space asks for one action each for "
        f"{agents}. It is a multi-agent environment wearing a single-agent base class, "
        "so nothing can be read off it correctly: declare it a pettingzoo ParallelEnv "
        "and give it possible_agents. The wrapper is a few lines, and it is what lets "
        "the platform seat those agents."
    )


def _rebuilt_by(source: Any) -> str:
    """Return the call that rebuilds this environment somewhere else.

    A class and a ``functools.partial`` both write themselves down: a class is its own
    import path, and a partial is its function's path with its bound arguments. A
    study's own function writes itself as a call, and its **source** is what travels.
    """
    if isinstance(source, functools.partial):
        where = f"{source.func.__module__}.{source.func.__qualname__}"
        written = [repr(one) for one in source.args]
        written += [f"{key}={value!r}" for key, value in source.keywords.items()]
        return f"{where}({', '.join(written)})"
    where = getattr(source, "__qualname__", type(source).__name__)
    return f"{_module_of(source)}.{where}()"


def _module_of(source: Any) -> str:
    """Return the module the callable came from, following a partial to its function."""
    if isinstance(source, functools.partial):
        return str(source.func.__module__)
    return str(getattr(source, "__module__", ""))


def _api_of(built: Any) -> str:
    """Name the environment API from what the environment actually inherits."""
    for module, name, api in (
        # PettingZoo first: the order is fixed so that one deployment's answer is every
        # deployment's, whichever packages happen to be installed.
        ("pettingzoo.utils.env", "ParallelEnv", "pettingzoo-parallel"),
        ("pettingzoo.utils.env", "AECEnv", "pettingzoo-aec"),
        ("gymnasium", "Env", "gymnasium"),
    ):
        base = _maybe(module, name)
        if base is not None and isinstance(built, base):
            return api
    # Unreachable: the base-class refusal has already run. It is here so that a change
    # to one and not the other fails rather than naming an api wrongly.
    raise AssertionError("an environment passed the base-class check and matched none")


def _maybe(module: str, name: str) -> Any:
    """Return one class if its package is installed, and nothing if it is not."""
    try:
        return getattr(importlib.import_module(module), name)
    except Exception:
        return None


def _agents_of(built: Any, api: str) -> tuple[Any, ...]:
    """Return the agents that act in this environment, in the environment's order.

    This is what replaces the seat-to-index map every multi-agent study kept by hand.
    A mistyped seat then becomes something the platform can refuse while the author is
    reading their own code, rather than a ``KeyError`` on a participant's first frame.
    """
    if api == "gymnasium":
        return (SINGLE_AGENT,)
    for name in ("possible_agents", "agents"):
        found = getattr(built, name, None)
        if found:
            return tuple(found)
    # A parallel environment that names its agents only once it has been reset.
    reset = getattr(built, "reset", None)
    if callable(reset):
        try:
            reset(seed=0)
        except Exception:
            return (SINGLE_AGENT,)
        found = getattr(built, "agents", None)
        if found:
            return tuple(found)
    return (SINGLE_AGENT,)


# What the one agent of a single-agent environment is called. Gymnasium names none, and
# a seating has to name something.
SINGLE_AGENT: Final[str] = "agent"


def _action_space_of(built: Any, agent: Any, api: str) -> Any:
    """Return one agent's action space, whichever way this API spells it."""
    space = getattr(built, "action_space", None)
    if callable(space) and api != "gymnasium":
        try:
            return space(agent)
        except TypeError:
            return space
    return space


def _keys_of(built: Any) -> tuple[dict[str, int] | None, int | None]:
    """Read the key bindings the environment declares, if it declares any.

    ``gymnasium.utils.play`` has a convention for this: ``get_keys_to_action`` returns
    a map from a tuple of held keys to an action, and the empty tuple is what the
    environment does when nothing is held. That is the platform's own binding shape,
    chords and a default action included, so an environment following it needs no
    bindings written at all. The convention also means **held** keys, so a study that
    takes these takes ``held_actions=True`` with them.
    """
    read = getattr(getattr(built, "unwrapped", built), "get_keys_to_action", None)
    if not callable(read):
        return None, None
    try:
        declared = cast("Mapping[Any, int]", read())
    except Exception:
        return None, None
    bindings: dict[str, int] = {}
    default: int | None = None
    for held, action in declared.items():
        codes = cast("tuple[int, ...]", held if isinstance(held, tuple) else (held,))
        if not codes:
            default = int(action)
            continue
        named = [BROWSER_KEY.get(int(code)) for code in codes]
        if any(one is None for one in named):
            continue
        bindings["+".join(str(one) for one in named)] = int(action)
    return bindings or None, default


def _fps_of(built: Any) -> int | None:
    """Return the frame rate the environment says it draws at.

    ``render_fps`` is the one key read, because it is the one Gymnasium specifies. An
    environment that declares nothing there declares nothing at all as far as this is
    concerned, and the rate falls to the platform's own default -- or to the ``fps=``
    the study wrote, which outranks both.
    """
    declared = cast("Mapping[str, Any]", getattr(built, "metadata", None) or {})
    rate = declared.get("render_fps")
    return int(rate) if rate else None


def _max_steps_of(built: Any) -> int | None:
    """Return the episode limit, from wherever this environment keeps it."""
    limit = getattr(getattr(built, "spec", None), "max_episode_steps", None)
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
    declaration and no to the question, and the question is the one that matters -- the
    Gymnasium classic-control environments are exactly that case, because they draw
    with pygame.
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
    verifies a browser run by re-executing it, so the two step identically only if the
    pin is the installed version rather than a number somebody typed.

    Where the roots come from depends on what the study named. A class or a partial
    comes from its own module, so nothing of the study travels. A study's own function
    is study code carried by its source, so what has to be installed is what the
    **function imports** -- and one that imports the study itself is refused, because a
    participant's browser cannot install the study.
    """
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


def _cannot_travel(name: str) -> str | None:
    """Say why one distribution cannot be installed in a participant's browser."""
    if name in PYODIDE_CARRIES:
        return None
    try:
        found = metadata.distribution(name).files
    except metadata.PackageNotFoundError:
        return None
    files = cast("Sequence[Any]", found) if found else ()
    compiled = sorted(
        {str(one.name) for one in files if str(one.name).endswith(COMPILED)}
    )
    if not compiled:
        return None
    return (
        f"{name} holds compiled code ({compiled[0]} and {len(compiled) - 1} more), so "
        "a participant's browser cannot install it: run this activity on the server, "
        "or name an environment that is pure Python"
    )


def _refuse_local(source: Any, local: Sequence[str]) -> str:
    """Say that what builds the environment reaches code a browser cannot install."""
    named = ", ".join(local)
    if isinstance(source, (type, functools.partial)):
        return (
            f"the environment comes from {named}, which is not an installed "
            "distribution, so a browser run has nothing to install: publish it, or "
            "name a class from a package that is installed"
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

    A factory that builds an environment is usually a few imports and a constructor, so
    reading its imports is enough to know what a browser has to install. It is also how
    a factory that reaches the study's own code is caught.

    One limit is worth knowing. Whether a root is installable is asked of
    ``packages_distributions()``, which maps a top-level module to whatever distribution
    ships it -- and a distribution may ship a generic name. On this machine ``tests``
    maps to ``slimevb``, because that package ships a top-level ``tests`` module. So a
    factory importing a study package whose name a dependency also claims is judged
    installable when it is not. It is a false negative rather than a false alarm: the
    failure then arrives as a browser import error, which is what the check exists to
    avoid, so a study package should not be named after something on PyPI.
    """
    try:
        text = inspect.getsource(source)
    except (OSError, TypeError):
        return set()
    try:
        tree = ast.parse(textwrap.dedent(text))
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        found.update(_imported_roots(node))
    return found


def _imported_roots(node: ast.AST) -> list[str]:
    """Return the root packages one statement imports, if it imports anything."""
    if isinstance(node, ast.Import):
        return [alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module and not node.level:
        return [node.module.split(".")[0]]
    return []


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
            "keys= : which key is which action. Neither API says that, and this "
            "environment does not follow the gymnasium.utils.play convention."
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
            "seats= : which agent each player takes. It is a study's most "
            "consequential decision, so it is written rather than derived."
        )
    if not draws:
        asks.append(
            "render= : this environment hands over no frame, so the activity needs a "
            "drawing of its own."
        )
    return tuple(asks)


# -- the browser bundle -------------------------------------------------------------

# The generic bundle one browser runs. There is one of these for every environment,
# because the environment is named rather than reimplemented: it replaces the
# hand-written Python each browser study used to ship, one copy per execution.
_BUNDLE: Final[str] = '''
from __future__ import annotations

{carried}

_env = None


def make_env():
    """Build this study's environment in the participant's own browser."""
    global _env
    _env = {build}
    return _env
'''


def bundle_for(source: EnvFactory, found: Derived) -> str:
    """Return the Python one browser runs to rebuild this environment.

    A class or a registered call becomes an import line, so nothing of the study
    travels. A study's own function is study code, so the function's **own source** is
    carried -- which is why it must import nothing of the study, and why that is
    checked before this is reached (``Derived.blocks``).
    """
    if isinstance(source, (type, functools.partial)):
        root = found.build.split("(")[0]
        module, _, name = root.rpartition(".")
        carried = f"from {module} import {name}" if module else ""
        build = f"{name}({found.build.split('(', 1)[1]}" if module else found.build
        return _BUNDLE.format(carried=carried, build=build)
    carried = textwrap.dedent(inspect.getsource(source))
    return _BUNDLE.format(carried=carried, build=f"{source.__name__}()")


__all__ = [
    "BROWSER_KEY",
    "COMPILED",
    "PYODIDE_CARRIES",
    "SINGLE_AGENT",
    "Derived",
    "EnvFactory",
    "EnvironmentRefused",
    "bundle_for",
    "derive",
    "env_bases",
]
