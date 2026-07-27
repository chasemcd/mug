"""A running process reports what it served: counts, traces, probes, and lines.

The first half drives ``mug.observability`` on its own -- the sinks, the series
bound, the Prometheus rendering, and the trace-context reader. The second half drives
a built application: the edge answers with a trace and counts what it served, the
realtime transport reports the open-session level and what it refused, and the three
operator endpoints answer what a supervisor and a load balancer read.

One property is asserted throughout: nothing observable names a participant. The
series are labelled by command, outcome, and error category only, so scraping this
process cannot leak who was in the study.
"""

from __future__ import annotations

import json
import logging
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from mug.admission import AdmissionPolicy
from mug.app import build_demo_app
from mug.gateway import Gateway
from mug.observability import (
    InMemoryTelemetry,
    NullTelemetry,
    log_line,
    parse_traceparent,
    trace_id,
)

_TRACE = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


# -- the sinks -----------------------------------------------------------------


def test_the_null_sink_accepts_everything_and_keeps_nothing() -> None:
    """The default sink is a no-op, so an uninstrumented run pays nothing."""
    sink = NullTelemetry()

    assert sink.count("mug_test_total", outcome="ok") is None
    assert sink.gauge("mug_test_level", 1.0) is None
    assert sink.observe("mug_test_ms", 12.0) is None


def test_counters_gauges_and_observations_are_kept_apart() -> None:
    """Each kind of series answers the question it is for."""
    sink = InMemoryTelemetry()
    sink.count("mug_edge_commands_total", outcome="accepted")
    sink.count("mug_edge_commands_total", outcome="accepted")
    sink.count("mug_edge_commands_total", outcome="rejected")
    sink.gauge("mug_realtime_open_sessions", 3)
    sink.observe("mug_command_ms", 10.0)
    sink.observe("mug_command_ms", 20.0)

    snapshot = sink.snapshot()

    assert snapshot["counters"] == {
        'mug_edge_commands_total{outcome="accepted"}': 2.0,
        'mug_edge_commands_total{outcome="rejected"}': 1.0,
    }
    assert snapshot["gauges"] == {"mug_realtime_open_sessions": 3}
    # An observation keeps a count and a sum, which is a mean and nothing per event.
    assert snapshot["observations"] == {"mug_command_ms": {"count": 2, "sum": 30.0}}


def test_the_series_bound_drops_rather_than_grow_and_says_so() -> None:
    """A call site that labels without a limit cannot consume the process."""
    sink = InMemoryTelemetry(max_series=2)
    for index in range(10):
        sink.count("mug_test_total", label=str(index))

    snapshot = sink.snapshot()

    assert len(snapshot["counters"]) == 2
    # The gap is counted, so a dropped series is visible rather than silent.
    assert snapshot["dropped_series"] == 8


def test_a_known_series_keeps_counting_past_the_bound() -> None:
    """The bound stops new series, not the ones already being reported."""
    sink = InMemoryTelemetry(max_series=1)
    sink.count("mug_test_total", outcome="ok")
    sink.count("mug_test_total", outcome="other")
    sink.count("mug_test_total", outcome="ok")

    assert sink.snapshot()["counters"] == {'mug_test_total{outcome="ok"}': 2.0}


def test_the_rendering_is_the_prometheus_text_format() -> None:
    """An operator scrapes this process with a standard collector and no library."""
    sink = InMemoryTelemetry()
    sink.count("mug_edge_commands_total", command="visit.start", outcome="accepted")
    sink.gauge("mug_realtime_open_sessions", 2)
    sink.observe("mug_command_ms", 5.0)

    lines = sink.render_prometheus().splitlines()

    served = 'mug_edge_commands_total{command="visit.start",outcome="accepted"} 1'
    assert served in lines
    assert "mug_realtime_open_sessions 2" in lines
    assert "mug_command_ms_count 1" in lines
    assert "mug_command_ms_sum 5" in lines


# -- the trace context ---------------------------------------------------------


def test_a_valid_traceparent_is_read_and_its_trace_id_extracted() -> None:
    """The caller's trace is adopted, so one request is one trace end to end."""
    trace = parse_traceparent(_TRACE)

    assert trace is not None
    assert trace_id(trace) == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_an_unusable_traceparent_is_ignored_rather_than_refused() -> None:
    """A bad header is a bad debugging aid, never a refused request."""
    assert parse_traceparent(None) is None
    assert parse_traceparent("nonsense") is None
    # An all-zero trace identifier is not a trace, per the contract's own rule.
    assert parse_traceparent("00-" + "0" * 32 + "-00f067aa0ba902b7-01") is None


def test_a_minted_trace_is_well_formed_for_any_entropy_source() -> None:
    """Minting a trace can never raise inside a request, whatever the entropy."""
    zeros = Gateway(entropy=lambda size: bytes(size))

    trace = zeros.new_trace()

    assert parse_traceparent(trace.traceparent) is not None
    assert trace_id(trace) is not None


def test_a_log_line_is_one_json_object(caplog: pytest.LogCaptureFixture) -> None:
    """One object per line is what a log reader can query; a sentence is not."""
    with caplog.at_level(logging.INFO, logger="mug"):
        log_line("edge.command", command="visit.start", outcome="accepted")

    payload = json.loads(caplog.records[-1].getMessage())
    assert payload == {
        "event": "edge.command",
        "command": "visit.start",
        "outcome": "accepted",
    }


# -- the running application ---------------------------------------------------


def _client(**config: object) -> tuple[TestClient, InMemoryTelemetry]:
    """Build the demo application and return its client and its telemetry sink."""
    app = build_demo_app(**config)
    sink: InMemoryTelemetry = app.state.telemetry
    return TestClient(app), sink


def _http(**config: object) -> tuple[httpx.Client, InMemoryTelemetry]:
    # starlette's TestClient is an httpx.Client; the base type is fully typed.
    client, sink = _client(**config)
    return client, sink


def test_the_edge_answers_with_the_caller_s_trace() -> None:
    """A caller that traces its request reads the same trace back."""
    client, _ = _http()

    answer = client.post(
        "/commands/visit.start", json={}, headers={"traceparent": _TRACE}
    )

    assert answer.headers["traceparent"] == _TRACE


def test_the_edge_mints_a_trace_when_the_caller_sends_none() -> None:
    """Every request is traceable, whether or not the caller started one."""
    client, _ = _http()

    answer = client.post("/commands/visit.start", json={})

    assert parse_traceparent(answer.headers["traceparent"]) is not None


def test_the_edge_counts_what_it_served_by_outcome() -> None:
    """A command that does not validate is counted as the rejection it was."""
    client, sink = _http()

    client.post("/commands/visit.start", json={})
    client.post("/commands/nonsense", json={})

    counters = sink.snapshot()["counters"]
    assert (
        'mug_edge_commands_total{category="validation",command="visit.start",'
        'outcome="rejected"}' in counters
    )
    assert (
        'mug_edge_commands_total{category="not_found",command="nonsense",'
        'outcome="rejected"}' in counters
    )


def test_the_transport_reports_the_open_session_level() -> None:
    """The level rises while a participant is connected and falls when they go."""
    client, sink = _client()

    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        during = sink.snapshot()["gauges"]["mug_realtime_open_sessions"]

    after = sink.snapshot()["gauges"]["mug_realtime_open_sessions"]
    assert during == 1
    assert after == 0


def test_the_transport_counts_a_refusal_by_its_category() -> None:
    """A process at its bound says so in the count, not only to the client."""
    client, sink = _client(admission=AdmissionPolicy(max_sessions=0))

    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["code"] == "transport.at_capacity"

    counters = sink.snapshot()["counters"]
    assert counters['mug_realtime_refused_total{category="backpressure"}'] == 1.0


def test_health_is_alive_and_readiness_is_capacity() -> None:
    """A full process is alive but not ready, which is the whole point of two."""
    client, _ = _http(admission=AdmissionPolicy(max_sessions=0))

    assert client.get("/healthz").status_code == 200
    readiness = client.get("/readyz")

    assert readiness.status_code == 503
    assert readiness.json() == {
        "ready": False,
        "open_sessions": 0,
        "max_sessions": 0,
    }


def test_a_process_with_room_is_ready() -> None:
    """A process below its bound asks for more participants."""
    client, _ = _http()

    readiness = client.get("/readyz")

    assert readiness.status_code == 200
    assert readiness.json()["ready"] is True


def test_metrics_render_for_a_scrape_and_name_no_participant() -> None:
    """The scrape carries the process's counts and nothing about who was in it."""
    client, _ = _client()
    with client.websocket_connect("/ws") as socket:
        subject = socket.receive_json()["subject"]

    body = cast("httpx.Client", client).get("/metrics").text

    assert "mug_realtime_open_sessions" in body
    assert body.endswith("\n")
    # The one identifier the session did produce is nowhere in the scrape.
    assert subject not in body
