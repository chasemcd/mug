"""Validate MUG API-19 Dataset Query, Export, and Lineage contracts, version 0."""
from __future__ import annotations
from typing import Any
import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-19", "export.schema.json")
BUNDLE_NAMES = {'mug.api-19.export.fixture-manifest', 'mug.api-19.dataset-schema-binding', 'mug.api-19.export-bundle', 'mug.api-19.export-request', 'mug.api-19.lineage-record'}

def semantic_violations(name, value):
    violations = []
    if name == "LineageRecord":
        if not value["source_stream_ids"] and not value["source_artifact_ids"]:
            violations.append(("exportLineage", "/source_stream_ids"))
        if value["transformation"] != "none" and not value["source_artifact_ids"]:
            violations.append(("derivedExportSource", "/source_artifact_ids"))
    return violations

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api19_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api19_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api19_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api19_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)

