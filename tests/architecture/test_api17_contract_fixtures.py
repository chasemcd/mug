"""Validate MUG API-17 Content, Forms, and Presentation contracts, version 0."""
from __future__ import annotations
from typing import Any
import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-17", "content.schema.json")
BUNDLE_NAMES = {'mug.api-17.accessibility-profile', 'mug.api-17.content-spec', 'mug.api-17.presentation-component', 'mug.api-17.form-spec', 'mug.api-17.content.fixture-manifest', 'mug.api-17.form-response', 'mug.api-17.gate-control'}

def semantic_violations(name, value):
    if name == "FormSpec":
        seen = set()
        for i, f in enumerate(value["fields"]):
            if f["field_key"] in seen:
                return [("duplicateField", f"/fields/{i}/field_key")]
            seen.add(f["field_key"])
    if name == "AccessibilityProfile":
        if value["wcag_level"] in {"aa", "aaa"} and not (value["keyboard_navigable"] and value["screen_reader"]):
            return [("accessibilityFloor", "/wcag_level")]
    if name == "GateControl":
        expected_kind = "flow_node" if value["gate_target"] == "advance" else "interaction"
        if value["anchor"]["anchor_kind"] != expected_kind:
            return [("gateAnchorMismatch", "/anchor/anchor_kind")]
    return []

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api17_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api17_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api17_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api17_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)
