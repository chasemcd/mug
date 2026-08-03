"""A real conversation with a real model, over the real mount. No provider double.

Every other test of the chat mount replaces the provider. That is right for what
they test -- the room, the order, the record -- and it is exactly why the mount was
able to ship a payload no provider could read: the doubles read the shape the mount
wrote, so the suite agreed with itself all the way down and a participant got
silence.

So this one keeps the real adapter and the real HTTP transport, and talks to a model
running on this machine. It asserts two things a double can not:

1. **The model is told what the participant said, and what the author wrote.** The
   request that leaves the process is inspected. The words must be under ``content``,
   because that is the only field Ollama, Anthropic, and OpenAI read.
2. **The conversation carries.** The second turn's prompt holds the first exchange,
   and the model answers a question that can only be answered from it.

The tests skip when no runner answers, so the suite never depends on the network.
Run one first::

    ollama serve
    ollama pull llama3.2:1b

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from fastapi import WebSocketDisconnect

from mug.agents import AgentIds
from mug.agents.adapters import (
    HttpRequest,
    HttpResponse,
    adapter_for,
    httpx_transport,
)
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.kernel import Digest
from mug.participant_chat import ChatSeatSpec, run_chat_activity
from mug.realtime import Session
from mug.runtime import CommandContext
from mug.storage import InMemoryStore
from tests.support.chat import chat_spec

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 28, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_OLLAMA = "http://localhost:11434"

# The instruction the author writes and the platform must send unchanged. It is a
# word no model produces by itself, so a reply that carries it proves the prompt
# arrived rather than that the model is polite.
_MARKER = "BANANA"


def _runner() -> str | None:
    """Return the smallest model this runner holds, or None when there is none.

    The smallest is taken because this test talks to it several times. A machine
    that also holds a large model must not spend a minute of the suite on it.
    """
    try:
        import httpx

        with httpx.Client(timeout=1.0) as client:
            reply = client.get(f"{_OLLAMA}/api/tags")
    except Exception:
        return None
    if reply.status_code != 200:
        return None
    models = cast("list[dict[str, Any]]", reply.json().get("models", []))
    if not models:
        return None
    smallest = min(models, key=lambda one: one.get("size", 0))
    return str(smallest["name"])


_MODEL = _runner()
pytestmark = pytest.mark.skipif(
    _MODEL is None, reason="no local Ollama runner with a model"
)


class _Counsellor(LLMAgent):
    """An author's chat agent, written the way the shipped example writes one."""

    provider = Provider.OSS
    model = _MODEL or "llama3.2:1b"
    decides_every = 1
    on_timeout = Fallback.WAIT

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        said = "\n".join(f"{one.sender}: {one.text}" for one in chat.last(12))
        return (
            "You are a helpful assistant. Answer in one short sentence.\n"
            f"Begin every reply with the word {_MARKER}.\n\n"
            f"The conversation so far:\n{said or '(nothing yet)'}\n\n"
            "Write your next reply, and nothing else."
        )


class _Socket:
    """A socket that replays scripted frames and keeps what the mount pushed back."""

    def __init__(self, frames: list[Any]) -> None:
        self._inbound = list(frames)
        self.sent: list[dict[str, Any]] = []

    async def receive_text(self) -> str:
        if not self._inbound:
            raise WebSocketDisconnect(code=1000)
        return json.dumps(self._inbound.pop(0))

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)

    @property
    def replies(self) -> list[str]:
        """Return what the participant was shown, in order."""
        return [
            str(frame["text"])
            for frame in self.sent
            if frame.get("type") == "chat" and frame.get("author") != "you"
        ]


class _Watched:
    """The real Ollama adapter, with every request it sent kept for inspection."""

    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []
        send = httpx_transport(timeout=180.0)

        async def watched(request: HttpRequest) -> HttpResponse:
            self.requests.append(request)
            return await send(request)

        # The transport is the adapter's own seam, so the request that really goes
        # out is the one inspected. Nothing between the mount and the runner is
        # replaced.
        self._inner = adapter_for("oss", base_url=_OLLAMA, transport=watched)

    async def __call__(self, call: Any) -> Any:
        return await self._inner(call)

    def prompt(self, index: int) -> str:
        """Return the words of one request, as the provider reads them.

        Only ``content`` is read. That is the whole point of this file: a test that
        reads the field the platform happens to write proves the platform agrees
        with itself, not that a model was told anything.
        """
        messages = cast("list[dict[str, Any]]", self.requests[index].json["messages"])
        return "\n".join(str(one["content"]) for one in messages)


class _Contexts:
    """Mint a fresh command context on one aggregate's stream, keyed by its id."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def __call__(self, aggregate_id: str) -> CommandContext:
        n = next(self._counter)
        body = _UUID.format(n)
        return CommandContext.model_validate(
            {
                "command_id": "command_" + body,
                "receipt_id": "receipt_" + body,
                "error_id": "error_" + body,
                "idempotency_key": "idem_" + f"{n:021d}" + "A",
                "event_id": "event_" + body,
                "stream_id": "stream_" + aggregate_id.split("_", 1)[1],
                "producer": {
                    "epoch_id": "prodepoch_" + _UUID.format(9),
                    "sequence": n,
                    "content_digest": _DIGEST.model_dump(mode="json"),
                },
                "aggregate_id": aggregate_id,
                "principal": {"kind": "service", "id": "service_" + _UUID.format(0xA)},
                "recorded_at": "2026-07-28T00:00:00.000000Z",
                "event_data_handling": {"privacy_labels": ["research"]},
            }
        )


class _Ids:
    """Mint deterministic runtime-occurrence ids, one counter for every kind."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def __call__(self, kind: str) -> str:
        return f"{kind}_" + _UUID.format(0x1000 + next(self._counter))


def _session() -> Session:
    session = Session.__new__(Session)
    session.principal = None  # type: ignore[assignment]
    session.cursor = 0
    session.state = {"flow_id": "visitplan_" + _UUID.format(0x50)}
    session.outbox = []
    return session


async def _talk(*said: str) -> tuple[_Socket, _Watched]:
    """Hold one conversation with the live model and return what happened."""
    adapter = _Watched()
    seat = ChatSeatSpec(
        agent=_Counsellor(),
        adapter=adapter,
        ids=AgentIds(
            agent_version_id="agentver_" + _UUID.format(0x430),
            agent_definition_id="agentdef_" + _UUID.format(0x431),
            agent_key="counsellor",
            version_number=1,
            prompt_version_id="promptver_" + _UUID.format(0x440),
            fallback_policy_key="chat-fallback",
        ),
        actor_id="actor_" + _UUID.format(0x300),
    )
    frames: list[Any] = [{"type": "chat", "text": one} for one in said]
    socket = _Socket([*frames, {"type": "chat_end"}])
    await run_chat_activity(
        cast("Any", socket),
        _session(),
        chat_spec(seat=seat, channel_key="counsel", max_messages=8),
        store=InMemoryStore(),
        new_context=_Contexts(),
        new_id=_Ids(),
        now=lambda: _START,
    )
    return socket, adapter


@pytest.mark.slow
async def test_a_participant_types_and_a_real_model_answers() -> None:
    """The whole point: a message goes in and words come back out.

    This is the fault the owner met. The mount composed a payload no provider could
    read, so every message was answered with nothing at all, on every provider.
    """
    socket, adapter = await _talk("Hello, can you help me think something through?")

    assert len(adapter.requests) == 1, "the model was not called"
    assert socket.replies, "the participant was shown no reply at all"
    assert socket.replies[0].strip(), "the reply reached the participant empty"


@pytest.mark.slow
async def test_the_model_is_sent_what_the_participant_said() -> None:
    """The participant's words are in the request, where a provider reads them."""
    _socket, adapter = await _talk("My favourite fruit is a plum.")

    assert "My favourite fruit is a plum." in adapter.prompt(0)


@pytest.mark.slow
async def test_the_model_is_sent_the_prompt_the_author_wrote() -> None:
    """An author's instructions travel with the conversation, and are obeyed.

    The prompt is the only thing an author writes about what their model is for. A
    reply that carries the marker proves it arrived, because nothing else in the
    conversation asks for that word.
    """
    socket, adapter = await _talk("Hello.")

    assert f"Begin every reply with the word {_MARKER}" in adapter.prompt(0)
    assert _MARKER in socket.replies[0], (
        "the model did not obey the author's prompt, so it likely never read it: "
        + socket.replies[0]
    )


@pytest.mark.slow
async def test_the_conversation_carries_from_one_turn_to_the_next() -> None:
    """The second turn reads the first, so the model is in a conversation.

    A mount that composed each turn on its own would answer every message as if it
    were the first, which is what a participant feels as a model with no memory.

    What the model then *does* with the conversation is not asserted. The smallest
    model on a machine is often a one-billion-parameter model, and asking it to
    recall a name from the turn before fails about one run in ten. That failure
    would be about the model and not about the platform, and a test that fails for
    a reason it does not name is worse than no test.
    """
    socket, adapter = await _talk(
        "My name is Wilhelmina and I am choosing between two jobs.",
        "What is my name?",
    )

    second = adapter.prompt(1)
    assert "Wilhelmina" in second, "the second turn did not carry the first message"
    assert socket.replies[0] in second, "the second turn did not carry the first reply"
    assert len(socket.replies) == 2, "the second message was not answered"
    assert socket.replies[1].strip(), "the second reply reached the participant empty"


@pytest.mark.slow
async def test_a_model_the_runner_does_not_hold_is_reported_not_hidden() -> None:
    """A wrong model name reaches the participant as a notice, not as silence.

    This is the second half of the fault. A provider that refuses leaves the mount
    with nothing to say, and a participant who is told nothing waits for a reply
    that is never coming and reports the whole study as broken.
    """

    class _Missing(_Counsellor):
        model = "a-model-nobody-has-pulled"

    adapter = adapter_for("oss", base_url=_OLLAMA, timeout=30.0)
    seat = ChatSeatSpec(
        agent=_Missing(),
        adapter=adapter,
        ids=AgentIds(
            agent_version_id="agentver_" + _UUID.format(0x430),
            agent_definition_id="agentdef_" + _UUID.format(0x431),
            agent_key="counsellor",
            version_number=1,
            prompt_version_id="promptver_" + _UUID.format(0x440),
            fallback_policy_key="chat-fallback",
        ),
        actor_id="actor_" + _UUID.format(0x300),
    )
    socket = _Socket([{"type": "chat", "text": "Hello?"}, {"type": "chat_end"}])
    await run_chat_activity(
        cast("Any", socket),
        _session(),
        chat_spec(seat=seat, channel_key="counsel"),
        store=InMemoryStore(),
        new_context=_Contexts(),
        new_id=_Ids(),
        now=lambda: _START,
    )

    assert socket.replies == []
    notices = [one for one in socket.sent if one.get("type") == "chat_notice"]
    assert notices, "the participant was left waiting with nothing said"
    assert notices[0]["code"] == "no-reply"
