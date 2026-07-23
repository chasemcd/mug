"""Offline schema resolution against the frozen corpus.

The frozen JSON-Schema corpus is the authoritative contract. This module loads a
schema bundle, validates a value against a named definition with a Draft 2020-12
validator, and verifies that a ``SchemaRef`` digest matches the bundle.
Resolution is offline and allowlisted: a ``$ref`` never triggers a network
fetch, and an unknown schema fails closed.

A family bundle (for example API-11 storage) ``$ref``s into the shared kernel, so
``load_family_schema`` registers the shared-kernel bundle as a referenced
resource next to the family bundle.

The corpus currently lives under ``docs/architecture/``. A later step vendors it
into the package; the public functions here stay the same.
"""

from __future__ import annotations

import json
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from mug.kernel.canonical import sha256_hex
from mug.kernel.refs import SchemaRef

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PHASE0 = _REPO_ROOT / "docs/architecture/phase-0"
_SHARED_KERNEL_PATH = _PHASE0 / "shared-kernel/schemas/v0/shared-kernel.schema.json"

_FORMAT_CHECKER = Draft202012Validator.FORMAT_CHECKER


class SchemaNotFoundError(LookupError):
    """Raised when a requested schema definition is not in the bundle."""


def _load_document(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry_for(documents: list[dict[str, Any]]) -> Registry[Any]:
    """Build an offline registry keyed by each document's ``$id``."""
    registry: Registry[Any] = Registry()
    for document in documents:
        # `referencing` ships no precise types, so pyright cannot narrow these.
        resource = Resource.from_contents(document)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        registry = registry.with_resource(document["$id"], resource)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    return registry


class SchemaBundle:
    """One loaded schema bundle plus its offline validators.

    The primary document owns the ``$defs`` this bundle validates. Referenced
    documents (for example the shared kernel) resolve ``$ref`` targets but are
    not the validation surface.
    """

    def __init__(
        self,
        document: dict[str, Any],
        referenced: list[dict[str, Any]] | None = None,
    ) -> None:
        self._document = document
        self._primary_id: str = document["$id"]
        self._registry = _registry_for([document, *(referenced or [])])

    @property
    def document(self) -> dict[str, Any]:
        """The raw primary schema document."""
        return self._document

    @property
    def bundle_digest(self) -> str:
        """The canonical SHA-256 hex of the whole primary document."""
        return sha256_hex(self._document)

    def def_names(self) -> frozenset[str]:
        """The names of every ``$defs`` entry in the primary bundle."""
        return frozenset(self._document.get("$defs", {}))

    def validator_for(self, def_name: str) -> Draft202012Validator:
        """Return a validator bound to one ``$defs`` definition."""
        if def_name not in self._document.get("$defs", {}):
            raise SchemaNotFoundError(def_name)
        schema = {
            "$schema": self._document["$schema"],
            "$ref": f"{self._primary_id}#/$defs/{def_name}",
        }
        return Draft202012Validator(
            schema, registry=self._registry, format_checker=_FORMAT_CHECKER
        )

    def validate(self, def_name: str, instance: Any) -> None:
        """Validate an instance against a definition; raise on the first error."""
        # jsonschema's validate signature is untyped in the stubs.
        self.validator_for(def_name).validate(instance)  # pyright: ignore[reportUnknownMemberType]

    def is_valid(self, def_name: str, instance: Any) -> bool:
        """Return whether an instance validates against a definition."""
        # jsonschema's is_valid signature is untyped in the stubs.
        return self.validator_for(def_name).is_valid(instance)  # pyright: ignore[reportUnknownMemberType]

    def verify_ref(self, ref: SchemaRef) -> None:
        """Verify that a ``SchemaRef`` pins version 0 and this bundle's digest.

        A mismatch is an integrity failure and raises.
        """
        if ref.version != 0:
            raise ValueError(f"schema {ref.name} must pin version 0")
        if ref.digest.hex != self.bundle_digest:
            raise ValueError(f"schema {ref.name} digest does not match the bundle")


# Backwards-compatible name for the shared-kernel bundle.
SharedKernelSchema = SchemaBundle


@lru_cache(maxsize=1)
def load_shared_kernel_schema() -> SchemaBundle:
    """Load and cache the frozen shared-kernel schema bundle."""
    return SchemaBundle(_load_document(_SHARED_KERNEL_PATH))


@cache
def load_family_schema(schema_path: str) -> SchemaBundle:
    """Load a family bundle with the shared kernel registered as a reference.

    ``schema_path`` is a string so the result is cacheable. It points at the
    family ``*.schema.json`` file.
    """
    family = _load_document(Path(schema_path))
    shared_kernel = _load_document(_SHARED_KERNEL_PATH)
    return SchemaBundle(family, referenced=[shared_kernel])
