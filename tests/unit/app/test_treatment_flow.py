"""A study manipulates something, and the data says what each participant got.

`mug/visits/types.py` declared factors, four assignment policies, counterbalanced
order, a durable allocation counter, and separate assignment and exposure records.
`materialize_flow` built the flow in the authored order and assigned nothing, so
none of it had a producer: every participant met the same study and the platform
could not answer "which condition was this person in".

These tests drive the whole application over studies that manipulate what a
participant reads. They hold four promises:

- a participant is assigned, reads the page their level names, and **keeps that
  condition** through a reload, a reconnection, and a restart of the process;
- **balance is durable** -- the counts survive the process, so a study restarted
  half way through does not rebalance from zero;
- **intent and delivery are separate records** -- a participant who leaves after
  consent has an assignment and no exposure, and the export keeps them apart;
- a within-subject factor **repeats its activity once per level**, in an order the
  plan records with a commitment to the seed that drew it.
"""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.content import Choice, Form, Page, Study, plan_of
from mug.content.plan import occurrence_id_for
from mug.export import export_study_dataset
from mug.export.types import GitProvenanceRef
from mug.gateway import Gateway
from mug.kernel import Digest
from mug.storage import ArtifactStore, InMemoryStore
from mug.visits.assignment import (
    Treatment,
    allocation_id_for,
    assignment_id_for,
    exposure_id_for,
    read_allocation,
    recorded_assignments,
    recorded_levels,
)
from mug.visits.design import Assign, Order

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_GIT = GitProvenanceRef(commit="0" * 40, branch="main", dirty=False)
_SECRET = b"a-shared-deployment-secret------"

_EASY = "Take as long as you like."
_HARD = "You have thirty seconds."


def _difficulty(**overrides: Any) -> Treatment:
    fields: dict[str, Any] = {"assign": Assign.balanced()}
    fields.update(overrides)
    return Treatment("difficulty", {"easy": _EASY, "hard": _HARD}, **fields)


def _study(treatment: Treatment) -> Study:
    """Consent, then instructions whose wording is the manipulation."""
    return Study(
        Form("consent", Choice("agree", "Do you consent to take part?", ["yes", "no"])),
        Page("instructions", treatment.map({"easy": _EASY, "hard": _HARD})),
        Page("debrief", "# Thank you"),
    )


def _app(store: InMemoryStore, study: Study, gateway: Gateway) -> TestClient:
    return TestClient(build_study_app(study=study, store=store, gateway=gateway))


def _advance(answers: dict[str, Any], n: int) -> dict[str, Any]:
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


def _next_delivery(socket: Any) -> dict[str, Any]:
    """Read frames until the next delivered activity, past the transport acks."""
    for _ in range(8):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame.get("type") == "delivery":
            return cast("dict[str, Any]", frame["delivery"])
    raise AssertionError("the flow delivered no further activity")


def _consent(socket: Any, n: int = 1) -> dict[str, Any]:
    """Answer the consent form and return the activity that follows it."""
    assert socket.receive_json()["type"] == "handshake_ack"
    assert socket.receive_json()["delivery"]["activity_key"] == "consent"
    socket.send_json(_advance({"agree": "yes"}, n))
    return _next_delivery(socket)


def _text(delivery: dict[str, Any]) -> str:
    """Return the page body one delivery carries."""
    return cast("str", delivery["content"]["body"]["text"])


def _reach_instructions(
    store: InMemoryStore, study: Study, gateway: Gateway, n: int = 1
) -> str:
    """Run one participant to the instructions and return what they read."""
    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        return _text(_consent(socket, n))


def _visit_of(store: InMemoryStore) -> str:
    """Return the one visit the store holds."""
    plans = [
        plan_of(state)
        for aggregate_id, state in store.scan_aggregates()
        if aggregate_id.startswith("visitplan_")
    ]
    found = [one for one in plans if one is not None]
    assert len(found) == 1
    return found[0].visit_id


# -- what a participant is given -------------------------------------------------


def test_a_participant_reads_the_page_their_assigned_level_names() -> None:
    """The manipulation is what the participant meets, not a field in a record."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    read = _reach_instructions(store, _study(_difficulty()), gateway)

    assert read in {_EASY, _HARD}
    levels = recorded_levels(
        store, assignment_id_for(gateway.derived_id, _visit_of(store), "difficulty")
    )
    assert read == (_EASY if levels["difficulty"] == "easy" else _HARD)


def test_a_reconnection_keeps_the_condition_the_participant_already_had() -> None:
    """A study whose condition changes under a refresh is not a study."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    client = _app(store, _study(_difficulty()), gateway)

    with client.websocket_connect("/ws") as socket:
        token = socket.receive_json()["resume_token"]
        assert socket.receive_json()["delivery"]["activity_key"] == "consent"
        socket.send_json(_advance({"agree": "yes"}, 1))
        first = _text(_next_delivery(socket))

    with client.websocket_connect(f"/ws?resume_token={token}") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        resumed = socket.receive_json()["delivery"]

    assert resumed["activity_key"] == "instructions"
    assert _text(resumed) == first
    # One visit, one assignment: the reconnection read what was already decided
    # rather than deciding again.
    assert len(_assignment_ids(store)) == 1


def _assignment_ids(store: InMemoryStore) -> list[str]:
    """Return every aggregate whose head is a treatment assignment."""
    return [
        aggregate_id
        for aggregate_id, state in store.scan_aggregates()
        if isinstance(state, dict)
        and cast("dict[str, Any]", state).get("schema", {}).get("name")
        == "mug.api-04.treatment-assignment"
    ]


def test_a_restart_reloads_the_committed_plan_and_reshuffles_nothing() -> None:
    """The plan is drawn once. A process restart re-reads it; it never redraws."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    study = _study(_difficulty())
    read = _reach_instructions(store, study, gateway)

    visit_id = _visit_of(store)
    plans = {
        aggregate_id: plan_of(state)
        for aggregate_id, state in store.scan_aggregates()
        if aggregate_id.startswith("visitplan_") and plan_of(state) is not None
    }
    before = next(iter(plans.values()))
    assert before is not None
    digest_before = before.plan_digest.hex

    # A whole new application over the same store and the same deployment secret.
    restarted = Gateway(secret=_SECRET)
    _app(store, study, restarted)

    after = plan_of(store.load_aggregate(next(iter(plans))))
    assert after is not None
    assert after.plan_digest.hex == digest_before
    assert recorded_levels(
        store, assignment_id_for(restarted.derived_id, visit_id, "difficulty")
    ) == recorded_levels(
        store, assignment_id_for(gateway.derived_id, visit_id, "difficulty")
    )
    assert read in {_EASY, _HARD}


def test_balance_holds_across_a_restart_rather_than_starting_over() -> None:
    """A counter that a restart resets is not balance, it is balance per process."""
    store = InMemoryStore()
    study = _study(_difficulty())
    read: list[str] = []
    for index in range(4):
        # A new gateway per participant, as a new process would have -- the secret
        # is the deployment's, so the derivations still agree.
        read.append(
            _reach_instructions(store, study, Gateway(secret=_SECRET), index + 1)
        )

    assert read.count(_EASY) == 2
    assert read.count(_HARD) == 2

    allocation = read_allocation(
        store,
        allocation_id_for(
            Gateway(secret=_SECRET).derived_id,
            _any_plan(store).study_version.study_version_id,
        ),
    )
    assert allocation is not None
    assert sum(one.participants for one in allocation.cells) == 4


def _any_plan(store: InMemoryStore) -> Any:
    for aggregate_id, state in store.scan_aggregates():
        if aggregate_id.startswith("visitplan_"):
            found = plan_of(state)
            if found is not None:
                return found
    raise AssertionError("no plan was committed")


# -- intent is not delivery -------------------------------------------------------


def test_a_participant_who_leaves_early_has_an_assignment_and_no_exposure() -> None:
    """Assignment is what they were given; exposure is what they reached."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    study = _study(_difficulty())
    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "consent"
        # They read the consent form and close the tab.

    visit_id = _visit_of(store)
    assert recorded_levels(
        store, assignment_id_for(gateway.derived_id, visit_id, "difficulty")
    )
    occurrence = occurrence_id_for(gateway.derived_id, visit_id, "instructions")
    assert (
        store.load_aggregate(
            exposure_id_for(gateway.derived_id, occurrence, "difficulty")
        )
        is None
    )


def test_reaching_the_activity_records_the_exposure_it_delivered() -> None:
    """The exposure names the occurrence and the level that was actually shown."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    read = _reach_instructions(store, _study(_difficulty()), gateway)

    visit_id = _visit_of(store)
    occurrence = occurrence_id_for(gateway.derived_id, visit_id, "instructions")
    state = store.load_aggregate(
        exposure_id_for(gateway.derived_id, occurrence, "difficulty")
    )
    assert isinstance(state, dict)
    body = cast("dict[str, Any]", state)
    assert body["occurrence_id"] == occurrence
    assert read == (_EASY if body["level_key"] == "easy" else _HARD)


async def test_the_export_keeps_assignment_and_exposure_as_distinct_rows() -> None:
    """A reader who cannot tell them apart cannot see their own dropout."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    _reach_instructions(store, _study(_difficulty()), gateway)

    export = await export_study_dataset(
        store=store,
        artifacts=cast("ArtifactStore", store),
        study_version=_any_plan(store).study_version,
        git_provenance=_GIT,
        export_key="treatments",
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=lambda: "2026-07-26T00:00:00.000000Z",
    )
    kinds = {one.dataset_kind: one for one in export.values}
    assert "assignments" in kinds
    assert "exposures" in kinds

    assigned = await _rows(store, kinds["assignments"].artifact.artifact_id)
    exposed = await _rows(store, kinds["exposures"].artifact.artifact_id)
    assert len(assigned) == 1
    assert len(exposed) == 1
    assert assigned[0]["state"]["treatment_key"] == "difficulty"
    assert exposed[0]["state"]["occurrence_id"].startswith("activity_")
    # The plan travels too, so the orders it drew leave a trace a reader can open.
    assert "plans" in kinds


async def _rows(store: InMemoryStore, artifact_id: str) -> list[dict[str, Any]]:
    data = await cast("ArtifactStore", store).read_artifact(artifact_id)
    return [
        cast("dict[str, Any]", json.loads(line))
        for line in data.decode("utf-8").splitlines()
        if line
    ]


# -- repeated activities and their order ------------------------------------------


def test_a_within_subject_factor_repeats_its_activity_once_per_level() -> None:
    """The participant meets every level, so the activity happens twice."""
    wording = Treatment(
        "wording", {"easy": _EASY, "hard": _HARD}, within=True, order=Order.RANDOMIZED
    )
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    study = _study(wording)

    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        first = _consent(socket)
        socket.send_json(_advance({}, 2))
        second = _next_delivery(socket)

    assert first["activity_key"] == "instructions"
    assert second["activity_key"] == "instructions"
    # One activity, two occurrences: each is its own step with its own name.
    assert first["occurrence_key"] != second["occurrence_key"]
    assert {_text(first), _text(second)} == {_EASY, _HARD}

    # Nobody is ASSIGNED a within-subject level, because they meet every one of
    # them. A record saying "this participant was in the easy condition" would be
    # false, so there is none -- only the order, and one exposure per occurrence.
    assert _assignment_ids(store) == []
    visit_id = _visit_of(store)
    exposed = [
        store.load_aggregate(
            exposure_id_for(
                gateway.derived_id,
                occurrence_id_for(gateway.derived_id, visit_id, key),
                "wording",
            )
        )
        for key in ("instructions.easy", "instructions.hard")
    ]
    assert [one["level_key"] for one in exposed if isinstance(one, dict)] == [
        "easy",
        "hard",
    ]


def test_the_plan_records_the_order_it_drew_and_commits_to_its_seed() -> None:
    """An order a deployment cannot later prove is an order nobody can check."""
    wording = Treatment(
        "wording", {"easy": _EASY, "hard": _HARD}, within=True, order=Order.RANDOMIZED
    )
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    _reach_instructions(store, _study(wording), gateway)

    plan = _any_plan(store)
    assert len(plan.randomization_outcomes) == 1
    outcome = plan.randomization_outcomes[0]
    assert outcome.rule_key == "wording"
    assert sorted(outcome.chosen) == ["easy", "hard"]
    assert outcome.seed_commitment.algorithm == "sha-256"
    assert [one.ordinal for one in plan.activities] == [0, 1, 2, 3]


def test_two_occurrences_of_one_activity_carry_different_parameters() -> None:
    """The plan says what each step delivers, so the two rounds are not the same."""
    wording = Treatment(
        "wording", {"easy": _EASY, "hard": _HARD}, within=True, order=Order.RANDOMIZED
    )
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    _reach_instructions(store, _study(wording), gateway)

    plan = _any_plan(store)
    repeated = [one for one in plan.activities if one.ordinal in (1, 2)]
    assert repeated[0].parameter_digest.hex != repeated[1].parameter_digest.hex
    # Same authored activity, so the same definition; different occurrences.
    assert repeated[0].activity_definition_id == repeated[1].activity_definition_id
    assert repeated[0].occurrence_id != repeated[1].occurrence_id


# -- a factor that waits for an answer --------------------------------------------


def test_a_stratified_factor_waits_for_its_answer_and_is_then_assigned() -> None:
    """It cannot be decided before the participant has said what it stratifies on."""
    screening = Form(
        "screening",
        Choice("handedness", "Which hand do you write with?", ["left", "right"]),
    )
    layout = Treatment(
        "layout",
        {"wide": _EASY, "narrow": _HARD},
        assign=Assign.stratified(by=screening.field("handedness")),
    )
    study = Study(
        screening,
        Page("instructions", layout.map({"wide": _EASY, "narrow": _HARD})),
        Page("debrief", "# Thank you"),
    )
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)

    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "screening"
        # Nothing is assigned yet: the answer it stratifies on does not exist.
        assert _assignment_ids(store) == []
        socket.send_json(_advance({"handedness": "left"}, 1))
        read = _text(_next_delivery(socket))

    visit_id = _visit_of(store)
    levels = recorded_levels(
        store, assignment_id_for(gateway.derived_id, visit_id, "layout")
    )
    assert levels["layout"] in {"wide", "narrow"}
    assert read == (_EASY if levels["layout"] == "wide" else _HARD)


def test_a_deferred_assignment_restates_the_step_it_will_be_delivered_at() -> None:
    """A plan that still names a placeholder condition is a plan that lies."""
    screening = Form(
        "screening", Choice("handedness", "Which hand?", ["left", "right"])
    )
    layout = Treatment(
        "layout",
        {"wide": _EASY, "narrow": _HARD},
        assign=Assign.stratified(by=screening.field("handedness")),
    )
    study = Study(
        screening, Page("instructions", layout.map({"wide": _EASY, "narrow": _HARD}))
    )
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)

    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["activity_key"] == "screening"
        before = _any_plan(store).activities[1].parameter_digest.hex
        socket.send_json(_advance({"handedness": "right"}, 1))
        _next_delivery(socket)

    after = _any_plan(store).activities[1].parameter_digest.hex
    assert after != before


# -- a study that manipulates nothing ---------------------------------------------


def test_a_study_with_no_treatment_records_no_assignment_at_all() -> None:
    """Everything here costs a questionnaire study nothing, not even a read."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    plain = Study(
        Form("consent", Choice("agree", "Do you consent to take part?", ["yes", "no"])),
        Page("instructions", _EASY),
    )
    with _app(store, plain, gateway).websocket_connect("/ws") as socket:
        assert _text(_consent(socket)) == _EASY

    names = {
        cast("dict[str, Any]", state).get("schema", {}).get("name")
        for _id, state in store.scan_aggregates()
        if isinstance(state, dict)
    }
    assert "mug.api-04.treatment-assignment" not in names
    assert "mug.api-04.treatment-exposure" not in names
    assert "mug.api-04.allocation-state" not in names


def test_one_assignment_aggregate_holds_every_factor_of_a_crossed_unit() -> None:
    """Half a cell is not an assignment: a crossed unit is one decision."""
    from mug.content import Design

    difficulty = Treatment("difficulty", {"easy": _EASY, "hard": _HARD})
    partner = Treatment("partner", ["human", "ai"])
    study = Study(
        Form("consent", Choice("agree", "Do you consent?", ["yes", "no"])),
        Page("instructions", difficulty.map({"easy": _EASY, "hard": _HARD})),
        Page("who", partner.map({"human": "A person.", "ai": "A model."})),
        design=Design(cross=[difficulty, partner]),
    )
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    _reach_instructions(store, study, gateway)

    written = recorded_assignments(
        store,
        assignment_id_for(gateway.derived_id, _visit_of(store), "difficulty+partner"),
    )
    assert sorted(one.treatment_key for one in written) == ["difficulty", "partner"]
    assert all(one.scope == "participant" for one in written)
    assert all(one.visit_id == _visit_of(store) for one in written)
