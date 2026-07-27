"""Coordinate authenticated browser connections into live P2P game rooms.

This module is the imperative shell around the transport-neutral room core. It
binds an authenticated browser session and durable enrollment to a formed actor
and full connection lease. It owns matchmaking, room lifetime, ICE grant scope,
capture persistence, and terminal re-pooling. It does not parse or serialize the
API-09 wire; the web adapter owns that boundary.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from datetime import timezone
from typing import Any, Literal, cast

from mug.client.ice import IceCredentialResponse, IceGrantError, IceGrantRegistry
from mug.game.p2p_pool import (
    FormedRoom,
    P2PRoomPool,
    RoomPoolConfig,
    RoomPoolRuntime,
    WaitingPeer,
)
from mug.game.p2p_room import P2PRoom, P2PRoomError
from mug.game.p2p_room_types import (
    CapturePersistenceFence,
    MeshAbort,
    MeshFinish,
    MeshStart,
    RoomEffect,
    SignalKind,
)
from mug.gateway import Gateway
from mug.interactions.bus import NodeMessage
from mug.interactions.rendezvous import Ticket
from mug.kernel import Digest, PrincipalRef, compute_digest
from mug.nodes import (
    P2P_CALL,
    P2P_EFFECT,
    P2P_END,
    P2P_ICE,
    P2P_SEATED,
    Node,
    assignment_as_json,
    assignment_of_json,
    effect_as_json,
    effect_of_json,
    end_as_json,
    end_of_json,
)
from mug.participant_p2p_capture import (
    P2PCaptureWrite,
    P2PEpisodeWrite,
    persist_p2p_capture,
    record_p2p_episode,
)
from mug.participant_p2p_types import (
    BrowserP2PConfig,
    P2PConnectionIdentity,
    P2PEdgeError,
    P2PSend,
    PeerAssignment,
    RoomAssignment,
    RoomEnd,
)
from mug.storage import Store

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _credentials_of_json(held: Mapping[str, Any]) -> IceCredentialResponse:
    """Rebuild one ICE answer from the process that issued the grant.

    The fields cross rather than the browser's configuration object, because the
    node that asked has to hand its browser exactly what the issuing node built.
    """
    return IceCredentialResponse(
        stun_urls=tuple(cast("list[str]", held["stun_urls"])),
        turn_urls=tuple(cast("list[str]", held["turn_urls"])),
        username=cast("str | None", held.get("username")),
        credential=cast("str | None", held.get("credential")),
        force_relay=bool(held["force_relay"]),
    )


@dataclass
class P2PConnection:
    """One authenticated browser socket the coordinator holds authority over."""

    connection_id: str
    identity: P2PConnectionIdentity
    send: P2PSend
    active: bool = True


@dataclass
class _Join:
    connection: P2PConnection
    assignment: asyncio.Future[RoomAssignment]


@dataclass
class _LiveRoom:
    room: P2PRoom
    assignments: dict[str, RoomAssignment]
    episode_id: str
    timeout_task: asyncio.Task[None] | None = None


class P2PCoordinator:
    """Own matchmaking and live state for one browser P2P game mount."""

    def __init__(
        self,
        gateway: Gateway,
        store: Store,
        config: BrowserP2PConfig,
        monotonic: Callable[[], float] = time.monotonic,
        node: Node | None = None,
    ) -> None:
        self.config = config
        self._gateway = gateway
        self._store = store
        self._monotonic = monotonic
        self._pool = P2PRoomPool(
            RoomPoolConfig(
                channel_key=config.channel_key,
                size=config.size,
                seed=config.seed,
                study_version=config.study_version,
                limits=config.limits,
                verify_capture=config.capture_verifier,
            ),
            RoomPoolRuntime(
                new_id=gateway.new_id,
                new_handle=gateway.new_handle,
                now=self._now,
                utc_now=gateway.clock,
                monotonic=monotonic,
            ),
        )
        self._ice = IceGrantRegistry(
            new_handle=gateway.new_handle,
            utc_now=gateway.clock,
            config=config.ice,
        )
        self._lock = asyncio.Lock()
        self._connections: dict[str, P2PConnection] = {}
        self._by_session: dict[str, str] = {}
        self._by_enrollment: dict[str, str] = {}
        self._waiting: dict[str, _Join] = {}
        self._rooms: dict[str, _LiveRoom] = {}
        self._room_of_connection: dict[str, str] = {}
        self._closed_rooms: deque[str] = deque(maxlen=1_024)
        self._node = node
        # Which node holds the socket behind each stand-in connection this process
        # made for a browser it does not hold, and which room each is in.
        self._away: dict[str, str] = {}
        self._elsewhere: dict[str, str] = {}
        self._pending: dict[str, RoomAssignment] = {}
        self._running: set[asyncio.Task[None]] = set()
        if node is not None:
            node.link.on(P2P_SEATED, self._on_seated)
            node.link.on(P2P_CALL, self._on_call)
            node.link.on(P2P_EFFECT, self._on_effect)
            node.link.on(P2P_END, self._on_end)
            node.link.on(P2P_ICE, self._on_ice)

    async def connect(
        self, identity: P2PConnectionIdentity, send: P2PSend
    ) -> P2PConnection:
        """Register one authenticated socket and fence any prior binding."""
        connection = P2PConnection(self._gateway.new_handle(), identity, send)
        effects: list[MeshAbort] = []
        async with self._lock:
            old_ids = {
                value
                for value in (
                    self._by_session.get(identity.browser_session_handle),
                    self._by_enrollment.get(identity.enrollment_id),
                )
                if value is not None
            }
            for old_id in old_ids:
                effect = self._replace_locked(old_id)
                if effect is not None:
                    effects.append(effect)
            self._connections[connection.connection_id] = connection
            self._by_session[identity.browser_session_handle] = connection.connection_id
            self._by_enrollment[identity.enrollment_id] = connection.connection_id
        for effect in effects:
            await self._dispatch(effect)
        return connection

    async def enqueue(
        self, connection: P2PConnection
    ) -> asyncio.Future[RoomAssignment]:
        """Submit one active connection and return its room-assignment future."""
        future = asyncio.get_running_loop().create_future()
        async with self._lock:
            self._require_active(connection)
            if connection.identity.enrollment_id in self._waiting:
                raise P2PEdgeError(
                    "command.state_conflict", "the enrollment is already waiting"
                )
            if connection.connection_id in self._room_of_connection:
                raise P2PEdgeError(
                    "command.state_conflict", "the connection is already in a room"
                )
            self._waiting[connection.identity.enrollment_id] = _Join(connection, future)
            if self._node is None:
                for formed in self._pool.submit(self._peer(connection)):
                    self._form_locked(formed)
        if self._node is not None:
            await self._rendezvous(connection)
        return future

    def _peer(self, connection: P2PConnection) -> WaitingPeer:
        """Return the pool's view of one connection that is waiting for a room."""
        return WaitingPeer(
            connection_id=connection.connection_id,
            enrollment_id=connection.identity.enrollment_id,
            visit_id=connection.identity.visit_id,
        )

    async def _rendezvous(self, connection: P2PConnection) -> None:
        """Put one browser in the shared waiting room and claim a group if it fills.

        Whichever process claims the group holds the room core for it, and every
        other process becomes a relay between its own browser and that one. The
        browsers still talk to each other directly: only the negotiation crosses
        the boundary, which is what makes this affordable.
        """
        node = self._node
        assert node is not None
        identity = connection.identity
        await node.rendezvous.submit(
            self.config.channel_key,
            Ticket(
                enrollment_id=identity.enrollment_id,
                visit_id=identity.visit_id,
                node_id=node.node_id,
                connection_id=connection.connection_id,
                enqueued_at=self._now(),
                details={
                    "browser_session_handle": identity.browser_session_handle,
                    "principal": identity.principal.model_dump(mode="json"),
                },
            ),
        )
        claimed = await node.rendezvous.claim(self.config.channel_key, self.config.size)
        if claimed:
            self._spawn(self._own(claimed))

    def _spawn(self, work: Coroutine[Any, Any, None]) -> None:
        """Run one piece of hosting work, holding it until it is finished."""
        task = asyncio.ensure_future(work)
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def _own(self, claimed: Sequence[Ticket]) -> None:
        """Hold the room core for one claimed group, wherever its browsers are.

        A member this process does not hold gets a stand-in connection with the
        same connection id its own node gave it, so one identifier names one
        browser across the deployment and neither side has to translate. The
        stand-in's ``send`` puts the effect on the bus; nothing else about the room
        knows the difference.
        """
        node = self._node
        assert node is not None
        for ticket in claimed:
            if ticket.node_id != node.node_id:
                await self._stand_in(ticket)
        async with self._lock:
            formed: list[FormedRoom] = []
            for ticket in claimed:
                connection = self._connections.get(ticket.connection_id)
                if connection is None:
                    continue
                formed.extend(self._pool.submit(self._peer(connection)))
            for room in formed:
                self._form_locked(room)
        await self._announce(claimed)

    async def _stand_in(self, ticket: Ticket) -> None:
        """Register the stand-in for one browser another process holds."""
        node = self._node
        assert node is not None
        identity = P2PConnectionIdentity(
            browser_session_handle=cast(
                "str", ticket.details["browser_session_handle"]
            ),
            enrollment_id=ticket.enrollment_id,
            visit_id=ticket.visit_id,
            principal=PrincipalRef.model_validate(ticket.details["principal"]),
        )
        away = ticket.node_id
        connection_id = ticket.connection_id

        async def send(effect: RoomEffect) -> None:
            await node.link.tell(
                away,
                P2P_EFFECT,
                {"connection_id": connection_id, **effect_as_json(effect)},
            )

        connection = P2PConnection(connection_id, identity, send)
        async with self._lock:
            self._connections[connection_id] = connection
            self._by_session[identity.browser_session_handle] = connection_id
            self._by_enrollment[identity.enrollment_id] = connection_id
            self._waiting[identity.enrollment_id] = _Join(
                connection, asyncio.get_running_loop().create_future()
            )
            self._away[connection_id] = away

    async def _announce(self, claimed: Sequence[Ticket]) -> None:
        """Tell every other node the assignment its own browser is to be given."""
        node = self._node
        assert node is not None
        room_handle: str | None = None
        for ticket in claimed:
            if ticket.node_id == node.node_id:
                continue
            async with self._lock:
                room_handle = self._room_of_connection.get(ticket.connection_id)
                live = self._rooms.get(room_handle or "")
                assignment = (
                    live.assignments.get(ticket.connection_id)
                    if live is not None
                    else None
                )
            if assignment is None:
                continue
            assignment.ended.add_done_callback(
                lambda done, member=ticket: self._spawn(self._tell_end(member, done))
            )
            await node.link.tell(
                ticket.node_id,
                P2P_SEATED,
                {
                    "connection_id": ticket.connection_id,
                    "owner_node": node.node_id,
                    "assignment": assignment_as_json(assignment),
                },
            )
        if room_handle is not None:
            await node.rendezvous.open_room(
                room_handle=room_handle,
                group_key=self.config.channel_key,
                owner_node=node.node_id,
                members=claimed,
            )

    async def _tell_end(self, ticket: Ticket, done: asyncio.Future[RoomEnd]) -> None:
        """Tell the node that holds one browser how its room ended."""
        if done.cancelled() or done.exception() is not None:
            return
        node = self._node
        assert node is not None
        await node.link.tell(
            ticket.node_id,
            P2P_END,
            {
                "connection_id": ticket.connection_id,
                "end": end_as_json(done.result()),
            },
        )

    async def _redeem_elsewhere(
        self, browser_session_handle: str | None, grant_handle: str
    ) -> IceCredentialResponse | None:
        """Redeem an ICE grant on the process that issued it, if that is another.

        The browser asks for its TURN credentials over an ordinary same-origin
        request, which the load balancer sends wherever it likes. The grant was
        issued by the process that runs its room and is redeemable exactly once, so
        the request has to reach that process rather than be answered locally.
        """
        if self._node is None or browser_session_handle is None:
            return None
        connection_id = self._by_session.get(browser_session_handle)
        owner = self._elsewhere.get(connection_id or "")
        if owner is None:
            return None
        answer = await self._node.link.ask(
            owner,
            P2P_ICE,
            {
                "browser_session_handle": browser_session_handle,
                "grant_handle": grant_handle,
            },
        )
        code = answer.get("code")
        if code is not None:
            raise P2PEdgeError(
                cast("str", code), cast("str", answer.get("message", ""))
            )
        held = cast("Mapping[str, Any]", answer["credentials"])
        return _credentials_of_json(held)

    async def _relay(
        self, connection: P2PConnection, call: str, body: NodeMessage
    ) -> bool:
        """Hand one browser's frame to the process that runs its room.

        Returns False when this process runs the room itself, so the caller carries
        on locally. A refusal comes back as a code and is raised here, so a browser
        on a relaying node is told exactly what it would have been told on the node
        that runs the room.
        """
        owner = self._elsewhere.get(connection.connection_id)
        if owner is None or self._node is None:
            return False
        answer = await self._node.link.ask(
            owner,
            P2P_CALL,
            {"call": call, "connection_id": connection.connection_id, **body},
        )
        code = answer.get("code")
        if code is not None:
            raise P2PRoomError(
                cast("str", code), cast("str", answer.get("message", ""))
            )
        return True

    async def _on_seated(self, message: NodeMessage) -> NodeMessage | None:
        """Take the assignment the process that runs the room built for our browser."""
        connection_id = cast("str", message["connection_id"])
        connection = self._connections.get(connection_id)
        if connection is None:
            return None
        assignment = assignment_of_json(
            cast("Mapping[str, Any]", message["assignment"])
        )
        async with self._lock:
            join = self._waiting.pop(connection.identity.enrollment_id, None)
            self._elsewhere[connection_id] = cast("str", message["owner_node"])
            self._room_of_connection[connection_id] = assignment.room_handle
            self._pending[connection_id] = assignment
        if join is not None and not join.assignment.done():
            join.assignment.set_result(assignment)
        return None

    async def _on_effect(self, message: NodeMessage) -> NodeMessage | None:
        """Write one effect the process that runs the room produced for our browser."""
        connection = self._connections.get(cast("str", message["connection_id"]))
        if connection is None or not connection.active:
            return None
        await connection.send(effect_of_json(message))
        return None

    async def _on_end(self, message: NodeMessage) -> NodeMessage | None:
        """Resolve our browser's wait with how its room ended elsewhere."""
        connection_id = cast("str", message["connection_id"])
        async with self._lock:
            assignment = self._pending.pop(connection_id, None)
            self._elsewhere.pop(connection_id, None)
            self._room_of_connection.pop(connection_id, None)
        if assignment is not None and not assignment.ended.done():
            assignment.ended.set_result(
                end_of_json(cast("Mapping[str, Any]", message["end"]))
            )
        return None

    async def _on_ice(self, message: NodeMessage) -> NodeMessage | None:
        """Redeem an ICE grant this process issued, for a browser held elsewhere."""
        try:
            credentials = await self.redeem_ice(
                cast("str | None", message.get("browser_session_handle")),
                cast("str", message["grant_handle"]),
            )
        except (P2PEdgeError, IceGrantError) as refusal:
            return {"code": refusal.code, "message": refusal.safe_message}
        return {
            "credentials": {
                "stun_urls": list(credentials.stun_urls),
                "turn_urls": list(credentials.turn_urls),
                "username": credentials.username,
                "credential": credentials.credential,
                "force_relay": credentials.force_relay,
            }
        }

    async def _on_call(self, message: NodeMessage) -> NodeMessage | None:
        """Apply one browser's frame here, on behalf of the node that holds it."""
        connection = self._connections.get(cast("str", message["connection_id"]))
        if connection is None:
            return {"code": "auth.unauthenticated", "message": "no P2P session"}
        try:
            await self._apply(connection, message)
        except (P2PRoomError, P2PEdgeError) as refusal:
            return {"code": refusal.code, "message": refusal.safe_message}
        return {}

    async def _apply(self, connection: P2PConnection, message: NodeMessage) -> None:
        """Route one relayed call to the method it names."""
        call = cast("str", message["call"])
        room_handle = cast("str", message.get("room_handle", ""))
        if call == "signal":
            await self.relay_signal(
                connection,
                room_handle=room_handle,
                request_id=cast("str", message["request_id"]),
                target_peer_handle=cast("str", message["target_peer_handle"]),
                negotiation_generation=int(cast("int", message["generation"])),
                signal_kind=cast("SignalKind", message["signal_kind"]),
                payload_json=cast("str | None", message.get("payload_json")),
            )
        elif call == "ready":
            await self.mark_ready(
                connection,
                room_handle,
                int(cast("int", message["generation"])),
                tuple(cast("list[str]", message["peer_handles"])),
            )
        elif call == "complete":
            await self.report_complete(
                connection,
                room_handle,
                int(cast("int", message["generation"])),
                Digest.model_validate(message["trajectory_digest"]),
                int(cast("int", message["frame_count"])),
            )
        elif call == "capture":
            await self.submit_capture(
                connection,
                room_handle=room_handle,
                generation=int(cast("int", message["generation"])),
                trajectory_digest=Digest.model_validate(message["trajectory_digest"]),
                frame_count=int(cast("int", message["frame_count"])),
                payload_json=cast("str", message["payload_json"]),
                payload_digest=Digest.model_validate(message["payload_digest"]),
            )
        elif call == "disconnect":
            await self.disconnect(connection)

    async def relay_signal(
        self,
        connection: P2PConnection,
        *,
        room_handle: str,
        request_id: str,
        target_peer_handle: str,
        negotiation_generation: int,
        signal_kind: SignalKind,
        payload_json: str | None,
    ) -> None:
        """Validate one signal and deliver its server-stamped effect."""
        if await self._relay(
            connection,
            "signal",
            {
                "room_handle": room_handle,
                "request_id": request_id,
                "target_peer_handle": target_peer_handle,
                "generation": negotiation_generation,
                "signal_kind": signal_kind,
                "payload_json": payload_json,
            },
        ):
            return
        async with self._lock:
            live = self._live_room_locked(connection, room_handle)
            effect = live.room.relay_signal(
                connection_id=connection.connection_id,
                request_id=request_id,
                target_peer_handle=target_peer_handle,
                negotiation_generation=negotiation_generation,
                signal_kind=signal_kind,
                payload_json=payload_json,
            )
        if effect is not None:
            await self._dispatch(effect)

    async def mark_ready(
        self,
        connection: P2PConnection,
        room_handle: str,
        generation: int,
        peer_handles: tuple[str, ...],
    ) -> None:
        """Record one full validation report and dispatch the one start effect."""
        if await self._relay(
            connection,
            "ready",
            {
                "room_handle": room_handle,
                "generation": generation,
                "peer_handles": list(peer_handles),
            },
        ):
            return
        async with self._lock:
            live = self._live_room_locked(connection, room_handle)
            effect = live.room.mark_ready(
                connection_id=connection.connection_id,
                negotiation_generation=generation,
                validated_peer_handles=peer_handles,
            )
        if effect is not None:
            await self._dispatch(effect)

    async def report_complete(
        self,
        connection: P2PConnection,
        room_handle: str,
        generation: int,
        trajectory_digest: Digest,
        frame_count: int,
    ) -> None:
        """Record one completion claim and dispatch finish or conflict."""
        if await self._relay(
            connection,
            "complete",
            {
                "room_handle": room_handle,
                "generation": generation,
                "trajectory_digest": trajectory_digest.model_dump(mode="json"),
                "frame_count": frame_count,
            },
        ):
            return
        async with self._lock:
            live = self._live_room_locked(connection, room_handle)
            effect = live.room.report_complete(
                connection_id=connection.connection_id,
                negotiation_generation=generation,
                trajectory_digest=trajectory_digest,
                frame_count=frame_count,
            )
        if effect is not None:
            await self._dispatch(effect)

    async def submit_capture(
        self,
        connection: P2PConnection,
        *,
        room_handle: str,
        generation: int,
        trajectory_digest: Digest,
        frame_count: int,
        payload_json: str,
        payload_digest: Digest,
    ) -> None:
        """Validate, persist, and receipt the designated owner's capture once."""
        if await self._relay(
            connection,
            "capture",
            {
                "room_handle": room_handle,
                "generation": generation,
                "trajectory_digest": trajectory_digest.model_dump(mode="json"),
                "frame_count": frame_count,
                "payload_json": payload_json,
                "payload_digest": payload_digest.model_dump(mode="json"),
            },
        ):
            return
        async with self._lock:
            live = self._live_room_locked(connection, room_handle)
            result = live.room.submit_capture(
                connection_id=connection.connection_id,
                negotiation_generation=generation,
                trajectory_digest=trajectory_digest,
                frame_count=frame_count,
                payload_json=payload_json,
                payload_digest=payload_digest,
            )
            room = live.room
            episode_id = live.episode_id
        if isinstance(result, MeshAbort):
            await self._dispatch(result)
            return
        if result is None:
            return
        try:
            receipt = await self._persist_capture(room, result, payload_json)
            await self._record_episode(room, episode_id, payload_json)
        except Exception:
            await self.abort(room_handle, "server_unavailable", "repool")
            return
        async with self._lock:
            current = self._rooms.get(room_handle)
            if current is None or current.room is not room:
                return
            effect = room.set_capture_receipt(result, receipt)
        if effect is not None:
            await self._dispatch(effect)

    async def redeem_ice(
        self, browser_session_handle: str | None, grant_handle: str
    ) -> IceCredentialResponse:
        """Redeem ICE only for the current authenticated browser room binding.

        ``browser_session_handle`` is the deployment's own answer to "which browser
        is this?", and when it is given the redemption must agree with it. A
        deployment that has no authenticated same-origin session passes ``None``,
        and the grant names its own browser: it is unguessable, one-use, expiring,
        and bound to one room and one peer, and the checks below still require that
        browser to hold a live connection seated in that live room.
        """
        forwarded = await self._redeem_elsewhere(browser_session_handle, grant_handle)
        if forwarded is not None:
            return forwarded
        async with self._lock:
            session = browser_session_handle or self._ice.bound_session(grant_handle)
            if session is None:
                raise P2PEdgeError("resource.not_found", "the ICE grant is not valid")
            connection_id = self._by_session.get(session)
            connection = self._connections.get(connection_id or "")
            if connection is None or not connection.active:
                raise P2PEdgeError("auth.unauthenticated", "no P2P session is active")
            room_handle = self._room_of_connection.get(connection.connection_id)
            live = self._rooms.get(room_handle or "")
            if live is None:
                raise P2PEdgeError("auth.forbidden", "no P2P room is active")
            member = live.room.member_for_connection(connection.connection_id)
            if member is None:
                raise P2PEdgeError("auth.forbidden", "no P2P peer is bound")
            return self._ice.redeem(
                grant_handle,
                session,
                live.room.room_handle,
                member.peer_handle,
            )

    def waiting_count(self) -> int:
        """Return how many enrollments are waiting for a room right now.

        The waiting room is otherwise invisible from outside: a browser that is
        waiting receives nothing until its room forms. An operator view needs this
        number to answer "is anyone stuck?", and so does a test that must know a
        departure has been processed before it acts on it.
        """
        return len(self._waiting)

    def visit_of_peer(self, peer_handle: str) -> str | None:
        """Return the visit behind one live peer handle, or None if it is not live.

        The map from a public handle to its trusted binding stays server-side.
        This reads one entry of it, which an operator view or an authenticated
        same-origin endpoint needs to scope a request to its own participant.
        """
        for live in self._rooms.values():
            for member in live.room.members():
                if member.peer_handle == peer_handle:
                    return member.visit_id
        return None

    async def disconnect(self, connection: P2PConnection) -> None:
        """Release a wait or abort the complete room when a socket disconnects."""
        # A browser that leaves a room this process does not run still ends it for
        # its peers, so the departure crosses before the local bookkeeping does.
        with contextlib.suppress(P2PRoomError, P2PEdgeError, TimeoutError):
            await self._relay(connection, "disconnect", {})
        if self._node is not None:
            async with self._lock:
                self._elsewhere.pop(connection.connection_id, None)
                self._pending.pop(connection.connection_id, None)
            await self._node.rendezvous.release(
                self.config.channel_key, connection.identity.enrollment_id
            )
        effect: MeshAbort | None = None
        async with self._lock:
            connection.active = False
            enrollment = connection.identity.enrollment_id
            join = self._waiting.get(enrollment)
            if join is not None and join.connection is connection:
                self._waiting.pop(enrollment)
                self._pool.release(enrollment)
                if not join.assignment.done():
                    join.assignment.cancel()
            room_handle = self._room_of_connection.get(connection.connection_id)
            live = self._rooms.get(room_handle or "")
            if live is not None:
                effect = live.room.disconnect(connection.connection_id)
            self._drop_binding_locked(connection)
        if effect is not None:
            await self._dispatch(effect)

    async def abort(
        self,
        room_handle: str,
        reason: Literal[
            "peer_disconnected",
            "negotiation_timeout",
            "validation_failed",
            "stale_connection",
            "room_replaced",
            "capture_timeout",
            "capture_conflict",
            "server_unavailable",
        ],
        disposition: Literal["repool", "resume_flow", "terminal"],
    ) -> None:
        """Abort one live room by its server-held handle."""
        async with self._lock:
            live = self._rooms.get(room_handle)
            effect = live.room.abort(reason, disposition) if live is not None else None
        if effect is not None:
            await self._dispatch(effect)

    def _form_locked(self, formed: FormedRoom) -> None:
        room = formed.room
        assignments = self._assignments(formed)
        # The mesh plays one episode, so the group gets one episode identity. It
        # is minted here, where the room is formed, and never sent to a browser.
        live = _LiveRoom(
            room=room,
            assignments=assignments,
            episode_id=self._gateway.new_id("episode"),
        )
        self._rooms[room.room_handle] = live
        for placement in formed.placements:
            connection_id = placement.connection_id
            connection = self._connections[connection_id]
            join = self._waiting.pop(connection.identity.enrollment_id)
            self._room_of_connection[connection_id] = room.room_handle
            join.assignment.set_result(assignments[connection_id])
        live.timeout_task = asyncio.create_task(self._watch_timeout(room.room_handle))

    def _assignments(self, formed: FormedRoom) -> dict[str, RoomAssignment]:
        room = formed.room
        assignments: dict[str, RoomAssignment] = {}
        for placement in formed.placements:
            connection = self._connections[placement.connection_id]
            grant = self._ice.issue(
                connection.identity.browser_session_handle,
                room.room_handle,
                placement.local_peer_handle,
            )
            assignments[placement.connection_id] = RoomAssignment(
                room_handle=room.room_handle,
                local_peer_handle=placement.local_peer_handle,
                capture_owner_handle=room.capture_owner_handle,
                negotiation_generation=room.negotiation_generation,
                peers=tuple(
                    PeerAssignment(peer_handle=remote.peer_handle, role=remote.role)
                    for remote in placement.remote_peers
                ),
                validation_timeout_ms=int(
                    self.config.limits.validation_timeout_seconds * 1_000
                ),
                ice_grant=grant,
                ice_endpoint=self.config.ice_endpoint,
                ended=asyncio.get_running_loop().create_future(),
            )
        return assignments

    async def _watch_timeout(self, room_handle: str) -> None:
        while True:
            async with self._lock:
                live = self._rooms.get(room_handle)
                if live is None:
                    return
                delay = max(0.0, live.room.deadline - self._monotonic())
            await asyncio.sleep(delay)
            async with self._lock:
                live = self._rooms.get(room_handle)
                effect = live.room.expire() if live is not None else None
            if effect is not None:
                await self._dispatch(effect)
                return

    async def _persist_capture(
        self,
        room: P2PRoom,
        fence: CapturePersistenceFence,
        payload_json: str,
    ) -> str:
        return await persist_p2p_capture(
            self._gateway,
            self._store,
            P2PCaptureWrite(
                room_handle=room.room_handle,
                interaction_id=room.interaction_id,
                negotiation_generation=room.negotiation_generation,
                payload_digest=fence.payload_digest,
                payload_json=payload_json,
            ),
        )

    async def _record_episode(
        self, room: P2PRoom, episode_id: str, payload_json: str
    ) -> None:
        """Record the agreed trajectory as one peer-authority episode.

        Only a mount that ships a browser mesh game can read the payload, because
        only then does the server know its shape. A study that brought its own
        capture verifier keeps the artifact and the receipt and records nothing
        further, which is what it asked for.
        """
        spec = self.config.game
        if spec is None:
            return
        owner = next(
            member
            for member in room.members()
            if member.peer_handle == room.capture_owner_handle
        )
        connection = self._connections.get(owner.connection_id)
        if connection is None:
            raise P2PEdgeError("auth.unauthenticated", "the capture owner has gone")
        await record_p2p_episode(
            self._gateway,
            self._store,
            P2PEpisodeWrite(
                interaction_id=room.interaction_id,
                episode_id=episode_id,
                channel_key=spec.channel_key,
                membership_generation=room.negotiation_generation,
                mesh_membership_digest=compute_digest(
                    room.membership.model_dump(mode="json")
                ),
                actor_by_handle={
                    member.peer_handle: member.actor_id for member in room.members()
                },
                seat_by_handle={
                    member.peer_handle: member.seat_key for member in room.members()
                },
                reference_handle=owner.peer_handle,
                reference_visit_id=owner.visit_id,
                reference_principal=connection.identity.principal,
                payload_json=payload_json,
            ),
        )

    async def _dispatch(self, effect: RoomEffect) -> None:
        """Deliver one effect, and release a terminal room only after it is sent.

        A terminal effect is often produced inside a member's own reader task. That
        task is cancelled once the member's room future resolves, so the release
        must come last: otherwise the dispatch cancels itself part way through the
        broadcast and a peer never learns that the room ended.
        """
        release: Callable[[], None] | None = None
        if isinstance(effect, (MeshAbort, MeshFinish)):
            connections, release = await self._close_room(effect)
        elif isinstance(effect, MeshStart):
            connections = self._connections_for(effect.connection_ids)
        else:
            connection = self._connections.get(effect.connection_id)
            connections = [connection] if connection is not None else []
        failed: list[P2PConnection] = []
        for connection in connections:
            # A connection that already went away is skipped, not written to. A
            # peer disconnect is the usual cause of a terminal effect, and a write
            # to that socket can block, which would keep the effect from every
            # other member of the room.
            if not connection.active:
                continue
            try:
                await connection.send(effect)
            except Exception:
                failed.append(connection)
        if release is not None:
            release()
            return
        for connection in failed:
            await self.disconnect(connection)

    async def _close_room(
        self, effect: MeshAbort | MeshFinish
    ) -> tuple[list[P2PConnection], Callable[[], None]]:
        """Drop one terminal room and return its members and its release step.

        The release resolves every member's room future, which lets each member's
        flow continue. The caller runs it after the terminal frame has reached
        every socket.
        """
        async with self._lock:
            live = self._rooms.pop(effect.room_handle, None)
            if live is None:
                return [], lambda: None
            task = live.timeout_task
            if task is not None and task is not asyncio.current_task():
                task.cancel()
            self._closed_rooms.append(effect.room_handle)
            end = (
                RoomEnd(kind="abort", disposition=effect.disposition)
                if isinstance(effect, MeshAbort)
                else RoomEnd(
                    kind="finish",
                    disposition="resume_flow",
                    capture_receipt=effect.capture_receipt,
                )
            )
            assignments = list(live.assignments.items())
            for connection_id, _ in assignments:
                self._room_of_connection.pop(connection_id, None)

            def release() -> None:
                for _, assignment in assignments:
                    if not assignment.ended.done():
                        assignment.ended.set_result(end)

            return self._connections_for(effect.connection_ids), release

    def _connections_for(self, connection_ids: tuple[str, ...]) -> list[P2PConnection]:
        return [
            connection
            for connection_id in connection_ids
            if (connection := self._connections.get(connection_id)) is not None
        ]

    def _live_room_locked(
        self, connection: P2PConnection, room_handle: str
    ) -> _LiveRoom:
        self._require_active(connection)
        if room_handle in self._closed_rooms:
            raise P2PRoomError("command.state_conflict", "the room is closed")
        if self._room_of_connection.get(connection.connection_id) != room_handle:
            raise P2PRoomError("auth.forbidden", "the connection is not a room member")
        live = self._rooms.get(room_handle)
        if live is None:
            raise P2PRoomError("command.state_conflict", "the room is closed")
        return live

    def _replace_locked(self, connection_id: str) -> MeshAbort | None:
        connection = self._connections.get(connection_id)
        if connection is None:
            return None
        connection.active = False
        enrollment = connection.identity.enrollment_id
        join = self._waiting.get(enrollment)
        if join is not None and join.connection is connection:
            self._waiting.pop(enrollment)
            self._pool.release(enrollment)
            if not join.assignment.done():
                join.assignment.set_exception(
                    P2PEdgeError(
                        "lease.stale_generation", "the connection was replaced"
                    )
                )
        room_handle = self._room_of_connection.get(connection_id)
        live = self._rooms.get(room_handle or "")
        self._drop_binding_locked(connection)
        return live.room.abort("room_replaced", "repool") if live is not None else None

    def _drop_binding_locked(self, connection: P2PConnection) -> None:
        identity = connection.identity
        connection_id = connection.connection_id
        if self._by_session.get(identity.browser_session_handle) == connection_id:
            self._by_session.pop(identity.browser_session_handle)
        if self._by_enrollment.get(identity.enrollment_id) == connection_id:
            self._by_enrollment.pop(identity.enrollment_id)

    @staticmethod
    def _require_active(connection: P2PConnection) -> None:
        if not connection.active:
            raise P2PEdgeError("lease.stale_generation", "the connection is stale")

    def _now(self) -> str:
        value = self._gateway.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime(_INSTANT)


__all__ = [
    "BrowserP2PConfig",
    "P2PConnection",
    "P2PConnectionIdentity",
    "P2PCoordinator",
    "P2PEdgeError",
    "PeerAssignment",
    "RoomAssignment",
    "RoomEnd",
]
