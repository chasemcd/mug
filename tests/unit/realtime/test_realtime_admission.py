"""Admission bounds what the process accepts, and the transport answers refusals.

The first half drives ``mug.admission`` on its own with a hand-moved clock: the
token bucket, the session gate, the frame bound, and the delivery bound. The second
half drives the same bounds through ``serve_session`` over FastAPI's test client, so
each refusal is proven to reach a client as a safe error frame that names the wait
and, for a command, to be refused *before* it is dispatched -- a bound that still
does the work it refused is not a bound.

Every refusal reuses a contract error category (``backpressure``, ``rate_limit``,
``protocol``), which the HTTP edge already maps to a status, so nothing here invents
an error kind.

The frame bound was briefly derived from the study, because a browser-run game
reported in a single command is as large as the game is long. A run is reported in
parts now (``mug.game.capture_parts``), so the bound is a constant of the transport
again and the reporting cadence is what fits it.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from examples.mountain_car.browser_env import mountain_car_browser_spec
from mug.admission import (
    Admission,
    AdmissionPolicy,
    Refusal,
    SessionBudget,
    SessionOverloaded,
    TokenBucket,
    capture_frame_bytes,
)
from mug.app import build_demo_app
from mug.client import RealtimeCommand
from mug.game.capture_parts import FRAMES_PER_PART
from mug.gateway import Gateway
from mug.kernel import CommandReceipt, Digest, PrincipalRef, SchemaRef
from mug.realtime import Session, serve_session
from mug.storage import InMemoryStore

_PARTICIPANT = PrincipalRef(
    kind="participant", id="participant_019b6000-0000-7000-8000-0000000000aa"
)
_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


class _Clock:
    """A monotonic reader a test moves by hand, in seconds."""

    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _command_frame(command_id: str = "command_019b6000-0000-7000-8000-000000000001"):
    """Build one valid realtime command frame with a small payload."""
    command = RealtimeCommand(
        command_id=command_id,
        channel_key="demo.channel",
        intent_schema=SchemaRef(name="mug.demo.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        idempotency_key="idem_0123456789abcdefghijkA",
        submitted_at="2026-07-21T00:00:00.000000Z",
    )
    return {
        "type": "command",
        "command": command.model_dump(mode="json", exclude_none=True),
        "payload": {"note": "hello"},
    }


def _app(admission: Admission, dispatched: list[str]) -> TestClient:
    """Mount one bounded websocket route; the dispatch records what reached it."""
    app = FastAPI()

    def resolve(_websocket: WebSocket) -> PrincipalRef:
        return _PARTICIPANT

    async def dispatch(
        command: RealtimeCommand, _payload: object, _session: Session
    ) -> CommandReceipt | None:
        dispatched.append(command.command_id)
        return None

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:  # pyright: ignore[reportUnusedFunction]
        await serve_session(
            websocket,
            resolve_principal=resolve,
            dispatch=dispatch,
            protocol_version="0.1.0",
            admission=admission,
        )

    return TestClient(app)


# -- the bounds on their own ---------------------------------------------------


def test_the_bucket_allows_a_burst_then_states_the_wait() -> None:
    """A bucket spends its burst, then answers with how long to wait."""
    clock = _Clock()
    bucket = TokenBucket(rate_per_second=2.0, burst=3, now=clock)

    assert [bucket.take() for _ in range(3)] == [None, None, None]
    wait = bucket.take()
    assert wait is not None
    # Two per second, so the next token is half a second away.
    assert 400 <= wait <= 500


def test_the_bucket_refills_by_elapsed_time() -> None:
    """Waiting the stated time is enough; the bucket holds no timer."""
    clock = _Clock()
    bucket = TokenBucket(rate_per_second=2.0, burst=1, now=clock)
    assert bucket.take() is None
    assert bucket.take() is not None

    clock.advance(0.5)
    assert bucket.take() is None


def test_the_bucket_never_refills_past_its_burst() -> None:
    """A long quiet spell does not bank credit for a bigger burst later."""
    clock = _Clock()
    bucket = TokenBucket(rate_per_second=10.0, burst=2, now=clock)
    clock.advance(3600.0)

    assert [bucket.take() for _ in range(2)] == [None, None]
    assert bucket.take() is not None


def test_the_gate_refuses_a_connection_past_capacity() -> None:
    """A full process refuses the next connection with backpressure and a wait."""
    gate = Admission(AdmissionPolicy(max_sessions=1), now=_Clock())

    first = gate.admit()
    assert isinstance(first, SessionBudget)
    second = gate.admit()

    assert isinstance(second, Refusal)
    assert second.code == "transport.at_capacity"
    assert second.category == "backpressure"
    assert second.retry_after_ms == AdmissionPolicy().at_capacity_retry_after_ms
    # A refused connection took no place: it is the admitted one that holds it.
    assert gate.open_sessions == 1


def test_a_released_session_gives_its_place_back() -> None:
    """The place a session held is available to the next connection."""
    gate = Admission(AdmissionPolicy(max_sessions=1), now=_Clock())
    assert isinstance(gate.admit(), SessionBudget)

    gate.release()

    assert gate.open_sessions == 0
    assert isinstance(gate.admit(), SessionBudget)


def test_an_oversized_frame_is_refused_as_a_protocol_error() -> None:
    """A frame larger than any command needs is not admissible."""
    budget = SessionBudget(AdmissionPolicy(max_frame_bytes=16), now=_Clock())

    assert budget.check_frame(16) is None
    refusal = budget.check_frame(17)
    assert refusal is not None
    assert refusal.code == "transport.frame_too_large"
    assert refusal.category == "protocol"
    # Waiting does not make an oversized frame acceptable.
    assert refusal.retry_after_ms is None


def test_the_capture_bound_grows_with_the_run_it_has_to_hold() -> None:
    """A longer game is a larger report, and the bound follows it.

    The frame bound is otherwise a guess, and a guess refuses the run at the end,
    after the participant has played the whole game.
    """
    assert capture_frame_bytes(600) > capture_frame_bytes(200)
    assert capture_frame_bytes(600) - capture_frame_bytes(200) == 400 * 1024
    # A game of no length still has a report: the envelope and the boundary.
    assert capture_frame_bytes(0) > 0


def test_the_frame_bound_is_a_constant_again() -> None:
    """A run is reported in parts now, so the bound stops being a study's business.

    It was briefly derived from how long the longest browser game ran, because a
    whole run reported in one command is as large as the game is long. Reporting in
    parts puts the size back under the transport's own control, which is where a
    transport bound belongs -- ``FRAMES_PER_PART`` is chosen to fit it, and
    ``tests/unit/game/test_capture_parts.py`` holds it to that.
    """
    spec = mountain_car_browser_spec()
    default = AdmissionPolicy().max_frame_bytes

    served = build_demo_app(
        store=InMemoryStore(), gateway=Gateway(), browser_game=spec
    )

    assert served.state.admission.policy.max_frame_bytes == default
    assert capture_frame_bytes(FRAMES_PER_PART) <= default


def test_a_session_refuses_to_queue_deliveries_without_a_limit() -> None:
    """A runaway queue raises rather than grow; the bound is the session's budget."""
    session = Session(_PARTICIPANT, max_pending_deliveries=2)
    session.deliver({"kind": "one"})
    session.deliver({"kind": "two"})

    with pytest.raises(SessionOverloaded):
        session.deliver({"kind": "three"})


def test_an_unbounded_session_queues_freely() -> None:
    """With no budget the queue is unbounded, which is what a test wants."""
    session = Session(_PARTICIPANT)
    for index in range(1000):
        session.deliver({"kind": index})

    assert len(session.outbox) == 1000


# -- the bounds through the transport ------------------------------------------


def test_a_connection_past_capacity_is_refused_before_the_handshake() -> None:
    """A full process answers a safe error and never opens a session."""
    gate = Admission(AdmissionPolicy(max_sessions=0), now=_Clock())
    dispatched: list[str] = []

    with _app(gate, dispatched).websocket_connect("/ws") as socket:
        message = socket.receive_json()

    assert message["type"] == "error"
    assert message["code"] == "transport.at_capacity"
    assert message["category"] == "backpressure"
    assert message["retry_after_ms"] == AdmissionPolicy().at_capacity_retry_after_ms


def test_an_over_rate_command_is_refused_and_never_dispatched() -> None:
    """A command over the rate answers a wait, and does not reach the handler.

    This is what makes the refusal safe to retry: the command had no effect, so the
    client resends the same one after the stated wait rather than mint another.
    """
    clock = _Clock()
    gate = Admission(
        AdmissionPolicy(max_commands_per_second=1.0, command_burst=1), now=clock
    )
    dispatched: list[str] = []
    second = "command_019b6000-0000-7000-8000-000000000002"

    with _app(gate, dispatched).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.send_json(_command_frame())
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["code"] == "command.unsupported"
        socket.send_json(_command_frame(second))
        refused = socket.receive_json()

    assert refused["type"] == "error"
    assert refused["code"] == "transport.rate_limited"
    assert refused["category"] == "rate_limit"
    assert refused["retry_after_ms"] >= 1
    # It names the command it refused, so a client can match it to its own frame.
    assert refused["command_id"] == second
    # Only the first command was ever dispatched.
    assert dispatched == ["command_019b6000-0000-7000-8000-000000000001"]


def test_waiting_the_stated_time_admits_the_next_command() -> None:
    """The wait a refusal states is the wait that works."""
    clock = _Clock()
    gate = Admission(
        AdmissionPolicy(max_commands_per_second=1.0, command_burst=1), now=clock
    )
    dispatched: list[str] = []
    second = "command_019b6000-0000-7000-8000-000000000002"

    with _app(gate, dispatched).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.send_json(_command_frame())
        socket.receive_json()
        socket.receive_json()
        clock.advance(1.0)
        socket.send_json(_command_frame(second))
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"

    assert dispatched == ["command_019b6000-0000-7000-8000-000000000001", second]


def test_an_oversized_frame_is_refused_and_the_session_survives() -> None:
    """An oversized frame is refused unparsed; the connection stays usable."""
    gate = Admission(AdmissionPolicy(max_frame_bytes=1024), now=_Clock())
    dispatched: list[str] = []

    with _app(gate, dispatched).websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        socket.send_json({"type": "command", "command": {"pad": "x" * 2000}})
        refused = socket.receive_json()
        # The same connection then serves a frame within the bound.
        socket.send_json(_command_frame())
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"

    assert refused["code"] == "transport.frame_too_large"
    assert refused["category"] == "protocol"
    # The oversized frame never reached the parser, so it never reached a handler.
    assert dispatched == ["command_019b6000-0000-7000-8000-000000000001"]


def test_a_closed_session_returns_its_place_to_the_process() -> None:
    """However a session ends, the process gets its capacity back."""
    gate = Admission(AdmissionPolicy(max_sessions=1), now=_Clock())
    dispatched: list[str] = []
    client = _app(gate, dispatched)

    for _ in range(3):
        with client.websocket_connect("/ws") as socket:
            assert socket.receive_json()["type"] == "handshake_ack"
        assert gate.open_sessions == 0
