"""Fixture 7: a form flow with randomization, repeats, state, and a redirect.

This is the study with no game in it, and it is the one most studies actually
are: consent, instructions, a task met more than once, a questionnaire, a
debrief, a completion code, and a link back to where the participant came from.
The parity document asks for all six capabilities **in one flow**, because that is
where they interact -- a participant who is randomized into a condition must keep
it across the repeats, and what they carry between activities must survive both.

- **Randomization.** The instructions a participant reads are the manipulation. It
  is assigned, balanced, and recorded, so the data says which condition each
  person was in.
- **Repeated activities.** A within-subject factor makes one activity happen once
  per level, in a recorded order. It is one activity that occurred twice, not two
  activities, and each occurrence is named.
- **Participant state.** An early activity writes a namespace the study declared,
  and a later one is delivered it.
- **Completion and redirect.** The participant reaches the end with a completion
  code and the return link a recruitment platform needs.
"""

from __future__ import annotations

from typing import Any, cast

from _participant import Participant
from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.content import Choice, Form, Likert, Page, Study, Text, plan_of
from mug.content.plan import occurrence_id_for
from mug.gateway import Gateway
from mug.storage import InMemoryStore, Store
from mug.visits.assignment import (
    Treatment,
    assignment_id_for,
    recorded_assignments,
)
from mug.visits.design import Order
from mug.visits.state import State

_RETURN = "https://recruitment.test/return"
_SECRET = b"a-shared-deployment-secret------"

_CAREFUL = "Take as long as you like. There is no time limit."
_QUICK = "Work quickly. You have thirty seconds for each answer."

_SHORT = "# A short task\n\nName one thing you can see."
_LONG = "# A longer task\n\nName five things you can see."


def _study() -> Study:
    """Return the whole flow: randomized, repeated, stateful, and completed."""
    pace = Treatment("pace", {"careful": _CAREFUL, "quick": _QUICK})
    task = Treatment(
        "task-length",
        {"short": _SHORT, "long": _LONG},
        within=True,
        order=Order.RANDOMIZED,
    )
    return Study(
        Form("consent", Choice("agree", "Do you agree to take part?", ["yes", "no"])),
        Page("instructions", pace.map({"careful": _CAREFUL, "quick": _QUICK})),
        Page("task", task.map({"short": _SHORT, "long": _LONG})),
        Form(
            "survey",
            Likert("effort", "How hard did you work?", scale=7),
            Text("comments", "Anything to add?", required=False),
        ),
        Page("debrief", "# Thank you"),
        state=[State("progress")],
    )


def _plan_of(store: Store) -> Any:
    """Return the one committed plan the visit followed."""
    found = [
        plan
        for _aggregate_id, state in store.scan_aggregates()
        if (plan := plan_of(state)) is not None
    ]
    assert len(found) == 1
    return found[0]


def _visit_of(store: Store) -> str:
    """Return the visit the one plan was materialized for."""
    return str(_plan_of(store).visit_id)


def _client(store: Store, gateway: Gateway) -> TestClient:
    return TestClient(
        build_study_app(
            study=_study(),
            store=store,
            gateway=gateway,
            return_url=_RETURN,
        )
    )


def _walk(person: Participant, *, write_state: bool = True) -> dict[str, Any]:
    """Walk the whole study, and return everything it delivered on the way."""
    seen: list[dict[str, Any]] = []
    for _ in range(24):
        delivered = person.delivery()
        seen.append(delivered)
        kind = delivered["kind"]
        if kind == "complete":
            return {"seen": seen, "completion": delivered}
        if kind == "form" and delivered["form"]["form_key"] == "consent":
            person.advance({"agree": "yes"})
        elif kind == "form":
            person.advance({"effort": 5})
        else:
            if write_state and delivered.get("activity_key") == "instructions":
                person.send(
                    "state.set",
                    {
                        "namespace": "progress",
                        "value": {"read-instructions": True},
                        "revision": 0,
                    },
                )
            person.advance()
    raise AssertionError("the study never finished")


def test_one_participant_walks_the_whole_flow_to_a_code_and_a_link() -> None:
    """The capability: every part of the flow, in one run, ending correctly."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    client = _client(store, gateway)
    with client, client.websocket_connect("/ws") as socket:
        walked = _walk(Participant(socket).handshake())

    completion = cast("dict[str, Any]", walked["completion"])
    assert completion["completion_code"].startswith("MUG-")
    assert completion["return_url"] == _RETURN


def test_the_participant_is_randomized_and_the_record_says_into_what() -> None:
    """A manipulation nobody can read back is not a manipulation."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    client = _client(store, gateway)
    with client, client.websocket_connect("/ws") as socket:
        walked = _walk(Participant(socket).handshake())

    instructions = [
        one
        for one in cast("list[dict[str, Any]]", walked["seen"])
        if one.get("activity_key") == "instructions"
    ]
    assert len(instructions) == 1
    body = str(instructions[0]["content"]["body"]["text"])
    assert body in {_CAREFUL, _QUICK}

    visit_id = _visit_of(store)
    assigned = recorded_assignments(
        store, assignment_id_for(gateway.derived_id, visit_id, "pace")
    )
    levels = {one.treatment_key: one.level_key for one in assigned}
    assert levels.get("pace") in {"careful", "quick"}
    # The page the participant read is the page their assigned level names.
    assert body == (_CAREFUL if levels["pace"] == "careful" else _QUICK)


def test_the_repeated_activity_happens_once_per_level_under_its_own_name() -> None:
    """One activity that occurred twice, and the records tell the two apart."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    client = _client(store, gateway)
    with client, client.websocket_connect("/ws") as socket:
        walked = _walk(Participant(socket).handshake())

    tasks = [
        one
        for one in cast("list[dict[str, Any]]", walked["seen"])
        if one.get("activity_key") == "task"
    ]
    assert len(tasks) == 2, "a within-subject factor is met once per level"
    assert {str(one["content"]["body"]["text"]) for one in tasks} == {
        _SHORT,
        _LONG,
    }
    # Two occurrences of one activity, each named -- so an analysis can say which
    # of the two a response belongs to.
    assert tasks[0]["occurrence_key"] != tasks[1]["occurrence_key"]


def test_what_an_early_activity_wrote_reaches_a_later_one() -> None:
    """Participant state is what carries a study's own memory across its steps."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    client = _client(store, gateway)
    with client, client.websocket_connect("/ws") as socket:
        walked = _walk(Participant(socket).handshake())

    seen = cast("list[dict[str, Any]]", walked["seen"])
    first = next(one for one in seen if one.get("activity_key") == "instructions")
    debrief = next(one for one in seen if one.get("activity_key") == "debrief")

    # Empty before it is written, and delivered afterwards: a first read and a
    # hundredth read are one shape.
    assert first["state"] == {"progress": {}}
    assert debrief["state"] == {"progress": {"read-instructions": True}}


def test_a_study_that_writes_nothing_is_still_delivered_its_namespace() -> None:
    """A participant who wrote nothing reads an empty namespace, never a missing one."""
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    client = _client(store, gateway)
    with client, client.websocket_connect("/ws") as socket:
        walked = _walk(Participant(socket).handshake(), write_state=False)

    for delivered in cast("list[dict[str, Any]]", walked["seen"]):
        if delivered["kind"] in {"content", "form"}:
            assert delivered["state"] == {"progress": {}}


def test_the_flow_the_participant_walked_is_the_flow_that_was_planned() -> None:
    """The order was drawn once, committed, and then followed.

    A study that re-drew the order on each delivery would give a participant a
    different experiment from the one its own plan records.
    """
    store, gateway = InMemoryStore(), Gateway(secret=_SECRET)
    client = _client(store, gateway)
    with client, client.websocket_connect("/ws") as socket:
        walked = _walk(Participant(socket).handshake())

    plan = _plan_of(store)
    planned = [
        one.occurrence_id
        for one in sorted(plan.activities, key=lambda one: one.ordinal)
    ]
    delivered = [
        occurrence_id_for(gateway.derived_id, plan.visit_id, str(one["occurrence_key"]))
        for one in cast("list[dict[str, Any]]", walked["seen"])
        if "occurrence_key" in one
    ]
    assert delivered == planned
