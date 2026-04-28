"""OvercookedV2 TestTimeSimple environment with partial observability.

Wraps cogrid 0.3.0's ``OvercookedV2-TestTimeSimple-V0`` registration with a
MUG-compatible ``render`` that produces an *agent-centred* 5x5 viewport. Each
agent's view spans a Chebyshev radius of 2 around their own cell; cells
outside the world grid render as void. The viewport scrolls with the agent,
matching the ``local_view`` observation tensor that V2 RL agents see.

Sprite policy: reuse the existing Overcooked V1 atlases (terrain, chefs,
objects) for the items they cover (counter, pot, serve, dishes, onion,
tomato, plate, onion-soup, tomato-soup, all chef poses). New V2 ingredients
(broccoli, mushroom) and mixed soups have no sprites, so they fall back to
vector primitives.

This file is executed by Pyodide to create the ``env`` variable at module
scope.
"""
from __future__ import annotations

import collections
import copy
import functools
import logging

from cogrid.cogrid_env import CoGridEnv
from cogrid.core.objects.builtins import Counter, Wall
from cogrid.envs import registry
from cogrid.envs.overcooked import v2_objects  # registers V2 object types
from cogrid.envs.overcooked.agent import OvercookedAgent
from cogrid.envs.overcooked.overcooked_grid_objects import (
    Onion,
    OnionSoup,
    OnionStack,
    Plate,
    PlateStack,
    Tomato,
    TomatoSoup,
    TomatoStack,
)
from cogrid.envs.overcooked.v2_objects import (
    Broccoli,
    BroccoliStack,
    ButtonIndicator,
    Mushroom,
    MushroomStack,
    OpenDeliveryZone,
    OpenPot,
    RecipeIndicator,
)

from mug.rendering import Surface

logger = logging.getLogger(__name__)

SOURCE_ENV_ID = "OvercookedV2-TestTimeSimple-V0"
ENV_ID = f"{SOURCE_ENV_ID}-MUG"

ASSET_PATH = "examples/cogrid/assets/overcooked/sprites"

VIEW_RADIUS = 2
VIEW_DIAM = 2 * VIEW_RADIUS + 1  # 5x5 window
TILE_SIZE = 60
WIDTH = VIEW_DIAM * TILE_SIZE
HEIGHT = VIEW_DIAM * TILE_SIZE

# Render one cell beyond the visible viewport on each side so that sprites
# entering or leaving the visible area can tween from / to off-canvas
# positions instead of popping in / out. The 7x7 ring is rendered every
# frame; cells outside the canvas (fractional x or y outside [0, 1]) are
# clipped by Phaser at draw time.
BUFFER = 1
RENDER_DIAM = VIEW_DIAM + 2 * BUFFER  # 7x7 effective render area

# Sprite tween duration (ms). Matches V1's chef-sprite tween. At fps=30 the
# tween covers ~2.3 frames, so each step glides smoothly into the next.
TWEEN_MS = 75

# cogrid direction enum -> sprite atlas direction string.
DIR_TO_CARDINAL = {0: "EAST", 1: "SOUTH", 2: "WEST", 3: "NORTH"}

INGREDIENT_COLORS = {
    "onion": "#F5C518",
    "tomato": "#D63A2F",
    "broccoli": "#228B22",
    "mushroom": "#8B5A2B",
}

# Recipe indicator dot colors mirror cogrid v2_objects._RECIPE_DOT_COLORS so
# the indicator state (1 = onion_soup, 2 = tomato_soup, ...) reads correctly.
RECIPE_DOT_COLORS = {
    1: "#F5C518",  # onion_soup
    2: "#D63A2F",  # tomato_soup
    3: "#228B22",  # broccoli-based
    4: "#8B5A2B",  # mushroom-based
}

# Hat colors per agent_id for the chef sprite overlay.
AGENT_HAT_COLORS = {0: "blue", 1: "green"}
AGENT_HAT_FALLBACK = "red"

FLOOR_COLOR = "#F5EFE0"
VOID_COLOR = "#1A1A1A"
PLATE_COLOR = "#F5F5F5"
INDICATOR_BG = "#5F7CC8"
BUTTON_BG_ACTIVE = "#C77CD0"
BUTTON_BG_INACTIVE = "#503266"

# Held-item suffix on chef sprites. Frames named ``{DIR}{suffix}.png`` exist
# only for these items; everything else falls back to a plain chef sprite
# plus a vector overlay drawn on top.
SPRITE_HELD_SUFFIX = {
    "onion": "-onion",
    "tomato": "-tomato",
    "plate": "-dish",
    "onion_soup": "-soup-onion",
    "tomato_soup": "-soup-tomato",
}


def _key(obj) -> str:
    """Stable per-frame ID for an object.

    cogrid 0.3.0 grid objects expose ``object_id`` (a class-name string, not
    unique) rather than a per-instance uuid. Grid-anchored objects have a
    stable ``pos`` we can key off; loose / inventory items fall back to
    Python's ``id()`` since they only need to be unique *within* a frame
    (the surface is reset every render).
    """
    pos = getattr(obj, "pos", None)
    if pos is not None:
        return f"{pos[0]}-{pos[1]}"
    return f"i{id(obj)}"


def _ingredient_kind(obj):
    """Return the ingredient family or None."""
    if isinstance(obj, Onion):
        return "onion"
    if isinstance(obj, Tomato):
        return "tomato"
    if isinstance(obj, Broccoli):
        return "broccoli"
    if isinstance(obj, Mushroom):
        return "mushroom"
    return None


def _carry_kind(obj):
    """Identify a carryable item by family for sprite-suffix lookup.

    Returns one of ``onion``, ``tomato``, ``plate``, ``onion_soup``,
    ``tomato_soup``, ``broccoli``, ``mushroom``, ``mixed_soup``, ``unknown``.
    """
    ing = _ingredient_kind(obj)
    if ing is not None:
        return ing
    if isinstance(obj, Plate):
        return "plate"
    if isinstance(obj, OnionSoup):
        return "onion_soup"
    if isinstance(obj, TomatoSoup):
        return "tomato_soup"
    # v2_objects.make_soup() generates classes for mixed soups at runtime; they
    # subclass the base GridObj and are pickupable but have no V1 sprite.
    return "mixed_soup"


def _soup_color(obj):
    """Return a hex color for a plated soup (used for vector fallback)."""
    if isinstance(obj, OnionSoup):
        return INGREDIENT_COLORS["onion"]
    if isinstance(obj, TomatoSoup):
        return INGREDIENT_COLORS["tomato"]
    color = getattr(obj, "color", None)
    if isinstance(color, tuple) and len(color) == 3:
        return "#{:02X}{:02X}{:02X}".format(*color)
    return "#888888"


class OvercookedV2PartialObsEnv(CoGridEnv):
    """CoGridEnv subclass that renders an agent-centred 5x5 viewport.

    Each render is keyed by ``agent_id``: every cell drawn is the world cell
    in the requesting agent's 5x5 Chebyshev neighbourhood. World cells outside
    the viewport are not transmitted; viewport cells outside the world grid
    are rendered as ``VOID_COLOR`` so the player can sense map boundaries.
    """

    def __init__(self, config, render_mode=None, **kwargs):
        kwargs.setdefault("agent_class", OvercookedAgent)
        super().__init__(config, render_mode=render_mode, **kwargs)
        self.surface = Surface(width=WIDTH, height=HEIGHT)
        self.surface.register_atlas(
            "terrain",
            img_path=f"{ASSET_PATH}/terrain.png",
            json_path=f"{ASSET_PATH}/terrain.json",
        )
        self.surface.register_atlas(
            "chefs",
            img_path=f"{ASSET_PATH}/chefs.png",
            json_path=f"{ASSET_PATH}/chefs.json",
        )
        self.surface.register_atlas(
            "objects",
            img_path=f"{ASSET_PATH}/objects.png",
            json_path=f"{ASSET_PATH}/objects.json",
        )
        # Mixed onion+tomato pot frames live in a separate atlas with names
        # like ``soup_idle_tomato_2_onion_1.png`` -- registered so the pot
        # render can reach them when the contents are a mix.
        self.surface.register_atlas(
            "soups",
            img_path=f"{ASSET_PATH}/soups.png",
            json_path=f"{ASSET_PATH}/soups.json",
        )

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def render(self, *, agent_id=None):
        assert self.render_mode == "mug"

        # Default to the first agent if the caller didn't pass one. Keeps the
        # canvas size stable for spectators / unit tests; logged so misuse is
        # discoverable. ``env.reset()`` calls render() internally with no
        # args, so this branch fires every episode start.
        if agent_id is None or agent_id not in self.grid.grid_agents:
            if agent_id is not None:
                logger.warning(
                    "OvercookedV2PartialObsEnv.render: unknown agent_id=%r, "
                    "falling back to first agent",
                    agent_id,
                )
            agent_id = next(iter(self.grid.grid_agents))

        # Reset per-frame: the viewport scrolls with the agent, so persistent
        # caching would mis-target IDs that referred to a different world
        # cell last frame.
        self.surface.reset()

        viewer = self.grid.grid_agents[agent_id]
        ar, ac = viewer.pos
        r0 = ar - VIEW_RADIUS
        c0 = ac - VIEW_RADIUS

        def in_buffer(world_pos) -> bool:
            """World cell falls within the rendered (visible + buffer) area."""
            wr, wc = world_pos
            return (
                r0 - BUFFER <= wr < r0 + VIEW_DIAM + BUFFER
                and c0 - BUFFER <= wc < c0 + VIEW_DIAM + BUFFER
            )

        def to_xy(world_pos) -> tuple[float, float]:
            """World cell -> top-left (x, y) in 0..1 canvas fractions.

            Cells in the buffer ring map to negative or >1 fractions; that's
            intentional -- Phaser positions the sprite off-canvas where it's
            clipped, but a position-tween from off-canvas into the visible
            area (or vice versa) animates smoothly when the agent moves.
            """
            wr, wc = world_pos
            return (wc - c0) / VIEW_DIAM, (wr - r0) / VIEW_DIAM

        # 1. Tile background: floor for in-world cells, void for out-of-world.
        self._draw_background(r0, c0)

        # 2. Static / placed objects in the buffered render area. Buffer
        # rendering means a cell at the visible edge that's about to scroll
        # off-screen still has a UUID at off-canvas position next frame, so
        # Phaser tweens its slide-out instead of destroying it abruptly.
        for obj in self.grid.grid:
            if obj is None or not in_buffer(obj.pos):
                continue
            self._draw_object(obj, to_xy(obj.pos))

        # 3. Partner agents -- buffered too, so a partner crossing the
        # viewport boundary slides in / out smoothly with the rest of the
        # world. The wire packet contains their state at off-canvas positions
        # one cell beyond the agent's actual vision radius (visible only via
        # devtools / network inspection); acceptable for our study contexts.
        for aid, agent_obj in self.grid.grid_agents.items():
            if aid == agent_id:
                continue
            if not in_buffer(agent_obj.pos):
                continue
            self._draw_agent(aid, agent_obj, to_xy(agent_obj.pos), is_self=False)

        # 4. Self -- always at viewport center (2, 2).
        self._draw_agent(
            agent_id,
            viewer,
            (VIEW_RADIUS / VIEW_DIAM, VIEW_RADIUS / VIEW_DIAM),
            is_self=True,
        )

        return self.surface.commit().to_dict()

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------
    def _draw_background(self, r0: int, c0: int) -> None:
        # World-stable IDs (``bg-w{wr}-{wc}``) so Phaser tweens each tile's
        # screen position when the viewport scrolls instead of destroying
        # the old one and creating a new one. Iterating BUFFER + 5 + BUFFER
        # gives off-canvas tiles ready to slide into view next step.
        cell = 1.0 / VIEW_DIAM
        for vr in range(-BUFFER, VIEW_DIAM + BUFFER):
            for vc in range(-BUFFER, VIEW_DIAM + BUFFER):
                wr = r0 + vr
                wc = c0 + vc
                in_world = 0 <= wr < self.grid.height and 0 <= wc < self.grid.width
                color = FLOOR_COLOR if in_world else VOID_COLOR
                self.surface.rect(
                    id=f"bg-w{wr}-{wc}",
                    x=vc * cell,
                    y=vr * cell,
                    w=cell,
                    h=cell,
                    color=color,
                    relative=True,
                    depth=-10,
                    tween_duration=TWEEN_MS,
                )

    def _draw_object(self, obj, xy: tuple[float, float]) -> None:
        x, y = xy
        cell = 1.0 / VIEW_DIAM

        if isinstance(obj, (Counter, Wall)):
            self._draw_counter_tile(obj, x, y, cell)
            if isinstance(obj, Counter) and obj.obj_placed_on is not None:
                # ``obj_placed_on`` is re-instantiated each render sync so
                # ``id(obj)``-based keys would churn every frame. Anchor the
                # placed item to its host counter's world position for a
                # stable, tween-able UUID.
                self._draw_floor_item(
                    obj.obj_placed_on,
                    x,
                    y,
                    cell,
                    key_override=f"on-counter-{_key(obj)}",
                )
            return

        # Static fixtures sit on a counter visually; draw the counter sprite
        # underneath so they read as kitchen surfaces, not floor.
        if isinstance(
            obj,
            (
                OnionStack,
                TomatoStack,
                BroccoliStack,
                MushroomStack,
                PlateStack,
                OpenPot,
                OpenDeliveryZone,
                RecipeIndicator,
                ButtonIndicator,
            ),
        ):
            self._draw_counter_tile(obj, x, y, cell)

        if isinstance(obj, OnionStack):
            self._draw_terrain_sprite("onions.png", obj, x, y, cell)
        elif isinstance(obj, TomatoStack):
            self._draw_terrain_sprite("tomatoes.png", obj, x, y, cell)
        elif isinstance(obj, BroccoliStack):
            self._draw_vector_stack(obj, x, y, cell, "broccoli")
        elif isinstance(obj, MushroomStack):
            self._draw_vector_stack(obj, x, y, cell, "mushroom")
        elif isinstance(obj, PlateStack):
            self._draw_terrain_sprite("dishes.png", obj, x, y, cell)
        elif isinstance(obj, OpenPot):
            self._draw_pot(obj, x, y, cell)
        elif isinstance(obj, OpenDeliveryZone):
            self._draw_terrain_sprite("serve.png", obj, x, y, cell)
        elif isinstance(obj, RecipeIndicator):
            self._draw_recipe_indicator(obj, x, y, cell)
        elif isinstance(obj, ButtonIndicator):
            self._draw_button_indicator(obj, x, y, cell)
        else:
            # Loose item dropped on the floor (rare in V2 layouts but safe).
            self._draw_floor_item(obj, x, y, cell)

    def _draw_counter_tile(self, obj, x: float, y: float, cell: float) -> None:
        # Sprite x/y are fractional (0..1) but w/h are pixels: the JS renderer
        # multiplies x/y by canvas size and feeds w/h straight to
        # setDisplaySize. ``cell`` is the fractional position step used by
        # rects/circles; sprites use ``TILE_SIZE`` for size instead.
        self.surface.image(
            id=f"counter-{_key(obj)}",
            x=x,
            y=y,
            w=TILE_SIZE,
            h=TILE_SIZE,
            image_name="terrain",
            frame="counter.png",
            relative=True,
            depth=-5,
            tween_duration=TWEEN_MS,
        )

    def _draw_terrain_sprite(
        self, frame: str, obj, x: float, y: float, cell: float
    ) -> None:
        self.surface.image(
            id=f"terrain-{frame[:-4]}-{_key(obj)}",
            x=x,
            y=y,
            w=TILE_SIZE,
            h=TILE_SIZE,
            image_name="terrain",
            frame=frame,
            relative=True,
            depth=-3,
            tween_duration=TWEEN_MS,
        )

    def _draw_vector_stack(
        self, obj, x: float, y: float, cell: float, kind: str
    ) -> None:
        """Vector fallback for ingredient stacks without sprites (broccoli, mushroom).

        Distinguished by ingredient color alone -- a text label looked good
        statically but tweened poorly when the viewport scrolled (Phaser
        re-rasterizes text on each tween step, producing visible jitter).
        """
        cx = x + cell / 2
        cy = y + cell / 2
        # ID keyed by world position (via ``_key(obj)``) -- not viewport
        # fraction -- so the same stack tweens across frames as the viewport
        # scrolls.
        self.surface.circle(
            id=f"stack-{kind}-{_key(obj)}",
            x=cx,
            y=cy,
            radius=cell * 0.32,
            color=INGREDIENT_COLORS[kind],
            stroke_color="#000000",
            stroke_width=1,
            relative=True,
            depth=-3,
            tween_duration=TWEEN_MS,
        )

    def _draw_pot(self, obj: OpenPot, x: float, y: float, cell: float) -> None:
        # Pot body always renders via the V1 terrain sprite -- same silhouette
        # as standard Overcooked.
        self.surface.image(
            id=f"pot-{_key(obj)}",
            x=x,
            y=y,
            w=TILE_SIZE,
            h=TILE_SIZE,
            image_name="terrain",
            frame="pot.png",
            relative=True,
            depth=-2,
            tween_duration=TWEEN_MS,
        )

        ingredients = list(getattr(obj, "objects_in_pot", []))
        if not ingredients:
            return  # empty pot is just the body sprite

        capacity = getattr(obj, "capacity", 3)
        timer = int(getattr(obj, "cooking_timer", 0))
        contents_id = f"pot-{_key(obj)}-contents"
        atlas, frame = self._pot_contents_frame(ingredients, capacity, timer)

        if atlas is not None:
            # Pre-rendered sprite covers this combo / state.
            self.surface.image(
                id=contents_id,
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name=atlas,
                frame=frame,
                relative=True,
                depth=1,
                tween_duration=TWEEN_MS,
            )
        else:
            # Vector fallback: any pot containing broccoli, mushroom, or other
            # ingredients without dedicated art. Draw colored dots inside the
            # pot so the player can still read the contents.
            cx = x + cell / 2
            cy = y + cell * 0.45
            for i, ing in enumerate(ingredients):
                kind = _ingredient_kind(ing)
                color = INGREDIENT_COLORS.get(kind, "#888888")
                offset = (i - (len(ingredients) - 1) / 2) * cell * 0.18
                self.surface.circle(
                    id=f"pot-{_key(obj)}-ing-{i}",
                    x=cx + offset,
                    y=cy,
                    radius=cell * 0.10,
                    color=color,
                    stroke_color="#000000",
                    stroke_width=1,
                    relative=True,
                    depth=1,
                    tween_duration=TWEEN_MS,
                )

        if len(ingredients) >= capacity:
            self.surface.text(
                id=f"pot-{_key(obj)}-timer",
                text=f"{timer:02d}",
                x=x + cell / 2,
                y=y + cell * 0.72,
                size=14,
                color="#FF5050" if timer > 0 else "#80FF80",
                relative=True,
                depth=2,
                tween_duration=TWEEN_MS,
            )

    def _pot_contents_frame(
        self, ingredients: list, capacity: int, timer: int
    ) -> tuple[str | None, str | None]:
        """Pick the right sprite for the current pot contents.

        Returns ``(atlas, frame)`` for sprite rendering, or ``(None, None)``
        if no sprite covers this combo (caller must vector-fallback). Naming
        conventions differ between atlases -- ``objects`` uses
        ``soup-{kind}-{count}-cooking`` / ``soup-{kind}-cooked`` for pure
        onion or pure tomato pots, while ``soups`` uses
        ``soup_{idle|cooked|done}_tomato_{T}_onion_{O}`` for mixed pots.
        """
        counts = collections.Counter(_ingredient_kind(ing) for ing in ingredients)
        n = len(ingredients)

        # Pure-onion or pure-tomato: V1 objects atlas covers all states.
        for kind in ("onion", "tomato"):
            if counts.get(kind) == n:
                if timer == 0 and n >= capacity:
                    return "objects", f"soup-{kind}-cooked.png"
                return "objects", f"soup-{kind}-{n}-cooking.png"

        # Mixed onion+tomato (no broccoli/mushroom): use the soups atlas.
        if counts.get("broccoli", 0) == 0 and counts.get("mushroom", 0) == 0:
            T = counts.get("tomato", 0)
            O = counts.get("onion", 0)
            if T + O == n and (T > 0 and O > 0):
                if n < capacity:
                    state = "idle"
                elif timer == 0:
                    state = "done"
                else:
                    state = "cooked"
                return "soups", f"soup_{state}_tomato_{T}_onion_{O}.png"

        # Broccoli, mushroom, or any combination involving them -- no sprite.
        return None, None

    def _draw_recipe_indicator(self, obj, x: float, y: float, cell: float) -> None:
        self.surface.rect(
            id=f"recipe-{_key(obj)}-bg",
            x=x + cell * 0.1,
            y=y + cell * 0.1,
            w=cell * 0.8,
            h=cell * 0.8,
            color=INDICATOR_BG,
            border_radius=4,
            relative=True,
            depth=-2,
            tween_duration=TWEEN_MS,
        )
        dot_color = RECIPE_DOT_COLORS.get(int(getattr(obj, "state", 0)))
        if dot_color is not None:
            self.surface.circle(
                id=f"recipe-{_key(obj)}-dot",
                x=x + cell * 0.5,
                y=y + cell * 0.5,
                radius=cell * 0.18,
                color=dot_color,
                relative=True,
                depth=-1,
                tween_duration=TWEEN_MS,
            )

    def _draw_button_indicator(self, obj, x: float, y: float, cell: float) -> None:
        active = int(getattr(obj, "state", 0)) > 0
        self.surface.rect(
            id=f"button-{_key(obj)}-bg",
            x=x + cell * 0.1,
            y=y + cell * 0.1,
            w=cell * 0.8,
            h=cell * 0.8,
            color=BUTTON_BG_ACTIVE if active else BUTTON_BG_INACTIVE,
            border_radius=4,
            relative=True,
            depth=-2,
            tween_duration=TWEEN_MS,
        )
        self.surface.circle(
            id=f"button-{_key(obj)}-knob",
            x=x + cell * 0.5,
            y=y + cell * 0.5,
            radius=cell * 0.16,
            color="#FFFFFF" if active else "#A088B0",
            relative=True,
            depth=-1,
            tween_duration=TWEEN_MS,
        )

    def _draw_floor_item(
        self,
        obj,
        x: float,
        y: float,
        cell: float,
        *,
        key_override: str | None = None,
    ) -> None:
        """Render an item sitting on a counter or on the floor.

        ``key_override`` lets the caller anchor the IDs to a stable host
        position (e.g. ``on-counter-{r}-{c}``) instead of the per-instance
        fallback used for loose floor items. cogrid re-instantiates
        ``obj_placed_on`` each render sync, so without an override the
        ``id(obj)`` fallback would change every frame and prevent tweens.

        Sprites for onion/tomato/plate/onion-soup/tomato-soup; vector
        fallback for broccoli/mushroom and runtime-generated mixed soups.
        """
        key = key_override or _key(obj)
        carry = _carry_kind(obj)
        # Sprite-backed items go through the objects atlas, sized smaller than
        # the cell so the underlying counter is still visible.
        sprite_frame = {
            "onion": "onion.png",
            "tomato": "tomato.png",
            "plate": "dish.png",
            "onion_soup": "soup-onion-dish.png",
            "tomato_soup": "soup-tomato-dish.png",
        }.get(carry)
        if sprite_frame is not None:
            self.surface.image(
                id=f"item-{key}",
                x=x + cell * 0.15,
                y=y + cell * 0.15,
                w=TILE_SIZE * 0.7,
                h=TILE_SIZE * 0.7,
                image_name="objects",
                frame=sprite_frame,
                relative=True,
                depth=0,
                tween_duration=TWEEN_MS,
            )
            return

        cx = x + cell / 2
        cy = y + cell / 2
        if carry in ("broccoli", "mushroom"):
            self.surface.circle(
                id=f"item-{carry}-{key}",
                x=cx,
                y=cy,
                radius=cell * 0.22,
                color=INGREDIENT_COLORS[carry],
                stroke_color="#000000",
                stroke_width=1,
                relative=True,
                depth=0,
                tween_duration=TWEEN_MS,
            )
            return
        # Mixed soup (any V2-generated soup type) -- plate base + colored center.
        self.surface.circle(
            id=f"soup-base-{key}",
            x=cx,
            y=cy,
            radius=cell * 0.30,
            color=PLATE_COLOR,
            stroke_color="#888888",
            stroke_width=1,
            relative=True,
            depth=0,
            tween_duration=TWEEN_MS,
        )
        self.surface.circle(
            id=f"soup-center-{key}",
            x=cx,
            y=cy,
            radius=cell * 0.18,
            color=_soup_color(obj),
            relative=True,
            depth=1,
            tween_duration=TWEEN_MS,
        )

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------
    def _draw_agent(
        self,
        aid,
        agent_obj,
        xy: tuple[float, float],
        *,
        is_self: bool,
    ) -> None:
        x, y = xy
        cell = 1.0 / VIEW_DIAM
        cardinal = DIR_TO_CARDINAL[int(agent_obj.dir) % 4]

        held_obj = agent_obj.inventory[0] if agent_obj.inventory else None
        carry = _carry_kind(held_obj) if held_obj is not None else None
        held_suffix = SPRITE_HELD_SUFFIX.get(carry, "") if carry else ""

        # Self never moves on screen (always at viewport center) so a tween
        # does nothing useful and would cause the held-item overlay to slide
        # awkwardly when self changes direction in place. Partner does move
        # on screen -- both when they walk and when self walks -- so they
        # get the full tween.
        tween_ms = 0 if is_self else TWEEN_MS

        # Body sprite -- the chefs atlas has a per-direction frame plus
        # held-item variants for the items we have sprites for. For
        # broccoli/mushroom/mixed-soup, we use the plain chef sprite and
        # overlay the held item ourselves.
        self.surface.image(
            id=f"agent-{aid}-body",
            x=x,
            y=y,
            w=TILE_SIZE,
            h=TILE_SIZE,
            image_name="chefs",
            frame=f"{cardinal}{held_suffix}.png",
            relative=True,
            depth=3,
            tween_duration=tween_ms,
        )
        # Hat overlay -- distinguishes agents (blue / green / fallback).
        hat_color = AGENT_HAT_COLORS.get(aid, AGENT_HAT_FALLBACK)
        self.surface.image(
            id=f"agent-{aid}-hat",
            x=x,
            y=y,
            w=TILE_SIZE,
            h=TILE_SIZE,
            image_name="chefs",
            frame=f"{cardinal}-{hat_color}hat.png",
            relative=True,
            depth=4,
            tween_duration=tween_ms,
        )
        # Self-vs-other indicator: thin colored ring at the top so the
        # viewing player can spot themselves at a glance.
        ring_color = "#FFFFFF" if is_self else "#000000"
        self.surface.rect(
            id=f"agent-{aid}-ring",
            x=x + cell * 0.05,
            y=y + cell * 0.05,
            w=cell * 0.9,
            h=cell * 0.05,
            color=ring_color,
            relative=True,
            depth=5,
            tween_duration=tween_ms,
        )

        # Held-item overlay for items without a chef-sprite variant.
        if held_obj is not None and not held_suffix:
            self._draw_held_overlay(
                held_obj, carry, x, y, cell, aid, cardinal, tween_ms
            )

    def _draw_held_overlay(
        self,
        obj,
        carry: str,
        x: float,
        y: float,
        cell: float,
        aid,
        cardinal: str,
        tween_ms: int,
    ) -> None:
        """Draw a held item on top of a plain chef sprite.

        Position offsets follow the cogrid sprite convention: held items sit
        slightly in front of the chef in their facing direction. The
        ``tween_ms`` argument is forwarded from the calling agent so the
        held item glides with the chef (partner) or snaps in place (self).
        """
        # In-front-of-chef offset by direction (small, so it stays inside the tile).
        offset = {
            "EAST": (0.20, 0.0),
            "WEST": (-0.20, 0.0),
            "NORTH": (0.0, -0.20),
            "SOUTH": (0.0, 0.20),
        }[cardinal]
        cx = x + cell / 2 + offset[0] * cell
        cy = y + cell / 2 + offset[1] * cell

        if carry in ("broccoli", "mushroom"):
            self.surface.circle(
                id=f"agent-{aid}-held",
                x=cx,
                y=cy,
                radius=cell * 0.16,
                color=INGREDIENT_COLORS[carry],
                stroke_color="#000000",
                stroke_width=1,
                relative=True,
                depth=6,
                tween_duration=tween_ms,
            )
            return
        # Mixed soup -- plate + colored center.
        self.surface.circle(
            id=f"agent-{aid}-held-base",
            x=cx,
            y=cy,
            radius=cell * 0.20,
            color=PLATE_COLOR,
            stroke_color="#000000",
            stroke_width=1,
            relative=True,
            depth=6,
            tween_duration=tween_ms,
        )
        self.surface.circle(
            id=f"agent-{aid}-held-center",
            x=cx,
            y=cy,
            radius=cell * 0.12,
            color=_soup_color(obj),
            relative=True,
            depth=7,
            tween_duration=tween_ms,
        )


# ---------------------------------------------------------------------------
# Registration: build a MUG-rendered variant by reusing the cogrid V2 config.
# ---------------------------------------------------------------------------
# Probe the upstream registration to recover its config (rewards, layout, tick
# functions, etc.) without re-deriving it here. The probe env is throwaway.
_probe = registry.make(SOURCE_ENV_ID)
_v2_config = copy.deepcopy(_probe.config)
del _probe

registry.register(
    environment_id=ENV_ID,
    env_class=functools.partial(OvercookedV2PartialObsEnv, config=_v2_config),
)

env = registry.make(ENV_ID, render_mode="mug")
