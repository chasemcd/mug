"""Screen a connection while it plays: measure, compare, escalate, and record.

API-06 declares the policy -- the bounds, the warn-then-exclude ladder, and the
researcher callback -- and API-09 declares the sample a client sends. Neither
declared what compares one to the other, so a study could state a latency bound
that nothing enforced. This module is that comparison, and it is deliberately
server-authoritative: the client reports what it measured, and the server alone
decides what the measurement costs the participant.

The module is two halves, the same shape as ``mug.visits.assignment``.

The **pure half** decides. ``over_bounds`` names the metrics a sample breaks and
``action_at`` reads the ladder. Neither touches a clock, a store, or the network,
so a test states the bound, the sample, and the count, and the answer follows.

The **durable half** records. One aggregate holds the running screening of one
actor: how many times they have been over, what the ladder did about it, and the
last measurement as it arrived. It is derived from the interaction and the actor,
so a participant who reconnects carries their violation count with them rather
than starting clean -- a screening that a refresh resets is not a screening.

**Warn is not exclude.** A participant over the bound once is told; a participant
over it repeatedly is excluded. Both are recorded, because an analysis needs to
know a session was degraded even when it was allowed to finish.

**The researcher callback is fail-closed by default** (the same rule and the same
vocabulary as an API-04 eligibility callback). A hook that raises excludes the
participant unless the study explicitly asked for ``fail_open``; a study that
screens on a rule it cannot evaluate must not quietly keep everybody.

**One identifier note.** The registry names no monitoring kind. The screening of
one actor in one interaction is a runtime occurrence of API-06, so it takes
``interaction`` -- the kind that describes it -- with the actor in the derivation
seed. Inventing a prefix would break a frozen registry.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Final, Literal

from pydantic import Field

from mug.interactions.types import (
    MonitoringCallback,
    MonitoringLadderStep,
    MonitoringPolicy,
    interactions_schema,
)
from mug.kernel import (
    CommandTypeRef,
    Digest,
    Duration,
    SchemaRef,
    TypedObject,
    UtcInstant,
    VersionStamp,
    etag,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import ActorInstanceId, InteractionId, VisitId
from mug.kernel.refs import NonNegativeSafeInteger
from mug.runtime import CommandContext, commit_command
from mug.storage import Store

# The two client quality metrics API-09 names. A sample of anything else is not a
# measurement this platform knows how to judge, so it is dropped rather than
# guessed at.
METRICS: Final[tuple[str, ...]] = ("rtt", "hidden")

_SCREEN = CommandTypeRef(name="monitoring.screen", version=0)

# Derive one actor's screening aggregate. The kind is API-06's runtime occurrence.
Derive = Callable[[str, str], str]

# Build the readiness gate op one ladder action raises, or None for none. API-09
# owns the gate op and this layer may not import it, so the caller supplies it.
GateFor = Callable[[str], "Mapping[str, Any] | None"]


def monitoring_id_for(derive: Derive, interaction_id: str, actor_id: str) -> str:
    """Return the aggregate that holds one actor's screening in one interaction."""
    return derive("interaction", f"monitoring:{interaction_id}:{actor_id}")


@dataclass(frozen=True)
class Screen:
    """What a study declares about the connection quality it needs.

    An author writes it once, on the study, and the platform does the rest::

        Study(Form("consent", ...), Game("play"),
              screen=Screen(max_rtt_ms=250, exclude_after=3))

    ``max_rtt_ms`` bounds the round trip between the browser and the server, and
    ``max_hidden_ms`` bounds how long the page may be in the background. A sample
    over either bound is one violation. ``warn_after`` violations tell the
    participant; ``exclude_after`` violations end the session.

    ``at_entry`` also screens the first sample, which the client sends with its
    handshake: a participant whose connection is already over the bound is refused
    entry rather than admitted and then excluded a minute later.
    ``sample_every_ms`` is how often the client measures again while it plays.

    ``on_violation`` is the study's own hook, run server-side as an actor crosses a
    rung. It must be a module-level function, because the record addresses it by
    qualified name and a name is what makes it findable later. It is fail-closed:
    a hook that raises excludes the participant, unless the study writes
    ``on_error="fail_open"``.
    """

    max_rtt_ms: int = 400
    max_hidden_ms: int = 15_000
    warn_after: int = 2
    exclude_after: int = 4
    at_entry: bool = True
    sample_every_ms: int = 10_000
    on_violation: Callable[..., Any] | None = None
    on_error: Literal["fail_closed", "fail_open"] = "fail_closed"

    def __post_init__(self) -> None:
        if self.max_rtt_ms <= 0 or self.max_hidden_ms <= 0:
            raise ValueError("a screening bound must be a positive number of ms")
        if self.sample_every_ms < 1000:
            raise ValueError("a screen samples at most once a second")
        if self.warn_after < 1:
            raise ValueError("a screen warns after at least one violation")
        if self.exclude_after <= self.warn_after:
            raise ValueError("a screen excludes after more violations than it warns")
        if self.on_violation is not None:
            # Built here rather than at first use, so a hook that can never be
            # addressed is refused while the author is still reading their own code.
            handler_name(self.on_violation)

    def bounds(self) -> dict[str, int]:
        """Return the microsecond bound of each metric, keyed by metric name."""
        return {
            "rtt": self.max_rtt_ms * 1000,
            "hidden": self.max_hidden_ms * 1000,
        }

    def policy(self) -> MonitoringPolicy:
        """Return the frozen API-06 policy this declaration means."""
        callback = (
            None
            if self.on_violation is None
            else MonitoringCallback(
                handler=handler_name(self.on_violation), on_error=self.on_error
            )
        )
        return MonitoringPolicy(
            enforcement="server-authoritative",
            max_rtt=Duration(microseconds=self.max_rtt_ms * 1000),
            max_hidden=Duration(microseconds=self.max_hidden_ms * 1000),
            ladder=[
                MonitoringLadderStep(at_violations=self.warn_after, action="warn"),
                MonitoringLadderStep(
                    at_violations=self.exclude_after, action="exclude"
                ),
            ],
            callback=callback,
        )


def handler_name(hook: Callable[..., Any]) -> str:
    """Return the dotted qualified name of a researcher hook.

    A record addresses a callback by name, so a hook with no addressable name is
    refused here rather than recorded as something that cannot be found again. A
    lambda and a function defined inside another function are both unaddressable.
    """
    name = f"{getattr(hook, '__module__', '')}.{getattr(hook, '__qualname__', '')}"
    if "<" in name or not name.strip("."):
        raise ValueError("a monitoring callback must be a module-level function")
    return name


def over_bounds(
    policy: MonitoringPolicy, samples: Mapping[str, int]
) -> tuple[str, ...]:
    """Return the metrics this sample breaks, in the order API-09 names them.

    A metric the policy does not bound, and a sample that is not a whole number of
    microseconds, are both ignored: the server judges what it declared and nothing
    else.
    """
    bounds = {
        "rtt": policy.max_rtt.microseconds,
        "hidden": policy.max_hidden.microseconds,
    }
    return tuple(
        metric
        for metric in METRICS
        if isinstance(samples.get(metric), int) and samples[metric] > bounds[metric]
    )


def action_at(policy: MonitoringPolicy, violations: int) -> str | None:
    """Return the ladder action at this many violations, or None for none yet.

    The ladder rises, so the highest rung the count has reached is the one that
    applies: a participant at the exclude count is excluded, not warned again.
    """
    reached = [step for step in policy.ladder if violations >= step.at_violations]
    return reached[-1].action if reached else None


def callback_action(policy: MonitoringPolicy, run: Callable[[], Any]) -> str | None:
    """Run the researcher hook and return the action its failure implies.

    The hook observes; it does not decide. What it decides is what happens when it
    *cannot* run: a fail-closed callback that raises excludes the participant, and a
    fail-open one lets them carry on. That is the whole reason the record carries
    ``on_error``.
    """
    if policy.callback is None:
        return None
    try:
        run()
    except Exception:
        return "exclude" if policy.callback.on_error == "fail_closed" else None
    return None


class ScreeningState(KernelModel):
    """The running screening of one actor: what was measured, and what it cost.

    ``measurement`` is the API-09 record as it arrived, so the evidence that a
    decision was made on is kept beside the decision rather than reconstructed from
    it. ``violations`` counts across the whole interaction, not one connection: a
    participant who reconnects carries their count.

    ``gate`` is the readiness op an exclusion raises. Excluding a participant is
    blocking them from advancing, so the block is written as the gate op that says
    so rather than left implicit in a status word.
    """

    interaction_id: InteractionId
    actor_id: ActorInstanceId
    visit_id: VisitId
    policy: MonitoringPolicy
    violations: NonNegativeSafeInteger
    action: Literal["warn", "exclude"] | None = None
    over: Annotated[list[str], Field(max_length=8)] = Field(default_factory=list)
    measurement: dict[str, Any] = Field(default_factory=dict)
    gate: dict[str, Any] | None = None
    measured_at: UtcInstant
    version: VersionStamp


def read_screening(store: Store, monitoring_id: str) -> ScreeningState | None:
    """Return one actor's committed screening state, or None when it has none."""
    raw = store.load_aggregate(monitoring_id)
    if not isinstance(raw, Mapping):
        return None
    try:
        return ScreeningState.model_validate(raw)
    except ValueError:
        return None


def next_screening(
    current: ScreeningState | None,
    *,
    interaction_id: str,
    actor_id: str,
    visit_id: str,
    policy: MonitoringPolicy,
    measurement: Mapping[str, Any],
    over: Sequence[str],
    measured_at: str,
    gate_for: GateFor | None = None,
) -> ScreeningState:
    """Return the screening state one more measurement leaves the actor in."""
    violations = (current.violations if current is not None else 0) + (1 if over else 0)
    action = action_at(policy, violations)
    gate = None if action is None or gate_for is None else gate_for(action)
    body: dict[str, Any] = {
        "interaction_id": interaction_id,
        "actor_id": actor_id,
        "visit_id": visit_id,
        "policy": policy.model_dump(mode="json", exclude_none=True),
        "violations": violations,
        "action": action,
        "over": list(over),
        "measurement": dict(measurement),
        "gate": None if gate is None else dict(gate),
        "measured_at": measured_at,
    }
    revision = current.version.revision + 1 if current is not None else 1
    return ScreeningState(
        **body,  # pyright: ignore[reportArgumentType]
        version=VersionStamp(revision=revision, etag=etag(body)),
    )


async def record_screening(
    *,
    monitoring_id: str,
    interaction_id: str,
    actor_id: str,
    visit_id: str,
    policy: MonitoringPolicy,
    measurement: Mapping[str, Any],
    over: Sequence[str],
    measured_at: str,
    gate_for: GateFor | None = None,
    context: CommandContext,
    store: Store,
) -> ScreeningState | None:
    """Commit what one measurement did to one actor, and return the new state.

    Returns None when the commit is refused, and the caller then applies nothing:
    an exclusion the ledger did not take is an exclusion that a reconnection would
    not remember, and acting on it would end a session for a reason no record
    holds.
    """
    current = read_screening(store, monitoring_id)
    updated = next_screening(
        current,
        interaction_id=interaction_id,
        actor_id=actor_id,
        visit_id=visit_id,
        policy=policy,
        measurement=measurement,
        over=over,
        measured_at=measured_at,
        gate_for=gate_for,
    )
    receipt = await commit_command(
        context,
        command=_SCREEN,
        new_state=updated.model_dump(mode="json", exclude_none=True),
        result=TypedObject(
            schema=_interaction_schema(),
            data={
                "outcome": updated.action or "measured",
                "interaction_id": interaction_id,
                "actor_id": actor_id,
                "violations": updated.violations,
            },
        ),
        store=store,
        expected_revision=current.version.revision if current is not None else None,
    )
    if receipt.outcome != "accepted":
        return None
    return updated


def _interaction_schema() -> SchemaRef:
    """Return the pinned API-06 reference a screening result is typed by.

    A screening decision mirrors no record of its own, so it is typed by the family
    that owns the policy it was made under rather than by an invented schema.
    """
    return SchemaRef(
        name="mug.api-06.interaction",
        version=0,
        digest=Digest(algorithm="sha-256", hex=interactions_schema().bundle_digest),
    )


__all__ = [
    "METRICS",
    "Screen",
    "ScreeningState",
    "action_at",
    "callback_action",
    "handler_name",
    "monitoring_id_for",
    "next_screening",
    "over_bounds",
    "read_screening",
    "record_screening",
]
