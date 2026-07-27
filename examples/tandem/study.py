"""The Tandem study: what a researcher actually writes.

This is a whole study, not a game with a demo bolted around it. The participant
meets the activities in the order written here: they consent, read what they are
about to do, answer a short pre-survey, play the two-player game with a partner,
answer a post-survey about that partner, and read a debrief. The game is one step
among the others.

Run it with::

    uvicorn examples.tandem.study:app

The application prints one launch ticket at start, and a second participant needs
a second ticket against the same store (peer-to-peer needs two people).
"""

from __future__ import annotations

from examples.tandem.browser_mesh_env import tandem_mesh_spec
from mug.app import build_app_from_env
from mug.content import Choice, Form, Game, Likert, Page, Study, Text
from mug.participant_p2p_types import BrowserP2PConfig

INSTRUCTIONS = """
# Working together

You and another participant will each control one square on a shared grid.

A gold token appears somewhere on the grid. Whoever reaches it first scores a
point, and a new token appears. Use the **arrow keys** to move.

You will play one round. There is no way to talk to your partner, so you will
have to work out what they are doing from what they do.
"""

DEBRIEF = """
# Thank you

That is the end of the study.

You played with another real participant. Nothing you did was scored against you,
and your partner saw exactly the same grid you did.

If you have questions about this research, contact the study team at the address
on the consent page.
"""


def tandem_study() -> Study:
    """Return the ordered activities one participant walks through."""
    return Study(
        Form(
            "consent",
            Choice(
                "agree",
                "I have read the information sheet and agree to take part.",
                ["yes", "no"],
            ),
            Choice(
                "data-sharing",
                "I agree that my anonymised data may be shared with other"
                " researchers.",
                ["yes", "no"],
            ),
        ),
        Page("instructions", INSTRUCTIONS),
        Form(
            "pre-survey",
            Likert(
                "games-experience",
                "How often do you play video games?",
                scale=5,
            ),
            Likert(
                "cooperation-comfort",
                "How comfortable are you working with someone you cannot talk to?",
                scale=7,
            ),
        ),
        Game("play"),
        Form(
            "post-survey",
            Likert(
                "teamwork",
                "How well do you feel you and your partner worked together?",
                scale=7,
            ),
            Likert(
                "partner-strategy",
                "How predictable did your partner's moves feel?",
                scale=7,
            ),
            Text(
                "strategy",
                "What were you trying to do? (optional)",
                required=False,
            ),
        ),
        Page("debrief", DEBRIEF),
    )


# The game the ``play`` activity runs: two browsers, one grid, no game server.
tandem_game = BrowserP2PConfig(
    channel_key="tandem", size=2, game=tandem_mesh_spec(), seed=7
)

app = build_app_from_env(
    study=tandem_study(),
    browser_p2p=tandem_game,
    require_launch=True,
)
