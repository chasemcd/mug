"""The native realtime transport: one session per websocket connection.

The transport is an ingress adapter, a sibling of the HTTP edge. It accepts a
websocket, resolves the acting principal, and answers a handshake. It then reads
typed command frames, acknowledges each with a ``TransportAck``, and hands the
command to a dispatch seam that does the domain work. The seam owns no command in
M1; a later milestone wires the participant handlers behind it.

A session keeps a resume cursor: the highest stream sequence the participant has
seen. A client reconnects with its last cursor as the ``resume_from`` query
parameter, and the handshake reports the cursor the server resumes from. The
transport never leaks a provider trace, a credential, or an input value; a frame
that does not validate returns a generic, safe error.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from mug.client import RealtimeCommand, TransportAck
from mug.kernel import CommandReceipt, PrincipalRef, StreamPosition

# The dispatch seam: do the domain work for one parsed command and answer a
# durable receipt, or None when no handler owns the command. M1 injects a seam
# that owns no command; a later milestone wires the participant handlers.
RealtimeDispatch = Callable[
    ["RealtimeCommand", Any, "Session"], Awaitable[CommandReceipt | None]
]
# Resolve the acting principal for one connection (a pseudonymous subject).
ResolvePrincipal = Callable[[WebSocket], PrincipalRef]
# Establish the session before the handshake (for example, resume or open the
# flow) and return extra handshake fields (for example a resume token) to send.
Establish = Callable[["Session"], Awaitable[dict[str, Any]]]
# Seed a session once the handshake completes (for example, open the flow).
OnOpen = Callable[["Session"], Awaitable[None]]
# Run a server-driven activity (for example, the game stepping loop) that takes
# the socket over, reads its own input frames, and pushes its own frames.
OnGame = Callable[[WebSocket, "Session"], Awaitable[None]]


class SessionRejected(Exception):
    """The establish hook refuses a connection (for example, no valid ticket).

    A launch gate raises this to turn a bad entry into a safe error and a close,
    rather than a session. The message is participant-safe: it names no principal,
    no ticket value, and no trace.
    """

    def __init__(self, code: str, category: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.category = category
        self.safe_message = message


class Session:
    """The per-connection state the transport keeps for one participant.

    ``cursor`` is the highest stream sequence the participant has seen; a commit
    advances it, and a reconnect resumes from it. ``state`` is an application bag
    the dispatch and open hooks use (for example the participant flow). ``outbox``
    holds delivery frames the server pushes after the next flush.
    """

    def __init__(self, principal: PrincipalRef, *, cursor: int = 0) -> None:
        self.principal = principal
        self.cursor = cursor
        self.state: dict[str, Any] = {}
        self.outbox: list[dict[str, Any]] = []

    def deliver(self, delivery: dict[str, Any]) -> None:
        """Queue one delivery payload for the next flush to the client."""
        self.outbox.append(delivery)


def _resume_from(websocket: WebSocket) -> int:
    """Read the client resume cursor from the query, clamped to nonnegative."""
    raw = websocket.query_params.get("resume_from")
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _accepted_position(receipt: CommandReceipt) -> StreamPosition | None:
    """Return the head stream position of a committed receipt, if it has one."""
    positions = receipt.stream_positions
    if not positions:
        return None
    stream_id, sequence = max(positions.items(), key=lambda item: item[1])
    return StreamPosition(stream_id=stream_id, sequence=sequence)


async def _send_ack(websocket: WebSocket, ack: TransportAck) -> None:
    """Send one transport acknowledgement frame."""
    await websocket.send_json(
        {"type": "ack", "ack": ack.model_dump(mode="json", exclude_none=True)}
    )


async def _send_error(
    websocket: WebSocket,
    command_id: str | None,
    code: str,
    category: str,
    message: str,
) -> None:
    """Send one safe error frame; it carries no trace and no input value."""
    await websocket.send_json(
        {
            "type": "error",
            "command_id": command_id,
            "code": code,
            "category": category,
            "message": message,
        }
    )


async def _flush(websocket: WebSocket, session: Session) -> None:
    """Push every queued delivery to the client, oldest first."""
    while session.outbox:
        await websocket.send_json(
            {"type": "delivery", "delivery": session.outbox.pop(0)}
        )


async def _handle_command(
    websocket: WebSocket,
    frame: dict[str, Any],
    dispatch: RealtimeDispatch,
    session: Session,
) -> None:
    """Parse, acknowledge, dispatch one command, and acknowledge its outcome."""
    try:
        command = RealtimeCommand.model_validate(frame.get("command"))
    except ValidationError:
        await _send_error(
            websocket,
            None,
            "schema.validation_failed",
            "validation",
            "the command did not validate",
        )
        return
    await _send_ack(
        websocket, TransportAck(command_id=command.command_id, ack_kind="parsed")
    )
    receipt = await dispatch(command, frame.get("payload"), session)
    if receipt is None:
        await _send_error(
            websocket,
            command.command_id,
            "command.unsupported",
            "unsupported",
            "no handler owns this command",
        )
        return
    if receipt.outcome != "accepted" and receipt.error is not None:
        await _send_error(
            websocket,
            command.command_id,
            receipt.error.code,
            receipt.error.category,
            receipt.error.safe_message,
        )
        return
    position = _accepted_position(receipt)
    if position is None:
        await _send_error(
            websocket,
            command.command_id,
            "internal.error",
            "internal",
            "the commit reported no stream position",
        )
        return
    await _send_ack(
        websocket,
        TransportAck(
            command_id=command.command_id,
            ack_kind="accepted",
            stream_position=position,
        ),
    )
    session.cursor = max(session.cursor, position.sequence)


async def serve_session(
    websocket: WebSocket,
    *,
    resolve_principal: ResolvePrincipal,
    dispatch: RealtimeDispatch,
    protocol_version: str,
    on_establish: Establish | None = None,
    on_open: OnOpen | None = None,
    on_game: OnGame | None = None,
) -> None:
    """Accept one connection, answer the handshake, and serve command frames.

    The handshake resolves the acting principal and reports the resume cursor the
    client asked for. ``on_establish`` runs first, before the handshake, to resume
    or open the session; the fields it returns join the handshake (for example a
    resume token the client stores and presents on its next connection).
    ``on_open`` then seeds the session (for example, presents the current
    activity). The loop reads one frame at a time until the client disconnects; a
    malformed or unknown frame answers a safe error and the loop continues. Queued
    deliveries flush after the handshake and after each command. When a command
    marks the session ready to run an activity, ``on_game`` takes the socket over
    for the stepping loop, then returns.
    """
    await websocket.accept()
    principal = resolve_principal(websocket)
    session = Session(principal, cursor=_resume_from(websocket))
    token = websocket.query_params.get("resume_token")
    if token is not None:
        session.state["resume_token"] = token
    ticket = websocket.query_params.get("ticket")
    if ticket is not None:
        session.state["ticket"] = ticket
    handshake_extra: dict[str, Any] = {}
    if on_establish is not None:
        try:
            handshake_extra = await on_establish(session)
        except SessionRejected as rejected:
            # A refused entry (for example, no valid launch ticket) answers a safe
            # error and closes, so no session runs behind a bad credential.
            await _send_error(
                websocket, None, rejected.code, rejected.category, rejected.safe_message
            )
            return
    await websocket.send_json(
        {
            "type": "handshake_ack",
            "protocol_version": protocol_version,
            # The establish hook may rebind the principal (a resumed enrollment),
            # so the handshake reports the session principal, not the provisional.
            "subject": session.principal.id,
            "resume_cursor": session.cursor,
            **handshake_extra,
        }
    )
    if on_open is not None:
        await on_open(session)
        await _flush(websocket, session)
    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return
        try:
            loaded: Any = json.loads(raw)
        except ValueError:
            await _send_error(
                websocket,
                None,
                "schema.validation_failed",
                "validation",
                "the frame was not valid json",
            )
            continue
        if not isinstance(loaded, dict):
            await _send_error(
                websocket,
                None,
                "protocol.unsupported_frame",
                "protocol",
                "a frame must be a json object",
            )
            continue
        frame = cast("dict[str, Any]", loaded)
        kind = frame.get("type")
        if kind == "command":
            await _handle_command(websocket, frame, dispatch, session)
            await _flush(websocket, session)
            if session.state.pop("run_game", False) and on_game is not None:
                await on_game(websocket, session)
                await _flush(websocket, session)
        elif kind == "input":
            # An input frame outside the stepping loop has no effect; the loop
            # reads its own input while it owns the socket.
            continue
        else:
            await _send_error(
                websocket,
                None,
                "protocol.unsupported_frame",
                "protocol",
                "unknown frame type",
            )
