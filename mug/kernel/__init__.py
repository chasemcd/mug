"""The MUG shared kernel (layer L0).

This package holds the frozen wire contract that every family depends on: typed
identifiers, references, canonicalization and digests, the typed-object
envelope, the command envelope and receipt, the error taxonomy, the ordering and
fencing references, and the privacy lattice.

The package depends on nothing else in ``mug``. The frozen JSON-Schema corpus is
the authority; the models here serve it, and a conformance test fails the build
on any drift.
"""

from __future__ import annotations

from mug.kernel.canonical import (
    CanonicalizationVector,
    CanonicalizationVectorSet,
    canonical_bytes,
    compute_digest,
    etag,
    sha256_hex,
)
from mug.kernel.clock import (
    Duration,
    EventCursor,
    LeaseRef,
    ProducerPosition,
    StreamPosition,
    StreamPositions,
)
from mug.kernel.command import (
    CommandReceipt,
    IdempotencyKey,
    ReceiptDurability,
    WireCommandEnvelope,
)
from mug.kernel.command_types import CommandPreconditions, CommandTypeRef
from mug.kernel.errors import (
    ERROR_CODES,
    DomainError,
    ErrorCategory,
    RetryDirective,
    RetryMode,
)
from mug.kernel.ids import (
    ACTIVE_ID_PREFIXES,
    ID_KIND_REGISTRY,
    RESERVED_ID_PREFIXES,
    IdKind,
    RegisteredMugId,
    id_pattern,
)
from mug.kernel.privacy import (
    ALLOWED_PRIVACY_LABELS,
    DataHandlingRef,
    PrivacyClassification,
    join,
)
from mug.kernel.refs import (
    ArtifactRef,
    CapabilitySet,
    Digest,
    InlineBytes,
    PrincipalRef,
    PublicHandle,
    ResourceRef,
    SchemaRef,
    SeatKey,
    SecretRef,
    SemVer,
    TraceContext,
    UtcInstant,
    VersionStamp,
)
from mug.kernel.schema import (
    SchemaBundle,
    SharedKernelSchema,
    load_family_schema,
    load_shared_kernel_schema,
)
from mug.kernel.typed_object import TypedObject

__all__ = [  # noqa: RUF022  (grouped by contract area for readability, not alphabetized)
    # canonical
    "canonical_bytes",
    "sha256_hex",
    "compute_digest",
    "etag",
    "CanonicalizationVector",
    "CanonicalizationVectorSet",
    # ids
    "ID_KIND_REGISTRY",
    "ACTIVE_ID_PREFIXES",
    "RESERVED_ID_PREFIXES",
    "IdKind",
    "RegisteredMugId",
    "id_pattern",
    # refs
    "Digest",
    "SchemaRef",
    "ResourceRef",
    "PrincipalRef",
    "ArtifactRef",
    "SecretRef",
    "VersionStamp",
    "PublicHandle",
    "InlineBytes",
    "CapabilitySet",
    "TraceContext",
    "SemVer",
    "SeatKey",
    "UtcInstant",
    # privacy
    "PrivacyClassification",
    "DataHandlingRef",
    "ALLOWED_PRIVACY_LABELS",
    "join",
    # typed object
    "TypedObject",
    # clock / ordering
    "Duration",
    "StreamPosition",
    "StreamPositions",
    "EventCursor",
    "LeaseRef",
    "ProducerPosition",
    # command
    "WireCommandEnvelope",
    "CommandReceipt",
    "ReceiptDurability",
    "IdempotencyKey",
    "CommandTypeRef",
    "CommandPreconditions",
    # errors
    "DomainError",
    "ErrorCategory",
    "RetryDirective",
    "RetryMode",
    "ERROR_CODES",
    # schema
    "SchemaBundle",
    "SharedKernelSchema",
    "load_shared_kernel_schema",
    "load_family_schema",
]
