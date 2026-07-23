"""Canonical serialization and digests.

Canonical JSON is RFC 8785 (the JSON Canonicalization Scheme). Every digest in
the system comes from these bytes. No other canonicalizer exists in the code.
Never digest a Pydantic serializer's output directly; pass the plain JSON value
(from ``model_dump(mode="json")``) through this module.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any

import rfc8785
from pydantic import Field

from mug.kernel._base import KernelModel
from mug.kernel.refs import CanonicalizationVectorsSchemaRef, Digest


def canonical_bytes(value: Any) -> bytes:
    """Return the RFC 8785 canonical bytes of a plain JSON value."""
    return rfc8785.dumps(value)


def sha256_hex(value: Any) -> str:
    """Return the lowercase SHA-256 hex of a value's canonical bytes."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def compute_digest(value: Any) -> Digest:
    """Return the structured ``Digest`` of a value's canonical bytes."""
    return Digest(algorithm="sha-256", hex=sha256_hex(value))


def etag(value: Any) -> str:
    """Return the ``sha256:<hex>`` entity tag of a value's canonical bytes."""
    return f"sha256:{sha256_hex(value)}"


class CanonicalizationVector(KernelModel):
    """One canonicalization test vector: a value, its bytes, and its digest."""

    id: Annotated[
        str, Field(pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$", max_length=96)
    ]
    value: Any
    canonical_utf8: Annotated[str, Field(max_length=65536)]
    digest: Digest


class CanonicalizationVectorSet(KernelModel):
    """A set of canonicalization vectors for cross-language conformance."""

    # 'schema' is the contract field name; it shadows BaseModel.schema.
    schema: CanonicalizationVectorsSchemaRef  # pyright: ignore[reportIncompatibleMethodOverride]
    vectors: Annotated[
        list[CanonicalizationVector], Field(min_length=1, max_length=128)
    ]
