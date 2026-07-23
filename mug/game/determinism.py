"""The shared state-hash hook for browser determinism (API-16 ``state_hash``).

A browser run steps the environment in the participant browser, and the client is
the writer of the episode. So the server cannot trust a client-reported state
digest unless it can reproduce it. This module supplies the one hook that makes
that reproduction exact: a deterministic, dependency-free hash of a json-able
value that both sides compute the same way.

The client runs the hook in Pyodide (real CPython and numpy); the server runs it
in CPython when it re-executes the run to verify it. The hook uses only the
standard library, so it needs no package install and drifts on neither side. The
server ships its exact source to the client in the manifest, and one test checks
the shipped source against the hook here, so the two never diverge.

The hook is deliberately not the RFC 8785 canonicalizer the rest of the system
uses for record digests: that canonicalizer is not available in the browser
without a package install, and the state hash only needs both sides to agree with
each other, not with the wider digest scheme.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from mug.kernel import Digest, compute_digest

# The exact Python source of the hook the client runs in Pyodide. The server
# ships this in the client manifest; it defines ``_mug_state_hash_hex``. A unit
# test checks that this source computes the same hex as ``_state_hash_hex`` below,
# so the shipped hook and the server hook can never drift.
_HOOK_SOURCE = (
    "import hashlib as _mug_hashlib\n"
    "import json as _mug_json\n"
    "\n"
    "\n"
    "def _mug_state_hash_hex(value):\n"
    '    payload = _mug_json.dumps(value, separators=(",", ":"), sort_keys=True)\n'
    '    return _mug_hashlib.sha256(payload.encode("utf-8")).hexdigest()\n'
)


def _state_hash_hex(value: Any) -> str:
    """Return the hook's hex digest of a json-able value (the server copy)."""
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def state_hash(value: Any) -> Digest:
    """Return the structured state hash of a json-able value."""
    return Digest(algorithm="sha-256", hex=_state_hash_hex(value))


def state_hash_source() -> str:
    """Return the Python source of the hook the client runs in the browser."""
    return _HOOK_SOURCE


def state_hash_chain(frame_hexes: list[str]) -> Digest:
    """Return one digest that binds the ordered per-frame state hashes.

    The chain digest stands for the whole verified trajectory: a run whose frames
    each verify against the re-execution shares this one digest with its source.
    """
    return compute_digest(frame_hexes)


__all__ = ["state_hash", "state_hash_chain", "state_hash_source"]
