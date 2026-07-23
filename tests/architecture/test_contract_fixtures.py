"""Validate the versioned Phase 0 JSON Schema and golden-fixture contracts."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

import pytest
import rfc8785
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SHARED_KERNEL_ROOT = (
    REPOSITORY_ROOT / "docs" / "architecture" / "phase-0" / "shared-kernel"
)
SCHEMA_PATH = SHARED_KERNEL_ROOT / "schemas" / "v0" / "shared-kernel.schema.json"
FIXTURE_ROOT = SHARED_KERNEL_ROOT / "fixtures" / "v0"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
IDENTIFIER_CONTRACT_PATH = (
    SHARED_KERNEL_ROOT / "identifiers-and-resource-hierarchy.md"
)
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
MAX_SAFE_INTEGER = 9_007_199_254_740_991


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object member: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _parse_safe_integer(value: str) -> int:
    parsed = int(value)
    if not -MAX_SAFE_INTEGER <= parsed <= MAX_SAFE_INTEGER:
        raise ValueError(f"unsafe JSON integer: {value}")
    return parsed


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def _reject_lone_surrogates(value: Any) -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("JSON string contains a lone Unicode surrogate")
        return
    if isinstance(value, list):
        for item in value:
            _reject_lone_surrogates(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_lone_surrogates(key)
            _reject_lone_surrogates(item)


def strict_json_load(path: Path) -> Any:
    """Load the interoperable JSON subset used by MUG contracts."""

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_nonfinite,
        parse_int=_parse_safe_integer,
        parse_float=_parse_finite_float,
    )
    _reject_lone_surrogates(value)
    return value


SCHEMA = strict_json_load(SCHEMA_PATH)
MANIFEST = strict_json_load(MANIFEST_PATH)
REGISTRY = Registry().with_resource(SCHEMA["$id"], Resource.from_contents(SCHEMA))
TYPED_OBJECT_SCHEMAS = {
    ("mug.preference.response-submit-payload", 0): (
        "FixturePreferenceResponseSubmitPayload"
    ),
    ("mug.preference.response-submit-result", 0): (
        "FixturePreferenceResponseSubmitResult"
    ),
    ("mug.error.command-revision-conflict-details", 0): (
        "FixtureRevisionConflictDetails"
    ),
    ("mug.error.external-unknown-outcome-details", 0): (
        "FixtureUnknownOutcomeDetails"
    ),
    ("mug.visit.create-payload", 0): "FixtureEmptyObject",
    ("mug.error.command-state-conflict-details", 0): "FixtureEmptyObject",
    ("mug.error.dependency-unavailable-details", 0): "FixtureEmptyObject",
}
COMMAND_PAYLOAD_SCHEMAS = {
    ("preference.response.submit", 0): (
        "mug.preference.response-submit-payload",
        0,
    ),
    ("visit.create", 0): ("mug.visit.create-payload", 0),
}
COMMAND_RESULT_SCHEMAS = {
    ("preference.response.submit", 0): (
        "mug.preference.response-submit-result",
        0,
    ),
}
ERROR_DETAIL_SCHEMAS = {
    "command.revision_conflict": (
        "mug.error.command-revision-conflict-details",
        0,
    ),
    "command.state_conflict": (
        "mug.error.command-state-conflict-details",
        0,
    ),
    "dependency.unavailable": (
        "mug.error.dependency-unavailable-details",
        0,
    ),
    "external.unknown_outcome": (
        "mug.error.external-unknown-outcome-details",
        0,
    ),
}
SHARED_BUNDLE_SCHEMA_NAMES = {
    "mug.command-envelope",
    "mug.command-receipt",
    "mug.domain-error",
    "mug.fixture-manifest",
    "mug.canonicalization-vectors",
}


def validator_for(schema_ref: str) -> Draft202012Validator:
    bridge = {"$schema": DRAFT_2020_12, "$ref": schema_ref}
    return Draft202012Validator(
        bridge,
        registry=REGISTRY,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def json_pointer(path: Iterable[Any]) -> str:
    parts = [str(part).replace("~", "~0").replace("/", "~1") for part in path]
    return "" if not parts else "/" + "/".join(parts)


def walk_errors(error: ValidationError) -> Iterable[ValidationError]:
    yield error
    for child in error.context:
        yield from walk_errors(child)


def canonical_digest(value: Any) -> str:
    # RFC 8785 (JCS) conforming, matching _contract_harness.canonical_bytes.
    # json.dumps(sort_keys=True) is byte-identical only within the constrained
    # MUG profile and is non-conforming in general (integral floats, -0), so a
    # frozen digest anchor must use the library. The legacy form is still checked
    # for agreement in test_frozen_bundle_digest_is_jcs_conforming.
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def typed_object_violations(
    value: Any, path: tuple[Any, ...] = ()
) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        command = value.get("command")
        if isinstance(command, dict):
            command_key = (command.get("name"), command.get("version"))
            for field, bindings in (
                ("payload", COMMAND_PAYLOAD_SCHEMAS),
                ("result", COMMAND_RESULT_SCHEMAS),
            ):
                wrapper = value.get(field)
                if isinstance(wrapper, dict):
                    schema_ref = wrapper.get("schema", {})
                    actual = (schema_ref.get("name"), schema_ref.get("version"))
                    if actual != bindings.get(command_key):
                        yield "commandSchemaBinding", json_pointer(
                            (*path, field, "schema")
                        )

        details = value.get("details")
        if isinstance(value.get("code"), str) and isinstance(details, dict):
            schema_ref = details.get("schema", {})
            actual = (schema_ref.get("name"), schema_ref.get("version"))
            if actual != ERROR_DETAIL_SCHEMAS.get(value["code"]):
                yield "errorSchemaBinding", json_pointer(
                    (*path, "details", "schema")
                )

        schema_ref = value.get("schema")
        data = value.get("data")
        if isinstance(schema_ref, dict) and isinstance(data, dict):
            key = (schema_ref.get("name"), schema_ref.get("version"))
            definition_name = TYPED_OBJECT_SCHEMAS.get(key)
            if definition_name is None:
                yield "schemaRegistry", json_pointer((*path, "schema"))
            else:
                expected_digest = canonical_digest(SCHEMA["$defs"][definition_name])
                actual_digest = schema_ref.get("digest", {}).get("hex")
                if actual_digest != expected_digest:
                    yield "digest", json_pointer((*path, "schema", "digest", "hex"))
                else:
                    schema_uri = f"{SCHEMA['$id']}#/$defs/{definition_name}"
                    for error in validator_for(schema_uri).iter_errors(data):
                        yield error.validator, json_pointer(
                            (*path, "data", *error.absolute_path)
                        )

        for key, child in value.items():
            yield from typed_object_violations(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from typed_object_violations(child, (*path, index))


def iter_schema_ref_objects(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if (
            isinstance(value.get("name"), str)
            and isinstance(value.get("version"), int)
            and isinstance(value.get("digest"), dict)
        ):
            yield value
        for child in value.values():
            yield from iter_schema_ref_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_schema_ref_objects(child)


def shared_semantic_violations(
    case: dict[str, Any], instance: Any
) -> list[tuple[str, str]]:
    definition_name = case["schema_ref"].rsplit("/", 1)[-1]
    violations: list[tuple[str, str]] = []

    if definition_name == "CapabilitySet" and instance != sorted(instance):
        violations.append(("canonicalOrder", ""))

    if definition_name == "InlineBytes":
        data = instance["data"]
        padding = "=" * (-len(data) % 4)
        decoded = base64.b64decode(data + padding, altchars=b"-_", validate=True)
        if len(decoded) != instance["size_bytes"]:
            violations.append(("decodedSize", "/size_bytes"))
        if hashlib.sha256(decoded).hexdigest() != instance["digest"]["hex"]:
            violations.append(("digest", "/digest/hex"))

    return violations


def fixture_cases() -> list[dict[str, Any]]:
    return MANIFEST["cases"]


@pytest.mark.parametrize(
    "case",
    fixture_cases(),
    ids=lambda case: case["id"],
)
def test_contract_fixture(case: dict[str, Any]) -> None:
    instance_path = (FIXTURE_ROOT / case["instance"]).resolve()
    assert instance_path.is_relative_to(FIXTURE_ROOT.resolve())
    instance = strict_json_load(instance_path)
    errors = sorted(
        validator_for(case["schema_ref"]).iter_errors(instance),
        key=lambda error: (list(error.absolute_path), str(error.validator)),
    )

    typed_violations = list(typed_object_violations(instance))
    shared_violations = (
        shared_semantic_violations(case, instance) if not errors else []
    )
    validation_layer = case.get("validation_layer", "schema")

    if case["expect"] == "valid":
        assert not errors, "\n".join(error.message for error in errors)
        assert not typed_violations, typed_violations
        assert not shared_violations, shared_violations
        return

    expected = case["expected_error"]
    if validation_layer == "typed_object":
        assert not errors, "typed-object fixture must pass its shared envelope schema"
        assert (
            expected["keyword"],
            expected["instance_pointer"],
        ) in typed_violations
        return

    if validation_layer == "semantic":
        assert not errors, "semantic fixture must pass its JSON Schema"
        assert not typed_violations, typed_violations
        assert (
            expected["keyword"],
            expected["instance_pointer"],
        ) in shared_violations
        return

    assert errors, "invalid fixture unexpectedly passed validation"
    flattened = [nested for error in errors for nested in walk_errors(error)]
    assert any(
        nested.validator == expected["keyword"]
        and json_pointer(nested.absolute_path) == expected["instance_pointer"]
        for nested in flattened
    ), (
        f"did not find {expected['keyword']} at "
        f"{expected['instance_pointer']!r}; got "
        f"{[(error.validator, json_pointer(error.absolute_path)) for error in flattened]}"
    )


def test_schema_document_is_valid_draft_2020_12() -> None:
    assert SCHEMA["$schema"] == DRAFT_2020_12
    assert SCHEMA["$id"].startswith("urn:mug:schema:")
    Draft202012Validator.check_schema(SCHEMA)


def test_registered_id_schema_matches_the_documented_registry() -> None:
    pattern = SCHEMA["$defs"]["RegisteredMugId"]["pattern"]
    prefix_group = re.search(r"\(\?:([^)]*)\)", pattern)
    assert prefix_group is not None
    schema_prefixes = set(prefix_group.group(1).split("|"))

    contract = IDENTIFIER_CONTRACT_PATH.read_text(encoding="utf-8")

    # Active registry rows are the markdown table `| `prefix` | ... |` lines.
    documented_prefixes = set(
        re.findall(r"^\| `([a-z0-9]+)` \|", contract, flags=re.MULTILINE)
    )
    assert documented_prefixes
    assert schema_prefixes == documented_prefixes

    # Retired prefixes stay documented as reserved (never reused) but must be
    # absent from both the active table and the version-0 schema pattern.
    reserved_section = re.search(
        r"^### Reserved \(retired\) prefixes\n(.*?)(?=^#|\Z)",
        contract,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert reserved_section is not None
    reserved_prefixes = set(
        re.findall(
            r"`([a-z0-9]+)`",
            "\n".join(
                line
                for line in reserved_section.group(1).splitlines()
                if line.lstrip().startswith("-") or line.startswith("  ")
            ),
        )
    )
    assert reserved_prefixes
    assert not reserved_prefixes & schema_prefixes
    assert not reserved_prefixes & documented_prefixes


def test_privacy_classification_lattice_is_closed_and_canonical() -> None:
    classifications = [
        tuple(branch["const"])
        for branch in SCHEMA["$defs"]["PrivacyClassification"]["oneOf"]
    ]
    assert classifications == [
        ("public",),
        ("research",),
        ("research", "sensitive"),
        ("research", "pii"),
        ("research", "sensitive", "pii"),
    ]

    def join(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
        restrictions = set(left) | set(right)
        restrictions.discard("public")
        restrictions.discard("research")
        if left == ("public",) and right == ("public",):
            return ("public",)
        return (
            "research",
            *(label for label in ("sensitive", "pii") if label in restrictions),
        )

    for left in classifications:
        assert join(left, left) == left
        for right in classifications:
            assert join(left, right) == join(right, left)
            assert join(left, right) in classifications
            for third in classifications:
                assert join(join(left, right), third) == join(
                    left, join(right, third)
                )


def iter_schema_references(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        schema_ref = value.get("$ref")
        if isinstance(schema_ref, str):
            yield schema_ref
        for child in value.values():
            yield from iter_schema_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_schema_references(child)


def test_every_schema_reference_resolves_offline() -> None:
    resolver = REGISTRY.resolver(base_uri=SCHEMA["$id"])
    for schema_ref in iter_schema_references(SCHEMA):
        resolved = resolver.lookup(schema_ref)
        assert resolved.contents is not None
    for case in fixture_cases():
        resolved = resolver.lookup(case["schema_ref"])
        assert resolved.contents is not None


def test_fixture_manifest_validates_and_is_complete() -> None:
    validator_for(
        "urn:mug:schema:mug.shared-kernel:0#/$defs/FixtureManifest"
    ).validate(MANIFEST)

    case_ids = [case["id"] for case in fixture_cases()]
    assert len(case_ids) == len(set(case_ids)), "duplicate fixture case ID"

    listed_paths: set[Path] = set()
    for case in fixture_cases():
        instance_path = (FIXTURE_ROOT / case["instance"]).resolve()
        assert instance_path.is_relative_to(FIXTURE_ROOT.resolve())
        assert instance_path.is_file()
        assert instance_path.parent.name == case["expect"]
        listed_paths.add(instance_path)

    fixture_paths = {
        path.resolve()
        for directory in (FIXTURE_ROOT / "valid", FIXTURE_ROOT / "invalid")
        for path in directory.glob("*.json")
    }
    assert listed_paths == fixture_paths


def test_all_shared_schema_refs_bind_the_current_draft_bundle() -> None:
    # The current schema contains only JCS-stable JSON primitives, so this is the
    # RFC 8785 byte representation for this document. Cross-language general JCS
    # conformance remains a separate Phase 0 acceptance gate.
    expected = canonical_digest(SCHEMA)

    paths = [MANIFEST_PATH, *(FIXTURE_ROOT / case["instance"] for case in fixture_cases())]
    for path in paths:
        document = strict_json_load(path)
        for schema_ref in iter_schema_ref_objects(document):
            if schema_ref["name"] in SHARED_BUNDLE_SCHEMA_NAMES:
                assert schema_ref["version"] == 0, path
                assert schema_ref["digest"]["hex"] == expected, path


def test_canonicalization_vectors_are_internally_consistent() -> None:
    vectors = strict_json_load(
        FIXTURE_ROOT / "valid" / "canonicalization-vectors.json"
    )["vectors"]
    for vector in vectors:
        canonical = vector["canonical_utf8"].encode("utf-8")
        # Conforming RFC 8785 canonical form (JCS). The dedicated cross-language
        # vector suite (Python rfc8785 + browser JS) lives in
        # tests/architecture/conformance/.
        expected_canonical = rfc8785.dumps(vector["value"])
        assert canonical == expected_canonical
        parsed = json.loads(
            canonical.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
            parse_int=_parse_safe_integer,
            parse_float=_parse_finite_float,
        )
        _reject_lone_surrogates(parsed)
        assert parsed == vector["value"]
        assert hashlib.sha256(canonical).hexdigest() == vector["digest"]["hex"]


def test_frozen_bundle_digest_is_jcs_conforming() -> None:
    # Guard the frozen anchor. The shared-kernel bundle — and every value we
    # digest for TypedObject second-stage binding — must canonicalize identically
    # under the legacy json.dumps form and the conforming rfc8785 library. They
    # agree today (0 corpus deltas). This fails loudly if a future schema edit
    # introduces a value where they diverge (integral float such as
    # `"multipleOf": 1.0`, negative zero, or a non-ASCII key), which would
    # otherwise freeze a non-conforming digest anchor into the accepted contract.
    legacy = json.dumps(
        SCHEMA, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert legacy == rfc8785.dumps(SCHEMA)
    assert canonical_digest(SCHEMA) == hashlib.sha256(legacy).hexdigest()


def test_valid_inline_bytes_have_canonical_data_size_and_digest() -> None:
    inline = strict_json_load(FIXTURE_ROOT / "valid" / "inline-bytes.json")
    data = inline["data"]
    padding = "=" * (-len(data) % 4)
    decoded = base64.b64decode(data + padding, altchars=b"-_", validate=True)
    assert base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") == data
    assert len(decoded) == inline["size_bytes"]
    assert hashlib.sha256(decoded).hexdigest() == inline["digest"]["hex"]


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ('{"a": 1, "a": 2}', "duplicate JSON object member"),
        ('{"value": NaN}', "non-finite JSON number"),
        ('{"value": Infinity}', "non-finite JSON number"),
        ('{"value": -Infinity}', "non-finite JSON number"),
        ('{"value": 9007199254740992}', "unsafe JSON integer"),
        ('{"value": 1e400}', "non-finite JSON number"),
        ('{"value": "\\ud800"}', "lone Unicode surrogate"),
    ],
)
def test_strict_loader_rejects_noninteroperable_json(
    tmp_path: Path, source: str, message: str
) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        strict_json_load(path)
