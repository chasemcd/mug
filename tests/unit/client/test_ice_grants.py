"""An ICE grant is room-scoped, peer-scoped, expiring, and used exactly once.

The browser needs STUN and TURN configuration to open a peer connection, but the
long-lived TURN secret must stay in the server process. The registry issues an
opaque grant with the mesh bootstrap and derives a short-lived credential only
when the authenticated peer redeems that grant. These tests prove:

- a grant redeems once, and only for the browser session, room, and peer it was
  bound to;
- an unknown, reused, or expired grant fails closed with a safe code;
- the derived TURN credential is short-lived and specific to the grant, and the
  long-lived secret never appears in a repr or in the response object's repr;
- the direct JSON response is transient WebRTC configuration only.

The clock and the handle minter are injected, so no test reads a wall clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mug.client.ice import (
    IceCredentialResponse,
    IceGrantError,
    IceGrantRegistry,
    IceServerConfig,
    TurnSecret,
)

_START = datetime(2026, 7, 24, tzinfo=timezone.utc)
_SESSION = "handle_session01"
_ROOM = "handle_room01"
_PEER = "handle_peer01"


class _Clock:
    """A controllable UTC clock and handle minter for one registry."""

    def __init__(self) -> None:
        self.now = _START
        self.minted = 0

    def utc_now(self) -> datetime:
        return self.now

    def new_handle(self) -> str:
        self.minted += 1
        return f"handle_grant{self.minted:02d}"


def _registry(
    clock: _Clock, *, config: IceServerConfig | None = None
) -> IceGrantRegistry:
    return IceGrantRegistry(
        new_handle=clock.new_handle,
        utc_now=clock.utc_now,
        config=config,
    )


def _turn_config(**overrides: object) -> IceServerConfig:
    base: dict[str, object] = {
        "turn_secret": TurnSecret(b"0123456789abcdef"),
        "stun_urls": ("stun:stun.example:3478",),
        "turn_urls": ("turn:turn.example:3478",),
        "ttl_seconds": 60,
    }
    base.update(overrides)
    return IceServerConfig(**base)  # type: ignore[arg-type]


def test_a_grant_redeems_once_and_derives_a_short_lived_credential() -> None:
    """The first redemption returns configuration; the second is a conflict."""
    clock = _Clock()
    registry = _registry(clock, config=_turn_config())
    grant = registry.issue(_SESSION, _ROOM, _PEER)

    response = registry.redeem(grant.handle, _SESSION, _ROOM, _PEER)

    assert response.turn_urls == ("turn:turn.example:3478",)
    assert response.username is not None
    assert response.credential is not None
    # The username carries the grant expiry, so the credential cannot outlive it.
    expiry = int((_START + timedelta(seconds=60)).timestamp())
    assert response.username.startswith(str(expiry))

    with pytest.raises(IceGrantError) as caught:
        registry.redeem(grant.handle, _SESSION, _ROOM, _PEER)
    assert caught.value.code == "command.state_conflict"


def test_a_grant_is_bound_to_its_session_room_and_peer() -> None:
    """A stolen handle cannot be redeemed from another binding."""
    clock = _Clock()
    registry = _registry(clock, config=_turn_config())
    grant = registry.issue(_SESSION, _ROOM, _PEER)

    for session, room, peer in (
        ("handle_other", _ROOM, _PEER),
        (_SESSION, "handle_room02", _PEER),
        (_SESSION, _ROOM, "handle_peer02"),
    ):
        with pytest.raises(IceGrantError) as caught:
            registry.redeem(grant.handle, session, room, peer)
        assert caught.value.code == "auth.forbidden"

    # The refused attempts did not consume the grant.
    assert registry.redeem(grant.handle, _SESSION, _ROOM, _PEER).username is not None


def test_an_unknown_grant_is_refused() -> None:
    """A guessed handle is not a capability."""
    registry = _registry(_Clock(), config=_turn_config())
    with pytest.raises(IceGrantError) as caught:
        registry.redeem("handle_guess", _SESSION, _ROOM, _PEER)
    assert caught.value.code == "resource.not_found"


def test_an_expired_grant_is_refused_and_discarded() -> None:
    """A grant past its short lifetime cannot be redeemed later."""
    clock = _Clock()
    registry = _registry(clock, config=_turn_config(ttl_seconds=30))
    grant = registry.issue(_SESSION, _ROOM, _PEER)

    clock.now = _START + timedelta(seconds=31)
    with pytest.raises(IceGrantError) as caught:
        registry.redeem(grant.handle, _SESSION, _ROOM, _PEER)
    assert caught.value.code == "lease.expired"

    with pytest.raises(IceGrantError) as again:
        registry.redeem(grant.handle, _SESSION, _ROOM, _PEER)
    assert again.value.code == "resource.not_found"


def test_two_grants_get_different_credentials() -> None:
    """A credential is derived per grant, so one browser cannot reuse another's."""
    clock = _Clock()
    registry = _registry(clock, config=_turn_config())
    first = registry.issue(_SESSION, _ROOM, _PEER)
    second = registry.issue("handle_session02", _ROOM, "handle_peer02")

    left = registry.redeem(first.handle, _SESSION, _ROOM, _PEER)
    right = registry.redeem(second.handle, "handle_session02", _ROOM, "handle_peer02")

    assert left.credential != right.credential


def test_the_long_lived_turn_secret_never_appears_in_a_representation() -> None:
    """A log line or a traceback cannot leak the deployment TURN secret."""
    secret = TurnSecret(b"0123456789abcdef")
    assert "0123456789abcdef" not in repr(secret)
    assert "0123456789abcdef" not in str(secret)

    clock = _Clock()
    registry = _registry(clock, config=_turn_config(turn_secret=secret))
    grant = registry.issue(_SESSION, _ROOM, _PEER)
    response = registry.redeem(grant.handle, _SESSION, _ROOM, _PEER)

    assert repr(response) == "IceCredentialResponse(<redacted>)"
    assert response.credential is not None
    assert response.credential not in repr(response)


def test_the_direct_response_is_transient_webrtc_configuration() -> None:
    """The redemption body carries ICE servers only, with no MUG record fields."""
    clock = _Clock()
    registry = _registry(clock, config=_turn_config(force_relay=True))
    grant = registry.issue(_SESSION, _ROOM, _PEER)

    body = registry.redeem(grant.handle, _SESSION, _ROOM, _PEER).as_json()

    assert set(body) == {"iceServers", "iceTransportPolicy"}
    assert body["iceTransportPolicy"] == "relay"
    servers = body["iceServers"]
    assert servers[0] == {"urls": ["stun:stun.example:3478"]}
    assert set(servers[1]) == {"urls", "username", "credential"}


def test_a_keyless_deployment_returns_stun_only() -> None:
    """A study with no TURN secret still gets a usable STUN configuration."""
    clock = _Clock()
    registry = _registry(
        clock, config=IceServerConfig(stun_urls=("stun:stun.example:3478",))
    )
    grant = registry.issue(_SESSION, _ROOM, _PEER)

    response = registry.redeem(grant.handle, _SESSION, _ROOM, _PEER)

    assert isinstance(response, IceCredentialResponse)
    assert response.username is None
    assert response.credential is None
    assert response.as_json()["iceServers"] == [{"urls": ["stun:stun.example:3478"]}]


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (IceServerConfig(ttl_seconds=1), "from 5 to 300 seconds"),
        (IceServerConfig(ttl_seconds=600), "from 5 to 300 seconds"),
        (IceServerConfig(turn_urls=("turn:turn.example:3478",)), "require a TURN"),
        (IceServerConfig(force_relay=True), "relay-only ICE requires"),
    ],
)
def test_an_unsafe_ice_configuration_is_refused(
    config: IceServerConfig, message: str
) -> None:
    """A deployment cannot configure an unbounded or unusable ICE policy."""
    with pytest.raises(ValueError, match=message):
        _registry(_Clock(), config=config)


def test_a_short_turn_secret_is_refused() -> None:
    """A TURN secret below the minimum length is not accepted."""
    with pytest.raises(ValueError, match="at least 16 bytes"):
        TurnSecret(b"tooshort")
