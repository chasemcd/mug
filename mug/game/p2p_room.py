"""Coordinate one authenticated browser peer-to-peer room.

The room owns only live state. It receives already-authenticated connection
bindings and a frozen API-06 mesh, validates every effect against those bindings,
and returns transport-neutral effects for the server edge to deliver.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from datetime import datetime, timezone

from mug.game.p2p_capture import (
    CaptureLimits,
    CaptureOutcome,
    CaptureReconciler,
    P2PCaptureError,
)
from mug.game.p2p_room_types import (
    AbortDisposition,
    AbortReason,
    BoundPeer,
    CapturePersistenceFence,
    MeshAbort,
    MeshFinish,
    MeshStart,
    RoomBinding,
    RoomEffect,
    RoomLimits,
    RoomRuntime,
    RoomState,
    SignalDelivery,
    SignalKind,
)
from mug.interactions.types import P2PMeshMembership
from mug.kernel import Digest


class P2PRoomError(RuntimeError):
    """A safe failure from the live room boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message


class P2PRoom:
    """Own one formed room's signalling, readiness, and capture state."""

    def __init__(self, binding: RoomBinding, runtime: RoomRuntime) -> None:
        self._validate_shape(
            binding.interaction_id, binding.membership, binding.members
        )
        self.room_handle = binding.room_handle
        self.interaction_id = binding.interaction_id
        self.membership = binding.membership
        self.negotiation_generation = binding.negotiation_generation
        self.seed = binding.seed
        self.limits = runtime.limits
        self._monotonic = runtime.monotonic
        self._utc_now = runtime.utc_now
        self._lease_is_current = runtime.lease_is_current
        self._fence_lease = runtime.fence_lease
        self._members = {member.peer_handle: member for member in binding.members}
        self._by_connection = {
            member.connection_id: member.peer_handle for member in binding.members
        }
        self._capture_owner = min(
            binding.members, key=lambda item: item.actor_id
        ).peer_handle
        self._capture = CaptureReconciler(
            peer_handles=tuple(self._members),
            owner_handle=self._capture_owner,
            limits=CaptureLimits(
                max_payload_bytes=runtime.limits.max_capture_bytes,
                max_frame_count=runtime.limits.max_frame_count,
            ),
            verify_payload=runtime.verify_capture,
        )
        self._deadline = runtime.monotonic() + runtime.limits.validation_timeout_seconds
        self._state: RoomState = "formed"
        self._ready: dict[str, frozenset[str]] = {}
        self._signal_count: dict[str, int] = dict.fromkeys(self._members, 0)
        self._signal_times: dict[str, deque[float]] = {
            handle: deque() for handle in self._members
        }
        self._signal_requests: dict[
            tuple[str, str], tuple[str, int, SignalKind, str | None]
        ] = {}
        self._start_emitted = False
        self._fenced = False

    @property
    def state(self) -> RoomState:
        """Return the room lifecycle state."""
        return self._state

    @property
    def capture_owner_handle(self) -> str:
        """Return the only peer handle allowed to submit the capture payload."""
        return self._capture_owner

    @property
    def peer_handles(self) -> tuple[str, ...]:
        """Return the opaque peer handles in stable actor order."""
        return tuple(
            member.peer_handle
            for member in sorted(self._members.values(), key=lambda item: item.actor_id)
        )

    @property
    def deadline(self) -> float:
        """Return the authority-local validation deadline."""
        return self._deadline

    def members(self) -> tuple[BoundPeer, ...]:
        """Return the room's bound members, for the server-side handle map."""
        return tuple(self._members.values())

    def member_for_connection(self, connection_id: str) -> BoundPeer | None:
        """Return the current bound member for a connection."""
        handle = self._by_connection.get(connection_id)
        return self._members.get(handle) if handle is not None else None

    def begin_signalling(self) -> None:
        """Move a newly formed room into signalling."""
        if self._state != "formed":
            raise P2PRoomError("command.state_conflict", "the room already started")
        self._state = "signalling"

    def relay_signal(
        self,
        *,
        connection_id: str,
        request_id: str,
        target_peer_handle: str,
        negotiation_generation: int,
        signal_kind: SignalKind,
        payload_json: str | None,
    ) -> SignalDelivery | MeshAbort | None:
        """Validate and relay one opaque signal, stamping its source server-side."""
        source = self._authorize(connection_id, negotiation_generation)
        if self._state not in ("signalling", "validating"):
            raise P2PRoomError("command.state_conflict", "the room is not signalling")
        target = self._members.get(target_peer_handle)
        if target is None or target.peer_handle == source.peer_handle:
            raise P2PRoomError(
                "p2p.unknown_target", "the signal target is not permitted"
            )
        if not self._is_current(target):
            return self._stale_abort()
        self._check_signal_attempt(source.peer_handle, payload_json)
        key = (source.peer_handle, request_id)
        fingerprint = (
            target_peer_handle,
            negotiation_generation,
            signal_kind,
            payload_json,
        )
        prior = self._signal_requests.get(key)
        if prior is not None:
            if prior != fingerprint:
                raise P2PRoomError(
                    "command.idempotency_conflict",
                    "the signal request changed during retry",
                )
            return None
        self._check_new_signal(source.peer_handle)
        self._signal_requests[key] = fingerprint
        return SignalDelivery(
            connection_id=target.connection_id,
            room_handle=self.room_handle,
            source_peer_handle=source.peer_handle,
            target_peer_handle=target.peer_handle,
            negotiation_generation=self.negotiation_generation,
            signal_kind=signal_kind,
            payload_json=payload_json,
        )

    def mark_ready(
        self,
        *,
        connection_id: str,
        negotiation_generation: int,
        validated_peer_handles: Sequence[str],
    ) -> MeshStart | MeshAbort | None:
        """Record one peer's complete validation and start once all peers are ready."""
        member = self._authorize(connection_id, negotiation_generation)
        if self._state == "running":
            return None
        if self._state not in ("signalling", "validating"):
            raise P2PRoomError("command.state_conflict", "the room cannot become ready")
        expected = frozenset(self._members) - {member.peer_handle}
        reported = frozenset(validated_peer_handles)
        if len(reported) != len(validated_peer_handles) or reported != expected:
            raise P2PRoomError(
                "schema.validation_failed", "the peer validation set is incomplete"
            )
        prior = self._ready.get(member.peer_handle)
        if prior is not None:
            if prior != reported:
                raise P2PRoomError(
                    "command.state_conflict", "the peer changed its ready report"
                )
            return None
        self._ready[member.peer_handle] = reported
        self._state = "validating"
        if len(self._ready) != len(self._members) or self._start_emitted:
            return None
        if not self._all_current():
            return self._stale_abort()
        self._state = "ready"
        self._start_emitted = True
        effect = MeshStart(
            connection_ids=self._connection_ids(),
            room_handle=self.room_handle,
            negotiation_generation=self.negotiation_generation,
            seed=self.seed,
            start_sequence=1,
            capture_owner_handle=self._capture_owner,
        )
        self._state = "running"
        self._deadline = self._monotonic() + self.limits.capture_deadline()
        return effect

    def report_complete(
        self,
        *,
        connection_id: str,
        negotiation_generation: int,
        trajectory_digest: Digest,
        frame_count: int,
    ) -> RoomEffect | None:
        """Record one peer's completion and reconcile it with every other peer."""
        member = self._authorize(connection_id, negotiation_generation)
        if self._state != "running":
            raise P2PRoomError("command.state_conflict", "the room is not running")
        try:
            status = self._capture.report(
                member.peer_handle, trajectory_digest, frame_count
            )
        except P2PCaptureError as error:
            raise P2PRoomError(error.code, error.safe_message) from error
        if status == "conflict":
            return self.abort("capture_conflict", "terminal")
        return self._maybe_finish()

    def submit_capture(
        self,
        *,
        connection_id: str,
        negotiation_generation: int,
        trajectory_digest: Digest,
        frame_count: int,
        payload_json: str,
        payload_digest: Digest,
    ) -> CapturePersistenceFence | MeshAbort | None:
        """Accept one bounded owner payload after recomputing its canonical digest."""
        member = self._authorize(connection_id, negotiation_generation)
        if self._state != "running":
            raise P2PRoomError("command.state_conflict", "the room is not running")
        try:
            status = self._capture.submit(
                peer_handle=member.peer_handle,
                trajectory_digest=trajectory_digest,
                frame_count=frame_count,
                payload_json=payload_json,
                payload_digest=payload_digest,
            )
        except P2PCaptureError as error:
            raise P2PRoomError(error.code, error.safe_message) from error
        if status == "conflict":
            effect = self.abort("capture_conflict", "terminal")
            assert effect is not None
            return effect
        if status != "accepted":
            return None
        if not self._all_current():
            return self._stale_abort()
        return CapturePersistenceFence(
            room_handle=self.room_handle,
            negotiation_generation=self.negotiation_generation,
            payload_digest=payload_digest,
        )

    def capture_payload(self) -> str | None:
        """Return the accepted capture payload for the imperative shell to persist."""
        return self._capture.payload()

    def set_capture_receipt(
        self, fence: CapturePersistenceFence, receipt: str
    ) -> RoomEffect | None:
        """Attach the durable capture receipt and finish when every peer agrees."""
        if self._state != "running":
            raise P2PRoomError("command.state_conflict", "the room is not running")
        if (
            fence.room_handle != self.room_handle
            or fence.negotiation_generation != self.negotiation_generation
            or fence.payload_digest != self._capture.payload_digest()
        ):
            raise P2PRoomError(
                "lease.stale_generation", "the capture persistence fence is stale"
            )
        if not self._all_current():
            return self._stale_abort()
        try:
            outcome = self._capture.set_receipt(receipt)
        except P2PCaptureError as error:
            raise P2PRoomError(error.code, error.safe_message) from error
        return self._finish(outcome)

    def disconnect(self, connection_id: str) -> MeshAbort | None:
        """Abort when a currently bound member disconnects."""
        if connection_id not in self._by_connection:
            return None
        return self.abort("peer_disconnected", "repool")

    def expire(self) -> MeshAbort | None:
        """Abort a room that did not validate or capture before its deadline."""
        if self._state in ("complete", "abort"):
            return None
        if self._monotonic() < self._deadline:
            return None
        if self._state == "running":
            return self.abort("capture_timeout", "repool")
        return self.abort("negotiation_timeout", "repool")

    def abort(
        self,
        reason: AbortReason,
        disposition: AbortDisposition,
    ) -> MeshAbort | None:
        """Fence every connection lease and emit one terminal abort."""
        if self._state in ("complete", "abort"):
            return None
        self._state = "abort"
        self._fence_all()
        return MeshAbort(
            connection_ids=self._connection_ids(),
            room_handle=self.room_handle,
            negotiation_generation=self.negotiation_generation,
            reason=reason,
            disposition=disposition,
        )

    def _authorize(self, connection_id: str, generation: int) -> BoundPeer:
        if self._state in ("complete", "abort"):
            raise P2PRoomError("command.state_conflict", "the room is closed")
        if generation != self.negotiation_generation:
            raise P2PRoomError("lease.stale_generation", "the room generation is stale")
        member = self.member_for_connection(connection_id)
        if member is None:
            raise P2PRoomError("auth.forbidden", "the connection is not a room member")
        self._validate_member(member)
        return member

    def _validate_member(self, member: BoundPeer) -> None:
        lease = member.lease
        if (
            lease.interaction_id != self.interaction_id
            or lease.actor_id != member.actor_id
            or lease.lease.namespace_epoch_id == ""
            or member.actor_id not in self.membership.peer_actor_ids
        ):
            raise P2PRoomError("auth.forbidden", "the connection binding is invalid")
        if self._fenced or not self._lease_is_current(lease):
            raise P2PRoomError(
                "lease.stale_generation", "the connection lease is stale"
            )
        if _instant(lease.expires_at) <= _aware(self._utc_now()):
            raise P2PRoomError("lease.expired", "the connection lease has expired")

    def _is_current(self, member: BoundPeer) -> bool:
        try:
            self._validate_member(member)
        except P2PRoomError:
            return False
        return True

    def _all_current(self) -> bool:
        return all(self._is_current(member) for member in self._members.values())

    def _stale_abort(self) -> MeshAbort:
        effect = self.abort("stale_connection", "repool")
        assert effect is not None
        return effect

    def _check_signal_attempt(self, peer_handle: str, payload_json: str | None) -> None:
        payload_bytes = len(payload_json.encode("utf-8")) if payload_json else 0
        if payload_bytes > self.limits.max_signal_bytes:
            raise P2PRoomError(
                "runtime.backpressure", "the signal payload is too large"
            )
        now = self._monotonic()
        times = self._signal_times[peer_handle]
        while times and now - times[0] >= self.limits.signal_window_seconds:
            times.popleft()
        if len(times) >= self.limits.max_signals_per_window:
            raise P2PRoomError("quota.rate_limited", "signals are arriving too quickly")
        times.append(now)

    def _check_new_signal(self, peer_handle: str) -> None:
        count = self._signal_count[peer_handle] + 1
        if count > self.limits.max_signals_per_peer:
            raise P2PRoomError("runtime.backpressure", "the signal limit was reached")
        self._signal_count[peer_handle] = count

    def _maybe_finish(self) -> RoomEffect | None:
        return self._finish(self._capture.finish())

    def _finish(self, outcome: CaptureOutcome | None) -> RoomEffect | None:
        if outcome is None:
            return None
        if self._state != "running":
            return None
        if not self._all_current():
            return self._stale_abort()
        self._state = "complete"
        self._fence_all()
        return MeshFinish(
            connection_ids=self._connection_ids(),
            room_handle=self.room_handle,
            negotiation_generation=self.negotiation_generation,
            trajectory_digest=outcome.trajectory_digest,
            frame_count=outcome.frame_count,
            capture_receipt=outcome.capture_receipt,
        )

    def _fence_all(self) -> None:
        if self._fenced:
            return
        self._fenced = True
        for member in self._members.values():
            if self._lease_is_current(member.lease):
                self._fence_lease(member.lease)

    def _connection_ids(self) -> tuple[str, ...]:
        return tuple(member.connection_id for member in self._members.values())

    @staticmethod
    def _validate_shape(
        interaction_id: str,
        membership: P2PMeshMembership,
        members: Sequence[BoundPeer],
    ) -> None:
        if not 2 <= len(members) <= 16:
            raise ValueError("a browser peer room needs from 2 to 16 members")
        if len(members) != len(membership.peer_actor_ids):
            raise ValueError("room members must cover the complete frozen mesh")
        handles = {member.peer_handle for member in members}
        connections = {member.connection_id for member in members}
        actors = {member.actor_id for member in members}
        if (
            len(handles) != len(members)
            or len(connections) != len(members)
            or actors != set(membership.peer_actor_ids)
            or membership.interaction_id != interaction_id
        ):
            raise ValueError("room bindings must be unique and match the membership")


def _instant(value: str) -> datetime:
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    return parsed.replace(tzinfo=timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "BoundPeer",
    "CapturePersistenceFence",
    "MeshAbort",
    "MeshFinish",
    "MeshStart",
    "P2PRoom",
    "P2PRoomError",
    "RoomBinding",
    "RoomEffect",
    "RoomLimits",
    "RoomRuntime",
    "RoomState",
    "SignalDelivery",
    "SignalKind",
]
