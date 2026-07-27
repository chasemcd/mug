"""Reconcile bounded capture claims from one frozen peer set."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from mug.kernel import Digest

CaptureStatus = Literal["accepted", "duplicate", "pending", "ready", "conflict"]


class P2PCaptureError(RuntimeError):
    """A safe invalid capture submission."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


@dataclass(frozen=True)
class CaptureLimits:
    """The payload and trajectory limits for one room."""

    max_payload_bytes: int
    max_frame_count: int


@dataclass(frozen=True)
class CaptureOutcome:
    """The reconciled trajectory and its opaque durable receipt handle."""

    trajectory_digest: Digest
    frame_count: int
    capture_receipt: str


@dataclass(frozen=True)
class VerifiedCapture:
    """The trajectory identity derived from a validated capture payload."""

    trajectory_digest: Digest
    frame_count: int


# The study supplies the verifier, so the return value is checked at runtime.
CaptureVerifier = Callable[[str], object]


@dataclass(frozen=True)
class _Claim:
    trajectory_digest: Digest
    frame_count: int


@dataclass(frozen=True)
class _Submission:
    claim: _Claim
    payload_json: str
    payload_digest: Digest


class CaptureReconciler:
    """Own the completion claims and designated-owner capture for one room."""

    def __init__(
        self,
        *,
        peer_handles: tuple[str, ...],
        owner_handle: str,
        limits: CaptureLimits,
        verify_payload: CaptureVerifier,
    ) -> None:
        if len(peer_handles) < 2 or len(set(peer_handles)) != len(peer_handles):
            raise ValueError("capture reconciliation needs unique peer handles")
        if owner_handle not in peer_handles:
            raise ValueError("the capture owner must be a room peer")
        self._peers = frozenset(peer_handles)
        self._owner = owner_handle
        self._limits = limits
        self._verify_payload = verify_payload
        self._claims: dict[str, _Claim] = {}
        self._submission: _Submission | None = None
        self._receipt: str | None = None
        self._finished = False

    def report(
        self, peer_handle: str, trajectory_digest: Digest, frame_count: int
    ) -> CaptureStatus:
        """Record one completion claim and report its reconciliation status."""
        self._require_peer(peer_handle)
        if frame_count < 0 or frame_count > self._limits.max_frame_count:
            raise P2PCaptureError(
                "schema.validation_failed", "the frame count is invalid"
            )
        claim = _Claim(trajectory_digest, frame_count)
        prior = self._claims.get(peer_handle)
        if prior is not None:
            return "duplicate" if prior == claim else "conflict"
        if self._claims and claim not in self._claims.values():
            return "conflict"
        if self._submission is not None and claim != self._submission.claim:
            return "conflict"
        self._claims[peer_handle] = claim
        return "ready" if self._can_finish() else "pending"

    def submit(
        self,
        *,
        peer_handle: str,
        trajectory_digest: Digest,
        frame_count: int,
        payload_json: str,
        payload_digest: Digest,
    ) -> CaptureStatus:
        """Validate and accept the designated owner's bounded payload once."""
        self._require_peer(peer_handle)
        if peer_handle != self._owner:
            raise P2PCaptureError("auth.forbidden", "only the capture owner may submit")
        if frame_count < 0 or frame_count > self._limits.max_frame_count:
            raise P2PCaptureError(
                "schema.validation_failed", "the frame count is invalid"
            )
        if len(payload_json.encode("utf-8")) > self._limits.max_payload_bytes:
            raise P2PCaptureError(
                "runtime.backpressure", "the capture payload is too large"
            )
        try:
            json.loads(
                payload_json,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (RecursionError, ValueError) as error:
            raise P2PCaptureError(
                "schema.validation_failed", "the capture payload is not valid json"
            ) from error
        raw_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        if raw_digest != payload_digest.hex:
            raise P2PCaptureError(
                "artifact.integrity_failed", "the capture payload digest does not match"
            )
        try:
            verified = self._verify_payload(payload_json)
        except Exception as error:
            raise P2PCaptureError(
                "schema.validation_failed", "the capture payload did not validate"
            ) from error
        if not isinstance(verified, VerifiedCapture):
            raise P2PCaptureError(
                "schema.validation_failed", "the capture verifier returned no claim"
            )
        if (
            verified.trajectory_digest != trajectory_digest
            or verified.frame_count != frame_count
        ):
            raise P2PCaptureError(
                "artifact.integrity_failed",
                "the capture payload does not match its trajectory claim",
            )
        submission = _Submission(
            _Claim(trajectory_digest, frame_count), payload_json, payload_digest
        )
        if self._submission is not None:
            return "duplicate" if self._submission == submission else "conflict"
        if self._claims and submission.claim not in self._claims.values():
            return "conflict"
        self._submission = submission
        return "accepted"

    def payload(self) -> str | None:
        """Return the accepted payload for the imperative shell to persist."""
        return self._submission.payload_json if self._submission is not None else None

    def payload_digest(self) -> Digest | None:
        """Return the accepted raw-byte digest for persistence fencing."""
        return self._submission.payload_digest if self._submission is not None else None

    def set_receipt(self, receipt: str) -> CaptureOutcome | None:
        """Fix the persisted receipt handle and return an outcome when reconciled."""
        if self._submission is None:
            raise P2PCaptureError(
                "command.state_conflict", "no capture payload has been accepted"
            )
        if self._receipt is not None and self._receipt != receipt:
            raise P2PCaptureError(
                "command.state_conflict", "the capture receipt is already fixed"
            )
        self._receipt = receipt
        return self.finish()

    def finish(self) -> CaptureOutcome | None:
        """Return the one final outcome after all peers and persistence agree."""
        if self._finished or not self._can_finish() or self._receipt is None:
            return None
        assert self._submission is not None
        self._finished = True
        return CaptureOutcome(
            trajectory_digest=self._submission.claim.trajectory_digest,
            frame_count=self._submission.claim.frame_count,
            capture_receipt=self._receipt,
        )

    def _can_finish(self) -> bool:
        return self._submission is not None and frozenset(self._claims) == self._peers

    def _require_peer(self, peer_handle: str) -> None:
        if peer_handle not in self._peers:
            raise P2PCaptureError("auth.forbidden", "the capture peer is not a member")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate JSON object keys instead of choosing a hidden winner."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    """Reject JavaScript numeric constants that RFC 8259 does not permit."""
    raise ValueError(f"invalid JSON constant {value}")


__all__ = [
    "CaptureLimits",
    "CaptureOutcome",
    "CaptureReconciler",
    "CaptureStatus",
    "CaptureVerifier",
    "P2PCaptureError",
    "VerifiedCapture",
]
