"""One two-seat environment, one partner policy, and both execution modes.

Fixtures 2 and 3 ask for a person and a policy in one environment, and fixture 3
asks for it **in both browser and server execution**. A claim like that is only
worth anything if the two modes really run the same environment and the same
policy. So both are written once, here, as source:

- ``ENV_SOURCE`` is the environment core. It steps a mapping of every seat's
  action, which is what the server-authoritative loop gives it.
- ``POLICY_SOURCE`` is the partner's decision function, from an observation to an
  action.

The browser bundle is those two plus a thin wrapper that runs the policy *inside
the bundle*, so the partner decides in the participant's own browser. The server
mode executes the same two strings and seats the policy as a ``Bot``. Neither mode
gets its own copy, so the two cannot drift apart while the fixture still passes.

The environment is deliberately small and deliberately deterministic. A browser
run is verified by re-execution, so a partner that decided differently on the
server than it did in the browser would fail verification -- which is the reason a
browser-side policy must be deterministic, and a fact this fixture states rather
than assumes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mug.game.browser import BrowserGameSpec
from mug.game.controllers import HeuristicController
from mug.game.multiseat import MultiStepResult

# The seats. The person takes ``harvester``; the policy takes ``partner``.
YOU = "harvester"
PARTNER = "partner"

ENV_SOURCE = '''
GRID = 7
STAY, UP, DOWN, LEFT, RIGHT = 0, 1, 2, 3, 4
_MOVES = {STAY: (0, 0), UP: (0, -1), DOWN: (0, 1), LEFT: (-1, 0), RIGHT: (1, 0)}
SEATS = ("harvester", "partner")


class Harvest:
    """Two seats gather from one field. Every seat moves on every frame."""

    def __init__(self, length=12):
        self._length = length
        self.frame = 0
        self.places = {"harvester": (0, 0), "partner": (GRID - 1, GRID - 1)}
        self.scores = {"harvester": 0, "partner": 0}
        self.crop = (GRID // 2, GRID // 2)

    def observe(self):
        """Return the state every seat sees. Both seats see the same field."""
        return {
            "frame": self.frame,
            "places": {seat: list(self.places[seat]) for seat in SEATS},
            "scores": dict(self.scores),
            "crop": list(self.crop),
        }

    def restart(self):
        """Return the field to its start, and report what a seat first sees."""
        self.frame = 0
        self.places = {"harvester": (0, 0), "partner": (GRID - 1, GRID - 1)}
        self.scores = {"harvester": 0, "partner": 0}
        self.crop = (GRID // 2, GRID // 2)
        return self.observe()

    def advance(self, actions):
        """Move every seat, award the crop, and say whether the run has ended."""
        self.frame += 1
        for seat in SEATS:
            dx, dy = _MOVES.get(int(actions.get(seat, STAY)) % 5, (0, 0))
            x, y = self.places[seat]
            self.places[seat] = (
                min(GRID - 1, max(0, x + dx)),
                min(GRID - 1, max(0, y + dy)),
            )
        rewards = {seat: 0.0 for seat in SEATS}
        for seat in SEATS:
            if self.places[seat] == self.crop:
                self.scores[seat] += 1
                rewards[seat] = 1.0
                # The next crop is a fixed walk from the last one, so the whole
                # field is a function of the seats' actions and nothing else.
                cx, cy = self.crop
                self.crop = ((cx + 3) % GRID, (cy + 2) % GRID)
                break
        return rewards, self.frame >= self._length
'''

POLICY_SOURCE = '''
def partner_action(observation):
    """Walk toward the crop, horizontally first. It never stands still."""
    x, y = observation["places"]["partner"]
    cx, cy = observation["crop"]
    if x != cx:
        return 4 if cx > x else 3
    if y != cy:
        return 2 if cy > y else 1
    return 0
'''

# The wrapper the browser runs. It is the only part that differs between the two
# modes, and all it does is decide the partner's action before stepping the core.
_BROWSER_WRAPPER = '''

class BrowserHarvest:
    """The browser's view: one action in, because the partner decides in here."""

    def __init__(self):
        self._core = Harvest()
        self.partner_actions = []

    def reset(self, seed=None):
        self.partner_actions = []
        return self._core.restart(), {}

    def step(self, action):
        theirs = partner_action(self._core.observe())
        self.partner_actions.append(theirs)
        rewards, done = self._core.advance({"harvester": action, "partner": theirs})
        return (
            self._core.observe(),
            rewards["harvester"],
            done,
            False,
            {"partner_action": theirs, "partner_score": self._core.scores["partner"]},
        )


def make_env():
    """Build the environment the participant browser steps."""
    return BrowserHarvest()


def draw(observation):
    """Return the surface commands for one observed frame."""
    cell = 1.0 / GRID
    commands = [
        {"op": "rect", "id": "field", "relative": True, "color": "#eef3e2",
         "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    ]
    cx, cy = observation["crop"]
    commands.append(
        {"op": "circle", "id": "crop", "relative": True, "color": "#d4af37",
         "x": (cx + 0.5) * cell, "y": (cy + 0.5) * cell, "radius": cell * 0.3}
    )
    colors = {"harvester": "#2d6cdf", "partner": "#df6c2d"}
    for seat in SEATS:
        x, y = observation["places"][seat]
        commands.append(
            {"op": "rect", "id": "seat-" + seat, "relative": True,
             "color": colors[seat], "x": x * cell + cell * 0.15,
             "y": y * cell + cell * 0.15, "w": cell * 0.7, "h": cell * 0.7}
        )
    return commands
'''

BROWSER_BUNDLE = ENV_SOURCE + POLICY_SOURCE + _BROWSER_WRAPPER


def browser_spec() -> BrowserGameSpec:
    """Return the browser-execution specification, with the partner in the bundle."""
    return BrowserGameSpec(
        channel_key="harvest",
        source_bundle=BROWSER_BUNDLE,
        requires=(),
        action_bindings={"ArrowUp": 1, "ArrowDown": 2, "ArrowLeft": 3, "ArrowRight": 4},
        default_action=0,
        seed=11,
        fps=0,
        max_steps=32,
        countdown_seconds=0,
    )


def _loaded() -> dict[str, Any]:
    """Execute the shared source once and return what it defined."""
    namespace: dict[str, Any] = {}
    exec(ENV_SOURCE + POLICY_SOURCE, namespace)
    return namespace


def partner_policy() -> Any:
    """Return the partner's decision function, from the one shared source."""
    return _loaded()["partner_action"]


def partner_controller() -> HeuristicController:
    """Return the server-side seat controller over the same decision function."""
    return HeuristicController(partner_policy())


class ServerHarvest:
    """The server's view: every seat's action arrives together, from the loop."""

    def __init__(self, length: int = 12) -> None:
        self._core = _loaded()["Harvest"](length)

    def reset(self) -> MultiStepResult:
        """Start the run and give every seat its first observation."""
        observed = self._core.restart()
        return MultiStepResult(
            observations={seat: observed for seat in (YOU, PARTNER)},
            rewards={YOU: 0.0, PARTNER: 0.0},
            terminated=False,
            truncated=False,
        )

    def step(self, actions: Mapping[str, int]) -> MultiStepResult:
        """Step one frame with the action every seat supplied."""
        rewards, done = self._core.advance(dict(actions))
        observed = self._core.observe()
        return MultiStepResult(
            observations={seat: observed for seat in (YOU, PARTNER)},
            rewards={seat: float(rewards[seat]) for seat in (YOU, PARTNER)},
            terminated=bool(done),
            truncated=False,
        )


__all__ = [
    "BROWSER_BUNDLE",
    "ENV_SOURCE",
    "PARTNER",
    "POLICY_SOURCE",
    "YOU",
    "ServerHarvest",
    "browser_spec",
    "partner_controller",
    "partner_policy",
]
