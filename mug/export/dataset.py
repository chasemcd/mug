"""The full dataset export across a study's whole ledger (API-19 runtime).

The demo export (``export_visit``) serializes ONE visit's streams. This module
generalizes it to the full dataset: every canonical event a study recorded,
grouped by dataset kind -- ``events``, ``trajectories``, ``preferences``,
``conversations`` -- each kind a newline-delimited-JSON artifact with an
``ExportBundle`` that names its rows and a ``LineageRecord`` that states its
origin.

An export bundle carries only canonical event envelopes: stream position, producer
position, event schema, payload digest, recorded time, and data-handling label. One
row IS one ``mug.api-10.event-envelope``, so the row schema names that envelope.

A spine of digests is not yet a dataset, so each research kind also gets a values
artifact: what its aggregates committed, bound to the bundle rows by digest
(``collect_dataset_values``). That is where the research answers are -- which run a
participant preferred, how an episode ended -- and it is a separate artifact, so the
row contract stays exactly as frozen. No raw observation and no secret material
leaves through either: an observation lives in the episode's own trajectory artifact
and a secret is never committed as state.

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
from mug.export.preferences import PREFERENCE_PAIRS, collect_preference_rows
from mug.export.types import (
    DatasetSchemaBinding,
    ExportBundle,
    ExportRequest,
    GitProvenanceRef,
    LineageRecord,
)
from mug.kernel import ArtifactRef, DataHandlingRef, SchemaRef, compute_digest
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

# Dataset kinds that get a values artifact but no bundle. The frozen API-19
# ``DatasetKind`` enum names exactly four kinds and ``forms`` is not one of them, so
# a form response is a canonical event on the ``events`` spine like any other and
# only its committed values need a place of their own. The values artifacts are this
# module's own runtime addition, so they are free to be keyed by anything.
VALUES_ONLY_KINDS: Final[tuple[str, ...]] = (
    "forms",
    "plans",
    "assignments",
    "exposures",
)

# A canonical event's values kind. The bundle kinds map by the same families; the
# rest are values-only.
#
# Assignment and exposure are two kinds rather than one, and that is the point of
# them: an assignment is what a participant was given and an exposure is what they
# actually reached. A study that reads them as one number can not see its own
# dropout, so the export keeps them apart where a reader can not miss it. The keys
# are matched longest first, so the two API-04 records separate while anything else
# in that family stays with the spine.
_VALUES_KIND_BY_FAMILY: Final[Mapping[str, str]] = {
    **_SEMANTIC_KIND_BY_FAMILY,
    "mug.api-17.": "forms",  # what a participant answered on a form
    "mug.api-04.treatment-assignment": "assignments",  # the condition they were given
    "mug.api-04.treatment-exposure": "exposures",  # the condition they reached
    # The visit plan: the ordered occurrences and the randomization outcomes. It is
    # committed under a command result rather than a record family, so it is named
    # by that result -- and without it the drawn orders leave no exported trace.
    "mug.command-result.visit-transition": "plans",
}


def values_kind_of(event: EventEnvelope) -> str | None:
    """Return the values kind one event belongs to, or None when it has none."""
    name = event.event_schema.name
    for family in sorted(_VALUES_KIND_BY_FAMILY, key=len, reverse=True):
        if name.startswith(family):
            return _VALUES_KIND_BY_FAMILY[family]
    return None


def _envelope_row_schema() -> SchemaRef:
    """Return the event-envelope schema ref without a full envelope instance."""
    factory = EventEnvelope.model_fields["schema"].default_factory
    assert factory is not None  # the envelope always pins its schema
    return cast("SchemaRef", factory())  # pyright: ignore[reportCallIssue]


# Every export row is a canonical event envelope; the row schema names it.
_ROW_SCHEMA: Final[SchemaRef] = _envelope_row_schema()
_RESEARCH: Final[DataHandlingRef] = DataHandlingRef(privacy_labels=["research"])
_NDJSON: Final[str] = "application/x-ndjson"
# An export applies no filters yet, so every request pins the empty filter set.
_FILTERS: Final[dict[str, object]] = {}


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


def collect_dataset_values(
    store: Store, grouped: Mapping[str, GroupedRows]
) -> dict[str, list[dict[str, object]]]:
    """Read the committed state behind each research dataset's streams.

    An exported row is a canonical event: it says that something happened, at which
    position, under which schema, and binds its content by digest. That is the right
    shape for a spine every export copies, and on its own it is not a dataset -- a
    reader can not say which run a participant preferred, only that a preference was
    recorded.

    So the export also reads what each aggregate committed. One row per aggregate,
    carrying its identifier, its stream, and its state. The state is exactly what the
    ledger bound: digesting it reproduces the ``payload_digest`` of that aggregate's
    own exported row, so the values are checkable against the spine rather than a
    file beside it. One stream may carry more than one aggregate -- a preference
    assignment and its response are one lineage and share a stream -- so the check is
    that the ledger bound this state, not that it bound it last.

    Only the three research kinds get values; ``events`` is the spine and stays as it
    is. Rows are ordered by stream then aggregate, so one ledger always gives one
    artifact.
    """
    kinds = sorted(set(_VALUES_KIND_BY_FAMILY.values()))
    by_stream = {
        kind: set(grouped[kind].source_stream_ids) for kind in kinds if kind in grouped
    }
    values: dict[str, list[dict[str, object]]] = {kind: [] for kind in kinds}
    for aggregate_id, state in sorted(store.scan_aggregates(), key=_by_id):
        stream_id = _stream_of(aggregate_id)
        for kind, streams in by_stream.items():
            if stream_id in streams:
                values[kind].append(
                    {
                        "aggregate_id": aggregate_id,
                        "stream_id": stream_id,
                        "state": state,
                    }
                )
    return {kind: sorted(rows, key=_values_order) for kind, rows in values.items()}


def _by_id(item: tuple[str, object]) -> str:
    """Order one scanned aggregate by its identifier."""
    return item[0]


def _values_order(row: Mapping[str, object]) -> tuple[str, str]:
    """Order one values row by its stream, then by its aggregate."""
    return (str(row["stream_id"]), str(row["aggregate_id"]))


class DatasetValues(NamedTuple):
    """One dataset kind's committed values: the artifact and how many rows it has."""

    dataset_kind: str
    artifact: ArtifactRef
    row_count: int


def collect_dataset_rows(store: Store) -> dict[str, GroupedRows]:
    """Read the whole ledger once and group canonical events by dataset kind.

    Rows keep the store's per-stream order; across streams they follow the
    sorted stream id, so the grouping is reproducible from the ledger alone.
    """
    every = (*DATASET_KINDS, *VALUES_ONLY_KINDS)
    rows: dict[str, list[dict[str, object]]] = {kind: [] for kind in every}
    streams: dict[str, set[str]] = {kind: set() for kind in every}
    for stream_id in discover_streams(store):
        for event in read_ledger(store, stream_id):
            payload = event.model_dump(mode="json", exclude_none=True)
            for kind in dataset_kinds_of(event):
                rows[kind].append(payload)
                streams[kind].add(stream_id)
            values_kind = values_kind_of(event)
            if values_kind in VALUES_ONLY_KINDS:
                streams[cast("str", values_kind)].add(stream_id)
    return {kind: GroupedRows(rows[kind], sorted(streams[kind])) for kind in every}


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
    """A study's full dataset export: the bundles, lineage, bindings, and values.

    ``bundles``, ``lineage``, and ``bindings`` are the frozen API-19 records.
    ``values`` is what each research dataset's aggregates committed, one artifact per
    kind, bound to the bundle rows by digest (see ``collect_dataset_values``).
    ``requests`` is the ``ExportRequest`` behind each bundle, so an export says what
    was asked for -- study version, kind, filters, and when -- rather than only what
    came out.
    """

    bundles: list[ExportBundle]
    lineage: list[LineageRecord]
    bindings: list[DatasetSchemaBinding]
    values: tuple[DatasetValues, ...] = ()
    requests: tuple[ExportRequest, ...] = ()


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
    collected = collect_dataset_values(store, grouped)
    # The one derived dataset: the recorded judgements joined into the flat rows a
    # reward model is trained on. Every other values kind is the committed state as
    # it stands; this one is a projection, and it says so by having its own builder.
    pairs = await collect_preference_rows(store, artifacts)
    if pairs:
        collected[PREFERENCE_PAIRS] = pairs
    bundles: list[ExportBundle] = []
    lineage: list[LineageRecord] = []
    collected_values: list[DatasetValues] = []
    exported_kinds: list[str] = []
    requests: list[ExportRequest] = []
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
        requests.append(
            ExportRequest(
                export_key=f"{export_key}-{kind}",
                study_version=study_version,
                dataset_kind=kind,  # pyright: ignore[reportArgumentType]
                filters_digest=compute_digest(_FILTERS),
                requested_at=now(),
            )
        )
    # Values follow the collected kinds, not the exported ones: ``forms`` has values
    # and no bundle, because the frozen ``DatasetKind`` enum does not name it.
    for kind in (*exported_kinds, *VALUES_ONLY_KINDS, PREFERENCE_PAIRS):
        rows = collected.get(kind)
        if not rows:
            continue
        collected_values.append(
            DatasetValues(
                dataset_kind=kind,
                artifact=await _stage_ndjson(
                    artifacts,
                    data=_ndjson(rows),
                    new_artifact_id=new_artifact_id,
                    new_upload_id=new_upload_id,
                    now=now,
                    data_handling=data_handling,
                ),
                row_count=len(rows),
            )
        )
    bindings = [
        DatasetSchemaBinding(dataset_kind=kind, row_schema=_ROW_SCHEMA)  # pyright: ignore[reportArgumentType]
        for kind in exported_kinds
    ]
    return DatasetExport(
        bundles=bundles,
        lineage=lineage,
        bindings=bindings,
        values=tuple(collected_values),
        requests=tuple(requests),
    )


__all__ = [
    "DATASET_KINDS",
    "DatasetExport",
    "DatasetValues",
    "GroupedRows",
    "build_dataset_export",
    "collect_dataset_rows",
    "collect_dataset_values",
    "dataset_kinds_of",
    "dataset_schema_bindings",
    "discover_streams",
    "export_study_dataset",
]
