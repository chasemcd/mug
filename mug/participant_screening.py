"""Turn a client's quality samples into an entry decision and an in-play ladder.

`mug.visits.eligibility` decides whether a visit may enter and `mug.interactions
.monitoring` decides what a bad sample costs an actor. Both are pure. This module
is the impure half between them and the socket: it reads the client's frame, builds
the frozen API-09 ``MonitoringMeasurement`` from it, and records what the server
decided.

**The client reports, the server judges.** A browser sends the numbers it measured
and nothing else -- no verdict, no policy, no bound. Every comparison happens here,
which is what "server-authoritative" in the API-06 policy means: the bound, the
ladder, and the decision never leave the server, so a client can not admit itself
and can not decide it has been warned rather than excluded.

What this is **not** is a defence against a determined participant. The numbers are
measured in a browser the participant owns, so a participant who wants to report a
better connection than they have can. The screen exists to keep honest evidence of
connection quality and to end sessions that are too poor to yield usable data, not
to police anyone.

**Entry and in-play read the same evidence.** The first sample decides admission and
every later one climbs the ladder, so a study gets both from one declaration. Entry
waits for that first sample rather than admitting on silence: a decision recorded
before any evidence arrived would be a decision about nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from mug.client.types import (
    GateAnchor,
    GateOp,
    MonitoringMeasurement,
    MonitoringPolicyRef,
    QualityMeasurement,
)
from mug.content import Study
from mug.interactions.monitoring import (
    METRICS,
    Screen,
    ScreeningState,
    callback_action,
    monitoring_id_for,
    over_bounds,
    record_screening,
)
from mug.interactions.types import interactions_schema
from mug.kernel import Digest, Duration
from mug.realtime import Session
from mug.runtime import CommandContext
from mug.storage import Store
from mug.visits.eligibility import (
    Decision,
    Entry,
    bounds_decision,
    callback_for,
    decide,
    eligibility_id_for,
    entry_node_id,
    read_decision,
    record_decision,
)

# The seat a single-participant study screens. A multi-seat interaction screens each
# seat under the same policy; the seat key travels with the measurement so that the
# record says which one was measured.
SEAT_KEY = "player"

# The widest sample the server will read: one hour in microseconds. A number past it
# is a broken client or a hostile one, and either way it is dropped rather than
# recorded as a measurement.
_MAX_SAMPLE = 3_600_000_000

# Mint one command context on one aggregate (the transport injects it).
MintContext = Callable[[str, str], Any]


def samples_of(frame: Mapping[str, Any]) -> dict[str, int]:
    """Read the quality samples off one untrusted client frame.

    Only the metrics API-09 names are read, only whole microseconds are accepted,
    and a value outside the sane range is dropped. A frame with nothing readable in
    it yields nothing, which is not the same as a frame that reported zero.
    """
    raw = frame.get("samples")
    if not isinstance(raw, dict):
        return {}
    found = cast("dict[str, Any]", raw)
    return {
        metric: found[metric]
        for metric in METRICS
        if isinstance(found.get(metric), int)
        and not isinstance(found.get(metric), bool)
        and 0 <= found[metric] <= _MAX_SAMPLE
    }


def measurement_of(
    samples: Mapping[str, int], *, seat_key: str, measured_at: str
) -> MonitoringMeasurement | None:
    """Build the frozen API-09 measurement from what the client reported.

    The record is built here rather than accepted from the client, so the schema
    reference and the policy pin are the server's own. Returns None when the client
    reported nothing this platform judges.
    """
    readings = [
        QualityMeasurement(
            metric=cast("Any", metric), observed=Duration(microseconds=samples[metric])
        )
        for metric in METRICS
        if metric in samples
    ]
    if not readings:
        return None
    return MonitoringMeasurement(
        policy=MonitoringPolicyRef(
            name="mug.api-06.interaction",
            version=0,
            digest=Digest(
                algorithm="sha-256", hex=interactions_schema().bundle_digest
            ),
        ),
        seat_key=seat_key,  # pyright: ignore[reportArgumentType]
        measurements=readings,
        measured_at=measured_at,  # pyright: ignore[reportArgumentType]
    )


def screening_ids(derive: Callable[[str, str], str], visit_id: str) -> tuple[str, str]:
    """Return the interaction and actor one visit's screening is recorded under.

    A flow with no formed interaction still has one participant on one connection,
    and that is what is being screened. Both identifiers derive from the visit, so a
    reconnection carries its violation count rather than starting clean.
    """
    return (
        derive("interaction", f"session:{visit_id}"),
        derive("actor", f"participant:{visit_id}"),
    )


def _refusal(reason: str) -> dict[str, Any]:
    """Return the outcome frame that ends a session."""
    return {"action": "exclude", "reason": reason}


def gate_op_for(
    action: str,
    *,
    derive: Callable[[str, str], str],
    visit_id: str,
    activity_key: str,
    requested_at: str,
) -> dict[str, Any] | None:
    """Return the readiness gate op an exclusion raises, or None for a warning.

    Excluding a participant is blocking them from advancing, so it is written as
    the op that says exactly that. A warning blocks nothing: they carry on, and the
    record says they were told.
    """
    if action != "exclude":
        return None
    return GateOp(
        gate_id=derive("gate", f"exclude:{visit_id}"),  # pyright: ignore[reportArgumentType]
        target="advance",
        action="block",
        anchor=GateAnchor(anchor_kind="flow_node", anchor_key=activity_key),  # pyright: ignore[reportArgumentType]
        requested_at=requested_at,  # pyright: ignore[reportArgumentType]
    ).model_dump(mode="json", exclude_none=True)


async def entry_decision(
    *,
    study: Study,
    visit_id: str,
    study_version_id: str,
    samples: Mapping[str, int],
    store: Store,
    derive: Callable[[str, str], str],
    mint: Callable[[str, str], Any],
    now: Callable[[], str],
) -> Decision:
    """Decide whether this visit may enter, recording the decision the first time.

    A decision already recorded is read back rather than made again: a participant
    who reconnects meets the answer they were given, and a refusal can not be
    retried away by reloading the page.
    """
    eligibility_id = eligibility_id_for(derive, visit_id)
    recorded = read_decision(store, eligibility_id)
    if recorded is not None:
        return recorded
    screen = study.screen
    decision = Decision(admitted=True, reason="eligible")
    if screen is not None and screen.at_entry:
        decision = bounds_decision(screen.bounds(), samples)
    if decision.admitted and study.admit is not None:
        on_error = "fail_closed" if screen is None else screen.on_error
        decision = decide(
            study.admit,
            Entry(
                visit_id=visit_id,
                study_version_id=study_version_id,
                metrics=dict(samples),
            ),
            on_error=on_error,
        )
    callbacks = (
        []
        if study.admit is None
        else [
            callback_for(
                study.admit,
                flow_node_id=entry_node_id(derive, study_version_id),
                rule_key="entry",
                on_error="fail_closed" if screen is None else screen.on_error,
            )
        ]
    )
    context = cast("CommandContext", await mint("eligibility.decide", eligibility_id))
    await record_decision(
        eligibility_id=eligibility_id,
        visit_id=visit_id,
        decision=decision,
        callbacks=callbacks,
        metrics=samples,
        decided_at=now(),
        context=context,
        store=store,
    )
    return decision


async def measure(
    *,
    screen: Screen,
    visit_id: str,
    activity_key: str,
    samples: Mapping[str, int],
    store: Store,
    derive: Callable[[str, str], str],
    mint: Callable[[str, str], Any],
    now: Callable[[], str],
) -> ScreeningState | None:
    """Record one measurement against the study's screen, and return the outcome.

    Returns None when the client reported nothing readable, or when the commit was
    refused. Nothing is applied on None: an exclusion the ledger did not take is one
    a reconnection would not remember.
    """
    measurement = measurement_of(samples, seat_key=SEAT_KEY, measured_at=now())
    if measurement is None:
        return None
    interaction_id, actor_id = screening_ids(derive, visit_id)
    policy = screen.policy()
    context = cast(
        "CommandContext",
        await mint(
            "monitoring.screen",
            monitoring_id_for(derive, interaction_id, actor_id),
        ),
    )
    return await record_screening(
        monitoring_id=monitoring_id_for(derive, interaction_id, actor_id),
        interaction_id=interaction_id,
        actor_id=actor_id,
        visit_id=visit_id,
        policy=policy,
        measurement=measurement.model_dump(mode="json", exclude_none=True),
        over=over_bounds(policy, samples),
        measured_at=measurement.measured_at,
        gate_for=lambda action: gate_op_for(
            action,
            derive=derive,
            visit_id=visit_id,
            activity_key=activity_key,
            requested_at=measurement.measured_at,
        ),
        context=context,
        store=store,
    )


def _decidable(study: Study, samples: Mapping[str, int]) -> bool:
    """Return whether entry can be decided on the evidence in hand.

    A study that screens the connection at entry waits for a sample: the client
    handshake may arrive one round trip before the client has measured anything, and
    admitting on that silence would record a decision about no evidence at all.
    """
    screen = study.screen
    if screen is None or not screen.at_entry:
        return True
    return bool(samples)


async def screen_frame(
    frame: Mapping[str, Any],
    *,
    session: Session,
    study: Study,
    study_version_id: str,
    store: Store,
    derive: Callable[[str, str], str],
    mint: Callable[[str, str], Any],
    now: Callable[[], str],
) -> dict[str, Any] | None:
    """Judge one client frame and return what to tell the participant.

    The first frame that carries evidence decides admission, whether it rode the
    client handshake or arrived later; every frame after that climbs the ladder. The
    answer is None when there is nothing to say.
    """
    visit_id = session.state.get("visit_id")
    if not isinstance(visit_id, str):
        return None
    if study.screen is None and study.admit is None:
        return None
    samples = samples_of(frame)
    # A visit that was already refused never reaches here: the establish hook
    # refuses the reconnection before the handshake (``_refuse_ineligible`` in
    # ``mug.participant``), so a recorded refusal is enforced in one place rather
    # than in two that have to be kept in step.
    recorded = read_decision(store, eligibility_id_for(derive, visit_id))
    if recorded is None and _decidable(study, samples):
        decision = await entry_decision(
            study=study,
            visit_id=visit_id,
            study_version_id=study_version_id,
            samples=samples,
            store=store,
            derive=derive,
            mint=mint,
            now=now,
        )
        if not decision.admitted:
            return _refusal(decision.reason)
    screen = study.screen
    if screen is None or not samples:
        return None
    occurrence = session.state.get("occurrence_key")
    state = await measure(
        screen=screen,
        visit_id=visit_id,
        activity_key=occurrence if isinstance(occurrence, str) else "entry",
        samples=samples,
        store=store,
        derive=derive,
        mint=mint,
        now=now,
    )
    if state is None or state.action is None:
        return None
    action = state.action
    if screen.on_violation is not None:
        hook = screen.on_violation
        forced = callback_action(state.policy, lambda: hook(state))
        if forced == "exclude":
            action = "exclude"
    if action == "exclude":
        return _refusal("this session was ended because the connection was too poor")
    return {"action": "warn", "reason": "your connection is struggling"}


__all__ = [
    "SEAT_KEY",
    "MintContext",
    "entry_decision",
    "measure",
    "measurement_of",
    "samples_of",
    "screen_frame",
    "screening_ids",
]
