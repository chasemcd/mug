"""Sign and verify the participant return link (a stateless resume token).

A returning participant presents a return token to resume the same visit. The
token must be one the server issued, unchanged, and inside its return window.
Without a signature the resume token is the bare flow id: a stolen or guessed
flow id would resume another participant's visit. A signed token closes that gap
-- only a token the server minted, with its claims intact, resumes a visit.

The token is stateless: it carries its claims and a keyed signature, so a verify
needs no store read. ``sign_return_link`` builds ``<claims>.<mac>`` where the
claims are base64url json and the mac is the HMAC-SHA256 of the claims under the
server signing key. ``verify_return_link`` recomputes the mac in constant time
and returns the claims only when it matches; the caller owns the clock and checks
the expiry.

The module depends on nothing in the platform, so any layer may sign or verify.
It never logs, and it names no token value in a returned value.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class ReturnClaims:
    """The claims a return token carries: the flow to resume and its expiry.

    ``flow_id`` names the visit's flow the resume rehydrates. ``expires_at`` is
    the wire-format instant past which the token no longer resumes; the caller
    owns the clock and rejects an expired token.
    """

    flow_id: str
    expires_at: str


def _b64encode(raw: bytes) -> str:
    """Encode bytes as unpadded base64url ascii."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    """Decode unpadded base64url ascii; raises on malformed input."""
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _mac(signing_key: bytes, message: str) -> str:
    """Compute the base64url HMAC-SHA256 of one message under the signing key."""
    digest = hmac.new(signing_key, message.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def sign_return_link(signing_key: bytes, claims: ReturnClaims) -> str:
    """Build one signed return token: ``<base64url-claims>.<base64url-mac>``.

    The claims serialize with sorted keys and no spaces, so the same claims
    always sign to the same token. The mac binds the claims to the signing key,
    so a change to either the flow id or the expiry breaks the signature.
    """
    body = json.dumps(
        {"flow_id": claims.flow_id, "expires_at": claims.expires_at},
        separators=(",", ":"),
        sort_keys=True,
    )
    message = _b64encode(body.encode("utf-8"))
    return message + "." + _mac(signing_key, message)


def verify_return_link(signing_key: bytes, token: str) -> ReturnClaims | None:
    """Return the claims when the token is well-formed and its mac matches.

    It splits the token, recomputes the mac over the claims part, and compares in
    constant time. A malformed token, a bad signature, or claims that are not the
    expected shape all return ``None``. Expiry is not checked here; the caller
    owns the clock.
    """
    message, separator, mac = token.partition(".")
    if not separator or not mac or "." in mac:
        return None
    if not hmac.compare_digest(_mac(signing_key, message), mac):
        return None
    try:
        data: Any = json.loads(_b64decode(message))
    except (binascii.Error, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    claims = cast("dict[str, Any]", data)
    flow_id = claims.get("flow_id")
    expires_at = claims.get("expires_at")
    if not isinstance(flow_id, str) or not isinstance(expires_at, str):
        return None
    return ReturnClaims(flow_id=flow_id, expires_at=expires_at)
