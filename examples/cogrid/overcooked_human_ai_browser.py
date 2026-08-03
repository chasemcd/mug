"""Overcooked against a trained partner, run entirely in the participant's browser.

The same task as ``overcooked_human_ai``, with nothing stepping on the server. The
kitchen runs in the participant's own browser through Pyodide, and the trained
policy is scored beside it by the browser's build of the same inference runtime the
server uses. So one machine holds the whole human-AI study, and the server only
records what it reports.

Choose this over the server-run version when the study must scale past what one
server can step, when a round trip per frame would be felt, or when the deployment
must do no per-participant computing at all. The cost is the download: the browser
fetches a Python runtime, the environment package, and the model before the first
round, so the study does that while the participant reads the instructions.

**What is recorded, and what verification means here.** The browser writes the
episode and reports it. The server re-executes the same bundle under the reported
actions and checks every state hash, which is what turns the report into evidence.
The partner is scored by a runtime the server has no copy of, so its decisions
travel with the run and are replayed into the re-execution. What that verifies is
the run: the trajectory follows from the actions reported, and the values recorded
are the server's own re-execution of it.

Run it with::

    uv run uvicorn examples.cogrid.overcooked_human_ai_browser:app

Install the environment first: ``uv pip install cogrid==0.3.2``. Nothing else is
needed on the server -- the model is served to the browser, not run here.
"""

from __future__ import annotations

from examples.cogrid import pages
from examples.cogrid.env import overcooked_browser
from examples.cogrid.sprites import overcooked_assets
from mug.app import build_app_from_env
from mug.content import Choice, Form, Game, Likert, Page, Study, Text

INSTRUCTIONS = pages.instructions(
    partner=(
        "You and an AI partner run a kitchen together. Everything runs in this "
        "browser, so it may take a moment to get ready."
    ),
    rounds="You will cook one round with this partner.",
)

DEBRIEF = """
# Thank you

Your partner was a policy trained to cook this kitchen. It ran in your own
browser, beside the kitchen itself: nothing about the game was computed on our
server.
"""


def overcooked_human_ai_browser_study() -> Study:
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
        # One round. A browser-executed game is written by the client and
        # captured once, so the server has no round loop for it: a study that asked
        # for three would play one and say nothing. The platform refuses that rather
        # than dropping it quietly, and a study that wants three rounds here writes
        # three game activities.
        Game("play", caption=pages.IN_GAME),
        Form(
            "post-survey",
            Likert(
                "effective", "How effective was your partner as a teammate?", scale=7
            ),
            Likert("enjoyed", "How much did you enjoy playing with them?", scale=7),
            Likert(
                "human-or-bot",
                "How likely is it that your partner was a person rather than a bot?",
                scale=7,
            ),
            Text("comments", "Anything to add? (optional)", required=False),
        ),
        Page("debrief", DEBRIEF),
        # The trained network is declared beside the pictures, because to this
        # study it is the same kind of thing: a file it ships, named rather than
        # addressed, and served by its own digest.
        assets=overcooked_assets(policy=True),
    )


def build() -> object:
    """Build the application that runs this study."""
    return build_app_from_env(
        study=overcooked_human_ai_browser_study(),
        browser_game=overcooked_browser(),
    )


app = build()
