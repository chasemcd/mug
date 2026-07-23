"""Validate MUG API-18 Preferences, Annotation, and Quality contracts, version 0."""
from __future__ import annotations
from typing import Any
import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-18", "preference.schema.json")
BUNDLE_NAMES = {'mug.api-18.quality-evidence', 'mug.api-18.preference-response', 'mug.api-18.preference.fixture-manifest', 'mug.api-18.candidate-ref', 'mug.api-18.preference-protocol', 'mug.api-18.preference-assignment'}

def semantic_violations(name, value):
    if name == "PreferenceAssignment":
        seen = set()
        for i, k in enumerate(value["candidate_display_order"]):
            if k in seen:
                return [("duplicateDisplayOrder", f"/candidate_display_order/{i}")]
            seen.add(k)
    if name == "PreferenceResponse":
        # D12-5: a recorded choice must be one of the presented candidates.
        if value["choice"] not in value["presented_order"]:
            return [("choiceNotPresented", "/choice")]
    return []

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api18_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api18_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api18_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api18_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)

def test_api18_comparison_task_set_is_typed_and_closed() -> None:
    # F-3 / D12-3: v0 comparison tasks are the typed closed set pairwise + rating.
    task = FAMILY.schema["$defs"]["ComparisonTask"]
    assert task["properties"]["kind"]["enum"] == ["pairwise", "rating"]
    assert task["additionalProperties"] is False

def test_api18_response_choice_is_presented_with_the_shown_order() -> None:
    asn = strict_json_load(FAMILY.fixture_root / "valid" / "preference-assignment.minimal-static.json")
    resp = strict_json_load(FAMILY.fixture_root / "valid" / "preference-response.minimal-static.json")
    # D12-4/5: the randomized, blinded presentation never changes candidate
    # identity; the choice must be one presented, with the order that was shown.
    assert resp["assignment_id"] == asn["assignment_id"]
    assert resp["presented_order"] == asn["candidate_display_order"]
    assert resp["choice"] in resp["presented_order"]
