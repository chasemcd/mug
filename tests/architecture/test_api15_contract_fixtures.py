"""Validate MUG API-15 Experimental Agent Memory contracts, version 0."""
from __future__ import annotations
from typing import Any
import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-15", "memory.schema.json")
BUNDLE_NAMES = {'mug.api-15.memory-scope', 'mug.api-15.memory-proposal', 'mug.api-15.memory-commit', 'mug.api-15.memory-read', 'mug.api-15.memory.fixture-manifest'}

def semantic_violations(name, value):
    if name == "MemoryCommit":
        if value["new_version"]["revision"] != value["prior_version"]["revision"] + 1:
            return [("memoryVersion", "/new_version/revision")]
    return []

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api15_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api15_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api15_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api15_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)

def test_api15_commit_matches_its_proposal_base() -> None:
    prop = strict_json_load(FAMILY.fixture_root / "valid" / "memory-proposal.minimal-static.json")
    commit = strict_json_load(FAMILY.fixture_root / "valid" / "memory-commit.minimal-static.json")
    # Compare-and-swap: a commit applies a proposal against the exact base it read.
    assert commit["prior_version"] == prop["base_version"]
    assert commit["committed_digest"] == prop["proposed_digest"]
    assert commit["provenance_decision_id"] == prop["provenance_decision_id"]

