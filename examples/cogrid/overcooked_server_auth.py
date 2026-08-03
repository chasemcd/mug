"""Two people cook together, with the server stepping the kitchen: the whole study.

The same task as ``overcooked_human_human``, run the other way. The server holds
the environment, reads both participants' keys, and pushes every frame, so nobody's
machine decides what happened.

Choose this over the peer-to-peer version when the environment is too heavy for a
browser, when the study must not trust a participant's machine, or when a
participant's connection cannot carry a data channel. The cost is a round trip per
frame, which a fast game feels and this one does not.

Run it with::

    uv run uvicorn examples.cogrid.overcooked_server_auth:app

Install the environment first: ``uv pip install cogrid==0.3.2``.
"""

from __future__ import annotations

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
from examples.cogrid.sprites import overcooked_assets
from mug.app import build_app_from_env
from mug.content import Choice, Form, Game, Human, Likert, Page, Study, Text

INSTRUCTIONS = pages.instructions(partner=pages.HUMAN_HUMAN)

# The kitchen this deployment runs, and how long one round lasts.
LAYOUT = "cramped_room"
ROUND_STEPS = 1350


def overcooked_server_auth_study() -> Study:
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
        # Who cooks which chef is written down rather than taken from the order
        # two people happened to connect in. The chefs are CoGrid's own agents, so
        # there is no map from a seat name to an environment agent to get wrong.
        Game(
            "play",
            overcooked_kitchen(LAYOUT, ROUND_STEPS),
            seats={CHEF_ONE: Human(), CHEF_TWO: Human()},
            keys=ACTION_BINDINGS,
            held_actions=False,
            default_action=NOOP,
            fps=FPS,
            render=render,
            scene=overcooked_scene(LAYOUT),
            hud=kitchen_hud,
            size=kitchen_size(LAYOUT),
            episodes=5,
            between=pages.BETWEEN_ROUNDS,
            caption=pages.IN_GAME,
        ),
        Form(
            "post-survey",
            Likert(
                "effective", "How effective was your partner as a teammate?", scale=7
            ),
            Likert("enjoyed", "How much did you enjoy playing with them?", scale=7),
            Text("comments", "Anything to add? (optional)", required=False),
        ),
        Page("debrief", pages.DEBRIEF_PEOPLE),
        assets=overcooked_assets(),
    )


def build() -> object:
    """Build the application that runs this study."""
    return build_app_from_env(study=overcooked_server_auth_study())


app = build()
