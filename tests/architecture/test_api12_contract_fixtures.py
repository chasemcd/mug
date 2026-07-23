"""Validate MUG API-12 Automated Controllers and Scheduling contracts, version 0."""

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

FAMILY = load_family("api-12", "scheduler.schema.json")
BUNDLE_NAMES = {
    "mug.api-12.controller-policy",
    "mug.api-12.decision-request",
    "mug.api-12.decision-result",
    "mug.api-12.fallback-policy",
    "mug.api-12.p2p-bot-authority",
    "mug.api-12.scheduler-state",
    "mug.api-12.scheduler.fixture-manifest",
}

AUTHORITY_CLAIM_FIELDS = (
    "interaction_id",
    "channel_key",
    "episode_id",
    "episode_generation",
    "bot_actor_id",
    "authority_actor_id",
    "mesh_membership_digest",
    "membership_generation",
    "authority_fence",
)


def _p2p_authority() -> dict[str, Any]:
    return strict_json_load(
        FAMILY.fixture_root / "valid" / "p2p-bot-authority.four-peer.json"
    )


def _claim_violations(claim: dict[str, Any]) -> list[tuple[str, str]]:
    authority = _p2p_authority()
    if claim["authority_assignment_digest"]["hex"] != canonical_digest(authority):
        return [
            (
                "authorityBinding",
                "/p2p_authority/authority_assignment_digest",
            )
        ]
    for field in AUTHORITY_CLAIM_FIELDS:
        if claim[field] != authority[field]:
            return [("authorityBinding", f"/p2p_authority/{field}")]
    return []


def semantic_violations(name: str, value: Any) -> list[tuple[str, str]]:
    if name == "P2PBotAuthority":
        eligible = value["eligible_peer_actor_ids"]
        if eligible != sorted(eligible):
            return [("canonicalPeerOrder", "/eligible_peer_actor_ids")]
        if value["authority_actor_id"] != eligible[-1]:
            return [("authoritySelection", "/authority_actor_id")]
        return []

    if name == "DecisionRequest" and value["execution_mode"] == "p2p":
        claim = value["p2p_authority"]
        request_bindings = {
            "bot_actor_id": value["actor_id"],
            "channel_key": value["channel_key"],
            "episode_generation": value["episode_generation"],
        }
        for field, expected in request_bindings.items():
            if claim[field] != expected:
                return [("authorityBinding", f"/p2p_authority/{field}")]
        return _claim_violations(claim)

    if name == "DecisionResult":
        if value["outcome"] == "produced" and "action_digest" not in value:
            return [("decisionEvidence", "/outcome")]
        if value["outcome"] == "produced" and value["staleness"] == "stale":
            return [("staleDecision", "/staleness")]
        if value["execution_mode"] == "p2p":
            violations = _claim_violations(value["p2p_authority"])
            if violations:
                return violations
            if (
                value["outcome"] == "produced"
                and value["producer"]["content_digest"] != value["action_digest"]
            ):
                return [("publishedActionDigest", "/producer/content_digest")]
    return []


@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api12_contract_fixture(case: dict[str, Any]) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)


def test_api12_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)


def test_api12_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")


def test_api12_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)


def test_api12_p2p_request_result_share_authority_and_action_evidence() -> None:
    request = strict_json_load(
        FAMILY.fixture_root / "valid" / "decision-request.p2p-bot.json"
    )
    result = strict_json_load(
        FAMILY.fixture_root / "valid" / "decision-result.p2p-bot.json"
    )
    authority = _p2p_authority()

    assert request["decision_id"] == result["decision_id"]
    assert request["p2p_authority"] == result["p2p_authority"]
    assert (
        request["p2p_authority"]["authority_assignment_digest"]["hex"]
        == canonical_digest(authority)
    )
    assert result["producer"]["content_digest"] == result["action_digest"]
    assert result["replay_behavior"] == "apply-recorded-action"


def test_api12_p2p_authority_binds_api06_mesh_fixture() -> None:
    authority = _p2p_authority()
    api06_root = FAMILY.api_root.parent / "api-06"
    mesh_schema = strict_json_load(
        api06_root / "schemas" / "v0" / "interaction.schema.json"
    )
    mesh = strict_json_load(
        api06_root
        / "fixtures"
        / "v0"
        / "valid"
        / "p2p-mesh-membership.four-peer.json"
    )

    assert authority["mesh_membership_schema"]["digest"]["hex"] == canonical_digest(
        mesh_schema
    )
    assert authority["mesh_membership_digest"]["hex"] == canonical_digest(mesh)
    assert authority["membership_generation"] == mesh["membership_generation"]
    assert authority["eligible_peer_actor_ids"] == mesh["peer_actor_ids"]
