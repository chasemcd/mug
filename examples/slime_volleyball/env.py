"""Slime Volleyball: the environment, the drawing, and the seat a policy takes.

This is study code, not platform code. It declares the ``slime_volleyball``
package's court for what it actually is, draws it with the platform's own surface
primitives, and offers the game in the two shapes a study needs:

- ``SlimeCourt`` -- the environment, which a study hands over as it is. The
  platform reads the two slimes, their action set, and the episode bound off it.
- ``slime_volleyball_mesh()`` -- two people, one court, no game server. The whole
  environment is shipped to both browsers and each steps a replica.

**Why there is a wrapper here at all.** ``SlimeVolleyEnv`` subclasses
``gymnasium.Env``, which acts one agent, and then asks for one action each for
``agent_left`` and ``agent_right``. It is a multi-agent environment wearing a
single-agent base class, and read as it declares itself it derives as one agent
whose action is a whole dictionary -- which no key can bind to. So this study says
what it is: ``SlimeCourt`` is the same environment declared a PettingZoo
``ParallelEnv``, and it is the few lines the platform's refusal asks for.

The package is not a dependency of this repository. It is the study's own choice
of environment, and the platform must not depend on any one of them, so this
module says what is missing rather than failing somewhere further in.

Install it with ``uv pip install slimevb``.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar, cast

from mug.game.browser_mesh import BrowserMeshSpec
from mug.game.env import StepResult
from mug.game.surface import Surface

# The actions, in the order the environment reads them. A chord is its own
# action, and it is written as the sequence of keys it is: holding up and left
# together is a diagonal jump, which is not the same move as either key alone.
NOOP, LEFT, UPLEFT, UP, UPRIGHT, RIGHT = 0, 1, 2, 3, 4, 5

ACTION_BINDINGS = {
    "ArrowLeft": LEFT,
    "ArrowRight": RIGHT,
    "ArrowUp": UP,
    ("ArrowUp", "ArrowLeft"): UPLEFT,
    ("ArrowUp", "ArrowRight"): UPRIGHT,
}

LEFT_SLIME = "#ff0000"
RIGHT_SLIME = "#0000ff"
BALL = "#000000"
BALL_DONE = "#aaff00"
GROUND = "#747275"
FENCE = "#000000"

# The seats, named as the environment names them.
LEFT_SEAT = "agent_left"
RIGHT_SEAT = "agent_right"


class SlimeVolleyballMissing(RuntimeError):
    """The environment package this example needs is not installed."""


def _package() -> Any:
    """Import the environment package, or say plainly what is missing."""
    try:
        import slime_volleyball.slimevolley_env as environment
    except ImportError as problem:  # pragma: no cover - depends on the machine
        raise SlimeVolleyballMissing(
            "this example needs the slime_volleyball package:"
            " uv pip install slimevb"
        ) from problem
    return environment


def _constants() -> Any:
    """Return the environment's own court geometry."""
    from slime_volleyball.core import constants

    return constants


# The two slimes and the ball, as the environment sizes them. They are constants of
# the game rather than of its state, so they are read once and named here.
AGENT_RADIUS = 1.5
BALL_RADIUS = 0.5


def court_scene(env: Any) -> dict[str, Any] | None:
    """Return one frame of the court as plain data, in world coordinates.

    The drawing reads this rather than the environment, for one reason: a frame is
    **recorded**. What a study puts in a frame's metrics is written into the run, so
    a drawing that read a live environment object could not be recorded and could
    never be drawn again from the record.

    The package builds a second object for its own pixel renderer, and only when
    something asks it to draw. A study that read that object read ``None`` on every
    frame and drew nothing at all.
    """
    state = getattr(env, "_env_state", None)
    if state is None:
        return None
    numbers = _constants()
    fence_middle = 0.75 + numbers.REF_WALL_HEIGHT / 2
    fence_height = numbers.REF_WALL_HEIGHT - 1.5
    return {
        "ball": [float(state.ball_pos[0]), float(state.ball_pos[1])],
        # Where the ball is going, which a picture does not need and a partner does:
        # a slime decides where to stand from where the ball will be. It is in the
        # record either way, so what the partner read is part of the run.
        "ball_speed": [float(state.ball_vel[0]), float(state.ball_vel[1])],
        "left": [float(state.agent_pos[0, 0]), float(state.agent_pos[0, 1])],
        "right": [float(state.agent_pos[1, 0]), float(state.agent_pos[1, 1])],
        "fence_x": 0.0,
        "fence_top": fence_middle + fence_height / 2,
        "fence_bottom": fence_middle - fence_height / 2,
        # The ground is a block, and what a drawing wants is the top of it: the
        # line the slimes stand on and the ball bounces off.
        "ground_y": 0.75 + numbers.REF_U / 2,
    }


def _view_height() -> float:
    """Return how much of the world's height the court window shows.

    The court is wider than it is tall: the environment's own window is 1200 by
    500 pixels at one scale, so it shows the whole width and a fraction of the
    height. A drawing that divided both by the width put the whole game in the
    bottom quarter of the canvas.
    """
    numbers = _constants()
    return numbers.REF_W * numbers.WINDOW_HEIGHT / numbers.WINDOW_WIDTH


def _to_x(value: float) -> float:
    """Return one world x as a relative screen coordinate."""
    return value / _constants().REF_W + 0.5


def _to_y(value: float) -> float:
    """Return one world y as a relative screen coordinate."""
    return 1 - value / _view_height()


def _draw_slime(
    surface: Surface,
    name: str,
    where: list[float],
    facing: int,
    ball: list[float],
    color: str,
) -> None:
    """Draw one slime: a half circle for the body, and eyes that watch the ball."""
    steps = 24
    radius = AGENT_RADIUS
    x, y = where
    body = [
        (
            _to_x(math.cos(math.pi - math.pi * index / steps) * radius + x),
            _to_y(math.sin(math.pi - math.pi * index / steps) * radius + y),
        )
        for index in range(steps + 1)
    ]
    surface.polygon(points=body, color=color, object_id=f"{name}-body", depth=-1)

    angle = math.pi * (120 if facing == 1 else 60) / 180
    eye_x = x + 0.6 * radius * math.cos(angle)
    eye_y = y + 0.6 * radius * math.sin(angle)
    towards_x = ball[0] - eye_x
    towards_y = ball[1] - eye_y
    length = math.hypot(towards_x, towards_y) or 1.0
    scale = _constants().REF_W

    surface.circle(
        x=_to_x(eye_x),
        y=_to_y(eye_y),
        radius=radius * 0.3 / scale,
        color="#ffffff",
        object_id=f"{name}-eye",
        depth=1,
    )
    surface.circle(
        x=_to_x(eye_x + towards_x / length * 0.15 * radius),
        y=_to_y(eye_y + towards_y / length * 0.15 * radius),
        radius=radius * 0.1 / scale,
        color="#000000",
        object_id=f"{name}-pupil",
        depth=2,
    )


def render(surface: Surface, state: StepResult) -> None:
    """Draw the court, the two slimes, and the ball for one frame."""
    court = state.info.get("scene")
    if not isinstance(court, dict):
        return
    scene = cast("dict[str, Any]", court)
    scale = _constants().REF_W

    # The court itself never moves, so it is persistent and travels as a delta.
    fence_x = _to_x(float(scene["fence_x"]))
    surface.line(
        points=[
            (fence_x, _to_y(float(scene["fence_top"]))),
            (fence_x, _to_y(float(scene["fence_bottom"]))),
        ],
        color=FENCE,
        object_id="fence",
        persistent=True,
    )
    ground_y = _to_y(float(scene["ground_y"]))
    surface.line(
        points=[(0.0, ground_y), (1.0, ground_y)],
        color=GROUND,
        object_id="ground",
        persistent=True,
        depth=-1,
    )

    ball = cast("list[float]", scene["ball"])
    _draw_slime(
        surface, "left", cast("list[float]", scene["left"]), -1, ball, LEFT_SLIME
    )
    _draw_slime(
        surface, "right", cast("list[float]", scene["right"]), 1, ball, RIGHT_SLIME
    )
    surface.circle(
        x=_to_x(ball[0]),
        y=_to_y(ball[1]),
        radius=BALL_RADIUS / scale,
        color=BALL_DONE if state.terminated else BALL,
        object_id="ball",
    )


def the_court(env: Any, seat: str) -> tuple[dict[str, Any], str]:
    """Return what a planning partner is shown: the court, and which slime it is.

    This is the study's ``SeatView``. A slime decides where to stand from where the
    ball is going, and a velocity is not in an observation. The loop calls this on the
    environment it is stepping, so a partner reads the rally it is actually playing.

    It reads the same description of the court the drawing reads, so what the partner
    saw and what the participant saw are one recorded thing.
    """
    return court_scene(env) or {}, seat


# The court class, built once when it is first asked for. It cannot be written at
# module level: it inherits from the package's own class, and this module has to import
# with the package absent so that it can say what is missing.
_COURT: Any = None


def _court_class() -> Any:
    """Return the court declared as the parallel environment it is."""
    global _COURT
    if _COURT is not None:
        return _COURT
    from pettingzoo.utils.env import ParallelEnv

    class SlimeCourt(_package().SlimeVolleyEnv, ParallelEnv):
        """The Slime Volleyball court, declared for the environment it really is.

        The package's own class subclasses ``gymnasium.Env`` and then asks for one
        action each for two named slimes. That is a PettingZoo parallel environment,
        so this says so: it names ``possible_agents``, which is what the platform
        reads the seats off.

        It also unwraps the observation. The package hands each seat
        ``{"obs": array}``, and what a seat sees should be the array a network was
        trained on rather than a dictionary holding it.
        """

        possible_agents: ClassVar[tuple[str, ...]] = (LEFT_SEAT, RIGHT_SEAT)
        metadata: ClassVar[dict[str, Any]] = {"render_modes": ["rgb_array"]}

        def __init__(self, seed: int = 42, max_steps: int = 3000) -> None:
            super().__init__(
                config={"human_inputs": True, "seed": seed}, render_mode="rgb_array"
            )
            self.agents = list(self.possible_agents)
            self.max_steps = max_steps

        def reset(self, **named: Any) -> tuple[dict[str, Any], dict[str, Any]]:
            """Start a rally, and hand each slime the array it sees."""
            observed, info = cast(
                "tuple[Any, Any]", super().reset(**_only_seed(named))
            )
            self.agents = list(self.possible_agents)
            return _seen(observed), cast("dict[str, Any]", info)

        def step(self, actions: Any) -> tuple[dict[str, Any], Any, Any, Any, Any]:
            """Step both slimes' actions at once."""
            observed, rewards, terminated, truncated, info = cast(
                "tuple[Any, Any, Any, Any, Any]", super().step(actions)
            )
            return _seen(observed), rewards, terminated, truncated, info

    _COURT = SlimeCourt
    return _COURT


def slime_court(seed: int = 42, max_steps: int = 3000) -> Any:
    """Return the court this study runs, built and ready to step.

    This is the whole of what a study hands the platform: the two slimes, their six
    actions, and the rally length are all read off it.
    """
    return _court_class()(seed=seed, max_steps=max_steps)


def _only_seed(named: dict[str, Any]) -> dict[str, Any]:
    """Keep the arguments the package's own reset takes, and drop the rest.

    The loop resets with a seed. This environment takes its seed when it is built, so
    a seed passed later is dropped rather than raising in front of a participant.
    """
    del named
    return {}


def _seen(observed: Any) -> dict[str, Any]:
    """Return what each seat sees, unwrapped from the package's nesting."""
    if not isinstance(observed, dict):
        return {}
    held = cast("dict[str, Any]", observed)
    return {
        key: value["obs"] if isinstance(value, dict) and "obs" in value else value
        for key, value in held.items()
    }


# The Python both browsers run in Pyodide for the two-person game. It is the whole
# environment and its drawing, so the peers each step an identical replica and
# agree over their own data channels.
_MESH_BUNDLE = '''
import dataclasses

import numpy
import slime_volleyball.slimevolley_env as slimevolley_env

SEATS = ("agent_left", "agent_right")

# Every field of the environment's own state record, so a snapshot covers the
# whole court. A rollback replays from a snapshot, so a field left out here is a
# field the two peers can silently disagree about.
_VECTORS = ("ball_pos", "ball_vel", "ball_prev_pos")
_PAIRS = ("agent_pos", "agent_vel", "agent_desired_vel")


class Court:
    """Two people, one court. Both replicas step this from the same inputs."""

    def __init__(self, peer_actor_ids, seed):
        self.peers = tuple(sorted(peer_actor_ids))
        self.seat_of = {peer: SEATS[index] for index, peer in enumerate(self.peers)}
        self.env = slimevolley_env.SlimeVolleyEnv(
            config={"human_inputs": True, "seed": seed}, render_mode="rgb_array"
        )
        self.env.reset()
        self.frame = 0
        self.scores = {peer: 0 for peer in self.peers}

    def step(self, actions):
        self.frame += 1
        moves = {self.seat_of[peer]: int(actions[peer]) for peer in self.peers}
        _obs, rewards, _term, _trunc, _info = self.env.step(moves)
        for peer in self.peers:
            got = rewards.get(self.seat_of[peer], 0) if isinstance(rewards, dict) else 0
            if got > 0:
                self.scores[peer] += 1
        return (self.observation(), rewards, False, False, None)

    def observation(self):
        return {
            "frame": self.frame,
            "scores": dict(self.scores),
            "state": self.positions(),
        }

    def positions(self):
        """Return the court positions the drawing reads, as plain numbers."""
        state = self.env._env_state
        return {
            "ball_pos_x": float(state.ball_pos[0]),
            "ball_pos_y": float(state.ball_pos[1]),
            "agent_left_x": float(state.agent_pos[0, 0]),
            "agent_left_y": float(state.agent_pos[0, 1]),
            "agent_right_x": float(state.agent_pos[1, 0]),
            "agent_right_y": float(state.agent_pos[1, 1]),
        }

    def snapshot(self):
        state = self.env._env_state
        kept = {name: getattr(state, name).tolist() for name in _VECTORS}
        kept.update({name: getattr(state, name).tolist() for name in _PAIRS})
        kept["agent_life"] = state.agent_life.tolist()
        kept["delay_life"] = int(state.delay_life)
        kept["time"] = int(state.time)
        kept["done"] = bool(state.done)
        return (self.frame, dict(self.scores), kept)

    def restore(self, snapshot):
        frame, scores, kept = snapshot
        self.frame = frame
        self.scores = dict(scores)
        changes = {
            name: numpy.array(kept[name], dtype=numpy.float32)
            for name in _VECTORS + _PAIRS
        }
        changes["agent_life"] = numpy.array(kept["agent_life"], dtype=numpy.int32)
        changes["delay_life"] = numpy.int32(kept["delay_life"])
        changes["time"] = numpy.int32(kept["time"])
        changes["done"] = numpy.bool_(kept["done"])
        self.env._env_state = dataclasses.replace(self.env._env_state, **changes)


def make_replica(peer_actor_ids, seed):
    """Build one deterministic replica for the frozen peer set and shared seed."""
    return Court(peer_actor_ids, seed)


# The court is wider than it is tall, so the two axes are scaled apart. Both
# replicas draw with the same numbers the server drawing uses.
WORLD_W = 48.0
WORLD_H = 20.0


def to_x(value):
    """Return one world x as a relative screen coordinate."""
    return value / WORLD_W + 0.5


def to_y(value):
    """Return one world y as a relative screen coordinate."""
    return 1 - value / WORLD_H


def draw(replica):
    """Return the surface commands for the replica's current state."""
    state = replica.observation()["state"]
    commands = [
        {"op": "rect", "id": "court", "relative": True, "color": "#e8f0ff",
         "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        {"op": "line", "id": "fence", "relative": True, "color": "#000000",
         "points": [[0.5, to_y(3.5)], [0.5, to_y(1.5)]]},
        {"op": "line", "id": "ground", "relative": True, "color": "#747275",
         "points": [[0.0, to_y(1.5)], [1.0, to_y(1.5)]]},
        {"op": "circle", "id": "ball", "relative": True, "color": "#000000",
         "x": to_x(state.get("ball_pos_x", 0.0)),
         "y": to_y(state.get("ball_pos_y", 0.0)), "radius": 0.5 / WORLD_W},
    ]
    for name, colour, key in (
        ("left", "#ff0000", "agent_left"),
        ("right", "#0000ff", "agent_right"),
    ):
        commands.append(
            {"op": "circle", "id": "slime-" + name, "relative": True, "color": colour,
             "x": to_x(state.get(key + "_x", 0.0)),
             "y": to_y(state.get(key + "_y", 0.0)),
             "radius": 1.5 / WORLD_W}
        )
    return commands
'''


def slime_volleyball_mesh(*, max_steps: int = 3000) -> BrowserMeshSpec:
    """Return the two-person browser game: one court, two replicas, no server."""
    return BrowserMeshSpec(
        channel_key="slime-volleyball",
        source_bundle=_MESH_BUNDLE,
        requires=("slime_volleyball", "numpy"),
        action_bindings=dict(ACTION_BINDINGS),
        default_action=NOOP,
        fps=30,
        max_steps=max_steps,
        # Slime Volleyball is fast and frame-sensitive, so a short input delay
        # keeps the game responsive and the rollback does the rest.
        input_delay=2,
        snapshot_interval=10,
    )


__all__ = [
    "ACTION_BINDINGS",
    "LEFT_SEAT",
    "RIGHT_SEAT",
    "SlimeVolleyballMissing",
    "court_scene",
    "render",
    "slime_court",
    "slime_volleyball_mesh",
    "the_court",
]
