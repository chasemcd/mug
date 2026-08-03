"""Overcooked with a partner you can talk to: three rounds, one conversation.

The partner is a language model. It cooks beside the participant in the same
kitchen, on the same timeline, and the two can write to each other while they play.
What makes it a study rather than a demonstration is the third round: the
conversation is one conversation across all three, so whatever the pair worked out
in round one is in the model's prompt in round three.

Compare this file against ``overcooked_human_ai.py``, which is the same kitchen with
a trained network in the second seat. Three lines differ:

- the second chef is a ``Model`` rather than a ``Bot``;
- the activity carries a ``Chat``;
- the activity plays three rounds instead of one.

The kitchen, the keys, the drawing, the status line and the frame rate are the
shipped ones, untouched.

**The model decides jobs, not moves.** That is the whole reason the kitchen can run
at thirty frames a second with a model in it: see ``chef_agent.TalkingChef``.

Run it with::

    ollama serve
    ollama pull llama3.2
    uv run uvicorn examples.cogrid.overcooked_llm_chat:app

Install the environment first: ``uv pip install cogrid==0.3.2``.

``MUG_OLLAMA_URL`` points at a runner somewhere other than
``http://localhost:11434``; ``MUG_OLLAMA_MODEL`` picks a different model, which
must be one ``ollama pull`` has already fetched. A larger model keeps to the reply
shape more reliably and is worth it here.

**To watch the chef think, run it with ``MUG_DEBUG=1``.** A drawer opens on the
study's own screen (the backtick key, or the button in the corner) and holds what
the seat was asked, what came back, how long it took, which job was read out of the
reply, and what it said. The same notes are at ``/_debug/notes`` for a script. It
is off unless it is asked for, because a prompt is not a participant's to read::

    MUG_DEBUG=1 uv run uvicorn examples.cogrid.overcooked_llm_chat:app

**A hosted model is one argument.** Nothing else in this file changes::

    class HostedChef(TalkingChef):
        provider = Provider.ANTHROPIC
        model = "claude-sonnet-5"
        secret = "anthropic-api-key"

    study = overcooked_llm_chat_study(
        HostedChef(), resolve_secret=lambda name: os.environ["ANTHROPIC_API_KEY"]
    )

The credential is resolved by a function at call time and never written into the
study, so it is absent from the compiled study version, the published bundle, and
the recorded agent build.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import os
from typing import Any

from examples.cogrid import pages
from examples.cogrid.chef_agent import TalkingChef
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
from examples.cogrid.kitchen_text import kitchen_as_text
from examples.cogrid.sprites import overcooked_assets
from mug.agents.adapters import adapter_for
from mug.app import build_app_from_env
from mug.authoring import LLMAgent
from mug.content import (
    Chat,
    Choice,
    Form,
    Game,
    Human,
    Likert,
    Model,
    Page,
    Study,
    Text,
)
from mug.providers.runtime import ProviderAdapter, SecretResolver

# Where a local runner is, and which model it should use. Both have working
# defaults, so a reader who has run ``ollama pull llama3.2`` needs to set nothing.
_DEFAULT_URL = "http://localhost:11434"
OLLAMA_URL = os.environ.get("MUG_OLLAMA_URL", _DEFAULT_URL)
OLLAMA_MODEL = os.environ.get("MUG_OLLAMA_MODEL", "llama3.2")

# The kitchen both this study and the trained-partner study cook in. One layout is
# what makes three rounds about the pair rather than about the room.
LAYOUT = "cramped_room"
ROUND_STEPS = 600

# Three rounds, because the point of talking is what a pair works out **between**
# rounds. One round shows a partner that can be instructed; three show whether the
# instruction carried.
ROUNDS = 3

# What every round of this study is. It is the shipped kitchen and nothing about it
# was slowed down or shortened for the model: a chef on a grid moves once per press,
# stands still on a frame with no key, and the shift runs at thirty frames a second.
COOKING: dict[str, Any] = {
    "keys": ACTION_BINDINGS,
    "held_actions": False,
    "default_action": NOOP,
    "fps": FPS,
    "render": render,
    "scene": overcooked_scene(LAYOUT),
    "hud": kitchen_hud,
    "caption": pages.IN_GAME_WITH_TALK,
    "size": kitchen_size(LAYOUT),
}

GREETING = (
    "Hello. I am cooking with you. Tell me what you want me to do and I will do it."
)


class LocalChef(TalkingChef):
    """The shared partner, pinned to a local runner and a model you have pulled."""

    model = OLLAMA_MODEL


def overcooked_llm_chat_study(
    agent: LLMAgent | None = None,
    *,
    adapter: ProviderAdapter | None = None,
    resolve_secret: SecretResolver | None = None,
    rounds: int = ROUNDS,
    steps: int = ROUND_STEPS,
) -> Study:
    """Return the ordered activities one participant walks through.

    ``agent`` is the partner. With none, the local chef runs, which is what makes a
    hosted model one argument rather than an edit: a subclass that names another
    provider changes nothing else here.

    ``rounds`` and ``steps`` are how many rounds and how long each is. They have the
    shipped values, and a test that walks the whole study in a browser shortens
    ``steps`` alone -- how long a round lasts is a property of the environment,
    where every other thing about the activity is the study's.
    """
    return Study(
        Form(
            "consent",
            Choice(
                "agree",
                "I have read the information sheet and agree to take part.",
                ["yes", "no"],
            ),
        ),
        Page(
            "instructions",
            pages.instructions(partner=pages.TALKING_AI, rounds=pages.THREE_ROUNDS),
        ),
        Game(
            "cook",
            overcooked_kitchen(LAYOUT, steps),
            seats={
                CHEF_ONE: Human(),
                # The seating is written exactly as it is for a trained partner.
                # What makes this chef decide jobs rather than grid moves is two
                # methods on the agent, so nothing about the seat has to say it.
                CHEF_TWO: Model(
                    agent or LocalChef(),
                    # What the model is shown of the kitchen. The runtime records it
                    # into the agent's own history too, so it reads what the kitchen
                    # looked like three decisions ago as well as now.
                    text_view=kitchen_as_text,
                    adapter=adapter,
                    resolve_secret=resolve_secret,
                ),
            },
            # Three rounds of one activity are one interaction, so they are one
            # conversation: what the pair agreed in round one is in the model's
            # prompt in round three.
            episodes=rounds,
            between=pages.BETWEEN_ROUNDS_TALKING,
            chat=Chat("kitchen-talk", greeting=GREETING, max_messages=200),
            **COOKING,
        ),
        Form(
            "post-survey",
            Likert("understood", "My partner understood what I asked for.", scale=7),
            Likert("helped", "Talking to my partner helped us cook.", scale=7),
            Likert(
                "changed", "My partner changed what it did after I asked.", scale=7
            ),
            Text(
                "reasoning",
                "What did you say to your partner, and did it work? (optional)",
                required=False,
            ),
        ),
        Page("debrief", pages.DEBRIEF_TALKING),
        assets=overcooked_assets(),
    )


def local_study() -> Study:
    """Return the study, with its partner run on the local model runner.

    The adapter is named only when the runner is somewhere other than the default
    address. A study happy with ``http://localhost:11434`` names no adapter and the
    one its declared provider names is used.

    There is no ``resolve_secret``: a local runner has no credential.
    """
    elsewhere = OLLAMA_URL != _DEFAULT_URL
    return overcooked_llm_chat_study(
        adapter=adapter_for("oss", base_url=OLLAMA_URL) if elsewhere else None
    )


def build() -> object:
    """Build the application that runs this study."""
    return build_app_from_env(study=local_study())


app = build()
