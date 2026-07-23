"""Validate MUG API-16 Replay Capture, Bundles, and Validation contracts, version 0."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from _contract_harness import (
    canonical_bytes,
    canonical_digest,
    check_bundle_binding,
    check_manifest_complete,
    check_schema_valid,
    load_family,
    run_fixture_case,
    strict_json_load,
)

FAMILY = load_family("api-16", "replay.schema.json")
BUNDLE_NAMES = {
    "mug.api-16.replay-manifest",
    "mug.api-16.p2p-replay-evidence",
    "mug.api-16.decision-tape",
    "mug.api-16.state-hash-check",
    "mug.api-16.replay.fixture-manifest",
    "mug.api-16.replay-bundle-validation",
}


def _finality_violations(
    value: dict[str, Any], pointer_prefix: str = ""
) -> list[tuple[str, str]]:
    if (
        value.get("status") == "verified"
        and value["verified_through_frame"] > value["confirmed_through_frame"]
    ):
        return [
            (
                "p2pFinalityOrder",
                f"{pointer_prefix}/verified_through_frame",
            )
        ]
    return []


def semantic_violations(name: str, value: dict[str, Any]) -> list[tuple[str, str]]:
    if name == "ReplayManifest":
        levels = value["capability_levels"]
        if not (levels["visual"] or levels["deterministic"]):
            return [("replayCapability", "/capability_levels")]
        if value["reproduction_scope"] == "canonical-and-experienced":
            replay = value["experienced_stream_replay"]
            canonical_event_ids = set(replay["canonical_event_ids"])
            for index, frame in enumerate(replay["experienced_lineage"]):
                if (
                    frame["delivery_kind"] == "corrected"
                    and frame["canonical_event_id"] not in canonical_event_ids
                ):
                    return [
                        (
                            "experiencedCorrectedLineage",
                            f"/experienced_stream_replay/experienced_lineage/{index}/canonical_event_id",
                        )
                    ]
        if value["execution_mode"] == "p2p":
            evidence = value["p2p_replay_evidence"]
            if evidence["frozen_peer_actor_ids"] != sorted(
                evidence["frozen_peer_actor_ids"]
            ):
                return [("canonicalPeerOrder", "/p2p_replay_evidence/frozen_peer_actor_ids")]
            if evidence["mesh_membership_digest"] != evidence["mesh_membership"][
                "artifact"
            ]["digest"]:
                return [("meshDigestBinding", "/p2p_replay_evidence/mesh_membership_digest")]
            finality_hits = _finality_violations(
                evidence["finality_outcome"],
                "/p2p_replay_evidence/finality_outcome",
            )
            if finality_hits:
                return finality_hits
            root_artifacts = {
                artifact["artifact_id"]: artifact for artifact in value["artifact_refs"]
            }
            for binding_name in (
                "mesh_membership",
                "frame_finality",
                "episode_boundaries",
                "bot_authorities",
                "decision_results",
                "decision_tape",
            ):
                artifact = evidence[binding_name]["artifact"]
                if root_artifacts.get(artifact["artifact_id"]) != artifact:
                    return [
                        (
                            "p2pArtifactClosure",
                            f"/p2p_replay_evidence/{binding_name}/artifact",
                        )
                    ]
    if name == "P2PFinalityOutcome":
        return _finality_violations(value)
    if name == "DecisionTape":
        decision_ids: set[str] = set()
        action_coordinates: set[tuple[Any, ...]] = set()
        for index, entry in enumerate(value["entries"]):
            if entry["kind"] != "p2p-bot-action":
                continue
            if entry["decision_id"] in decision_ids:
                return [("duplicateDecision", f"/entries/{index}/decision_id")]
            decision_ids.add(entry["decision_id"])
            coordinate = (
                entry["bot_actor_id"],
                entry["episode_id"],
                entry["frame_number"],
                entry["membership_generation"],
                entry["authority_generation"],
            )
            if coordinate in action_coordinates:
                return [("duplicateBotAction", f"/entries/{index}/frame_number")]
            action_coordinates.add(coordinate)
            if entry["bot_actor_id"] == entry["authority_actor_id"]:
                return [("botAuthorityActor", f"/entries/{index}/authority_actor_id")]
    if name == "StateHashCheck" and value["verification"] == "deterministic":
        hashes_match = value["expected_state_hash"] == value["observed_state_hash"]
        expected_result = "match" if hashes_match else "mismatch"
        if value["result"] != expected_result:
            return [("stateHashResult", "/result")]
    if name == "ReplayBundleValidation":
        if value["external_calls_made"]:
            return [("replayExternalCalls", "/external_calls_made")]
        expected = not value["external_calls_made"] and not value[
            "modified_artifact_ids"
        ]
        if value["valid"] != expected:
            return [("replayValidity", "/valid")]
    return []


@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api16_contract_fixture(case: dict[str, Any]) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)


def test_api16_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)


def test_api16_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")


def test_api16_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)


def test_api16_deterministic_snapshots_have_closed_codec_neutral_coverage() -> None:
    coverage = FAMILY.schema["$defs"]["SnapshotCoverage"]
    expected = {
        "environment_state",
        "platform_state",
        "python_random_state",
        "numpy_random_state",
        "mug_javascript_rng_state",
    }
    assert set(coverage["required"]) == expected
    assert set(coverage["properties"]) == expected
    assert all(specification == {"const": True} for specification in coverage["properties"].values())
    assert coverage["additionalProperties"] is False
    assert FAMILY.schema["$defs"]["EnvHooks"]["properties"]["snapshot_restore"] == {
        "const": True
    }
    assert not any("codec" in name.lower() for name in FAMILY.schema["$defs"])


def test_api16_p2p_mode_requires_and_non_p2p_forbids_p2p_evidence() -> None:
    fixture = strict_json_load(
        FAMILY.fixture_root / "valid" / "replay-manifest.p2p-deterministic.json"
    )
    missing = deepcopy(fixture)
    del missing["p2p_replay_evidence"]
    assert list(FAMILY.validator_for(f"{FAMILY.schema['$id']}#/$defs/ReplayManifest").iter_errors(missing))

    non_p2p = deepcopy(fixture)
    non_p2p["execution_mode"] = "server"
    assert list(FAMILY.validator_for(f"{FAMILY.schema['$id']}#/$defs/ReplayManifest").iter_errors(non_p2p))


def test_api16_p2p_fixture_closes_over_membership_and_decision_tape_bytes() -> None:
    replay_manifest = strict_json_load(
        FAMILY.fixture_root / "valid" / "replay-manifest.p2p-deterministic.json"
    )
    evidence = replay_manifest["p2p_replay_evidence"]

    mesh_path = (
        FAMILY.api_root.parent
        / "api-06"
        / "fixtures"
        / "v0"
        / "valid"
        / "p2p-mesh-membership.four-peer.json"
    )
    mesh = strict_json_load(mesh_path)
    mesh_artifact = evidence["mesh_membership"]["artifact"]
    assert evidence["mesh_membership"]["schema"] == mesh["schema"]
    assert mesh_artifact["digest"]["hex"] == canonical_digest(mesh)
    assert mesh_artifact["size_bytes"] == len(canonical_bytes(mesh))
    assert evidence["mesh_membership_digest"] == mesh_artifact["digest"]
    assert evidence["membership_generation"] == mesh["membership_generation"]
    assert evidence["frozen_peer_actor_ids"] == mesh["peer_actor_ids"]

    api12_fixture_root = (
        FAMILY.api_root.parent / "api-12" / "fixtures" / "v0" / "valid"
    )
    authority = strict_json_load(
        api12_fixture_root / "p2p-bot-authority.four-peer.json"
    )
    authority_binding = evidence["bot_authorities"]
    assert authority_binding["schema"] == authority["schema"]
    assert authority_binding["artifact"]["digest"]["hex"] == canonical_digest(
        authority
    )
    assert authority_binding["artifact"]["size_bytes"] == len(
        canonical_bytes(authority)
    )

    decision_result = strict_json_load(
        api12_fixture_root / "decision-result.p2p-bot.json"
    )
    result_binding = evidence["decision_results"]
    assert result_binding["schema"] == decision_result["schema"]
    assert result_binding["artifact"]["digest"]["hex"] == canonical_digest(
        decision_result
    )
    assert result_binding["artifact"]["size_bytes"] == len(
        canonical_bytes(decision_result)
    )

    tape = strict_json_load(
        FAMILY.fixture_root / "valid" / "decision-tape.p2p-bot-action.json"
    )
    tape_binding = evidence["decision_tape"]
    assert tape_binding["schema"] == tape["schema"]
    assert tape_binding["artifact"]["digest"]["hex"] == canonical_digest(tape)
    assert tape_binding["artifact"]["size_bytes"] == len(canonical_bytes(tape))
    entry = tape["entries"][0]
    assert entry["mesh_membership_digest"] == evidence["mesh_membership_digest"]
    assert entry["membership_generation"] == evidence["membership_generation"]
    assert entry["authority_actor_id"] in evidence["frozen_peer_actor_ids"]
    assert entry["replay_behavior"] == "apply-recorded-action"
    assert entry["decision_origin"] in {
        "authority-local",
        "server-scheduler",
    }
    assert entry["decision_id"] == decision_result["decision_id"]
    assert entry["decision_result_digest"]["hex"] == canonical_digest(decision_result)
    assert entry["bot_actor_id"] == authority["bot_actor_id"]
    assert entry["authority_actor_id"] == authority["authority_actor_id"]
    assert entry["authority_generation"] == authority["authority_fence"]["generation"]
    assert entry["frame_number"] == decision_result["p2p_authority"]["target_frame"]
    assert entry["action_digest"] == decision_result["action_digest"]


def test_api16_model_output_decision_tape_path_remains_supported() -> None:
    tape = strict_json_load(
        FAMILY.fixture_root / "valid" / "decision-tape.minimal-static.json"
    )
    assert tape["entries"][0]["kind"] == "model-output"
    assert not semantic_violations("DecisionTape", tape)
