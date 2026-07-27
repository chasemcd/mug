"""The participant flow service: materialize, present, advance, and refuse.

These tests drive the flow handlers through the real gateway, runtime spine, and
in-memory store. A flow materializes at the consent form; a valid answer advances
to the survey; an invalid answer is refused with a safe validation error; the
flow reaches completion at the end of the study; and advancing an unknown flow is
refused as not found.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mug.content import (
    AdvanceFlowCommand,
    FlowState,
    MaterializeFlowCommand,
    advance_flow,
    demo_study,
    flow_of,
    materialize_flow,
    plan_of,
    present,
)
from mug.gateway import Gateway
from mug.kernel import (
    CommandReceipt,
    DataHandlingRef,
    Digest,
    PrincipalRef,
    WireCommandEnvelope,
)
from mug.kernel.refs import StudyVersionRef
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_PARTICIPANT = PrincipalRef(
    kind="participant", id="participant_019b6000-0000-7000-8000-0000000000aa"
)
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_FLOW_ID = "visitplan_019b6000-0000-7000-8000-00000000000a"
_VISIT_ID = "visit_019b6000-0000-7000-8000-00000000000b"


def _idem(tag: str) -> str:
    return "idem_" + tag.ljust(21, "0") + "A"


def _mint(
    gateway: Gateway, command_name: str, target_id: str, data: dict[str, Any], idem: str
) -> CommandContext:
    envelope = {
        "schema": {
            "name": "mug.command-envelope",
            "version": 0,
            "digest": _A_DIGEST.model_dump(mode="json"),
        },
        "protocol_version": "0.1.0",
        "command": {"name": command_name, "version": 0},
        "request_id": "request_019b6000-0000-7000-8000-000000000001",
        "idempotency_key": idem,
        "target": {"id": target_id},
        "payload": {
            "schema": {
                "name": "mug.edge.payload",
                "version": 0,
                "digest": _A_DIGEST.model_dump(mode="json"),
            },
            "data": data,
        },
    }
    return gateway.mint(
        WireCommandEnvelope.model_validate(envelope),
        principal=_PARTICIPANT,
        data_handling=_RESEARCH,
    )


def _flow(store: InMemoryStore) -> FlowState:
    """Return the runtime flow the visit-plan aggregate carries."""
    state = flow_of(store.load_aggregate(_FLOW_ID))
    assert state is not None
    return state


async def _materialize(gateway: Gateway, store: InMemoryStore) -> CommandReceipt:
    context = _mint(
        gateway, "flow.materialize", _FLOW_ID, {"visit_id": _VISIT_ID}, _idem("Ma")
    )
    return await materialize_flow(
        MaterializeFlowCommand(visit_id=_VISIT_ID),
        study=demo_study(),
        context=context,
        store=store,
        **_plan_args(gateway),  # pyright: ignore[reportArgumentType]
    )


async def _advance(
    gateway: Gateway,
    store: InMemoryStore,
    answers: dict[str, Any],
    revision: int,
    idem: str,
) -> CommandReceipt:
    context = _mint(
        gateway,
        "flow.advance",
        _FLOW_ID,
        {"answers": answers, "expected_revision": revision},
        idem,
    )
    return await advance_flow(
        AdvanceFlowCommand(answers=answers, expected_revision=revision),
        study=demo_study(),
        context=context,
        store=store,
    )


async def test_materialize_opens_the_flow_at_the_consent_form() -> None:
    """A materialized flow starts at the consent form, active, others pending."""
    store = InMemoryStore()
    receipt = await _materialize(Gateway(), store)
    assert receipt.outcome == "accepted"

    state = _flow(store)
    plan = plan_of(store.load_aggregate(_FLOW_ID))
    assert plan is not None
    assert state.pointer == 0
    assert state.activities[0].key == "consent"
    assert state.activities[0].activity_key == "consent"
    # Progress is the plan's, not the pointer's: the pointer says where, the plan
    # says what has been done.
    assert [one.status for one in plan.activities][:2] == ["active", "pending"]
    assert plan.study_version.version_number == 1
    assert state.status == "in-progress"

    payload = present(state, demo_study())
    assert payload["kind"] == "form"
    assert payload["form"]["form_key"] == "consent"


async def test_a_valid_answer_advances_to_the_next_activity() -> None:
    """Consent answered advances the pointer to the survey form."""
    store = InMemoryStore()
    gateway = Gateway()
    await _materialize(gateway, store)

    receipt = await _advance(gateway, store, {"agree": "yes"}, 1, _idem("Av"))
    assert receipt.outcome == "accepted"

    state = _flow(store)
    plan = plan_of(store.load_aggregate(_FLOW_ID))
    assert plan is not None
    assert state.pointer == 1
    assert [one.status for one in plan.activities][:2] == ["completed", "active"]
    assert present(state, demo_study())["form"]["form_key"] == "survey"


async def test_an_invalid_answer_is_refused_before_it_advances() -> None:
    """A consent answer outside the options is refused and does not advance."""
    store = InMemoryStore()
    gateway = Gateway()
    await _materialize(gateway, store)

    receipt = await _advance(gateway, store, {"agree": "maybe"}, 1, _idem("Ai"))
    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.category == "validation"

    state = _flow(store)
    assert state.pointer == 0


async def test_the_flow_reaches_completion_at_the_end_of_the_study() -> None:
    """Answering each activity in turn drives the flow to completion."""
    store = InMemoryStore()
    gateway = Gateway()
    await _materialize(gateway, store)

    await _advance(gateway, store, {"agree": "yes"}, 1, _idem("A1"))
    await _advance(gateway, store, {"mood": 4}, 2, _idem("A2"))
    await _advance(gateway, store, {}, 3, _idem("A3"))  # the game activity
    receipt = await _advance(gateway, store, {}, 4, _idem("A4"))  # the debrief
    assert receipt.outcome == "accepted"

    state = _flow(store)
    assert state.status == "completed"
    completed = present(state, demo_study())
    assert completed["kind"] == "complete"
    assert completed["completion_code"].startswith("MUG-")


async def test_advancing_an_unknown_flow_is_refused() -> None:
    """Advancing a flow that was never materialized is refused as not found."""
    store = InMemoryStore()
    receipt = await _advance(Gateway(), store, {"agree": "yes"}, 1, _idem("Au"))
    assert receipt.outcome == "rejected"
    assert receipt.error is not None
    assert receipt.error.category == "not_found"


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
