"""A preference elicited inside the conversation, and the branch it did not take.

`CandidateReplySet` was a frozen record with a model, fixtures, and no producer.
A study could compare answers recorded before anyone arrived (W2, W3), but it
could not ask the question the field actually asks: *of these two replies to what
you just said, which would you rather have had?* -- and then go on talking.

These tests hold what the record has to mean:

- the participant picks a reply and **the thread continues from the one they
  picked**, with the prompt, every candidate, the selected one, and the response
  that chose it all named in one record;
- the reply they did not pick reaches **nobody**, then or later, and is kept
  anyway -- a committed message and a durable generation with its own private
  provenance, which is the only place an untaken branch exists;
- an answer names a **candidate**, never a side of the screen, so a shuffled
  presentation cannot be read back wrong;
- a judgement is more than one bit: a **tie** is recordable without inventing a
  choice, and each authored **axis** is recorded against the candidate it is about;
- a retry records **one** choice (NS-10), and one candidate set costs **one**
  model activation, whatever ``n`` is.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from typing import Any, cast

from fastapi import WebSocketDisconnect

from mug.agents import AgentIds
from mug.agents.generation import recorded_generation
from mug.authoring import (
    Axis,
    Chat,
    Elicit,
    Fallback,
    History,
    LLMAgent,
    Provider,
    Thoughts,
)
from mug.conversation import TurnPolicy
from mug.gateway import Gateway
from mug.kernel import Digest, PrincipalRef
from mug.participant_chat import (
    ChatDurability,
    ChatSeatSpec,
    ChatSpec,
    run_chat_activity,
)
from mug.participant_elicit import assignment_id_for
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.realtime import Session
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 27, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_PARTNER_ACTOR = "actor_" + _UUID.format(0x300)
_RIVAL_ACTOR = "actor_" + _UUID.format(0x301)
_FLOW = "visitplan_" + _UUID.format(0x50)
_VISIT = "visit_" + _UUID.format(0x60)
_SECRET = b"a-shared-deployment-secret------"


class _Partner(LLMAgent):
    """An author's chat agent: a keyless local runner."""

    provider = Provider.OSS
    model = "fake-local"
    decides_every = 1
    on_timeout = Fallback.REPEAT_LAST

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Chat,
        thoughts: Thoughts,
    ) -> str:
        return ""


class _Sampler:
    """A fake provider whose every call answers differently, as sampling does."""

    def __init__(self, tag: str = "draft") -> None:
        self._tag = tag
        self._counter = itertools.count(1)
        self.calls = 0

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.calls += 1
        payload = cast("dict[str, Any]", call.payload)
        last = cast("list[dict[str, str]]", payload["messages"])[-1]["text"]
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": f"{self._tag} {next(self._counter)} to {last}"},
        )


class _Parrot:
    """A fake provider that answers the same way every time, as temperature 0 does."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.calls += 1
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
            output={"text": "the one answer"},
        )


class _Socket:
    """A socket that replays scripted frames, and can answer what it is shown."""

    def queue(self, frame: dict[str, Any]) -> None:
        """Put one more frame at the front of what this client will send next."""
        self._inbound.insert(0, frame)


    def __init__(self, frames: list[Any]) -> None:
        self._inbound = list(frames)
        self.sent: list[dict[str, Any]] = []
        # A reply the client writes once it has seen the candidates. The test sets
        # it as a function of the frame, because the handles are not knowable in
        # advance -- which is the point of them.
        self.answer: Any = None

    async def receive_text(self) -> str:
        if not self._inbound:
            raise WebSocketDisconnect(code=1000)
        frame = self._inbound.pop(0)
        return frame if isinstance(frame, str) else json.dumps(frame)

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)
        if payload.get("type") == "chat_candidates" and self.answer is not None:
            written = self.answer(payload)
            if written is not None:
                self._inbound.insert(0, written)

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        return [frame for frame in self.sent if frame.get("type") == kind]

    def one(self, kind: str) -> dict[str, Any]:
        found = self.of_type(kind)
        assert len(found) == 1, f"expected one {kind}, got {len(found)}"
        return found[0]


class _Contexts:
    """Mint a fresh command context on one aggregate's stream, keyed by its id."""

    def __init__(self, start: int = 1) -> None:
        self._counter = itertools.count(start)

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
                "recorded_at": "2026-07-27T00:00:00.000000Z",
                "event_data_handling": {"privacy_labels": ["research"]},
            }
        )


class _Ids:
    """Mint deterministic runtime-occurrence ids, one counter for all kinds."""

    def __init__(self, start: int = 0x1000) -> None:
        self._counter = itertools.count(start)

    def __call__(self, kind: str) -> str:
        return f"{kind}_" + _UUID.format(next(self._counter))


def _seat(agent_actor: str, adapter: Any, key: str, offset: int) -> ChatSeatSpec:
    return ChatSeatSpec(
        agent=_Partner(),
        adapter=adapter,
        ids=AgentIds(
            agent_version_id="agentver_" + _UUID.format(0x430 + offset),
            agent_definition_id="agentdef_" + _UUID.format(0x460 + offset),
            agent_key=key,
            version_number=1,
            prompt_version_id="promptver_" + _UUID.format(0x490 + offset),
            fallback_policy_key="chat-fallback",
        ),
        actor_id=agent_actor,
    )


def _spec(elicit: Elicit | None, adapter: Any, *, second: Any = None) -> ChatSpec:
    seats = [_seat(_PARTNER_ACTOR, adapter, "partner", 0)]
    if second is not None:
        seats.append(_seat(_RIVAL_ACTOR, second, "rival", 1))
    return ChatSpec(
        seats=tuple(seats),
        max_messages=4,
        max_activations_per_turn=len(seats),
        elicit_preference=elicit,
    )


def _session() -> Session:
    session = Session.__new__(Session)
    session.principal = PrincipalRef(
        kind="participant", id="participant_" + _UUID.format(0xB0)
    )
    session.cursor = 0
    session.state = {"flow_id": _FLOW, "visit_id": _VISIT}
    session.outbox = []
    return session


def _durable(store: InMemoryStore, gateway: Gateway) -> ChatDurability:
    return ChatDurability(
        derive=gateway.derived_id,
        artifacts=store,
        new_artifact_id=lambda seed: gateway.derived_id("artifact", seed),
        new_upload_id=lambda: gateway.new_id("upload"),
        occurrence_key="talk",
    )


async def _run(
    frames: list[Any],
    store: InMemoryStore,
    gateway: Gateway,
    spec: ChatSpec,
    *,
    ids: int = 0x1000,
    answer: Any = None,
) -> _Socket:
    """Run one chat activity over a scripted socket that answers what it is shown."""
    socket = _Socket(frames)
    socket.answer = answer
    await run_chat_activity(
        cast("Any", socket),
        _session(),
        spec,
        store=store,
        new_context=_Contexts(),
        new_id=_Ids(ids),
        now=lambda: _START,
        durable=_durable(store, gateway),
        gateway=gateway,
    )
    return socket


def _pick(index: int = 0, **extra: Any) -> Any:
    """Answer an elicitation by choosing the option at one shown position."""

    def answer(frame: dict[str, Any]) -> dict[str, Any]:
        options = cast("list[dict[str, str]]", frame["options"])
        return {
            "type": "chat_candidate_choice",
            "choice": options[index]["handle"],
            **extra,
        }

    return answer


def _pick_first_written() -> Any:
    """Answer by choosing the reply the model wrote first.

    The sampler numbers its outputs and they are posted in that order, so this
    always keeps the candidate with the *lower* channel sequence -- which puts the
    reply nobody chose above it, where an unguarded flush would deliver it.
    """

    def answer(frame: dict[str, Any]) -> dict[str, Any]:
        options = cast("list[dict[str, str]]", frame["options"])
        first = next(o for o in options if o["text"].startswith("draft 1"))
        return {"type": "chat_candidate_choice", "choice": first["handle"]}

    return answer


def _skip(_frame: dict[str, Any]) -> dict[str, Any]:
    """Answer an elicitation by passing on it."""
    return {"type": "chat_candidate_skip"}


def _texts(frame: dict[str, Any]) -> list[str]:
    return [option["text"] for option in cast("list[Any]", frame["options"])]


def _states(store: InMemoryStore, schema: str) -> list[dict[str, Any]]:
    """Return every recorded aggregate head of one schema, in scan order."""
    found: list[dict[str, Any]] = []
    for _aggregate_id, state in store.scan_aggregates():
        if isinstance(state, dict):
            body = cast("dict[str, Any]", state)
            if body.get("schema", {}).get("name") == schema:
                found.append(body)
    return found


_CANDIDATE_SET = "mug.api-08.candidate-reply-set"
_RESPONSE = "mug.api-18.preference-response"
_QUALITY = "mug.api-18.quality-evidence"
_MESSAGE = "mug.api-08.chat-message"


# -- the thread continues from the reply the participant chose --------------------


async def test_a_participant_picks_a_reply_and_the_conversation_goes_on_from_it() -> (
    None
):
    """The proof: one record names the prompt, both replies, and the one kept."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    socket = await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2), _Sampler()),
        answer=_pick(1),
    )

    shown = socket.one("chat_candidates")
    assert len(shown["options"]) == 2
    kept = _texts(shown)[1]

    # The thread went on with the reply they picked, and only that one.
    assert [frame["text"] for frame in socket.of_type("chat")] == [kept]

    recorded = _states(store, _CANDIDATE_SET)
    assert len(recorded) == 1
    written = recorded[0]
    response = _states(store, _RESPONSE)[0]
    assert len(written["candidate_message_ids"]) == 2
    assert written["selected_message_id"] in written["candidate_message_ids"]
    assert written["preference_response_id"] == response["response_id"]
    assert response["choice"] == written["selected_message_id"]
    # The prompt the candidates answered is the participant's own message.
    prompts = [
        message
        for message in _states(store, _MESSAGE)
        if message["message_id"] == written["prompt_message_id"]
    ]
    assert prompts and prompts[0]["author_actor_id"] not in (
        _PARTNER_ACTOR,
        _RIVAL_ACTOR,
    )


async def test_the_reply_that_was_not_chosen_reaches_nobody() -> None:
    """The branch not taken is on no screen, and no delivery receipt says it was."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    socket = await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2), _Sampler()),
        answer=_pick(0),
    )

    shown = socket.one("chat_candidates")
    kept, dropped = _texts(shown)
    delivered = [frame["text"] for frame in socket.of_type("chat")]
    assert delivered == [kept]
    assert dropped not in delivered

    written = _states(store, _CANDIDATE_SET)[0]
    unchosen = [
        message_id
        for message_id in written["candidate_message_ids"]
        if message_id != written["selected_message_id"]
    ]
    receipts = _states(store, "mug.api-08.delivery-receipt")
    assert unchosen
    assert all(receipt["message_id"] not in unchosen for receipt in receipts)


async def test_the_unchosen_reply_is_kept_with_everything_known_about_it() -> None:
    """It is a committed message and a durable generation, not a discarded string."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2), _Sampler()),
        answer=_pick(0),
    )

    written = _states(store, _CANDIDATE_SET)[0]
    for message_id in written["candidate_message_ids"]:
        assert isinstance(store.load_aggregate(message_id), dict)
        generation = recorded_generation(
            store, gateway.derived_id("generation", f"chat-reply:{message_id}")
        )
        assert generation is not None
        # The provider is in the private provenance and nowhere a browser reaches.
        assert generation.provenance.artifact_id != generation.visible.artifact_id


async def test_a_reply_that_was_not_chosen_is_not_delivered_on_a_later_refresh() -> (
    None
):
    """A room flushes what a member has not been sent; it must not send this.

    The participant keeps the reply the model wrote **first**, so the one they did
    not keep sits *above* it in the channel. A delivery watermark is a high-water
    mark, so that is the arrangement in which a leak would happen -- and it does not,
    because the room never took the unchosen reply into its order at all. A message
    the room did not adopt is a message nothing can deliver.
    """
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    first = await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2), _Sampler()),
        answer=_pick_first_written(),
    )
    shown = _texts(first.one("chat_candidates"))
    kept = next(text for text in shown if text.startswith("draft 1"))
    dropped = next(text for text in shown if text != kept)
    sequences = {
        message["message_id"]: message["sequence"]
        for message in _states(store, _MESSAGE)
    }
    written = _states(store, _CANDIDATE_SET)[0]
    unchosen = next(
        message_id
        for message_id in written["candidate_message_ids"]
        if message_id != written["selected_message_id"]
    )
    assert sequences[unchosen] > sequences[written["selected_message_id"]]

    second = await _run(
        [], store, gateway, _spec(Elicit.replies(n=2), _Sampler()), ids=0x4000
    )
    restored = [frame["text"] for frame in second.of_type("chat")]
    assert dropped not in restored
    assert restored == ["hello", kept]


# -- what is recorded says more than which one won --------------------------------


async def test_a_tie_is_recorded_and_the_thread_still_goes_on() -> None:
    """Neither was preferred, and one reply still had to continue the conversation."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    socket = await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2, ties=True), _Sampler()),
        answer=_pick(0, verdict="tie"),
    )

    response = _states(store, _RESPONSE)[0]
    assert response["verdict"] == "tie"
    assert response["choice"] in response["presented_order"]
    assert [frame["text"] for frame in socket.of_type("chat")] == [
        _texts(socket.one("chat_candidates"))[0]
    ]


async def test_a_tie_is_not_read_from_a_study_that_did_not_offer_one() -> None:
    """A client that sends a verdict the protocol never declared is not believed."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2), _Sampler()),
        answer=_pick(0, verdict="tie"),
    )
    assert "verdict" not in _states(store, _RESPONSE)[0]


async def test_each_axis_is_recorded_against_the_candidate_it_is_about() -> None:
    """A shuffled presentation must never be able to invert a rating."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    axes = [
        Axis("helpful", "Which reply is more helpful?"),
        Axis("wordy", "How wordy is each reply?", each=True, points=5),
    ]

    def answer(frame: dict[str, Any]) -> dict[str, Any]:
        options = cast("list[dict[str, str]]", frame["options"])
        return {
            "type": "chat_candidate_choice",
            "choice": options[0]["handle"],
            "ratings": [
                {"axis": "helpful", "option": options[1]["handle"], "value": 2},
                {"axis": "wordy", "option": options[0]["handle"], "value": 1},
                {"axis": "wordy", "option": options[1]["handle"], "value": 4},
            ],
        }

    socket = await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2, on=axes), _Sampler()),
        answer=answer,
    )

    shown = socket.one("chat_candidates")
    assert [axis["key"] for axis in shown["axes"]] == ["helpful", "wordy"]
    assert [axis["scope"] for axis in shown["axes"]] == ["pair", "each"]

    response = _states(store, _RESPONSE)[0]
    ratings = cast("list[dict[str, Any]]", response["ratings"])
    assert len(ratings) == 3
    # Every rating names a candidate that was shown, by its own key.
    assert all(
        rating["candidate_key"] in response["presented_order"] for rating in ratings
    )
    helpful = next(r for r in ratings if r["dimension_key"] == "helpful")
    assert helpful["candidate_key"] != response["choice"]
    assert helpful["value"] == 2


async def test_an_axis_answered_with_no_candidate_is_the_midpoint() -> None:
    """The middle of a slider favours neither, and that is a value, not a gap."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)

    def answer(frame: dict[str, Any]) -> dict[str, Any]:
        options = cast("list[dict[str, str]]", frame["options"])
        return {
            "type": "chat_candidate_choice",
            "choice": options[0]["handle"],
            "ratings": [{"axis": "helpful", "value": 0}],
        }

    await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(
            Elicit.replies(n=2, on=[Axis("helpful", "More helpful?")]), _Sampler()
        ),
        answer=answer,
    )
    rating = cast("list[dict[str, Any]]", _states(store, _RESPONSE)[0]["ratings"])[0]
    assert rating["value"] == 0
    assert "candidate_key" not in rating


async def test_a_rating_for_a_reply_nobody_was_shown_is_not_recorded() -> None:
    """An answer that names something outside the set is dropped, not stored."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)

    def answer(frame: dict[str, Any]) -> dict[str, Any]:
        options = cast("list[dict[str, str]]", frame["options"])
        return {
            "type": "chat_candidate_choice",
            "choice": options[0]["handle"],
            "ratings": [
                {"axis": "helpful", "option": "handle_not-a-real-one", "value": 1},
                {"axis": "helpful", "option": options[0]["handle"], "value": 2},
            ],
        }

    await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(
            Elicit.replies(n=2, on=[Axis("helpful", "More helpful?")]), _Sampler()
        ),
        answer=answer,
    )
    ratings = cast("list[dict[str, Any]]", _states(store, _RESPONSE)[0]["ratings"])
    assert len(ratings) == 1
    assert ratings[0]["value"] == 2


async def test_how_long_the_judgement_took_is_recorded() -> None:
    """A judgement returned in no time is one an analysis must be able to find."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2), _Sampler()),
        answer=_pick(0, response_time_ms=4200),
    )
    quality = _states(store, _QUALITY)[0]
    assert quality["response_time_ms"] == 4200


# -- blinding, sampling, and the cost of a turn -----------------------------------


async def test_what_reaches_the_browser_carries_no_reply_identity() -> None:
    """Blinding is structural: the frame has handles and text, and nothing else."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    socket = await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2), _Sampler(), second=_Sampler("other")),
        answer=_pick(0),
    )
    shown = json.dumps(socket.one("chat_candidates"))
    assert _PARTNER_ACTOR not in shown
    assert _RIVAL_ACTOR not in shown
    for message_id in _states(store, _CANDIDATE_SET)[0]["candidate_message_ids"]:
        assert message_id not in shown


async def test_a_retry_of_one_answer_records_one_choice() -> None:
    """NS-10: the same key over the same turn replays; it does not judge twice."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)

    def answer(frame: dict[str, Any]) -> dict[str, Any]:
        options = cast("list[dict[str, str]]", frame["options"])
        return {
            "type": "chat_candidate_choice",
            "choice": options[0]["handle"],
            "idempotency_key": "idem_000000000000000999999A",
        }

    socket = _Socket([{"type": "chat", "text": "hello"}])

    def twice(frame: dict[str, Any]) -> dict[str, Any]:
        # The client sends its answer, then sends it again -- a double click, or a
        # reconnect that replays what it had not seen acknowledged.
        written = answer(frame)
        socket.queue(written)
        return written

    socket.answer = twice
    await run_chat_activity(
        cast("Any", socket),
        _session(),
        _spec(Elicit.replies(n=2), _Sampler()),
        store=store,
        new_context=_Contexts(),
        new_id=_Ids(),
        now=lambda: _START,
        durable=_durable(store, gateway),
        gateway=gateway,
    )
    assert len(_states(store, _RESPONSE)) == 1
    assert len(_states(store, _CANDIDATE_SET)) == 1


async def test_one_candidate_set_costs_one_model_activation() -> None:
    """D08-5: asking for more candidates must not widen a turn's model budget."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    adapter = _Sampler()
    spec = ChatSpec(
        seat=_seat(_PARTNER_ACTOR, adapter, "partner", 0),
        max_messages=4,
        policy=TurnPolicy(
            channel_key="chat", activation="free", max_model_activations_per_turn=1
        ),
        elicit_preference=Elicit.replies(n=3),
    )
    socket = await _run(
        [{"type": "chat", "text": "hello"}], store, gateway, spec, answer=_pick(0)
    )
    assert len(socket.one("chat_candidates")["options"]) == 3
    # Three replies and three model calls, under a policy that admits one
    # activation a turn. That the set spends exactly one of them is the claim
    # ``test_a_candidate_set_spends_one_activation_however_many_it_holds`` makes,
    # where the budget lives.
    assert adapter.calls == 3


async def test_two_replies_that_say_the_same_thing_are_not_a_comparison() -> None:
    """A model at temperature zero writes one answer twice; asking is a coin toss."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    socket = await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2), _Parrot()),
        answer=_pick(0),
    )
    assert socket.of_type("chat_candidates") == []
    assert [frame["text"] for frame in socket.of_type("chat")] == ["the one answer"]
    assert _states(store, _RESPONSE) == []


async def test_a_participant_who_passes_records_no_preference() -> None:
    """No judgement was made, so none is invented; the thread still goes on."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    socket = await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2), _Sampler()),
        answer=_skip,
    )
    assert _states(store, _RESPONSE) == []
    assert _states(store, _CANDIDATE_SET) == []
    assert [frame["text"] for frame in socket.of_type("chat")] == [
        _texts(socket.one("chat_candidates"))[0]
    ]


async def test_which_turns_are_elicited_is_derived_and_not_drawn() -> None:
    """A sampled study elicits the same turns however often the run is replayed."""
    gateway = Gateway(secret=_SECRET)
    spec = Elicit.replies(n=2, sample=0.5)
    prompts = ["message_" + _UUID.format(n) for n in range(40)]

    from mug.participant_elicit import elicits

    once = [elicits(gateway, spec, prompt) for prompt in prompts]
    again = [elicits(gateway, spec, prompt) for prompt in prompts]
    assert once == again
    # It samples: some turns are elicited and some are not.
    assert 0 < sum(once) < len(prompts)
    # A study that asks every turn asks the sampler nothing.
    assert all(elicits(gateway, Elicit.replies(n=2), prompt) for prompt in prompts)


async def test_two_model_seats_can_answer_the_same_turn_against_each_other() -> None:
    """Elicit.between is the arena setting: one reply from each declared seat."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    partner, rival = _Sampler("partner"), _Sampler("rival")
    socket = await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(
            Elicit.between(_PARTNER_ACTOR, _RIVAL_ACTOR), partner, second=rival
        ),
        answer=_pick(0),
    )
    shown = _texts(socket.one("chat_candidates"))
    assert sorted(text.split()[0] for text in shown) == ["partner", "rival"]
    assert partner.calls == 1
    assert rival.calls == 1


async def test_a_turn_is_answered_plainly_when_the_study_elicits_nothing() -> None:
    """A conversation with no elicitation behaves exactly as it did before W19."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    socket = await _run(
        [{"type": "chat", "text": "hello"}], store, gateway, _spec(None, _Sampler())
    )
    assert socket.of_type("chat_candidates") == []
    assert len(socket.of_type("chat")) == 1
    assert _states(store, _CANDIDATE_SET) == []


async def test_one_turn_has_one_assignment_however_often_it_is_reached() -> None:
    """The assignment is derived from the prompt, so it is the same one every time."""
    gateway = Gateway(secret=_SECRET)
    prompt = "message_" + _UUID.format(0x77)
    first = assignment_id_for(gateway, _FLOW, "chat", prompt)
    assert first == assignment_id_for(gateway, _FLOW, "chat", prompt)
    assert first != assignment_id_for(gateway, _FLOW, "coach", prompt)
    assert first != assignment_id_for(
        gateway, _FLOW, "chat", "message_" + _UUID.format(0x78)
    )


# -- the judgement leaves the platform in the shape the field trains on -----------


async def test_a_recorded_judgement_exports_as_a_row_a_reward_model_reads() -> None:
    """The proof that it left: prompt, chosen, rejected, and what nobody else keeps."""
    from mug.export.preferences import collect_preference_rows

    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)

    def answer(frame: dict[str, Any]) -> dict[str, Any]:
        options = cast("list[dict[str, str]]", frame["options"])
        return {
            "type": "chat_candidate_choice",
            "choice": options[0]["handle"],
            "response_time_ms": 3100,
            "ratings": [
                {"axis": "helpful", "option": options[0]["handle"], "value": 2}
            ],
        }

    socket = await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(
            Elicit.replies(
                n=2, ties=True, on=[Axis("helpful", "More helpful?")]
            ),
            _Sampler(),
        ),
        answer=answer,
    )
    kept, dropped = _texts(socket.one("chat_candidates"))

    rows = await collect_preference_rows(store, store)
    assert len(rows) == 1
    row = rows[0]
    # The three fields every preference corpus is read by, with the real words.
    assert row["prompt"] == "hello"
    assert row["chosen"] == kept
    assert row["rejected"] == dropped
    assert row["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": kept},
    ]
    # And the things a published corpus cannot say.
    assert row["verdict"] == "choice"
    assert row["tie_offered"] is True
    assert row["shown_first"] == "chosen"
    assert row["blinded"] is True
    assert row["response_time_ms"] == 3100
    assert row["ratings"] == [
        {"dimension": "helpful", "favours": "chosen", "value": 2}
    ]


async def test_a_comparison_of_three_replies_exports_two_pairs() -> None:
    """A corpus is pairs, so one set of three candidates is two rows, not one."""
    from mug.export.preferences import collect_preference_rows

    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=3), _Sampler()),
        answer=_pick(0),
    )
    rows = await collect_preference_rows(store, store)
    assert len(rows) == 2
    assert len({row["rejected"] for row in rows}) == 2
    assert len({row["chosen"] for row in rows}) == 1


async def test_the_protocol_a_study_asked_under_is_recorded() -> None:
    """An absent tie must be readable as "none offered", not only "none chosen"."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(
            Elicit.replies(n=2, ties=True, on=[Axis("helpful", "More helpful?")]),
            _Sampler(),
        ),
        answer=_pick(0),
    )
    declared = _states(store, "mug.api-18.preference-protocol")
    assert len(declared) == 1
    task = cast("dict[str, Any]", declared[0]["task"])
    assert task["allow_tie"] is True
    assert [dim["key"] for dim in cast("list[Any]", task["dimensions"])] == ["helpful"]
    assert declared[0]["blinded"] is True
    assert declared[0]["randomize_order"] is True


async def test_an_exported_row_says_which_reply_was_on_top() -> None:
    """Position bias is what the randomizer exists for, and nobody records it.

    The participant here chose the reply they were shown *second*, so a row that
    always claimed the chosen one was first would be saying the opposite of what
    happened -- and an analysis looking for order effects would find none.
    """
    from mug.export.preferences import collect_preference_rows

    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    socket = await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2), _Sampler()),
        answer=_pick(1),
    )
    shown = _texts(socket.one("chat_candidates"))

    rows = await collect_preference_rows(store, store)
    assert len(rows) == 1
    assert rows[0]["chosen"] == shown[1]
    assert rows[0]["shown_first"] == "rejected"


async def test_the_pairs_travel_with_the_rest_of_the_export() -> None:
    """`mug export` carries the trainable rows out, not only the canonical records."""
    import itertools

    from mug.export import export_study_dataset
    from mug.export.preferences import PREFERENCE_PAIRS
    from mug.export.types import GitProvenanceRef
    from mug.kernel.refs import StudyVersionRef

    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    socket = await _run(
        [{"type": "chat", "text": "hello"}],
        store,
        gateway,
        _spec(Elicit.replies(n=2), _Sampler()),
        answer=_pick(0),
    )
    kept = _texts(socket.one("chat_candidates"))[0]

    artifacts, uploads = itertools.count(1), itertools.count(1)
    export = await export_study_dataset(
        store=store,
        artifacts=store,
        study_version=StudyVersionRef(
            study_id="study_" + _UUID.format(0x1),
            study_version_id="studyver_" + _UUID.format(0x10),
            version_number=1,
            manifest_digest=_DIGEST,
        ),
        git_provenance=GitProvenanceRef(commit="0" * 40, branch="main", dirty=False),
        new_artifact_id=lambda: "artifact_" + _UUID.format(0x8000 + next(artifacts)),
        new_upload_id=lambda: "upload_" + _UUID.format(0x9000 + next(uploads)),
        now=lambda: "2026-07-27T00:00:00.000000Z",
    )
    pairs = next(v for v in export.values if v.dataset_kind == PREFERENCE_PAIRS)
    assert pairs.row_count == 1
    written = json.loads(
        (await store.read_artifact(pairs.artifact.artifact_id)).decode("utf-8")
    )
    assert written["prompt"] == "hello"
    assert written["chosen"] == kept


async def test_the_room_never_takes_an_unchosen_reply_into_its_order() -> None:
    """The one rule the whole guarantee rests on, checked where it is enforced.

    An unchosen candidate is committed to the channel and handed to nobody. It is
    in no room's order, so no delivery, no flush, and no reconnection can reach it
    -- there is one enforcement point rather than two to keep in step.
    """
    from mug.conversation.room import ChatRoom, RoomChannel, RoomMember

    store = InMemoryStore()
    room = ChatRoom(
        store=store,
        interaction_id="interaction_" + _UUID.format(0x1),
        channels=[RoomChannel(key="chat")],
        now=lambda: _START,
    )
    room.add_member(
        RoomMember(actor_id="actor_" + _UUID.format(0x2), channels=("chat",))
    )
    room.add_member(
        RoomMember(
            actor_id="actor_" + _UUID.format(0x3), channels=("chat",), kind="model"
        )
    )
    seen: list[str] = []

    async def sink(message: Any, text: str) -> None:
        seen.append(text)

    room.attach("actor_" + _UUID.format(0x2), sink)
    posted = await room.post(
        actor_id="actor_" + _UUID.format(0x3),
        channel_key="chat",
        text="adopted",
        message_id="message_" + _UUID.format(0x4),
        new_context=_Contexts(),
    )
    assert posted is not None
    # A message committed to the channel and never adopted: the shape a candidate
    # reply the participant did not choose is left in.
    _, unadopted = await room.channel("chat").post(
        context=_Contexts(500)("message_" + _UUID.format(0x5)),
        message_id="message_" + _UUID.format(0x5),
        author_actor_id="actor_" + _UUID.format(0x3),
        content_digest=_DIGEST,
        visibility="public",
        idempotency_key="idem_" + f"{7:021d}" + "A",
    )

    await room.flush(
        "actor_" + _UUID.format(0x2), new_context=_Contexts(600), new_id=_Ids(0x7000)
    )
    assert seen == ["adopted"]
    assert all(
        held.message_id != unadopted.message_id
        for held in room.history("chat")
    )
