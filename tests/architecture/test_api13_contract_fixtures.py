"""Validate MUG API-13 Model Providers, Usage, and Errors contracts, version 0."""
from __future__ import annotations
from typing import Any
import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-13", "provider.schema.json")
BUNDLE_NAMES = {'mug.api-13.agent-version', 'mug.api-13.provider.fixture-manifest', 'mug.api-13.provider-request', 'mug.api-13.provider-response', 'mug.api-13.provider-error'}

def semantic_violations(name, value):
    if name == "ProviderResponse" and value["outcome"] == "completed" and "output_digest" not in value:
        return [("providerEvidence", "/outcome")]
    return []

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api13_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api13_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api13_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api13_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)

