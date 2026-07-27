"""Admission control: the bounds one process runs its realtime sessions under.

A study that runs for real meets load the tests never produce: more participants
than the process was sized for, a client that retries in a tight loop, a frame far
larger than any command. Without a bound, each of those spends memory and processor
time the process needs for the participants already playing, and the failure is the
worst kind -- everyone slows down together and nothing says why.

This module is the bound. It answers one question -- may this process do this work
now? -- and returns a ``Refusal`` when the answer is no. It decides nothing about
transport: the caller turns a refusal into whatever its transport says. The realtime
transport sends a safe error frame; the HTTP edge already maps the same categories
to a status.

The refusals reuse the contract's own vocabulary. ``backpressure`` says the process
is full, ``rate_limit`` says this connection is going too fast, and ``protocol`` says
the frame was not admissible; each carries the wait a client should respect, which
is the ``retry_after_ms`` of the kernel's retry directive. So nothing here is a new
error kind, and a client that already reads a domain error reads these.

The module holds no clock of its own beyond an injected monotonic reader, and no
entropy, so a test drives every bound with a hand-moved clock.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from mug.kernel.errors import ErrorCategory


@dataclass(frozen=True)
class Refusal:
    """One refused piece of work: why, and how long to wait before retrying.

    ``category`` is a contract error category, so a caller maps it with the table it
    already has. ``retry_after_ms`` is the wait a client should respect; it is None
    when waiting does not help.
    """

    code: str
    category: ErrorCategory
    message: str
    retry_after_ms: int | None = None


@dataclass(frozen=True)
class AdmissionPolicy:
    """The bounds one process runs under. Every field has a working default.

    The defaults are sized for one modest process serving one study: a few hundred
    participants at once, each sending commands at human speed. A deployment that
    knows its own numbers overrides them; nobody has to.

    ``max_frame_bytes`` bounds the frame this transport will *process*. The bytes
    themselves are read by the server below it, whose own websocket message limit is
    the memory bound (``uvicorn --ws-max-size``); this cap keeps a frame no command
    can be inside from reaching the parser and the handlers.
    """

    max_sessions: int = 512
    max_commands_per_second: float = 20.0
    command_burst: int = 40
    max_frame_bytes: int = 64 * 1024
    max_pending_deliveries: int = 256
    at_capacity_retry_after_ms: int = 5_000


class SessionOverloaded(Exception):
    """A session queued more deliveries than its budget allows.

    The queue drains to the client after every command and every activity, so
    reaching the bound means the work queued for one participant is running away.
    The transport closes such a session rather than grow without a limit: the
    participant reconnects with their resume cursor and carries on from the activity
    they were at, so the close costs a reconnection and nothing else.
    """


class TokenBucket:
    """Allow work at a steady rate, with a burst -- the shape of "N per second".

    The bucket refills by elapsed time, so it holds no timer and no task. ``take``
    spends one token and returns None; with no token left it returns the wait in
    milliseconds until the next one, which is what a client needs to be told.
    """

    def __init__(
        self,
        *,
        rate_per_second: float,
        burst: int,
        now: Callable[[], float],
    ) -> None:
        self._rate = rate_per_second
        self._burst = float(burst)
        self._now = now
        self._tokens = float(burst)
        self._last = now()

    def take(self) -> int | None:
        """Spend one token, or return the wait in milliseconds until the next."""
        moment = self._now()
        refilled = self._tokens + (moment - self._last) * self._rate
        self._tokens = min(self._burst, refilled)
        self._last = moment
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return None
        if self._rate <= 0:
            return None
        return max(1, int(((1.0 - self._tokens) / self._rate) * 1000))


class SessionBudget:
    """What one connection is allowed to spend, checked frame by frame.

    The transport asks before it does work, never after: a refused frame is never
    parsed and never dispatched, so a refusal costs the process almost nothing. That
    is the point of a bound -- refusing has to be cheaper than serving.
    """

    def __init__(self, policy: AdmissionPolicy, *, now: Callable[[], float]) -> None:
        self._policy = policy
        self._commands = TokenBucket(
            rate_per_second=policy.max_commands_per_second,
            burst=policy.command_burst,
            now=now,
        )

    @property
    def max_pending_deliveries(self) -> int:
        """The queued deliveries one session may hold before it is overloaded."""
        return self._policy.max_pending_deliveries

    def check_frame(self, size_bytes: int) -> Refusal | None:
        """Refuse a frame larger than any command needs to be."""
        if size_bytes <= self._policy.max_frame_bytes:
            return None
        return Refusal(
            code="transport.frame_too_large",
            category="protocol",
            message="the frame is larger than this transport accepts",
        )

    def check_command(self) -> Refusal | None:
        """Refuse a command this connection is sending faster than its rate."""
        wait = self._commands.take()
        if wait is None:
            return None
        return Refusal(
            code="transport.rate_limited",
            category="rate_limit",
            message="too many commands; retry after the stated wait",
            retry_after_ms=wait,
        )


class Admission:
    """The process-wide gate: how many sessions, and what each may spend.

    One instance is shared by every connection an application serves, so it is the
    place that knows how loaded the process is. ``open_sessions`` is that number,
    which is also the first thing an operator wants to read.

    A refused connection is told to come back: ``backpressure`` with a wait, the same
    answer the HTTP edge gives a caller when the process is full. Refusing at the
    door is what keeps the participants already playing unaffected.
    """

    def __init__(
        self,
        policy: AdmissionPolicy | None = None,
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policy = policy or AdmissionPolicy()
        self._now = now
        self._open = 0

    @property
    def policy(self) -> AdmissionPolicy:
        """The bounds this gate applies."""
        return self._policy

    @property
    def open_sessions(self) -> int:
        """How many sessions are open right now."""
        return self._open

    def admit(self) -> SessionBudget | Refusal:
        """Admit one connection and return its budget, or refuse it.

        The caller must ``release`` an admitted session, whichever way it ends, or
        the process leaks capacity until it refuses everybody.
        """
        if self._open >= self._policy.max_sessions:
            return Refusal(
                code="transport.at_capacity",
                category="backpressure",
                message="the server is at capacity; retry after the stated wait",
                retry_after_ms=self._policy.at_capacity_retry_after_ms,
            )
        self._open += 1
        return SessionBudget(self._policy, now=self._now)

    def release(self) -> None:
        """Give one admitted session's place back."""
        self._open = max(0, self._open - 1)


__all__ = [
    "Admission",
    "AdmissionPolicy",
    "Refusal",
    "SessionBudget",
    "SessionOverloaded",
    "TokenBucket",
]
