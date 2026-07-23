"""RFC 8785 (JCS) Python conformance for the MUG Phase 0 contract corpus.

Locks the vetted `rfc8785` library AND the contract harness
(`canonical_bytes` / `canonical_digest`) to the shared conformance vectors in
`rfc8785-vectors.json`. The same vectors are replayed in a real browser by
`test_rfc8785_browser_conformance.py`, proving Python(rfc8785) == browser(JS
JCS). G5 gate of the kernel promotion slice.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import rfc8785

from tests.architecture._contract_harness import canonical_bytes, canonical_digest

VECTORS_PATH = Path(__file__).with_name("rfc8785-vectors.json")
VECTORS: list[dict] = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def _ids() -> list[str]:
    return [vector["name"] for vector in VECTORS]


def test_vector_file_is_wellformed() -> None:
    assert VECTORS, "no conformance vectors loaded"
    names = [vector["name"] for vector in VECTORS]
    assert len(names) == len(set(names)), "duplicate vector names"
    for vector in VECTORS:
        assert set(vector) == {"name", "value", "canonical", "sha256"}, vector["name"]
        assert isinstance(vector["canonical"], str)
        assert isinstance(vector["sha256"], str)
        assert len(vector["sha256"]) == 64


@pytest.mark.parametrize("vector", VECTORS, ids=_ids())
def test_rfc8785_library_matches_vector(vector: dict) -> None:
    produced = rfc8785.dumps(vector["value"])
    assert produced.decode("utf-8") == vector["canonical"]
    assert hashlib.sha256(vector["canonical"].encode("utf-8")).hexdigest() == vector[
        "sha256"
    ]
    assert hashlib.sha256(produced).hexdigest() == vector["sha256"]


@pytest.mark.parametrize("vector", VECTORS, ids=_ids())
def test_contract_harness_reproduces_vector(vector: dict) -> None:
    """The harness the whole Phase 0 corpus depends on must agree byte-for-byte."""
    assert canonical_bytes(vector["value"]).decode("utf-8") == vector["canonical"]
    assert canonical_digest(vector["value"]) == vector["sha256"]
