"""Issue and redeem transient, one-use browser ICE grants for API-09.

The registry keeps no TURN credential. It derives a short-lived credential only
when an unguessable grant is redeemed, and the edge sends that value in a direct
``no-store`` response.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"


class TurnSecret:
    """Hold a long-lived TURN secret without exposing it through repr or str."""

    __slots__ = ("_value",)

    def __init__(self, value: bytes) -> None:
        if len(value) < 16:
            raise ValueError("the TURN secret must contain at least 16 bytes")
        self._value = bytes(value)

    def derive(self, username: str) -> str:
        """Derive the coturn REST credential for one expiring username."""
        digest = hmac.new(self._value, username.encode("utf-8"), hashlib.sha1).digest()
        return base64.b64encode(digest).decode("ascii")

    def __repr__(self) -> str:
        return "TurnSecret(<redacted>)"

    __str__ = __repr__


@dataclass(frozen=True)
class IceGrant:
    """The non-secret handle and expiry placed in a peer bootstrap."""

    handle: str
    expires_at: str


@dataclass(frozen=True, repr=False)
class IceCredentialResponse:
    """A transient browser ICE response whose representation hides credentials."""

    stun_urls: tuple[str, ...]
    turn_urls: tuple[str, ...]
    username: str | None
    credential: str | None
    force_relay: bool

    def __repr__(self) -> str:
        return "IceCredentialResponse(<redacted>)"

    def as_json(self) -> dict[str, Any]:
        """Build the direct WebRTC configuration response."""
        servers: list[dict[str, Any]] = []
        if self.stun_urls:
            servers.append({"urls": list(self.stun_urls)})
        if self.turn_urls and self.username is not None and self.credential is not None:
            servers.append(
                {
                    "urls": list(self.turn_urls),
                    "username": self.username,
                    "credential": self.credential,
                }
            )
        return {
            "iceServers": servers,
            "iceTransportPolicy": "relay" if self.force_relay else "all",
        }


@dataclass(frozen=True)
class IceServerConfig:
    """Configure public ICE servers and one optional private TURN secret."""

    turn_secret: TurnSecret | None = None
    stun_urls: tuple[str, ...] = ()
    turn_urls: tuple[str, ...] = ()
    ttl_seconds: int = 60
    force_relay: bool = False


class IceGrantError(RuntimeError):
    """A safe refusal to redeem an ICE grant."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


@dataclass
class _GrantState:
    browser_session_handle: str
    room_handle: str
    peer_handle: str
    expires_at: datetime
    redeemed: bool = False


class IceGrantRegistry:
    """Keep short-lived grant handles and redeem each exactly once."""

    def __init__(
        self,
        *,
        new_handle: Callable[[], str],
        utc_now: Callable[[], datetime],
        config: IceServerConfig | None = None,
    ) -> None:
        resolved = config or IceServerConfig()
        if resolved.ttl_seconds < 5 or resolved.ttl_seconds > 300:
            raise ValueError("the ICE grant lifetime must be from 5 to 300 seconds")
        if resolved.turn_urls and resolved.turn_secret is None:
            raise ValueError("TURN URLs require a TURN secret")
        if resolved.force_relay and not resolved.turn_urls:
            raise ValueError("relay-only ICE requires at least one TURN URL")
        self._new_handle = new_handle
        self._utc_now = utc_now
        self._config = resolved
        self._grants: dict[str, _GrantState] = {}

    def issue(
        self, browser_session_handle: str, room_handle: str, peer_handle: str
    ) -> IceGrant:
        """Issue one unguessable short-lived grant without deriving a credential."""
        now = _aware(self._utc_now())
        expires_at = now + timedelta(seconds=self._config.ttl_seconds)
        handle = self._new_handle()
        self._grants[handle] = _GrantState(
            browser_session_handle=browser_session_handle,
            room_handle=room_handle,
            peer_handle=peer_handle,
            expires_at=expires_at,
        )
        self._discard_expired(now)
        return IceGrant(handle=handle, expires_at=expires_at.strftime(_INSTANT))

    def bound_session(self, handle: str) -> str | None:
        """Return the browser session one live grant was issued to, if any.

        A deployment that carries the visit in its own authenticated session names
        the browser itself, and redemption checks the two agree. A deployment that
        does not has only the grant, and the grant knows which browser it was made
        for. It is still the capability either way: unguessable, one-use, expiring,
        and bound to one room and one peer.
        """
        grant = self._grants.get(handle)
        return None if grant is None else grant.browser_session_handle

    def redeem(
        self,
        handle: str,
        browser_session_handle: str,
        room_handle: str,
        peer_handle: str,
    ) -> IceCredentialResponse:
        """Consume one current grant and derive its transient browser credential."""
        now = _aware(self._utc_now())
        grant = self._grants.get(handle)
        if grant is None:
            raise IceGrantError("resource.not_found", "the ICE grant is not valid")
        if (
            grant.browser_session_handle != browser_session_handle
            or grant.room_handle != room_handle
            or grant.peer_handle != peer_handle
        ):
            raise IceGrantError(
                "auth.forbidden", "the ICE grant is not bound to this peer"
            )
        if grant.redeemed:
            raise IceGrantError(
                "command.state_conflict", "the ICE grant was already used"
            )
        if grant.expires_at <= now:
            self._grants.pop(handle, None)
            raise IceGrantError("lease.expired", "the ICE grant has expired")
        grant.redeemed = True
        username: str | None = None
        credential: str | None = None
        if self._config.turn_secret is not None:
            expires_epoch = int(grant.expires_at.timestamp())
            username = f"{expires_epoch}:{handle.removeprefix('handle_')}"
            credential = self._config.turn_secret.derive(username)
        return IceCredentialResponse(
            stun_urls=self._config.stun_urls,
            turn_urls=self._config.turn_urls,
            username=username,
            credential=credential,
            force_relay=self._config.force_relay,
        )

    def _discard_expired(self, now: datetime) -> None:
        expired = [
            handle
            for handle, grant in self._grants.items()
            if grant.expires_at <= now or grant.redeemed
        ]
        for handle in expired:
            self._grants.pop(handle, None)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "IceCredentialResponse",
    "IceGrant",
    "IceGrantError",
    "IceGrantRegistry",
    "IceServerConfig",
    "TurnSecret",
]
