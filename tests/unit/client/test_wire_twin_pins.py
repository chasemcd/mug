"""The TypeScript twin's pinned contract digests match the Python contract.

The participant client is written twice: once in JavaScript and once in TypeScript
against a kernel twin. The twin refuses a peer-to-peer frame whose schema reference
does not name the api-09 bundle it was built for, which is right -- a peer must be
able to refuse a frame from a client built against a different contract.

It carries that digest as a **written constant**, because a peer has to be able to
refuse before it trusts anything. So the constant goes stale the moment the bundle
moves, and a stale one refuses **every** P2P frame: a working server, a working peer,
and a mesh that never forms.

That is exactly what happened. A contract change moved the api-09 bundle, 3132 Python
tests and 907 architecture tests passed, and every peer-to-peer browser run was broken
-- found only by running a real two-browser mesh, which takes three minutes and is not
in the fast gate. This test costs milliseconds and would have said so at once.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mug.client.types import client_schema

# Where the twin writes the digests it refuses frames against.
_WIRE_FIELDS = (
    Path(__file__).resolve().parents[3] / "ts" / "src" / "client" / "p2pWireFields.ts"
)

# The compiled client the browser is actually served. A source file the build has not
# been run over is a source file the participant never receives.
_BUILT = (
    Path(__file__).resolve().parents[3]
    / "ts"
    / "dist-web"
    / "client"
    / "p2pWireFields.js"
)

_PINNED = re.compile(r"P2P_CLIENT_BUNDLE_DIGEST\s*=\s*\n?\s*'([0-9a-f]{64})'")


def _pinned_in(path: Path) -> str:
    """Return the api-09 bundle digest one file pins."""
    found = _PINNED.search(path.read_text(encoding="utf-8"))
    assert found is not None, f"{path.name} pins no api-09 bundle digest"
    return found.group(1)


def test_the_typescript_twin_pins_the_api09_bundle_it_is_built_against() -> None:
    """The written constant is the digest of the schema bundle in this tree."""
    assert _WIRE_FIELDS.is_file(), "the TypeScript client is not in this checkout"

    assert _pinned_in(_WIRE_FIELDS) == client_schema().bundle_digest, (
        "ts/src/client/p2pWireFields.ts pins an api-09 bundle digest that is not the "
        "one in this tree. Every peer-to-peer frame will be refused with 'schema must "
        "identify ...' and no mesh will form. Restamp the constant when the bundle "
        "moves."
    )


@pytest.mark.skipif(not _BUILT.is_file(), reason="ts/dist-web is not built")
def test_the_client_the_browser_is_served_pins_the_same_bundle() -> None:
    """The built client agrees with its own source.

    The browser is served ``dist-web``, not ``src``. A corrected source that was never
    rebuilt is a correction no participant receives, and the failure looks exactly like
    the one the correction was for.
    """
    assert _pinned_in(_BUILT) == _pinned_in(_WIRE_FIELDS), (
        "ts/dist-web is stale: it pins a different api-09 bundle from its own source. "
        "Run `npm run build:web` in ts/."
    )
