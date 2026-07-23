"""Generate the cross-language kernel conformance vectors.

The Python kernel is the source of truth. This module builds the three vector
sets -- canonicalization, identifier encoding, and the typed-object envelope --
from the live Python kernel and writes them under ``vectors/``. The TypeScript
twin reads the same files and must reproduce every field, so the two languages
agree by construction.

Run it as a module to refresh the files after a deliberate kernel change::

    uv run python -m tests.conformance.generate_vectors

The conformance test also calls ``build_all`` and asserts the on-disk files equal
a fresh build, so a stale or hand-edited vector fails the build.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mug.kernel import sha256_hex
from mug.kernel.canonical import canonical_bytes
from mug.kernel.ids import ID_KIND_REGISTRY, RESERVED_ID_PREFIXES

VECTORS_DIR = Path(__file__).resolve().parent / "vectors"

# One canonical, valid UUIDv7 body reused across every identifier vector: version
# nibble 7, variant nibble 8. The body is never a trusted time or entropy source,
# so a fixed value is correct for a vector.
_UUID = "0190b2a0-1c3d-7f00-8abc-000000000001"

# The canonicalization corpus. Each value exercises one rule: member ordering,
# nesting, unicode escaping, the ECMAScript number basis, and the real kernel
# object shapes (a digest, a schema reference, a typed-object envelope). The
# number cases match the frozen G5 RFC 8785 browser-conformance corpus.
_CANONICAL_VALUES: list[tuple[str, Any]] = [
    ("object-key-ordering", {"b": 1, "a": 2, "c": 3}),
    ("object-nested", {"z": {"b": 2, "a": 1}, "a": [3, 2, 1]}),
    ("object-empty", {}),
    ("array-empty", []),
    ("array-nested", [[1, 2], [3, [4, 5]]]),
    ("string-unicode", {"greeting": "héllo", "emoji": "😀"}),
    ("string-escapes", {"quote": 'a"b', "backslash": "a\\b", "newline": "a\nb"}),
    ("string-control", {"tab": "a\tb", "cr": "a\rb"}),
    ("number-integer", {"n": 42}),
    ("number-negative", {"n": -17}),
    ("number-zero", {"n": 0}),
    ("number-integral-float", {"n": 1.0}),
    ("number-fraction", {"n": 1.5}),
    ("boolean-and-null", {"t": True, "f": False, "n": None}),
    ("nested-mixed", {"list": [{"k": "v"}, [1, [2, 3]]], "flag": True}),
    (
        "kernel-digest",
        {
            "algorithm": "sha-256",
            "hex": (
                "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
            ),
        },
    ),
    (
        "kernel-schema-ref",
        {
            "name": "mug.command-envelope",
            "version": 0,
            "digest": {
                "algorithm": "sha-256",
                "hex": (
                    "e145110e712e3ed0a6b233551b27a90aa39b4c93ed67e111ba2002d16e5ed1fa"
                ),
            },
        },
    ),
    (
        "kernel-typed-object",
        {
            "schema": {
                "name": "mug.study.publish",
                "version": 0,
                "digest": {
                    "algorithm": "sha-256",
                    "hex": (
                        "f613a572f53e0e577f557af7e41633d7c30546ae97e1e20b8ad0dbea"
                        "7118d7a6"
                    ),
                },
            },
            "data": {"study_id": f"study_{_UUID}", "title": "A study"},
        },
    ),
]


def _canonicalization_vectors() -> dict[str, Any]:
    vectors: list[dict[str, Any]] = []
    for name, value in _CANONICAL_VALUES:
        canonical = canonical_bytes(value).decode("utf-8")
        vectors.append(
            {
                "name": name,
                "value": value,
                "canonical": canonical,
                "sha256": sha256_hex(value),
            }
        )
    return {"kind": "canonicalization", "vectors": vectors}


# A representative spread of active kinds, plus every failure mode the twin's
# ``parseId`` / ``isRegisteredId`` must reject.
_ID_KINDS_SAMPLED = (
    "study",
    "participant",
    "event",
    "stream",
    "command",
    "artifact",
    "prefassign",
)


def _id_vectors() -> dict[str, Any]:
    active = {kind.prefix for kind in ID_KIND_REGISTRY}
    vectors: list[dict[str, Any]] = []

    for prefix in _ID_KINDS_SAMPLED:
        assert prefix in active
        identifier = f"{prefix}_{_UUID}"
        vectors.append(
            {
                "name": f"valid-{prefix}",
                "id": identifier,
                "registered": True,
                "kind": prefix,
                "uuid": _UUID,
            }
        )

    reserved = sorted(RESERVED_ID_PREFIXES)[0]
    invalid: list[tuple[str, str]] = [
        ("reserved-prefix", f"{reserved}_{_UUID}"),
        ("unknown-prefix", f"widget_{_UUID}"),
        ("uuid-wrong-version", "study_0190b2a0-1c3d-6f00-8abc-000000000001"),
        ("uuid-wrong-variant", "study_0190b2a0-1c3d-7f00-7abc-000000000001"),
        ("uuid-uppercase", "study_0190B2A0-1C3D-7F00-8ABC-000000000001"),
        ("missing-underscore", f"study{_UUID}"),
        ("empty", ""),
        ("prefix-only", "study_"),
    ]
    for name, identifier in invalid:
        vectors.append(
            {
                "name": f"invalid-{name}",
                "id": identifier,
                "registered": False,
                "kind": None,
                "uuid": None,
            }
        )
    return {"kind": "ids", "vectors": vectors}


_DIGEST_HEX = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
_GOOD_SCHEMA_REF = {
    "name": "mug.study.publish",
    "version": 0,
    "digest": {"algorithm": "sha-256", "hex": _DIGEST_HEX},
}


def _typed_object_vectors() -> dict[str, Any]:
    valid_value = {"schema": _GOOD_SCHEMA_REF, "data": {"study_id": f"study_{_UUID}"}}
    vectors: list[dict[str, Any]] = [
        {
            "name": "valid-typed-object",
            "value": valid_value,
            "valid": True,
            "canonical": canonical_bytes(valid_value).decode("utf-8"),
            "sha256": sha256_hex(valid_value),
        },
        {
            "name": "valid-empty-data",
            "value": {"schema": _GOOD_SCHEMA_REF, "data": {}},
            "valid": True,
            "canonical": canonical_bytes(
                {"schema": _GOOD_SCHEMA_REF, "data": {}}
            ).decode("utf-8"),
            "sha256": sha256_hex({"schema": _GOOD_SCHEMA_REF, "data": {}}),
        },
    ]
    invalid: list[tuple[str, Any]] = [
        ("missing-schema", {"data": {}}),
        ("missing-data", {"schema": _GOOD_SCHEMA_REF}),
        ("data-is-array", {"schema": _GOOD_SCHEMA_REF, "data": []}),
        (
            "bad-schema-name",
            {
                "schema": {
                    "name": "study.publish",
                    "version": 0,
                    "digest": {"algorithm": "sha-256", "hex": _DIGEST_HEX},
                },
                "data": {},
            },
        ),
        (
            "bad-digest-hex",
            {
                "schema": {
                    "name": "mug.study.publish",
                    "version": 0,
                    "digest": {"algorithm": "sha-256", "hex": "abc"},
                },
                "data": {},
            },
        ),
        (
            "negative-version",
            {
                "schema": {
                    "name": "mug.study.publish",
                    "version": -1,
                    "digest": {"algorithm": "sha-256", "hex": _DIGEST_HEX},
                },
                "data": {},
            },
        ),
    ]
    for name, value in invalid:
        vectors.append(
            {
                "name": name,
                "value": value,
                "valid": False,
                "canonical": None,
                "sha256": None,
            }
        )
    return {"kind": "typed-object", "vectors": vectors}


def build_all() -> dict[str, dict[str, Any]]:
    """Build every vector set from the live Python kernel."""
    return {
        "canonicalization": _canonicalization_vectors(),
        "ids": _id_vectors(),
        "typed-object": _typed_object_vectors(),
    }


def _serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_all(directory: Path = VECTORS_DIR) -> None:
    """Write every vector set to ``directory`` as formatted JSON."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, payload in build_all().items():
        (directory / f"{name}.json").write_text(_serialize(payload), encoding="utf-8")


if __name__ == "__main__":
    write_all()
    print(f"wrote kernel conformance vectors to {VECTORS_DIR}")
