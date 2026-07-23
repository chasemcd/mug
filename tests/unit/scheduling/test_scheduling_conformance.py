"""Schema-authority conformance for the scheduling (API-12) models.

The frozen API-12 bundle is the authority. This test binds the scheduling models
to it through the golden fixtures: what the schema accepts, the model parses;
what the schema rejects, the model rejects. Several invariants (the p2p authority
selection and binding, the produced-result evidence, and the realtime fallback)
live in the models as validators, so at the semantic layer the model is stricter
than the raw schema and the test compares to the manifest.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mug.scheduling import (
    ControllerPolicy,
    DecisionRequest,
    DecisionResult,
    FallbackPolicy,
    P2PBotAuthority,
    SchedulerState,
    scheduling_schema,
)

_FIXTURES = (
    Path(__file__).resolve().parents[3] / "docs/architecture/phase-0/api-12/fixtures/v0"
)

_VALIDATORS: dict[str, Callable[[Any], Any]] = {
    "ControllerPolicy": ControllerPolicy.model_validate,
    "DecisionRequest": DecisionRequest.model_validate,
    "DecisionResult": DecisionResult.model_validate,
    "FallbackPolicy": FallbackPolicy.model_validate,
    "P2PBotAuthority": P2PBotAuthority.model_validate,
    "SchedulerState": SchedulerState.model_validate,
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


# One invalid case is cross-record: a p2p decision result whose authority actor
# does not match the bound bot authority record. Only the scheduler runtime, which
# holds the live authority, can reject it. A standalone record cannot, so the
# record model accepts this fixture and the manifest check skips it here.
_CROSS_RECORD_CASES = {"decision-result.invalid.p2p-wrong-authority"}


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_model_matches_manifest(case: dict[str, Any]) -> None:
    """The scheduling model verdict matches the manifest for every case."""
    if case["id"] in _CROSS_RECORD_CASES:
        pytest.skip("cross-record authority binding is a scheduler-runtime invariant")

    def_name = _def_name(case["schema_ref"])
    validate = _VALIDATORS.get(def_name)
    assert validate is not None, f"no scheduling validator for {def_name}"

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

    schema = scheduling_schema()
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
    """A valid fixture's schema reference pins the frozen API-12 bundle digest."""
    schema = scheduling_schema()
    state = _instance("valid/scheduler-state.minimal-static.json")
    assert state["schema"]["digest"]["hex"] == schema.bundle_digest
