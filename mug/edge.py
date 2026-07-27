"""The HTTP edge (layer L9): mint a context, dispatch, and serialize the receipt.

The edge is the only layer that speaks HTTP. It receives an untrusted
``WireCommandEnvelope``, resolves the caller principal from verified auth, and
asks the gateway to mint the trusted ``CommandContext``. It then routes the
command to its handler by command type, runs it, and answers with the
``CommandReceipt`` as JSON. A rejected receipt maps its error category to an HTTP
status. The edge never leaks provider traces, credentials, or input values; an
envelope that does not validate returns a generic, safe error.

Auth is a seam: ``authenticate`` derives the principal from the request. The wire
envelope never carries a principal, so a client can never claim one.

The edge is also where a request becomes observable. It reads the caller's W3C
``traceparent`` (or mints one), answers with it so the whole hop is one trace, counts
each command by its outcome, and writes one structured line naming the command, the
outcome, and the trace. None of that reaches a record: the telemetry sink defaults to
one that discards, and a trace is never persisted.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import NamedTuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from mug.authoring import PublishStudyCommand, publish_study
from mug.gateway import Gateway
from mug.identity import EnrollCommand, LaunchCommand, enroll, launch
from mug.kernel import CommandReceipt, PrincipalRef, WireCommandEnvelope
from mug.kernel._base import KernelModel
from mug.kernel.errors import ErrorCategory
from mug.kernel.privacy import DataHandlingRef
from mug.observability import (
    NullTelemetry,
    Telemetry,
    log_line,
    parse_traceparent,
    trace_id,
)
from mug.platform import DeployCommand, deploy
from mug.storage import Store
from mug.visits import (
    AdvanceVisitCommand,
    StartVisitCommand,
    advance_visit,
    start_visit,
)

_Handler = Callable[..., Awaitable[CommandReceipt]]
_Authenticate = Callable[[Request], PrincipalRef]


class _Route(NamedTuple):
    """One command surface: the input model, its handler, and its token flag."""

    model: type[KernelModel]
    handler: _Handler
    issue_handle: bool = False


# The command surface the edge exposes: command type -> route.
_ROUTES: dict[str, _Route] = {
    "study.publish": _Route(PublishStudyCommand, publish_study),
    "platform.deploy": _Route(DeployCommand, deploy),
    "enrollment.enroll": _Route(EnrollCommand, enroll),
    "launch.issue": _Route(LaunchCommand, launch, issue_handle=True),
    "visit.start": _Route(StartVisitCommand, start_visit),
    "visit.advance": _Route(AdvanceVisitCommand, advance_visit),
}

# The privacy classification the edge attaches to the event of a minted context.
_DATA_HANDLING = DataHandlingRef(privacy_labels=["research"])


class UnknownCommandType(Exception):
    """No route matches a command type."""


async def dispatch_command(
    command_type: str,
    envelope: WireCommandEnvelope,
    *,
    gateway: Gateway,
    store: Store,
    principal: PrincipalRef,
    data_handling: DataHandlingRef = _DATA_HANDLING,
) -> CommandReceipt:
    """Mint a context and run one command's handler over the shared route table.

    This is the single command path. The HTTP edge and the command-line front end
    both call it, so a command reaches its family the same way whatever the
    transport is. The caller validates the wire envelope and resolves the trusted
    principal; this function validates the payload against the routed model, asks
    the gateway to mint the trusted context, and runs the handler.

    It raises ``UnknownCommandType`` for a type with no route and a
    ``ValidationError`` for a payload that does not match the routed model, so the
    caller maps each to its own transport-level answer.
    """
    route = _ROUTES.get(command_type)
    if route is None:
        raise UnknownCommandType(command_type)
    command = route.model.model_validate(envelope.payload.data)
    context = gateway.mint(
        envelope,
        principal=principal,
        data_handling=data_handling,
        issue_handle=route.issue_handle,
    )
    return await route.handler(command, context=context, store=store)

# An error category maps to an HTTP status. An accepted receipt is always 200.
_STATUS: dict[ErrorCategory, int] = {
    "protocol": 400,
    "validation": 400,
    "authentication": 401,
    "authorization": 403,
    "not_found": 404,
    "conflict": 409,
    "stale": 409,
    "deadline": 504,
    "unsupported": 501,
    "rate_limit": 429,
    "backpressure": 503,
    "dependency": 502,
    "integrity": 422,
    "privacy": 403,
    "internal": 500,
}


def _safe_error(
    code: str,
    category: str,
    message: str,
    status: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Answer a transport-level failure with a minimal, safe error body."""
    return JSONResponse(
        {"outcome": "rejected", "code": code, "category": category, "message": message},
        status_code=status,
        headers=headers,
    )


def build_app(
    store: Store,
    *,
    gateway: Gateway,
    authenticate: _Authenticate,
    telemetry: Telemetry | None = None,
) -> FastAPI:
    """Build the edge over a store, a context gateway, and an auth resolver.

    ``telemetry`` is where the edge reports what it served. It defaults to a sink
    that discards, so a test and a script pay nothing; a deployment passes the
    process's own sink and reads the counts back from it.
    """
    sink: Telemetry = telemetry or NullTelemetry()

    app = FastAPI(title="MUG edge", version="0")

    @app.post("/commands/{command_type}")
    async def submit(  # pyright: ignore[reportUnusedFunction]
        command_type: str, request: Request
    ) -> JSONResponse:
        # One trace covers the whole hop: the caller's if it sent one, ours if not,
        # and the answer carries it back either way.
        trace = parse_traceparent(request.headers.get("traceparent")) or (
            gateway.new_trace()
        )
        headers = {"traceparent": trace.traceparent}

        def answer(code: str, category: str, message: str, status: int) -> JSONResponse:
            sink.count(
                "mug_edge_commands_total",
                command=command_type,
                outcome="rejected",
                category=category,
            )
            log_line(
                "edge.command",
                command=command_type,
                outcome="rejected",
                category=category,
                code=code,
                status=status,
                trace_id=trace_id(trace),
            )
            return _safe_error(code, category, message, status, headers)

        route = _ROUTES.get(command_type)
        if route is None:
            return answer(
                "resource.not_found", "not_found", "unknown command type", 404
            )
        try:
            principal = authenticate(request)
        except PermissionError:
            return answer(
                "auth.unauthenticated", "authentication", "authentication required", 401
            )
        try:
            envelope = WireCommandEnvelope.model_validate(await request.json())
            receipt = await dispatch_command(
                command_type,
                envelope,
                gateway=gateway,
                store=store,
                principal=principal,
            )
        except (ValidationError, KeyError, ValueError, UnknownCommandType):
            return answer(
                "schema.validation_failed",
                "validation",
                "the request did not validate",
                400,
            )
        status = 200
        category = "none"
        if receipt.outcome != "accepted" and receipt.error is not None:
            status = _STATUS.get(receipt.error.category, 400)
            category = receipt.error.category
        sink.count(
            "mug_edge_commands_total",
            command=command_type,
            outcome=receipt.outcome,
            category=category,
        )
        log_line(
            "edge.command",
            command=command_type,
            outcome=receipt.outcome,
            category=category,
            status=status,
            trace_id=trace_id(trace),
        )
        return JSONResponse(
            receipt.model_dump(mode="json", exclude_none=True),
            status_code=status,
            headers=headers,
        )

    return app
