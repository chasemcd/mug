from __future__ import annotations

from mug.server import remote_game


def slime_volleyball_game_page_header_fn(
    game: remote_game.ServerGame, player_name: str
) -> str:
    """Function that takes the game and a player name to determine the html that should be shown when the game active."""
    player_id = None
    for pid, sid in game.human_players.items():
        if sid == player_name:
            player_id = pid

    assert player_id is not None

    if player_id == "agent_right":
        html_path = "mug/server/static/templates/slime_vb_agent_right_header.html"
    else:
        html_path = "mug/server/static/templates/slime_vb_agent_left_header.html"

    try:
        with open(html_path, encoding="utf-8") as f:
            header_html = f.read()
    except FileNotFoundError:
        header_html = f"<p> Unable to load header file {html_path}.</p>"

    return header_html


def hud_text_fn(game: remote_game.ServerGame) -> str:
    """Function to create HUD text to display"""
    left_red_score = game.total_positive_rewards["agent_left"]
    right_blue_score = game.total_positive_rewards["agent_right"]
    return f"Red Points: {int(left_red_score)} | Blue Points {int(right_blue_score)}"
