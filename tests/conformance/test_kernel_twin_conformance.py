"""Cross-language kernel conformance: Python kernel == TypeScript twin.

The shared vector sets under ``vectors/`` are the contract. The Python kernel
generates them, so the first two tests prove the Python side still reproduces
them byte for byte (and that no vector was hand-edited into drift). The last test
runs the TypeScript twin's conformance runner over the same files and asserts it
exits clean, so a single-byte divergence between the two languages fails the
build.

The TypeScript test needs a built ``ts/`` workspace and ``node`` on the path. In
continuous integration the workflow builds the workspace first, so the test runs
for real; on a machine without the build it skips with a clear message rather than
failing.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mug.kernel import TypedObject, sha256_hex
from mug.kernel.canonical import canonical_bytes
from mug.kernel.ids import ID_KIND_REGISTRY, UUIDV7
from tests.conformance.generate_vectors import build_all

_HERE = Path(__file__).resolve().parent
_VECTORS = _HERE / "vectors"
_REPO_ROOT = _HERE.parents[1]
_TS_ROOT = _REPO_ROOT / "ts"
_RUNNER = _TS_ROOT / "dist" / "conformance" / "run.js"

_REGISTERED = re.compile(
    "^(?:" + "|".join(k.prefix for k in ID_KIND_REGISTRY) + ")_" + UUIDV7 + "$"
)


def _load(name: str) -> dict[str, Any]:
    return json.loads((_VECTORS / f"{name}.json").read_text(encoding="utf-8"))


def test_on_disk_vectors_match_a_fresh_python_build() -> None:
    """The committed vectors equal a fresh build, so nothing has drifted."""
    fresh = build_all()
    for name, payload in fresh.items():
        assert _load(name) == payload, f"{name}.json is stale; regenerate it"


def test_python_kernel_reproduces_the_canonicalization_vectors() -> None:
    """The Python kernel reproduces every canonical string and digest."""
    for vector in _load("canonicalization")["vectors"]:
        value = vector["value"]
        assert canonical_bytes(value).decode("utf-8") == vector["canonical"]
        assert sha256_hex(value) == vector["sha256"]


def test_python_kernel_reproduces_the_id_vectors() -> None:
    """The Python id registry reproduces every identifier verdict and its parts."""
    for vector in _load("ids")["vectors"]:
        matched = _REGISTERED.match(vector["id"])
        assert bool(matched) == vector["registered"], vector["name"]
        if matched:
            kind, _, uuid = vector["id"].partition("_")
            assert kind == vector["kind"]
            assert uuid == vector["uuid"]


def test_python_kernel_reproduces_the_typed_object_vectors() -> None:
    """The Python typed-object model reproduces every envelope verdict."""
    for vector in _load("typed-object")["vectors"]:
        try:
            TypedObject.model_validate(vector["value"])
            valid = True
        except ValidationError:
            valid = False
        assert valid == vector["valid"], vector["name"]
        if vector["valid"]:
            value = vector["value"]
            assert canonical_bytes(value).decode("utf-8") == vector["canonical"]
            assert sha256_hex(value) == vector["sha256"]


def _ensure_built() -> None:
    """Build the ts/ workspace when its dependencies are present but dist is not.

    A build failure is tolerated, not fatal: the current TypeScript needs a modern
    node (see ``ts/.nvmrc``), so on a shell that still resolves an old system node
    the build simply produces no ``dist``, and the caller skips. Continuous
    integration builds with the pinned node first, so there the runner exists.
    """
    if _RUNNER.exists():
        return
    tsc = _TS_ROOT / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        return
    subprocess.run(
        [str(tsc), "-p", "tsconfig.json"],
        cwd=_TS_ROOT,
        capture_output=True,
        check=False,
        timeout=180,
    )


def test_typescript_twin_reproduces_every_vector() -> None:
    """The TypeScript twin's runner reproduces every shared vector (exit 0)."""
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node is not on the path")
    _ensure_built()
    if not _RUNNER.exists():
        pytest.skip("ts/ workspace is not built; run `npm ci && npm run build` in ts/")

    result = subprocess.run(
        ["node", str(_RUNNER), str(_VECTORS)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
