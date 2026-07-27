"""A participant answers a form, and the researcher reads what they said.

`advance_flow` validated every answer against the form the author wrote and then
committed a flow head saying the activity was completed. The values reached no
aggregate, no event, and no artifact: a study that asked for consent, a mood
rating, and a free-text comment kept none of the three, and `FormResponse` was a
frozen record with fixtures and no producer.

These tests drive the whole application -- the real transport, the real flow, the
real export -- over a study that asks three questions of three kinds, and check
that what was said is what is recorded, that it is checkable against the ledger,
and that a participant is recorded once however many times they submit.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.content import Choice, Form, Likert, Page, Study, Text
from mug.content.forms import (
    read_answers,
    recorded_answers,
    recorded_form_response,
)
from mug.content.plan import occurrence_id_for
from mug.export import export_study_dataset
from mug.export.types import GitProvenanceRef
from mug.gateway import Gateway
from mug.kernel import Digest, compute_digest
from mug.kernel.refs import StudyVersionRef
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_COMMENT = "the second round felt much easier than the first"
_STUDY_VERSION = StudyVersionRef(
    study_id="study_019b6000-0000-7000-8000-000000000001",
    study_version_id="studyver_019b6000-0000-7000-8000-000000000010",
    version_number=1,
    manifest_digest=_A_DIGEST,
)
_GIT = GitProvenanceRef(commit="0" * 40, branch="main", dirty=False)


def _study() -> Study:
    """The study under test: one form of three field kinds, then a debrief."""
    return Study(
        Form(
            "consent",
            Choice("agree", "Do you consent to take part?", ["yes", "no"]),
            Likert("mood", "How do you feel right now?", scale=5),
            Text("comment", "Anything you want to tell us?"),
        ),
        Page("debrief", "# Thank you"),
    )


def _app(store: InMemoryStore, gateway: Gateway | None = None) -> TestClient:
    return TestClient(
        build_study_app(study=_study(), store=store, gateway=gateway or Gateway())
    )


def _advance(answers: dict[str, Any], n: int) -> dict[str, Any]:
    """Build the flow command the client sends when it submits a form."""
    return {
        "type": "command",
        "command": {
            "command_id": f"command_019b6000-0000-7000-8000-0000000000{n:02x}",
            "channel_key": "flow.advance",
            "intent_schema": {
                "name": "mug.demo.intent",
                "version": 0,
                "digest": _A_DIGEST.model_dump(mode="json"),
            },
            "payload_digest": _A_DIGEST.model_dump(mode="json"),
            "idempotency_key": "idem_" + str(n) * 21 + "A",
            "submitted_at": "2026-07-26T00:00:00.000000Z",
        },
        "payload": {"answers": answers},
    }


_ANSWERS: dict[str, Any] = {"agree": "yes", "mood": 4, "comment": _COMMENT}


def _answer_the_form(
    socket: Any, answers: dict[str, Any] | None = None, n: int = 1
) -> dict[str, Any]:
    """Read the form, submit it, and return the delivery that follows."""
    assert socket.receive_json()["type"] == "handshake_ack"
    assert socket.receive_json()["delivery"]["activity_key"] == "consent"
    socket.send_json(_advance(answers if answers is not None else _ANSWERS, n))
    return _next_delivery(socket)


def _next_delivery(socket: Any) -> dict[str, Any]:
    """Read frames until the next delivered activity, past the transport acks."""
    for _ in range(8):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame.get("type") == "delivery":
            return cast("dict[str, Any]", frame["delivery"])
    raise AssertionError("the flow delivered no further activity")


# -- what the participant said ---------------------------------------------------


async def test_what_the_participant_answered_is_what_is_recorded() -> None:
    """All three field kinds reach the store, with the question that asked them."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        debrief = _answer_the_form(socket)

    assert debrief["kind"] == "content"
    body = await _recorded_body(store)
    assert body["answers"] == _ANSWERS
    # An answer means nothing without the question, so the form travels with it.
    assert body["form_key"] == "consent"
    assert body["form_version"] == 1


async def test_the_recorded_answers_are_checkable_against_the_ledger() -> None:
    """Evidence, not a file beside the ledger: re-digesting reproduces the record."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _answer_the_form(socket)

    occurrence = _occurrences(store)[0]
    response = recorded_form_response(store, occurrence)
    assert response is not None
    body = await _recorded_body(store)
    assert compute_digest(body).hex == response.answers_digest.hex
    # And the aggregate the commit bound is the record itself.
    head = cast("dict[str, Any]", store.load_aggregate(occurrence))
    assert head["schema"]["name"] == "mug.api-17.form-response"
    assert head["visit_id"] == response.visit_id


def test_the_occurrence_derives_from_the_visit_and_the_form() -> None:
    """A participant meets one occurrence per form, on every connection."""
    store = InMemoryStore()
    gateway = Gateway(secret=b"a shared deployment secret")
    with _app(store, gateway).websocket_connect("/ws") as socket:
        _answer_the_form(socket)

    occurrence = _occurrences(store)[0]
    response = recorded_form_response(store, occurrence)
    assert response is not None
    assert occurrence == occurrence_id_for(
        gateway.derived_id, response.visit_id, "consent"
    )


def test_a_form_that_is_refused_records_nothing() -> None:
    """A rejected submission must not leave half an answer behind."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "consent"
        # 'maybe' is not one of the options the author wrote.
        socket.send_json(_advance({"agree": "maybe", "mood": 4}, 2))
        socket.receive_json()

    assert _occurrences(store) == [], "a refused form recorded an answer"


async def test_two_forms_in_one_visit_are_two_occurrences() -> None:
    """The occurrence derives from the form as well as the visit.

    A study that asks twice must keep both answers. If the derivation named only the
    visit, the second form would land on the first one's aggregate and the store
    would fence it -- the participant would answer and nothing would change.
    """
    store = InMemoryStore()
    study = Study(
        Form("pre", Text("hope", "What do you expect?")),
        Form("post", Text("hope", "What actually happened?")),
        Page("debrief", "# Thank you"),
    )
    client = TestClient(build_study_app(study=study, store=store, gateway=Gateway()))
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "pre"
        socket.send_json(_advance({"hope": "something easy"}, 4))
        assert _next_delivery(socket)["activity_key"] == "post"
        socket.send_json(_advance({"hope": "something hard"}, 5))
        assert _next_delivery(socket)["kind"] == "content"

    occurrences = _occurrences(store)
    assert len(occurrences) == 2, "one form overwrote the other"
    said = {(await _body_of(store, one))["answers"]["hope"] for one in occurrences}
    assert said == {"something easy", "something hard"}


async def test_the_flow_does_not_advance_past_answers_it_did_not_record() -> None:
    """Advancing past an unrecorded form is exactly how the answers were lost.

    The recorder is the seam that ends that, so a recorder which fails must stop
    the flow rather than let the participant walk on with nothing kept.
    """
    from mug.content.service import (
        AdvanceFlowCommand,
        MaterializeFlowCommand,
        advance_flow,
        materialize_flow,
    )

    store, gateway = InMemoryStore(), Gateway()
    study = _study()
    plan_id = gateway.new_id("visitplan")
    await materialize_flow(
        MaterializeFlowCommand(visit_id=gateway.new_id("visit")),
        study=study,
        context=_context(gateway, plan_id, 1),
        store=store,
        **_plan_args(gateway),  # pyright: ignore[reportArgumentType]
    )

    async def refuse(_form: Any, _answers: dict[str, Any]) -> bool:
        return False

    receipt = await advance_flow(
        AdvanceFlowCommand(answers=_ANSWERS, expected_revision=1),
        study=study,
        context=_context(gateway, plan_id, 2),
        store=store,
        on_answers=refuse,
    )
    assert receipt.outcome == "rejected"
    head = cast("dict[str, Any]", store.load_aggregate(plan_id))
    assert head["flow"]["pointer"] == 0
    assert head["activities"][0]["status"] == "active"


def _context(gateway: Gateway, target: str, n: int) -> Any:
    """Mint one command context on an aggregate's stream, as the mount would."""
    from mug.kernel import DataHandlingRef, PrincipalRef, WireCommandEnvelope

    zero = Digest(algorithm="sha-256", hex="0" * 64).model_dump(mode="json")
    envelope = WireCommandEnvelope.model_validate(
        {
            "schema": {"name": "mug.command-envelope", "version": 0, "digest": zero},
            "protocol_version": "0.1.0",
            "command": {"name": "flow.advance", "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-00000000000" + str(n),
            "idempotency_key": "idem_" + str(n) * 21 + "A",
            "target": {"id": target},
            "payload": {
                "schema": {"name": "mug.edge.payload", "version": 0, "digest": zero},
                "data": {},
            },
        }
    )
    return gateway.mint(
        envelope,
        principal=PrincipalRef(kind="participant", id=gateway.new_id("participant")),
        data_handling=DataHandlingRef(privacy_labels=["research"]),
    )


async def test_a_second_participant_does_not_overwrite_the_first() -> None:
    """The occurrence is per visit, so two participants keep two answers."""
    store = InMemoryStore()
    client = _app(store, Gateway(secret=b"a shared deployment secret"))
    with client.websocket_connect("/ws") as socket:
        _answer_the_form(socket)
    first = _occurrences(store)
    assert len(first) == 1

    with client.websocket_connect("/ws") as socket:
        _answer_the_form(socket, {"agree": "no", "mood": 1, "comment": "nope"}, n=3)

    both = _occurrences(store)
    assert len(both) == 2
    said = {(await _body_of(store, one))["answers"]["comment"] for one in both}
    assert said == {_COMMENT, "nope"}


async def _body_of(store: InMemoryStore, occurrence: str) -> dict[str, Any]:
    """Read back the answers one recorded occurrence names."""
    reference = recorded_answers(store, occurrence)
    assert reference is not None
    return read_answers(await store.read_artifact(reference.artifact_id))


# -- what the researcher reads ---------------------------------------------------


async def test_the_export_carries_the_answers() -> None:
    """A researcher reads the answers out of the export, not out of the store."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _answer_the_form(socket)

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
    assert "forms" in values, "the export carried no form values"
    rows = await _rows(store, values["forms"].artifact.artifact_id)
    state = cast("dict[str, Any]", rows[0]["state"])
    assert state["form_key"] == "consent"
    # The row names the answers artifact, and the artifact holds what was said.
    body = read_answers(await store.read_artifact(state["answers"]["artifact_id"]))
    assert body["answers"]["comment"] == _COMMENT


async def test_a_form_bundle_is_not_invented_for_a_frozen_enum() -> None:
    """``forms`` has values and no bundle: the frozen kinds are exactly four."""
    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _answer_the_form(socket)

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
    assert "forms" not in {bundle.dataset_kind for bundle in export.bundles}
    assert "forms" in {values.dataset_kind for values in export.values}
    # And every bundle it did export says what was asked for.
    assert {r.dataset_kind for r in export.requests} == {
        b.dataset_kind for b in export.bundles
    }
    for request in export.requests:
        assert request.study_version == _STUDY_VERSION


async def test_the_command_line_export_writes_the_artifacts_it_names(
    tmp_path: Any,
) -> None:
    """A values row names its evidence, so the export must carry the evidence too.

    Before this, ``mug export`` wrote the rows and none of the artifacts they point
    at -- the answers, the trajectories, the generations -- so the directory a
    researcher took away named files that were not in it.
    """
    from mug.cli.commands import run_export
    from mug.cli.session import CliSession, DurableStore

    store = InMemoryStore()
    with _app(store).websocket_connect("/ws") as socket:
        _answer_the_form(socket)

    session = CliSession.open(store=cast("DurableStore", store), gateway=Gateway())
    out = tmp_path / "export"
    # The study version has to be handed in: nothing publishes the study the app
    # ran, so ``discover_study_version`` finds none. That is W21, not this item.
    version_file = tmp_path / "study-version.json"
    version_file.write_text(_STUDY_VERSION.model_dump_json())
    await run_export(session, out, study_version_path=version_file, kinds=["events"])

    written = sorted(path.name for path in (out / "artifacts").glob("*.json"))
    assert written, "the export named artifacts it did not write"
    reference = recorded_answers(store, _occurrences(store)[0])
    assert reference is not None
    assert f"{reference.artifact_id}.json" in written
    manifest = json.loads((out / "manifest.json").read_text())
    assert reference.artifact_id in manifest["artifacts"]


# -- reading what was recorded ---------------------------------------------------


def _occurrences(store: InMemoryStore) -> list[str]:
    """Return every form-response aggregate the run committed."""
    return sorted(
        aggregate_id
        for aggregate_id, _ in store.scan_aggregates()
        if aggregate_id.startswith("activity_")
    )


async def _recorded_body(store: InMemoryStore) -> dict[str, Any]:
    """Read back the answers artifact one recorded form names."""
    reference = recorded_answers(store, _occurrences(store)[0])
    assert reference is not None
    return read_answers(await store.read_artifact(reference.artifact_id))


async def _rows(store: InMemoryStore, artifact_id: str) -> list[dict[str, Any]]:
    """Read one ndjson artifact back into its rows."""
    data = await store.read_artifact(artifact_id)
    return [
        cast("dict[str, Any]", json.loads(line))
        for line in data.decode().splitlines()
        if line.strip()
    ]


def _seeding(gateway: Gateway) -> Callable[[str], bytes]:
    """The seed source a plan draws its orders from."""
    return lambda role: gateway.derived_seed("treatment", role)


def _plan_args(gateway: Gateway) -> dict[str, object]:
    """The identity and seed a plan is drafted with, for a study with no design."""
    return {
        "study_version": StudyVersionRef(
            study_id=gateway.derived_id("study", "test"),
            study_version_id=gateway.derived_id("studyver", "test"),
            version_number=1,
            manifest_digest=Digest(algorithm="sha-256", hex="0" * 64),
        ),
        "derive": gateway.derived_id,
        "seed": _seeding(gateway),
    }
