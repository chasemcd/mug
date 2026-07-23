"""Schema-authority conformance for the jobs (API-22) models.

The frozen API-22 bundle is the authority. This test binds the job models to it
through the golden fixtures: what the schema accepts, the model parses; what the
schema rejects, the model rejects. Two invariants (``jobResult`` on ``JobRun`` and
on ``JobResult``) live in the models as validators, so at the semantic layer the
model is stricter than the raw schema and the test compares to the manifest.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from mug.jobs import (
    FirstClassJobKind,
    JobRequest,
    JobResult,
    JobRun,
    jobs_schema,
)

_FIXTURES = (
    Path(__file__).resolve().parents[3] / "docs/architecture/phase-0/api-22/fixtures/v0"
)

_FIRST_CLASS: TypeAdapter[FirstClassJobKind] = TypeAdapter(FirstClassJobKind)

_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "JobRequest": JobRequest.model_validate,
    "JobRun": JobRun.model_validate,
    "JobResult": JobResult.model_validate,
    "FirstClassJobKind": _FIRST_CLASS.validate_python,
}


def _cases() -> list[dict[str, Any]]:
    manifest = json.loads((_FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    return manifest["cases"]


def _def_name(schema_ref: str) -> str:
    return schema_ref.split("#/$defs/", 1)[1]


def _instance(relative: str) -> Any:
    return json.loads((_FIXTURES / relative).read_text(encoding="utf-8"))


def _dump(model: Any) -> Any:
    """Serialize a validated value: an object via model_dump, a scalar as itself."""
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", exclude_none=True)
    return model


_CASES = _cases()
_CASE_IDS = [case["id"] for case in _CASES]


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_model_matches_manifest(case: dict[str, Any]) -> None:
    """The job model verdict matches the manifest for every case."""
    def_name = _def_name(case["schema_ref"])
    validate = _VALIDATORS.get(def_name)
    assert validate is not None, f"no job validator for {def_name}"

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

    schema = jobs_schema()
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
        assert _dump(model) == instance


def test_pinned_schema_ref_matches_bundle_digest() -> None:
    """A valid fixture's schema reference pins the frozen API-22 bundle digest."""
    schema = jobs_schema()
    request = _instance("valid/job-request.minimal-static.json")
    assert request["schema"]["digest"]["hex"] == schema.bundle_digest
