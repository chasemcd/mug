"""Validate API-04 visit-plan, treatment, exposure, and state contracts."""

from __future__ import annotations

from typing import Any

import pytest

from _contract_harness import (
    canonical_digest,
    check_bundle_binding,
    check_manifest_complete,
    check_schema_valid,
    load_family,
    run_fixture_case,
    strict_json_load,
)

FAMILY = load_family("api-04", "visit-plan.schema.json")
BUNDLE_NAMES = {
    "mug.api-04.visit",
    "mug.api-04.visit-plan",
    "mug.api-04.eligibility-callback",
    "mug.api-04.treatment-plan",
    "mug.api-04.treatment-assignment",
    "mug.api-04.treatment-exposure",
    "mug.api-04.allocation-state",
    "mug.api-04.state-document",
    "mug.api-04.fixture-manifest",
}


def semantic_violations(name: str, value: Any) -> list[tuple[str, str]]:
    if name == "VisitPlan":
        seen: set[int] = set()
        for index, activity in enumerate(value["activities"]):
            if activity["ordinal"] in seen:
                return [("duplicateOrdinal", f"/activities/{index}/ordinal")]
            seen.add(activity["ordinal"])
        return []
    if name == "TreatmentPlan":
        hits: list[tuple[str, str]] = []
        shared_keys = {treatment["key"] for treatment in value["shared_treatments"]}
        placed_keys: set[str] = set()
        for index, placement in enumerate(value["placements"]):
            treatment = placement["treatment"]
            if "ref" in treatment:
                # R-15: a placement either carries a one-off inline treatment or
                # references a declared shared treatment object.
                if treatment["ref"] not in shared_keys:
                    hits.append(
                        ("danglingTreatmentRef", f"/placements/{index}/treatment/ref")
                    )
                else:
                    placed_keys.add(treatment["ref"])
            else:
                placed_keys.add(treatment["key"])
        # A Design(cross=[...]) naming a treatment placed nowhere is a compile
        # error (R-15): every crossed factor must have at least one effect site.
        for index, factor_key in enumerate(value.get("design", {}).get("cross", [])):
            if factor_key not in placed_keys:
                hits.append(("unplacedDesignFactor", f"/design/cross/{index}"))
        return hits
    return []


@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api04_contract_fixture(case: dict[str, Any]) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)


def test_api04_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)


def test_api04_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")


def test_api04_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)


def test_api04_visit_pins_immutable_version_and_deployment() -> None:
    visit = strict_json_load(FAMILY.fixture_root / "valid" / "visit.minimal-static.json")
    plan = strict_json_load(FAMILY.fixture_root / "valid" / "visit-plan.minimal-static.json")
    # A visit pins one study version and one deployment revision; its plan agrees.
    assert visit["study_version"] == plan["study_version"]
    assert visit["deployment"]["study_version"] == visit["study_version"]
    assert plan["visit_id"] == visit["visit_id"]
    # ADR-0014: no wave gating; multi-part participation is flow-based.
    assert "wave_key" not in visit
    # The materialized plan digest closes over its activities and outcomes.
    recomputed = canonical_digest(
        {"activities": plan["activities"], "randomization_outcomes": plan["randomization_outcomes"]}
    )
    assert plan["plan_digest"]["hex"] == recomputed


def test_api04_assignment_and_exposure_are_separate_records() -> None:
    assignment = strict_json_load(
        FAMILY.fixture_root / "valid" / "treatment-assignment.participant.json"
    )
    exposure = strict_json_load(
        FAMILY.fixture_root / "valid" / "treatment-exposure.minimal-static.json"
    )
    # Assignment is intent (no occurrence); exposure is actual delivery (an occurrence).
    assert "occurrence_id" not in assignment
    assert "occurrence_id" in exposure
    assert assignment["treatment_key"] == exposure["treatment_key"]
    assert assignment["level_key"] == exposure["level_key"]


def test_api04_group_assignment_is_shared_by_the_group_not_a_visit() -> None:
    group_assignment = strict_json_load(
        FAMILY.fixture_root / "valid" / "treatment-assignment.group-scope.json"
    )
    # D06-7: a Scope.GROUP assignment is made once per matched group and shared
    # by every member — it references the group, never a single member's visit.
    assert group_assignment["scope"] == "group"
    assert "group_id" in group_assignment
    assert "visit_id" not in group_assignment


def _iter_assign_policies(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("policy"), str):
            found.append(value)
        for child in value.values():
            found.extend(_iter_assign_policies(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_iter_assign_policies(child))
    return found


def test_api04_balanced_assignment_always_carries_the_unit_knob() -> None:
    # R-7 / A04-O05: Assign.balanced carries an explicit typed balancing unit.
    for name in ("treatment-plan.inline-cast.json", "treatment-plan.shared-crossed.json"):
        plan = strict_json_load(FAMILY.fixture_root / "valid" / name)
        for policy in _iter_assign_policies(plan):
            if policy["policy"] == "balanced":
                assert policy["unit"] in {"groups", "participants"}, name


def test_api04_eligibility_callback_is_flow_level_and_fails_closed_by_default() -> None:
    # RP-10 / ADR-0014: flow-level screening/eligibility callbacks are addressed by
    # a server-side qualified name and default to fail-closed (exclude/block) on
    # error or timeout; fail-open is an explicit per-callback opt-in. This is
    # distinct from API-06 MonitoringPolicy continuous in-play exclusion.
    on_error = FAMILY.schema["$defs"]["EligibilityCallback"]["properties"]["on_error"]
    assert on_error["enum"] == ["fail_closed", "fail_open"]
    assert on_error["default"] == "fail_closed"

    default_closed = strict_json_load(
        FAMILY.fixture_root / "valid" / "eligibility-callback.default-fail-closed.json"
    )
    fail_open = strict_json_load(
        FAMILY.fixture_root / "valid" / "eligibility-callback.explicit-fail-open.json"
    )
    # The default fixture omits on_error; the schema default supplies fail_closed.
    assert "on_error" not in default_closed
    assert fail_open["on_error"] == "fail_open"
    # Callbacks are server-side qualified names (module path + attribute), never
    # inline code — matching the corpus factory qualified-name convention.
    for record in (default_closed, fail_open):
        module, sep, attribute = record["callback"].partition(":")
        assert sep and module and attribute
        assert "<lambda>" not in record["callback"]
    # The plan-level attachment point references the same callback contract.
    plan_eligibility = FAMILY.schema["$defs"]["VisitPlan"]["properties"]["eligibility"]
    assert plan_eligibility["items"]["$ref"] == "#/$defs/EligibilityCallback"
