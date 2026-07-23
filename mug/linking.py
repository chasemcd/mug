"""Link a recruitment-platform participant to a pseudonymous enrolment (API-03).

A study run on Prolific (or behind an OIDC provider, or an institution roster)
receives each participant with an external subject id in the launch URL. That id
names a real person, so it must not enter the study data. This boundary blinds it
the moment it arrives and never keeps the raw value: it derives the opaque handle,
issues an ``ExternalIdentityLink`` keyed by that handle, and returns only the
handle and the enrolment it points at.

The link round-trips without the raw id. A returning participant presents the
same external id; ``resolve_enrollment`` blinds it the same way and reads the link
back by its handle to recover the enrolment. So the platform admits the same
person once and recognizes them on return, while the data holds only the blinded
handle -- no external id in any record, event, or export.

The module lives beside ``mug.launch``, above the gateway. It composes the
identity command family and the blinding primitive by reference; no inner layer
imports it. The server key is resolved by name at the boundary (``blinding_key``),
mirroring the return-link key; the handler never sees a raw external id.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from typing import Literal

from mug.gateway import Gateway
from mug.identity import LinkIdentityCommand, blind_external_id, link_identity
from mug.identity.types import ExternalIdentityLink
from mug.kernel import DataHandlingRef, Digest, PrincipalRef, WireCommandEnvelope
from mug.storage import Store

Provider = Literal["prolific", "mturk", "oidc", "institution", "contact"]

# An external identity link always carries a pii label beside the research label.
_LINK_HANDLING = DataHandlingRef(privacy_labels=["research", "pii"])
_ENVELOPE_DIGEST = Digest(algorithm="sha-256", hex="0" * 64)


@dataclass(frozen=True)
class LinkProvision:
    """The result of linking one external participant: the handle and enrolment.

    ``subject_handle`` is the blinded external subject id -- the token key. The
    raw external id is not a field here; the boundary consumed it and kept only
    the handle. ``enrollment_id`` and ``provider`` name what the link points at.
    """

    subject_handle: str
    enrollment_id: str
    provider: str


def blinding_key_from_env() -> bytes | None:
    """Return the identity-blinding key from ``MUG_IDENTITY_BLINDING_KEY``, or None.

    A deployment sets ``MUG_IDENTITY_BLINDING_KEY`` to a long random secret, so a
    blinded handle stays stable across a restart -- a returning participant is
    recognized even after the server has restarted. With the variable unset a
    fresh per-process key is used, so the links do not survive a restart.
    """
    secret = os.environ.get("MUG_IDENTITY_BLINDING_KEY")
    return secret.encode("utf-8") if secret else None


def _idem(handle: str) -> str:
    """Derive one stable idempotency key from the blinded handle.

    The key is a function of the handle alone, so a genuine retry of the same
    link (same external id, so the same handle) replays with no second effect,
    while a different external id keys a different link.
    """
    raw = hashlib.sha256(b"identity.link" + handle.encode("ascii")).digest()[:16]
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return "idem_" + body


def _envelope(
    enrollment_id: str, data: dict[str, object], idem: str
) -> WireCommandEnvelope:
    """Build a wire envelope for one server-side link command."""
    schema = {
        "name": "mug.command-envelope",
        "version": 0,
        "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
    }
    return WireCommandEnvelope.model_validate(
        {
            "schema": schema,
            "protocol_version": "0.1.0",
            "command": {"name": "identity.link", "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-000000000001",
            "idempotency_key": idem,
            "target": {"id": enrollment_id},
            "payload": {
                "schema": {
                    "name": "mug.edge.payload",
                    "version": 0,
                    "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
                },
                "data": data,
            },
        }
    )


async def provision_identity_link(
    gateway: Gateway,
    store: Store,
    *,
    researcher: PrincipalRef,
    enrollment_id: str,
    provider: Provider,
    external_id: str,
    blinding_key: bytes,
) -> LinkProvision:
    """Blind one external subject id and link it to a pseudonymous enrolment.

    It derives the opaque handle from the external id, then issues the link
    through the real ``link_identity`` handler, keyed by that handle. The raw
    external id is used only to derive the handle; it never enters the command,
    the record, or the returned value. A second call with the same external id
    blinds to the same handle and replays with no second effect.
    """
    handle = blind_external_id(blinding_key, provider, external_id)
    envelope = _envelope(
        enrollment_id,
        {
            "enrollment_id": enrollment_id,
            "provider": provider,
            "external_subject_handle": handle,
            "data_handling": _LINK_HANDLING.model_dump(mode="json"),
        },
        _idem(handle),
    )
    context = gateway.mint(
        envelope,
        principal=researcher,
        data_handling=_LINK_HANDLING,
        handle=handle,
    )
    receipt = await link_identity(
        LinkIdentityCommand(
            enrollment_id=enrollment_id,
            provider=provider,
            external_subject_handle=handle,
            data_handling=_LINK_HANDLING,
        ),
        context=context,
        store=store,
    )
    if receipt.outcome != "accepted":
        raise RuntimeError("the external identity link could not be issued")
    return LinkProvision(
        subject_handle=handle, enrollment_id=enrollment_id, provider=provider
    )


def resolve_enrollment(
    store: Store,
    *,
    provider: Provider,
    external_id: str,
    blinding_key: bytes,
) -> str | None:
    """Return the enrolment a returning external participant was linked to.

    It blinds the external id the same way the link did and reads the token back
    by that handle. It returns the enrolment id when a link exists, or None when
    the participant has not been linked. The raw external id is used only to
    derive the handle and is never stored or logged.
    """
    handle = blind_external_id(blinding_key, provider, external_id)
    raw = store.load_token(handle)
    if raw is None:
        return None
    return ExternalIdentityLink.model_validate(raw).enrollment_id
