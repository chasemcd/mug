"""A study screens who may enter and who may stay, and records both decisions.

The API-06 monitoring ladder and the API-04 eligibility callback were fully
specified, had no runtime, and no client emitted a sample. So a study could declare
that it needed a fast connection and a participant on a poor one would play the
whole thing.

These tests drive the whole application. They hold four promises:

- a study that screens on latency **refuses entry**, and the refusal has a reason
  that a reader can find in the ledger;
- a participant who crosses the bound in play is **warned and then excluded**, and
  the exclusion is the gate op that says advancing is blocked;
- a refusal **survives a reconnection**: reloading the page is not a way to be
  judged again;
- a study that declares no screen **records nothing** and its clients are never
  even asked to measure.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient

from mug.app import build_study_app
from mug.content import Choice, Form, Page, Screen, Study, plan_of
from mug.gateway import Gateway
from mug.interactions.monitoring import monitoring_id_for, read_screening
from mug.participant_screening import screening_ids
from mug.storage import InMemoryStore
from mug.visits.eligibility import Entry, eligibility_id_for, read_decision

_SECRET = b"a-shared-deployment-secret------"


def only_fast_browsers(entry: Entry) -> bool | str:
    """A study's own entry rule: it wants evidence, and it wants it good."""
    if "rtt" not in entry.metrics:
        return "this study needs to measure your connection"
    return True


def refuse_everyone(entry: Entry) -> bool | str:
    """A study's own entry rule that turns everybody away, with a reason."""
    return "this study has closed to new participants"


def broken_rule(entry: Entry) -> bool | str:
    """A study's own entry rule that does not work, which is the interesting case."""
    raise RuntimeError("the study's rule is broken")


def _study(**screening: Any) -> Study:
    return Study(
        Form("consent", Choice("agree", "Do you consent to take part?", ["yes", "no"])),
        Page("debrief", "# Thank you"),
        **screening,
    )


def _app(store: InMemoryStore, study: Study, gateway: Gateway) -> TestClient:
    return TestClient(build_study_app(study=study, store=store, gateway=gateway))


def _open(socket: Any) -> dict[str, Any]:
    """Read the handshake and the opening activity, and return the handshake."""
    handshake = cast("dict[str, Any]", socket.receive_json())
    assert handshake["type"] == "handshake_ack"
    assert socket.receive_json()["type"] == "delivery"
    return handshake


def _measure(socket: Any, **samples: int) -> dict[str, Any] | None:
    """Send one measurement and return the frame it answered, or None for silence.

    Silence is the usual answer, and a socket gives no way to wait for nothing. So a
    frame the transport always answers follows the measurement, and reaching it
    means the measurement said nothing.
    """
    socket.send_json({"type": "measurement", "samples": samples})
    socket.send_json({"type": "unknown_frame"})
    answer: dict[str, Any] | None = None
    for _ in range(4):
        frame = cast("dict[str, Any]", socket.receive_json())
        if frame.get("code") == "protocol.unsupported_frame":
            return answer
        answer = frame
        if frame.get("code") == "policy.excluded":
            # An exclusion closes the connection, so no further frame arrives.
            return answer
    raise AssertionError("the transport answered the probe frame with nothing")


def _visit_of(store: InMemoryStore) -> str:
    """Return the one visit the store holds."""
    found = [
        plan
        for aggregate_id, state in store.scan_aggregates()
        if aggregate_id.startswith("visitplan_")
        and (plan := plan_of(state)) is not None
    ]
    assert len(found) == 1
    return found[0].visit_id


# -- entry -----------------------------------------------------------------------


def test_a_study_that_screens_on_latency_refuses_entry_with_a_recorded_reason() -> None:
    """The proof: a poor connection is turned away, and the ledger says why."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    study = _study(screen=Screen(max_rtt_ms=200, warn_after=1, exclude_after=2))

    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        _open(socket)
        answer = _measure(socket, rtt=900_000)

    assert answer is not None
    assert answer["type"] == "error"
    assert answer["code"] == "policy.excluded"
    assert "connection" in answer["message"]

    visit_id = _visit_of(store)
    decision = read_decision(store, eligibility_id_for(gateway.derived_id, visit_id))
    assert decision is not None
    assert decision.admitted is False
    assert "rtt" in decision.reason


def test_a_good_connection_is_admitted_and_told_nothing() -> None:
    """A participant within the bound hears nothing at all about screening."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    study = _study(screen=Screen(max_rtt_ms=500))

    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        _open(socket)
        assert _measure(socket, rtt=40_000, hidden=0) is None

    decision = read_decision(
        store, eligibility_id_for(gateway.derived_id, _visit_of(store))
    )
    assert decision is not None
    assert decision.admitted is True


def test_the_studys_own_rule_refuses_with_its_own_reason() -> None:
    """An entry rule is the study's, so the participant reads the study's words."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)

    with _app(store, _study(admit=refuse_everyone), gateway).websocket_connect(
        "/ws"
    ) as socket:
        _open(socket)
        answer = _measure(socket, rtt=1_000)

    assert answer is not None
    assert answer["message"] == "this study has closed to new participants"


def test_a_rule_that_raises_refuses_by_default() -> None:
    """Fail-closed: a screen nobody can evaluate does not admit everybody."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)

    with _app(store, _study(admit=broken_rule), gateway).websocket_connect(
        "/ws"
    ) as socket:
        _open(socket)
        answer = _measure(socket, rtt=1_000)

    assert answer is not None
    assert answer["code"] == "policy.excluded"
    decision = read_decision(
        store, eligibility_id_for(gateway.derived_id, _visit_of(store))
    )
    assert decision is not None
    assert decision.reason == "the eligibility rule failed to run"


def test_a_fail_open_rule_that_raises_admits() -> None:
    """A study may ask for the other rule, and then it is the study's decision."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    study = _study(admit=broken_rule, screen=Screen(on_error="fail_open"))

    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        _open(socket)
        assert _measure(socket, rtt=1_000) is None


def test_the_declared_rule_reaches_the_visit_plan_by_name() -> None:
    """The plan says what this visit was screened by, not merely that it was."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)

    with _app(store, _study(admit=only_fast_browsers), gateway).websocket_connect(
        "/ws"
    ) as socket:
        _open(socket)

    plans = [
        plan
        for aggregate_id, state in store.scan_aggregates()
        if aggregate_id.startswith("visitplan_")
        and (plan := plan_of(state)) is not None
    ]
    assert plans[0].eligibility is not None
    declared = plans[0].eligibility[0]
    assert declared.callback.endswith(":only_fast_browsers")
    assert declared.on_error == "fail_closed"


# -- in play ---------------------------------------------------------------------


def test_a_participant_over_the_bound_is_warned_and_then_excluded() -> None:
    """The ladder: told first, ended second, and both recorded."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    study = _study(
        screen=Screen(max_rtt_ms=200, at_entry=False, warn_after=1, exclude_after=2)
    )

    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        _open(socket)
        warned = _measure(socket, rtt=900_000)
        excluded = _measure(socket, rtt=900_000)

    assert warned is not None
    assert warned["type"] == "screening"
    assert warned["action"] == "warn"
    assert excluded is not None
    assert excluded["code"] == "policy.excluded"

    interaction_id, actor_id = screening_ids(gateway.derived_id, _visit_of(store))
    state = read_screening(
        store, monitoring_id_for(gateway.derived_id, interaction_id, actor_id)
    )
    assert state is not None
    assert state.violations == 2
    assert state.action == "exclude"
    assert state.over == ["rtt"]


def test_an_exclusion_records_the_gate_op_that_blocks_advancing() -> None:
    """Excluding someone is blocking them, and the record says so in those terms."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    study = _study(
        screen=Screen(max_rtt_ms=200, at_entry=False, warn_after=1, exclude_after=2)
    )

    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        _open(socket)
        _measure(socket, rtt=900_000)
        _measure(socket, rtt=900_000)

    interaction_id, actor_id = screening_ids(gateway.derived_id, _visit_of(store))
    state = read_screening(
        store, monitoring_id_for(gateway.derived_id, interaction_id, actor_id)
    )
    assert state is not None
    assert state.gate is not None
    assert state.gate["target"] == "advance"
    assert state.gate["action"] == "block"
    assert state.gate["anchor"]["anchor_kind"] == "flow_node"


def test_the_measurement_is_kept_beside_the_decision_it_was_made_on() -> None:
    """A verdict with no evidence is an assertion; the record carries both."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    study = _study(
        screen=Screen(max_rtt_ms=200, at_entry=False, warn_after=1, exclude_after=9)
    )

    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        _open(socket)
        _measure(socket, rtt=900_000, hidden=0)

    interaction_id, actor_id = screening_ids(gateway.derived_id, _visit_of(store))
    state = read_screening(
        store, monitoring_id_for(gateway.derived_id, interaction_id, actor_id)
    )
    assert state is not None
    measurement = state.measurement
    assert measurement["schema"]["name"] == "mug.api-09.monitoring-measurement"
    assert measurement["seat_key"] == "player"
    assert {one["metric"] for one in measurement["measurements"]} == {"rtt", "hidden"}


def test_a_sample_the_server_can_not_read_is_dropped_rather_than_guessed() -> None:
    """An untrusted frame is untrusted: a bad number measures nothing."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    study = _study(screen=Screen(max_rtt_ms=200, at_entry=False, warn_after=1))

    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        _open(socket)
        socket.send_json({"type": "measurement", "samples": {"rtt": "very slow"}})
        assert _measure(socket, rtt=1_000) is None

    interaction_id, actor_id = screening_ids(gateway.derived_id, _visit_of(store))
    state = read_screening(
        store, monitoring_id_for(gateway.derived_id, interaction_id, actor_id)
    )
    assert state is not None
    assert state.violations == 0


# -- across connections ----------------------------------------------------------


def test_a_refusal_survives_a_reconnection() -> None:
    """Reloading the page is not a way to be judged again."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    study = _study(screen=Screen(max_rtt_ms=200, warn_after=1, exclude_after=2))
    client = _app(store, study, gateway)

    with client.websocket_connect("/ws") as socket:
        handshake = _open(socket)
        _measure(socket, rtt=900_000)
    token = handshake["resume_token"]

    with client.websocket_connect(f"/ws?resume_token={token}") as socket:
        frame = cast("dict[str, Any]", socket.receive_json())

    assert frame["type"] == "error"
    assert frame["code"] == "policy.excluded"


def test_a_violation_count_carries_across_a_reconnection() -> None:
    """A screen a refresh resets is not a screen."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    study = _study(
        screen=Screen(max_rtt_ms=200, at_entry=False, warn_after=1, exclude_after=2)
    )
    client = _app(store, study, gateway)

    with client.websocket_connect("/ws") as socket:
        handshake = _open(socket)
        assert (_measure(socket, rtt=900_000) or {}).get("action") == "warn"
    token = handshake["resume_token"]

    with client.websocket_connect(f"/ws?resume_token={token}") as socket:
        _open(socket)
        second = _measure(socket, rtt=900_000)

    assert second is not None
    assert second["code"] == "policy.excluded"


# -- a study that screens nothing -------------------------------------------------


def test_a_study_with_no_screen_asks_its_client_for_nothing() -> None:
    """The handshake is silent, so the client sends no sample at all."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)

    with _app(store, _study(), gateway).websocket_connect("/ws") as socket:
        handshake = _open(socket)

    assert "screening" not in handshake


def test_a_study_with_no_screen_records_nothing_when_a_client_measures() -> None:
    """A client that measures anyway costs the study no record and no refusal."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)

    with _app(store, _study(), gateway).websocket_connect("/ws") as socket:
        _open(socket)
        assert _measure(socket, rtt=9_000_000) is None

    visit_id = _visit_of(store)
    assert (
        read_decision(store, eligibility_id_for(gateway.derived_id, visit_id)) is None
    )
    interaction_id, actor_id = screening_ids(gateway.derived_id, visit_id)
    assert (
        read_screening(
            store, monitoring_id_for(gateway.derived_id, interaction_id, actor_id)
        )
        is None
    )


def test_a_screening_study_tells_its_client_how_often_to_measure() -> None:
    """The cadence is the server's to set, so a client can not sample itself out."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)
    study = _study(screen=Screen(sample_every_ms=3000))

    with _app(store, study, gateway).websocket_connect("/ws") as socket:
        handshake = _open(socket)

    assert handshake["screening"] == {"sample_every_ms": 3000}


def test_a_ping_is_answered_with_its_own_token() -> None:
    """The round trip a screen measures needs something to bounce off."""
    store = InMemoryStore()
    gateway = Gateway(secret=_SECRET)

    with _app(store, _study(), gateway).websocket_connect("/ws") as socket:
        _open(socket)
        socket.send_json({"type": "ping", "token": "abc123"})
        frame = cast("dict[str, Any]", socket.receive_json())

    assert frame == {"type": "pong", "token": "abc123"}
