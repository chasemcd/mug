"""Validate API-02 platform-composition and deployment contracts.

Covers the 0.2 two-verb surface (D03-1, D03-5; ADR-0015): an ungated
live/stopped `Deployment` aggregate, the internal immutable
`DeploymentRevision` created by `mug deploy`, pass-at-deploy secret bindings
held only as shared-kernel `SecretRef`s (D03-3; `Resolution.CURRENT` default),
the internal `SatisfactionReport` (satisfied iff every gap list is empty), and
the positive-allowlist `ClientDeploymentProjection`.
"""

from __future__ import annotations

from typing import Any, Iterable

import pytest

from _contract_harness import (
    canonical_digest,
    check_bundle_binding,
    check_manifest_complete,
    check_schema_valid,
    json_pointer,
    load_family,
    run_fixture_case,
    strict_json_load,
)

FAMILY = load_family("api-02", "platform-deployment.schema.json")
BUNDLE_NAMES = {
    "mug.api-02.deployment-requirement",
    "mug.api-02.deployment",
    "mug.api-02.deployment-revision",
    "mug.api-02.client-deployment",
    "mug.api-02.satisfaction-report",
    "mug.api-02.fixture-manifest",
}
SECRET_MATERIAL_KEYS = {"credential", "password", "secret_value", "token", "api_key"}


def _secret_material_violations(
    value: Any, path: tuple[Any, ...] = ()
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in SECRET_MATERIAL_KEYS:
                violations.append(("secretMaterial", json_pointer((*path, key))))
            violations.extend(_secret_material_violations(child, (*path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(_secret_material_violations(child, (*path, index)))
    return violations


def _revision_violations(rev: dict[str, Any]) -> list[tuple[str, str]]:
    violations = _secret_material_violations(rev)

    seen_secret_keys: set[str] = set()
    for index, binding in enumerate(rev["secret_bindings"]):
        if binding["requirement_key"] in seen_secret_keys:
            violations.append(
                (
                    "duplicateSecretKey",
                    json_pointer(("secret_bindings", index, "requirement_key")),
                )
            )
        seen_secret_keys.add(binding["requirement_key"])

    for index, binding in enumerate(rev.get("provider_bindings", [])):
        if binding["secret_requirement_key"] not in seen_secret_keys:
            violations.append(
                (
                    "providerSecretBinding",
                    json_pointer(
                        ("provider_bindings", index, "secret_requirement_key")
                    ),
                )
            )

    seen_slots: set[str] = set()
    for index, binding in enumerate(rev["execution_bindings"]):
        if binding["slot"] in seen_slots:
            violations.append(
                (
                    "duplicateExecutionSlot",
                    json_pointer(("execution_bindings", index, "slot")),
                )
            )
        seen_slots.add(binding["slot"])
    return violations


def _report_violations(report: dict[str, Any]) -> list[tuple[str, str]]:
    consistent = not (
        report["unbound_secret_requirements"]
        or report["missing_execution_slots"]
        or report["region_gaps"]
    )
    if report["satisfied"] != consistent:
        return [("satisfiedConsistency", "/satisfied")]
    return []


def _deployment_violations(deployment: dict[str, Any]) -> list[tuple[str, str]]:
    if deployment["current_revision"]["deployment_id"] != deployment["deployment_id"]:
        return [("revisionDeploymentMismatch", "/current_revision/deployment_id")]
    return []


def semantic_violations(name: str, value: Any) -> list[tuple[str, str]]:
    if name == "DeploymentRevision":
        return _revision_violations(value)
    if name == "SatisfactionReport":
        return _report_violations(value)
    if name == "Deployment":
        return _deployment_violations(value)
    if name == "ClientDeploymentProjection":
        return _secret_material_violations(value)
    return []


@pytest.mark.parametrize("case", FAMILY.cases, ids=lambda case: case["id"])
def test_api02_contract_fixture(case: dict[str, Any]) -> None:
    run_fixture_case(FAMILY, case, semantic_violations)


def test_api02_schema_is_valid_and_all_references_resolve_offline() -> None:
    check_schema_valid(FAMILY)


def test_api02_fixture_manifest_is_valid_unique_and_complete() -> None:
    check_manifest_complete(FAMILY, f"{FAMILY.schema['$id']}#/$defs/FixtureManifest")


def test_api02_schema_refs_bind_the_current_bundle() -> None:
    check_bundle_binding(FAMILY, BUNDLE_NAMES)


def _fixture(name: str) -> Any:
    return strict_json_load(FAMILY.fixture_root / "valid" / name)


def test_api02_revision_satisfies_pinned_requirement() -> None:
    requirement = _fixture("deployment-requirement.minimal-static.json")
    revision = _fixture("deployment-revision.minimal-static.json")

    # The revision pins the exact composed-requirement bytes it was checked
    # against, so a later requirement change cannot silently count as satisfied.
    assert revision["requirement_digest"]["hex"] == canonical_digest(requirement)

    data = requirement["data"]

    # Secret completeness: every non-optional requirement key is bound.
    bound = {binding["requirement_key"] for binding in revision["secret_bindings"]}
    for secret in data["secret_requirements"]:
        if not secret["optional"]:
            assert secret["requirement_key"] in bound

    # Execution coverage: every (slot, runtime) has a build binding.
    provided_slots = {
        (binding["slot"], binding["runtime"])
        for binding in revision["execution_bindings"]
    }
    for slot in data["execution_slots"]:
        assert (slot["slot"], slot["runtime"]) in provided_slots

    # Region policy: the deploy's region is allowed by the requirement.
    assert revision["region"] in data["region_policy"]["allowed_regions"]


def test_api02_client_projection_closes_over_the_revision() -> None:
    revision = _fixture("deployment-revision.minimal-static.json")
    projection = _fixture("client-deployment.minimal-static.json")

    reference = projection["deployment"]
    assert reference["manifest_digest"]["hex"] == canonical_digest(revision)
    assert reference["deployment_revision_id"] == revision["deployment_revision_id"]
    assert reference["study_version"] == revision["study_version"]

    # A projection exposes only the revision's participant endpoints; it can
    # neither invent an endpoint nor surface an internal one.
    participant_endpoints = {
        (endpoint["role"], endpoint["url"])
        for endpoint in revision["endpoints"]
        if endpoint["audience"] == "participant"
    }
    for endpoint in projection["endpoints"]:
        assert (endpoint["role"], endpoint["url"]) in participant_endpoints


def test_api02_dispositions_pin_the_recorded_revision() -> None:
    revision = _fixture("deployment-revision.minimal-static.json")
    for name in ("deployment.live-static.json", "deployment.stopped-static.json"):
        deployment = _fixture(name)
        # `mug stop` flips the disposition only; the recorded revision (which
        # in-flight visits pin, NS-08) is byte-identical in both dispositions.
        reference = deployment["current_revision"]
        assert reference["deployment_id"] == revision["deployment_id"]
        assert reference["manifest_digest"]["hex"] == canonical_digest(revision)
        assert deployment["study_id"] == revision["study_version"]["study_id"]
