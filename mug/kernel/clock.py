"""Frozen ordering and fencing references.

These reference objects are the portable, persistable projections of the runtime
ordering and lease machinery. They carry stream positions, cursors, producer
positions, and the non-secret lease reference.

The runtime-authority structures (``FencingClaim``, the monotonic clock tuples,
``CommandContext``) are coordinator-local and nonportable. ADR-0009/0010 keep
their byte-freeze deferred to the API-06/12 runtime layer, so this module does
not model them as wire contracts.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from mug.kernel._base import KernelModel
from mug.kernel.ids import id_pattern
from mug.kernel.refs import Digest, NonNegativeSafeInteger, PositiveSafeInteger

_STREAM_ID = Annotated[str, Field(pattern=id_pattern("stream"))]


class Duration(KernelModel):
    """A nonnegative, portable duration in whole microseconds."""

    microseconds: NonNegativeSafeInteger


class StreamPosition(KernelModel):
    """A single stream identity paired with a committed sequence number."""

    stream_id: _STREAM_ID
    sequence: PositiveSafeInteger


class EventCursor(KernelModel):
    """A read position in one stream. ``after_sequence`` 0 is before the first event."""

    stream_id: _STREAM_ID
    after_sequence: NonNegativeSafeInteger


class LeaseRef(KernelModel):
    """The non-secret, persistable reference to a lease and its generation."""

    lease_id: Annotated[str, Field(pattern=id_pattern("lease"))]
    namespace_epoch_id: Annotated[str, Field(pattern=id_pattern("leaseepoch"))]
    generation: PositiveSafeInteger


class ProducerPosition(KernelModel):
    """A producer epoch, its per-epoch sequence, and the content digest."""

    epoch_id: Annotated[str, Field(pattern=id_pattern("prodepoch"))]
    sequence: PositiveSafeInteger
    content_digest: Digest


# A map of stream identifier to committed sequence (schema `StreamPositions`).
StreamPositions = Annotated[
    dict[_STREAM_ID, PositiveSafeInteger],
    Field(max_length=64),
]
