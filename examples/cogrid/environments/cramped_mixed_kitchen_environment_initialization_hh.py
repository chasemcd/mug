"""Cramped Mixed Kitchen human-human environment initialization for CoGrid 0.2.2.

Two-agent environment for human-human multiplayer experiments on the
CrampedMixedKitchen layout, which includes both onions and tomatoes
plus an order queue that tells players which soup to prepare.

This file is executed by Pyodide to create the environment. It must
produce an ``env`` variable at module scope.
"""
from __future__ import annotations

import functools

import numpy as np
from cogrid.cogrid_env import CoGridEnv
from cogrid.core import grid_object
from cogrid.envs import registry
from cogrid.envs.overcooked import overcooked_grid_objects
from cogrid.envs.overcooked.agent import OvercookedAgent
from cogrid.envs.overcooked.config import (_build_order_tables,
                                           build_order_extra_state,
                                           order_queue_tick)
from cogrid.envs.overcooked.rewards import (ExpiredOrderPenalty,
                                            OrderDeliveryReward,
                                            OrderGatedIngredientInPotReward)

from mug.rendering import Surface

ASSET_PATH = "examples/cogrid/assets/overcooked/sprites"
TILE_SIZE = 45
GRID_COLS = 5
GRID_ROWS = 5
GRID_WIDTH = GRID_COLS * TILE_SIZE   # 225
GRID_HEIGHT = GRID_ROWS * TILE_SIZE  # 225
ORDER_BAR_HEIGHT = 45
WIDTH = GRID_WIDTH                         # 225
HEIGHT = GRID_HEIGHT + ORDER_BAR_HEIGHT    # 270

DIR_TO_CARDINAL_DIRECTION = {
    0: "EAST",
    1: "SOUTH",
    2: "WEST",
    3: "NORTH",
}
PLAYER_COLORS = {0: "blue", 1: "green"}

# Order display constants
ORDER_TIME_LIMIT = 100
RECIPE_COLORS = {
    0: "#FFC832",   # onion soup – golden yellow
    1: "#DC3232",   # tomato soup – red
}
ORDER_BG_COLOR = "#323232"
URGENT_COLOR = "#FF5050"

# Order bar layout (in pixels, within the ORDER_BAR_HEIGHT strip)
# Each slot: dish icon on top, thin timer bar below, evenly spaced.
NUM_ORDER_SLOTS = 3
ICON_SIZE = 30          # dish sprite size
TIMER_BAR_HEIGHT = 5
TIMER_BAR_GAP = 2       # gap between icon and bar
# Divide width into NUM_ORDER_SLOTS equal columns; center icon in each.
SLOT_COL_WIDTH = WIDTH / NUM_ORDER_SLOTS  # 75px per column


def get_x_y(
    pos: tuple[int, int], game_height: int, game_width: int
) -> tuple[float, float]:
    col, row = pos
    x = row * TILE_SIZE / game_width
    y = (col * TILE_SIZE + ORDER_BAR_HEIGHT) / game_height
    return x, y


class OvercookedEnv(CoGridEnv):
    """CoGridEnv subclass that renders the CrampedMixedKitchen via the MUG Surface API."""

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

    def on_reset(self) -> None:
        super().on_reset()
        self._pending_surface_reset = True

    def get_infos(self, **kwargs):
        infos = super().get_infos(**kwargs)
        for agent_id, agent in self.grid.grid_agents.items():
            row, col = agent.pos
            infos[agent_id]["row"] = int(row)
            infos[agent_id]["col"] = int(col)
            infos[agent_id]["direction"] = int(agent.dir)
            infos[agent_id]["layout_id"] = self.current_layout_id
        return infos

    def render(self):
        assert self.render_mode == "mug"

        # --- Static terrain objects ---
        for obj in self.grid.grid:
            if obj is None:
                continue

            if (
                isinstance(obj, grid_object.Counter)
                or isinstance(obj, grid_object.Wall)
                or isinstance(obj, overcooked_grid_objects.Pot)
            ):
                x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
                self.surface.image(
                    id=obj.uuid,
                    x=x,
                    y=y,
                    w=TILE_SIZE,
                    h=TILE_SIZE,
                    image_name="terrain",
                    frame="counter.png",
                    persistent=True,
                    relative=True,
                    depth=-2,
                )

            if isinstance(obj, overcooked_grid_objects.DeliveryZone):
                x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
                self.surface.image(
                    id=obj.uuid,
                    x=x,
                    y=y,
                    w=TILE_SIZE,
                    h=TILE_SIZE,
                    image_name="terrain",
                    frame="serve.png",
                    persistent=True,
                    relative=True,
                )

            if isinstance(obj, overcooked_grid_objects.PlateStack):
                x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
                self.surface.image(
                    id=obj.uuid,
                    x=x,
                    y=y,
                    w=TILE_SIZE,
                    h=TILE_SIZE,
                    image_name="terrain",
                    frame="dishes.png",
                    persistent=True,
                    relative=True,
                )
            elif isinstance(obj, overcooked_grid_objects.OnionStack):
                x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
                self.surface.image(
                    id=obj.uuid,
                    x=x,
                    y=y,
                    w=TILE_SIZE,
                    h=TILE_SIZE,
                    image_name="terrain",
                    frame="onions.png",
                    persistent=True,
                    relative=True,
                )
            elif isinstance(obj, overcooked_grid_objects.TomatoStack):
                x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
                self.surface.image(
                    id=obj.uuid,
                    x=x,
                    y=y,
                    w=TILE_SIZE,
                    h=TILE_SIZE,
                    image_name="terrain",
                    frame="tomatoes.png",
                    persistent=True,
                    relative=True,
                )
            elif isinstance(obj, overcooked_grid_objects.Pot):
                x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
                self.surface.image(
                    id=f"{obj.uuid}-pot",
                    x=x,
                    y=y,
                    w=TILE_SIZE,
                    h=TILE_SIZE,
                    image_name="terrain",
                    frame="pot.png",
                    persistent=True,
                    relative=True,
                )

        # --- Dynamic objects ---
        for obj in self.grid.grid:
            if obj is None:
                continue

            if hasattr(obj, "can_place_on") and obj.can_place_on and obj.obj_placed_on is not None:
                self._draw_dynamic_object(obj.obj_placed_on, parent_pos=obj.pos)

            self._draw_dynamic_object(obj)

        # --- Agent sprites ---
        for i, agent_obj in enumerate(self.grid.grid_agents.values()):
            x, y = get_x_y(agent_obj.pos, HEIGHT, WIDTH)
            held_object_name = ""
            if agent_obj.inventory:
                held_obj = agent_obj.inventory[0]
                if isinstance(held_obj, overcooked_grid_objects.Onion):
                    held_object_name = "-onion"
                elif isinstance(held_obj, overcooked_grid_objects.OnionSoup):
                    held_object_name = "-soup-onion"
                elif isinstance(held_obj, overcooked_grid_objects.Tomato):
                    held_object_name = "-tomato"
                elif isinstance(held_obj, overcooked_grid_objects.TomatoSoup):
                    held_object_name = "-soup-tomato"
                elif isinstance(held_obj, overcooked_grid_objects.Plate):
                    held_object_name = "-dish"

            dir = DIR_TO_CARDINAL_DIRECTION[agent_obj.dir]
            self.surface.image(
                id=f"agent-{i}-sprite",
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="chefs",
                frame=f"{dir}{held_object_name}.png",
                tween_duration=75,
                relative=True,
            )
            self.surface.image(
                id=f"agent-{i}-hat-sprite",
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="chefs",
                frame=f"{dir}-{PLAYER_COLORS[i]}hat.png",
                tween_duration=75,
                relative=True,
                depth=2,
            )

        # --- Order HUD ---
        self._render_order_bar()

        result = self.surface.commit().to_dict()

        if getattr(self, "_pending_surface_reset", False):
            self.surface._committed_persistent.clear()
            self.surface._ephemeral_buffer.clear()
            self._pending_surface_reset = False

        return result

    def _draw_dynamic_object(self, obj, parent_pos=None):
        """Draw a dynamic (non-persistent) object onto the surface."""
        pos = obj.pos if obj.pos is not None else parent_pos
        if pos is None:
            return
        if isinstance(obj, overcooked_grid_objects.Pot):
            x, y = get_x_y(pos, HEIGHT, WIDTH)
            if not obj.objects_in_pot:
                return

            # Determine ingredient type from pot contents
            first_item = obj.objects_in_pot[0]
            if isinstance(first_item, overcooked_grid_objects.Tomato):
                ingredient = "tomato"
            else:
                ingredient = "onion"

            status = "cooked" if obj.cooking_timer == 0 else "cooking"
            if status == "cooking":
                frame = f"soup-{ingredient}-{len(obj.objects_in_pot)}-cooking.png"
            else:
                frame = f"soup-{ingredient}-cooked.png"

            self.surface.image(
                id=f"{obj.uuid}-contents",
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="objects",
                frame=frame,
                relative=True,
                depth=1,
            )

            if status == "cooking" and len(obj.objects_in_pot) == 3:
                self.surface.text(
                    id=f"{obj.uuid}-timer",
                    text=f"{obj.cooking_timer:02d}",
                    x=x,
                    y=y,
                    size=14,
                    color="red",
                    relative=True,
                )

        elif isinstance(obj, overcooked_grid_objects.Onion):
            x, y = get_x_y(pos, HEIGHT, WIDTH)
            self.surface.image(
                id=obj.uuid,
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="objects",
                frame="onion.png",
                relative=True,
                depth=1,
            )
        elif isinstance(obj, overcooked_grid_objects.Tomato):
            x, y = get_x_y(pos, HEIGHT, WIDTH)
            self.surface.image(
                id=obj.uuid,
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="objects",
                frame="tomato.png",
                relative=True,
                depth=1,
            )
        elif isinstance(obj, overcooked_grid_objects.Plate):
            x, y = get_x_y(pos, HEIGHT, WIDTH)
            self.surface.image(
                id=obj.uuid,
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="objects",
                frame="dish.png",
                relative=True,
                depth=1,
            )
        elif isinstance(obj, overcooked_grid_objects.OnionSoup):
            x, y = get_x_y(pos, HEIGHT, WIDTH)
            self.surface.image(
                id=obj.uuid,
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="objects",
                frame="soup-onion-dish.png",
                relative=True,
                depth=1,
            )
        elif isinstance(obj, overcooked_grid_objects.TomatoSoup):
            x, y = get_x_y(pos, HEIGHT, WIDTH)
            self.surface.image(
                id=obj.uuid,
                x=x,
                y=y,
                w=TILE_SIZE,
                h=TILE_SIZE,
                image_name="objects",
                frame="soup-tomato-dish.png",
                relative=True,
                depth=1,
            )

    def _render_order_bar(self):
        """Render orders as dish icons with a timer bar underneath.

        The order strip is ORDER_BAR_HEIGHT pixels tall at the top of the
        surface. A white background fills it, then each of the 3 order
        slots is centered in its equal-width column.
        """
        # White background for the entire order strip
        self.surface.rect(
            id="order-bar-bg",
            x=0,
            y=0,
            w=WIDTH,
            h=ORDER_BAR_HEIGHT,
            color="black",
            persistent=True,
            depth=-1,
        )

        extra = getattr(self._env_state, "extra_state", None)
        if extra is None:
            return

        order_recipe = extra.get("overcooked.order_recipe")
        order_timer = extra.get("overcooked.order_timer")
        if order_recipe is None or order_timer is None:
            return

        for i in range(NUM_ORDER_SLOTS):
            # Center of this column
            col_center_x = SLOT_COL_WIDTH * i + SLOT_COL_WIDTH / 2
            # Icon top-left
            icon_x = col_center_x - ICON_SIZE / 2
            icon_y = (ORDER_BAR_HEIGHT - ICON_SIZE - TIMER_BAR_GAP - TIMER_BAR_HEIGHT) / 2
            bar_x = icon_x
            bar_y = icon_y + ICON_SIZE + TIMER_BAR_GAP

            recipe_idx = int(np.array(order_recipe[i]))
            timer = int(np.array(order_timer[i]))

            if recipe_idx < 0:
                # Empty slot — dim background bar only
                self.surface.rect(
                    id=f"order-bg-{i}",
                    x=bar_x,
                    y=bar_y,
                    w=ICON_SIZE,
                    h=TIMER_BAR_HEIGHT,
                    color=ORDER_BG_COLOR,
                )
                continue

            # Dish icon (positions as fractions, size in pixels)
            frame = "soup-onion-dish.png" if recipe_idx == 0 else "soup-tomato-dish.png"
            self.surface.image(
                id=f"order-icon-{i}",
                x=icon_x / WIDTH,
                y=icon_y / HEIGHT,
                w=ICON_SIZE,
                h=ICON_SIZE,
                image_name="objects",
                frame=frame,
                relative=True,
                depth=5,
            )

            # Timer bar background
            self.surface.rect(
                id=f"order-bg-{i}",
                x=bar_x,
                y=bar_y,
                w=ICON_SIZE,
                h=TIMER_BAR_HEIGHT,
                color=ORDER_BG_COLOR,
            )

            # Timer bar fill
            progress = timer / ORDER_TIME_LIMIT
            color = RECIPE_COLORS.get(recipe_idx, RECIPE_COLORS[0])
            if progress < 0.2:
                color = URGENT_COLOR

            fill_width = max(1, ICON_SIZE * progress)
            self.surface.rect(
                id=f"order-fill-{i}",
                x=bar_x,
                y=bar_y,
                w=fill_width,
                h=TIMER_BAR_HEIGHT,
                color=color,
                depth=1,
            )


# ---- Config ----

_order_cfg = {
    "spawn_probs": {"onion_soup": 0.05, "tomato_soup": 0.05},
    "max_active": 3,
    "time_limit": ORDER_TIME_LIMIT,
}

_order_tables = _build_order_tables(_order_cfg, recipe_results=["onion_soup", "tomato_soup"])

overcooked_config = {
    "name": "overcooked",
    "num_agents": 2,
    "action_set": "cardinal_actions",
    "features": [
        "agent_dir",
        "overcooked_inventory",
        "next_to_counter",
        "next_to_pot",
        "object_type_masks",
        "ordered_pot_features",
        "dist_to_other_players",
        "agent_position",
        "can_move_direction",
        "order_observation",
    ],
    "rewards": [
        OrderDeliveryReward(coefficient=1.0, common_reward=True),
        OrderGatedIngredientInPotReward(coefficient=0.1, common_reward=False),
        ExpiredOrderPenalty(penalty=-0.75),
    ],
    "grid": {"layout": "overcooked_cramped_mixed_kitchen_v0"},
    "max_steps": 4000,
    "scope": "overcooked",
    "pickupable_types": ["onion", "onion_soup", "plate", "tomato", "tomato_soup"],
    "orders": _order_cfg,
    "tick_fn": order_queue_tick,
    "extra_static_tables": _order_tables,
    "extra_state_init_fn": functools.partial(build_order_extra_state, _order_cfg),
}

registry.register(
    environment_id="Overcooked-CrampedMixedKitchen-HH-MUG",
    env_class=functools.partial(OvercookedEnv, config=overcooked_config),
)

env = registry.make("Overcooked-CrampedMixedKitchen-HH-MUG", render_mode="mug")
