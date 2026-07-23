"""Identity, enrollment, and launch (API-03, layer L1).

This family owns three record types: the ``Enrollment`` that records a
participant in a study, the ``LaunchTicket`` that admits a participant to a
deployment, and the ``ExternalIdentityLink`` to an external provider. Each record
references the kernel (L0) principal, deployment, and privacy types; the family
adds no runtime.
"""

from __future__ import annotations

from mug.identity.linking import blind_external_id
from mug.identity.service import (
    EnrollCommand,
    LaunchCommand,
    LinkIdentityCommand,
    enroll,
    launch,
    link_identity,
)
from mug.identity.types import (
    Enrollment,
    ExternalIdentityLink,
    LaunchTicket,
    identity_schema,
)

__all__ = [
    "EnrollCommand",
    "Enrollment",
    "ExternalIdentityLink",
    "LaunchCommand",
    "LaunchTicket",
    "LinkIdentityCommand",
    "blind_external_id",
    "enroll",
    "identity_schema",
    "launch",
    "link_identity",
]
