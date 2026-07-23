"""Validate MUG API-22 Durable Jobs and Workers contracts, version 0."""
from __future__ import annotations
from typing import Any
import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-22", "jobs.schema.json")
BUNDLE_NAMES = {'mug.api-22.job-result', 'mug.api-22.jobs.fixture-manifest', 'mug.api-22.job-run', 'mug.api-22.job-request'}

def semantic_violations(name, value):
    if name == "JobRun" and value["status"] == "succeeded" and "result_digest" not in value:
        return [("jobResult", "/status")]
    if name == "JobResult" and value["outcome"] == "success" and "result_ref" not in value:
        return [("jobResult", "/outcome")]
    return []

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api22_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api22_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api22_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api22_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)

def test_api22_result_pins_the_request_work_key() -> None:
    req = strict_json_load(FAMILY.fixture_root / "valid" / "job-request.minimal-static.json")
    res = strict_json_load(FAMILY.fixture_root / "valid" / "job-result.minimal-static.json")
    # Idempotent work key ties a request to its single durable result.
    assert req["work_key"] == res["work_key"]
    assert req["job_id"] == res["job_id"]

def test_api22_first_class_job_kinds_are_named_and_usable_as_job_kinds() -> None:
    kinds = FAMILY.schema["$defs"]["FirstClassJobKind"]["enum"]
    # Compile-at-publish (ADR-0013) and `mug simulate` headless batch runs
    # (D11-7) are first-class v0 job kinds, alongside export/replay bundle builds.
    assert "compile-at-publish" in kinds
    assert "simulate-batch" in kinds
    # Every first-class kind is a legal domain job-kind key.
    authoring_key = FAMILY.validator_for(f"{FAMILY.schema['$id']}#/$defs/AuthoringKey")
    for kind in kinds:
        authoring_key.validate(kind)

