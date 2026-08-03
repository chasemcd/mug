"""Two people play Slime Volleyball in their own browsers: the whole study.

There is no game server. Both browsers run the environment through Pyodide and
agree over their own data channels, with the platform's rollback keeping the two
replicas identical. The game is fast and frame-sensitive, which is exactly the
case rollback exists for.

Run it with::

    uv run uvicorn examples.slime_volleyball.human_human:app

The application prints one launch ticket at start, and the second participant
needs a second ticket against the same store.
"""

from __future__ import annotations

from examples.slime_volleyball.env import slime_volleyball_mesh
from mug.app import build_app_from_env
from mug.content import Choice, Form, Game, Likert, Page, Screen, Study, Text
from mug.participant_p2p_types import BrowserP2PConfig

INSTRUCTIONS = """
# Slime Volleyball

You will play against another participant. One of you is the **red** slime on the
left and one is the **blue** slime on the right.

- **Left and right arrows** move you.
- **Up arrow** jumps.
- **Up with left or right** jumps in that direction.

Land the ball on your opponent's side to score. You will wait a moment while we
find you a partner.
"""

DEBRIEF = """
# Thank you

You played against another real participant. The game ran in your two browsers
rather than on our server, and the two of you agreed on every frame.
"""


def slime_human_study() -> Study:
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
        Game("play"),
        Form(
            "post-survey",
            Likert("teamwork", "How well matched was your opponent?", scale=7),
            Likert("smoothness", "How smoothly did the game run?", scale=7),
            Text("comments", "Anything to add? (optional)", required=False),
        ),
        Page("debrief", DEBRIEF),
        # A fast game punishes a poor connection, and a participant on one is
        # better told so than left to a frustrating rally. The study declares the
        # connection it needs, and the platform measures, warns, and excludes.
        screen=Screen(max_rtt_ms=100, warn_after=2, exclude_after=4),
    )


def build() -> object:
    """Build the application that runs this study."""
    return build_app_from_env(
        study=slime_human_study(),
        browser_p2p=BrowserP2PConfig(
            channel_key="slime-volleyball",
            size=2,
            game=slime_volleyball_mesh(),
            seed=7,
        ),
        require_launch=True,
    )


app = build()
