"""Two people cook together in their own browsers: the whole study.

There is no game server. Both browsers run the kitchen through Pyodide and agree
over their own data channels. Each pair is given **one** of the five layouts, so
the study covers all five across its participants without asking anybody to play
five rounds.

Run it with::

    uv run uvicorn examples.cogrid.overcooked_human_human:app

Install the environment first: ``uv pip install cogrid==0.3.2``. The application
prints one launch ticket at start, and the second participant needs a second
ticket against the same store.
"""

from __future__ import annotations

from examples.cogrid import pages
from examples.cogrid.env import LAYOUTS, overcooked_mesh
from examples.cogrid.sprites import overcooked_assets
from mug.app import build_app_from_env
from mug.content import Choice, Form, Game, Likert, Page, Screen, Study, Text
from mug.participant_p2p_types import BrowserP2PConfig

INSTRUCTIONS = pages.instructions(partner=pages.HUMAN_HUMAN)

# The kitchen this deployment runs. The five layouts are a deployment choice
# rather than a per-pair one: both browsers must ship the same environment, and a
# room forms before either of them could be told which layout they were given. A
# study that wants all five runs one deployment for each and pools the exports.
LAYOUT = LAYOUTS[0][0]


def overcooked_human_human_study() -> Study:
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
        # One round. A peer-to-peer room runs once to its end: the two browsers
        # agree on one episode and the room closes, so there is no round loop for
        # the server to run. A study that asked for five here would have played one
        # and said nothing, which the platform now refuses rather than dropping.
        Game("play", caption=pages.IN_GAME),
        Form(
            "post-survey",
            Likert(
                "effective",
                "How effective was your partner as a teammate?",
                scale=7,
            ),
            Likert("enjoyed", "How much did you enjoy playing with them?", scale=7),
            Likert("their-part", "How much did your partner contribute?", scale=7),
            Likert("my-part", "How much did you contribute?", scale=7),
            Likert(
                "human-or-bot",
                "How likely is it that your partner was a person rather than a bot?",
                scale=7,
            ),
            Text("comments", "Anything to add? (optional)", required=False),
        ),
        Page("debrief", pages.DEBRIEF_PEOPLE),
        assets=overcooked_assets(),
        # A pair whose connection is poor will feel every rollback, so the study
        # says what it needs and the platform measures, warns, and excludes.
        screen=Screen(max_rtt_ms=100, warn_after=2, exclude_after=4),
    )


def build() -> object:
    """Build the application that runs this study."""
    return build_app_from_env(
        study=overcooked_human_human_study(),
        browser_p2p=BrowserP2PConfig(
            channel_key="overcooked",
            size=2,
            game=overcooked_mesh(layout=LAYOUT),
            seed=11,
        ),
        require_launch=True,
    )


app = build()
