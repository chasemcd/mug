"""Validate API-01 study authoring, compilation, and publication contracts."""

from __future__ import annotations

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
PHASE_0_ROOT = REPOSITORY_ROOT / "docs" / "architecture" / "phase-0"
SHARED_SCHEMA_PATH = (
    PHASE_0_ROOT
    / "shared-kernel"
    / "schemas"
    / "v0"
    / "shared-kernel.schema.json"
)
API_ROOT = PHASE_0_ROOT / "api-01"
SCHEMA_PATH = API_ROOT / "schemas" / "v0" / "study-authoring.schema.json"
FIXTURE_ROOT = API_ROOT / "fixtures" / "v0"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
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
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_nonfinite,
        parse_int=_parse_safe_integer,
        parse_float=_parse_finite_float,
    )
    _reject_lone_surrogates(value)
    return value


SHARED_SCHEMA = strict_json_load(SHARED_SCHEMA_PATH)
SCHEMA = strict_json_load(SCHEMA_PATH)
MANIFEST = strict_json_load(MANIFEST_PATH)
REGISTRY = Registry().with_resources(
    [
        (SHARED_SCHEMA["$id"], Resource.from_contents(SHARED_SCHEMA)),
        (SCHEMA["$id"], Resource.from_contents(SCHEMA)),
    ]
)
DOMAIN_SCHEMAS = {
    ("mug.fixture.content-activity", 0): "FixtureContentActivity",
    ("mug.fixture.terminal-action", 0): "FixtureTerminalAction",
    ("mug.fixture.client-component-config", 0): (
        "FixtureClientComponentConfig"
    ),
    ("mug.fixture.server-activity-config", 0): (
        "FixtureServerActivityConfig"
    ),
    ("mug.fixture.data-flow", 0): "FixtureDataFlow",
    ("mug.fixture.deployment-requirements", 0): (
        "FixtureDeploymentRequirements"
    ),
    ("mug.fixture.runtime-scope-selector", 0): (
        "FixtureRuntimeScopeSelector"
    ),
    ("mug.fixture.projection-selector", 0): "FixtureProjectionSelector",
}
API_BUNDLE_SCHEMA_NAMES = {
    "mug.study.authoring-document",
    "mug.study.client-manifest",
    "mug.study.compiled-candidate",
    "mug.study.fixture-manifest",
    "mug.study.manifest-set",
    "mug.study.provenance-manifest",
    "mug.study.published-version",
    "mug.study.scientific-manifest",
    "mug.study.server-manifest",
    "mug.study.validation-report",
}
DEFINITION_PREFIXES = {
    "activity": "activitydef_",
    "agent": "agentdef_",
    "channel": "channeldef_",
    "flow_node": "flownode_",
    "preference_protocol": "prefdef_",
    "prompt": "promptdef_",
    "seat": "seatdef_",
    "tool": "tooldef_",
}
INTERNAL_ID = re.compile(
    r"^(?:study|studyver|flownode|deploy|deployrev|"
    r"activitydef|activity|seatdef|actor|controller|interaction|channeldef|"
    r"channel|artifact|agentdef|agentver|promptdef|promptver|tooldef|toolver|"
    r"prefdef|prefver|secret)_"
    r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-"
    r"[0-9a-f]{12}$"
)


def validator_for(schema_ref: str) -> Draft202012Validator:
    return Draft202012Validator(
        {"$schema": DRAFT_2020_12, "$ref": schema_ref},
        registry=REGISTRY,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def json_pointer(path: Iterable[Any]) -> str:
    parts = [str(part).replace("~", "~0").replace("/", "~1") for part in path]
    return "" if not parts else "/" + "/".join(parts)


def canonical_bytes(value: Any) -> bytes:
    # RFC 8785 (JCS) conforming, matching _contract_harness.canonical_bytes.
    # json.dumps(sort_keys=True) is byte-identical only within the constrained
    # MUG profile and non-conforming in general (integral floats, -0).
    return rfc8785.dumps(value)


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def exact_fixture_reference_violations(
    filename: str,
    digest_hex: str,
    size_bytes: int,
    digest_pointer: str,
    size_pointer: str,
) -> list[tuple[str, str]]:
    document = strict_json_load(FIXTURE_ROOT / "valid" / filename)
    violations: list[tuple[str, str]] = []
    if digest_hex != canonical_digest(document):
        violations.append(("closureDigest", digest_pointer))
    if size_bytes != len(canonical_bytes(document)):
        violations.append(("closureSize", size_pointer))
    return violations


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


def typed_object_violations(
    value: Any, path: tuple[Any, ...] = ()
) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        schema_ref = value.get("schema")
        data = value.get("data")
        if isinstance(schema_ref, dict) and isinstance(data, dict):
            key = (schema_ref.get("name"), schema_ref.get("version"))
            definition_name = DOMAIN_SCHEMAS.get(key)
            if definition_name is None:
                yield "schemaRegistry", json_pointer((*path, "schema"))
            else:
                expected_digest = canonical_digest(SCHEMA["$defs"][definition_name])
                if schema_ref.get("digest", {}).get("hex") != expected_digest:
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


def _definition_violations(
    definitions: list[dict[str, Any]], path: tuple[Any, ...] = ()
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    seen_keys: set[tuple[str, str]] = set()
    seen_ids: set[str] = set()
    for index, definition in enumerate(definitions):
        key = (definition["kind"], definition["key"])
        if key in seen_keys:
            violations.append(
                ("duplicateDefinitionKey", json_pointer((*path, index, "key")))
            )
        seen_keys.add(key)

        definition_id = definition["definition"]["id"]
        if definition_id in seen_ids:
            violations.append(
                ("duplicateDefinitionId", json_pointer((*path, index, "definition", "id")))
            )
        seen_ids.add(definition_id)
        if not definition_id.startswith(DEFINITION_PREFIXES[definition["kind"]]):
            violations.append(
                ("definitionKind", json_pointer((*path, index, "definition", "id")))
            )

    ordered = [(definition["kind"], definition["key"]) for definition in definitions]
    if ordered != sorted(ordered):
        violations.append(("canonicalOrder", json_pointer(path)))
    return violations


def _git_provenance_violations(
    value: dict[str, Any], path: tuple[Any, ...] = ()
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    patch = value.get("patch")
    if value["dirty"] and patch is None:
        violations.append(("dirtyWithoutPatch", json_pointer((*path, "dirty"))))
    if not value["dirty"] and patch is not None:
        violations.append(("cleanWithPatch", json_pointer((*path, "patch"))))
    if patch is not None:
        artifact = patch.get("artifact")
        if artifact is not None and artifact["content_encoding"] == "identity":
            if artifact["digest"]["hex"] != patch["patch_digest"]["hex"]:
                violations.append(
                    (
                        "patchDigest",
                        json_pointer((*path, "patch", "artifact", "digest", "hex")),
                    )
                )
            if artifact["size_bytes"] != patch["size_bytes"]:
                violations.append(
                    (
                        "patchSize",
                        json_pointer((*path, "patch", "artifact", "size_bytes")),
                    )
                )
    return violations


def _node_references(node: dict[str, Any]) -> list[tuple[str, int | None]]:
    kind = node["kind"]
    if kind == "sequence":
        return [(child, index) for index, child in enumerate(node["children"])]
    if kind == "randomized_select":
        return [(child, index) for index, child in enumerate(node["choices"])]
    if kind == "repeat":
        return [(node["child"], None)]
    if kind == "branch":
        references = [
            (case["child"], index) for index, case in enumerate(node["cases"])
        ]
        if "default_child" in node:
            references.append((node["default_child"], None))
        return references
    return []


def _flow_violations(
    flow: dict[str, Any], path: tuple[Any, ...] = ()
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    nodes = flow["nodes"]
    by_id: dict[str, dict[str, Any]] = {}
    id_index: dict[str, int] = {}
    seen_keys: set[str] = set()
    for index, node in enumerate(nodes):
        if node["node_id"] in by_id:
            violations.append(
                ("duplicateNodeId", json_pointer((*path, "nodes", index, "node_id")))
            )
        by_id[node["node_id"]] = node
        id_index[node["node_id"]] = index
        if node["key"] in seen_keys:
            violations.append(
                ("duplicateNodeKey", json_pointer((*path, "nodes", index, "key")))
            )
        seen_keys.add(node["key"])
        if node["kind"] == "randomized_select" and node["choose"] > len(
            node["choices"]
        ):
            violations.append(
                ("chooseExceedsChoices", json_pointer((*path, "nodes", index, "choose")))
            )

    if flow["entry_node_id"] not in by_id:
        violations.append(("missingNode", json_pointer((*path, "entry_node_id"))))
        return violations

    adjacency: dict[str, list[str]] = {node_id: [] for node_id in by_id}
    for node_id, node in by_id.items():
        index = id_index[node_id]
        for reference, reference_index in _node_references(node):
            if reference not in by_id:
                if node["kind"] == "sequence":
                    pointer = (*path, "nodes", index, "children", reference_index)
                elif node["kind"] == "randomized_select":
                    pointer = (*path, "nodes", index, "choices", reference_index)
                elif node["kind"] == "repeat":
                    pointer = (*path, "nodes", index, "child")
                elif reference_index is None:
                    pointer = (*path, "nodes", index, "default_child")
                else:
                    pointer = (*path, "nodes", index, "cases", reference_index, "child")
                violations.append(("missingNode", json_pointer(pointer)))
            else:
                adjacency[node_id].append(reference)

    reachable: set[str] = set()
    visiting: set[str] = set()

    def walk(node_id: str) -> None:
        if node_id in visiting:
            violations.append(
                ("flowCycle", json_pointer((*path, "nodes", id_index[node_id], "node_id")))
            )
            return
        if node_id in reachable:
            return
        visiting.add(node_id)
        reachable.add(node_id)
        for child in adjacency[node_id]:
            walk(child)
        visiting.remove(node_id)

    walk(flow["entry_node_id"])
    for node_id, index in id_index.items():
        if node_id not in reachable:
            violations.append(
                ("unreachableNode", json_pointer((*path, "nodes", index, "node_id")))
            )
    if not any(
        by_id[node_id]["kind"] == "terminal" for node_id in reachable
    ):
        violations.append(("terminalMissing", json_pointer((*path, "entry_node_id"))))
    if nodes != sorted(nodes, key=lambda item: item["key"]):
        violations.append(("canonicalOrder", json_pointer((*path, "nodes"))))
    return violations


def _client_disclosure_violations(
    value: Any, path: tuple[Any, ...] = ()
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    forbidden_keys = {
        "artifact_id",
        "binding_id",
        "bucket",
        "credential",
        "filename",
        "model_id",
        "path",
        "private_condition",
        "prompt_id",
        "provider_id",
        "secret_ref",
        "signed_url",
        "storage_uri",
        "study_id",
        "treatment_id",
        "tool_id",
    }
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, key)
            if key.lower() in forbidden_keys:
                violations.append(("clientDisclosure", json_pointer(child_path)))
            violations.extend(_client_disclosure_violations(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(_client_disclosure_violations(child, (*path, index)))
    elif isinstance(value, str) and INTERNAL_ID.fullmatch(value):
        violations.append(("clientDisclosure", json_pointer(path)))
    return violations


def _secret_reference_violations(
    value: Any, path: tuple[Any, ...] = ()
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    if isinstance(value, dict):
        if "binding_id" in value and "resolution" in value:
            violations.append(("secretReference", json_pointer(path)))
        for key, child in value.items():
            if key.lower() in {"credential", "password", "secret_value", "token"}:
                violations.append(("secretMaterial", json_pointer((*path, key))))
            violations.extend(_secret_reference_violations(child, (*path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(_secret_reference_violations(child, (*path, index)))
    return violations


def _manifest_artifact_violations(
    value: dict[str, Any], path: tuple[Any, ...] = ()
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    artifact = value["artifact"]
    if (
        artifact["content_encoding"] == "identity"
        and value["content_digest"]["hex"] != artifact["digest"]["hex"]
    ):
        violations.append(
            ("artifactDigest", json_pointer((*path, "artifact", "digest", "hex")))
        )
    content_schema = artifact.get("content_schema")
    if content_schema is not None and content_schema != value["manifest_schema"]:
        violations.append(
            ("artifactSchema", json_pointer((*path, "artifact", "content_schema")))
        )
    return violations


def _manifest_set_violations(value: dict[str, Any]) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    expected_names = {
        "scientific": "mug.study.scientific-manifest",
        "server": "mug.study.server-manifest",
        "provenance": "mug.study.provenance-manifest",
    }
    for field, expected_name in expected_names.items():
        descriptor = value[field]
        violations.extend(_manifest_artifact_violations(descriptor, (field,)))
        if descriptor["manifest_schema"]["name"] != expected_name:
            violations.append(
                ("manifestRole", json_pointer((field, "manifest_schema", "name")))
            )
    for index, projection in enumerate(value["clients"]):
        descriptor = projection["manifest"]
        violations.extend(
            _manifest_artifact_violations(descriptor, ("clients", index, "manifest"))
        )
        if descriptor["manifest_schema"]["name"] != "mug.study.client-manifest":
            violations.append(
                (
                    "manifestRole",
                    json_pointer(("clients", index, "manifest", "manifest_schema", "name")),
                )
            )

    file_by_field = {
        "scientific": "scientific-manifest.minimal-static.json",
        "server": "server-manifest.minimal-static.json",
        "provenance": "provenance-manifest.minimal-static.json",
    }
    for field, filename in file_by_field.items():
        descriptor = value[field]
        violations.extend(
            exact_fixture_reference_violations(
                filename,
                descriptor["content_digest"]["hex"],
                descriptor["artifact"]["size_bytes"],
                json_pointer((field, "content_digest", "hex")),
                json_pointer((field, "artifact", "size_bytes")),
            )
        )
    client_descriptor = value["clients"][0]["manifest"]
    violations.extend(
        exact_fixture_reference_violations(
            "client-manifest.minimal-static.json",
            client_descriptor["content_digest"]["hex"],
            client_descriptor["artifact"]["size_bytes"],
            "/clients/0/manifest/content_digest/hex",
            "/clients/0/manifest/artifact/size_bytes",
        )
    )
    validation = value["validation_report"]
    violations.extend(
        exact_fixture_reference_violations(
            "validation-report.valid.json",
            validation["digest"]["hex"],
            validation["size_bytes"],
            "/validation_report/digest/hex",
            "/validation_report/size_bytes",
        )
    )

    scientific = strict_json_load(
        FIXTURE_ROOT / "valid" / "scientific-manifest.minimal-static.json"
    )
    projections = scientific["projections"]
    if (
        projections["clients"][0]["manifest"]["content_digest"]
        != client_descriptor["content_digest"]
    ):
        violations.append(("projectionDigest", "/clients/0/manifest/content_digest/hex"))
    for field in ("server", "provenance"):
        if projections[field]["content_digest"] != value[field]["content_digest"]:
            violations.append(("projectionDigest", f"/{field}/content_digest/hex"))
    return violations


def semantic_violations(
    definition_name: str, value: Any
) -> list[tuple[str, str]]:
    if definition_name == "FlowSpec":
        return _flow_violations(value)
    if definition_name == "GitProvenance":
        return _git_provenance_violations(value)
    if definition_name == "ManifestArtifact":
        return _manifest_artifact_violations(value)
    if definition_name == "ClientManifest":
        violations = _client_disclosure_violations(value)
        for index, component in enumerate(value["components"]):
            if component["component_schema"] != component["config"]["schema"]:
                violations.append(
                    ("componentSchema", f"/components/{index}/config/schema")
                )
        return violations
    if definition_name == "AuthoringDocument":
        violations = _definition_violations(value["definitions"], ("definitions",))
        violations.extend(_flow_violations(value["flow"], ("flow",)))
        activity_ids = {
            definition["definition"]["id"]
            for definition in value["definitions"]
            if definition["kind"] == "activity"
        }
        for index, node in enumerate(value["flow"]["nodes"]):
            if (
                node["kind"] == "activity"
                and node["activity_definition_id"] not in activity_ids
            ):
                violations.append(
                    (
                        "activityDefinitionMissing",
                        f"/flow/nodes/{index}/activity_definition_id",
                    )
                )
        violations.extend(_secret_reference_violations(value))
        return violations
    if definition_name == "CompiledStudyCandidate":
        # The fingerprint is what makes a compile reproducible: it must be the
        # digest of the inputs it names, or nothing can check that the same inputs
        # were compiled twice into the same study.
        if canonical_digest(value["inputs"]) != value["input_fingerprint"]["hex"]:
            violations = [("inputFingerprint", "/input_fingerprint/hex")]
        else:
            violations = []
        return violations
    if definition_name == "StudyServerManifest":
        return _secret_reference_violations(value)
    if definition_name == "ProvenanceManifest":
        violations = _git_provenance_violations(value["source_git"], ("source_git",))
        violations.extend(_secret_reference_violations(value))
        projection_files = {
            "client": "client-manifest.minimal-static.json",
            "server": "server-manifest.minimal-static.json",
        }
        for index, output in enumerate(value["projection_outputs"]):
            projection = output["projection"]
            filename = projection_files[output["role"]]
            violations.extend(
                exact_fixture_reference_violations(
                    filename,
                    projection["content_digest"]["hex"],
                    projection["size_bytes"],
                    f"/projection_outputs/{index}/projection/content_digest/hex",
                    f"/projection_outputs/{index}/projection/size_bytes",
                )
            )
        return violations
    if definition_name == "PublishedStudyVersion":
        violations = _git_provenance_violations(
            value["git_provenance"], ("git_provenance",)
        )
        violations.extend(
            _manifest_artifact_violations(value["scientific"], ("scientific",))
        )
        for index, projection in enumerate(value["clients"]):
            violations.extend(
                _manifest_artifact_violations(
                    projection["manifest"], ("clients", index, "manifest")
                )
            )
        for field in ("server", "provenance"):
            violations.extend(_manifest_artifact_violations(value[field], (field,)))
        closure_files = {
            "scientific": "scientific-manifest.minimal-static.json",
            "server": "server-manifest.minimal-static.json",
            "provenance": "provenance-manifest.minimal-static.json",
        }
        for field, filename in closure_files.items():
            descriptor = value[field]
            violations.extend(
                exact_fixture_reference_violations(
                    filename,
                    descriptor["content_digest"]["hex"],
                    descriptor["artifact"]["size_bytes"],
                    f"/{field}/content_digest/hex",
                    f"/{field}/artifact/size_bytes",
                )
            )
        for index, projection in enumerate(value["clients"]):
            descriptor = projection["manifest"]
            violations.extend(
                exact_fixture_reference_violations(
                    "client-manifest.minimal-static.json",
                    descriptor["content_digest"]["hex"],
                    descriptor["artifact"]["size_bytes"],
                    f"/clients/{index}/manifest/content_digest/hex",
                    f"/clients/{index}/manifest/artifact/size_bytes",
                )
            )
        if (
            value["study_version"]["manifest_digest"]["hex"]
            != value["scientific"]["content_digest"]["hex"]
        ):
            violations.append(("versionDigest", "/study_version/manifest_digest/hex"))
        violations.extend(_secret_reference_violations(value))
        return violations
    if definition_name == "ScientificManifest":
        violations = _manifest_artifact_violations(
            value["normalized_study"], ("normalized_study",)
        )
        normalized = value["normalized_study"]
        violations.extend(
            exact_fixture_reference_violations(
                "authoring-document.minimal-static.json",
                normalized["content_digest"]["hex"],
                normalized["artifact"]["size_bytes"],
                "/normalized_study/content_digest/hex",
                "/normalized_study/artifact/size_bytes",
            )
        )
        if value["source_digest"] != value["normalized_study"]["content_digest"]:
            violations.append(("sourceDigest", "/source_digest/hex"))
        capabilities = [
            requirement["capability"]
            for requirement in value["capability_closure"]["requirements"]
        ]
        if capabilities != sorted(capabilities) or len(capabilities) != len(set(capabilities)):
            violations.append(("canonicalOrder", "/capability_closure/requirements"))
        projection_files = {
            "server": "server-manifest.minimal-static.json",
            "provenance": "provenance-manifest.minimal-static.json",
        }
        for field, filename in projection_files.items():
            projection = value["projections"][field]
            violations.extend(
                exact_fixture_reference_violations(
                    filename,
                    projection["content_digest"]["hex"],
                    projection["size_bytes"],
                    f"/projections/{field}/content_digest/hex",
                    f"/projections/{field}/size_bytes",
                )
            )
        for index, client in enumerate(value["projections"]["clients"]):
            projection = client["manifest"]
            violations.extend(
                exact_fixture_reference_violations(
                    "client-manifest.minimal-static.json",
                    projection["content_digest"]["hex"],
                    projection["size_bytes"],
                    f"/projections/clients/{index}/manifest/content_digest/hex",
                    f"/projections/clients/{index}/manifest/size_bytes",
                )
            )
        violations.extend(_secret_reference_violations(value))
        return violations
    if definition_name == "ManifestSet":
        return _manifest_set_violations(value)
    if definition_name == "ValidationReport":
        actual = {severity: 0 for severity in ("error", "warning", "info")}
        for diagnostic in value["diagnostics"]:
            actual[diagnostic["severity"]] += 1
        violations = []
        if value["counts"] != actual:
            violations.append(("diagnosticCounts", "/counts"))
        if value["valid"] != (actual["error"] == 0):
            violations.append(("validity", "/valid"))
        return violations
    return []


def publication_violations(value: Any, path: tuple[Any, ...] = ()) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    if isinstance(value, dict):
        if (
            isinstance(value.get("name"), str)
            and isinstance(value.get("version"), int)
            and isinstance(value.get("digest"), dict)
            and value["version"] == 0
        ):
            violations.append(("schemaVersionZero", json_pointer((*path, "version"))))
        for key, child in value.items():
            violations.extend(publication_violations(child, (*path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(publication_violations(child, (*path, index)))
    return violations


def fixture_cases() -> list[dict[str, Any]]:
    return MANIFEST["cases"]


@pytest.mark.parametrize("case", fixture_cases(), ids=lambda case: case["id"])
def test_api01_contract_fixture(case: dict[str, Any]) -> None:
    instance_path = (FIXTURE_ROOT / case["instance"]).resolve()
    assert instance_path.is_relative_to(FIXTURE_ROOT.resolve())
    instance = strict_json_load(instance_path)
    errors = sorted(
        validator_for(case["schema_ref"]).iter_errors(instance),
        key=lambda error: (list(error.absolute_path), str(error.validator)),
    )
    typed_violations = list(typed_object_violations(instance)) if not errors else []
    definition_name = case["schema_ref"].rsplit("/", 1)[-1]
    semantic = (
        semantic_violations(definition_name, instance)
        if not errors and not typed_violations
        else []
    )
    publication = (
        publication_violations(instance)
        if not errors and not typed_violations and not semantic
        else []
    )

    if case["expect"] == "valid":
        assert not errors, "\n".join(error.message for error in errors)
        assert not typed_violations, typed_violations
        assert not semantic, semantic
        return

    expected = case["expected_error"]
    layer = case.get("validation_layer", "schema")
    expected_pair = (expected["keyword"], expected["instance_pointer"])
    if layer == "typed_object":
        assert not errors
        assert expected_pair in typed_violations
        return
    if layer == "semantic":
        assert not errors
        assert not typed_violations
        assert expected_pair in semantic
        return
    if layer == "publication":
        assert not errors
        assert not typed_violations
        assert not semantic
        assert expected_pair in publication
        return

    assert errors, "invalid fixture unexpectedly passed structural validation"
    flattened = [nested for error in errors for nested in walk_errors(error)]
    actual = [
        (error.validator, json_pointer(error.absolute_path)) for error in flattened
    ]
    assert expected_pair in actual, f"expected {expected_pair!r}; got {actual!r}"


def test_api01_schema_is_valid_and_all_references_resolve_offline() -> None:
    assert SCHEMA["$schema"] == DRAFT_2020_12
    Draft202012Validator.check_schema(SCHEMA)
    resolver = REGISTRY.resolver(base_uri=SCHEMA["$id"])
    for schema_ref in iter_schema_references(SCHEMA):
        assert resolver.lookup(schema_ref).contents is not None
    for case in fixture_cases():
        assert resolver.lookup(case["schema_ref"]).contents is not None


def test_api01_v0_exposes_no_plugin_framework_surface() -> None:
    serialized_schema = json.dumps(SCHEMA, ensure_ascii=False, sort_keys=True).lower()
    assert "plugin" not in serialized_schema
    assert "trust_class" not in serialized_schema

    authoring = strict_json_load(
        FIXTURE_ROOT / "valid" / "authoring-document.minimal-static.json"
    )
    authoring["plugins"] = []
    errors = list(
        validator_for(f"{SCHEMA['$id']}#/$defs/AuthoringDocument").iter_errors(
            authoring
        )
    )
    assert any(error.validator == "additionalProperties" for error in errors)

    code_package = strict_json_load(
        FIXTURE_ROOT / "invalid" / "code-package.mutable-entrypoint-url.json"
    )
    code_package["entrypoint"] = "mug_study.policy:BallChaser"
    validator_for(f"{SCHEMA['$id']}#/$defs/CodePackageRef").validate(code_package)


def test_api01_fixture_manifest_is_valid_unique_and_complete() -> None:
    validator_for(f"{SCHEMA['$id']}#/$defs/FixtureManifest").validate(MANIFEST)
    case_ids = [case["id"] for case in fixture_cases()]
    assert len(case_ids) == len(set(case_ids))

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


def test_api01_schema_refs_bind_the_current_draft_bundle() -> None:
    expected = canonical_digest(SCHEMA)
    paths = [MANIFEST_PATH, *(FIXTURE_ROOT / case["instance"] for case in fixture_cases())]
    for path in paths:
        document = strict_json_load(path)
        for schema_ref in iter_schema_ref_objects(document):
            if schema_ref["name"] in API_BUNDLE_SCHEMA_NAMES:
                assert schema_ref["version"] == 0, path
                assert schema_ref["digest"]["hex"] == expected, path


def test_manifest_set_closes_over_exact_fixture_bytes() -> None:
    manifest_set = strict_json_load(
        FIXTURE_ROOT / "valid" / "manifest-set.minimal-static.json"
    )
    assert not _manifest_set_violations(manifest_set)


def test_publication_compiler_rejects_every_version_zero_schema() -> None:
    for filename in (
        "authoring-document.minimal-static.json",
        "scientific-manifest.minimal-static.json",
        "manifest-set.minimal-static.json",
        "published-version.minimal-static.json",
    ):
        document = strict_json_load(FIXTURE_ROOT / "valid" / filename)
        assert publication_violations(document), filename
