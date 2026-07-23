"""Validate MUG API-14 Tools, Approval, and Environment Commands contracts, version 0."""
from __future__ import annotations
from typing import Any
import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-14", "tools.schema.json")
BUNDLE_NAMES = {'mug.api-14.tools.fixture-manifest', 'mug.api-14.tool-approval', 'mug.api-14.tool-version', 'mug.api-14.tool-result', 'mug.api-14.tool-call', 'mug.api-14.environment-command-mailbox'}

def semantic_violations(name, value):
    violations = []
    if name == "ToolResult" and value["outcome"] == "executed":
        if "result_digest" not in value:
            violations.append(("toolEvidence", "/outcome"))
        if value["approval_required"] and "approval_digest" not in value:
            violations.append(("approvalGate", "/approval_required"))
    return violations

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api14_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api14_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api14_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api14_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)
