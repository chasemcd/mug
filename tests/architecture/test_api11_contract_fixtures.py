"""Validate MUG API-11 Storage, Artifacts, Transactions, and Outbox contracts, version 0."""
from __future__ import annotations
from typing import Any
import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-11", "storage.schema.json")
BUNDLE_NAMES = {'mug.api-11.outbox-record', 'mug.api-11.artifact-staging', 'mug.api-11.storage.fixture-manifest', 'mug.api-11.finalized-artifact', 'mug.api-11.unit-of-work-receipt'}

def semantic_violations(name, value):
    if name == "FinalizedArtifact":
        if value["artifact"]["digest"]["hex"] != value["intended_digest"]["hex"]:
            return [("artifactDigest", "/artifact/digest/hex")]
    if name == "OutboxRecord":
        if value["status"] == "confirmed" and not value["event_ids"]:
            return [("outboxEvidence", "/event_ids")]
    return []

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api11_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api11_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api11_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api11_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)

