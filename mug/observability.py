"""What a running process tells an operator: counts, traces, and log lines.

A study that runs unattended fails in ways its tests never show: one command type
starts to reject, the process fills with sessions and refuses at the door, a worker
stops finishing jobs. Each of those is visible from the outside only if the process
says so. This module is what it says with.

It adds no dependency, and it keeps three surfaces apart:

- **Counts.** ``Telemetry`` is a three-method sink -- a counter, a gauge, and an
  observation. Every call site takes one, and the default does nothing, so
  instrumenting a path costs it no branch and no import of an agent. The bundled
  ``InMemoryTelemetry`` keeps the series in the process and renders them in the
  Prometheus text format, which an operator can scrape with nothing installed.
- **Traces.** The shared kernel already models a W3C ``TraceContext``. An ingress
  adapter reads the caller's ``traceparent``, and answers with it, so one request
  across the edge, a study's own proxy, and the browser is one trace. A trace is
  never persisted: no canonical event has a field for it, and inventing one would
  change a frozen contract for a debugging aid.
- **Log lines.** ``log_line`` writes one JSON object per line to the standard
  logging module. One object per line is what a log reader can query; a sentence is
  not.

Labels are deliberately a closed, small set at each call site -- an outcome, an error
category, a command name. Nothing here labels a series with a participant, a
principal, or an identifier: that would both leak and grow the series count without
a limit.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol

from mug.kernel.refs import TraceContext

_LOGGER_NAME = "mug"

# A series name and its sorted labels together identify one series.
_Series = tuple[str, tuple[tuple[str, str], ...]]


class Telemetry(Protocol):
    """The sink a call site reports to. Three verbs, and none of them can fail.

    A telemetry call must never raise and never block: it sits inside a request, a
    frame loop, and a worker claim, and a process must not fail because its
    reporting did.
    """

    def count(self, name: str, /, **labels: str) -> None:
        """Add one to a counter -- something happened."""
        ...

    def gauge(self, name: str, value: float, /, **labels: str) -> None:
        """Set a gauge -- something is currently true of the process."""
        ...

    def observe(self, name: str, value: float, /, **labels: str) -> None:
        """Record one measurement -- how long, or how many, this one time."""
        ...


class NullTelemetry:
    """A sink that discards everything: the default, so nothing has to check.

    A call site takes a ``Telemetry`` and reports unconditionally. Making the
    do-nothing case an object rather than a None check keeps the instrumented path
    the same shape as the uninstrumented one.
    """

    def count(self, name: str, /, **labels: str) -> None:
        return None

    def gauge(self, name: str, value: float, /, **labels: str) -> None:
        return None

    def observe(self, name: str, value: float, /, **labels: str) -> None:
        return None


class InMemoryTelemetry:
    """Keep the series in the process, and render them for a scrape.

    This is the sink a deployment gets by default. It holds counters, gauges, and a
    running count-and-sum per observed series -- enough for a rate, a level, and a
    mean -- and nothing per event, so its memory is bounded by the number of series
    and not by traffic.

    ``max_series`` is the backstop against a call site that labels a series with
    something unbounded: past it, new series are dropped rather than allowed to
    consume the process. The drop is itself counted, so the gap is visible instead of
    silent.
    """

    def __init__(self, *, max_series: int = 4096) -> None:
        self._max_series = max_series
        self._counters: dict[_Series, float] = {}
        self._gauges: dict[_Series, float] = {}
        self._observations: dict[_Series, tuple[int, float]] = {}
        self._dropped = 0

    def count(self, name: str, /, **labels: str) -> None:
        key = _key(name, labels)
        if key in self._counters or self._room():
            self._counters[key] = self._counters.get(key, 0.0) + 1.0

    def gauge(self, name: str, value: float, /, **labels: str) -> None:
        key = _key(name, labels)
        if key in self._gauges or self._room():
            self._gauges[key] = value

    def observe(self, name: str, value: float, /, **labels: str) -> None:
        key = _key(name, labels)
        if key not in self._observations and not self._room():
            return
        seen, total = self._observations.get(key, (0, 0.0))
        self._observations[key] = (seen + 1, total + value)

    def snapshot(self) -> dict[str, Any]:
        """Return the current series as plain data: counters, gauges, observations."""
        return {
            "counters": {
                _render_key(key): value for key, value in self._counters.items()
            },
            "gauges": {_render_key(key): value for key, value in self._gauges.items()},
            "observations": {
                _render_key(key): {"count": seen, "sum": total}
                for key, (seen, total) in self._observations.items()
            },
            "dropped_series": self._dropped,
        }

    def render_prometheus(self) -> str:
        """Render the series in the Prometheus text exposition format.

        The format is a line per series, so an operator scrapes this process with a
        standard collector and no library here. An observed series renders as the
        ``_count`` and ``_sum`` pair a mean is taken from.
        """
        lines: list[str] = []
        for key, value in sorted(self._counters.items()):
            lines.append(f"{_render_key(key)} {_number(value)}")
        for key, value in sorted(self._gauges.items()):
            lines.append(f"{_render_key(key)} {_number(value)}")
        for key, (seen, total) in sorted(self._observations.items()):
            name, labels = key
            lines.append(f"{_render_key((name + '_count', labels))} {seen}")
            lines.append(f"{_render_key((name + '_sum', labels))} {_number(total)}")
        lines.append(f"mug_telemetry_dropped_series {self._dropped}")
        return "\n".join(lines) + "\n"

    def _room(self) -> bool:
        """Return whether one more series fits, counting the drop when it does not."""
        if self._series_count() < self._max_series:
            return True
        self._dropped += 1
        return False

    def _series_count(self) -> int:
        return len(self._counters) + len(self._gauges) + len(self._observations)


def _key(name: str, labels: Mapping[str, str]) -> _Series:
    """Build the identity of one series: its name and its sorted labels."""
    return name, tuple(sorted(labels.items()))


def _render_key(key: _Series) -> str:
    """Render one series identity in the Prometheus name-and-labels form."""
    name, labels = key
    if not labels:
        return name
    rendered = ",".join(f'{label}="{_escape(value)}"' for label, value in labels)
    return f"{name}{{{rendered}}}"


def _escape(value: str) -> str:
    """Escape a label value for the text exposition format."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _number(value: float) -> str:
    """Render a number without a trailing ``.0`` for a whole count."""
    return str(int(value)) if value == int(value) else repr(value)


def parse_traceparent(value: str | None) -> TraceContext | None:
    """Return the caller's trace context, or None when there is nothing usable.

    A trace context is a debugging aid a caller supplies, so a malformed one is
    ignored rather than refused: a bad header must not cost a participant their
    session. The kernel model is the validator, so what this accepts is exactly what
    the contract says a trace context is.
    """
    if value is None:
        return None
    try:
        return TraceContext(traceparent=value)
    except ValueError:
        return None


def trace_id(trace: TraceContext | None) -> str | None:
    """Return the 32-character trace identifier of a trace context, if there is one.

    It is the field a log reader joins on, and it is safe to log: it identifies a
    request, never a person.
    """
    return None if trace is None else trace.traceparent[3:35]


def log_line(event: str, /, level: int = logging.INFO, **fields: Any) -> None:
    """Write one structured log line: a JSON object with an event name.

    Fields must be safe to keep: an identifier the platform minted, a category, a
    count. Never a payload, a credential, a provider trace, or a participant's input
    -- the same rule the transports follow for an error message.
    """
    logging.getLogger(_LOGGER_NAME).log(
        level, json.dumps({"event": event, **fields}, sort_keys=True, default=str)
    )


__all__ = [
    "InMemoryTelemetry",
    "NullTelemetry",
    "Telemetry",
    "log_line",
    "parse_traceparent",
    "trace_id",
]
