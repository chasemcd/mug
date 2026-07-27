"""Decide whether one visit may enter, and record why (API-04, RP-10).

Eligibility is enforced at the flow, not the wave (ADR-0014): a study names a
server-side rule, the platform evaluates it before the participant is admitted, and
the decision is canonical evidence. ``EligibilityCallback`` is the frozen record
that says which rule was declared, and ``VisitPlan.eligibility`` is where the plan
carries it.

Three things are worth stating plainly.

**The rule runs on the server.** A browser can claim anything, so a screen a client
enforces is not a screen. The study writes a plain function, the platform calls it,
and the participant's client is told the outcome and nothing else.

**The default is fail-closed.** A rule that raises refuses entry, unless the study
explicitly writes ``on_error="fail_open"``. Silently admitting everyone when the
screen is broken is the failure this default exists to prevent -- and it is the same
vocabulary API-06 uses for its monitoring callback, on purpose.

**A refusal has a reason and the reason is recorded.** A rule returns True to admit,
or a short reason string to refuse; the reason reaches the participant and the
ledger. "Refused" with no reason is an unanswerable support ticket.

The rule is addressed by qualified name in the record, so it must be a module-level
function. The study injects the function itself, so core carries no study logic
(the rule lives in the study's own repository), and the record carries the name, so
an analysis a year later can find what was run.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from mug.kernel import CommandTypeRef, TypedObject, compute_digest
from mug.runtime import CommandContext, commit_command
from mug.storage import Store
from mug.visits.types import EligibilityCallback

_DECIDE = CommandTypeRef(name="eligibility.decide", version=0)

# Derive an identifier of a registered kind from a stable seed (the gateway).
Derive = Callable[[str, str], str]


@dataclass(frozen=True)
class Entry:
    """What the server knows about a connection when it decides to admit it.

    ``metrics`` is the client capability evidence: each quality metric the client
    measured, in whole microseconds (``rtt``, ``hidden``). It is empty when the
    client sent none, which is itself something a strict rule may refuse on.
    """

    visit_id: str
    study_version_id: str
    metrics: Mapping[str, int]


# The study's own screening rule. It returns True to admit, or a short reason to
# refuse; False refuses with a default reason.
EligibilityRule = Callable[[Entry], "bool | str"]


@dataclass(frozen=True)
class Decision:
    """The outcome of one entry decision: admitted or not, and why."""

    admitted: bool
    reason: str


def rule_name(rule: EligibilityRule) -> str:
    """Return the ``module:attribute`` name the record addresses a rule by.

    A rule with no addressable name -- a lambda, or a function defined inside
    another function -- is refused here rather than recorded as something that
    cannot be found again.
    """
    module = getattr(rule, "__module__", "")
    qualname = getattr(rule, "__qualname__", "")
    if not module or not qualname or "<" in qualname:
        raise ValueError("an eligibility rule must be a module-level function")
    return f"{module}:{qualname}"


def callback_for(
    rule: EligibilityRule,
    *,
    flow_node_id: str,
    rule_key: str = "entry",
    on_error: str = "fail_closed",
) -> EligibilityCallback:
    """Return the frozen declaration of one rule, evaluated at one flow node."""
    return EligibilityCallback(
        flow_node_id=flow_node_id,  # pyright: ignore[reportArgumentType]
        rule_key=rule_key,  # pyright: ignore[reportArgumentType]
        callback=rule_name(rule),  # pyright: ignore[reportArgumentType]
        on_error=on_error,  # pyright: ignore[reportArgumentType]
    )


def entry_node_id(derive: Derive, study_version_id: str) -> str:
    """Return the flow node an entry rule is evaluated at.

    Entry is one node of the flow for the whole study version, so the identifier
    derives from the version: two visits of one study name the same node, and two
    versions name two.
    """
    return derive("flownode", f"entry:{study_version_id}")


def eligibility_id_for(derive: Derive, visit_id: str) -> str:
    """Return the aggregate that holds one visit's entry decision.

    It derives from the visit, so a participant who reconnects meets the decision
    already made about them rather than a second evaluation with a second answer.
    """
    return derive("visit", f"eligibility:{visit_id}")


def decide(
    rule: EligibilityRule, entry: Entry, *, on_error: str = "fail_closed"
) -> Decision:
    """Evaluate one rule against one connection, and never raise.

    A rule that raises is the case this function exists for: the outcome is a
    refusal under ``fail_closed`` and an admission under ``fail_open``, and either
    way the reason says the rule failed rather than pretending it answered.
    """
    try:
        answer = rule(entry)
    except Exception:
        if on_error == "fail_open":
            return Decision(admitted=True, reason="the eligibility rule failed to run")
        return Decision(admitted=False, reason="the eligibility rule failed to run")
    if answer is True:
        return Decision(admitted=True, reason="eligible")
    if isinstance(answer, str) and answer.strip():
        return Decision(admitted=False, reason=answer.strip()[:200])
    return Decision(admitted=False, reason="this study is not open to you")


def bounds_decision(bounds: Mapping[str, int], metrics: Mapping[str, int]) -> Decision:
    """Refuse entry when the client's own evidence is already over a bound.

    This is the latency screen, and it reads the same numbers the in-play ladder
    reads. A metric the client did not measure is not a refusal: the server screens
    what it was told, and a client that reports nothing is judged in play instead.
    """
    for metric in sorted(bounds):
        observed = metrics.get(metric)
        if isinstance(observed, int) and observed > bounds[metric]:
            return Decision(
                admitted=False,
                reason=f"this study needs a better connection ({metric})",
            )
    return Decision(admitted=True, reason="eligible")


def read_decision(store: Store, eligibility_id: str) -> Decision | None:
    """Return the decision already recorded for one visit, or None for none."""
    raw = store.load_aggregate(eligibility_id)
    if not isinstance(raw, Mapping):
        return None
    body = cast("Mapping[str, Any]", raw)
    admitted = body.get("admitted")
    reason = body.get("reason")
    if not isinstance(admitted, bool) or not isinstance(reason, str):
        return None
    return Decision(admitted=admitted, reason=reason)


async def record_decision(
    *,
    eligibility_id: str,
    visit_id: str,
    decision: Decision,
    callbacks: Sequence[EligibilityCallback],
    metrics: Mapping[str, int],
    decided_at: str,
    context: CommandContext,
    store: Store,
) -> bool:
    """Commit one entry decision, with the rules it was made under.

    The declaration is written beside the outcome so the record answers both
    questions at once: what was decided, and what it was decided by. A repeated
    decision is refused by the store, which is the correct answer -- the first one
    stands.
    """
    state: dict[str, Any] = {
        "visit_id": visit_id,
        "admitted": decision.admitted,
        "reason": decision.reason,
        "eligibility": [
            one.model_dump(mode="json", exclude_none=True) for one in callbacks
        ],
        "metrics": dict(sorted(metrics.items())),
        "evidence_digest": compute_digest(dict(sorted(metrics.items()))).model_dump(
            mode="json"
        ),
        "decided_at": decided_at,
    }
    schema = callbacks[0].schema if callbacks else None
    receipt = await commit_command(
        context,
        command=_DECIDE,
        new_state=state,
        result=TypedObject(
            schema=schema or _callback_schema(),
            data={
                "outcome": "admitted" if decision.admitted else "refused",
                "visit_id": visit_id,
                "reason": decision.reason,
            },
        ),
        store=store,
    )
    return receipt.outcome == "accepted"


def _callback_schema() -> Any:
    """Return the API-04 reference a decision with no declared rule is typed by."""
    return EligibilityCallback(
        flow_node_id="flownode_00000000-0000-7000-8000-000000000000",
        rule_key="entry",
        callback="mug.visits.eligibility:bounds_decision",
    ).schema


__all__ = [
    "Decision",
    "EligibilityRule",
    "Entry",
    "bounds_decision",
    "callback_for",
    "decide",
    "eligibility_id_for",
    "entry_node_id",
    "read_decision",
    "record_decision",
    "rule_name",
]
