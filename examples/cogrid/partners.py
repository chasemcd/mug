"""The partners a participant cooks with, and the seam they satisfy.

Each partner has one method, ``decide(observation)``, which returns a discrete
action. The platform holds that seam and nothing else; what an observation means
in a kitchen, and what a good move is, is the study's own business and lives here.

The two kinds of partner need different things, and the difference is the point:

- the **trained** partner needs only its own seat's observation, which is exactly
  what the platform hands a seat;
- a **planning** partner reads the kitchen -- the grid, the pots, where the other
  chef is standing. That is not in an observation, so it names a ``sees`` and the loop
  shows it the environment it is stepping (``the_kitchen``).

Three partners are written, because the study that uses them asks a participant to
compare them. They differ in a way a participant can feel:

- ``exported_partner`` is the trained network the legacy study played against. It
  is scored by ``onnxruntime`` from the observation CoGrid already produced.
- ``scripted_chef`` works the whole kitchen: it fetches onions, fills the pot,
  plates the soup, and delivers it. It gets in the way, because it goes wherever
  the next job is.
- ``station_keeper`` stays near the pot and only does the jobs that come to it. It
  is easier to work around and slower on its own.

None of them learns, and none can see what the participant is about to do. That is
what the debrief tells the participant, and it is true of all three.

Each takes ``decide_every``: how many frames pass between one decision and the
next. A partner that decided on all thirty frames a second would change its mind
faster than a person could read it, so the kitchen's partners decide every fifth
frame, as the legacy study's did, and stand still on the four frames between. A
kitchen is a grid: a partner that repeated one step of a walk five times would walk
five squares and arrive past whatever it was going to.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from examples.cogrid.env import PARTNER_DECIDES_EVERY, chef_at
from mug.casting import OnnxPolicy
from mug.casting.types import OnnxPreprocessing
from mug.game.controllers import HeuristicController, OnnxController

# The trained policy this study ships, beside the study that plays it.
MODEL_PATH = str(
    Path(__file__).resolve().parent
    / "assets/overcooked/models/cogrid-0.2.1-cramped-room.onnx"
)

# The cardinal action set, as CoGrid orders it.
MOVE_UP, MOVE_DOWN, MOVE_LEFT, MOVE_RIGHT, PICKUP_DROP, TOGGLE, NOOP = range(7)

_TOWARDS = {
    (-1, 0): MOVE_UP,
    (1, 0): MOVE_DOWN,
    (0, -1): MOVE_LEFT,
    (0, 1): MOVE_RIGHT,
}

# Which way a chef faces after each move, as CoGrid numbers the four directions.
_FACING = {MOVE_RIGHT: 0, MOVE_DOWN: 1, MOVE_LEFT: 2, MOVE_UP: 3}

# How many onions make one soup.
_POT_HOLDS = 3


def _free(env: Any, cell: tuple[int, int]) -> bool:
    """Return whether a chef can stand on one square.

    A counter, a pot, a stack, and the other chef all block the way. A partner that
    did not check would walk into the person it works with and stay there, which is
    what a study sees as a partner that stopped helping.
    """
    row, column = cell
    if not (0 <= row < env.grid.height and 0 <= column < env.grid.width):
        return False
    if env.grid.get(row, column) is not None:
        return False
    return all(
        (int(chef.pos[0]), int(chef.pos[1])) != cell
        for chef in env.grid.grid_agents.values()
    )


def _neighbours(cell: tuple[int, int]) -> list[tuple[tuple[int, int], int]]:
    """Return each square beside one, and the move that reaches it."""
    return [
        ((cell[0] + step[0], cell[1] + step[1]), move)
        for step, move in _TOWARDS.items()
    ]


def _routes(env: Any, start: tuple[int, int]) -> dict[tuple[int, int], tuple[int, int]]:
    """Return, for every square the chef can walk to, the first move and the cost.

    A kitchen is small and full of counters, so the way to a job is often not the
    way the crow flies. Walking the whole floor once a frame is cheap here and it is
    what makes the difference between a partner that works and one that presses
    itself against a counter for the rest of the round.
    """
    found: dict[tuple[int, int], tuple[int, int]] = {}
    queue = [(start, 0, -1)]
    seen = {start}
    while queue:
        cell, cost, first = queue.pop(0)
        for beside, move in _neighbours(cell):
            if beside in seen or not _free(env, beside):
                continue
            seen.add(beside)
            opening = move if first < 0 else first
            found[beside] = (opening, cost + 1)
            queue.append((beside, cost + 1, opening))
    return found


def _places(env: Any, kind: str) -> list[tuple[int, int]]:
    """Return every square holding a thing of one kind, by the name it goes by."""
    return [
        (int(item.pos[0]), int(item.pos[1]))
        for item in env.grid.grid
        if item is not None
        and getattr(item, "pos", None) is not None
        and type(item).__name__ == kind
    ]


def _at(item: Any) -> tuple[int, int]:
    """Return one thing's square."""
    return (int(item.pos[0]), int(item.pos[1]))


def _is_ready(pot: Any) -> bool:
    """Return whether a pot holds soup that has finished cooking."""
    return len(pot.objects_in_pot) >= _POT_HOLDS and int(pot.cooking_timer) == 0


class Chef:
    """A partner that walks to a job and does it.

    ``reach`` is how far it will go for a job. A partner that will go anywhere
    works the whole kitchen; one that will not go far stays at its station.

    **What the job is and how to get there are two questions.** ``squares_for``
    answers the first for a job it is given a name for, ``recipe`` answers it from
    what the chef is holding, and ``towards`` answers the second for either. That
    is what lets one planner serve both a scripted partner, which chooses its own
    job by the recipe, and a language model, which chooses the job and leaves the
    walking to this.
    """

    def __init__(self, reach: int, *, fetches: bool = True) -> None:
        self._reach = reach
        self._fetches = fetches

    def decide(self, env: Any, seat: Any) -> int:
        """Return this partner's action for one frame of one kitchen."""
        chef = chef_at(env, seat)
        if chef is None:
            return NOOP
        return self.towards(env, chef, self.recipe(env, chef))

    def towards(self, env: Any, chef: Any, jobs: list[tuple[int, int]]) -> int:
        """Return one move that carries the chef towards a job, or does it.

        A job with no square is a job with nothing to do -- plating a soup nobody
        has cooked -- and the chef stands where it is. That is the right answer and
        it is also legible: a partner waiting at the pot is waiting for the soup.
        """
        if not jobs:
            return NOOP
        here = (int(chef.pos[0]), int(chef.pos[1]))

        # Standing beside the job already: face it, then use it.
        for job in jobs:
            for beside, move in _neighbours(here):
                if beside == job:
                    return PICKUP_DROP if chef.dir == _FACING[move] else move

        return self._walk(env, here, jobs)

    def _walk(
        self, env: Any, here: tuple[int, int], jobs: list[tuple[int, int]]
    ) -> int:
        """Return the first move of the shortest walk to a square beside a job."""
        routes = _routes(env, here)
        best: tuple[int, int] | None = None
        for job in jobs:
            for beside, _move in _neighbours(job):
                found = routes.get(beside)
                if found is None or found[1] > self._reach:
                    continue
                if best is None or found[1] < best[1]:
                    best = found
        return NOOP if best is None else best[0]

    def recipe(self, env: Any, chef: Any) -> list[tuple[int, int]]:
        """Return where this partner would go next, given what it is holding.

        The order is the whole recipe: carry what you hold to where it goes, and
        with empty hands fetch what the pots need. A partner that only knew "get an
        onion" filled the pot and then stood in front of it with a fourth onion for
        the rest of the round.
        """
        carrying = chef.inventory[0] if chef.inventory else None
        held = type(carrying).__name__ if carrying is not None else ""
        cooked, room = self._pots(env)

        if held == "OnionSoup":
            return _places(env, "DeliveryZone")
        if held == "Plate":
            return cooked
        if held == "Onion":
            return room
        if not self._fetches:
            # A partner that does not fetch waits for the work to arrive. With
            # empty hands there is nothing at its station to do.
            return []
        if cooked:
            return _places(env, "PlateStack")
        return _places(env, "OnionStack") if room else []

    def squares_for(self, env: Any, chef: Any, job: str) -> list[tuple[int, int]]:
        """Return where a **named** job is, for a partner that was told which one.

        This is the whole of what a job means, and every line of it is a fact about
        Overcooked -- which is why it is in the study and not in the platform. A
        name it does not know is nowhere, so the chef stands still rather than
        walking somewhere nobody asked for.
        """
        cooked, room = self._pots(env)
        if job == "FETCH_ONION":
            return _places(env, "OnionStack")
        if job == "FILL_POT":
            return room
        if job == "FETCH_PLATE":
            return _places(env, "PlateStack")
        if job == "PLATE_SOUP":
            return cooked
        if job == "DELIVER":
            return _places(env, "DeliveryZone")
        return []

    def _pots(self, env: Any) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        """Return the pots whose soup is ready, and the pots with room in them."""
        pots = [item for item in env.grid.grid if type(item).__name__ == "Pot"]
        return (
            [_at(pot) for pot in pots if _is_ready(pot)],
            [_at(pot) for pot in pots if len(pot.objects_in_pot) < _POT_HOLDS],
        )


def the_kitchen(env: Any, seat: str) -> tuple[Any, str]:
    """Return what a planning partner is shown: the kitchen, and which chef it is.

    This is the study's ``SeatView``. The platform hands a seat its own observation,
    which is right for a policy and not enough for a planner: a route through a
    kitchen is a fact about the grid, the pots, and where the other chef is standing.
    The loop calls this on the environment it is stepping, so a partner reads the
    kitchen this participant is cooking in and never another's.
    """
    return env, seat


def _planning(reach: int, *, fetches: bool, decide_every: int) -> HeuristicController:
    """Return a planning partner on the seat seam, shown the kitchen it stands in."""
    chef = Chef(reach=reach, fetches=fetches)
    return HeuristicController(
        lambda seen: chef.decide(*seen),
        decide_every=decide_every,
        between=NOOP,
        sees=the_kitchen,
    )


def scripted_chef(
    *, decide_every: int = PARTNER_DECIDES_EVERY
) -> HeuristicController:
    """Return the partner that works the whole kitchen.

    It fetches, it cooks, and it delivers, so it can run the kitchen on its own.
    It also goes wherever the next job is, which is where the participant often
    wants to be.

    ``decide_every`` is the frame skip -- how many frames pass between one decision
    and the next.
    """
    return _planning(99, fetches=True, decide_every=decide_every)


def station_keeper(
    *, decide_every: int = PARTNER_DECIDES_EVERY
) -> HeuristicController:
    """Return the partner that stays near the pot and waits for work to arrive.

    It carries what it is given: an onion into the pot, a soup to the serving
    square. It never walks to a stack, so it takes nothing the participant was
    going for, and it delivers nothing until the participant brings it something.
    """
    return _planning(99, fetches=False, decide_every=decide_every)


def exported_partner(
    *,
    model_path: str = MODEL_PATH,
    policy_ref: str = "cogrid-cramped-room@1",
    input_name: str = "input",
    output_name: str = "logits",
    decide_every: int = PARTNER_DECIDES_EVERY,
    seed: int = 20260728,
) -> OnnxController:
    """Return the trained partner: the network the legacy study played against.

    It needs no kitchen, only its own seat's observation, which is what the platform
    hands a seat: this is a policy, and a policy is trained on an observation. The
    features are the ones CoGrid already produced for that seat, so nothing here
    re-derives a feature vector -- reading them anywhere else is how a study ends up
    scoring the wrong 892 numbers.

    The action is **drawn** from the softmax of the scores rather than taken as the
    greatest, which is what the legacy study did. A kitchen is full of states where
    two moves score alike, and a partner that always broke that tie the same way
    walked the same circle for a whole round. The draw is seeded, so a run repeats.

    It needs ``onnxruntime``: ``uv pip install onnxruntime``.
    """
    policy = OnnxPolicy(
        policy_ref=policy_ref,
        preprocessing=OnnxPreprocessing(transform="flatten"),
        selection_mode="sample",
        temperature=1.0,
    )
    draws = random.Random(seed)

    def infer(seen: Any) -> list[float]:
        import numpy
        import onnxruntime

        if seen is None:
            # A frame with no observation for this seat is one the partner cannot
            # score. Returning nothing is refused by the controller, which is
            # right: a seat must not invent an action from an absent observation.
            return []
        flat = numpy.asarray(seen, dtype=numpy.float32).reshape(1, -1)
        scores = _session(model_path, onnxruntime).run(
            [output_name], {input_name: flat}
        )[0]
        return [float(one) for one in scores[0]]

    # The network was trained to act once per environment step, so the frames it
    # does not decide on are idle rather than a repeat of its last move. Repeating
    # one step of a walk five times walks five squares, and a partner that did that
    # would arrive past every pot it was going to.
    return OnnxController(
        policy,
        infer,
        draw=draws.random,
        decide_every=decide_every,
        between=NOOP,
    )


_SESSIONS: dict[str, Any] = {}


def _session(model_path: str, runtime: Any) -> Any:
    """Return the inference session for one model, loaded once."""
    if model_path not in _SESSIONS:
        _SESSIONS[model_path] = runtime.InferenceSession(model_path)
    return _SESSIONS[model_path]


__all__ = [
    "MODEL_PATH",
    "Chef",
    "exported_partner",
    "scripted_chef",
    "station_keeper",
    "the_kitchen",
]
