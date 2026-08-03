"""The two preference-chat examples run, end to end, with no network.

`examples/preference_chat/` shows the thing the platform exists for: a participant
talks to a model, sees two possible replies on each turn, says which one they would
rather have had, and the conversation carries on from the one they chose.

These tests drive the **example studies themselves** through the running
application over a real websocket, with a fake HTTP transport injected into the
**real** provider adapters. So the whole path is exercised -- the study, the mount,
the compiled speaker, the adapter's own request and reply mapping, the elicitation,
and the recorded preference -- and nothing reaches a network.

The last test is the one that matters most for the hosted example: **the API key
reaches the provider's request header and appears in no record anywhere.** A study
that leaked a credential into its own data would be worse than one that never ran.
"""

from __future__ import annotations

import inspect
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from examples.preference_chat import study as study_module
from examples.preference_chat.agent import AXES
from examples.preference_chat.anthropic import (
    SECRET_NAME,
    HostedCounsellor,
    MissingApiKey,
    hosted_study,
    read_api_key,
)
from examples.preference_chat.ollama import LocalCounsellor, local_study
from examples.preference_chat.study import preference_chat_study
from mug.agents.adapters import HttpRequest, HttpResponse, adapter_for
from mug.app import build_study_app
from mug.client import RealtimeCommand
from mug.content import Study
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.storage import InMemoryStore, Store

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_KEY = "sk-ant-test-0123456789"

# Two replies that are easy to tell apart, so a test can say which one the
# conversation carried on with.
_DRAFTS = [
    "That sounds like a trade-off between money and time. Which matters more?",
    "Write down the three things you would regret most, then rank them.",
]


class _Recorder:
    """A fake HTTP transport: it answers on a script and keeps what it was sent."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.sent: list[HttpRequest] = []
        self._replies = 0

    async def __call__(self, request: HttpRequest) -> HttpResponse:
        self.sent.append(request)
        text = _DRAFTS[self._replies % len(_DRAFTS)]
        self._replies += 1
        if self.provider == "anthropic":
            return HttpResponse(
                status=200,
                body={
                    "model": "claude-sonnet-5",
                    "content": [{"type": "text", "text": text}],
                    "usage": {"input_tokens": 11, "output_tokens": 7},
                    "stop_reason": "end_turn",
                },
            )
        return HttpResponse(
            status=200,
            body={
                "model": "llama3.2",
                "message": {"role": "assistant", "content": text},
                "prompt_eval_count": 11,
                "eval_count": 7,
            },
        )


def _wired(provider: str, **fields: Any) -> tuple[Study, _Recorder]:
    """Return the example's study with a fake transport in its adapter."""
    recorder = _Recorder(provider)
    agent = HostedCounsellor() if provider == "anthropic" else LocalCounsellor()
    study = preference_chat_study(
        agent,
        adapter=adapter_for(provider, transport=recorder),
        **fields,
    )
    return study, recorder


def _client(store: Store, study: Study) -> TestClient:
    return TestClient(
        build_study_app(
            study=study,
            store=store,
            gateway=Gateway(secret=b"a-shared-deployment-secret------"),
        )
    )


def _advance(answers: dict[str, Any], tag: str) -> dict[str, Any]:
    command = RealtimeCommand(
        command_id=f"command_019b6000-0000-7000-8000-0000000000{tag}",
        channel_key="flow.advance",
        intent_schema=SchemaRef(name="mug.example.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        idempotency_key="idem_" + tag.ljust(21, "0") + "A",
        submitted_at="2026-07-27T00:00:00.000000Z",
    )
    return {
        "type": "command",
        "command": command.model_dump(mode="json", exclude_none=True),
        "payload": {"answers": answers},
    }


def _to_the_conversation(socket: WebSocketTestSession) -> dict[str, Any]:
    """Consent, read the instructions, and stop when the conversation opens."""
    assert socket.receive_json()["type"] == "handshake_ack"
    assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"
    socket.send_json(_advance({"agree": "yes", "data-sharing": "yes"}, "01"))
    assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
    assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
    assert socket.receive_json()["delivery"]["activity_key"] == "instructions"
    socket.send_json(_advance({}, "02"))
    assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
    assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
    for _ in range(8):
        message = cast("dict[str, Any]", socket.receive_json())
        if message.get("type") == "delivery":
            return cast("dict[str, Any]", message["delivery"])
    raise AssertionError("the conversation never opened")


def _read_until(socket: WebSocketTestSession, kind: str) -> dict[str, Any]:
    """Read frames until one of a named kind arrives."""
    for _ in range(24):
        message = cast("dict[str, Any]", socket.receive_json())
        if message.get("type") == kind:
            return message
    raise AssertionError(f"no {kind} frame arrived")


def _states(store: Store, schema_name: str) -> list[dict[str, Any]]:
    """Return every recorded aggregate head of one schema name."""
    found: list[dict[str, Any]] = []
    for _aggregate_id, state in store.scan_aggregates():
        if not isinstance(state, dict):
            continue
        head = cast("dict[str, Any]", state)
        schema = head.get("schema")
        if isinstance(schema, dict) and cast("dict[str, Any]", schema).get(
            "name"
        ) == schema_name:
            found.append(head)
    return found


# -- what the author writes ---------------------------------------------------


def test_the_study_names_a_model_and_no_identifier_at_all() -> None:
    """The author writes a `Model`. Everything else is derived at the mount.

    This is the whole reason a chat activity can be written in one line now. An
    author who had to supply an agent version id, a definition id, a prompt version
    id, and an actor id would be writing platform plumbing into their study.
    """
    written_talk = local_study().talks["counsel"]
    assert len(written_talk.speakers) == 1

    written = inspect.getsource(study_module)
    assert "AgentIds" not in written
    assert "actor_id" not in written


def test_both_examples_are_the_same_study_on_two_backends() -> None:
    """The comparison the pair exists to make: only the backend differs."""
    local = local_study().talks["counsel"]
    hosted = hosted_study().talks["counsel"]

    assert local.key == hosted.key
    assert local.greeting == hosted.greeting
    assert local.max_messages == hosted.max_messages
    # The judgement asked of the participant is identical.
    assert local.elicit is not None
    assert hosted.elicit is not None
    # And the models are not.
    assert local.speakers[0].agent.provider != hosted.speakers[0].agent.provider


def test_the_axes_ask_for_a_comparison_and_a_rating_of_each() -> None:
    """A pair judgement and a per-reply rating are different data; both are asked."""
    by_key = {axis.key: axis for axis in AXES}
    assert by_key["helpful"].scope == "pair", "a comparison between the two replies"
    assert by_key["tone"].scope == "each", "a rating of each reply on its own"


# -- the running conversation --------------------------------------------------


@pytest.mark.parametrize("provider", ["oss", "anthropic"])
def test_a_participant_sees_two_replies_and_the_chosen_one_carries_on(
    provider: str,
) -> None:
    """The capability, end to end, on both backends."""
    store = InMemoryStore()
    study, recorder = _wired(provider)
    client = _client(store, study)
    with client, client.websocket_connect("/ws") as socket:
        delivery = _to_the_conversation(socket)
        # The activity says what it is. It used to arrive as a game the client had
        # to be told was not one (``kind: "game", mode: "chat"``).
        assert delivery["kind"] == "chat"

        socket.send_json({"type": "chat", "text": "Should I take the new job?"})
        shown = _read_until(socket, "chat_candidates")
        options = cast("list[dict[str, Any]]", shown["options"])

        # Two replies, blinded: what the participant sees is a handle, never the
        # model's own message id, and never which one was written first.
        assert len(options) == 2
        assert {one["text"] for one in options} == set(_DRAFTS)
        assert all(one["handle"] for one in options)

        chosen = options[1]
        socket.send_json(
            {"type": "chat_candidate_choice", "choice": chosen["handle"]}
        )
        socket.send_json({"type": "chat_end"})

    # The provider was really reached, twice, through its own adapter.
    assert len(recorder.sent) == 2
    assert all(request.url for request in recorder.sent)

    # One candidate set was recorded, and it names the reply the participant kept.
    sets = _states(store, "mug.api-08.candidate-reply-set")
    assert len(sets) == 1
    assert len(sets[0]["candidate_message_ids"]) == 2
    assert sets[0]["selected_message_id"] in sets[0]["candidate_message_ids"]

    # The reply nobody chose is kept as well: two candidates, one conversation.
    assert len(_states(store, "mug.api-18.preference-response")) == 1


@pytest.mark.parametrize(
    ("provider", "fragment"),
    [("oss", "/api/chat"), ("anthropic", "/v1/messages")],
)
def test_each_backend_is_reached_at_its_own_endpoint(
    provider: str, fragment: str
) -> None:
    """The adapter follows from the agent's declared provider, and nothing else."""
    store = InMemoryStore()
    study, recorder = _wired(provider)
    client = _client(store, study)
    with client, client.websocket_connect("/ws") as socket:
        _to_the_conversation(socket)
        socket.send_json({"type": "chat", "text": "Should I move house?"})
        _read_until(socket, "chat_candidates")
        socket.send_json({"type": "chat_end"})

    assert recorder.sent
    assert all(fragment in request.url for request in recorder.sent)


# -- the credential ------------------------------------------------------------


def _the_test_key(_name: str) -> str:
    """Resolve the credential the way the example does, with a known value."""
    return _KEY


def test_the_api_key_reaches_the_request_header_and_no_record() -> None:
    """The sharpest test here: the key is used and never written down.

    It is read at call time by a function, so it is not a field on the study, not
    on the agent, and not in the compiled study version. The adapter puts it in one
    request header and never returns it. What the ledger records about a call is
    the request digest and the **name** of the secret, never its value.
    """
    store = InMemoryStore()
    study, recorder = _wired("anthropic", resolve_secret=_the_test_key)
    client = _client(store, study)
    with client, client.websocket_connect("/ws") as socket:
        _to_the_conversation(socket)
        socket.send_json({"type": "chat", "text": "Should I take the new job?"})
        shown = _read_until(socket, "chat_candidates")
        options = cast("list[dict[str, Any]]", shown["options"])
        socket.send_json(
            {"type": "chat_candidate_choice", "choice": options[0]["handle"]}
        )
        socket.send_json({"type": "chat_end"})

    # It was used: every request carried it in the header Anthropic reads.
    assert recorder.sent
    assert all(request.headers.get("x-api-key") == _KEY for request in recorder.sent)

    # And it is nowhere in what the deployment wrote down.
    written = repr(
        [state for _aggregate_id, state in store.scan_aggregates()]
    )
    assert _KEY not in written
    assert "sk-ant" not in written


def test_the_key_is_read_from_the_environment_and_missing_is_said_plainly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A researcher without a key is told what to set, not shown a stack trace."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingApiKey, match="ANTHROPIC_API_KEY"):
        read_api_key(SECRET_NAME)

    monkeypatch.setenv("ANTHROPIC_API_KEY", _KEY)
    assert read_api_key(SECRET_NAME) == _KEY

    # A name this study does not hold is refused rather than answered with the one
    # credential it does have.
    with pytest.raises(MissingApiKey, match="no credential"):
        read_api_key("some-other-secret")


def test_the_local_example_asks_for_no_credential_at_all() -> None:
    """The reason to reach for the local runner first: there is nothing to leak."""
    said = local_study().talks["counsel"]
    assert said.speakers[0].resolve_secret is None
