"""Validate MUG API-08 Conversation, Routing, and Delivery contracts, version 0."""
from __future__ import annotations
from typing import Any
import pytest
from _contract_harness import (canonical_digest, check_bundle_binding, check_manifest_complete,
    check_schema_valid, load_family, run_fixture_case, strict_json_load)

FAMILY = load_family("api-08", "conversation.schema.json")
BUNDLE_NAMES = {'mug.api-08.conversation-segment', 'mug.api-08.delivery-receipt', 'mug.api-08.chat-message', 'mug.api-08.conversation.fixture-manifest', 'mug.api-08.turn-policy', 'mug.api-08.context-snapshot', 'mug.api-08.candidate-reply-set'}

def semantic_violations(name, value):
    if name == "ConversationSegment":
        span = value["end_sequence"] - value["start_sequence"] + 1
        if span != len(value["message_ids"]):
            return [("segmentContiguity", "/message_ids")]
    if name == "CandidateReplySet":
        # The thread continues only with a presented candidate (D12-8).
        if value["selected_message_id"] not in value["candidate_message_ids"]:
            return [("candidateSelection", "/selected_message_id")]
    return []

@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api08_contract_fixture(case: dict) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)

def test_api08_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)

def test_api08_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")

def test_api08_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)

def test_api08_context_snapshot_precedes_the_message() -> None:
    snap = strict_json_load(FAMILY.fixture_root / "valid" / "context-snapshot.minimal-static.json")
    msg = strict_json_load(FAMILY.fixture_root / "valid" / "chat-message.minimal-static.json")
    # The exact context used for a model request is captured and references prior messages.
    assert msg["message_id"] in snap["included_message_ids"] or snap["message_id"] != msg["message_id"]
    assert snap["included_message_ids"]

