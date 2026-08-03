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

An ``Admission`` bounds what the process accepts (``mug.admission``). It is checked
at the door and then before each frame, so a connection the process has no room for
is refused before it becomes a session, and a frame outside a session's budget is
refused before it is parsed or dispatched. The resume cursor is what makes a refusal
safe to answer with a close: the participant reconnects and carries on from the
activity they were at.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from starlette.websockets import WebSocketState

from mug.admission import Admission, Refusal, SessionBudget, SessionOverloaded
from mug.client import RealtimeCommand, TransportAck
from mug.kernel import CommandReceipt, PrincipalRef, StreamPosition
from mug.observability import NullTelemetry, Telemetry, log_line

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

# What runs when a connection ends, however it ends. It is where work a participant
# left unfinished is closed off: a browser game reports its run in parts while it is
# played, and a participant who shuts the tab mid-round never sends the last one. The
# hook is given the session so it can seal what did arrive. It must not touch the
# socket -- by the time it runs there is nothing to write to.
OnClose = Callable[["Session"], Awaitable[None]]
# Run a server-driven activity (for example, the game stepping loop) that takes
# the socket over, reads its own input frames, and pushes its own frames.
OnGame = Callable[[WebSocket, "Session"], Awaitable[None]]
# Judge one client quality sample against the study's screen. It answers the
# outcome frame to send the participant -- ``{"type": "screening", "action":
# "warn" | "exclude", "reason": ...}`` -- or None when nothing is to be said. The
# transport closes the connection on ``exclude``; what that costs the participant
# is already recorded by the time this returns.
OnMeasure = Callable[["Session", dict[str, Any]], Awaitable[dict[str, Any] | None]]


# How many unclaimed frames of one type the router holds, and how many types it
# holds them for. The bound is what keeps a client that sends a type nothing reads
# from growing the buffer without end.
_HELD_PER_TYPE = 32
_HELD_TYPES = 16


class FrameChannel:
    """The frames of the types one activity subscribed to, in arrival order.

    ``get`` answers the next frame, or None once the connection closed. An
    activity reads until it gets None, which is how it learns the participant
    went away without watching the socket itself.
    """

    def __init__(self, types: frozenset[str]) -> None:
        self.types = types
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def get(self) -> dict[str, Any] | None:
        """Return the next frame of a subscribed type, or None when closed."""
        return await self._queue.get()

    def offer(self, frame: dict[str, Any]) -> None:
        """Hand one frame to the activity waiting on this channel."""
        self._queue.put_nowait(frame)

    def close(self) -> None:
        """Wake the waiting activity with the end of the connection."""
        self._queue.put_nowait(None)


class FrameRouter:
    """Read one socket on behalf of every activity that shares it.

    A composed activity runs a game and a conversation over one connection, and
    both want to read frames. They must not each call ``receive_text``: two
    readers race for every frame and one of them wins at random, so a message
    lands in the game's reader and is never seen again. So one task reads, and
    each activity subscribes to the frame types it owns -- ``input`` for the
    stepping loop, ``chat`` for the room, ``interval_done`` for the interval.

    A frame that arrives before its activity subscribed is **held**, not dropped:
    a composed mount starts its panes one after the other, and a message the
    participant typed in that window must not vanish. The hold is bounded, so a
    client that sends a type nothing reads can not grow it without end.
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._channels: list[FrameChannel] = []
        self._held: dict[str, deque[dict[str, Any]]] = {}
        self._closed = False
        self._task: asyncio.Task[None] | None = None
        self.disconnected = False

    def subscribe(self, *types: str) -> FrameChannel:
        """Claim the named frame types, and take any that already arrived."""
        channel = FrameChannel(frozenset(types))
        self._channels.append(channel)
        for name in types:
            for frame in self._held.pop(name, ()):
                channel.offer(frame)
        if self._closed:
            channel.close()
        return channel

    async def run(self) -> None:
        """Read the socket until it closes, handing each frame to its channel."""
        try:
            while True:
                raw = await self._websocket.receive_text()
                loaded: Any = json.loads(raw)
                if isinstance(loaded, dict):
                    self._route(cast("dict[str, Any]", loaded))
        except (WebSocketDisconnect, RuntimeError):
            self.disconnected = True
        except ValueError:
            # A frame that is not JSON ends this activity's reading rather than
            # the connection: the session loop answers a safe error for a bad
            # command, and an activity frame gets the same treatment.
            self.disconnected = True
        finally:
            self.close()

    def close(self) -> None:
        """Close every channel, so each activity reading one wakes and stops."""
        self._closed = True
        for channel in self._channels:
            channel.close()

    async def __aenter__(self) -> FrameRouter:
        """Start reading the socket for every activity that shares it."""
        self._task = asyncio.create_task(self.run())
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Stop reading, and wake every activity still waiting on a frame."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.close()

    def _route(self, frame: dict[str, Any]) -> None:
        """Give one frame to the channel that claimed its type, or hold it."""
        name = frame.get("type")
        if not isinstance(name, str):
            return
        for channel in self._channels:
            if name in channel.types:
                channel.offer(frame)
                return
        held: deque[dict[str, Any]] | None = self._held.get(name)
        if held is None:
            if len(self._held) >= _HELD_TYPES:
                return
            held = deque(maxlen=_HELD_PER_TYPE)
            self._held[name] = held
        held.append(frame)


def read_frames(websocket: WebSocket) -> FrameRouter:
    """Share one socket for the body of an ``async with``, and stop after it.

    The reading task belongs to the router, so no reader outlives the activity
    that started it: leaving the block cancels it and wakes every pane still
    waiting on a frame.
    """
    return FrameRouter(websocket)


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

    The queue is bounded. It drains after every command and every activity, so one
    participant holds a handful of frames at most; a queue that reaches the bound is
    work running away, and ``deliver`` raises ``SessionOverloaded`` rather than let
    one connection grow without a limit.
    """

    def __init__(
        self,
        principal: PrincipalRef,
        *,
        cursor: int = 0,
        max_pending_deliveries: int | None = None,
    ) -> None:
        self.principal = principal
        self.cursor = cursor
        self.state: dict[str, Any] = {}
        self.outbox: list[dict[str, Any]] = []
        self.max_pending_deliveries = max_pending_deliveries

    def deliver(self, delivery: dict[str, Any]) -> None:
        """Queue one delivery payload for the next flush to the client."""
        bound = self.max_pending_deliveries
        if bound is not None and len(self.outbox) >= bound:
            raise SessionOverloaded(f"more than {bound} deliveries are queued")
        self.outbox.append(delivery)


def _deployment_mismatch(session: Session, frame: dict[str, Any]) -> str | None:
    """Return why a client's pinned deployment is refused, or None when it holds.

    The session knows the revision it is serving, because ``on_establish`` put it
    there. A client that pins that revision continues; a client that pins another
    one is running a build for a deployment this process no longer serves, and it is
    told so rather than left to behave as though it were current. A client that pins
    nothing is an older client and is let through -- refusing it would break every
    client that predates this frame.
    """
    serving = session.state.get("deployment_revision_id")
    if not isinstance(serving, str):
        return None
    accepted = frame.get("accepted_deployment")
    if not isinstance(accepted, dict):
        return None
    pinned = cast("dict[str, Any]", accepted).get("deployment_revision_id")
    if not isinstance(pinned, str) or pinned == serving:
        return None
    return "this client was built for a deployment revision that is not current"


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
    retry_after_ms: int | None = None,
) -> None:
    """Send one safe error frame; it carries no trace and no input value.

    ``retry_after_ms`` joins the frame only when waiting is the right answer (a rate
    limit, a full server), so a client is told when to come back instead of guessing.
    """
    frame: dict[str, Any] = {
        "type": "error",
        "command_id": command_id,
        "code": code,
        "category": category,
        "message": message,
    }
    if retry_after_ms is not None:
        frame["retry_after_ms"] = retry_after_ms
    await websocket.send_json(frame)


async def _send_refusal(
    websocket: WebSocket, command_id: str | None, refusal: Refusal
) -> None:
    """Send one admission refusal as a safe error frame."""
    await _send_error(
        websocket,
        command_id,
        refusal.code,
        refusal.category,
        refusal.message,
        refusal.retry_after_ms,
    )


def _command_id(frame: dict[str, Any]) -> str | None:
    """Read the command id off an unvalidated frame, so a refusal can name it.

    The frame is untrusted, so the id is used for correlation only; a value that is
    not a string is reported as no id rather than echoed back.
    """
    command = frame.get("command")
    if not isinstance(command, dict):
        return None
    command_id = cast("dict[str, Any]", command).get("command_id")
    return command_id if isinstance(command_id, str) else None


async def _screen(
    websocket: WebSocket,
    session: Session,
    frame: dict[str, Any],
    on_measure: OnMeasure | None,
) -> bool:
    """Judge one quality sample and answer it. Returns False to end the session.

    A warning is pushed and the session carries on. An exclusion is pushed as a safe
    error and the connection closes: the participant is told they were excluded and
    why, and the decision is already durable, so a reconnection meets it rather than
    starting clean.
    """
    if on_measure is None:
        return True
    outcome = await on_measure(session, frame)
    if outcome is None:
        return True
    if outcome.get("action") == "exclude":
        reason = outcome.get("reason")
        await _send_error(
            websocket,
            None,
            "policy.excluded",
            "policy",
            reason if isinstance(reason, str) else "this session was excluded",
        )
        return False
    await websocket.send_json({"type": "screening", **outcome})
    return True


async def _flush(websocket: WebSocket, session: Session) -> None:
    """Push every queued delivery to the client, oldest first."""
    while session.outbox:
        await websocket.send_json(
            {"type": "delivery", "delivery": session.outbox.pop(0)}
        )


async def _run_ready_activities(
    websocket: WebSocket, session: Session, on_game: OnGame | None
) -> bool:
    """Run each activity that takes the socket over, until one waits for input.

    A study may put two of them in a row -- a practice round and then the real
    one -- and the hook that runs the first advances the flow onto the second.
    Returning to the frame loop there would leave the participant on a socket with
    nothing to send, because a game activity is not a form: nothing else is coming
    to start it.

    Returns False when the participant went away inside a hook, so the caller
    stops rather than read or write a socket that already closed.
    """
    while session.state.pop("run_game", False) and on_game is not None:
        await on_game(websocket, session)
        if websocket.client_state is not WebSocketState.CONNECTED:
            return False
        await _flush(websocket, session)
    return True


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
    on_measure: OnMeasure | None = None,
    on_close: OnClose | None = None,
    admission: Admission | None = None,
    telemetry: Telemetry | None = None,
) -> None:
    """Admit one connection, answer the handshake, and serve command frames.

    ``admission`` is the process's own bound (``mug.admission``). A connection the
    process has no room for is refused at the door, before it becomes a session and
    before any hook runs, and told when to come back; an admitted one gets a budget
    that the frame loop checks. The place is given back however the session ends. With
    no admission passed the session is unbounded, which is what a test wants.

    ``telemetry`` is where the transport reports how many sessions are open and what
    it refused. It defaults to a sink that discards.

    ``on_close`` runs when the connection ends, whichever way it ends, and is where
    a participant's unfinished work is closed off. A browser game is reported in
    parts while it is played, so a participant who shuts the tab mid-round leaves a
    run nobody closed; the hook is what turns that into the frames they did play
    rather than nothing. It runs after the socket is gone, so it must not write to
    it, and a failure in it must not lose the connection's place.

    The handshake resolves the acting principal and reports the resume cursor the
    client asked for. ``on_establish`` runs first, before the handshake, to resume
    or open the session; the fields it returns join the handshake (for example a
    resume token the client stores and presents on its next connection).
    ``on_open`` then seeds the session (for example, presents the current
    activity). The loop reads one frame at a time until the client disconnects; a
    malformed, oversized, over-rate, or unknown frame answers a safe error and the
    loop continues. Queued deliveries flush after the handshake and after each
    command. When a command marks the session ready to run an activity, ``on_game``
    takes the socket over for the stepping loop, then returns.
    """
    sink: Telemetry = telemetry or NullTelemetry()
    await websocket.accept()
    opened: list[Session] = []
    budget: SessionBudget | None = None
    if admission is not None:
        admitted = admission.admit()
        if isinstance(admitted, Refusal):
            _report(sink, admission, refused=admitted.category)
            log_line("realtime.refused", code=admitted.code)
            await _send_refusal(websocket, None, admitted)
            return
        budget = admitted
        _report(sink, admission)
    try:
        await _serve_admitted(
            websocket,
            budget=budget,
            sink=sink,
            resolve_principal=resolve_principal,
            dispatch=dispatch,
            protocol_version=protocol_version,
            on_establish=on_establish,
            on_open=on_open,
            on_game=on_game,
            on_measure=on_measure,
            started=opened.append,
        )
    except SessionOverloaded:
        # The work queued for one participant ran away. Close rather than grow: the
        # resume cursor brings them back to the activity they were at.
        _report(sink, admission, refused="backpressure")
        log_line("realtime.refused", code="transport.session_overloaded")
        await _send_error(
            websocket,
            None,
            "transport.session_overloaded",
            "backpressure",
            "too much is queued for this connection; reconnect to resume",
        )
    finally:
        if admission is not None and budget is not None:
            admission.release()
            _report(sink, admission)
        if on_close is not None and opened:
            # However the connection ended. A participant who shut the tab
            # mid-round is exactly the case this exists for, and that arrives here
            # as a disconnect rather than as anything the client said.
            await on_close(opened[0])


def _report(
    sink: Telemetry, admission: Admission | None, *, refused: str | None = None
) -> None:
    """Report the open-session level, and count a refusal by its category.

    The level is the first number an operator reads, and the refusal count is the
    first sign a process is at its bound rather than merely busy.
    """
    if admission is not None:
        sink.gauge("mug_realtime_open_sessions", admission.open_sessions)
    if refused is not None:
        sink.count("mug_realtime_refused_total", category=refused)


async def _serve_admitted(
    websocket: WebSocket,
    *,
    budget: SessionBudget | None,
    sink: Telemetry,
    resolve_principal: ResolvePrincipal,
    dispatch: RealtimeDispatch,
    protocol_version: str,
    on_establish: Establish | None,
    on_open: OnOpen | None,
    on_game: OnGame | None,
    on_measure: OnMeasure | None = None,
    started: Callable[[Session], None] | None = None,
) -> None:
    """Serve one admitted connection: handshake, then the frame loop.

    ``started`` is told the session as soon as there is one, so the caller can close
    it off however the connection ends -- including by an exception, which is the
    case a hook called at the end of this function would miss.
    """
    principal = resolve_principal(websocket)
    session = Session(
        principal,
        cursor=_resume_from(websocket),
        max_pending_deliveries=(
            budget.max_pending_deliveries if budget is not None else None
        ),
    )
    if started is not None:
        started(session)
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
        # The opening activity may be the game itself: a study is free to put it
        # first, and a reconnection resumes wherever the participant stopped,
        # which may also be the game. Waiting for a command before running it
        # would leave that participant on a socket with nothing to send.
        if not await _run_ready_activities(websocket, session, on_game):
            return
    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return
        if budget is not None:
            oversized = budget.check_frame(len(raw))
            if oversized is not None:
                # Refused before it is parsed: a bound has to be cheaper than the
                # work it refuses, or it is not a bound.
                sink.count("mug_realtime_refused_total", category=oversized.category)
                await _send_refusal(websocket, None, oversized)
                continue
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
            if budget is not None:
                throttled = budget.check_command()
                if throttled is not None:
                    # Refused before it is dispatched, so the command has no effect
                    # and the client may safely retry the same one after the wait.
                    sink.count(
                        "mug_realtime_refused_total", category=throttled.category
                    )
                    await _send_refusal(websocket, _command_id(frame), throttled)
                    continue
            await _handle_command(websocket, frame, dispatch, session)
            await _flush(websocket, session)
            # A game hook owns the socket while it runs, so the participant can go
            # away inside it. The loop must not read or write a socket that
            # already closed: that raises rather than ending cleanly.
            if not await _run_ready_activities(websocket, session, on_game):
                return
        elif kind == "input":
            # An input frame outside the stepping loop has no effect; the loop
            # reads its own input while it owns the socket.
            continue
        elif kind == "client_handshake":
            # The client states which deployment revision it believes it is running
            # against. A client built for a superseded revision must not go on
            # quietly: it is refused here and the connection ends. The refusal comes
            # after the opening activity has already been delivered -- the server
            # speaks first -- so a stale client may see one screen. What it never
            # does is submit a command against a deployment it was not built for.
            refusal = _deployment_mismatch(session, frame)
            if refusal is not None:
                await _send_error(
                    websocket,
                    None,
                    "command.state_conflict",
                    "conflict",
                    refusal,
                )
                return
            # The same frame carries the client's own capability evidence, so entry
            # screening reads it before any command is accepted.
            if not await _screen(websocket, session, frame, on_measure):
                return
        elif kind == "ping":
            # The round trip a screen measures needs something to bounce off. The
            # reply carries the client's own token back and nothing else, so a ping
            # costs one frame and reveals nothing about anyone.
            await websocket.send_json({"type": "pong", "token": frame.get("token")})
        elif kind == "measurement":
            if not await _screen(websocket, session, frame, on_measure):
                return
        else:
            await _send_error(
                websocket,
                None,
                "protocol.unsupported_frame",
                "protocol",
                "unknown frame type",
            )
