"""Preference elicitation in a chat, on a model running on your own machine.

No API key, no per-token cost, and no participant text leaving the deployment.
That last one is the reason to reach for this first: a study that elicits
preferences inside a conversation is asking participants to type whatever is on
their mind, and a local model keeps every word of it on the machine you run.

Run a model, then run the study::

    ollama serve
    ollama pull llama3.2

    uv run uvicorn examples.preference_chat.ollama:app

`MUG_OLLAMA_URL` points at a runner somewhere other than
``http://localhost:11434``. `MUG_OLLAMA_MODEL` picks a different model; whatever
you name must be one ``ollama pull`` has already fetched.

`anthropic.py` runs the **same study** on a hosted model. Comparing the two files
is the point: they differ in the agent's provider line and in where a credential
comes from, and in nothing else.
"""

from __future__ import annotations

import os

from examples.preference_chat.agent import Counsellor
from examples.preference_chat.study import preference_chat_study
from mug.agents.adapters import adapter_for
from mug.app import build_app_from_env
from mug.authoring import Provider
from mug.content import Study

# Where the runner is, and which model it should use. Both have working defaults,
# so a reader who has run `ollama pull llama3.2` needs to set nothing.
_DEFAULT_URL = "http://localhost:11434"
OLLAMA_URL = os.environ.get("MUG_OLLAMA_URL", _DEFAULT_URL)
OLLAMA_MODEL = os.environ.get("MUG_OLLAMA_MODEL", "llama3.2")


class LocalCounsellor(Counsellor):
    """The shared agent, pinned to a local runner and a model you have pulled."""

    provider = Provider.OLLAMA
    model = OLLAMA_MODEL


def local_study() -> Study:
    """Return the study, with its conversation run on the local model runner.

    The adapter is named only when the runner is somewhere other than the default
    address. A study happy with ``http://localhost:11434`` passes the agent alone and
    the adapter follows from its declared provider.

    There is no ``resolve_secret``: a local runner has no credential, which is most
    of why this example exists.
    """
    elsewhere = OLLAMA_URL != _DEFAULT_URL
    return preference_chat_study(
        LocalCounsellor(),
        adapter=adapter_for("oss", base_url=OLLAMA_URL) if elsewhere else None,
    )


def build() -> object:
    """Build the application that runs this study."""
    return build_app_from_env(study=local_study())


app = build()
