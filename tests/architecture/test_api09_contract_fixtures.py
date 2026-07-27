"""Validate MUG API-09 Participant Client, Realtime, and Uploads contracts, version 0."""
from __future__ import annotations

import hashlib
from typing import Any
import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-09", "client.schema.json")
BUNDLE_NAMES = {'mug.api-09.realtime-command', 'mug.api-09.client-handshake', 'mug.api-09.seat-delivery', 'mug.api-09.transport-ack', 'mug.api-09.upload-ticket', 'mug.api-09.input-scheme', 'mug.api-09.bridge-message', 'mug.api-09.monitoring-measurement', 'mug.api-09.gate-op', 'mug.api-09.client.fixture-manifest'}

RESERVED_BRIDGE_KEYS = {"participant", "participant_id", "enrollment_id", "identity",
    "seat", "seat_key", "condition", "treatment", "assignment"}

def semantic_violations(name: str, value: Any) -> list:
    hits = []
    if name == "TransportAck" and value["ack_kind"] == "accepted" and "stream_position" not in value:
        hits.append(("ackEvidence", "/ack_kind"))
    if name == "BridgeMessage" and value.get("key") in RESERVED_BRIDGE_KEYS:
        hits.append(("bridgeUntrusted", "/key"))
    if name == "MonitoringMeasurement":
        metrics = [item["metric"] for item in value["measurements"]]
        if len(metrics) != len(set(metrics)):
            hits.append(("uniqueMeasurementMetric", "/measurements"))
    if name == "GateOp" and value["target"] == "join" and value["anchor"]["anchor_kind"] != "interaction":
        hits.append(("gateAnchorTarget", "/anchor/anchor_kind"))
    if name == "P2PMeshBootstrap":
        # One peer is one seat. A handle repeated in the peer set would have the
        # room negotiate with itself, and a bootstrap is what freezes the mesh.
        handles = [peer["peer_handle"] for peer in value["peers"]]
        if len(handles) != len(set(handles)):
            hits.append(("bootstrapHandles", "/peers"))
    if name == "P2PCaptureSubmission":
        # The digest binds the payload the peer really submitted. A submission
        # whose digest does not match its own bytes is unusable as evidence.
        digested = hashlib.sha256(value["payload_json"].encode("utf-8")).hexdigest()
        if value["payload_digest"]["hex"] != digested:
            hits.append(("capturePayloadDigest", "/payload_digest"))
    return hits

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api09_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api09_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api09_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api09_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)

