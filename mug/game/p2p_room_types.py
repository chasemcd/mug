"""Transport-neutral bindings and effects for an authenticated P2P room."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from mug.game.p2p_capture import CaptureVerifier
from mug.interactions.types import ConnectionLease, P2PMeshMembership
from mug.kernel import Digest

RoomState = Literal[
    "formed", "signalling", "validating", "ready", "running", "complete", "abort"
]
SignalKind = Literal["offer", "answer", "candidate", "end_of_candidates"]
AbortReason = Literal[
    "peer_disconnected",
    "negotiation_timeout",
    "validation_failed",
    "stale_connection",
    "room_replaced",
    "capture_timeout",
    "capture_conflict",
    "server_unavailable",
]
AbortDisposition = Literal["repool", "resume_flow", "terminal"]


# The deadline a room uses when nothing named a game to derive one from. A mount
# that runs a browser mesh always names one; a mount that verifies a study's own
# capture payload does not, and the platform has no episode length to read.
DEFAULT_CAPTURE_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class RoomLimits:
    """The bounded resources one live room permits.

    ``capture_timeout_seconds`` is how long the room waits, from the start
    barrier, for the trajectory the peers agreed on. It is unset by default
    because the answer belongs to the game the room plays and these limits are
    transport-neutral: the mount derives it from its own game specification
    (``BrowserP2PConfig.room_limits``). A number set here is the author's own and
    is used as written.
    """

    validation_timeout_seconds: float = 15.0
    max_signal_bytes: int = 65_536
    max_signals_per_peer: int = 256
    max_signals_per_window: int = 32
    signal_window_seconds: float = 1.0
    max_capture_bytes: int = 1_048_576
    max_frame_count: int = 10_000_000
    capture_timeout_seconds: float | None = None

    def capture_deadline(self) -> float:
        """Return the capture deadline, resolved for a room that is about to run."""
        if self.capture_timeout_seconds is None:
            return DEFAULT_CAPTURE_TIMEOUT_SECONDS
        return self.capture_timeout_seconds


@dataclass(frozen=True)
class BoundPeer:
    """One opaque peer handle bound to server-authoritative identity and lease."""

    peer_handle: str
    connection_id: str
    enrollment_id: str
    visit_id: str
    seat_key: str
    actor_id: str
    lease: ConnectionLease


@dataclass(frozen=True)
class SignalDelivery:
    """One server-stamped opaque signal to deliver to a bound peer."""

    connection_id: str
    room_handle: str
    source_peer_handle: str
    target_peer_handle: str
    negotiation_generation: int
    signal_kind: SignalKind
    payload_json: str | None


@dataclass(frozen=True)
class MeshStart:
    """The one all-ready start broadcast for a room."""

    connection_ids: tuple[str, ...]
    room_handle: str
    negotiation_generation: int
    seed: int
    start_sequence: int
    capture_owner_handle: str


@dataclass(frozen=True)
class MeshAbort:
    """A terminal room abort broadcast."""

    connection_ids: tuple[str, ...]
    room_handle: str
    negotiation_generation: int
    reason: AbortReason
    disposition: AbortDisposition


@dataclass(frozen=True)
class MeshFinish:
    """The one reconciled completion broadcast."""

    connection_ids: tuple[str, ...]
    room_handle: str
    negotiation_generation: int
    trajectory_digest: Digest
    frame_count: int
    capture_receipt: str


@dataclass(frozen=True)
class CapturePersistenceFence:
    """Bind one asynchronous capture write to its still-live room attempt."""

    room_handle: str
    negotiation_generation: int
    payload_digest: Digest


RoomEffect = SignalDelivery | MeshStart | MeshAbort | MeshFinish
LeaseCheck = Callable[[ConnectionLease], bool]
LeaseFence = Callable[[ConnectionLease], ConnectionLease]


@dataclass(frozen=True)
class RoomBinding:
    """The immutable authority bindings for one formed room."""

    room_handle: str
    interaction_id: str
    membership: P2PMeshMembership
    members: tuple[BoundPeer, ...]
    negotiation_generation: int
    seed: int


@dataclass(frozen=True)
class RoomRuntime:
    """The limits, clocks, and lease authority used by a live room."""

    limits: RoomLimits
    monotonic: Callable[[], float]
    utc_now: Callable[[], datetime]
    lease_is_current: LeaseCheck
    fence_lease: LeaseFence
    verify_capture: CaptureVerifier


__all__ = [
    "DEFAULT_CAPTURE_TIMEOUT_SECONDS",
    "AbortDisposition",
    "AbortReason",
    "BoundPeer",
    "CapturePersistenceFence",
    "MeshAbort",
    "MeshFinish",
    "MeshStart",
    "RoomBinding",
    "RoomEffect",
    "RoomLimits",
    "RoomRuntime",
    "RoomState",
    "SignalDelivery",
    "SignalKind",
]
