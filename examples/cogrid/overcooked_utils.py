from __future__ import annotations

from mug.server import remote_game

ASSET_PATH = "examples/cogrid/assets/overcooked/sprites"

ARROW_KEYS_IMG = "examples/shared/assets/keys/arrow_keys_2.png"
W_KEY_IMG = "examples/shared/assets/keys/icons8-w-key-50.png"
CHEF_IMGS = {
    0: "examples/cogrid/assets/overcooked/blue_chef.png",
    1: "examples/cogrid/assets/overcooked/green_chef.png",
}

def _legend_pair(img_src: str, img_alt: str, img_height_px: int, label: str) -> str:
    """One [image] [label] cell used inside the horizontal legend row."""
    return f"""
    <div style="display: flex; align-items: center; gap: 8px;">
        <img src="{img_src}" alt="{img_alt}"
             style="height: {img_height_px}px; width: auto;">
        <span>{label}</span>
    </div>
    """


CONTROLS_PAIRS_HTML = (
    _legend_pair(ARROW_KEYS_IMG, "Keyboard arrow keys", 70, "move")
    + _legend_pair(W_KEY_IMG, "W key", 36, "pick up / drop")
)


def overcooked_controls_row(chef_img: str, chef_label: str = "your chef") -> str:
    """Single horizontal row: chef pair + arrow-keys pair + W-key pair, evenly spaced."""
    chef_cell = _legend_pair(chef_img, chef_label, 36, chef_label)
    return f"""
    <div style="font-family: sans-serif; margin: 8px auto;
                display: flex; align-items: center; justify-content: center;
                gap: 28px; flex-wrap: wrap; font-size: 0.95em;">
        {chef_cell}
        {CONTROLS_PAIRS_HTML}
    </div>
    """


def overcooked_two_column_layout(header_html: str) -> str:
    """Shared-fallback layout: free-form header block on the left, controls on the right."""
    return f"""
    <div style="font-family: sans-serif; margin: 8px auto; max-width: 720px;">
        <div style="display: flex; align-items: center; justify-content: center;
                    gap: 28px; flex-wrap: wrap;">
            <div style="text-align: left; font-size: 0.95em; max-width: 300px;">
                {header_html}
            </div>
            <div style="display: flex; align-items: center; gap: 28px;
                        font-size: 0.9em;">
                {CONTROLS_PAIRS_HTML}
            </div>
        </div>
    </div>
    """


def overcooked_preload_assets_spec() -> list[dict]:
    """Return the Phaser asset specs for Overcooked atlases.

    These must be passed via ``.rendering(assets_to_preload=...)`` for
    P2P / Pyodide scenes so that Phaser preloads the textures before the
    environment starts rendering.  Server-authoritative scenes collect
    these automatically from the Surface.
    """
    return [
        {
            "object_type": "atlas_spec",
            "name": "terrain",
            "img_path": f"{ASSET_PATH}/terrain.png",
            "atlas_path": f"{ASSET_PATH}/terrain.json",
        },
        {
            "object_type": "atlas_spec",
            "name": "chefs",
            "img_path": f"{ASSET_PATH}/chefs.png",
            "atlas_path": f"{ASSET_PATH}/chefs.json",
        },
        {
            "object_type": "atlas_spec",
            "name": "objects",
            "img_path": f"{ASSET_PATH}/objects.png",
            "atlas_path": f"{ASSET_PATH}/objects.json",
        },
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
    """Per-participant in-game HTML so each player sees their own chef color."""
    player_id = None
    for pid, sid in game.human_players.items():
        if sid == player_name:
            player_id = pid
            break

    if player_id is None:
        # Spectator / lookup failed — fall back to the shared in_game_scene_body.
        return ""

    chef_img = CHEF_IMGS.get(player_id, CHEF_IMGS[0])
    return overcooked_controls_row(chef_img)


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
    fps = getattr(game, "fps", None) or getattr(
        getattr(game, "scene", None), "fps", 30
    )
    return f"Score: {score:03d}   |    Time Left: {(game.env.max_steps - game.tick_num) / fps:.1f}s"
