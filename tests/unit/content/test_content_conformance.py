"""Schema-authority conformance for the content (API-17) models.

The frozen API-17 bundle is the authority. This test binds the content models to
it through the golden fixtures: what the schema accepts, the model parses; what
the schema rejects, the model rejects. Several invariants (``duplicateField``,
``accessibilityFloor``, ``gateAnchorMismatch``, and the content-body and form
constraints) live in the models as validators, so at the semantic layer the
model is stricter than the raw schema and the test compares to the manifest.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mug.content import (
    AccessibilityProfile,
    ContentBody,
    ContentSpec,
    FormResponse,
    FormSpec,
    GateControl,
    PresentationComponent,
    content_schema,
)

_FIXTURES = (
    Path(__file__).resolve().parents[3] / "docs/architecture/phase-0/api-17/fixtures/v0"
)

_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "ContentSpec": ContentSpec.model_validate,
    "ContentBody": ContentBody.model_validate,
    "FormSpec": FormSpec.model_validate,
    "FormResponse": FormResponse.model_validate,
    "PresentationComponent": PresentationComponent.model_validate,
    "GateControl": GateControl.model_validate,
    "AccessibilityProfile": AccessibilityProfile.model_validate,
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
    """The content model verdict matches the manifest for every case."""
    def_name = _def_name(case["schema_ref"])
    validate = _VALIDATORS.get(def_name)
    assert validate is not None, f"no content validator for {def_name}"

    instance = _instance(case["instance"])
    if case["expect"] == "valid":
        validate(instance)
    else:
        with pytest.raises(ValidationError):
            validate(instance)


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_model_agrees_with_frozen_schema(case: dict[str, Any]) -> None:
    """At the pure-schema layer the model and the frozen schema give one verdict."""
    if case.get("validation_layer") == "semantic":
        pytest.skip("model is stricter than the raw schema at the semantic layer")

    schema = content_schema()
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
    """A valid fixture's schema reference pins the frozen API-17 bundle digest."""
    schema = content_schema()
    spec = _instance("valid/content-spec.inline-markdown.json")
    assert spec["schema"]["digest"]["hex"] == schema.bundle_digest
