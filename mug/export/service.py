"""Export one visit's canonical lineage as schema-bound JSONL.

The single export format is newline-delimited JSON (D13-1): one canonical event
per line, in stream order. A visit's lineage lives on its flow stream (the form
answers and pointer advances) and on any episode stream a runtime captured (the
transition per frame and the closing boundary). This service reads the flow
aggregate to discover those streams, reads each stream's canonical events, and
serializes them, so the export carries the visit's complete, ordered provenance:
stream position, producer position, event schema, payload digest, recorded time,
and data-handling label per event.

The export carries digests, never raw observations or answer values, so no
participant payload and no secret material leaves through it.
"""

from __future__ import annotations

import json
from typing import NamedTuple

from mug.content import FlowState
from mug.runtime import read_ledger
from mug.storage import Store


def _stream_of(aggregate_id: str) -> str:
    """Return the event stream that shares an aggregate's identifier body."""
    return "stream_" + aggregate_id.split("_", 1)[1]


class VisitExport(NamedTuple):
    """One visit's export: the source streams, the event count, and the JSONL."""

    flow_id: str
    visit_id: str
    stream_ids: list[str]
    event_count: int
    jsonl: str


def export_visit(store: Store, flow_id: str) -> VisitExport:
    """Export the visit's flow and episode streams as one JSONL document.

    ``flow_id`` is the visit's flow aggregate. A missing flow raises
    ``LookupError``, so a caller answers a not-found rather than an empty export.
    """
    raw = store.load_aggregate(flow_id)
    if raw is None:
        raise LookupError(f"no flow for {flow_id}")
    state = FlowState.model_validate(raw)
    stream_ids = [_stream_of(state.visitplan_id), *state.captured_streams]

    lines: list[str] = []
    for stream_id in stream_ids:
        for event in read_ledger(store, stream_id):
            lines.append(
                json.dumps(
                    event.model_dump(mode="json", exclude_none=True),
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
    jsonl = "".join(f"{line}\n" for line in lines)
    return VisitExport(
        flow_id=flow_id,
        visit_id=state.visit_id,
        stream_ids=stream_ids,
        event_count=len(lines),
        jsonl=jsonl,
    )


__all__ = ["VisitExport", "export_visit"]
