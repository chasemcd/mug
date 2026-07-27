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
    TraceContext,
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
        secret: bytes | None = None,
    ) -> None:
        self._clock = clock
        self._entropy = entropy
        # The secret seeds the content-addressed identifier derivation, so a derived
        # identifier is deterministic across a retry yet unguessable to the client.
        #
        # It defaults to a fresh per-process secret, which is right for one process
        # and wrong for several: two processes with different secrets derive
        # different command identifiers for the same retried envelope, and the store
        # then sees one idempotency key with two contents and refuses the retry
        # (``command.idempotency_conflict``) instead of replaying it. A deployment
        # that runs more than one process passes the same secret to each (see
        # ``MUG_GATEWAY_SECRET``), which is what makes a retry idempotent whichever
        # process it lands on.
        self._secret = secret if secret is not None else entropy(32)
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

    def new_handle(self) -> str:
        """Mint one unguessable public handle for a transient resource."""
        raw = self._entropy(16)
        return "handle_" + base64.urlsafe_b64encode(raw).decode().rstrip("=")

    # --- derived identity ---------------------------------------------------
    #
    # A minted identifier is fresh entropy, which is right for a new occurrence and
    # wrong for one a participant must meet twice. A participant who refreshes the
    # page reaches the same activity again, and it must be the same activity: the
    # same assignment, the same options, the same order. Deriving those identifiers
    # from what does not change -- the flow and the activity -- gives that for free,
    # with no lookup table and no session memory to lose. The server secret seeds
    # every derivation, so the values stay unguessable from the wire.

    def derived_id(self, kind: str, seed: str) -> str:
        """Return the one ``<kind>_<uuidv7>`` identifier this kind and seed give.

        Two calls with the same kind and seed always return the same identifier, and
        a different kind or seed gives an unrelated one.
        """
        return f"{kind}_{self._derive_uuid7(kind.encode(), seed)}"

    def derived_handle(self, seed: str) -> str:
        """Return the one unguessable public handle this seed gives."""
        return self._derive_handle(seed)

    def derived_seed(self, role: str, seed: str) -> bytes:
        """Return 32 reproducible bytes for a role and a seed.

        A blinded, randomized presentation commits to its seed by digest, so the
        deployment can later reveal the seed and prove the order it showed. The seed
        must therefore outlive the moment it is used, and stay unpredictable to the
        participant who is being randomized: deriving it from the server secret gives
        both, so nothing has to store it.
        """
        return hashlib.sha256(self._secret + role.encode() + seed.encode()).digest()

    def new_trace(self, *, sampled: bool = True) -> TraceContext:
        """Mint one W3C trace context, for a request that arrived without one.

        A trace identifies a request across the edge, a study's proxy, and the
        browser, so it is entropy, and entropy is minted here. It is never persisted:
        no canonical event carries a trace, and a debugging aid does not change a
        frozen contract.
        """
        raw = bytearray(self._entropy(24))
        # An all-zero trace id or parent id is not a trace context. Setting the top
        # bit of each rules that out for any entropy source, at the cost of one bit,
        # so minting a trace can never raise inside a request.
        raw[0] |= 0x80
        raw[16] |= 0x80
        return TraceContext(
            traceparent=(
                f"00-{raw[:16].hex()}-{raw[16:24].hex()}-{'01' if sampled else '00'}"
            )
        )

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
        caused_by: str | None = None,
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

        ``caused_by`` names the event this command answers, for a command that
        answers one: a model reply names the message that prompted it. It is what
        joins two streams that are each ordered on their own, so an analysis can
        follow a cause across them without one order being imposed over both. It
        does not enter the command's identity, because what a command answers does
        not change what the command is, and a retry must stay idempotent.
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
            causation_event_id=caused_by,
        )
