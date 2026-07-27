"""Schema-authority conformance for the authoring (API-01) models.

The frozen API-01 bundle is the authority. This test binds the authoring models
to it through the golden fixtures: what the schema accepts, the model parses;
what the schema rejects, the model rejects. Several invariants (for example
``duplicateDefinitionKey``, ``missingNode``, ``clientDisclosure``, and
``artifactDigest``) live in the models as validators, so at the semantic layer
the model is stricter than the raw schema and the test compares to the manifest.

The publication layer forbids a version-zero schema in a published record. The
record models do not gate publication; version 0 is a legal draft record. So the
model accepts what the publication layer alone rejects, and the test expects that.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mug.authoring import (
    AuthoringDocument,
    CapabilityRequirement,
    ClientManifest,
    CodePackageRef,
    CompiledStudyCandidate,
    Diagnostic,
    FlowSpec,
    GitProvenance,
    ManifestArtifact,
    ManifestSet,
    ProvenanceManifest,
    PublishedStudyVersion,
    ScientificManifest,
    SecretRequirement,
    ServerRuntimeBindingBase,
    StudyPublicationResult,
    StudyServerManifest,
    ValidationReport,
    authoring_schema,
)

_FIXTURES = (
    Path(__file__).resolve().parents[3] / "docs/architecture/phase-0/api-01/fixtures/v0"
)

_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "AuthoringDocument": AuthoringDocument.model_validate,
    "CapabilityRequirement": CapabilityRequirement.model_validate,
    "ClientManifest": ClientManifest.model_validate,
    "CodePackageRef": CodePackageRef.model_validate,
    "CompiledStudyCandidate": CompiledStudyCandidate.model_validate,
    "Diagnostic": Diagnostic.model_validate,
    "FlowSpec": FlowSpec.model_validate,
    "GitProvenance": GitProvenance.model_validate,
    "ManifestArtifact": ManifestArtifact.model_validate,
    "ManifestSet": ManifestSet.model_validate,
    "ProvenanceManifest": ProvenanceManifest.model_validate,
    "PublishedStudyVersion": PublishedStudyVersion.model_validate,
    "ScientificManifest": ScientificManifest.model_validate,
    "SecretRequirement": SecretRequirement.model_validate,
    "ServerRuntimeBindingBase": ServerRuntimeBindingBase.model_validate,
    "StudyPublicationResult": StudyPublicationResult.model_validate,
    "StudyServerManifest": StudyServerManifest.model_validate,
    "ValidationReport": ValidationReport.model_validate,
}


def _cases() -> list[dict[str, Any]]:
    manifest = json.loads((_FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    return manifest["cases"]


def _def_name(schema_ref: str) -> str:
    return schema_ref.split("#/$defs/", 1)[1]


def _instance(relative: str) -> Any:
    return json.loads((_FIXTURES / relative).read_text(encoding="utf-8"))


_CASES = _cases()
_CASE_IDS = [case["id"] for case in _CASES]


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_model_matches_manifest(case: dict[str, Any]) -> None:
    """The authoring model verdict matches the manifest for every case."""
    def_name = _def_name(case["schema_ref"])
    validate = _VALIDATORS.get(def_name)
    assert validate is not None, f"no authoring validator for {def_name}"

    instance = _instance(case["instance"])
    if case["expect"] == "valid":
        validate(instance)
    elif case.get("validation_layer") == "publication":
        # The record model does not gate publication; a version-zero draft
        # record is legal here. The publication compiler, not the record,
        # forbids it, so the model accepts what this layer alone rejects.
        validate(instance)
    else:
        with pytest.raises(ValidationError):
            validate(instance)


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_model_agrees_with_frozen_schema(case: dict[str, Any]) -> None:
    """At the pure-schema layer the model and the frozen schema give one verdict."""
    if case.get("validation_layer") in {"semantic", "publication"}:
        pytest.skip("model differs from the raw schema above the pure-schema layer")

    schema = authoring_schema()
    def_name = _def_name(case["schema_ref"])
    instance = _instance(case["instance"])

    schema_valid = schema.is_valid(def_name, instance)
    model_valid = True
    try:
        _VALIDATORS[def_name](instance)
    except ValidationError:
        model_valid = False

    assert schema_valid == (case["expect"] == "valid")
    assert model_valid == schema_valid


def test_valid_fixtures_round_trip() -> None:
    """Each valid fixture serializes back to its exact bytes."""
    for case in _CASES:
        if case["expect"] != "valid":
            continue
        def_name = _def_name(case["schema_ref"])
        instance = _instance(case["instance"])
        model = _VALIDATORS[def_name](instance)
        assert model.model_dump(mode="json", exclude_none=True) == instance


def test_pinned_schema_ref_matches_bundle_digest() -> None:
    """A valid fixture's schema reference pins the frozen API-01 bundle digest."""
    schema = authoring_schema()
    document = _instance("valid/authoring-document.minimal-static.json")
    assert document["schema"]["digest"]["hex"] == schema.bundle_digest
