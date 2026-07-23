"""The typed-object envelope.

A ``TypedObject`` wraps a data object with the ``SchemaRef`` that identifies its
schema. It is the carrier for a command payload, an accepted receipt result, and
a domain-error detail. The data has no domain meaning until a reader resolves the
referenced schema and validates the data against it (second-stage validation).
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from mug.kernel._base import KernelModel
from mug.kernel.refs import SchemaRef


class TypedObject(KernelModel):
    """A schema reference plus the data it describes."""

    # The contract names this field 'schema'; it shadows the deprecated
    # BaseModel.schema. We keep the contract name.
    schema: SchemaRef  # pyright: ignore[reportIncompatibleMethodOverride]
    data: Annotated[dict[str, Any], Field(max_length=256)]
