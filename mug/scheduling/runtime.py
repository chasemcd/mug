"""The scheduler runtime: turn one decision request into a recorded result (API-12).

The API-12 family (``mug.scheduling``) owns the decision records -- the
``DecisionRequest`` for one automated decision, the ``DecisionResult`` that carries
its outcome, the per-seat ``SchedulerState``, the ``ControllerPolicy`` and
``FallbackPolicy`` that govern an automated seat -- but adds no runtime. This module
is that runtime for the *server* execution mode: it awaits a bound controller under
the request deadline, classifies the outcome, applies the seat's fallback when the
decision misses the deadline or fails, and records the request and the result on
the shared command spine.

The scheduler is the hub, and it stays controller-agnostic. It awaits an injected
``AsyncController`` -- any async callable that maps an observation to a discrete
action -- so it drives an LLM seat, an asynchronous policy seat, and a tool-using
seat through one seam, with no knowledge of the provider behind it. A study
composes an LLM controller by wrapping ``mug.providers`` (render the observation to
a payload, call the model, parse the output to an action) and passes it here; the
scheduler never imports the provider. That composition lives above both families,
in the study, because the two families are siblings in the layer graph.

The bridge back to the game loop is the held-action seat. A person's input holds
the latest keypress and the loop samples it each frame; a scheduled seat holds the
latest decided action the same way. The scheduler decides off the frame clock and
applies the action to the seat (``mug.game.controllers.ScheduledSeat``); the loop
samples it synchronously through the same ``SeatActionSource`` seam, so a slow model
never blocks a fast frame.

The runtime is a producer boundary, so the caller injects the store, the clock, the
seat fallback, the default action, and a ``CommandContext`` factory that mints a
fresh context on the decision's stream. The peer-to-peer bot authority (a decision
that runs on a peer, not the server) stays deferred with the mesh phase; this slice
is server execution only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from mug.kernel import (
    CommandTypeRef,
    TypedObject,
    UtcInstant,
    compute_digest,
)
from mug.runtime import CommandContext, commit_command
from mug.scheduling.types import (
    DecisionRequest,
    DecisionResult,
    Fallback,
    FallbackRule,
)
from mug.storage import Store

# The observation is study-shaped, so the seam types it as ``Any`` (P0 duck-typing).
Observation = Any

_SUBMIT = CommandTypeRef(name="decision.submit", version=0)
_RESOLVE = CommandTypeRef(name="decision.resolve", version=0)

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"


@dataclass(frozen=True)
class DecisionContext:
    """What a bound async controller receives to decide one action.

    It carries the request (who, the deadline, the observation digest) and the raw
    observation the digest commits to, so the controller decides from the same
    state the scheduler recorded.
    """

    request: DecisionRequest
    observation: Observation


# An async controller maps a decision context to a discrete action. A study builds
# an LLM controller by composing ``mug.providers`` behind this seam.
AsyncController = Callable[[DecisionContext], Awaitable[int]]
NewContext = Callable[[str], CommandContext]


@dataclass(frozen=True)
class DecisionOutcome:
    """The scheduler's decision: the recorded result and the action the seat uses.

    ``action`` is the decided action when the result is produced, or the fallback
    action when the decision missed its deadline or failed. ``used_fallback`` says
    which, so the caller can distinguish a real decision from a filled-in one.
    """

    result: DecisionResult
    action: int
    used_fallback: bool
    replayed: bool = False


class Scheduler:
    """Drive one decision request to a recorded result, with a deadline fallback.

    The scheduler holds the injected impurity -- the store, the clock, the seat
    fallback rule, and the default action -- and exposes one operation. The caller
    passes a built ``DecisionRequest``, the raw observation, the bound controller,
    a context factory on the decision's stream, and the last applied action (for a
    ``repeat-last`` fallback).
    """

    def __init__(
        self,
        *,
        store: Store,
        now: Callable[[], datetime],
        fallback: FallbackRule,
        default_action: int = 0,
    ) -> None:
        self._store = store
        self._now = now
        self._fallback = fallback
        self._default_action = default_action

    async def decide(
        self,
        *,
        request: DecisionRequest,
        observation: Observation,
        controller: AsyncController,
        new_context: NewContext,
        last_action: int | None = None,
    ) -> DecisionOutcome:
        """Await the controller under the deadline and record the decision.

        The controller runs unless the deadline has already passed. A result that
        arrives before the deadline is produced and fresh; one that arrives late is
        timed out; a controller that raises is failed. A non-produced decision
        applies the seat's timeout fallback (``repeat-last`` reuses the last
        action, ``default-action`` uses the default), so the seat always has an
        action. The request is recorded before the controller runs, so a retry that
        finds a terminal head returns the recorded result without a second call.
        """
        decision_id = request.decision_id
        head = self._store.load_aggregate(decision_id)
        if head is not None and _is_terminal(head):
            result = DecisionResult.model_validate(head)
            action = self._fallback_action(self._fallback.on_timeout, last_action)
            return DecisionOutcome(
                result=result,
                action=action,
                used_fallback=result.outcome != "produced",
                replayed=True,
            )
        if head is None:
            await commit_command(
                new_context(decision_id),
                command=_SUBMIT,
                new_state=_state(request),
                result=_typed(request),
                store=self._store,
            )
        revision = self._store.revision_of(decision_id) or 0

        action, produced, failed = await self._run(request, observation, controller)
        if produced:
            applied, used_fallback = action, False
            result = self._produced(request, action)
        else:
            applied = self._fallback_action(self._fallback.on_timeout, last_action)
            used_fallback = True
            result = self._not_produced(request, failed)

        await commit_command(
            new_context(decision_id),
            command=_RESOLVE,
            new_state=_state(result),
            result=_typed(result),
            store=self._store,
            expected_revision=revision,
        )
        return DecisionOutcome(
            result=result, action=applied, used_fallback=used_fallback
        )

    # -- internals --------------------------------------------------------------

    async def _run(
        self,
        request: DecisionRequest,
        observation: Observation,
        controller: AsyncController,
    ) -> tuple[int, bool, bool]:
        """Run the controller under the deadline; return (action, produced, failed).

        The deadline is checked against the injected clock before and after the
        controller runs, so a late result is discarded. A controller that raises is
        reported as a failure, not a timeout.
        """
        deadline = _parse_instant(request.deadline)
        if self._now() >= deadline:
            return 0, False, False
        try:
            action = await controller(
                DecisionContext(request=request, observation=observation)
            )
        except Exception:
            return 0, False, True
        if self._now() >= deadline:
            return action, False, False
        return int(action), True, False

    def _produced(self, request: DecisionRequest, action: int) -> DecisionResult:
        """Build a produced, fresh decision result for the decided action."""
        return DecisionResult(
            decision_id=request.decision_id,
            execution_mode="server",
            outcome="produced",
            staleness="fresh",
            action_digest=compute_digest({"action": int(action)}),
            produced_at=self._instant(),
        )

    def _not_produced(self, request: DecisionRequest, failed: bool) -> DecisionResult:
        """Build a timed-out or failed decision result with no action digest."""
        return DecisionResult(
            decision_id=request.decision_id,
            execution_mode="server",
            outcome="failed" if failed else "timed-out",
            staleness="stale",
        )

    def _fallback_action(self, choice: Fallback, last_action: int | None) -> int:
        """Return the fallback action for a seat: repeat the last, or the default."""
        if choice == "repeat-last" and last_action is not None:
            return last_action
        return self._default_action

    def _instant(self) -> UtcInstant:
        """Return the current instant in the canonical wire form."""
        return self._now().astimezone(timezone.utc).strftime(_INSTANT)


def _state(record: DecisionRequest | DecisionResult) -> dict[str, Any]:
    """Dump one decision record to its canonical persisted form."""
    return record.model_dump(mode="json", exclude_none=True)


def _typed(record: DecisionRequest | DecisionResult) -> TypedObject:
    """Wrap one decision record as the command result that carries its schema."""
    return TypedObject(schema=record.schema, data=_state(record))


def _is_terminal(state: Any) -> bool:
    """Return whether an aggregate head is a recorded decision result."""
    if not isinstance(state, dict):
        return False
    schema = cast("dict[str, Any]", state).get("schema")
    if not isinstance(schema, dict):
        return False
    return cast("dict[str, Any]", schema).get("name") == "mug.api-12.decision-result"


def _parse_instant(text: str) -> datetime:
    """Parse a canonical UTC instant into a timezone-aware datetime."""
    return datetime.strptime(text, _INSTANT).replace(tzinfo=timezone.utc)


__all__ = [
    "AsyncController",
    "DecisionContext",
    "DecisionOutcome",
    "NewContext",
    "Observation",
    "Scheduler",
]
