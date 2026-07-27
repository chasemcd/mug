"""Dataset export, bundle, and lineage (API-19, layer L1).

This family owns four record types: the ``ExportRequest`` that pins a dataset
export, the produced ``ExportBundle``, the ``LineageRecord`` that states its
origin, and the ``DatasetSchemaBinding`` that binds a row schema to a dataset
kind. Each record references the kernel (L0).

The ``service`` module adds the per-visit runtime: ``export_visit`` reads one
visit's canonical streams and serializes them as the single JSONL export format.
The ``dataset`` module generalizes it to the full study dataset:
``export_study_dataset`` reads the whole ledger and produces one ``ExportBundle``
and ``LineageRecord`` per dataset kind (events, trajectories, preferences,
conversations), reproducibly from the ledger, beside one values artifact per
research kind holding what those aggregates committed.
"""

from __future__ import annotations

from mug.export.dataset import (
    DATASET_KINDS,
    DatasetExport,
    DatasetValues,
    GroupedRows,
    build_dataset_export,
    collect_dataset_rows,
    collect_dataset_values,
    dataset_kinds_of,
    dataset_schema_bindings,
    discover_streams,
    export_study_dataset,
)
from mug.export.service import VisitExport, export_visit
from mug.export.types import (
    DatasetSchemaBinding,
    ExportBundle,
    ExportRequest,
    GitProvenanceRef,
    LineageRecord,
    export_schema,
)

__all__ = [
    "DATASET_KINDS",
    "DatasetExport",
    "DatasetSchemaBinding",
    "DatasetValues",
    "ExportBundle",
    "ExportRequest",
    "GitProvenanceRef",
    "GroupedRows",
    "LineageRecord",
    "VisitExport",
    "build_dataset_export",
    "collect_dataset_rows",
    "collect_dataset_values",
    "dataset_kinds_of",
    "dataset_schema_bindings",
    "discover_streams",
    "export_schema",
    "export_study_dataset",
    "export_visit",
]
