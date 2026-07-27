"""Validate MUG API-18 Preferences, Annotation, and Quality contracts, version 0."""
from __future__ import annotations

import pytest
from _contract_harness import (
    check_bundle_binding,
    check_manifest_complete,
    check_schema_valid,
    load_family,
    run_fixture_case,
    strict_json_load,
)

FAMILY = load_family("api-18", "preference.schema.json")
BUNDLE_NAMES = {'mug.api-18.quality-evidence', 'mug.api-18.preference-response', 'mug.api-18.preference.fixture-manifest', 'mug.api-18.candidate-ref', 'mug.api-18.preference-protocol', 'mug.api-18.preference-assignment'}

def semantic_violations(name, value):
    if name == "PreferenceAssignment":
        seen = set()
        for i, k in enumerate(value["candidate_display_order"]):
            if k in seen:
                return [("duplicateDisplayOrder", f"/candidate_display_order/{i}")]
            seen.add(k)
    if name == "PreferenceProtocol":
        # A dimension is answered once, so a task names each of them once.
        seen = set()
        for i, dim in enumerate(value["task"].get("dimensions") or []):
            if dim["key"] in seen:
                return [("duplicateDimensionKey", f"/task/dimensions/{i}/key")]
            seen.add(dim["key"])
    if name == "PreferenceResponse":
        # D12-5: a recorded choice must be one of the presented candidates.
        if value["choice"] not in value["presented_order"]:
            return [("choiceNotPresented", "/choice")]
        for i, rating in enumerate(value.get("ratings") or []):
            candidate = rating.get("candidate_key")
            # A rating names a candidate that was shown, never a screen position.
            if candidate is not None and candidate not in value["presented_order"]:
                return [
                    ("ratingCandidateNotPresented", f"/ratings/{i}/candidate_key")
                ]
            # No candidate is the midpoint of the scale, which is the zero value.
            if (candidate is None) != (rating["value"] == 0):
                return [("ratingValueWithoutCandidate", f"/ratings/{i}/value")]
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

def test_api18_dimension_ratings_name_a_candidate_and_never_a_position() -> None:
    # A randomized display order must not be able to invert a dimension, so a
    # rating is recorded against the candidate key it is about. The only value
    # that names no candidate is the midpoint, which favours neither.
    rating = FAMILY.schema["$defs"]["DimensionRating"]
    assert set(rating["required"]) == {"dimension_key", "value"}
    assert "candidate_key" in rating["properties"]
    assert rating["additionalProperties"] is False
    resp = strict_json_load(
        FAMILY.fixture_root / "valid" / "preference-response.dimensional.json"
    )
    midpoint = [r for r in resp["ratings"] if "candidate_key" not in r]
    assert [r["value"] for r in midpoint] == [0]
    assert all(
        r["candidate_key"] in resp["presented_order"]
        for r in resp["ratings"]
        if "candidate_key" in r
    )


def test_api18_verdict_admits_a_tie_without_a_phantom_choice() -> None:
    # A tie says neither candidate was preferred; `choice` still names the one
    # the thread resolved to, so the choice-is-presented rule is unchanged.
    verdict = FAMILY.schema["$defs"]["PreferenceResponse"]["properties"]["verdict"]
    assert verdict["enum"] == ["choice", "tie", "both-bad"]
    resp = strict_json_load(
        FAMILY.fixture_root / "valid" / "preference-response.dimensional.json"
    )
    assert resp["verdict"] == "tie"
    assert resp["choice"] in resp["presented_order"]


def test_api18_response_choice_is_presented_with_the_shown_order() -> None:
    asn = strict_json_load(FAMILY.fixture_root / "valid" / "preference-assignment.minimal-static.json")
    resp = strict_json_load(FAMILY.fixture_root / "valid" / "preference-response.minimal-static.json")
    # D12-4/5: the randomized, blinded presentation never changes candidate
    # identity; the choice must be one presented, with the order that was shown.
    assert resp["assignment_id"] == asn["assignment_id"]
    assert resp["presented_order"] == asn["candidate_display_order"]
    assert resp["choice"] in resp["presented_order"]
