"""Assign a study's factors to one participant, and record what they then met.

`mug.visits.assignment` decides and records; `mug.content.plan` reads the study.
This module is the one that runs them together for a real visit: it walks the
units a study declares, claims a cell in the durable counter, writes the
assignment, and later writes the exposure when the participant actually reaches an
activity that delivers it.

Three properties are what the tests hold it to.

**Once.** Every identifier is derived from the visit and the factor, so a
participant who reloads, reconnects, or arrives after a restart reads the
assignment they already have. Nothing is redrawn, ever -- a study whose conditions
change under a refresh is not a study.

**Deferred, not skipped.** A stratified factor waits for the answer it stratifies
on. Until that answer exists the factor is simply not assigned, and every advance
tries again, so it lands on the first step after the form that supplies it. The
plan's parameter digests are restated at that point, so nothing claims a condition
before it was decided.

**Intent is not delivery.** ``assign_visit`` writes what a participant was assigned.
``record_exposures`` writes what they were actually shown, at which occurrence.
A participant who consents and leaves has the first and not the second.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from mug.content.plan import (
    Derive,
    Seed,
    between_treatments,
    declared_treatments,
    drawn_orders,
    order_cells,
    treatments_at,
)
from mug.content.study import Study
from mug.kernel.refs import StudyVersionRef
from mug.runtime import CommandContext
from mug.storage import Store
from mug.visits.assignment import (
    CLAIM_ATTEMPTS,
    Cell,
    allocation_id_for,
    assignment_id_for,
    choose,
    claim_cell,
    counterbalanced_order,
    counting_unit,
    counts_of,
    exposure_id_for,
    read_allocation,
    record_assignment,
    record_exposure,
    recorded_levels,
    stratifying_field,
    stratum_coordinate,
    stratum_of,
    unit_key,
    units,
)
from mug.visits.design import Treatment

# Mint the runtime authority for one command against one aggregate. The caller owns
# the gateway, so it owns this; everything below only asks for it.
MintContext = Callable[[str, str], Awaitable[CommandContext]]

# Read what this participant answered to one activity's field, or None when they
# have not answered it yet. A stratified factor waits on it.
AnswerLookup = Callable[[str, str], Awaitable[Any]]


async def assign_visit(
    study: Study,
    *,
    visit_id: str,
    study_version: StudyVersionRef,
    store: Store,
    derive: Derive,
    seed: Seed,
    now: Callable[[], str],
    mint: MintContext,
    answer: AnswerLookup | None = None,
) -> dict[str, str]:
    """Assign every factor that can be assigned now, and return the levels.

    A factor already assigned to this visit is read back rather than redrawn. A
    factor waiting for an answer it does not have is left out, and the next call
    picks it up.
    """
    assigned: dict[str, str] = {}
    allocation_id = allocation_id_for(derive, study_version.study_version_id)
    for unit in units(between_treatments(study), study.design):
        name = unit_key(unit)
        assignment_id = assignment_id_for(derive, visit_id, name)
        already = recorded_levels(store, assignment_id)
        if already:
            assigned.update(already)
            continue
        stratum = await _stratum(unit, answer)
        if stratum is _WAITING:
            continue
        cell = await _claim(
            unit,
            allocation_id=allocation_id,
            study_version=study_version,
            visit_id=visit_id,
            stratum=stratum,
            store=store,
            seed=seed,
            mint=mint,
        )
        levels = dict(cell)
        if await record_assignment(
            assignment_id=assignment_id,
            unit=unit,
            levels=levels,
            visit_id=visit_id,
            assigned_at=now(),
            context=await mint("treatment.assign", assignment_id),
            store=store,
        ):
            assigned.update(levels)
    return assigned


# The sentinel for "this factor is waiting for an answer it does not have yet". It
# is not None, because None is a perfectly good answer to stratify on.
_WAITING: Any = object()


async def _stratum(
    unit: Sequence[Treatment], answer: AnswerLookup | None
) -> str | None:
    """Return the stratum this unit is balanced inside, or the waiting sentinel."""
    field = stratifying_field(unit)
    if field is None:
        return None
    if answer is None:
        return _WAITING
    found = await answer(*field)
    if found is None:
        return _WAITING
    return stratum_of(found)


async def _claim(
    unit: Sequence[Treatment],
    *,
    allocation_id: str,
    study_version: StudyVersionRef,
    visit_id: str,
    stratum: str | None,
    store: Store,
    seed: Seed,
    mint: MintContext,
) -> Cell:
    """Choose this unit's cell and add it to the durable counter.

    The choice is made against the counts as they are read, and the claim commits
    against the revision it read. A claim that lands first wins, and this one reads
    the new count and chooses again -- which is exactly what keeps two participants
    who arrive together from being given the same emptiest cell.
    """
    counts_kind = counting_unit(unit)
    cell: Cell = ()
    for _ in range(CLAIM_ATTEMPTS):
        counts = counts_of(read_allocation(store, allocation_id), counts_kind)
        cell = choose(
            unit,
            counts=counts,
            seed=seed,
            study_version_id=study_version.study_version_id,
            visit_id=visit_id,
            stratum=stratum,
        )
        counted = _counted(cell, unit, stratum)
        if await claim_cell(
            allocation_id=allocation_id,
            study_version=study_version,
            cell=counted,
            unit_counts=counts_kind,
            context=await mint("treatment.count", allocation_id),
            store=store,
        ):
            break
    return cell


def _counted(cell: Cell, unit: Sequence[Treatment], stratum: str | None) -> Cell:
    """Return the cell as the counter holds it, stratum included."""
    if stratum is None:
        return tuple(sorted(cell))
    return tuple(sorted((*cell, stratum_coordinate(unit, stratum))))


async def visit_orders(
    study: Study,
    *,
    visit_id: str,
    study_version: StudyVersionRef,
    store: Store,
    derive: Derive,
    seed: Seed,
    mint: MintContext,
) -> dict[str, list[str]]:
    """Return the order each within-subject factor delivers its levels in.

    A counterbalanced order is the least used one so far and is counted like any
    other cell, so the orders stay even over the study version's lifetime rather
    than over one process.
    """
    allocation_id = allocation_id_for(derive, study_version.study_version_id)

    def counterbalance(treatment: Treatment) -> list[str]:
        return counterbalanced_order(
            treatment,
            counts=counts_of(read_allocation(store, allocation_id), "participants"),
            seed=seed,
            version_id=study_version.study_version_id,
        )

    orders = drawn_orders(
        study, visit_id=visit_id, seed=seed, counterbalance=counterbalance
    )
    for cell in order_cells(study, orders):
        await claim_cell(
            allocation_id=allocation_id,
            study_version=study_version,
            cell=cell,
            unit_counts="participants",
            context=await mint("treatment.count", allocation_id),
            store=store,
        )
    return orders


async def record_exposures(
    study: Study,
    *,
    activity_key: str,
    occurrence_id: str,
    visit_id: str,
    levels: Mapping[str, str],
    store: Store,
    derive: Derive,
    now: Callable[[], str],
    mint: MintContext,
) -> list[str]:
    """Record that this occurrence delivered the levels in force there.

    Returns the factors that were recorded. A factor placed here but not yet
    assigned records nothing: the participant met a stand-in, not a condition, and
    writing an exposure for it would put a level in the data that nobody was
    assigned.
    """
    written: list[str] = []
    for treatment in treatments_at(study, activity_key):
        level = levels.get(treatment.key)
        if level is None:
            continue
        exposure_id = exposure_id_for(derive, occurrence_id, treatment.key)
        if store.load_aggregate(exposure_id) is not None:
            written.append(treatment.key)
            continue
        if await record_exposure(
            exposure_id=exposure_id,
            visit_id=visit_id,
            treatment_key=treatment.key,
            level_key=level,
            occurrence_id=occurrence_id,
            exposed_at=now(),
            context=await mint("treatment.expose", exposure_id),
            store=store,
        ):
            written.append(treatment.key)
    return written


def manipulates(study: Study) -> bool:
    """Report whether this study manipulates anything at all.

    A study that does not skips every read and every commit here, so nothing about
    treatments costs a questionnaire study a single store call.
    """
    return bool(declared_treatments(study))


__all__ = [
    "AnswerLookup",
    "MintContext",
    "assign_visit",
    "manipulates",
    "record_exposures",
    "visit_orders",
]
