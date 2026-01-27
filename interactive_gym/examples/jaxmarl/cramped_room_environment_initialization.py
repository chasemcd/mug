# pip install --no-deps jaxmarl


import functools

import functools
import jaxmarl 
from interactive_gym.configurations.object_contexts import (
    Sprite,
    Text,
)



class MUGOvercooked(jaxmarl.environments.overcooked.overcooked.Overcooked):
    state = None
    KEY = 0
    def step(self, actions: dict):
        obs, self.state, rewards, dones, info = super().step(self.KEY, self.state, actions)

        # Convert chex.Arrays into numpy arrays
        
        
def get_x_y(
    pos: tuple[int, int], game_height: int, game_width: int
) -> tuple[int, int]:
    col, row = pos
    x = row * TILE_SIZE / game_width
    y = col * TILE_SIZE / game_height
    return x, y


ASSET_PATH = "static/assets/overcooked/sprites"
TILE_SIZE = 45
WIDTH = 7 * TILE_SIZE
HEIGHT = 6 * TILE_SIZE
DIR_TO_CARDINAL_DIRECTION = {
    0: "EAST",
    1: "SOUTH",
    2: "WEST",
    3: "NORTH",
}
PLAYER_COLORS = {0: "blue", 1: "green"}


def generate_counter_objects(env: overcooked.Overcooked) -> list[Sprite]:
    objs = []
    for obj in env.grid.grid:
        if not (
            isinstance(obj, grid_object.Counter)
            or isinstance(obj, grid_object.Wall)
            or isinstance(obj, overcooked_grid_objects.Pot)
        ):
            continue

        x, y = get_x_y(obj.pos, HEIGHT, WIDTH)

        objs.append(
            Sprite(
                obj.uuid,
                x=x,
                y=y,
                height=TILE_SIZE,
                width=TILE_SIZE,
                image_name="terrain",
                frame="counter.png",
                permanent=True,
                depth=-2,
            )
        )
    return objs


def generate_delivery_areas(
    env: overcooked.Overcooked,
) -> list[Sprite]:
    objs = []
    for obj in env.grid.grid:
        if not isinstance(obj, overcooked_grid_objects.DeliveryZone):
            continue
        x, y = get_x_y(obj.pos, HEIGHT, WIDTH)

        objs.append(
            Sprite(
                obj.uuid,
                x=x,
                y=y,
                height=TILE_SIZE,
                width=TILE_SIZE,
                image_name="terrain",
                frame="serve.png",
                permanent=True,
            )
        )
    return objs


def generate_static_tools(
    env: overcooked.Overcooked,
) -> list[Sprite]:
    objs = []
    for obj in env.grid.grid:
        if isinstance(obj, overcooked_grid_objects.PlateStack):
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
            objs.append(
                Sprite(
                    obj.uuid,
                    x=x,
                    y=y,
                    height=TILE_SIZE,
                    width=TILE_SIZE,
                    image_name="terrain",
                    frame="dishes.png",
                    permanent=True,
                )
            )
        elif isinstance(obj, overcooked_grid_objects.OnionStack):
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
            objs.append(
                Sprite(
                    obj.uuid,
                    x=x,
                    y=y,
                    height=TILE_SIZE,
                    width=TILE_SIZE,
                    image_name="terrain",
                    frame="onions.png",
                    permanent=True,
                )
            )
        elif isinstance(obj, overcooked_grid_objects.Pot):
            x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
            objs.append(
                Sprite(
                    obj.uuid,
                    x=x,
                    y=y,
                    height=TILE_SIZE,
                    width=TILE_SIZE,
                    image_name="terrain",
                    frame="pot.png",
                    permanent=True,
                )
            )

    return objs


def generate_agent_sprites(env: overcooked.Overcooked) -> list[Sprite]:
    objs = []
    for i, agent_obj in enumerate(env.grid.grid_agents.values()):
        x, y = get_x_y(agent_obj.pos, HEIGHT, WIDTH)
        held_object_name = ""
        if agent_obj.inventory:
            assert (
                len(agent_obj.inventory) == 1
            ), "Rendering not supported for inventory > 1."

            held_obj = agent_obj.inventory[0]
            if isinstance(held_obj, overcooked_grid_objects.Onion):
                held_object_name = "-onion"
            elif isinstance(held_obj, overcooked_grid_objects.OnionSoup):
                held_object_name = "-soup-onion"
            elif isinstance(held_obj, overcooked_grid_objects.Plate):
                held_object_name = "-dish"

        dir = DIR_TO_CARDINAL_DIRECTION[agent_obj.dir]

        objs.append(
            Sprite(
                f"agent-{i}-sprite",
                x=x,
                y=y,
                height=TILE_SIZE,
                width=TILE_SIZE,
                image_name="chefs",
                tween=True,
                tween_duration=75,
                frame=f"{dir}{held_object_name}.png",
            )
        )

        objs.append(
            Sprite(
                f"agent-{i}-hat-sprite",
                x=x,
                y=y,
                height=TILE_SIZE,
                width=TILE_SIZE,
                image_name="chefs",
                frame=f"{dir}-{PLAYER_COLORS[i]}hat.png",
                tween=True,
                tween_duration=75,
                depth=2,
            )
        )
    return objs


def generate_objects(
    env: overcooked.Overcooked,
) -> list[Sprite]:
    objs = []
    for obj in env.grid.grid:
        if obj is None:
            continue

        if obj.can_place_on and obj.obj_placed_on is not None:
            objs += temp_object_creation(obj=obj.obj_placed_on)

        objs += temp_object_creation(obj=obj)

    return objs


def temp_object_creation(obj: grid_object.GridObj):
    if isinstance(obj, overcooked_grid_objects.Pot):
        x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
        if not obj.objects_in_pot:
            return []
        status = "cooked" if obj.cooking_timer == 0 else "cooking"
        if status == "cooking":
            frame = f"soup-onion-{len(obj.objects_in_pot)}-cooking.png"
        else:
            frame = "soup-onion-cooked.png"

        pot_sprite = [
            Sprite(
                obj.uuid,
                x=x,
                y=y,
                height=TILE_SIZE,
                width=TILE_SIZE,
                image_name="objects",
                frame=frame,
                depth=-1,
            )
        ]

        if status == "cooking" and len(obj.objects_in_pot) == 3:
            pot_sprite.append(
                Text(
                    uuid="time_left",
                    text=f"{obj.cooking_timer:02d}",
                    x=x,
                    y=y,
                    size=14,
                    color="red",
                )
            )

        return pot_sprite
    elif isinstance(obj, overcooked_grid_objects.Onion):
        x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
        return [
            Sprite(
                obj.uuid,
                x=x,
                y=y,
                height=TILE_SIZE,
                width=TILE_SIZE,
                image_name="objects",
                frame="onion.png",
                depth=-1,
            )
        ]

    elif isinstance(obj, overcooked_grid_objects.Plate):
        x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
        return [
            Sprite(
                obj.uuid,
                x=x,
                y=y,
                height=TILE_SIZE,
                width=TILE_SIZE,
                image_name="objects",
                frame="dish.png",
                depth=-1,
            )
        ]
    elif isinstance(obj, overcooked_grid_objects.OnionSoup):
        x, y = get_x_y(obj.pos, HEIGHT, WIDTH)
        return [
            Sprite(
                obj.uuid,
                x=x,
                y=y,
                height=TILE_SIZE,
                width=TILE_SIZE,
                image_name="objects",
                frame="soup-onion-dish.png",
                depth=-1,
            )
        ]
    return []


class InteractiveGymOvercooked(OvercookedRewardEnv):
    def render(self):
        return self.env_to_render_fn()

    def get_infos(self, **kwargs):
        """Add the agent positions and directions to the infos dictionary"""
        infos = super().get_infos(**kwargs)

        for agent_id, agent in self.grid.grid_agents.items():
            row, col = agent.pos
            infos[agent_id]["row"] = int(row)
            infos[agent_id]["col"] = int(col)
            infos[agent_id]["direction"] = int(agent.dir)
            infos[agent_id]["layout_id"] = self.current_layout_id

        return infos

    def env_to_render_fn(self):
        render_objects = []

        if self.t == 0:
            render_objects += generate_counter_objects(env=self)
            render_objects += generate_delivery_areas(env=self)
            render_objects += generate_static_tools(env=self)

        render_objects += generate_agent_sprites(env=self)
        render_objects += generate_objects(env=self)

        return [obj.as_dict() for obj in render_objects]


class ScaledFullMapEncoding(features.FullMapEncoding):
    def generate(self, env, player_id, **kwargs):
        encoding = super().generate(env, player_id, **kwargs)
        return encoding / 100.0


feature_space.register_feature(
    "scaled_full_map_encoding", ScaledFullMapEncoding
)


overcooked_config = {
    "name": "overcooked",
    "num_agents": 2,
    "action_set": "cardinal_actions",
    "features": {
        0: [],
        1: [
            "overcooked_behavior_features",
            # "overcooked_vf_features",
            "scaled_full_map_encoding",
        ],
    },
    "rewards": [
        "delivery_reward",
        "delivery_act_reward",
        "onion_in_pot_reward_1.0coeff",
        "soup_in_dish_reward_1.0coeff",
    ],
    "grid": {"layout": "overcooked_cramped_room_v0"},
    "scope": "overcooked",
    "max_steps": 1350,
    "unshaped_proportion": 1.0,
    "enable_weight_randomization": False,
    "behavior_weights": {
        agent_id: {
            "delivery_reward": 1,
            "delivery_act_reward": 0,
            "onion_in_pot_reward": 0,
            "soup_in_dish_reward": 0,
        }
        for agent_id in range(2)
    },
}

registry.register(
    environment_id="Overcooked-BehaviorFeatures-CrampedRoom-EnvToRender",
    env_class=functools.partial(
        InteractiveGymOvercooked, config=overcooked_config
    ),
)

env = registry.make("Overcooked-BehaviorFeatures-CrampedRoom-EnvToRender")
