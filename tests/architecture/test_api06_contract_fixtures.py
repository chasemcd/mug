"""Validate MUG API-06 Interactions, Channels, Groups, and Leases contracts, version 0."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from _contract_harness import (
    check_bundle_binding,
    check_manifest_complete,
    check_schema_valid,
    load_family,
    run_fixture_case,
    strict_json_load,
)

FAMILY = load_family("api-06", "interaction.schema.json")
BUNDLE_NAMES = {
    "mug.api-06.interaction",
    "mug.api-06.channel-instance",
    "mug.api-06.membership",
    "mug.api-06.p2p-mesh-membership",
    "mug.api-06.mesh-latency-probe",
    "mug.api-06.group",
    "mug.api-06.connection-lease",
    "mug.api-06.matchmaking-ticket",
    "mug.api-06.interaction.fixture-manifest",
}

# D08-2: channel kinds are a closed typed set and each kind carries its own
# ordering guarantee — the author picks the kind, never the ordering mechanics.
KIND_ORDERING = {"game": "per-producer", "chat": "total", "annotation": "total"}


def semantic_violations(name: str, value: Any) -> list[tuple[str, str]]:
    if name == "ChannelInstance":
        if value["ordering"] != KIND_ORDERING[value["channel_type"]]:
            return [("channelOrdering", "/ordering")]
        return []
    if name == "Group":
        # R-18: a formed group has exactly its declared N members.
        if value["status"] == "formed" and len(value["members"]) != value["size"]:
            return [("groupSize", "/members")]
        return []
    if name == "P2PMeshMembership":
        if value["peer_actor_ids"] != sorted(value["peer_actor_ids"]):
            return [("canonicalPeerOrder", "/peer_actor_ids")]
        return []
    if name == "MonitoringPolicy":
        # RP-6: the warn-then-exclude ladder is an ordered escalation; each rung
        # fires at a strictly higher accumulated-violation count than the last.
        thresholds = [step["at_violations"] for step in value["ladder"]]
        if thresholds != sorted(thresholds) or len(thresholds) != len(set(thresholds)):
            return [("ladderOrder", "/ladder")]
        return []
    if name == "MeshLatencyProbe":
        # RP-7: a latency-bounded mesh forms only when every unordered pair of
        # peers is probed and each probed RTT is within max_p2p_rtt.
        max_us = value["max_p2p_rtt"]["microseconds"]
        peers = sorted(set(value["peer_actor_ids"]))
        observed = {frozenset(entry["peers"]) for entry in value["pairwise_rtts"]}
        expected = {frozenset(pair) for pair in itertools.combinations(peers, 2)}
        over_bound = any(
            entry["rtt"]["microseconds"] > max_us for entry in value["pairwise_rtts"]
        )
        if over_bound or observed != expected:
            return [("allPairsWithinRtt", "/pairwise_rtts")]
        return []
    return []


@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api06_contract_fixture(case: dict[str, Any]) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)


def test_api06_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)


def test_api06_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")


def test_api06_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)


def test_api06_four_peer_mesh_binds_existing_group_and_game_channel() -> None:
    mesh = strict_json_load(
        FAMILY.fixture_root / "valid" / "p2p-mesh-membership.four-peer.json"
    )
    group = strict_json_load(FAMILY.fixture_root / "valid" / "group.formed.json")
    channel = strict_json_load(
        FAMILY.fixture_root / "valid" / "channel-instance.game.json"
    )

    assert mesh["interaction_id"] == channel["interaction_id"]
    assert mesh["group_id"] == group["group_id"]
    assert mesh["channel_key"] == channel["channel_key"]
    assert channel["channel_type"] == "game"
    assert len(mesh["peer_actor_ids"]) == group["size"]


def test_api06_monitoring_policy_is_server_authoritative_and_fail_closed() -> None:
    # RP-6/RP-10: monitoring is server-side contract state, not client-trusted;
    # the researcher callback boundary defaults to fail_closed with explicit
    # fail_open opt-in, and an Interaction may carry the policy.
    policy = strict_json_load(
        FAMILY.fixture_root / "valid" / "monitoring-policy.warn-then-exclude.json"
    )
    assert policy["enforcement"] == "server-authoritative"
    assert [step["action"] for step in policy["ladder"]][-1] == "exclude"
    assert policy["callback"]["on_error"] == "fail_closed"
    assert "." in policy["callback"]["handler"]

    fail_open = strict_json_load(
        FAMILY.fixture_root / "valid" / "monitoring-policy.fail-open.json"
    )
    assert fail_open["callback"]["on_error"] == "fail_open"

    interaction = strict_json_load(
        FAMILY.fixture_root / "valid" / "interaction.monitored.json"
    )
    assert interaction["monitoring"]["enforcement"] == "server-authoritative"


def test_api06_mesh_probe_binds_existing_mesh_and_covers_all_pairs() -> None:
    # RP-7: the probe carries the complete all-pairs RTT set for the same mesh
    # peers as P2PMeshMembership, within the latency ticket's max_p2p_rtt.
    probe = strict_json_load(
        FAMILY.fixture_root / "valid" / "mesh-latency-probe.all-pairs.json"
    )
    mesh = strict_json_load(
        FAMILY.fixture_root / "valid" / "p2p-mesh-membership.four-peer.json"
    )
    ticket = strict_json_load(
        FAMILY.fixture_root / "valid" / "matchmaking-ticket.latency.json"
    )
    assert probe["interaction_id"] == mesh["interaction_id"]
    assert probe["group_id"] == mesh["group_id"]
    assert probe["channel_key"] == mesh["channel_key"]
    assert probe["peer_actor_ids"] == mesh["peer_actor_ids"]
    assert probe["membership_generation"] == mesh["membership_generation"]
    assert probe["max_p2p_rtt"] == ticket["match"]["max_p2p_rtt"]

    peers = probe["peer_actor_ids"]
    observed = {frozenset(entry["peers"]) for entry in probe["pairwise_rtts"]}
    expected = {frozenset(pair) for pair in itertools.combinations(peers, 2)}
    assert observed == expected
    assert all(
        entry["rtt"]["microseconds"] <= probe["max_p2p_rtt"]["microseconds"]
        for entry in probe["pairwise_rtts"]
    )
