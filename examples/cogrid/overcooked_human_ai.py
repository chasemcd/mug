"""Overcooked with two AI partners, and a judgement between them: the whole study.

This is the within-subject partner comparison the legacy study ran, written on the
new stack. The participant cooks one round with each partner and then says which
one they preferred -- overall, and on the four axes the study cares about.

The comparison is one object. The platform blinds the two partners, shuffles which
one is shown first, records the choice against the **candidate**, and exports the
result beside the two trajectories it is about. The legacy version needed a custom
scene with sliders and a text box, and recorded the answer as free-form scene data.

Run it with::

    uv run uvicorn examples.cogrid.overcooked_human_ai:app

Install the environment first: ``uv pip install cogrid==0.3.2``. The trained
partner needs ``uv pip install onnxruntime``.
"""

from __future__ import annotations

from typing import Any

from examples.cogrid import pages
from examples.cogrid.env import (
    ACTION_BINDINGS,
    CHEF_ONE,
    CHEF_TWO,
    FPS,
    NOOP,
    kitchen_hud,
    kitchen_size,
    overcooked_kitchen,
    overcooked_scene,
    render,
)
from examples.cogrid.partners import exported_partner, scripted_chef
from examples.cogrid.sprites import overcooked_assets
from mug.app import build_app_from_env
from mug.authoring import Axis, Comparison
from mug.content import Bot, Choice, Form, Game, Human, Likert, Page, Study, Text

INSTRUCTIONS = pages.instructions(partner=pages.HUMAN_AI, rounds=pages.TWO_ROUNDS)

# The kitchen both rounds are cooked in, and how long a round lasts. One layout for
# both rounds is what makes the comparison about the partner: a participant who
# preferred the second partner in a different kitchen has said nothing about either.
LAYOUT = "cramped_room"
ROUND_STEPS = 600

# What every round of this study is: a kitchen is a grid, so one press is one move,
# and a frame with no key held is a chef standing still. Held keys would make a tap of
# the pick-up key put a dish down and take it back thirty times a second.
COOKING: dict[str, Any] = {
    "keys": ACTION_BINDINGS,
    "held_actions": False,
    "default_action": NOOP,
    "fps": FPS,
    "render": render,
    "scene": overcooked_scene(LAYOUT),
    "hud": kitchen_hud,
    "caption": pages.IN_GAME,
    "size": kitchen_size(LAYOUT),
}

# What the judgement is made on. The first four are the statements the legacy
# study put on sliders; the fifth asks each partner to be rated on its own rather
# than against the other.
AXES = [
    Axis("coordination", "We coordinated our actions well together."),
    Axis("perceptive", "My partner understood what I was trying to do."),
    Axis("predictable", "I could predict what my partner would do next."),
    Axis("humanlike", "My partner felt human-like."),
    Axis("helpful", "How helpful was each partner?", each=True, points=7),
]


def overcooked_first_round() -> object:
    """Return the first round: one person, and the trained network beside them.

    The partner is the network the legacy study played against, and it needs nothing
    but its own seat's observation. It needs ``onnxruntime``: ``uv pip install
    onnxruntime``.
    """
    return Game(
        "round-one",
        overcooked_kitchen(LAYOUT, ROUND_STEPS),
        seats={CHEF_ONE: Human(), CHEF_TWO: Bot(exported_partner())},
        **COOKING,
    )


def overcooked_second_round() -> object:
    """Return the second round: a partner written by hand.

    The comparison is worth asking because the two partners are different in kind,
    not in setting: one is trained and one follows a written recipe. This one plans a
    route, so it reads the kitchen rather than an observation -- which it says by
    naming a ``sees``, not by holding an environment of its own.
    """
    return Game(
        "round-two",
        overcooked_kitchen(LAYOUT, ROUND_STEPS),
        seats={CHEF_ONE: Human(), CHEF_TWO: Bot(scripted_chef())},
        **COOKING,
    )


def overcooked_human_ai_study() -> Study:
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
        # Two rounds, two different partners. Each activity names the environment it
        # runs and who is in it, so the manipulation is written where it takes effect.
        overcooked_first_round(),
        Page("between", pages.BETWEEN_PARTNERS),
        overcooked_second_round(),
        Comparison(
            key="which-partner",
            ask="Did you prefer your first or your second partner?",
            options={"First partner": "round-one", "Second partner": "round-two"},
            ties=True,
            on=AXES,
        ),
        Form(
            "post-survey",
            Likert("enjoyment", "How much did you enjoy the task?", scale=7),
            Text(
                "reasoning",
                "Anything else about why you preferred one partner? (optional)",
                required=False,
            ),
        ),
        Page("debrief", pages.DEBRIEF_PARTNERS),
        assets=overcooked_assets(),
    )


def build() -> object:
    """Build the application that runs this study.

    Nothing is mounted beside the study: each round names the game it runs, so
    there is no study-wide game for one of them to fall back to.
    """
    return build_app_from_env(study=overcooked_human_ai_study())


app = build()
