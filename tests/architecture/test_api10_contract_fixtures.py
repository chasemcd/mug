"""Validate MUG API-10 Events, Capture, and Provenance contracts, version 0."""
from __future__ import annotations
from typing import Any
import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-10", "evidence.schema.json")
BUNDLE_NAMES = {'mug.api-10.capture-policy', 'mug.api-10.evidence.fixture-manifest', 'mug.api-10.experienced-frame', 'mug.api-10.event-envelope'}

def semantic_violations(name, value):
    hits = []
    if name == "CapturePolicy":
        streams = value["streams"]
        for i, rule in enumerate(streams):
            if rule["stream_kind"] == "experienced" and rule["profile"] != "experienced":
                hits.append(("streamProfile", f"/streams/{i}/profile"))
            if rule["stream_kind"] != "experienced" and rule["profile"] == "experienced":
                hits.append(("streamProfile", f"/streams/{i}/profile"))
        # RP-9: capturing the experienced stream requires also capturing the
        # canonical post-rollback truth it is joinable to (dual-stream capture).
        profiles = {rule["profile"] for rule in streams}
        if "experienced" in profiles and "canonical" not in profiles:
            hits.append(("experiencedRequiresCanonical", "/streams"))
    if name == "ExperiencedFrame":
        # RP-9: a corrected frame supersedes a speculative one and must carry the
        # linkage to the canonical frame that superseded it.
        if value["delivery_kind"] == "corrected" and "canonical_event_id" not in value:
            hits.append(("correctedRequiresCanonical", "/canonical_event_id"))
    return hits

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api10_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api10_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api10_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api10_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)

def test_api10_producer_positions_are_monotonic() -> None:
    e1 = strict_json_load(FAMILY.fixture_root / "valid" / "event-envelope.seq1.json")
    e2 = strict_json_load(FAMILY.fixture_root / "valid" / "event-envelope.seq2.json")
    assert e1["producer_position"]["epoch_id"] == e2["producer_position"]["epoch_id"]
    assert e2["producer_position"]["sequence"] > e1["producer_position"]["sequence"]
    assert e2["causation_event_id"] == e1["event_id"]


def test_api10_experienced_stream_covers_every_delivery_kind() -> None:
    # RP-9: the experienced stream classifies every rendered frame by delivery
    # kind and stays joinable to the canonical stream.
    stems = {
        "delivered": "experienced-frame.delivered",
        "speculative": "experienced-frame.minimal-static",
        "corrected": "experienced-frame.corrected",
        "skipped": "experienced-frame.skipped",
    }
    frames = {
        kind: strict_json_load(FAMILY.fixture_root / "valid" / f"{stem}.json")
        for kind, stem in stems.items()
    }
    assert {frame["delivery_kind"] for frame in frames.values()} == {
        "delivered",
        "speculative",
        "corrected",
        "skipped",
    }
    # A delivered, corrected, or skipped frame always links to its canonical frame.
    for kind in ("delivered", "corrected", "skipped"):
        assert "canonical_event_id" in frames[kind]
    # A corrected frame supersedes the speculative frame it replaces and links to
    # the same canonical frame the speculative one anticipated.
    corrected, speculative = frames["corrected"], frames["speculative"]
    assert corrected["supersedes_experienced_position"] == speculative["stream_position"]
    assert corrected["canonical_event_id"] == speculative["canonical_event_id"]


def test_api10_capture_policy_captures_both_streams_and_requires_canonical() -> None:
    # RP-9: a dual-stream policy captures both canonical and experienced streams;
    # experienced capture without canonical capture is a semantic violation.
    dual = strict_json_load(FAMILY.fixture_root / "valid" / "capture-policy.dual-stream.json")
    profiles = {rule["profile"] for rule in dual["streams"]}
    assert {"canonical", "experienced"} <= profiles
    experienced_only = strict_json_load(
        FAMILY.fixture_root / "invalid" / "capture-policy.experienced-without-canonical.json"
    )
    only_profiles = {rule["profile"] for rule in experienced_only["streams"]}
    assert "experienced" in only_profiles and "canonical" not in only_profiles

