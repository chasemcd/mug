"""A browser run is verified by re-executing it, so the environment must repeat.

The platform records a browser-run game by re-executing the reported actions and
matching every state hash. That is only ever evidence if the environment gives the
same trajectory from the same seed and the same actions. An environment that does
not is not slightly wrong: **every** participant's run is refused, at the end, with
nothing recorded, and the study looks broken to the person who played it.

Nothing tested that. The browser tests played one shortened round and read the
screen, which cannot tell a reproducible environment from an unreproducible one --
a single run always matches itself. This runs each shipped bundle twice in one
process and requires the two to agree, which is the whole property in one line.

It found a real fault the first time it ran: CoGrid 0.2.1 permutes which agent's
move resolves first on every step, and its numpy backend draws that permutation
from a fresh unseeded generator, so two chefs reaching for the same square were
separated by operating-system entropy. See ``examples.cogrid.env._pin_agent_priority``.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from mug.game.browser import BrowserGameSpec
from mug.game.determinism import state_hash
from mug.game.env import GymEnv

# Long enough that two agents contend. A run where nothing is contested cannot
# tell a seeded tiebreak from an unseeded one -- which is exactly why the browser
# test that pressed no keys passed against a broken environment.
_FRAMES = 120


def _browser_specs() -> list[tuple[str, BrowserGameSpec]]:
    """Return every shipped browser-run game, skipping the ones not installed."""
    found: list[tuple[str, BrowserGameSpec]] = []

    from examples.mountain_car.browser_env import mountain_car_browser_spec

    found.append(("mountain-car", mountain_car_browser_spec()))

    try:
        from examples.cogrid.env import overcooked_browser
    except Exception:  # pragma: no cover - the environment is an optional extra
        return found
    pytest.importorskip("cogrid", reason="uv pip install cogrid==0.3.2")
    found.append(("overcooked", overcooked_browser()))
    return found


_SPECS = _browser_specs()
_IDS = [name for name, _ in _SPECS]


def _legal(spec: BrowserGameSpec) -> list[int]:
    """Return the actions this game accepts, as the study itself declared them.

    A made-up action range is refused by the environment, and a game is only
    exercised by the moves a participant can actually make.
    """
    return sorted({*spec.action_bindings.values(), spec.default_action})


def _sequence(spec: BrowserGameSpec, *, seed: int) -> list[int]:
    """Return one repeatable but varied action sequence over this game's actions.

    Drawn from a seeded generator rather than written as a short cycle. The first
    version of this test cycled both seats through the actions in order, and the two
    chefs then moved so regularly that they never once reached for the same square
    -- so the tiebreak this test exists to check was never taken, and the test passed
    against the broken environment. Varied play contests things.
    """
    legal = _legal(spec)
    draw = random.Random(seed)
    return [draw.choice(legal) for _ in range(_FRAMES)]


def _run(spec: BrowserGameSpec, actions: list[int], partner: list[int]) -> list[str]:
    """Execute one bundle from its seed and return the per-frame state hashes.

    This is what ``mug.replay.verify._reference_run`` does when it checks a reported
    run, so a disagreement here is a run the server would refuse.
    """
    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)
    env = GymEnv(namespace["make_env"], seed=spec.seed)
    partner_acts = namespace.get("partner_acts") if spec.partner is not None else None
    env.reset()
    hashes: list[str] = []
    for index, action in enumerate(actions):
        if callable(partner_acts):
            partner_acts(partner[index])
        state = env.step(action)
        hashes.append(state_hash(state.observation).hex)
    return hashes


@pytest.mark.parametrize("name,spec", _SPECS, ids=_IDS)
def test_the_same_seed_and_actions_give_the_same_run_twice(
    name: str, spec: BrowserGameSpec
) -> None:
    """Two executions of one bundle agree frame for frame.

    Both executions are in this one process, which is the harder case and the real
    one: the server re-executes a run in a process that has already built the
    environment for other participants. An environment that carries state between
    constructions fails here.
    """
    actions = _sequence(spec, seed=1)
    partner = _sequence(spec, seed=2)

    first = _run(spec, actions, partner)
    second = _run(spec, actions, partner)

    assert len(first) == _FRAMES
    diverged = next(
        (at for at, (one, two) in enumerate(zip(first, second, strict=True), start=1)
         if one != two),
        None,
    )
    assert diverged is None, (
        f"{name} gave a different run the second time, first at frame {diverged}. "
        "A browser run of it can never be verified, so every participant's round "
        "is refused and nothing is recorded."
    )


@pytest.mark.parametrize("name,spec", _SPECS, ids=_IDS)
def test_a_run_is_the_consequence_of_its_actions(
    name: str, spec: BrowserGameSpec
) -> None:
    """A different action sequence gives a different run.

    Without this the first test passes for the worst possible reason: an
    environment that ignores what the participant does repeats perfectly.
    """
    steady = [spec.default_action] * _FRAMES
    varied = _sequence(spec, seed=1)
    partner = _sequence(spec, seed=2)

    assert _run(spec, steady, partner) != _run(spec, varied, partner), (
        f"{name} gave the same run for two different action sequences, so its "
        "state hashes say nothing about what was played"
    )
