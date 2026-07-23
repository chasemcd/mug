"""Validate MUG API-07 Environment, Game, Rendering, and Execution contracts, version 0."""
from __future__ import annotations

import json
import re

import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-07", "game.schema.json")
BUNDLE_NAMES = {
    "mug.api-07.render-packet",
    "mug.api-07.game.fixture-manifest",
    "mug.api-07.game-transition",
    "mug.api-07.execution-mode",
    "mug.api-07.episode-boundary",
    "mug.api-07.env-factory",
    "mug.api-07.p2p-frame-finality",
}
EXACT_PIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?==[0-9][A-Za-z0-9._+]*$")

def semantic_violations(name, value):
    hits = []
    if name == "GameTransition":
        decisions = value["applied_decisions"]
        decision_ids = [item["decision_id"] for item in decisions]
        actor_ids = [item["actor_id"] for item in decisions]
        if len(decision_ids) != len(set(decision_ids)):
            hits.append(("uniqueAppliedDecision", "/applied_decisions"))
        if len(actor_ids) != len(set(actor_ids)):
            hits.append(("uniqueDecisionActor", "/applied_decisions"))

        if value["authority"] == "peer":
            for index, decision in enumerate(decisions):
                if "publisher_actor_id" not in decision:
                    hits.append(
                        (
                            "peerDecisionPublisher",
                            f"/applied_decisions/{index}/publisher_actor_id",
                        )
                    )
                if "publisher_generation" not in decision:
                    hits.append(
                        (
                            "peerDecisionPublisher",
                            f"/applied_decisions/{index}/publisher_generation",
                        )
                    )
        elif any("publisher_actor_id" in item for item in decisions):
            hits.append(("unexpectedPeerPublisher", "/applied_decisions"))

    if name == "P2PFrameFinality":
        peers = value["frozen_peer_actor_ids"]
        peer_set = set(peers)
        if peers != sorted(peers):
            hits.append(("canonicalPeerOrder", "/frozen_peer_actor_ids"))

        actions = value["actions"]
        action_ids = [item["peer_actor_id"] for item in actions]
        if action_ids != sorted(action_ids):
            hits.append(("canonicalPeerOrder", "/actions"))
        if len(action_ids) != len(set(action_ids)) or not set(action_ids) <= peer_set:
            hits.append(("peerActionSet", "/actions"))

        hashes = value["hash_evidence"]
        hash_ids = [item["peer_actor_id"] for item in hashes]
        if hash_ids != sorted(hash_ids):
            hits.append(("canonicalPeerOrder", "/hash_evidence"))
        if len(hash_ids) != len(set(hash_ids)) or not set(hash_ids) <= peer_set:
            hits.append(("peerHashSet", "/hash_evidence"))

        status = value["status"]
        if status in {"confirmed", "verified", "disputed"} and set(action_ids) != peer_set:
            hits.append(("completePeerActions", "/actions"))
        if status in {"verified", "disputed"} and set(hash_ids) != peer_set:
            hits.append(("completePeerHashes", "/hash_evidence"))

        hash_values = [canonical_digest(item["state_hash"]) for item in hashes]
        if status == "verified" and len(set(hash_values)) != 1:
            hits.append(("unanimousPeerHashes", "/hash_evidence"))
        if status == "verified" and hash_values:
            agreed = canonical_digest(value["agreed_state_hash"])
            if agreed != hash_values[0]:
                hits.append(("agreedStateHash", "/agreed_state_hash"))
        if status == "disputed" and len(set(hash_values)) < 2:
            hits.append(("disputedPeerHashes", "/hash_evidence"))

    if name == "EpisodeBoundary" and "p2p_barrier" in value:
        barrier = value["p2p_barrier"]
        peers = barrier["frozen_peer_actor_ids"]
        endings = barrier["peer_end_frames"]
        end_ids = [item["peer_actor_id"] for item in endings]
        if peers != sorted(peers) or end_ids != sorted(end_ids):
            hits.append(("canonicalPeerOrder", "/p2p_barrier/peer_end_frames"))
        if len(end_ids) != len(set(end_ids)) or set(end_ids) != set(peers):
            hits.append(("completePeerEndFrames", "/p2p_barrier/peer_end_frames"))
        if endings and value["end_frame_exclusive"] != min(
            item["end_frame_exclusive"] for item in endings
        ):
            hits.append(("episodeBarrierMinimum", "/end_frame_exclusive"))
    return hits

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api07_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api07_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api07_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api07_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)

def test_api07_every_runtime_shares_the_normalized_transition() -> None:
    step = strict_json_load(FAMILY.fixture_root / "valid" / "game-transition.minimal-static.json")
    # Every runtime produces the same normalized transition contract: action + state.
    assert "action_digest" in step and "state_digest" in step
    assert step["applied_decisions"] == []
    assert step["authority"] in {"server", "browser", "peer"}

def test_api07_env_factory_records_a_factory_never_an_instance() -> None:
    # R-17: the compiled contract records a qualified name importable from the
    # study source bundle; env instances never cross a process/network boundary.
    for name in ("env-factory.server-minimal", "env-factory.browser-pinned",
                 "env-factory.treatment-args"):
        record = strict_json_load(FAMILY.fixture_root / "valid" / f"{name}.json")
        module, _, attribute = record["factory"].partition(":")
        assert module and attribute, record["factory"]
        assert "<lambda>" not in record["factory"]
        assert not any("instance" in key or "pickle" in key for key in record)

def test_api07_browser_factory_ships_pinned_requires_and_source_bundle() -> None:
    # ExecutionMode.BROWSER: requires= resolved to exact pins at publish; the
    # study source ships as a bundle unpacked onto sys.path in Pyodide.
    record = strict_json_load(FAMILY.fixture_root / "valid" / "env-factory.browser-pinned.json")
    assert record["mode"] == "browser"
    assert record["requires"] and all(EXACT_PIN.fullmatch(pin) for pin in record["requires"])
    assert record["source_bundle"]["data_handling"] == {"privacy_labels": ["public"]}


def test_api07_p2p_contract_fixes_the_mesh_and_rollback_semantics() -> None:
    record = strict_json_load(FAMILY.fixture_root / "valid" / "execution-mode.p2p.json")
    contract = record["p2p_contract"]
    assert contract["topology"] == "full-mesh"
    assert contract["confirmation"] == "complete-peer-action-set"
    assert contract["verification"] == "unanimous-peer-state-hashes"
    assert contract["episode_barrier"] == "minimum-end-frame-exclusive"
    assert contract["human_input_delay"] == "symmetric"
    assert contract["reconciliation"] == "lower-peer-actor-id-defers"
    assert set(contract["snapshot_coverage"]) == {
        "environment_state",
        "platform_state",
        "python_rng_state",
        "numpy_rng_state",
        "mug_js_rng_state",
    }
    assert all(contract["snapshot_coverage"].values())
    assert contract["bot_decisions"] == {
        "authority": "designated-peer",
        "selection": "highest-eligible-peer-actor-id",
        "tenure": "episode-fixed",
        "unilateral_switch": "forbidden",
        "authority_change": "new-fenced-authority-generation",
        "transport": "peer-input-stream",
        "rollback": "replay-recorded-decision-result",
    }


def test_api07_p2p_factory_requires_deterministic_hooks() -> None:
    record = strict_json_load(
        FAMILY.fixture_root / "valid" / "env-factory.p2p-deterministic.json"
    )
    assert {"snapshot-restore", "state-hash"} <= set(record["hooks"])


def test_api07_p2p_finality_progression_is_mesh_bound() -> None:
    names = ("speculative", "confirmed", "verified")
    records = [
        strict_json_load(FAMILY.fixture_root / "valid" / f"p2p-frame-finality.{name}.json")
        for name in names
    ]
    coordinate = ("interaction_id", "channel_key", "episode_id", "frame_number")
    assert [record["status"] for record in records] == list(names)
    assert len({tuple(record[key] for key in coordinate) for record in records}) == 1
    assert len({record["mesh_membership_digest"]["hex"] for record in records}) == 1
    assert len({record["membership_generation"] for record in records}) == 1
    assert records[0]["recorded_at"] < records[1]["recorded_at"] < records[2]["recorded_at"]


def test_api07_p2p_records_bind_the_api06_mesh_and_designated_publisher() -> None:
    mesh_path = (
        FAMILY.api_root.parent
        / "api-06"
        / "fixtures"
        / "v0"
        / "valid"
        / "p2p-mesh-membership.four-peer.json"
    )
    mesh = strict_json_load(mesh_path)
    mesh_digest = canonical_digest(mesh)
    decision_result_path = (
        FAMILY.api_root.parent
        / "api-12"
        / "fixtures"
        / "v0"
        / "valid"
        / "decision-result.p2p-bot.json"
    )
    decision_result = strict_json_load(decision_result_path)
    transition = strict_json_load(
        FAMILY.fixture_root / "valid" / "game-transition.p2p-recorded-bot.json"
    )
    finality = strict_json_load(
        FAMILY.fixture_root / "valid" / "p2p-frame-finality.verified.json"
    )
    boundary = strict_json_load(
        FAMILY.fixture_root / "valid" / "episode-boundary.p2p-minimum.json"
    )

    assert transition["mesh_membership_digest"]["hex"] == mesh_digest
    assert finality["mesh_membership_digest"]["hex"] == mesh_digest
    assert boundary["p2p_barrier"]["mesh_membership_digest"]["hex"] == mesh_digest
    assert transition["membership_generation"] == mesh["membership_generation"]
    assert finality["frozen_peer_actor_ids"] == mesh["peer_actor_ids"]
    assert boundary["p2p_barrier"]["frozen_peer_actor_ids"] == mesh["peer_actor_ids"]

    decision = transition["applied_decisions"][0]
    assert decision["decision_id"] == decision_result["decision_id"]
    assert decision["actor_id"] == decision_result["p2p_authority"]["bot_actor_id"]
    assert decision["action_digest"] == decision_result["action_digest"]
    assert decision["decision_result_digest"]["hex"] == canonical_digest(decision_result)
    assert decision["publisher_actor_id"] == max(mesh["peer_actor_ids"])
    assert decision["publisher_actor_id"] == decision_result["p2p_authority"]["authority_actor_id"]
    assert decision["publisher_generation"] == decision_result["p2p_authority"]["authority_fence"]["generation"]
    # ADR-0005 remains intact: an external decision is server-authoritative;
    # the designated peer exclusively publishes the recorded action into P2P.
    assert decision["decision_authority"] == "server"


def test_api07_episode_end_is_an_exclusive_minimum_barrier() -> None:
    boundary = strict_json_load(
        FAMILY.fixture_root / "valid" / "episode-boundary.p2p-minimum.json"
    )
    endings = boundary["p2p_barrier"]["peer_end_frames"]
    assert boundary["end_frame_exclusive"] == min(
        item["end_frame_exclusive"] for item in endings
    )


def test_api07_exposes_no_per_step_code_injection_surface() -> None:
    serialized_schema = json.dumps(FAMILY.schema, sort_keys=True)
    assert "on_game_step_code" not in serialized_schema
