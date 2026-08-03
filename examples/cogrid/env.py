"""Overcooked (CoGrid): the environment, the drawing, and what a chef can see.

This is study code, not platform code. It builds the CoGrid Overcooked kitchen and
draws it with the platform's own surface primitives. What it does **not** hold any
more is an adapter: CoGrid is a PettingZoo parallel environment, so a study hands it
over as it is and the platform reads the agents, the action set, and the episode
bound off it.

What is left here is the three things only this study can say:

- ``overcooked_kitchen(layout)`` -- the environment, bound the way this study builds
  it, taking no arguments;
- ``overcooked_scene(layout)`` -- what a picture of a kitchen needs, which an
  observation does not carry: the counters, the pots, and where each chef is;
- ``render`` and ``kitchen_hud`` -- the drawing and the status line that read it.

``overcooked_browser()`` and ``overcooked_mesh()`` are still written as browser
bundles, because a browser run carries its own Python program and the platform does
not write that program for a named environment yet.

The ``cogrid`` package is not a dependency of this repository. An environment is
the study's own choice, so this module says what is missing rather than failing
somewhere further in.

Install it with ``uv pip install cogrid==0.3.2`` (see ``COGRID``).
"""

from __future__ import annotations

import functools
from typing import Any, cast

from examples.cogrid.sprites import POLICY_ASSET
from mug.game.browser import BrowserGameSpec, BrowserPartner
from mug.game.browser_mesh import BrowserMeshSpec
from mug.game.env import StepResult
from mug.game.surface import Surface

# The actions, as CoGrid's cardinal action set orders them.
MOVE_UP, MOVE_DOWN, MOVE_LEFT, MOVE_RIGHT, PICKUP_DROP, TOGGLE, NOOP = range(7)

ACTION_BINDINGS = {
    "ArrowUp": MOVE_UP,
    "ArrowDown": MOVE_DOWN,
    "ArrowLeft": MOVE_LEFT,
    "ArrowRight": MOVE_RIGHT,
    "w": PICKUP_DROP,
    "W": PICKUP_DROP,
    "q": TOGGLE,
    "Q": TOGGLE,
}

# The two chefs, as **CoGrid** names them. They are the environment's own agents and
# not a name this study invented, which is the whole reason there is no longer a map
# from one to the other: a study used to carry ``{"agent-0": 0, "agent-1": 1}`` and
# translate on every call, and a mistyped seat came out as a KeyError on a
# participant's first frame. A seating is written over these, so what the study says
# and what the environment acts cannot drift apart.
CHEF_ONE = 0
CHEF_TWO = 1

TILE = 45
KITCHEN_BACKGROUND = "#e6b453"

# How fast the kitchen runs. The status line reads it to say how long is left, so
# it is written once here rather than in each study that shows one.
FPS = 30

# How often the AI partner decides. A partner that changed its mind thirty times a
# second would twitch on the spot; the legacy study ran it every fifth frame, and
# a participant reads that as a teammate walking rather than vibrating.
PARTNER_DECIDES_EVERY = 5

# The five layouts the legacy human-human study rotated through, with the grid
# each one fills. A study picks one per pair, so the sample covers all five.
LAYOUTS = (
    ("cramped_room", 5, 4),
    ("asymmetric_advantages", 9, 5),
    ("coordination_ring", 5, 5),
    ("forced_coordination", 5, 5),
    ("counter_circuit", 8, 5),
)

_DIRECTIONS = {0: "EAST", 1: "SOUTH", 2: "WEST", 3: "NORTH"}
_HAT = {0: "blue", 1: "green"}


# The one place this example says which environment it runs. The server imports
# this package and the participant's browser installs it with micropip, and the two
# must be the **same** version: a browser run is verified by the server re-executing
# it, so two versions that step even slightly differently would refuse every honest
# run. They were allowed to drift once -- the browser asked for 0.2.1 while the
# server had 0.3.1 -- so the pin is written once here and read everywhere.
COGRID = "cogrid==0.3.2"


class CoGridMissing(RuntimeError):
    """The environment package this example needs is not installed."""


def _cogrid() -> Any:
    """Import the environment package, or say plainly what is missing."""
    try:
        from cogrid.cogrid_env import CoGridEnv
        from cogrid.envs import registry
        from cogrid.envs.overcooked import overcooked_grid_objects
        from cogrid.envs.overcooked.agent import OvercookedAgent
        from cogrid.envs.overcooked.rewards import DeliveryReward
    except ImportError as problem:  # pragma: no cover - depends on the machine
        raise CoGridMissing(
            f"this example needs the cogrid package: uv pip install {COGRID}"
        ) from problem
    return {
        "env_class": CoGridEnv,
        "registry": registry,
        "objects": overcooked_grid_objects,
        "agent": OvercookedAgent,
        "reward": DeliveryReward,
    }


# The observation the trained policy was trained on, in the order it reads them.
# This is the study's own choice and it is plain data, so a browser study can name
# it with no environment package on the server: the kitchen itself is installed in
# the participant's browser, not beside the application.
KITCHEN_FEATURES: tuple[str, ...] = (
    "agent_dir",
    "overcooked_inventory",
    "next_to_counter",
    "next_to_pot",
    "object_type_masks",
    "ordered_pot_features",
    "dist_to_other_players",
    "agent_position",
    "can_move_direction",
)


def kitchen_config(
    layout: str = "cramped_room", max_steps: int = 1350
) -> dict[str, Any]:
    """Return the CoGrid configuration for one Overcooked layout."""
    parts = _cogrid()
    return {
        "name": "overcooked",
        "num_agents": 2,
        "action_set": "cardinal_actions",
        "features": list(KITCHEN_FEATURES),
        "rewards": [parts["reward"](coefficient=1.0, common_reward=True)],
        "grid": {"layout": f"overcooked_{layout}_v0"},
        "scope": "overcooked",
        "max_steps": max_steps,
        "pickupable_types": [
            "onion",
            "onion_soup",
            "plate",
            "tomato",
            "tomato_soup",
        ],
    }


def caught_up(env: Any) -> Any:
    """Return the environment with its grid objects caught up to its state.

    CoGrid 0.2.1 steps an array of numbers and writes the result back onto the grid
    and the chefs **only when it is asked to draw**. A study that reads the grid
    without asking sees the opening frame for the whole run: the chefs stand still,
    the pots stay empty, and nothing ever moves.

    Asking the environment to draw as well would make it produce a picture nobody
    reads on every frame, so this asks for the write-back alone.
    """
    catch_up = getattr(env, "_sync_objects_from_state", None)
    if callable(catch_up):
        catch_up()
    return env


def chef_at(env: Any, seat: Any) -> Any:
    """Return the chef one seat drives, or nothing when the seat is not in this env.

    A seat is named by the agent CoGrid itself acts, so this reads the environment
    with the study's own word for the chef and translates nothing. The seat arrives
    as text wherever it came from a record, so it is read back to the number the
    environment counts with.
    """
    return caught_up(env).grid.grid_agents.get(int(seat))


def make_kitchen(layout: str = "cramped_room", max_steps: int = 1350) -> Any:
    """Build one Overcooked environment for a layout."""
    import functools

    parts = _cogrid()
    identifier = f"Overcooked-{layout}-MUG"
    parts["registry"].register(
        environment_id=identifier,
        env_class=functools.partial(
            parts["env_class"],
            config=kitchen_config(layout, max_steps),
            agent_class=parts["agent"],
        ),
    )
    return parts["registry"].make(identifier)


# -- the scene, and the drawing that reads it ---------------------------------------

# What one grid square is, for the drawing. The name is the sprite the square is
# painted with; the environment's own class names are read into these once, here.
_TERRAIN = {
    "Counter": "counter.png",
    "Wall": "counter.png",
    "DeliveryZone": "serve.png",
    "PlateStack": "dishes.png",
    "OnionStack": "onions.png",
}

# What a chef can carry, and the sprite suffix that shows it.
_CARRIED = {"Onion": "-onion", "OnionSoup": "-soup-onion", "Plate": "-dish"}

# What can be put down, picked up, or cooked, and the sprite it is drawn with.
_MOVABLE = {
    "Onion": "onion.png",
    "Plate": "dish.png",
    "OnionSoup": "soup-onion-dish.png",
}


def kitchen_scene(
    env: Any, cols: int, rows: int, *, fps: int = FPS
) -> dict[str, Any]:
    """Return one frame of the kitchen as plain data.

    The drawing reads this rather than the environment itself, for one reason: a
    frame is **recorded**. What a study puts in a frame's metrics is written into
    the run, so a drawing that read a live environment object could not be
    recorded and could never be drawn again from the record. This can, so a replay
    redraws the same kitchen with no CoGrid installed.

    The shift the participant is working is in here too -- what has been delivered and
    how long is left -- read off the environment's own score and clock. It used to be
    counted by hand in an adapter this study wrote, which meant the count and the
    environment could disagree and nothing would say so.
    """
    parts = _cogrid()
    objects = parts["objects"]
    env = caught_up(env)
    tiles: list[dict[str, Any]] = []
    things: list[dict[str, Any]] = []
    pots: list[dict[str, Any]] = []
    for item in env.grid.grid:
        if item is None:
            continue
        kind = type(item).__name__
        where = [int(item.pos[0]), int(item.pos[1])]
        # Everything in this loop is fixed to the grid, so where it is names it.
        # The identifier only has to be stable frame to frame, which is what the
        # renderer tracks a drawn object by. CoGrid gave each object a random uuid
        # until 0.3, and it is gone -- rightly, because a fresh uuid per run is a
        # worse name for a counter than the square the counter is on. The browser
        # bundle has always named these by position.
        at = f"{where[0]}-{where[1]}"
        if kind in _TERRAIN or isinstance(item, objects.Pot):
            # A pot stands on a counter, so the counter is painted under it.
            tiles.append(
                {
                    "id": f"tile-{at}",
                    "sprite": _TERRAIN.get(kind, "counter.png"),
                    "pos": where,
                }
            )
        if isinstance(item, objects.Pot):
            tiles.append({"id": f"pot-{at}", "sprite": "pot.png", "pos": where})
            pots.append(
                {
                    "id": f"pot-{at}",
                    "pos": where,
                    "count": len(item.objects_in_pot),
                    "timer": int(item.cooking_timer),
                }
            )
        placed = getattr(item, "obj_placed_on", None)
        # Two movable things can share a square -- one on the counter and the
        # counter's own object -- so the role goes in the name as well as the
        # square, or the second would overwrite the first.
        for role, held in (("on", placed), ("at", item)):
            name = type(held).__name__ if held is not None else ""
            if name in _MOVABLE:
                things.append(
                    {"id": f"{role}-{at}", "sprite": _MOVABLE[name], "pos": where}
                )

    chefs = [
        {
            "pos": [int(chef.pos[0]), int(chef.pos[1])],
            "facing": _DIRECTIONS[int(chef.dir)],
            "carrying": _CARRIED.get(
                type(chef.inventory[0]).__name__ if chef.inventory else "", ""
            ),
        }
        for chef in env.grid.grid_agents.values()
    ]
    left = max(0, int(env.max_steps) - int(env.t)) / float(fps or 1)
    return {
        "cols": cols,
        "rows": rows,
        "tiles": tiles,
        "things": things,
        "pots": pots,
        "chefs": chefs,
        "delivered": int(env.cumulative_score),
        "seconds_left": round(left, 1),
    }


def overcooked_kitchen(
    layout: str = "cramped_room", max_steps: int = 1350
) -> Any:
    """Return the kitchen this study runs, bound so that it takes no arguments.

    This is the whole of what a study hands the platform. Everything else about the
    environment -- that it has two agents, that they act one of seven cardinal moves,
    how long an episode runs -- is read off it.
    """
    return functools.partial(make_kitchen, layout, max_steps)


def overcooked_scene(
    layout: str = "cramped_room", *, fps: int = FPS
) -> Any:
    """Return what a picture of this layout needs, as a function of the kitchen.

    The platform calls it once a frame and puts the answer in that frame's own
    metrics, so ``render`` and ``kitchen_hud`` read a recorded picture rather than a
    live environment.
    """
    cols, rows = _grid_of(layout)
    return functools.partial(kitchen_scene, cols=cols, rows=rows, fps=fps)


def kitchen_size(layout: str = "cramped_room") -> tuple[int, int]:
    """Return how large a picture of this layout is: one ``TILE`` a square.

    It is what ``Game(size=)`` takes, and it is the size the legacy study drew this
    kitchen at. One sprite pixel is one screen pixel, which is what a sprite sheet
    is drawn for: the same kitchen stretched over 600 by 400 is a fifth wider than
    it is tall, blurred, and several times the work to paint on every frame.
    """
    cols, rows = _grid_of(layout)
    return TILE * cols, TILE * rows


def _place(pos: list[int], cols: int, rows: int) -> tuple[float, float]:
    """Return one grid square as a relative screen coordinate.

    CoGrid counts a position as (row, column) and a screen counts it as (x, y), so
    the two are swapped here rather than anywhere else.
    """
    row, column = pos
    return column / cols, row / rows


def draw_kitchen(surface: Surface, scene: dict[str, Any]) -> None:
    """Draw one frame of the kitchen: the room, then what is in it, then the chefs.

    The room is persistent, so it is sent once and then travels as a delta. Every
    movable thing is drawn afresh each frame, which is what an object that can be
    picked up, put down, or eaten needs.
    """
    cols, rows = int(scene["cols"]), int(scene["rows"])
    width, height = 1.0 / cols, 1.0 / rows

    def tile(name: str, frame: str, pos: list[int], **extra: Any) -> None:
        x, y = _place(pos, cols, rows)
        surface.image(
            image_name=name, x=x, y=y, w=width, h=height, frame=frame, **extra
        )

    for one in scene["tiles"]:
        tile(
            "terrain",
            one["sprite"],
            one["pos"],
            object_id=one["id"],
            persistent=True,
            depth=-2,
        )

    for one in scene["things"]:
        tile("objects", one["sprite"], one["pos"], object_id=one["id"], depth=1)

    for pot in scene["pots"]:
        _draw_pot(surface, pot, cols, rows)

    for index, chef in enumerate(scene["chefs"]):
        x, y = _place(chef["pos"], cols, rows)
        facing = chef["facing"]
        surface.image(
            image_name="chefs",
            x=x,
            y=y,
            w=width,
            h=height,
            frame=f"{facing}{chef['carrying']}.png",
            object_id=f"chef-{index}",
            tween_duration=75,
        )
        surface.image(
            image_name="chefs",
            x=x,
            y=y,
            w=width,
            h=height,
            frame=f"{facing}-{_HAT[index]}hat.png",
            object_id=f"chef-{index}-hat",
            tween_duration=75,
            depth=2,
        )


def _draw_pot(surface: Surface, pot: dict[str, Any], cols: int, rows: int) -> None:
    """Draw what is cooking in one pot, and how long is left of it."""
    count = int(pot["count"])
    if not count:
        return
    x, y = _place(pot["pos"], cols, rows)
    timer = int(pot["timer"])
    sprite = (
        "soup-onion-cooked.png" if timer == 0 else f"soup-onion-{count}-cooking.png"
    )
    surface.image(
        image_name="objects",
        x=x,
        y=y,
        w=1.0 / cols,
        h=1.0 / rows,
        frame=sprite,
        object_id=f"{pot['id']}-contents",
        depth=1,
    )
    if timer and count == 3:
        # The countdown only means anything on a full pot, so it is only drawn
        # there. A timer over a half-full pot would say the soup was nearly ready
        # when it had not started.
        surface.text(
            x=x,
            y=y,
            text=f"{timer:02d}",
            color="#cc0000",
            font_size=14,
            object_id=f"{pot['id']}-timer",
        )


# -- what a participant reads, and what they see -------------------------------------


def kitchen_hud(state: StepResult) -> str:
    """Return the status line a cook reads while they work: dishes, and time left.

    This is the legacy study's own heads-up display, said the same way: what the
    kitchen has delivered, and how long is left of the shift. Both are read out of the
    recorded scene, so what the participant was told is part of the run.
    """
    scene = cast("dict[str, Any]", state.info.get("scene") or {})
    delivered = int(scene.get("delivered", 0))
    left = float(scene.get("seconds_left", 0.0))
    return f"Dishes delivered: {delivered:03d}     Time left: {left:.1f}s"


def render(surface: Surface, state: StepResult) -> None:
    """Draw one frame of the kitchen from the scene the environment recorded."""
    scene = state.info.get("scene")
    if isinstance(scene, dict):
        draw_kitchen(surface, cast("dict[str, Any]", scene))


def _grid_of(layout: str) -> tuple[int, int]:
    """Return the columns and rows one named layout fills."""
    for name, cols, rows in LAYOUTS:
        if name == layout:
            return cols, rows
    raise ValueError(f"{layout!r} is not a layout this example ships")


# The Python both browsers run for the two-person kitchen. Each peer installs
# CoGrid and builds its own replica of the same kitchen, so the environment travels
# to the browsers rather than the frames travelling back from a server.
#
# The bundle registers the environment itself. Nothing the server did is in scope
# here: this source is all a browser gets.
_MESH_BUNDLE = '''
import functools

from cogrid.cogrid_env import CoGridEnv
from cogrid.envs import registry
from cogrid.envs.overcooked.agent import OvercookedAgent
from cogrid.envs.overcooked.rewards import DeliveryReward

# CoGrid numbers its agents, so the two seats are 0 and 1.
SEATS = (0, 1)

CONFIG = {
    "name": "overcooked",
    "num_agents": 2,
    "action_set": "cardinal_actions",
    "features": ["agent_dir", "overcooked_inventory", "agent_position"],
    "rewards": [DeliveryReward(coefficient=1.0, common_reward=True)],
    "grid": {"layout": "overcooked_" + LAYOUT + "_v0"},
    "scope": "overcooked",
    "max_steps": MAX_STEPS,
    "pickupable_types": ["onion", "onion_soup", "plate", "tomato", "tomato_soup"],
}

# What each kind of square is painted, so the kitchen is legible without the
# sprite sheets a server-drawn study serves.
TERRAIN = {
    "Counter": "#8b6b3f",
    "Wall": "#8b6b3f",
    "Pot": "#3b3b3b",
    "DeliveryZone": "#9aa0a6",
    "OnionStack": "#d9a441",
    "PlateStack": "#f2f2f2",
}
CHEFS = ["#2d6cdf", "#2ddf6c"]


def build():
    """Register and build one replica of the kitchen this study runs."""
    identifier = "Overcooked-" + LAYOUT + "-mesh"
    registry.register(
        environment_id=identifier,
        env_class=functools.partial(
            CoGridEnv, config=CONFIG, agent_class=OvercookedAgent
        ),
    )
    return registry.make(identifier)


class Kitchen:
    """Two people, one kitchen. Both replicas step this from the same inputs."""

    def __init__(self, peer_actor_ids, seed):
        self.peers = tuple(sorted(peer_actor_ids))
        self.seat_of = {peer: SEATS[index] for index, peer in enumerate(self.peers)}
        self.env = build()
        self.env.reset(seed=seed)
        self.frame = 0
        self.delivered = 0

    def step(self, actions):
        self.frame += 1
        moves = {self.seat_of[peer]: int(actions[peer]) for peer in self.peers}
        _obs, rewards, _term, _trunc, _info = self.env.step(moves)
        got = sum(rewards.values()) if isinstance(rewards, dict) else float(rewards)
        if got > 0:
            self.delivered += 1
        return (self.observation(), rewards, False, False, None)

    def observation(self):
        # CoGrid writes its stepped state back onto the grid objects only when it
        # is asked to draw, so a replica that read the grid would show the opening
        # frame for the whole game.
        self.env._sync_objects_from_state()
        return {
            "frame": self.frame,
            "delivered": self.delivered,
            "tiles": [
                [type(item).__name__, int(item.pos[0]), int(item.pos[1])]
                for item in self.env.grid.grid
                if item is not None and type(item).__name__ in TERRAIN
            ],
            "chefs": [
                [int(chef.pos[0]), int(chef.pos[1]), int(chef.dir)]
                for chef in self.env.grid.grid_agents.values()
            ],
        }


def make_replica(peer_actor_ids, seed):
    """Build one replica for the frozen peer set and shared seed."""
    return Kitchen(peer_actor_ids, seed)


def square(name, colour, row, col, inset):
    """Return one grid square as a surface command."""
    return {
        "op": "rect", "id": name, "relative": True, "color": colour,
        "x": col / COLS + inset, "y": row / ROWS + inset,
        "w": 1.0 / COLS - inset * 2, "h": 1.0 / ROWS - inset * 2,
    }


def draw(replica):
    """Return the surface commands for the replica's current state."""
    observed = replica.observation()
    commands = [
        {"op": "rect", "id": "floor", "relative": True, "color": "#e6b453",
         "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    ]
    for index, tile in enumerate(observed["tiles"]):
        kind, row, col = tile
        commands.append(square("tile-" + str(index), TERRAIN[kind], row, col, 0.0))
    for index, chef in enumerate(observed["chefs"]):
        commands.append(
            square("chef-" + str(index), CHEFS[index % len(CHEFS)],
                   chef[0], chef[1], 0.02)
        )
    # The status line. In browser execution the study owns the whole drawing, so
    # the two people running this kitchen between them draw the same band the
    # server draws for a study it steps.
    left = max(0, MAX_STEPS - observed["frame"]) / 30.0
    commands.append({
        "op": "rect", "id": "hud-band", "relative": True, "color": "#101418",
        "x": 0.0, "y": 0.0, "w": 1.0, "h": 0.085, "depth": 100,
    })
    commands.append({
        "op": "text", "id": "hud-text", "relative": True, "color": "#f5f7fa",
        "text": "Dishes delivered: %03d     Time left: %.1fs" % (
            observed["delivered"], left
        ),
        "font_size": 15, "x": 0.015, "y": 0.061, "depth": 101,
    })
    return commands
'''


# The Python one browser runs for the human-AI kitchen. The environment steps in
# the participant's own browser and the exported partner is scored beside it by
# the browser's own inference runtime, so a whole human-AI study runs with no
# server in the loop.
#
# The drawing is here rather than shared with the server path because this source
# is *all* a browser gets: nothing this repository imports is in scope. What could
# drift -- which sprite each thing is painted with, and which frame of which sheet
# that is -- is injected into the header from this module's own maps, so those
# decisions still have one source.
_BROWSER_BUNDLE = '''
import functools

from cogrid.cogrid_env import CoGridEnv
from cogrid.envs import registry
from cogrid.envs.overcooked import overcooked_grid_objects
from cogrid.envs.overcooked.agent import OvercookedAgent
from cogrid.envs.overcooked.rewards import DeliveryReward

# CoGrid numbers its agents. The participant cooks the first; the exported network
# cooks the second.
COOK = 0
PARTNER = 1

CONFIG = {
    "name": "overcooked",
    "num_agents": 2,
    "action_set": "cardinal_actions",
    # The full feature set, because it is what the exported network was trained on.
    # A shorter one would score a vector of the wrong size and the partner would
    # never act.
    "features": FEATURES,
    "rewards": [DeliveryReward(coefficient=1.0, common_reward=True)],
    "grid": {"layout": "overcooked_" + LAYOUT + "_v0"},
    "scope": "overcooked",
    "max_steps": MAX_STEPS,
    "pickupable_types": ["onion", "onion_soup", "plate", "tomato", "tomato_soup"],
}

# What the partner is doing until it next decides. The driver sets this each frame
# from the browser's inference runtime, and the server sets it from the reported
# run when it re-executes the episode to verify it.
_partner_action = 0
_kitchen = None


def partner_acts(action):
    """Take the action the exported partner chose for this frame."""
    global _partner_action
    _partner_action = int(action)


def partner_observation():
    """Return the numbers the exported partner is scored on this frame."""
    return _kitchen.partner_obs()


class Kitchen:
    """One kitchen, one person, and one exported network cooking beside them."""

    def __init__(self):
        identifier = "Overcooked-" + LAYOUT + "-browser"
        registry.register(
            environment_id=identifier,
            env_class=functools.partial(
                CoGridEnv, config=CONFIG, agent_class=OvercookedAgent
            ),
        )
        self.env = registry.make(identifier)
        self.seen = {}
        self.frame = 0
        self.delivered = 0

    def reset(self, seed=None):
        observed, _info = self.env.reset(seed=seed)
        self.seen = dict(observed)
        self.frame = 0
        self.delivered = 0
        return self._numbers(COOK), {}

    def step(self, action):
        moves = {COOK: int(action), PARTNER: int(_partner_action)}
        observed, rewards, terminated, truncated, _info = self.env.step(moves)
        self.seen = dict(observed)
        self.frame += 1
        earned = float(rewards.get(COOK, 0.0))
        self.delivered += int(round(earned))
        return (
            self._numbers(COOK),
            earned,
            bool(terminated.get(COOK, False)),
            bool(truncated.get(COOK, False)),
            {},
        )

    def partner_obs(self):
        return self._numbers(PARTNER)

    def _numbers(self, who):
        found = self.seen.get(who)
        if found is None:
            return []
        return [float(one) for one in found]

    def scene(self):
        """Return one frame of the kitchen as plain data, as the server does.

        CoGrid writes its stepped state back onto the grid objects only when it is
        asked to draw, so a study that read the grid without asking would show the
        opening frame for the whole round.
        """
        self.env._sync_objects_from_state()
        tiles = []
        things = []
        pots = []
        for item in self.env.grid.grid:
            if item is None:
                continue
            kind = type(item).__name__
            where = [int(item.pos[0]), int(item.pos[1])]
            is_pot = isinstance(item, overcooked_grid_objects.Pot)
            if kind in TERRAIN or is_pot:
                tiles.append([TERRAIN.get(kind, "counter.png"), where])
            if is_pot:
                tiles.append(["pot.png", where])
                pots.append([where, len(item.objects_in_pot), int(item.cooking_timer)])
            placed = getattr(item, "obj_placed_on", None)
            for held in (placed, item):
                name = type(held).__name__ if held is not None else ""
                if name in MOVABLE:
                    things.append([MOVABLE[name], where])
        chefs = []
        for chef in self.env.grid.grid_agents.values():
            carried = type(chef.inventory[0]).__name__ if chef.inventory else ""
            chefs.append(
                [
                    [int(chef.pos[0]), int(chef.pos[1])],
                    DIRECTIONS[str(int(chef.dir))],
                    CARRIED.get(carried, ""),
                ]
            )
        return {"tiles": tiles, "things": things, "pots": pots, "chefs": chefs}


def make_env():
    """Build the kitchen this browser runs, and keep it where the partner reads it."""
    global _kitchen
    _kitchen = Kitchen()
    return _kitchen


def _sprite(name, sheet, where, ident, depth=0, tween=None):
    """Return one square of a sprite sheet as a surface command.

    The frame is the name the sheet was packed under, so this bundle carries no
    name-to-index map: the three that used to be injected into its header are gone.
    """
    row, column = where
    found = {
        "op": "image", "id": ident, "relative": True, "image_name": sheet,
        "frame": name,
        "x": column / COLS, "y": row / ROWS,
        "w": 1.0 / COLS, "h": 1.0 / ROWS, "depth": depth,
    }
    if tween is not None:
        found["tween_duration"] = tween
    return found


def draw(_observation):
    """Return the surface commands for the kitchen as it stands, and the status."""
    scene = _kitchen.scene()
    commands = [
        {"op": "rect", "id": "floor", "relative": True, "color": BACKGROUND,
         "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0, "depth": -3}
    ]
    for index, tile in enumerate(scene["tiles"]):
        commands.append(
            _sprite(tile[0], "terrain", tile[1], "tile-" + str(index), depth=-2)
        )
    for index, thing in enumerate(scene["things"]):
        commands.append(
            _sprite(thing[0], "objects", thing[1], "thing-" + str(index), depth=1)
        )
    for index, pot in enumerate(scene["pots"]):
        where, count, timer = pot
        if not count:
            continue
        name = (
            "soup-onion-cooked.png" if timer == 0
            else "soup-onion-" + str(count) + "-cooking.png"
        )
        commands.append(
            _sprite(name, "objects", where, "pot-" + str(index), depth=1)
        )
        if timer and count == 3:
            commands.append({
                "op": "text", "id": "pot-timer-" + str(index), "relative": True,
                "text": "%02d" % timer, "color": "#cc0000", "font_size": 14,
                "x": where[1] / COLS, "y": where[0] / ROWS, "depth": 2,
            })
    for index, chef in enumerate(scene["chefs"]):
        where, facing, carrying = chef
        commands.append(
            _sprite(facing + carrying + ".png", "chefs", where,
                    "chef-" + str(index), depth=1, tween=75)
        )
        commands.append(
            _sprite(facing + "-" + HAT[str(index)] + "hat.png", "chefs",
                    where, "chef-" + str(index) + "-hat", depth=2, tween=75)
        )
    left = max(0, MAX_STEPS - _kitchen.frame) / float(FPS)
    commands.append({
        "op": "rect", "id": "hud-band", "relative": True, "color": "#101418",
        "x": 0.0, "y": 0.0, "w": 1.0, "h": 0.085, "depth": 100,
    })
    commands.append({
        "op": "text", "id": "hud-text", "relative": True, "color": "#f5f7fa",
        "text": "Dishes delivered: %03d     Time left: %.1fs" % (
            _kitchen.delivered, left
        ),
        "font_size": 15, "x": 0.015, "y": 0.061, "depth": 101,
    })
    return commands
'''


def overcooked_browser(
    *,
    layout: str = "cramped_room",
    max_steps: int = 600,
    seed: int = 7,
    decide_every: int = PARTNER_DECIDES_EVERY,
) -> BrowserGameSpec:
    """Return the browser-run kitchen: one person, one exported network, no server.

    The environment steps in the participant's browser through Pyodide and the
    trained policy is scored beside it by the browser's own inference runtime. The
    model is named rather than addressed: ``overcooked-policy`` is a declared study
    asset (see ``overcooked_assets``), and the client resolves the name the same
    way it resolves a sprite.
    """
    cols, rows = _grid_of(layout)
    header = (
        f'LAYOUT = "{layout}"\n'
        f"MAX_STEPS = {max_steps}\nCOLS = {cols}\nROWS = {rows}\nFPS = {FPS}\n"
        f'BACKGROUND = "{KITCHEN_BACKGROUND}"\n'
        f"FEATURES = {list(KITCHEN_FEATURES)!r}\n"
        f"TERRAIN = {_TERRAIN!r}\nMOVABLE = {_MOVABLE!r}\nCARRIED = {_CARRIED!r}\n"
        f"DIRECTIONS = { ({str(k): v for k, v in _DIRECTIONS.items()})!r}\n"
        f"HAT = { ({str(k): v for k, v in _HAT.items()})!r}\n"
    )
    return BrowserGameSpec(
        channel_key="overcooked",
        source_bundle=header + _BROWSER_BUNDLE,
        requires=("numpy", COGRID),
        action_bindings=dict(ACTION_BINDINGS),
        default_action=NOOP,
        input_mode="single_keystroke",
        seed=seed,
        fps=FPS,
        max_steps=max_steps,
        partner=BrowserPartner(
            model=POLICY_ASSET,
            decide_every=decide_every,
            # The legacy study drew the partner's action from the softmax of its
            # scores rather than taking the greatest. A kitchen is full of states
            # where two moves score alike, and a partner that always broke that tie
            # the same way walked the same circle for a whole round.
            selection="sample",
            default_action=NOOP,
        ),
    )


def overcooked_mesh(
    *, layout: str = "cramped_room", max_steps: int = 1350
) -> BrowserMeshSpec:
    """Return the two-person browser kitchen: one layout, two replicas, no server."""
    cols, rows = _grid_of(layout)
    header = (
        f'LAYOUT = "{layout}"\nMAX_STEPS = {max_steps}\nCOLS = {cols}\nROWS = {rows}\n'
    )
    return BrowserMeshSpec(
        channel_key="overcooked",
        source_bundle=header + _MESH_BUNDLE,
        requires=(COGRID, "numpy"),
        action_bindings=dict(ACTION_BINDINGS),
        default_action=NOOP,
        fps=30,
        max_steps=max_steps,
        input_delay=3,
        snapshot_interval=10,
    )


__all__ = [
    "ACTION_BINDINGS",
    "CHEF_ONE",
    "CHEF_TWO",
    "FPS",
    "LAYOUTS",
    "PARTNER_DECIDES_EVERY",
    "CoGridMissing",
    "chef_at",
    "draw_kitchen",
    "kitchen_config",
    "kitchen_hud",
    "kitchen_scene",
    "kitchen_size",
    "make_kitchen",
    "overcooked_browser",
    "overcooked_kitchen",
    "overcooked_mesh",
    "overcooked_scene",
    "render",
]
