"""Application configuration and live views for the browser P2P edge."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from mug.client.ice import IceGrant, IceServerConfig
from mug.game.browser_mesh import BrowserMeshSpec, verify_mesh_capture
from mug.game.p2p_capture import CaptureVerifier
from mug.game.p2p_room_types import RoomEffect, RoomLimits
from mug.kernel import Digest, PrincipalRef
from mug.kernel.refs import StudyVersionRef


def _default_study_version() -> StudyVersionRef:
    return StudyVersionRef(
        study_id="study_019b6000-0000-7000-8000-0000000000c0",
        study_version_id="studyver_019b6000-0000-7000-8000-0000000000c1",
        version_number=1,
        manifest_digest=Digest(algorithm="sha-256", hex="0" * 64),
    )


@dataclass(frozen=True)
class BrowserP2PConfig:
    """Configure one browser-executed full-mesh game mount.

    A study normally supplies ``game``, the browser-executed mesh channel. The
    mount then ships that manifest to every browser and checks the trajectory the
    peers report against it, so nothing else has to be configured. ``verify_capture``
    is the escape hatch for a study that reports its own payload shape; naming
    neither is refused, because an unchecked capture is not a capture.
    """

    channel_key: str
    size: int
    game: BrowserMeshSpec | None = None
    verify_capture: CaptureVerifier | None = None
    seed: int = 0
    limits: RoomLimits = field(default_factory=RoomLimits)
    study_version: StudyVersionRef = field(default_factory=_default_study_version)
    ice: IceServerConfig = field(default_factory=IceServerConfig)
    ice_endpoint: str = "/api/p2p/ice"

    def __post_init__(self) -> None:
        if self.game is None and self.verify_capture is None:
            raise ValueError("a browser P2P mount needs a game or a capture verifier")
        if not 2 <= self.size <= 16:
            raise ValueError("a browser P2P game needs from 2 to 16 peers")
        if self.seed < 0:
            raise ValueError("a browser P2P seed must be nonnegative")
        if not self.ice_endpoint.startswith("/") or "?" in self.ice_endpoint:
            raise ValueError("the ICE endpoint must be a same-origin path")
        limits = self.limits
        if not 1 <= limits.validation_timeout_seconds <= 60:
            raise ValueError("the validation timeout must be from 1 to 60 seconds")
        if limits.capture_timeout_seconds <= 0:
            raise ValueError("the capture timeout must be positive")
        if limits.max_signal_bytes > 65_536:
            raise ValueError("the signal limit exceeds the API-09 wire bound")
        if limits.max_capture_bytes > 1_048_576:
            raise ValueError("the capture limit exceeds the API-09 wire bound")

    @property
    def capture_verifier(self) -> CaptureVerifier:
        """Return the verifier the room checks a submitted capture against."""
        if self.verify_capture is not None:
            return self.verify_capture
        return verify_mesh_capture


@dataclass(frozen=True)
class P2PConnectionIdentity:
    """Bind one authenticated socket to its browser, enrollment, and visit."""

    browser_session_handle: str
    enrollment_id: str
    visit_id: str
    principal: PrincipalRef


@dataclass(frozen=True)
class PeerAssignment:
    """Give one local peer a remote peer handle and deterministic offer role."""

    peer_handle: str
    role: Literal["offerer", "answerer"]


@dataclass(frozen=True)
class RoomEnd:
    """Tell one room member whether to finish, re-pool, or leave the flow."""

    kind: Literal["finish", "abort"]
    disposition: Literal["repool", "resume_flow", "terminal"]
    capture_receipt: str | None = None


@dataclass(frozen=True)
class RoomAssignment:
    """The internal bootstrap view for one authenticated room member."""

    room_handle: str
    local_peer_handle: str
    capture_owner_handle: str
    negotiation_generation: int
    peers: tuple[PeerAssignment, ...]
    validation_timeout_ms: int
    ice_grant: IceGrant
    ice_endpoint: str
    ended: asyncio.Future[RoomEnd]


def browser_session_handle(visit_id: str) -> str:
    """Derive one browser's stable public session handle from its visit.

    The coordinator keys a browser session by this handle: a reconnection of the
    same visit replaces the prior connection rather than joining the room twice.
    The value is derived, not minted, so the websocket path and the ICE endpoint
    reach the same handle for one participant with no shared table.
    """
    body = visit_id.split("_", 1)[-1].replace("-", "")
    return "handle_" + body[:21].ljust(21, "0") + "A"


class P2PEdgeError(RuntimeError):
    """A participant-safe refusal from the live P2P coordinator."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


P2PSend = Callable[[RoomEffect], Awaitable[None]]


__all__ = [
    "BrowserP2PConfig",
    "P2PConnectionIdentity",
    "P2PEdgeError",
    "P2PSend",
    "PeerAssignment",
    "RoomAssignment",
    "RoomEnd",
    "browser_session_handle",
]
