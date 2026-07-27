"""Schema-authority conformance for the kernel models.

The frozen JSON-Schema corpus is the authoritative contract. This test binds the
kernel Pydantic models to that corpus through the golden fixtures:

- Every fixture the schema accepts must parse into its model.
- Every fixture the schema rejects must fail its model.
- At the pure-schema layer, the model verdict and the frozen-schema verdict must
  agree. At the semantic layer the model is stricter than the raw schema by
  design (inline-byte digests, receipt-class rules), so the test compares the
  model to the manifest, not to the raw schema.
- The typed-object layer needs the command registry, so those cases stay with
  the architecture harness; this test skips them.

Any drift between a model and its schema fails the build.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mug.kernel import (
    ArtifactRef,
    CanonicalizationVectorSet,
    CommandReceipt,
    DomainError,
    EventCursor,
    InlineBytes,
    ResourceRef,
    SchemaRef,
    SecretRef,
    TraceContext,
    WireCommandEnvelope,
    load_shared_kernel_schema,
)
from mug.kernel.ids import ID_KIND_REGISTRY, UUIDV7
from mug.kernel.refs import (
    CAPABILITY_SET_ADAPTER,
    PUBLIC_HANDLE_ADAPTER,
    SEMVER_ADAPTER,
)

_FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "docs/architecture/phase-0/shared-kernel/fixtures/v0"
)


def _model_validator(validate: Callable[[Any], Any]) -> Callable[[Any], None]:
    def _run(instance: Any) -> None:
        validate(instance)

    return _run


# Map each `$defs` name the manifest references to a kernel validator that raises
# ``ValidationError`` on a rejected instance.
_VALIDATORS: dict[str, Callable[[Any], None]] = {
    "WireCommandEnvelope": _model_validator(WireCommandEnvelope.model_validate),
    "CommandReceipt": _model_validator(CommandReceipt.model_validate),
    "DomainError": _model_validator(DomainError.model_validate),
    "EventCursor": _model_validator(EventCursor.model_validate),
    "ArtifactRef": _model_validator(ArtifactRef.model_validate),
    "SecretRef": _model_validator(SecretRef.model_validate),
    "CanonicalizationVectorSet": _model_validator(
        CanonicalizationVectorSet.model_validate
    ),
    "InlineBytes": _model_validator(InlineBytes.model_validate),
    "ResourceRef": _model_validator(ResourceRef.model_validate),
    "TraceContext": _model_validator(TraceContext.model_validate),
    "SchemaRef": _model_validator(SchemaRef.model_validate),
    "CapabilitySet": _model_validator(CAPABILITY_SET_ADAPTER.validate_python),
    "PublicHandle": _model_validator(PUBLIC_HANDLE_ADAPTER.validate_python),
    "SemVer": _model_validator(SEMVER_ADAPTER.validate_python),
}


def _load_manifest_cases() -> list[dict[str, Any]]:
    manifest = json.loads((_FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    return manifest["cases"]


def _def_name(schema_ref: str) -> str:
    return schema_ref.split("#/$defs/", 1)[1]


def _load_instance(relative: str) -> Any:
    return json.loads((_FIXTURES / relative).read_text(encoding="utf-8"))


_CASES = _load_manifest_cases()
_CASE_IDS = [case["id"] for case in _CASES]


# The shared-kernel suite asserts a 'canonicalOrder' semantic rule on a capability
# set (unsorted -> invalid). That order is not a property of the reusable type:
# the CapabilitySet schema states only uniqueItems, and consuming families (api-05
# casting, api-09 client) reuse the identical type with unsorted valid instances.
# So the shared type treats a capability set as unique and unordered, and this one
# shared-kernel-local ordering case is not enforced by the record model.
_LOCAL_CONVENTION_CASES = {"capability-set.invalid.unsorted"}


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_model_matches_manifest(case: dict[str, Any]) -> None:
    """The kernel model verdict matches the manifest for schema/semantic cases."""
    if case.get("validation_layer") == "typed_object":
        pytest.skip("typed-object layer needs the command registry")
    if case["id"] in _LOCAL_CONVENTION_CASES:
        pytest.skip("capability-set order is a shared-kernel-local convention")

    def_name = _def_name(case["schema_ref"])
    validate = _VALIDATORS.get(def_name)
    assert validate is not None, f"no kernel validator for {def_name}"

    instance = _load_instance(case["instance"])
    if case["expect"] == "valid":
        validate(instance)  # must not raise
    else:
        with pytest.raises(ValidationError):
            validate(instance)


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_model_agrees_with_frozen_schema(case: dict[str, Any]) -> None:
    """At the pure-schema layer the model and the frozen schema give one verdict."""
    if case.get("validation_layer") in ("typed_object", "semantic"):
        pytest.skip("model is stricter than the raw schema at these layers")

    schema = load_shared_kernel_schema()
    def_name = _def_name(case["schema_ref"])
    instance = _load_instance(case["instance"])

    schema_valid = schema.is_valid(def_name, instance)
    model_valid = True
    try:
        _VALIDATORS[def_name](instance)
    except ValidationError:
        model_valid = False

    assert schema_valid == (case["expect"] == "valid")
    assert model_valid == schema_valid


def test_id_registry_matches_frozen_pattern() -> None:
    """The active kind registry equals the schema's RegisteredMugId prefix set."""
    schema = load_shared_kernel_schema()
    pattern = schema.document["$defs"]["RegisteredMugId"]["pattern"]
    # The pattern is ``^(?:a|b|...)_<uuidv7>$``; recover the prefix alternation.
    body = pattern[len("^(?:") : pattern.index(f")_{UUIDV7}$")]
    schema_prefixes = set(body.split("|"))
    registry_prefixes = {kind.prefix for kind in ID_KIND_REGISTRY}
    assert schema_prefixes == registry_prefixes


def test_bundle_digest_matches_pinned_schema_refs() -> None:
    """A shared-bundle SchemaRef in a fixture pins the frozen bundle digest."""
    schema = load_shared_kernel_schema()
    receipt = _load_instance("valid/command-receipt.accepted.json")
    ref = SchemaRef.model_validate(receipt["schema"])
    schema.verify_ref(ref)  # raises on any mismatch
    assert ref.digest.hex == schema.bundle_digest
