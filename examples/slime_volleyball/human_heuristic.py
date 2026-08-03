"""Slime Volleyball against a heuristic partner: the whole study.

One person plays the left slime; a hand-written policy plays the right one. The
server steps the environment, so the policy is ordinary Python and reaches no
provider and no network.

Run it with::

    uv run uvicorn examples.slime_volleyball.human_heuristic:app

Install the environment first: ``uv pip install slimevb``.
"""

from __future__ import annotations

import functools
from typing import Any

from examples.slime_volleyball.env import (
    ACTION_BINDINGS,
    LEFT_SEAT,
    NOOP,
    RIGHT_SEAT,
    court_scene,
    render,
    slime_court,
)
from examples.slime_volleyball.policies import ball_chaser
from mug.app import build_app_from_env
from mug.content import (
    Bot,
    Choice,
    Form,
    Game,
    Human,
    Likert,
    Page,
    Study,
    Text,
)

INSTRUCTIONS = """
# Slime Volleyball

You control the **red slime** on the left. Land the ball on your opponent's side
to score.

- **Left and right arrows** move you.
- **Up arrow** jumps.
- **Up with left or right** jumps in that direction.

You will play two rallies.
"""

DEBRIEF = """
# Thank you

You played against a policy the study wrote: it moves towards where the ball is
going, and jumps at a ball that is dropping near it. It does not learn, and it
did not adapt to you.
"""


# The court both studies play on, and how long a rally lasts. The frame rate is the
# study's own: the package declares one in a key Gymnasium does not specify, so the
# platform reads none, and how fast somebody plays is an experiment's decision anyway.
RALLY_STEPS = 3000
COURT_FPS = 30

# What every rally of this study is. A court is the case where a key acts on every
# frame it is held: letting go of "left" is itself a decision, and a slime that
# stepped once per press would stand still while the ball went past.
PLAYING: dict[str, Any] = {
    "keys": ACTION_BINDINGS,
    "held_actions": True,
    "default_action": NOOP,
    "fps": COURT_FPS,
    "render": render,
    "scene": court_scene,
}


def slime_heuristic_study() -> Study:
    """Return the ordered activities one participant walks through."""
    return Study(
        Form(
            "consent",
            Choice(
                "agree",
                "I have read the information sheet and agree to take part.",
                ["yes", "no"],
            ),
        ),
        Page("instructions", INSTRUCTIONS),
        # The court, and who plays which slime. The seats are the environment's own
        # agents, so there is no map from a study's word for a slime to the
        # environment's to get wrong.
        Game(
            "play",
            functools.partial(slime_court, max_steps=RALLY_STEPS),
            seats={LEFT_SEAT: Human(), RIGHT_SEAT: Bot(ball_chaser())},
            episodes=2,
            between="Take a moment, then start the next rally.",
            **PLAYING,
        ),
        Form(
            "post-survey",
            Likert("difficulty", "How hard was your opponent to play?", scale=7),
            Likert("humanlike", "How human-like did your opponent feel?", scale=7),
            Text("strategy", "What were you trying to do? (optional)", required=False),
        ),
        Page("debrief", DEBRIEF),
    )


def build() -> object:
    """Build the application that runs this study."""
    return build_app_from_env(study=slime_heuristic_study())


app = build()
