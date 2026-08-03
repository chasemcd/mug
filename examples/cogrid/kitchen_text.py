"""What a language model is shown of the kitchen it is cooking in.

The platform hands a seat its own observation, which for this kitchen is 892
numbers. That is exactly right for the trained partner in
``overcooked_human_ai.py`` and it is nothing a language model can act on. So the
study says what the kitchen looks like, in words.

It is one function used twice, and that is why it is one function:

- ``Model(chef, text_view=kitchen_as_text)`` -- the runtime records it into the
  agent's own history, so the model reads what the kitchen looked like three
  decisions ago as well as now;
- ``TalkingChef.get_prompt`` calls it on the live environment for the decision
  being made.

Nothing here is platform code. What a kitchen looks like is the study's own
business, exactly as ``overcooked_scene`` is for the picture.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from typing import Any

from examples.cogrid.env import caught_up

# What a chef can be holding, in the words the model reads. The environment's own
# class names are read into this once, here, the same way the sprite map does it.
CARRIED = {
    "Onion": "an onion",
    "Plate": "a clean plate",
    "OnionSoup": "a bowl of soup",
}

# One letter a square, so the map is short enough to read and short enough to send.
# A model reading a room needs the shape of it more than it needs the words.
LETTER = {
    "Counter": "#",
    "Wall": "#",
    "Pot": "P",
    "DeliveryZone": "D",
    "OnionStack": "O",
    "PlateStack": "L",
}

LEGEND = "# counter, P pot, D serving hatch, O onion crate, L plate rack, . floor"

FACING = {0: "east", 1: "south", 2: "west", 3: "north"}

# How many onions make one soup. It is CoGrid's own rule and the model is told it,
# because a partner that does not know how many onions a pot takes fills it wrong.
POT_HOLDS = 3


def kitchen_as_text(env: Any, agent_id: Any) -> str:
    """Return the kitchen in words, from one chef's point of view.

    Four things, because these are the four a cook acts on: where everything is,
    where the two chefs are and what each is holding, what the pots hold, and how
    much of the shift is left.
    """
    kitchen = caught_up(getattr(env, "env", env))
    return "\n".join(
        [
            _floor(kitchen),
            "",
            *_chefs(kitchen, str(agent_id)),
            *_pots(kitchen),
            _shift(kitchen),
        ]
    )


def _floor(kitchen: Any) -> str:
    """Return the floor plan, one letter a square, with the rows and columns named.

    Both are numbered, because every other line of the description names a square
    by its row and its column and a map nobody can index into is a picture rather
    than a statement.
    """
    height, width = int(kitchen.grid.height), int(kitchen.grid.width)
    rows = []
    for row in range(height):
        squares = [
            _square(kitchen.grid.get(row, column)) for column in range(width)
        ]
        rows.append(f"row {row}:  " + " ".join(squares))
    columns = "        " + " ".join(str(one) for one in range(width))
    return "\n".join(
        [f"The kitchen has {height} rows and {width} columns.", columns, *rows, LEGEND]
    )


def _square(item: Any) -> str:
    """Return the one letter that stands for what is on a square."""
    return "." if item is None else LETTER.get(type(item).__name__, "?")


def _chefs(kitchen: Any, me: str) -> list[str]:
    """Return where each chef is, which one the model is, and what each holds."""
    said = []
    for number, chef in kitchen.grid.grid_agents.items():
        carrying = type(chef.inventory[0]).__name__ if chef.inventory else ""
        who = "You are" if str(number) == me else "Your partner is"
        said.append(
            f"{who} chef {number}, at row {int(chef.pos[0])} column "
            f"{int(chef.pos[1])}, facing {FACING[int(chef.dir)]}, holding "
            f"{CARRIED.get(carrying, 'nothing')}."
        )
    return said


def _pots(kitchen: Any) -> list[str]:
    """Return what each pot holds, and whether its soup can be collected."""
    said = []
    for item in kitchen.grid.grid:
        if item is None or type(item).__name__ != "Pot":
            continue
        where = f"row {int(item.pos[0])} column {int(item.pos[1])}"
        count = len(item.objects_in_pot)
        timer = int(item.cooking_timer)
        if count == 0:
            said.append(f"The pot at {where} is empty. It needs {POT_HOLDS} onions.")
        elif count < POT_HOLDS:
            said.append(f"The pot at {where} holds {count} of {POT_HOLDS} onions.")
        elif timer:
            said.append(f"The pot at {where} is cooking, {timer} steps left.")
        else:
            said.append(f"The pot at {where} is READY. Bring a plate to it.")
    return said


def _shift(kitchen: Any) -> str:
    """Return the score and how much of the shift is left."""
    left = max(0, int(kitchen.max_steps) - int(kitchen.t))
    return (
        f"Dishes delivered so far: {int(kitchen.cumulative_score)}. "
        f"Steps left in the shift: {left}."
    )


__all__ = ["CARRIED", "FACING", "LEGEND", "LETTER", "POT_HOLDS", "kitchen_as_text"]
