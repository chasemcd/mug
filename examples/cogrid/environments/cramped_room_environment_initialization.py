"""Cramped Room environment initialization for CoGrid 0.2.1.

This file is executed by Pyodide to create the environment. It must
produce an ``env`` variable at module scope.
"""
from __future__ import annotations

import functools

from cogrid.cogrid_env import CoGridEnv
from cogrid.core import grid_object
from cogrid.envs import registry
from cogrid.envs.overcooked import overcooked_grid_objects
from cogrid.envs.overcooked.agent import OvercookedAgent
from cogrid.envs.overcooked.rewards import DeliveryReward

from mug.rendering import Surface

ASSET_PATH = "examples/cogrid/assets/overcooked/sprites"
TILE_SIZE = 45
WIDTH = 5 * TILE_SIZE
HEIGHT = 4 * TILE_SIZE
DIR_TO_CARDINAL_DIRECTION = {
    0: "EAST",
    1: "SOUTH",
    2: "WEST",
    3: "NORTH",
}
PLAYER_COLORS = {0: "blue", 1: "green"}


def get_x_y(
    pos: tuple[int, int], game_height: int, game_width: int
) -> tuple[float, float]:
    col, row = pos
    x = row * TILE_SIZE / game_width
    y = col * TILE_SIZE / game_height
    return x, y


class OvercookedEnv(CoGridEnv):
    """CoGridEnv subclass that renders via the MUG Surface API."""

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
        # Static objects (persistent, only sent on first frame or change)
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

        # Dynamic objects
        for obj in self.grid.grid:
            if obj is None:
                continue

            if hasattr(obj, "can_place_on") and obj.can_place_on and obj.obj_placed_on is not None:
                self._draw_dynamic_object(obj.obj_placed_on)

            self._draw_dynamic_object(obj)

        # Agent sprites
        for i, agent_obj in enumerate(self.grid.grid_agents.values()):
            x, y = get_x_y(agent_obj.pos, HEIGHT, WIDTH)
            held_object_name = ""
            if agent_obj.inventory:
                held_obj = agent_obj.inventory[0]
                if isinstance(held_obj, overcooked_grid_objects.Onion):
                    held_object_name = "-onion"
                elif isinstance(held_obj, overcooked_grid_objects.OnionSoup):
                    held_object_name = "-soup-onion"
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

        result = self.surface.commit().to_dict()

        if getattr(self, "_pending_surface_reset", False):
            self.surface._committed_persistent.clear()
            self.surface._ephemeral_buffer.clear()
            self._pending_surface_reset = False

        return result

    def _draw_dynamic_object(self, obj):
        """Draw a dynamic (non-persistent) object onto the surface."""
        if obj.pos is None:
            return
        if isinstance(obj, overcooked_grid_objects.Pot):
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
            if not obj.objects_in_pot:
                return
            status = "cooked" if obj.cooking_timer == 0 else "cooking"
            if status == "cooking":
                frame = f"soup-onion-{len(obj.objects_in_pot)}-cooking.png"
            else:
                frame = "soup-onion-cooked.png"

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
                    id="time_left",
                    text=f"{obj.cooking_timer:02d}",
                    x=x,
                    y=y,
                    size=14,
                    color="red",
                    relative=True,
                )
        elif isinstance(obj, overcooked_grid_objects.Onion):
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
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
        elif isinstance(obj, overcooked_grid_objects.Plate):
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
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
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
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
    ],
    "rewards": [
        DeliveryReward(coefficient=1.0, common_reward=True),
    ],
    "grid": {"layout": "overcooked_cramped_room_v0"},
    "scope": "overcooked",
    "max_steps": 1350,
    "pickupable_types": ["onion", "onion_soup", "plate", "tomato", "tomato_soup"],
}

registry.register(
    environment_id="Overcooked-CrampedRoom-MUG",
    env_class=functools.partial(OvercookedEnv, config=overcooked_config),
)

env = registry.make("Overcooked-CrampedRoom-MUG", render_mode="mug")
