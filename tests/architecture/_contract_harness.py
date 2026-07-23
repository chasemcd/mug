"""Shared machinery for Phase 0 API contract-fixture suites.

Each API family test module loads its schema bundle and fixture manifest through
`load_family`, then reuses the strict parser, offline validator, and the common
fixture-case / schema-validity / manifest-completeness / digest-binding checks.
Family-specific rules are expressed as a `semantic_violations(name, value)`
callback returning a list of `(keyword, json_pointer)` pairs.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable

import rfc8785
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PHASE_0_ROOT = REPOSITORY_ROOT / "docs" / "architecture" / "phase-0"
SHARED_SCHEMA_PATH = (
    PHASE_0_ROOT / "shared-kernel" / "schemas" / "v0" / "shared-kernel.schema.json"
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
    value = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_nonfinite,
        parse_int=_parse_safe_integer,
        parse_float=_parse_finite_float,
    )
    _reject_lone_surrogates(value)
    return value


def canonical_bytes(value: Any) -> bytes:
    """RFC 8785 (JSON Canonicalization Scheme) canonical bytes.

    The MUG canonical-JSON profile is RFC 8785; `json.dumps(sort_keys=True)` is
    byte-identical only within the constrained profile and is not conforming in
    general (integral floats, exponent formatting), so the conforming library is
    the canonical implementation. `strict_json_load` still enforces the MUG input
    constraints (no duplicate keys, finite numbers, safe integers, no lone
    surrogates) before canonicalization. Proven byte-equivalent to the prior
    `json.dumps` form across the entire Phase-0 corpus (0 deltas), so this swap
    changes no existing pinned digest.
    """
    return rfc8785.dumps(value)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def json_pointer(path: Iterable[Any]) -> str:
    parts = [str(part).replace("~", "~0").replace("/", "~1") for part in path]
    return "" if not parts else "/" + "/".join(parts)


def walk_errors(error: ValidationError) -> Iterable[ValidationError]:
    yield error
    for child in error.context:
        yield from walk_errors(child)


def iter_schema_references(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        if isinstance(value.get("$ref"), str):
            yield value["$ref"]
        for child in value.values():
            yield from iter_schema_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_schema_references(child)


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


_SHARED_SCHEMA = strict_json_load(SHARED_SCHEMA_PATH)


def load_family(api_dirname: str, schema_filename: str) -> SimpleNamespace:
    api_root = PHASE_0_ROOT / api_dirname
    schema_path = api_root / "schemas" / "v0" / schema_filename
    fixture_root = api_root / "fixtures" / "v0"
    manifest_path = fixture_root / "manifest.json"
    schema = strict_json_load(schema_path)
    manifest = strict_json_load(manifest_path)
    registry = Registry().with_resources(
        [
            (_SHARED_SCHEMA["$id"], Resource.from_contents(_SHARED_SCHEMA)),
            (schema["$id"], Resource.from_contents(schema)),
        ]
    )

    def validator_for(schema_ref: str) -> Draft202012Validator:
        return Draft202012Validator(
            {"$schema": DRAFT_2020_12, "$ref": schema_ref},
            registry=registry,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )

    return SimpleNamespace(
        api_root=api_root,
        schema=schema,
        manifest=manifest,
        registry=registry,
        fixture_root=fixture_root,
        manifest_path=manifest_path,
        validator_for=validator_for,
        cases=manifest["cases"],
    )


SemanticFn = Callable[[str, Any], list[tuple[str, str]]]


def run_fixture_case(
    family: SimpleNamespace, case: dict[str, Any], semantic: SemanticFn
) -> None:
    instance_path = (family.fixture_root / case["instance"]).resolve()
    assert instance_path.is_relative_to(family.fixture_root.resolve())
    instance = strict_json_load(instance_path)
    errors = sorted(
        family.validator_for(case["schema_ref"]).iter_errors(instance),
        key=lambda error: (list(error.absolute_path), str(error.validator)),
    )
    definition_name = case["schema_ref"].rsplit("/", 1)[-1]
    semantic_hits = semantic(definition_name, instance) if not errors else []

    if case["expect"] == "valid":
        assert not errors, "\n".join(error.message for error in errors)
        assert not semantic_hits, semantic_hits
        return

    expected = case["expected_error"]
    expected_pair = (expected["keyword"], expected["instance_pointer"])
    if case.get("validation_layer", "schema") == "semantic":
        assert not errors
        assert expected_pair in semantic_hits, f"{expected_pair!r} not in {semantic_hits!r}"
        return

    assert errors, "invalid fixture unexpectedly passed structural validation"
    flattened = [nested for error in errors for nested in walk_errors(error)]
    actual = [
        (error.validator, json_pointer(error.absolute_path)) for error in flattened
    ]
    assert expected_pair in actual, f"expected {expected_pair!r}; got {actual!r}"


def check_schema_valid(family: SimpleNamespace) -> None:
    assert family.schema["$schema"] == DRAFT_2020_12
    Draft202012Validator.check_schema(family.schema)
    resolver = family.registry.resolver(base_uri=family.schema["$id"])
    for schema_ref in iter_schema_references(family.schema):
        assert resolver.lookup(schema_ref).contents is not None
    for case in family.cases:
        assert resolver.lookup(case["schema_ref"]).contents is not None


def check_manifest_complete(family: SimpleNamespace, manifest_schema_ref: str) -> None:
    family.validator_for(manifest_schema_ref).validate(family.manifest)
    case_ids = [case["id"] for case in family.cases]
    assert len(case_ids) == len(set(case_ids))
    listed: set[Path] = set()
    for case in family.cases:
        instance_path = (family.fixture_root / case["instance"]).resolve()
        assert instance_path.is_relative_to(family.fixture_root.resolve())
        assert instance_path.is_file()
        assert instance_path.parent.name == case["expect"]
        listed.add(instance_path)
    on_disk = {
        path.resolve()
        for directory in (family.fixture_root / "valid", family.fixture_root / "invalid")
        for path in directory.glob("*.json")
    }
    assert listed == on_disk


def check_bundle_binding(family: SimpleNamespace, bundle_names: set[str]) -> None:
    expected = canonical_digest(family.schema)
    paths = [
        family.manifest_path,
        *(family.fixture_root / case["instance"] for case in family.cases),
    ]
    for path in paths:
        document = strict_json_load(path)
        for schema_ref in iter_schema_ref_objects(document):
            if schema_ref["name"] in bundle_names:
                assert schema_ref["version"] == 0, path
                assert schema_ref["digest"]["hex"] == expected, path
