"""The gateway mints a trusted command context from an untrusted envelope.

A verified gateway receives a ``WireCommandEnvelope`` and the principal that auth
resolved, then derives the runtime ``CommandContext`` the handlers need. It mints
the command, receipt, error, and event identifiers, reads the wall clock, and
assigns the producer position from its own epoch. The envelope names the target
aggregate and the client-controlled idempotency key; the gateway never trusts a
principal from the wire.

The identifier entropy and the wall clock are the only impurity in the platform.
Both are injected, so a test pins them and a mint is deterministic.

One command's identifiers are content-addressed: the gateway derives them from
the client idempotency key and the payload, so an identical retry re-mints the
identical identifiers and the store recognizes the replay (shared-kernel
idempotency, NS-10). A per-gateway server secret seeds the derivation, so the
public ticket handle stays unguessable to the client.
"""

from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Callable
from datetime import datetime, timezone

from mug.kernel import (
    DataHandlingRef,
    Digest,
    PrincipalRef,
    ProducerPosition,
    WireCommandEnvelope,
    compute_digest,
)
from mug.runtime import CommandContext

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _wall_clock() -> datetime:
    """Return the current instant in UTC."""
    return datetime.now(timezone.utc)


class Gateway:
    """Mint a trusted command context: the one clock-and-entropy boundary."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _wall_clock,
        entropy: Callable[[int], bytes] = os.urandom,
    ) -> None:
        self._clock = clock
        self._entropy = entropy
        # A per-gateway secret seeds the content-addressed identifier derivation,
        # so a derived handle is deterministic across a retry yet unguessable.
        self._secret = entropy(32)
        self._epoch = self.new_id("prodepoch")
        self._sequence = 0

    @property
    def clock(self) -> Callable[[], datetime]:
        """Return the injected wall clock (a ``datetime`` source).

        The game loop reads a string-form instant, but the agent runtime records a
        ``datetime`` (it formats deadlines itself), so a caller that drives an agent
        episode passes this clock, keeping the one injected time source.
        """
        return self._clock

    # --- minters ------------------------------------------------------------
    def _uuid7(self) -> str:
        """Mint one canonical UUIDv7 from the clock and the entropy source."""
        milliseconds = int(self._clock().timestamp() * 1000) & ((1 << 48) - 1)
        noise = self._entropy(10)
        raw = bytearray(16)
        raw[0:6] = milliseconds.to_bytes(6, "big")
        raw[6] = 0x70 | (noise[0] & 0x0F)
        raw[7] = noise[1]
        raw[8] = 0x80 | (noise[2] & 0x3F)
        raw[9:16] = noise[3:10]
        body = raw.hex()
        return f"{body[0:8]}-{body[8:12]}-{body[12:16]}-{body[16:20]}-{body[20:32]}"

    def new_id(self, prefix: str) -> str:
        """Mint one ``<prefix>_<uuidv7>`` identifier."""
        return f"{prefix}_{self._uuid7()}"

    def _derive_uuid7(self, role: bytes, seed: str) -> str:
        """Derive one deterministic ``<uuidv7>`` body from a role and the seed.

        The digest fills the identifier, and the version and variant nibbles are
        forced, so the result is a UUIDv7-shaped identifier that a given role and
        seed always reproduce.
        """
        digest = hashlib.sha256(self._secret + role + seed.encode()).digest()
        raw = bytearray(digest[:16])
        raw[6] = 0x70 | (raw[6] & 0x0F)
        raw[8] = 0x80 | (raw[8] & 0x3F)
        body = raw.hex()
        return f"{body[0:8]}-{body[8:12]}-{body[12:16]}-{body[16:20]}-{body[20:32]}"

    def _derive_handle(self, seed: str) -> str:
        """Derive one deterministic, unguessable public handle from the seed."""
        raw = hashlib.sha256(self._secret + b"handle" + seed.encode()).digest()[:16]
        return "handle_" + base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def _producer(self, content_digest: Digest) -> ProducerPosition:
        """Advance the epoch sequence and return the next producer position."""
        self._sequence += 1
        return ProducerPosition(
            epoch_id=self._epoch,
            sequence=self._sequence,
            content_digest=content_digest,
        )

    # --- context ------------------------------------------------------------
    def mint(
        self,
        envelope: WireCommandEnvelope,
        *,
        principal: PrincipalRef,
        data_handling: DataHandlingRef,
        issue_handle: bool = False,
        handle: str | None = None,
    ) -> CommandContext:
        """Derive the trusted context for one verified envelope.

        The envelope ``target`` names the aggregate the command addresses: a
        client mints it for a create, or it is the live resource for an update.
        The event stream shares the aggregate identifier body, so an aggregate's
        events always land on one stream. ``issue_handle`` is set for a token
        command, whose ticket handle the gateway mints. ``handle`` supplies a
        handle the caller already derived (a blinded external identity link is
        keyed by its own deterministic handle, not by a gateway-minted one); it
        takes precedence over ``issue_handle``.
        """
        aggregate_id = envelope.target.id
        content_digest = compute_digest(envelope.payload.data)
        # The command's identity is content-addressed by the client idempotency
        # key and the payload, so an identical retry re-mints identical
        # identifiers and the store replays it rather than conflicting (NS-10).
        seed = f"{envelope.idempotency_key}:{content_digest.hex}"
        if handle is not None:
            public_handle = handle
        elif issue_handle:
            public_handle = self._derive_handle(seed)
        else:
            public_handle = None
        return CommandContext(
            command_id="command_" + self._derive_uuid7(b"command", seed),
            receipt_id="receipt_" + self._derive_uuid7(b"receipt", seed),
            error_id="error_" + self._derive_uuid7(b"error", seed),
            request_id=envelope.request_id,
            idempotency_key=envelope.idempotency_key,
            event_id="event_" + self._derive_uuid7(b"event", seed),
            stream_id="stream_" + aggregate_id.split("_", 1)[1],
            producer=self._producer(content_digest),
            aggregate_id=aggregate_id,
            public_handle=public_handle,
            principal=principal,
            recorded_at=self._clock().strftime(_INSTANT),
            event_data_handling=data_handling,
        )
