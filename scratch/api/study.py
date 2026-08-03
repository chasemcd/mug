"""One study, two environments, three mounts -- and nothing but environments named.

This is the file to read. Run it::

    uv run python scratch/api/study.py

It is the study the current API cannot express, written against the proposed one:

- a **kitchen** (CoGrid Overcooked, a PettingZoo parallel environment) in the
  participant's own browser, with a trained chef beside them;
- a **hill** (Gymnasium MountainCar) stepped on the server, two rounds;
- a **conversation** on its own, about both of them.

Look at what is *not* written. No ``BrowserGameSpec``. No ``source_bundle``. No
``MultiSeatGame``. No ``requires=("numpy", "cogrid==0.3.2")``. No seat-to-index map.
No key bindings for MountainCar, because it declares its own. No drawing for the
kitchen, because CoGrid draws itself. Each activity names the environment its author
trained in, says where it runs and who is in it, and the platform reads the rest.

**Why the current API cannot express it.** The environment does not arrive on the
activity today: ``Game("play")`` names a key and the task comes from
``build_app_from_env(browser_game=...)``. ``mug/app.py:_add_realtime`` resolves nine
mutually exclusive keywords to **one** hook, and that is the only hook a session has,
so every game activity in a study runs the one mounted environment. Two environments
is not difficult; it is unrepresentable.
"""

from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scratch.api.proposed import Bot, Chat, Form, Game, Human, Model, Page, Study
from scratch.api.sprites import Sheet, sheets

# -- the environments, as their authors already have them ---------------------------


def kitchen() -> Any:
    """Build the Overcooked kitchen this study runs.

    A study author's own environment builder, unchanged from what they would write to
    train against it. It is named rather than reimplemented, and the one rule is that
    it reaches nothing of the study: every name it uses it imports itself, from a
    package a participant's browser can install. That rule is checked, and the
    message says which import failed it.

    CoGrid is configured with live reward objects, which is why this is a factory and
    not a class plus settings: a live object has no written form that rebuilds it, and
    it does not need one when it is built where it is used.
    """
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
        "rewards": [DeliveryReward(coefficient=1.0, common_reward=True)],
        "grid": {"layout": "overcooked_cramped_room_v0"},
        "scope": "overcooked",
        "max_steps": 600,
        "pickupable_types": ["onion", "onion_soup", "plate", "tomato", "tomato_soup"],
    }
    with contextlib.suppress(Exception):
        registry.register(
            environment_id="Overcooked-mug-study",
            env_class=functools.partial(
                CoGridEnv, config=config, agent_class=OvercookedAgent
            ),
        )
    return registry.make("Overcooked-mug-study", render_mode="rgb_array")


# The actions, as CoGrid's cardinal action set orders them. An author knows these
# because they trained against them; the platform reads that there are seven.
MOVE_UP, MOVE_DOWN, MOVE_LEFT, MOVE_RIGHT, PICKUP_DROP, TOGGLE, NOOP = range(7)

# The one thing no environment API can say: which key is which action. CoGrid
# declares no ``get_keys_to_action``, so the study says it. MountainCar declares its
# own, and this study says nothing about its keys at all.
KITCHEN_KEYS = {
    "ArrowUp": MOVE_UP,
    "ArrowDown": MOVE_DOWN,
    "ArrowLeft": MOVE_LEFT,
    "ArrowRight": MOVE_RIGHT,
    "w": PICKUP_DROP,
    "q": TOGGLE,
}


# -- the drawing, and the line the participant reads on it --------------------------
#
# The study's own sprites, drawn **by the name each was packed under**. There is no
# name-to-index map, nothing injected into a bundle header, and no second or third
# copy of this function for the browser and the mesh: it references asset names and
# literals only, so its source travels as it stands.
#
# Every name below is checked against the declared sheets by `main()`.

# What one grid square is painted, read from the environment's own class names.
TERRAIN = {
    "Counter": "counter.png",
    "Wall": "counter.png",
    "DeliveryZone": "serve.png",
    "PlateStack": "dishes.png",
    "OnionStack": "onions.png",
}

# What can be put down, picked up, or cooked.
MOVABLE = {
    "Onion": "onion.png",
    "Plate": "dish.png",
    "OnionSoup": "soup-onion-dish.png",
}

# What a chef carries, as the suffix on the chef sprite.
CARRIED = {"Onion": "-onion", "OnionSoup": "-soup-onion", "Plate": "-dish"}

FACING = {0: "EAST", 1: "SOUTH", 2: "WEST", 3: "NORTH"}
HAT = {0: "blue", 1: "green"}

KITCHEN_BACKGROUND = "#e6b453"


def draw_kitchen(surface: Any, state: Any) -> None:
    """Draw one frame of the kitchen: the room, what is in it, then the chefs.

    It reads the live environment. What is **recorded** is the surface commands this
    produces, so a replay redraws the same kitchen from the record with no CoGrid
    installed -- the drawing does not have to be run again.

    Like the environment factory, it imports what it needs inside itself, so its
    source can be carried into a browser run unchanged.
    """
    from cogrid.envs.overcooked import overcooked_grid_objects

    env = state.env
    # CoGrid writes its stepped state back onto the grid objects only when it is asked
    # to draw, so a drawing that read the grid without asking would show the opening
    # frame for the whole round.
    env._sync_objects_from_state()
    rows, cols = env.grid.height, env.grid.width
    width, height = 1.0 / cols, 1.0 / rows

    def sprite(sheet: str, frame: str, pos: Any, ident: str, **extra: Any) -> None:
        # CoGrid counts a position as (row, column) and a screen counts it as (x, y).
        row, column = int(pos[0]), int(pos[1])
        surface.image(
            image_name=sheet,
            frame=frame,
            x=column / cols,
            y=row / rows,
            w=width,
            h=height,
            object_id=ident,
            **extra,
        )

    surface.rect(
        x=0.0,
        y=0.0,
        w=1.0,
        h=1.0,
        color=KITCHEN_BACKGROUND,
        object_id="floor",
        persistent=True,
        depth=-3,
    )

    for item in env.grid.grid:
        if item is None:
            continue
        kind = type(item).__name__
        at = f"{int(item.pos[0])}-{int(item.pos[1])}"
        is_pot = isinstance(item, overcooked_grid_objects.Pot)
        if kind in TERRAIN or is_pot:
            # A pot stands on a counter, so the counter is painted under it.
            sprite(
                "terrain",
                TERRAIN.get(kind, "counter.png"),
                item.pos,
                f"tile-{at}",
                persistent=True,
                depth=-2,
            )
        if is_pot:
            sprite(
                "terrain", "pot.png", item.pos, f"pot-{at}", persistent=True, depth=-1
            )
            _draw_contents(sprite, surface, item, at, cols, rows)
        # Two movable things can share a square -- one on the counter and the
        # counter's own object -- so the role goes in the name as well as the square.
        for role, held in (("on", getattr(item, "obj_placed_on", None)), ("at", item)):
            name = type(held).__name__ if held is not None else ""
            if name in MOVABLE:
                sprite("objects", MOVABLE[name], item.pos, f"{role}-{at}", depth=1)

    for index, chef in enumerate(env.grid.grid_agents.values()):
        facing = FACING[int(chef.dir)]
        carrying = CARRIED.get(
            type(chef.inventory[0]).__name__ if chef.inventory else "", ""
        )
        sprite(
            "chefs",
            f"{facing}{carrying}.png",
            chef.pos,
            f"chef-{index}",
            tween_duration=75,
            depth=1,
        )
        sprite(
            "chefs",
            f"{facing}-{HAT[index]}hat.png",
            chef.pos,
            f"chef-{index}-hat",
            tween_duration=75,
            depth=2,
        )


def _draw_contents(
    sprite: Any, surface: Any, pot: Any, at: str, cols: int, rows: int
) -> None:
    """Draw what is cooking in one pot, and how long is left of it."""
    count = len(pot.objects_in_pot)
    if not count:
        return
    timer = int(pot.cooking_timer)
    frame = "soup-onion-cooked.png" if timer == 0 else f"soup-onion-{count}-cooking.png"
    sprite("objects", frame, pot.pos, f"pot-{at}-contents", depth=1)
    if timer and count == 3:
        # The countdown only means anything on a full pot. A timer over a half-full
        # one would say the soup was nearly ready when it had not started.
        surface.text(
            x=int(pot.pos[1]) / cols,
            y=int(pot.pos[0]) / rows,
            text=f"{timer:02d}",
            color="#cc0000",
            font_size=14,
            object_id=f"pot-{at}-timer",
        )


def kitchen_hud(state: Any) -> str:
    """Return the line the cook reads while they work: dishes, and time left.

    One line. The platform draws the band across the top, so this is the whole of what
    a study writes -- where today the same band and text are hand-written a second and
    a third time inside each browser bundle (`examples/cogrid/env.py` 743-752, 970-979)
    because the platform's own `draw_hud` cannot travel.
    """
    delivered = int(state.info.get("delivered", 0))
    left = float(state.info.get("seconds_left", 0.0))
    return f"Dishes delivered: {delivered:03d}     Time left: {left:.1f}s"


class Debriefer:
    """The model the participant talks to after they have played both games.

    A stand-in for an ``LLMAgent`` subclass so this file runs with no provider
    configured. It is written the same way a game's model seat is: the pinned build,
    the recorded actor, and the provider adapter are all derived at the mount.
    """

    key = "debriefer"


def _trained_chef() -> Any:
    """Stand in for the exported Overcooked policy this study seats."""
    return "overcooked-policy"


def hill() -> Any:
    """Build the MountainCar the participant drives.

    A registered Gymnasium environment, bound rather than named as a string: what a
    game activity takes is always something callable that returns an environment, so
    there is one kind of thing to hand over rather than three. ``render_mode`` is bound
    here because the platform passes nothing into a callable it was told takes no
    arguments.
    """
    import gymnasium

    return gymnasium.make("MountainCar-v0", render_mode="rgb_array")


# ``functools.partial(gymnasium.make, "MountainCar-v0", render_mode="rgb_array")`` is
# the same thing written shorter, and it has one advantage: a partial writes itself
# down, so nothing of the study has to travel to rebuild it. ``derive.py`` reads one.


def _draw_hill(surface: Any, state: Any) -> None:
    """Draw the car on the hill.

    MountainCar lists ``rgb_array`` and draws it with pygame, which is not installed
    here and cannot be installed in a browser, so its own frames are not available.
    The platform says so and asks for a drawing, rather than showing an empty canvas.
    """


# -- the study ----------------------------------------------------------------------

CONSENT = "I have read the information sheet and agree to take part."

INSTRUCTIONS = """
# Two tasks, then a conversation

First you will run a kitchen with an AI teammate. Then you will drive a car up a
hill. Then we will talk about both.

The kitchen runs in this browser, so it may take a moment to get ready.
"""

CHANGEOVER = "# Nice work\n\nThat is the kitchen finished. The hill is quite different."

COOK_CAPTION = """
You are the **blue chef**. Arrows move, **W** picks up and puts down, **Q** uses a
station. Your teammate is an AI.
"""

DRIVE_CAPTION = "Rock the car with the **left** and **right** arrows to reach the flag."

GREETING = "You have just played two very different games. How did they feel?"

DEBRIEF = """
# Thank you

Your kitchen teammate was a trained network that ran in your own browser. The hill
ran on our server.
"""


def mixed_study() -> Study:
    """Return the ordered activities one participant walks through."""
    return Study(
        Form("consent", CONSENT),
        Page("instructions", INSTRUCTIONS),
        # A PettingZoo kitchen, in the participant's own browser, with a trained chef
        # beside them. The chef is on the seating, so the same Bot(...) would be
        # scored by the application if this activity ran on the server.
        Game(
            "cook",
            kitchen,
            runs="browser",
            seats={0: Human(), 1: Bot(_trained_chef(), decides_every=5)},
            keys=KITCHEN_KEYS,
            # A kitchen is a grid, so one press is one move. Held actions would make a
            # tap of the pick-up key put a dish down and take it back thirty times a
            # second, and a tap of an arrow cross the room.
            held_actions=False,
            default_action=NOOP,
            # The study's own sprites, drawn by name, and one line of status. Without
            # these two the environment's own rgb_array frames are painted instead --
            # which is a working game with no code at all, and no sprites.
            render=draw_kitchen,
            hud=kitchen_hud,
            # The four sheets this drawing names, declared on the activity that draws
            # them. Each is one image and the atlas beside it; the platform reads the
            # atlas. They load before the kitchen and not before the hill.
            assets=sheets(),
            caption=COOK_CAPTION,
        ),
        Page("changeover", CHANGEOVER),
        # A Gymnasium environment, stepped on the server, two rounds. It declares its
        # own bindings through the gymnasium.utils.play convention, so this activity
        # says nothing about keys.
        Game(
            "drive",
            hill,
            runs="server",
            seats={"agent": Human()},
            render=_draw_hill,
            episodes=2,
            between="Take a moment, then drive again.",
            caption=DRIVE_CAPTION,
        ),
        # A conversation, on its own. A Chat, not a Game with the game taken out.
        Chat("reflect", Model(Debriefer()), greeting=GREETING, max_messages=12),
        Form("post-survey", "Which task did you prefer?"),
        Page("debrief", DEBRIEF),
        # Nothing study-wide. A picture an instruction page shows would go here, and
        # would load before every activity because every activity may show it.
    )


def one_environment_two_ways() -> Study:
    """Return a study that plays one environment on the server and in the browser.

    A practice round the application steps, and then the real round in the
    participant's own browser. Unrepresentable today, because the execution belongs to
    the deployment rather than to the activity.
    """
    seating = {0: Human(), 1: Bot(_trained_chef())}
    # Both activities draw the same kitchen, so both declare the same sheets. That is
    # allowed and read once: what is refused is one name standing for two files.
    drawn = sheets()
    return Study(
        Game(
            "practice",
            kitchen,
            runs="server",
            seats=seating,
            keys=KITCHEN_KEYS,
            held_actions=False,
            default_action=NOOP,
            render=draw_kitchen,
            assets=drawn,
        ),
        Game(
            "real",
            kitchen,
            runs="browser",
            seats=seating,
            keys=KITCHEN_KEYS,
            held_actions=False,
            default_action=NOOP,
            render=draw_kitchen,
            assets=drawn,
        ),
    )


# -- what an author is refused, while they read their own code ----------------------


def refusals() -> list[tuple[str, str]]:
    """Return each refusal and the message it gives, by provoking it."""
    found: list[tuple[str, str]] = []

    def caught(what: str, write: Any) -> None:
        try:
            write()
        except (TypeError, ValueError) as refused:
            found.append((what, str(refused)))
        else:  # pragma: no cover - a refusal that did not fire is the bug
            found.append((what, "NOT REFUSED -- the design is wrong here"))

    caught(
        "a seat the environment does not have",
        lambda: Game(
            "cook",
            kitchen,
            seats={0: Human(), 2: Bot(_trained_chef())},
            keys=KITCHEN_KEYS,
            held_actions=False,
            default_action=NOOP,
        ),
    )
    caught(
        "a person at a keyboard bound to nothing",
        lambda: Game("cook", kitchen, seats={0: Human(), 1: Bot(_trained_chef())}),
    )
    caught(
        "keys bound without saying how they act",
        lambda: Game("cook", kitchen, seats={0: Human()}, keys=KITCHEN_KEYS),
    )
    caught(
        "rounds a browser run plays once",
        lambda: Game(
            "cook",
            kitchen,
            runs="browser",
            episodes=3,
            seats={0: Human()},
            keys=KITCHEN_KEYS,
            held_actions=False,
            default_action=NOOP,
        ),
    )
    caught(
        "a model seat where no provider can be reached",
        lambda: Game(
            "cook",
            kitchen,
            runs="browser",
            seats={0: Human(), 1: Model(Debriefer())},
            keys=KITCHEN_KEYS,
            held_actions=False,
            default_action=NOOP,
        ),
    )
    caught(
        "something that is not callable at all",
        lambda: Game("cook", "MountainCar-v0"),  # pyright: ignore[reportArgumentType]
    )
    caught(
        "a callable returning something that is not one of the three APIs",
        lambda: Game("cook", _pretender),
    )
    caught(
        "one picture name standing for two different files",
        lambda: Study(
            _cook(assets=sheets()),
            _cook(key="cook-again", assets=[_other_terrain()]),
        ),
    )
    caught(
        "a person with no picture at all",
        lambda: Game(
            "balance",
            "CartPole-v1",
            seats={"agent": Human()},
            keys={"ArrowLeft": 0, "ArrowRight": 1},
            held_actions=True,
            default_action=0,
        ),
    )
    return found


class _Recorder:
    """A surface that records what it was asked to draw, so a drawing can be watched.

    A drawing is only real once something has read what it produced. The platform's own
    surface builds a render packet; this one keeps the calls, which is all that is
    needed to see whether a frame is drawn, where, and by which name.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def image(self, **command: Any) -> None:
        """Record one sprite."""
        self.calls.append({"op": "image", **command})

    def rect(self, **command: Any) -> None:
        """Record one rectangle."""
        self.calls.append({"op": "rect", **command})

    def text(self, **command: Any) -> None:
        """Record one line of text."""
        self.calls.append({"op": "text", **command})


def _watch_one_frame() -> None:
    """Run the drawing against a live kitchen and report what it produced.

    Every frame name it emits is checked against the declared sheets, so this is the
    whole loop closed: the study declares four sheets, the drawing names frames inside
    them, and a name that is not there is found here rather than as a hole in a canvas
    a participant is looking at.
    """
    env = kitchen()
    env.reset(seed=1)
    surface = _Recorder()
    draw_kitchen(surface, _Step(env, {}))

    declared = {sheet.name: sheet for sheet in sheets()}
    drawn = [one for one in surface.calls if one["op"] == "image"]
    kinds: dict[str, int] = {}
    unknown: list[str] = []
    for one in drawn:
        sheet, frame = one["image_name"], one["frame"]
        kinds[f"{sheet}/{frame}"] = kinds.get(f"{sheet}/{frame}", 0) + 1
        if frame not in declared[sheet].frames:
            unknown.append(f"{sheet}/{frame}")

    print(
        f"  {len(surface.calls)} commands: {len(drawn)} sprites on a "
        f"{env.grid.width}x{env.grid.height} grid"
    )
    for named, count in sorted(kinds.items()):
        print(f"    {count:2}x  {named}")
    if unknown:
        print(f"  UNKNOWN FRAMES: {', '.join(sorted(set(unknown)))}")
    else:
        print("  every frame it drew exists in the sheet it named")
    print(f"  hud: {kitchen_hud(_Step(env, {}))!r}")


@dataclass(frozen=True)
class _Step:
    """What a drawing receives: the environment now, and the frame's own metrics."""

    env: Any
    info: dict[str, Any]


def _check_frames() -> None:
    """Check every frame name `draw_kitchen` can emit against the declared sheets.

    This is the check the filename addressing makes possible at all. With an integer
    index there is nothing to check: every index is a valid number, and a re-packed
    sheet draws the wrong picture in silence.
    """
    declared = {sheet.name: sheet for sheet in sheets()}
    named: list[tuple[str, str]] = [("terrain", "pot.png")]
    named += [("terrain", one) for one in sorted(set(TERRAIN.values()))]
    named += [("objects", one) for one in sorted(set(MOVABLE.values()))]
    named += [("objects", "soup-onion-cooked.png")]
    named += [("objects", f"soup-onion-{n}-cooking.png") for n in (1, 2, 3)]
    named += [
        ("chefs", f"{facing}{carrying}.png")
        for facing in FACING.values()
        for carrying in ("", *CARRIED.values())
    ]
    named += [
        ("chefs", f"{facing}-{hat}hat.png")
        for facing in FACING.values()
        for hat in HAT.values()
    ]
    missing = [
        f"{sheet}/{frame}"
        for sheet, frame in named
        if frame not in declared[sheet].frames
    ]
    print(f"  {len(named)} frame names across {len(declared)} sheets")
    if missing:
        print(f"  MISSING: {', '.join(missing)}")
    else:
        print("  every one of them exists in the sheet it names")


def _pretender() -> Any:
    """Return something with step and reset that is not an environment.

    Research code is full of these, and the platform used to accept one by shape. It
    is refused now: whether an object is a Gymnasium environment, a PettingZoo parallel
    one, or a PettingZoo AEC one decides how every other derivation is read -- which
    agents there are, how an action is passed, whether a turn is taken.
    """

    class Pretender:
        def reset(self, **_kwargs: Any) -> Any:
            return None, {}

        def step(self, _action: Any) -> Any:
            return None, 0.0, False, False, {}

    return Pretender()


def _cook(*, key: str = "cook", assets: Any) -> Any:
    """Return the kitchen activity, for a refusal that needs two of them."""
    return Game(
        key,
        kitchen,
        seats={0: Human(), 1: Bot(_trained_chef())},
        keys=KITCHEN_KEYS,
        held_actions=False,
        default_action=NOOP,
        render=draw_kitchen,
        assets=assets,
    )


def _other_terrain() -> Sheet:
    """Return a second sheet that claims the name the kitchen's terrain already has."""
    return Sheet(
        name="terrain",
        image="somewhere/else/terrain.png",
        atlas="somewhere/else/terrain.json",
        frames={"counter.png": (0, 0, 16, 16)},
    )


def main() -> None:
    """Print what the study resolves to, then every refusal."""
    print("one study, two environments, three mounts -- nothing but environments named")
    print("=" * 78)
    study = mixed_study()
    for line in study.plan():
        print("  " + line)
    print()
    print(f"  requires (derived, merged, pinned): {list(study.requires)}")
    print(f"  pictures the study serves: {len(study.assets)}")
    print(f"  study-wide, loaded before everything: {len(study.study_wide)}")
    for one in study.activities:
        if one.kind == "game":
            named = ", ".join(sheet.name for sheet in study.assets_for(one.key))
            print(f"  before {one.key!r}: {named or 'nothing'}")
    print()

    print("one environment, two executions")
    print("=" * 78)
    twice = one_environment_two_ways()
    for line in twice.plan():
        print("  " + line)
    print(
        f"  the same four sheets, declared twice and served once: {len(twice.assets)}"
    )
    print()

    print("every sprite the drawing can name, checked against the declared sheets")
    print("=" * 78)
    _check_frames()
    print()

    print("the drawing, run against a live kitchen")
    print("=" * 78)
    _watch_one_frame()
    print()

    print("what an author is refused, while they read their own code")
    print("=" * 78)
    for what, message in refusals():
        print(f"  {what}")
        print(f"    {message}")
        print()


if __name__ == "__main__":
    main()
