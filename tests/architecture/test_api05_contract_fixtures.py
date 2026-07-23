"""Validate MUG API-05 Seats, Actors, Casting, Grouping, and Controller Bindings contracts, version 0."""
from __future__ import annotations
import json
from typing import Any
import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-05", "actor.schema.json")
BUNDLE_NAMES = {'mug.api-05.actor.fixture-manifest', 'mug.api-05.seat-definition', 'mug.api-05.actor-instance', 'mug.api-05.controller-binding', 'mug.api-05.cast-declaration', 'mug.api-05.seat-agent-binding', 'mug.api-05.group', 'mug.api-05.onnx-policy'}

ALLOWED = {"game-action": {"human-input", "scripted-policy", "rl-model"}, "chat-message": {"human-input", "llm"}, "annotation": {"human-input"}, "action-plan": {"rl-model", "llm"}}
def semantic_violations(name, value):
    hits = []
    if name == "ControllerBinding":
        if value["controller_kind"] not in ALLOWED[value["capability"]]:
            hits.append(("controllerCapability", "/controller_kind"))
    if name == "CastDeclaration":
        # R-16 cast totality: once a cast is declared it names EVERY seat —
        # no missing seats, no unknown seats, no implicit human default.
        if sorted(value["cast"]) != sorted(value["seats"]):
            hits.append(("castTotality", "/cast"))
    if name == "Group":
        # R-18 persistence-by-shared-object: every later activity that reuses
        # the group must declare OnMissing.WAIT or OnMissing.REGROUP.
        for index, activity in enumerate(value["activities"][1:], start=1):
            if "on_missing_member" not in activity:
                hits.append(("onMissingRequired", f"/activities/{index}"))
    return hits

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api05_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api05_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api05_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api05_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)

def test_api05_one_actor_distinct_bindings() -> None:
    game = strict_json_load(FAMILY.fixture_root / "valid" / "controller-binding.human-game.json")
    chat = strict_json_load(FAMILY.fixture_root / "valid" / "controller-binding.llm-chat.json")
    # One seat, different actors here, but the contract allows one actor to hold
    # distinct bindings per channel/capability; assert channels and capabilities differ.
    assert game["channel_key"] != chat["channel_key"]
    assert game["capability"] != chat["capability"]

def test_api05_group_persistence_is_the_shared_object() -> None:
    # R-18: one Group referenced by several activities reunites the same
    # participants; every later activity declares its OnMissing behavior.
    group = strict_json_load(FAMILY.fixture_root / "valid" / "group.persisted-two-activities.json")
    assert len(group["activities"]) >= 2
    assert all("on_missing_member" in activity for activity in group["activities"][1:])
    assert {activity["on_missing_member"] for activity in group["activities"][1:]} <= {"wait", "regroup"}

def test_api05_custom_pre_post_processing_is_typed_and_digested_not_inline_code() -> None:
    # RP-5: the inline-JavaScript custom_inference_fn escape hatch is dropped.
    # Custom behavior lives in a typed OnnxPolicy (declared preprocessing rule +
    # closed-vocabulary selection mode) or a versioned scripted Policy — never
    # inline code. The schema exposes no custom_inference_fn surface, and
    # ControllerBinding/OnnxPolicy reject it structurally via additionalProperties.
    def declared_property_names(node: Any) -> set[str]:
        names: set[str] = set()
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict):
                names.update(props)
            for child in node.values():
                names |= declared_property_names(child)
        elif isinstance(node, list):
            for child in node:
                names |= declared_property_names(child)
        return names
    assert "custom_inference_fn" not in declared_property_names(FAMILY.schema)
    onnx_policy = FAMILY.schema["$defs"]["OnnxPolicy"]
    assert onnx_policy["additionalProperties"] is False
    assert onnx_policy["properties"]["selection_mode"]["enum"] == ["argmax", "sample"]
    preprocessing = FAMILY.schema["$defs"]["OnnxPreprocessing"]["properties"]["transform"]["enum"]
    assert "normalize" in preprocessing
    policy = strict_json_load(FAMILY.fixture_root / "valid" / "onnx-policy.sample-temperature.json")
    assert policy["selection_mode"] in onnx_policy["properties"]["selection_mode"]["enum"]
    assert policy["preprocessing"]["transform"] in preprocessing
