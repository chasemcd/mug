"""Compile a conversation the way the platform does, for the tests that run one.

A conversation is written once, as ``Chat(...)``, and compiled into the
``ChatSpec`` the runtime reads. That is the only path a study has, so it is the
only path a test has: a test that built a ``ChatSpec`` by hand could exercise a
conversation no author is able to write, and would go on passing after the author's
way of writing it stopped reaching the runtime. That is exactly what happened --
``Game(chat=Chat(...))`` compiled to nothing and said nothing, while every test
passed, because every test wrote the compiled form.

``chat_spec`` is the one seam. It takes what an author writes and returns what the
runtime reads, through the platform's own ``chat_for``.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

from typing import Any

from mug.content import Chat, Step
from mug.mounts import chat_for
from mug.participant_chat import ChatSpec

# The channel a conversation is on when the test does not care which. It is the
# platform's own default, so a test that names nothing runs what a study that
# names nothing runs.
CHANNEL = "chat"


def derived(kind: str, words: str) -> str:
    """Mint one derived identifier, as a gateway does but without one.

    A test that pins its seats never reaches this: an authored ``Model`` speaker is
    what needs an identifier derived, and a compiled ``ChatSeatSpec`` brought its
    own.
    """
    return f"{kind}_{words}"


def chat_spec(key: str = CHANNEL, *speakers: Any, **written: Any) -> ChatSpec:
    """Return the runtime specification for one authored conversation.

    Everything an author may write is written here -- the speakers, the greeting,
    the bound, the placement -- and everything the runtime needs is derived, which
    is what the platform does with a study's own ``Chat(...)``.

    A conversation's key **is** its channel, so a test that names the channel the
    compiled way is read as naming the conversation. The platform refuses the two
    written together, which is right for an author and unhelpful for a helper whose
    callers build their keywords in a dictionary.
    """
    talk = written_chat(key, *speakers, **written).talk
    assert talk is not None, "Chat() built a step with no conversation in it"
    return chat_for(talk, derived_id=derived)


def written_chat(key: str = CHANNEL, *speakers: Any, **written: Any) -> Step:
    """Return one conversation exactly as an author writes it.

    This is what goes to the author's own surface -- ``Game(chat=...)`` and
    ``build_study_app(chat=...)``, both of which take ``Chat(...)`` and refuse the
    compiled form. ``chat_spec`` compiles this, and is what goes to the runtime.
    """
    named = dict(written)
    key = str(named.pop("channel_key", key))
    return Chat(key, *speakers, **named)


__all__ = ["CHANNEL", "chat_spec", "derived", "written_chat"]
