"""Slime Volleyball against an exported network: the whole study.

The partner is a trained policy exported to ONNX. The server steps the
environment and runs the inference, so the participant's browser downloads no
model and the study's weights never leave the deployment.

Run it with::

    uv run uvicorn examples.slime_volleyball.human_ai:app

It needs the environment and the inference runtime::

    uv pip install slimevb onnxruntime
"""

from __future__ import annotations

import functools
from pathlib import Path
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
from examples.slime_volleyball.policies import exported_partner
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

MODEL = str(Path(__file__).resolve().parent / "assets/models/slimevb_policy.onnx")

INSTRUCTIONS = """
# Slime Volleyball

You control the **red slime** on the left. Land the ball on your opponent's side
to score.

- **Left and right arrows** move you.
- **Up arrow** jumps.
- **Up with left or right** jumps in that direction.

You will play two rallies against a trained opponent.
"""

DEBRIEF = """
# Thank you

Your opponent was a neural network trained to play this game. It saw the same
court you did, and it chose the action it scored highest on every frame.
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


def slime_ai_study() -> Study:
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
        # The court, and who plays which slime. The trained partner needs only its
        # own seat's observation, which is what the platform hands a seat.
        Game(
            "play",
            functools.partial(slime_court, max_steps=RALLY_STEPS),
            seats={LEFT_SEAT: Human(), RIGHT_SEAT: Bot(exported_partner(MODEL))},
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
    return build_app_from_env(study=slime_ai_study())


app = build()
