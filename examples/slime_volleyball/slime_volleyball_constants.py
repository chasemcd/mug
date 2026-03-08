"""Shared constants for Slime Volleyball experiments."""
from __future__ import annotations

NOOP = 0
LEFT = 1
UPLEFT = 2
UP = 3
UPRIGHT = 4
RIGHT = 5

ACTION_MAPPING = {
    "ArrowLeft": LEFT,
    ("ArrowLeft", "ArrowUp"): UPLEFT,
    "ArrowUp": UP,
    ("ArrowRight", "ArrowUp"): UPRIGHT,
    "ArrowRight": RIGHT,
}
