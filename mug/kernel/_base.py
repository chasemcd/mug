"""Base model for the frozen kernel contract objects.

Every kernel typed object is a frozen Pydantic v2 model. The model forbids
unknown fields and uses the Python regular-expression engine, so its pattern
semantics match the frozen JSON-Schema corpus exactly.
"""

from __future__ import annotations

import warnings

from pydantic import BaseModel, ConfigDict

# The wire contract names a field ``schema`` on several typed objects (for
# example ``TypedObject`` and ``WireCommandEnvelope``). That name shadows a
# deprecated ``BaseModel.schema`` attribute, so Pydantic warns at class
# definition. The field works and serializes as ``schema``. We keep the
# contract field name and silence this one benign warning. Every model module
# imports this module before it defines such a class, so the filter is active in
# time.
warnings.filterwarnings(
    "ignore",
    message=r'Field name "schema" .*shadows an attribute in parent',
    category=UserWarning,
)


class KernelModel(BaseModel):
    """Frozen, closed base for a shared-kernel typed object.

    The configuration mirrors the schema rules:

    - ``frozen`` makes an instance immutable, so a contract object holds data
      and never mutates in place.
    - ``extra="forbid"`` maps to ``additionalProperties: false``.
    - ``regex_engine="python-re"`` makes field patterns match the JSON-Schema
      patterns exactly (no Rust-regex divergence).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        regex_engine="python-re",
    )
