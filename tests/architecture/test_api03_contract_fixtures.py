"""Validate API-03 identity, enrollment, and launch contracts."""

from __future__ import annotations

from typing import Any

import pytest

from _contract_harness import (
    check_bundle_binding,
    check_manifest_complete,
    check_schema_valid,
    load_family,
    run_fixture_case,
)

FAMILY = load_family("api-03", "identity-enrollment.schema.json")
BUNDLE_NAMES = {
    "mug.api-03.enrollment",
    "mug.api-03.launch-ticket",
    "mug.api-03.external-identity-link",
    "mug.api-03.fixture-manifest",
}


def semantic_violations(name: str, value: Any) -> list[tuple[str, str]]:
    if name == "Enrollment":
        if value["principal"]["kind"] != "participant":
            return [("principalKind", "/principal/kind")]
        return []
    if name == "ExternalIdentityLink":
        if "pii" not in value["data_handling"]["privacy_labels"]:
            return [("piiClassification", "/data_handling/privacy_labels")]
        return []
    return []


@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api03_contract_fixture(case: dict[str, Any]) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)


def test_api03_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)


def test_api03_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")


def test_api03_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)
