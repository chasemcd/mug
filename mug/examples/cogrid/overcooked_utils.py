from __future__ import annotations

from mug.server import remote_game

ASSET_PATH = "static/assets/overcooked/sprites"


def overcooked_preload_assets_spec() -> list[dict]:
    """Return the Phaser asset specs for Overcooked atlases.

    These must be passed via ``.rendering(assets_to_preload=...)`` for
    P2P / Pyodide scenes so that Phaser preloads the textures before the
    environment starts rendering.  Server-authoritative scenes collect
    these automatically from the Surface.
    """
    return [
        {"object_type": "atlas_spec", "name": "terrain", "img_path": f"{ASSET_PATH}/terrain.png", "atlas_path": f"{ASSET_PATH}/terrain.json"},
        {"object_type": "atlas_spec", "name": "chefs", "img_path": f"{ASSET_PATH}/chefs.png", "atlas_path": f"{ASSET_PATH}/chefs.json"},
        {"object_type": "atlas_spec", "name": "objects", "img_path": f"{ASSET_PATH}/objects.png", "atlas_path": f"{ASSET_PATH}/objects.json"},
    ]
TILE_SIZE = 45
DIR_TO_CARDINAL_DIRECTION = {
    0: "EAST",
    1: "SOUTH",
    2: "WEST",
    3: "NORTH",
}
PLAYER_COLORS = {0: "blue", 1: "green"}


def overcooked_game_page_header_fn(
    game: remote_game.ServerGame, player_name: str
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


def hud_text_fn(game: remote_game.ServerGame) -> str:
    """Function to create HUD text to display"""
    score = int(
        list(game.episode_rewards.values())[0]
        if len(game.episode_rewards) > 0
        else 0
    )
    fps = getattr(game, 'fps', None) or getattr(getattr(game, 'scene', None), 'fps', 30)
    return f"Score: {score:03d}   |    Time Left: {(game.env.max_steps - game.tick_num) / fps:.1f}s"
