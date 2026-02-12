from __future__ import annotations

import os

from cogrid.core import grid_object
from cogrid.envs import overcooked
from cogrid.envs.overcooked import overcooked_grid_objects

from mug.configurations import object_contexts, remote_config
from mug.server import remote_game

ASSET_PATH = "static/assets/overcooked/sprites"
TILE_SIZE = 45
DIR_TO_CARDINAL_DIRECTION = {
    0: "EAST",
    1: "SOUTH",
    2: "WEST",
    3: "NORTH",
}
PLAYER_COLORS = {0: "blue", 1: "green"}


def overcooked_game_page_header_fn(
    game: remote_game.RemoteGameV2, player_name: str
) -> str:
    """Function that takes the game and a player name to determine the html that should be shown when the game active."""
    player_id = None
    for pid, sid in game.human_players.items():
        if sid == player_name:
            player_id = pid

    if player_id is None:
        # No player id means we're a spectator
        return ""

    if player_id == 1:
        html_path = "mug/server/static/templates/overcooked_agent_1_header.html"
    else:
        html_path = "mug/server/static/templates/overcooked_agent_0_header.html"

    try:
        with open(html_path, encoding="utf-8") as f:
            header_html = f.read()
    except FileNotFoundError:
        header_html = f"<p> Unable to load header file {html_path}.</p>"

    return header_html


def get_x_y(
    pos: tuple[int, int], game_height: int, game_width: int
) -> tuple[int, int]:
    col, row = pos
    x = row * TILE_SIZE / game_width
    y = col * TILE_SIZE / game_height
    return x, y


def hud_text_fn(game: remote_game.RemoteGameV2) -> str:
    """Function to create HUD text to display"""
    score = int(
        list(game.episode_rewards.values())[0]
        if len(game.episode_rewards) > 0
        else 0
    )
    return f"Score: {score:03d}   |    Time Left: {(game.env.max_steps - game.tick_num) / game.config.fps:.1f}s"


def overcooked_preload_assets_spec() -> (
    list[
        object_contexts.AtlasSpec
        | object_contexts.MultiAtlasSpec
        | object_contexts.ImgSpec
    ]
):
    terrain = object_contexts.AtlasSpec(
        name="terrain",
        img_path=os.path.join(ASSET_PATH, "terrain.png"),
        atlas_path=os.path.join(ASSET_PATH, "terrain.json"),
    )
    chefs = object_contexts.AtlasSpec(
        name="chefs",
        img_path=os.path.join(ASSET_PATH, "chefs.png"),
        atlas_path=os.path.join(ASSET_PATH, "chefs.json"),
    )
    objects = object_contexts.AtlasSpec(
        name="objects",
        img_path=os.path.join(ASSET_PATH, "objects.png"),
        atlas_path=os.path.join(ASSET_PATH, "objects.json"),
    )

    return [
        terrain.as_dict(),
        chefs.as_dict(),
        objects.as_dict(),
    ]


def overcooked_env_to_render_fn(
    env: overcooked.Overcooked, config: remote_config.RemoteConfig
):
    render_objects = []

    if env.t == 0:
        render_objects += generate_counter_objects(env=env, config=config)
        render_objects += generate_delivery_areas(env, config=config)
        render_objects += generate_static_tools(env=env, config=config)

    render_objects += generate_agent_sprites(env=env, config=config)
    render_objects += generate_objects(env=env, config=config)

    return [obj.as_dict() for obj in render_objects]


def generate_counter_objects(
    env: overcooked.Overcooked, config: remote_config.RemoteConfig
) -> list[object_contexts.Sprite]:
    objs = []
    for obj in env.grid.grid:
        if not (
            isinstance(obj, grid_object.Counter)
            or isinstance(obj, grid_object.Wall)
            or isinstance(obj, overcooked_grid_objects.Pot)
        ):
            continue

        x, y = get_x_y(obj.pos, config.game_height, config.game_width)

        objs.append(
            object_contexts.Sprite(
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
    env: overcooked.Overcooked, config: remote_config.RemoteConfig
) -> list[object_contexts.Sprite]:
    objs = []
    for obj in env.grid.grid:
        if not isinstance(obj, overcooked_grid_objects.DeliveryZone):
            continue
        x, y = get_x_y(obj.pos, config.game_height, config.game_width)

        objs.append(
            object_contexts.Sprite(
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
    env: overcooked.Overcooked, config: remote_config.RemoteConfig
) -> list[object_contexts.Sprite]:
    objs = []
    for obj in env.grid.grid:
        if isinstance(obj, overcooked_grid_objects.PlateStack):
            x, y = get_x_y(obj.pos, config.game_height, config.game_width)
            objs.append(
                object_contexts.Sprite(
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
            x, y = get_x_y(obj.pos, config.game_height, config.game_width)
            objs.append(
                object_contexts.Sprite(
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
            x, y = get_x_y(obj.pos, config.game_height, config.game_width)
            objs.append(
                object_contexts.Sprite(
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


def generate_agent_sprites(
    env: overcooked.Overcooked, config: remote_config.RemoteConfig
) -> list[object_contexts.Sprite]:
    objs = []
    for i, agent_obj in enumerate(env.grid.grid_agents.values()):
        x, y = get_x_y(agent_obj.pos, config.game_height, config.game_width)
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
            object_contexts.Sprite(
                f"agent-{i}-sprite",
                x=x,
                y=y,
                height=TILE_SIZE,
                width=TILE_SIZE,
                image_name="chefs",
                tween=True,
                frame=f"{dir}{held_object_name}.png",
            )
        )

        objs.append(
            object_contexts.Sprite(
                f"agent-{i}-hat-sprite",
                x=x,
                y=y,
                height=TILE_SIZE,
                width=TILE_SIZE,
                image_name="chefs",
                frame=f"{dir}-{PLAYER_COLORS[i]}hat.png",
                tween=True,
                depth=2,
            )
        )

    return objs


def generate_objects(
    env: overcooked.Overcooked, config: remote_config.RemoteConfig
) -> list[object_contexts.Sprite]:
    objs = []
    for obj in env.grid.grid:
        if obj is None:
            continue

        if obj.can_place_on and obj.obj_placed_on is not None:
            objs += temp_object_creation(obj=obj.obj_placed_on, config=config)

        objs += temp_object_creation(obj=obj, config=config)

    return objs


def temp_object_creation(
    obj: grid_object.GridObj, config: remote_config.RemoteConfig
):
    if isinstance(obj, overcooked_grid_objects.Pot):
        x, y = get_x_y(obj.pos, config.game_height, config.game_width)
        if not obj.objects_in_pot:
            return []
        status = "cooked" if obj.cooking_timer == 0 else "cooking"
        if status == "cooking":
            frame = f"soup-onion-{len(obj.objects_in_pot)}-cooking.png"
        else:
            frame = "soup-onion-cooked.png"

        pot_sprite = [
            object_contexts.Sprite(
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
                object_contexts.Text(
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
        x, y = get_x_y(obj.pos, config.game_height, config.game_width)
        return [
            object_contexts.Sprite(
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
        x, y = get_x_y(obj.pos, config.game_height, config.game_width)
        return [
            object_contexts.Sprite(
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
        x, y = get_x_y(obj.pos, config.game_height, config.game_width)
        return [
            object_contexts.Sprite(
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
