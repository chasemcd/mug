"""Integrated Phase 0 corpus checks: every family is present and consistent, and
the cross-cutting gate documents cover every scenario and trust boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from _contract_harness import PHASE_0_ROOT, canonical_digest, strict_json_load

FAMILY_SCHEMAS = {
    "api-01": "study-authoring.schema.json",
    "api-02": "platform-deployment.schema.json",
    "api-03": "identity-enrollment.schema.json",
    "api-04": "visit-plan.schema.json",
    "api-05": "actor.schema.json",
    "api-06": "interaction.schema.json",
    "api-07": "game.schema.json",
    "api-08": "conversation.schema.json",
    "api-09": "client.schema.json",
    "api-10": "evidence.schema.json",
    "api-11": "storage.schema.json",
    "api-12": "scheduler.schema.json",
    "api-13": "provider.schema.json",
    "api-14": "tools.schema.json",
    "api-15": "memory.schema.json",
    "api-16": "replay.schema.json",
    "api-17": "content.schema.json",
    "api-18": "preference.schema.json",
    "api-19": "export.schema.json",
    "api-22": "jobs.schema.json",
}

# Families retired from the active contract corpus. Each keeps index.md and
# review-record.md tombstones but has no schemas or fixtures:
# - api-20 (governance) removed under F-4 / ADR-0015: governance is out of scope.
# - api-21 (plugins) retracted for v0 under D15-1..3 / ADR-0015: no plugin
#   framework; extensions are plain Python.
RETIRED_FAMILIES = ("api-20", "api-21")


def test_every_api_family_has_a_complete_document_set() -> None:
    for family, schema_file in FAMILY_SCHEMAS.items():
        root = PHASE_0_ROOT / family
        assert (root / "index.md").is_file(), family
        assert (root / "review-record.md").is_file(), family
        assert (root / "schemas" / "v0" / schema_file).is_file(), family
        assert (root / "fixtures" / "v0" / "manifest.json").is_file(), family


def test_retired_families_are_tombstoned() -> None:
    for family in RETIRED_FAMILIES:
        root = PHASE_0_ROOT / family
        assert (root / "index.md").is_file(), family
        assert (root / "review-record.md").is_file(), family
        assert not (root / "schemas").exists(), family
        assert not (root / "fixtures").exists(), family


def test_all_22_families_are_present() -> None:
    assert len(FAMILY_SCHEMAS) == 20
    assert len(RETIRED_FAMILIES) == 2
    assert len(FAMILY_SCHEMAS) + len(RETIRED_FAMILIES) == 22
    assert not set(RETIRED_FAMILIES) & set(FAMILY_SCHEMAS)


def test_family_bundle_digests_are_distinct() -> None:
    digests = {}
    for family, schema_file in FAMILY_SCHEMAS.items():
        schema = strict_json_load(
            PHASE_0_ROOT / family / "schemas" / "v0" / schema_file
        )
        digests[family] = canonical_digest(schema)
    assert len(set(digests.values())) == len(digests), digests


def test_family_manifest_suites_are_unique() -> None:
    suites = []
    for family in FAMILY_SCHEMAS:
        manifest = strict_json_load(
            PHASE_0_ROOT / family / "fixtures" / "v0" / "manifest.json"
        )
        suites.append(manifest["suite"])
    assert len(set(suites)) == len(suites)


def test_integrated_walkthrough_covers_every_scenario() -> None:
    text = (PHASE_0_ROOT / "integrated-walkthrough.md").read_text()
    for n in range(1, 13):
        assert f"NS-{n:02d}" in text, f"NS-{n:02d} missing from walkthrough"


def test_threat_model_covers_every_boundary() -> None:
    text = (PHASE_0_ROOT / "threat-model.md").read_text()
    for n in range(1, 11):
        assert f"B{n}" in text, f"boundary B{n} missing from threat model"


def test_backlog_orders_every_family() -> None:
    text = (PHASE_0_ROOT / "implementation-backlog.md").read_text()
    for family in FAMILY_SCHEMAS:
        token = "API-" + family.split("-")[1]
        assert token in text, f"{token} missing from backlog"
