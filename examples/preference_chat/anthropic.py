"""Preference elicitation in a chat, on a hosted Anthropic model.

The **same study** as `ollama.py`. What differs is the model the conversation runs
on and where its credential comes from — and the credential is the part worth
reading, because it is the one thing here that must never end up in the data.

Run it with::

    export ANTHROPIC_API_KEY=sk-ant-...
    uv run uvicorn examples.preference_chat.anthropic:app

`MUG_ANTHROPIC_MODEL` picks a different model.

## What happens to the key

It is read from the environment **at call time**, by a function, and it goes into
the ``x-api-key`` header of one request. It is not a field on the study, so it is
not in the compiled study version; it is not on the agent, so it is not in the
recorded build; and the adapter never returns it, logs it, or puts it in a
``ModelCompletion``. What the ledger records about the call is the request digest
and the **name** of the secret, never its value.

That is why ``resolve_secret`` is a function rather than a string. A string would
be captured wherever the study was captured — which, for a study that is compiled,
published, and exported, is several places a key has no business being.
"""

from __future__ import annotations

import os

from examples.preference_chat.agent import Counsellor
from examples.preference_chat.study import preference_chat_study
from mug.app import build_app_from_env
from mug.authoring import Provider
from mug.content import Study

ANTHROPIC_MODEL = os.environ.get("MUG_ANTHROPIC_MODEL", "claude-sonnet-5")
# The name the ledger records for this credential. It is an authoring key, not the
# key itself, and it is what a reader of the data sees where the secret was used.
SECRET_NAME = "anthropic-api-key"


class HostedCounsellor(Counsellor):
    """The shared agent, pinned to a hosted model.

    These three lines are the whole difference from ``ollama.py``. Everything the
    participant meets -- the instructions, the two replies, the axes, the survey --
    is written once in ``study.py`` and ``agent.py``.
    """

    provider = Provider.ANTHROPIC
    model = ANTHROPIC_MODEL
    # The *name* of the credential, not the credential. It is what the ledger
    # records where the secret was used, and what `read_api_key` is asked for.
    secret = SECRET_NAME


class MissingApiKey(RuntimeError):
    """The study needs a credential that the environment does not hold."""


def read_api_key(name: str) -> str:
    """Return the credential for one secret name, read when the call is made.

    It is read here rather than at import, so a key rotated while the study is
    running is picked up by the next call rather than at the next restart.
    """
    if name != SECRET_NAME:
        raise MissingApiKey(f"this study holds no credential named {name!r}")
    value = os.environ.get("ANTHROPIC_API_KEY")
    if not value:
        raise MissingApiKey(
            "this example needs an Anthropic credential:"
            " export ANTHROPIC_API_KEY=sk-ant-..."
        )
    return value


def hosted_study() -> Study:
    """Return the study, with its conversation run on the hosted model."""
    return preference_chat_study(HostedCounsellor(), resolve_secret=read_api_key)


def build() -> object:
    """Build the application that runs this study.

    The key is **not** checked here. A study that refused to start without one
    could not be imported to read its shape, and the adapter already turns a
    provider fault into the seat's fallback rather than an unhandled error. The
    check happens on the first call, where the failure can be recorded.
    """
    return build_app_from_env(study=hosted_study())


app = build()
