"""The full dataset export across a study's whole ledger (API-19 runtime).

The demo export (``export_visit``) serializes ONE visit's streams. This module
generalizes it to the full dataset: every canonical event a study recorded,
grouped by dataset kind -- ``events``, ``trajectories``, ``preferences``,
``conversations`` -- each kind a newline-delimited-JSON artifact with an
``ExportBundle`` that names its rows and a ``LineageRecord`` that states its
origin.

The export carries only canonical event envelopes: stream position, producer
position, event schema, payload digest, recorded time, and data-handling label.
It never carries a raw observation, an answer value, or secret material, so no
participant payload leaves through it. One row IS one ``mug.api-10.event-envelope``,
so the row schema names that envelope.

Reproducibility is the definition of done for API-19. The row order is
deterministic -- by source stream id, then by the position the store assigned --
and every id and timestamp is injected, so the same ledger and the same injected
ids produce byte-identical artifacts and identical digests.

An event belongs to ``events`` (the universal spine) always, and ALSO to one
semantic kind when its event schema is in that kind's family. A kind with no
event yields no bundle, so a study without conversations exports no conversation
bundle rather than an empty one.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Final, NamedTuple, cast

from mug.events import EventEnvelope
from mug.export.types import (
    DatasetSchemaBinding,
    ExportBundle,
    GitProvenanceRef,
    LineageRecord,
)
from mug.kernel import ArtifactRef, DataHandlingRef, SchemaRef
from mug.kernel.refs import StudyVersionRef
from mug.runtime import read_ledger
from mug.storage import ArtifactStaging, ArtifactStore, Store, digest_of

# The four dataset kinds API-19 names, in a stable order.
DATASET_KINDS: Final[tuple[str, ...]] = (
    "events",
    "trajectories",
    "preferences",
    "conversations",
)

# A canonical event's semantic dataset kind, keyed by its event-schema family.
# Every event belongs to `events`; an event whose schema is in one of these
# families ALSO belongs to the named kind.
_SEMANTIC_KIND_BY_FAMILY: Final[Mapping[str, str]] = {
    "mug.api-07.": "trajectories",  # game transitions and episode boundaries
    "mug.api-18.": "preferences",  # preference assignments, responses, quality
    "mug.api-08.": "conversations",  # chat messages and delivery
}

def _envelope_row_schema() -> SchemaRef:
    """Return the event-envelope schema ref without a full envelope instance."""
    factory = EventEnvelope.model_fields["schema"].default_factory
    assert factory is not None  # the envelope always pins its schema
    return cast("SchemaRef", factory())  # pyright: ignore[reportCallIssue]


# Every export row is a canonical event envelope; the row schema names it.
_ROW_SCHEMA: Final[SchemaRef] = _envelope_row_schema()
_RESEARCH: Final[DataHandlingRef] = DataHandlingRef(privacy_labels=["research"])
_NDJSON: Final[str] = "application/x-ndjson"


def dataset_kinds_of(event: EventEnvelope) -> tuple[str, ...]:
    """Return the dataset kinds one event belongs to, ``events`` first."""
    name = event.event_schema.name
    for family, kind in _SEMANTIC_KIND_BY_FAMILY.items():
        if name.startswith(family):
            return ("events", kind)
    return ("events",)


def dataset_schema_bindings() -> list[DatasetSchemaBinding]:
    """Return the row-schema binding for every dataset kind.

    Each kind's rows are canonical event envelopes, so every binding names the
    same envelope row schema. The bindings document the export shape for a
    researcher without opening an artifact.
    """
    return [
        DatasetSchemaBinding(dataset_kind=kind, row_schema=_ROW_SCHEMA)
        for kind in DATASET_KINDS
    ]


def _stream_of(aggregate_id: str) -> str:
    """Return the event stream that shares an aggregate's identifier body."""
    return "stream_" + aggregate_id.split("_", 1)[1]


def discover_streams(store: Store) -> list[str]:
    """Return every distinct event stream in the store, in a stable order."""
    seen = {_stream_of(aggregate_id) for aggregate_id, _ in store.scan_aggregates()}
    return sorted(seen)


class GroupedRows(NamedTuple):
    """One dataset kind's rows and the source streams that produced them."""

    rows: list[dict[str, object]]
    source_stream_ids: list[str]


def collect_dataset_rows(store: Store) -> dict[str, GroupedRows]:
    """Read the whole ledger once and group canonical events by dataset kind.

    Rows keep the store's per-stream order; across streams they follow the
    sorted stream id, so the grouping is reproducible from the ledger alone.
    """
    rows: dict[str, list[dict[str, object]]] = {kind: [] for kind in DATASET_KINDS}
    streams: dict[str, set[str]] = {kind: set() for kind in DATASET_KINDS}
    for stream_id in discover_streams(store):
        for event in read_ledger(store, stream_id):
            payload = event.model_dump(mode="json", exclude_none=True)
            for kind in dataset_kinds_of(event):
                rows[kind].append(payload)
                streams[kind].add(stream_id)
    return {
        kind: GroupedRows(rows[kind], sorted(streams[kind])) for kind in DATASET_KINDS
    }


def _ndjson(rows: Sequence[Mapping[str, object]]) -> bytes:
    """Serialize rows to newline-delimited JSON with sorted keys (D13-1)."""
    lines = [
        json.dumps(row, separators=(",", ":"), sort_keys=True) for row in rows
    ]
    return "".join(f"{line}\n" for line in lines).encode("utf-8")


def _json_bytes(obj: object) -> bytes:
    """Serialize one object to canonical, sorted-key JSON bytes."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")


async def _stage_ndjson(
    artifacts: ArtifactStore,
    *,
    data: bytes,
    new_artifact_id: Callable[[], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
    data_handling: DataHandlingRef,
) -> ArtifactRef:
    """Stage one ndjson blob against its own digest and finalize it."""
    staging = ArtifactStaging(
        upload_id=new_upload_id(),
        intended_digest=digest_of(data),
        size_bytes=len(data),
        media_type=_NDJSON,
        data_handling=data_handling,
    )
    finalized = await artifacts.finalize_artifact(
        staging, data, artifact_id=new_artifact_id(), finalized_at=now()
    )
    return finalized.artifact


async def build_dataset_export(
    *,
    kind: str,
    rows: Sequence[Mapping[str, object]],
    source_stream_ids: Sequence[str],
    export_key: str,
    study_version: StudyVersionRef,
    git_provenance: GitProvenanceRef,
    artifacts: ArtifactStore,
    new_artifact_id: Callable[[], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
    data_handling: DataHandlingRef = _RESEARCH,
) -> tuple[ExportBundle, LineageRecord]:
    """Build one dataset kind's ``ExportBundle`` and its ``LineageRecord``.

    The rows serialize to one ndjson artifact staged against its own digest. The
    lineage names the source streams the rows came from; the bundle digest binds
    the artifact, row count, lineage, and snapshot together, so the same ledger
    and the same injected ids reproduce the same bundle exactly.
    """
    data = _ndjson(rows)
    artifact = await _stage_ndjson(
        artifacts,
        data=data,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
        data_handling=data_handling,
    )
    lineage = LineageRecord(
        export_key=export_key,
        study_version=study_version,
        git_provenance=git_provenance,
        source_stream_ids=list(source_stream_ids),
        source_artifact_ids=[],
        transformation="none",
    )
    lineage_digest = digest_of(
        _json_bytes(lineage.model_dump(mode="json", exclude_none=True))
    )
    snapshot_at = now()
    bundle_digest = digest_of(
        _json_bytes(
            {
                "artifact": artifact.digest.hex,
                "dataset_kind": kind,
                "export_key": export_key,
                "lineage_digest": lineage_digest.hex,
                "row_count": len(rows),
                "snapshot_at": snapshot_at,
                "study_version_id": study_version.study_version_id,
            }
        )
    )
    bundle = ExportBundle(
        export_key=export_key,
        study_version=study_version,
        dataset_kind=kind,  # pyright: ignore[reportArgumentType]
        artifact=artifact,
        row_count=len(rows),
        row_schema=_ROW_SCHEMA,
        lineage_digest=lineage_digest,
        completeness="complete",
        snapshot_at=snapshot_at,
        bundle_digest=bundle_digest,
        data_handling=data_handling,
    )
    return bundle, lineage


class DatasetExport(NamedTuple):
    """A study's full dataset export: the bundles, lineage, and row bindings."""

    bundles: list[ExportBundle]
    lineage: list[LineageRecord]
    bindings: list[DatasetSchemaBinding]


async def export_study_dataset(
    *,
    store: Store,
    artifacts: ArtifactStore,
    study_version: StudyVersionRef,
    git_provenance: GitProvenanceRef,
    new_artifact_id: Callable[[], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
    kinds: Sequence[str] = DATASET_KINDS,
    export_key: str = "dataset",
    data_handling: DataHandlingRef = _RESEARCH,
) -> DatasetExport:
    """Export a study's whole ledger as one bundle per non-empty dataset kind.

    Reads the ledger once, groups the canonical events by kind, and produces an
    ``ExportBundle`` and ``LineageRecord`` for each requested kind that has at
    least one event. A kind with no event yields no bundle (a lineage record
    must name a source), so a study without conversations exports no
    conversation bundle. The result also carries the row-schema binding for the
    exported kinds, so the dataset is self-describing.
    """
    grouped = collect_dataset_rows(store)
    bundles: list[ExportBundle] = []
    lineage: list[LineageRecord] = []
    exported_kinds: list[str] = []
    for kind in kinds:
        group = grouped[kind]
        if not group.rows:
            continue
        bundle, record = await build_dataset_export(
            kind=kind,
            rows=group.rows,
            source_stream_ids=group.source_stream_ids,
            export_key=f"{export_key}-{kind}",
            study_version=study_version,
            git_provenance=git_provenance,
            artifacts=artifacts,
            new_artifact_id=new_artifact_id,
            new_upload_id=new_upload_id,
            now=now,
            data_handling=data_handling,
        )
        bundles.append(bundle)
        lineage.append(record)
        exported_kinds.append(kind)
    bindings = [
        DatasetSchemaBinding(dataset_kind=kind, row_schema=_ROW_SCHEMA)  # pyright: ignore[reportArgumentType]
        for kind in exported_kinds
    ]
    return DatasetExport(bundles=bundles, lineage=lineage, bindings=bindings)


__all__ = [
    "DATASET_KINDS",
    "DatasetExport",
    "GroupedRows",
    "build_dataset_export",
    "collect_dataset_rows",
    "dataset_kinds_of",
    "dataset_schema_bindings",
    "discover_streams",
    "export_study_dataset",
]
