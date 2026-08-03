"""An annotator compares two model generations, with every provider unreachable.

``OutputTape`` was a Protocol with one in-memory implementation and produced no
artifact reference, so a model generation could not be a preference candidate at
all. These tests drive the whole application -- the real generation job, the real
transport, the real annotation runtime, the real export -- over a study that
records two generations for one versioned input and then asks a participant which
one is better.

They check what NS-02 names: the three forms of a generation are distinct
references, the provider and the model are absent from everything the participant
is sent and present in the private provenance, and the annotation succeeds with
every provider offline.
"""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi.testclient import TestClient

from mug.agents.generation import (
    GenerationSet,
    ModelUnderTest,
    generation_id_for,
    input_digest_of,
    recorded_generation,
)
from mug.app import build_study_app
from mug.authoring import (
    Comparison,
    Fallback,
    History,
    LLMAgent,
    Provider,
    Thoughts,
    Transcript,
)
from mug.content import Page, Study
from mug.export import export_study_dataset
from mug.export.types import GitProvenanceRef
from mug.gateway import Gateway
from mug.kernel import Digest
from mug.kernel.refs import StudyVersionRef
from mug.preferences.runtime import response_id_for
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_ASK = "Which answer is better?"
_INPUT = {"messages": [{"role": "user", "text": "Explain gravity to a child."}]}
_STUDY_VERSION = StudyVersionRef(
    study_id="study_019b6000-0000-7000-8000-000000000001",
    study_version_id="studyver_019b6000-0000-7000-8000-000000000010",
    version_number=1,
    manifest_digest=_A_DIGEST,
)
_GIT = GitProvenanceRef(commit="0" * 40, branch="main", dirty=False)

_ANSWERS = {
    "warm-answer": "Gravity is the pull that brings you back down when you jump.",
    "dry-answer": "Gravity is the mutual attraction of masses.",
}


class _Writer(LLMAgent):
    """An author's model under test: a keyless local runner with a fixed build."""

    provider = Provider.OSS
    model = "fake-local"
    decides_every = 1
    on_timeout = Fallback.REPEAT_LAST

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        return ""


class _CountingAdapter:
    """A provider that answers one fixed text and counts how often it is called."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.calls += 1
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake-local-v3",
            usage=Usage(input_tokens=7, output_tokens=11, cost_micros=0),
            output={"text": self.text, "vendor_trace": "anthropic-internal-42"},
        )


class _Unreachable:
    """A provider that fails the test if anything calls it."""

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        raise AssertionError("a provider was contacted while a participant answered")


def _study() -> Study:
    """The study under test: read a page, then say which answer is better."""
    return Study(
        Page("intro", "# Read two answers"),
        Comparison(
            key="which-answer",
            ask=_ASK,
            of="model_output",
            options={"Warm": "warm-answer", "Dry": "dry-answer"},
        ),
        Page("debrief", "# Thank you"),
    )


def _generation_set(adapters: dict[str, Any]) -> GenerationSet:
    return GenerationSet(
        input=_INPUT,
        models={
            key: ModelUnderTest(agent=_Writer(), adapter=adapter)
            for key, adapter in adapters.items()
        },
    )


def _adapters() -> dict[str, _CountingAdapter]:
    return {key: _CountingAdapter(text) for key, text in _ANSWERS.items()}


def _app(
    store: InMemoryStore,
    adapters: dict[str, Any] | None = None,
    *,
    gateway: Gateway | None = None,
) -> TestClient:
    return TestClient(
        build_study_app(
            study=_study(),
            store=store,
            gateway=gateway or Gateway(),
            generate=_generation_set(adapters or _adapters()),
        )
    )


def _answer(handle: str, key: str) -> dict[str, Any]:
    return {"type": "comparison_response", "choice": handle, "idempotency_key": key}


def _reach_the_question(socket: Any) -> tuple[str, dict[str, Any]]:
    """Read the intro page, continue, and return the resume token and the options."""
    handshake = socket.receive_json()
    assert handshake["type"] == "handshake_ack"
    assert socket.receive_json()["delivery"]["activity_key"] == "intro"
    socket.send_json(_advance())
    delivery = _next_delivery(socket)
    assert delivery["kind"] == "comparison"
    return handshake["resume_token"], cast("dict[str, Any]", socket.receive_json())


def _next_delivery(socket: Any) -> dict[str, Any]:
    """Read frames until the next delivered activity, past the transport acks."""
    for _ in range(8):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame.get("type") == "delivery":
            return cast("dict[str, Any]", frame["delivery"])
    raise AssertionError("the flow delivered no further activity")


def _advance() -> dict[str, Any]:
    """Build the flow command the client sends to leave a content page."""
    return {
        "type": "command",
        "command": {
            "command_id": "command_019b6000-0000-7000-8000-0000000000f1",
            "channel_key": "flow.advance",
            "intent_schema": {
                "name": "mug.demo.intent",
                "version": 0,
                "digest": _A_DIGEST.model_dump(mode="json"),
            },
            "payload_digest": _A_DIGEST.model_dump(mode="json"),
            "idempotency_key": "idem_" + "9" * 21 + "A",
            "submitted_at": "2026-07-26T00:00:00.000000Z",
        },
        "payload": {"answers": {}},
    }


# -- the participant's side ------------------------------------------------------


def test_an_annotator_compares_two_generations_and_the_answer_is_recorded() -> None:
    """The whole loop: two recorded answers, one question, one recorded choice."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _reach_the_question(socket)
        assert options["type"] == "comparison"
        assert len(options["options"]) == 2

        socket.send_json(
            _answer(options["options"][0]["handle"], "idem_" + "a" * 21 + "A")
        )
        acknowledged = socket.receive_json()
        debrief = socket.receive_json()["delivery"]

    assert acknowledged["type"] == "comparison_ack"
    assert debrief["kind"] == "content"
    assert len(_responses(store)) == 1


def test_each_option_shows_the_text_the_generation_produced() -> None:
    """An annotator answers about the answers, so the answers are what is sent."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _reach_the_question(socket)

    shown = {option["text"] for option in options["options"]}
    assert shown == set(_ANSWERS.values())


def test_the_participant_is_sent_no_provider_and_no_model_identity() -> None:
    """The blinding NS-02 names is a property of the frame, so the frame is read."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _reach_the_question(socket)

    frame = json.dumps(options)
    assert "vendor_trace" not in frame, "the raw provider response reached the client"
    assert "anthropic" not in frame.lower()
    assert "fake-local" not in frame, "the model that answered reached the client"
    assert "Warm" not in frame and "Dry" not in frame, "the author's label leaked"
    assert "warm-answer" not in frame, "the option key named the condition"
    assert "generation_" not in frame
    for option in options["options"]:
        assert option["handle"].startswith("handle_")
        assert set(option) == {"handle", "text"}


def test_no_provider_is_contacted_while_a_participant_answers() -> None:
    """The generation ran before anyone connected, which is what NS-02 asks for."""
    store = InMemoryStore()
    adapters = _adapters()
    secret = b"a shared deployment secret"
    client = _app(store, adapters, gateway=Gateway(secret=secret))
    assert all(adapter.calls == 1 for adapter in adapters.values())

    # Every provider is now unreachable: the annotation reads artifacts only.
    unreachable = {key: _Unreachable() for key in _ANSWERS}
    second = _app(store, unreachable, gateway=Gateway(secret=secret))
    with second.websocket_connect("/ws") as socket:
        _, options = _reach_the_question(socket)
        socket.send_json(
            _answer(options["options"][0]["handle"], "idem_" + "b" * 21 + "A")
        )
        assert socket.receive_json()["type"] == "comparison_ack"

    assert all(adapter.calls == 1 for adapter in adapters.values())
    assert len(_responses(store)) == 1
    del client


def test_a_comparison_over_a_generation_that_was_never_recorded_records_nothing()  -> (
    None
):
    """A question about a gap is not asked, and nothing is recorded in its place."""
    store = InMemoryStore()
    study = Study(
        Page("intro", "# Read two answers"),
        Comparison(
            key="which-answer",
            ask=_ASK,
            of="model_output",
            options={"Warm": "warm-answer", "Missing": "never-generated"},
        ),
        Page("debrief", "# Thank you"),
    )
    client = TestClient(
        build_study_app(
            study=study,
            store=store,
            gateway=Gateway(),
            generate=_generation_set({"warm-answer": _CountingAdapter("only one")}),
        )
    )
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "intro"
        socket.send_json(_advance())
        asked = _next_delivery(socket)
        debrief = _next_delivery(socket)

    assert asked["kind"] == "comparison"
    assert debrief["kind"] == "content"
    assert _assignments(store) == [], "a comparison was assigned over a missing option"


def test_a_refresh_resumes_the_same_assignment_and_the_same_order() -> None:
    """A participant who reloads meets the question they were already asked."""
    store = InMemoryStore()
    gateway = Gateway()
    client = _app(store, gateway=gateway)
    with client.websocket_connect("/ws") as socket:
        token, first = _reach_the_question(socket)

    with client.websocket_connect(f"/ws?resume_token={token}") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["kind"] == "comparison"
        again = socket.receive_json()

    assert again["assignment_id"] == first["assignment_id"]
    assert [option["text"] for option in again["options"]] == [
        option["text"] for option in first["options"]
    ]
    assert len(_assignments(store)) == 1


# -- what was recorded, and who may read it --------------------------------------


def test_a_generation_is_recorded_in_three_distinct_forms() -> None:
    """Raw, normalized, and visible are three references, not three views of one."""
    store = InMemoryStore()
    _app(store)
    generation = _generation(store, "warm-answer")

    ids = {
        generation.raw.artifact_id,
        generation.normalized.artifact_id,
        generation.visible.artifact_id,
    }
    assert len(ids) == 3, "two forms shared one artifact"
    assert generation.provenance.artifact_id not in ids


async def test_the_three_forms_narrow_and_only_the_visible_one_is_public() -> None:
    """Each form answers a different question and carries its own classification."""
    store = InMemoryStore()
    _app(store)
    generation = _generation(store, "warm-answer")

    raw = await _read(store, generation.raw.artifact_id)
    normalized = await _read(store, generation.normalized.artifact_id)
    visible = await _read(store, generation.visible.artifact_id)

    assert raw["vendor_trace"] == "anthropic-internal-42"
    assert "vendor_trace" not in normalized, "the vendor stayed in the normalized form"
    assert normalized["text"] == _ANSWERS["warm-answer"]
    assert visible == {"text": _ANSWERS["warm-answer"]}

    assert generation.raw.data_handling.privacy_labels == ["research", "sensitive"]
    assert generation.normalized.data_handling.privacy_labels == ["research"]
    assert generation.visible.data_handling.privacy_labels == ["public"]


async def test_the_provider_identity_is_in_the_private_provenance_alone() -> None:
    """Blinded and available are both true, because the evidence is separated."""
    store = InMemoryStore()
    _app(store)
    generation = _generation(store, "warm-answer")

    provenance = await _read_json(store, generation.provenance.artifact_id)
    assert provenance["provider"] == "oss"
    assert provenance["resolved_model"] == "fake-local-v3"
    assert provenance["model_selector"] == "fake-local"
    assert provenance["modelcall_id"] == generation.modelcall_id
    assert generation.provenance.data_handling.privacy_labels == [
        "research",
        "sensitive",
    ]

    # And none of it is in the form the participant is shown.
    visible = json.dumps(await _read(store, generation.visible.artifact_id))
    assert "oss" not in visible and "fake-local" not in visible


def test_a_second_start_records_no_second_generation() -> None:
    """A restart finds the recorded generation and calls no model again.

    The generation address derives through the gateway's secret, so this holds for a
    restart and for a second process exactly when they share that secret -- the same
    rule that makes a client retry idempotent whichever process it lands on.
    """
    store = InMemoryStore()
    adapters = _adapters()
    secret = b"a shared deployment secret"
    _app(store, adapters, gateway=Gateway(secret=secret))
    before = _generation(store, "warm-answer")
    _app(store, adapters, gateway=Gateway(secret=secret))

    assert all(adapter.calls == 1 for adapter in adapters.values())
    assert _generation(store, "warm-answer") == before
    assert len(_generations(store)) == 2


def test_the_recorded_choice_names_the_generation_it_preferred() -> None:
    """The lineage is inside the record: the choice is the generation it stands for."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _reach_the_question(socket)
        socket.send_json(
            _answer(options["options"][1]["handle"], "idem_" + "c" * 21 + "A")
        )
        socket.receive_json()
        socket.receive_json()

    response = _responses(store)[0]
    assert sorted(response["presented_order"]) == _generations(store)
    assert response["choice"] in _generations(store)


def test_the_comparison_records_the_candidate_kind_the_author_wrote() -> None:
    """``of="model_output"`` is recorded as the contract's own name for the kind."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _reach_the_question(socket)

    comparison = _study().comparison("which-answer")
    assert comparison.of == "model-output"


async def test_the_export_carries_the_choice_and_reaches_both_generations() -> None:
    """A researcher reads the answer, then opens the generation behind it."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _, options = _reach_the_question(socket)
        socket.send_json(
            _answer(options["options"][0]["handle"], "idem_" + "d" * 21 + "A")
        )
        socket.receive_json()
        socket.receive_json()

    gateway = Gateway()
    export = await export_study_dataset(
        store=store,
        artifacts=store,
        study_version=_STUDY_VERSION,
        git_provenance=_GIT,
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=lambda: "2026-07-26T00:00:00.000000Z",
    )
    values = {kind.dataset_kind: kind for kind in export.values}
    rows = [
        json.loads(line)
        for line in (
            await store.read_artifact(values["preferences"].artifact.artifact_id)
        )
        .decode()
        .splitlines()
    ]
    # The assignment and the response are two records of one annotation, each the
    # head of its own aggregate, so both travel in the export.
    choice = next(
        row["state"]
        for row in rows
        if row["state"]["schema"]["name"] == "mug.api-18.preference-response"
    )
    # Each presented candidate is a generation the store still holds, so the text
    # that was compared is reachable from the exported choice alone.
    for candidate in choice["presented_order"]:
        generation = recorded_generation(store, candidate)
        assert generation is not None
        assert (await _read(store, generation.visible.artifact_id))["text"] in set(
            _ANSWERS.values()
        )


# -- reading what was recorded ---------------------------------------------------


async def _read(store: InMemoryStore, artifact_id: str) -> dict[str, Any]:
    """Read one stored generation form and return the output it holds."""
    body = await _read_json(store, artifact_id)
    return cast("dict[str, Any]", body["output"])


async def _read_json(store: InMemoryStore, artifact_id: str) -> dict[str, Any]:
    """Read one stored artifact back as the object it holds."""
    data = await store.read_artifact(artifact_id)
    return cast("dict[str, Any]", json.loads(data.decode().splitlines()[0]))


def _generation(store: InMemoryStore, key: str) -> Any:
    """Return the one generation the study recorded under one option key."""
    for aggregate_id in _generations(store):
        found = recorded_generation(store, aggregate_id)
        if found is not None and found.generation_key == key:
            return found
    raise AssertionError(f"no generation was recorded for {key!r}")


def _generations(store: InMemoryStore) -> list[str]:
    """Return every generation aggregate the run committed."""
    return sorted(
        aggregate_id
        for aggregate_id, _ in store.scan_aggregates()
        if aggregate_id.startswith("generation_")
    )


def _assignments(store: InMemoryStore) -> list[str]:
    """Return every preference aggregate the run committed."""
    return sorted(
        aggregate_id
        for aggregate_id, _ in store.scan_aggregates()
        if aggregate_id.startswith("prefassign_")
    )


def _responses(store: InMemoryStore) -> list[dict[str, Any]]:
    """Return every recorded preference response, read from its own aggregate.

    A response heads its own aggregate, whose identifier body is the assignment's,
    so the assignment stays readable after the answer.
    """
    found: list[dict[str, Any]] = []
    for aggregate_id in _assignments(store):
        state = store.load_aggregate(response_id_for(aggregate_id))
        if isinstance(state, dict):
            found.append(cast("dict[str, Any]", state))
    return found


def test_a_changed_input_is_a_different_generation() -> None:
    """NS-02 compares two models on *one versioned input*, so the input is in the
    address: change the question and the recorded answers are different answers."""
    store = InMemoryStore()
    secret = b"a shared deployment secret"
    adapters = _adapters()
    _app(store, adapters, gateway=Gateway(secret=secret))
    first = _generation(store, "warm-answer")

    asked_again = {**_INPUT, "messages": [{"role": "user", "text": "Explain time."}]}
    TestClient(
        build_study_app(
            study=_study(),
            store=store,
            gateway=Gateway(secret=secret),
            generate=GenerationSet(
                input=asked_again,
                models={
                    key: ModelUnderTest(agent=_Writer(), adapter=adapter)
                    for key, adapter in adapters.items()
                },
            ),
        )
    )

    assert all(adapter.calls == 2 for adapter in adapters.values())
    assert len(_generations(store)) == 4
    assert _generation_ids_for(store, "warm-answer") != [first.generation_id]


def _generation_ids_for(store: InMemoryStore, key: str) -> list[str]:
    """Return every generation aggregate recorded under one option key."""
    found: list[str] = []
    for aggregate_id in _generations(store):
        generation = recorded_generation(store, aggregate_id)
        if generation is not None and generation.generation_key == key:
            found.append(aggregate_id)
    return found


def test_the_generation_identifier_derives_from_the_key_and_the_input() -> None:
    """One key and one input always give one generation, on any process."""
    store = InMemoryStore()
    gateway = Gateway(secret=b"a shared deployment secret")
    _app(store, gateway=gateway)

    expected = generation_id_for(
        gateway.derived_id, "warm-answer", input_digest_of(_INPUT)
    )
    assert recorded_generation(store, expected) is not None
