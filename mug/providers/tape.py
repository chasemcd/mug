"""The durable model-output tape: keep a verbatim output for exact replay.

The provider records a model output by *digest* only -- the raw output is returned
to the caller and never persisted, a deliberate privacy boundary (see
``mug.providers.runtime``). A digest is enough to *verify* an output, but not to
*replay* one: a retry after a crash, or a re-run for analysis, finds the recorded
digest but not the text. So a decision that reasons over its own prior model output
-- a carried thought -- cannot re-derive it on replay, and falls back instead of
reproducing the reply.

This tape closes that gap without weakening the boundary. A study that wants
replay-exact decisions injects an ``OutputTape``; the provider then persists each
completed output, content-addressed by the digest the response already records, and
rehydrates it on a replay. The tape is opt-in, so the default provider still
persists nothing. Because the key is the output's own digest, the tape is
content-addressed: an output stores once, and a replay reads it back by the digest
the recorded ``ProviderResponse`` carries.

``InMemoryOutputTape`` is the reference implementation, and it makes replay exact
within one process (a re-run or an idempotent retry that finds the recorded head).
A cross-process, crash-durable tape is a drop-in behind the ``OutputTape`` seam -- a
store-backed implementation keyed the same way -- so the mechanism here does not
change when the durable backend lands.
"""

from __future__ import annotations

from typing import Any, Protocol

from mug.kernel import Digest

# The raw model output is study-shaped, so the seam types it as ``Any`` (P0
# duck-typing); it must be JSON-serializable, as the digest already requires.
Output = Any


class OutputTape(Protocol):
    """A content-addressed store of verbatim model outputs, keyed by digest.

    ``put`` records one completed output under its digest; ``get`` reads it back, or
    returns ``None`` when the tape holds no output for that digest (so a replay with
    a partial tape degrades to the recorded-by-digest-only behavior rather than
    failing). Both are async, so a store-backed tape can await its backend.
    """

    async def put(self, digest: Digest, output: Output) -> None: ...
    async def get(self, digest: Digest) -> Output | None: ...


class InMemoryOutputTape:
    """An in-process ``OutputTape`` for tests and same-process replay.

    It keys each output by its digest hex, so a re-run in the same process reads the
    exact recorded output back. This covers the in-process replay and the
    idempotent-retry cases; a cross-process, crash-durable tape is a store-backed
    drop-in behind the same seam.
    """

    def __init__(self) -> None:
        self._outputs: dict[str, Output] = {}

    async def put(self, digest: Digest, output: Output) -> None:
        """Record one output under its digest hex (a later put is idempotent)."""
        self._outputs[digest.hex] = output

    async def get(self, digest: Digest) -> Output | None:
        """Return the recorded output for a digest, or None when the tape has none."""
        return self._outputs.get(digest.hex)


__all__ = ["InMemoryOutputTape", "Output", "OutputTape"]
