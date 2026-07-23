"""Blind an external participant identifier into a stable, opaque handle.

A recruitment platform (Prolific, an OIDC provider, an institution) names a
participant by an external subject id -- a value that identifies a real person.
That id must never enter the study data: not a record, not an event, not an
export. But the platform still needs the study to admit the same person once, and
to recognize a returning person. A one-way blinded handle serves both ends.

``blind_external_id`` maps ``(provider, external_id)`` to a ``PublicHandle`` with
a keyed HMAC. The map is:

- deterministic -- the same external id always blinds to the same handle, so a
  link round-trips and a returning participant is recognized;
- one-way -- the handle is a truncated HMAC under a server key, so the external
  id cannot be recovered from the handle, and a guesser without the key cannot
  forge another participant's handle;
- provider-scoped -- the provider name is mixed in, so the same raw id under two
  providers blinds to two unrelated handles.

The module depends on nothing in the platform. The server key is supplied by the
caller (the boundary resolves it by name, as with the return-link key); this
function never reads a key from the environment and never logs the external id.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from mug.kernel.refs import PublicHandle

# The blinded provider names, matching the ExternalIdentityLink provider enum.
BLINDED_PROVIDERS = frozenset({"prolific", "mturk", "oidc", "institution", "contact"})


def blind_external_id(
    secret_key: bytes, provider: str, external_id: str
) -> PublicHandle:
    """Return the opaque public handle for one external subject id.

    The handle is the first sixteen bytes of the HMAC-SHA256 of
    ``<provider>:<external_id>`` under the server key, as unpadded base64url. The
    provider prefix domain-separates the two providers, so a shared raw id never
    correlates across them. Sixteen bytes render as twenty-two base64url
    characters whose last is one of ``A Q g w``, so the value fits the
    ``handle_...`` pattern the kernel enforces.
    """
    if provider not in BLINDED_PROVIDERS:
        raise ValueError(f"unknown external identity provider: {provider}")
    message = f"{provider}:{external_id}".encode()
    digest = hmac.new(secret_key, message, hashlib.sha256).digest()[:16]
    body = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return "handle_" + body
