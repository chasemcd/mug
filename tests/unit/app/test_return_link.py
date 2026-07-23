"""The return link signs its claims, so only a server-issued token verifies.

``sign_return_link`` builds a token from the claims and a signing key;
``verify_return_link`` returns the claims only when the token is well-formed and
its signature matches the same key. A tampered token, a wrong key, or a malformed
string returns None, so a stolen or guessed flow id can not stand in for a token
the server issued. The expiry is not checked here -- the caller owns the clock.
"""

from __future__ import annotations

from mug.returns import ReturnClaims, sign_return_link, verify_return_link

_KEY = b"a-server-signing-key-of-some-length"
_CLAIMS = ReturnClaims(
    flow_id="visitplan_019b6000-0000-7000-8000-00000000000a",
    expires_at="2026-07-22T00:00:00.000000Z",
)


def test_a_signed_token_verifies_and_returns_its_claims() -> None:
    """A token signed with a key verifies with the same key to the same claims."""
    token = sign_return_link(_KEY, _CLAIMS)
    verified = verify_return_link(_KEY, token)

    assert verified == _CLAIMS


def test_the_same_claims_always_sign_to_the_same_token() -> None:
    """Signing is deterministic, so a resume can return the token it received."""
    assert sign_return_link(_KEY, _CLAIMS) == sign_return_link(_KEY, _CLAIMS)


def test_a_token_signed_with_another_key_does_not_verify() -> None:
    """A token minted under a different key does not verify: no cross-key resume."""
    token = sign_return_link(b"another-key-entirely", _CLAIMS)

    assert verify_return_link(_KEY, token) is None


def test_a_tampered_claim_breaks_the_signature() -> None:
    """Altering the claims part of the token breaks the mac, so it fails to verify."""
    token = sign_return_link(_KEY, _CLAIMS)
    message, _, mac = token.partition(".")
    tampered = message[:-1] + ("A" if message[-1] != "A" else "B") + "." + mac

    assert verify_return_link(_KEY, tampered) is None


def test_a_tampered_signature_does_not_verify() -> None:
    """Altering the signature part of the token makes the mac compare fail."""
    token = sign_return_link(_KEY, _CLAIMS)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    assert verify_return_link(_KEY, tampered) is None


def test_a_malformed_token_returns_none() -> None:
    """A token with no signature, no claims, or extra parts is not well-formed."""
    assert verify_return_link(_KEY, "no-separator-here") is None
    assert verify_return_link(_KEY, "") is None
    assert verify_return_link(_KEY, ".") is None
    assert verify_return_link(_KEY, "one.two.three") is None
