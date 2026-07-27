"""Assign the declared factors, count the cells, and record intent and delivery.

`mug.visits.design` is what an author writes. This is what the platform does with
it, and it is deliberately two halves.

The **pure half** decides. Given the treatments, the crossing, the durable counts,
and a seed, it returns the levels -- no clock, no store, no ``random`` module.
Every draw comes from a seeded digest rather than process entropy, so the same
seed and the same counts always give the same answer and a test can state what a
participant will be assigned.

The **durable half** records. An assignment is written once per unit and never
revised: its aggregate identifier derives from the visit and the factor, so a
participant who reloads, reconnects, or arrives after a restart meets the level
they already have rather than a fresh draw. That is the whole reason the
identifier is derived instead of minted.

Three things are kept apart on purpose:

- **Intent and delivery are separate records** (D06-5). ``TreatmentAssignment``
  says which level a participant was assigned; ``TreatmentExposure`` says they
  actually reached an activity that delivered it. A participant who abandons the
  study after consent has an assignment and no exposure, and an analysis that can
  not tell those apart is an analysis with a silent dropout bias.
- **The counts are durable, not per process** (D06-2). Balance is a property of
  the study version's whole lifetime. A counter held in memory rebalances from
  zero at every restart, which is not balance.
- **The counts are claimed before the assignment is written.** Two participants
  arriving at once both read the same counts; the claim commits against the
  revision it read, so one of them loses and re-chooses against the count the
  other just added. The assignment is written after the claim, so a lost claim
  costs a re-draw and never a wrong record.

**One identifier note, stated plainly.** The frozen identifier registry names one
immutable-materialization kind for API-04 (``visitplan``) and one runtime-occurrence
kind (``activity``); it names no mutable API-04 counter. An assignment is an
immutable materialization and an exposure is a runtime occurrence, so both take the
kind that describes them. The allocation counter is mutable and borrows
``visitplan`` because inventing a prefix would break a frozen registry; its
mutability is carried where it belongs, in the record's own ``VersionStamp``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from itertools import product
from typing import Any, Final, cast

from mug.kernel import (
    CommandTypeRef,
    TypedObject,
    VersionStamp,
    compute_digest,
    etag,
)
from mug.kernel.refs import StudyVersionRef
from mug.runtime import CommandContext, commit_command
from mug.storage import Store
from mug.visits.design import Design, Treatment
from mug.visits.types import (
    AllocationCellCount,
    AllocationState,
    AssignBalanced,
    AssignBlocked,
    AssignStratified,
    CellLevel,
    TreatmentAssignment,
    TreatmentExposure,
)

_ASSIGN = CommandTypeRef(name="treatment.assign", version=0)
_EXPOSE = CommandTypeRef(name="treatment.expose", version=0)
_COUNT = CommandTypeRef(name="treatment.count", version=0)

# How many times a losing claim on the durable counter re-reads and re-chooses.
# A claim is lost only when another participant is assigned in the same instant,
# so a small bound covers real contention. On exhaustion the participant is still
# assigned and still recorded -- they are never turned away because a counter was
# busy -- and only that one count is missed, which the assignment records
# themselves still evidence.
CLAIM_ATTEMPTS: Final[int] = 8

# The schema name an assignment aggregate head carries.
ASSIGNMENT_SCHEMA: Final[str] = "mug.api-04.treatment-assignment"
EXPOSURE_SCHEMA: Final[str] = "mug.api-04.treatment-exposure"

Cell = tuple[tuple[str, str], ...]
Derive = Callable[[str, str], str]
Seed = Callable[[str], bytes]


# --- the pure half: choosing ---------------------------------------------------


def draw(seed: bytes, salt: str, count: int) -> int:
    """Return one index below ``count``, decided by the seed alone."""
    digest = hashlib.sha256(seed + b"|" + salt.encode()).digest()
    return int.from_bytes(digest, "big") % count


def shuffled(seed: bytes, items: Sequence[str]) -> list[str]:
    """Return the items in the one order this seed gives.

    Ordering by a keyed digest of each item is a shuffle that depends on nothing
    but the seed: no process entropy, no ``random`` module state, and the same
    answer on every Python that has SHA-256.
    """
    return sorted(
        items, key=lambda one: hashlib.sha256(seed + b"|" + one.encode()).digest()
    )


def units(
    treatments: Sequence[Treatment], design: Design | None
) -> list[tuple[Treatment, ...]]:
    """Group the treatments into the units that are assigned together.

    A crossed design is one unit, so its cells are balanced jointly. Every other
    treatment is its own unit and is balanced on its own, which is what "treatments
    assign independently" means.
    """
    crossed = tuple(design.cross) if design is not None else ()
    grouped: list[tuple[Treatment, ...]] = []
    if crossed:
        grouped.append(tuple(sorted(crossed, key=lambda one: one.key)))
    for treatment in treatments:
        if treatment not in crossed:
            grouped.append((treatment,))
    return grouped


def cells_of(unit: Sequence[Treatment]) -> list[Cell]:
    """Return every cell of one assignment unit, in a stable order."""
    return [
        tuple(zip((one.key for one in unit), levels, strict=True))
        for levels in product(*(one.level_keys for one in unit))
    ]


def unit_key(unit: Sequence[Treatment]) -> str:
    """Return the stable name of one assignment unit."""
    return "+".join(sorted(one.key for one in unit))


def stratum_of(answer: object) -> str:
    """Return the level-shaped name of one stratifying answer.

    An answer is whatever a participant typed or picked, and a cell coordinate is
    an authoring key, so the answer is folded into one. Two answers that fold to
    the same name are one stratum, which is why a stratifying field should be a
    choice rather than free text.
    """
    text = str(answer).strip().lower()
    folded = "".join(char if char.isalnum() else "-" for char in text)
    trimmed = "-".join(part for part in folded.split("-") if part)[:60]
    if not trimmed or not trimmed[0].isalpha():
        return f"s-{trimmed}" if trimmed else "s-none"
    return trimmed


def stratum_coordinate(unit: Sequence[Treatment], stratum: str) -> tuple[str, str]:
    """Return the cell coordinate that keeps one stratum's counts to itself."""
    return (f"{unit_key(unit).replace('+', '.')}.stratum", stratum)


def counts_of(allocation: AllocationState | None, unit_counts: str) -> dict[Cell, int]:
    """Read the durable counter into a plain cell -> count map."""
    if allocation is None:
        return {}
    found: dict[Cell, int] = {}
    for entry in allocation.cells:
        cell = tuple(sorted((one.treatment_key, one.level_key) for one in entry.cell))
        found[cell] = entry.groups if unit_counts == "groups" else entry.participants
    return found


def choose(
    unit: Sequence[Treatment],
    *,
    counts: Mapping[Cell, int],
    seed: Seed,
    study_version_id: str,
    visit_id: str,
    stratum: str | None = None,
) -> Cell:
    """Return the cell this unit assigns next, under its declared policy.

    ``stratum`` is set only for a stratified policy; it namespaces the counts so
    each stratum is balanced on its own rather than the study as a whole.
    """
    policy = unit[0].assign
    cells = cells_of(unit)
    name = unit_key(unit)
    keyed = [_with_stratum(cell, unit, stratum) for cell in cells]

    if isinstance(policy, AssignBlocked):
        # One block is one permutation of the cells, and the whole block is filled
        # before the next begins. The block's order must be the same for every
        # participant in it, so its seed names the study version and the block --
        # never the visit.
        total = sum(counts.get(cell, 0) for cell in keyed)
        block, position = divmod(total, len(cells))
        by_label = {_label(cell): cell for cell in cells}
        order = shuffled(
            seed(f"block:{study_version_id}:{name}:{block}"), list(by_label)
        )
        return by_label[order[position]]

    if isinstance(policy, AssignBalanced | AssignStratified):
        # The emptiest cell wins. The seed only breaks ties, so two equally empty
        # cells are still decided by something the participant can not predict.
        order = shuffled(
            seed(f"assign:{visit_id}:{name}"), [_label(cell) for cell in cells]
        )
        rank = {label: index for index, label in enumerate(order)}
        return min(
            cells,
            key=lambda cell: (
                counts.get(_with_stratum(cell, unit, stratum), 0),
                rank[_label(cell)],
            ),
        )

    return cells[draw(seed(f"assign:{visit_id}:{name}"), name, len(cells))]


def _label(cell: Cell) -> str:
    """Return one cell's stable text label."""
    return "|".join(f"{key}={level}" for key, level in cell)


def _with_stratum(cell: Cell, unit: Sequence[Treatment], stratum: str | None) -> Cell:
    """Return the counted cell: the assigned levels, plus any stratum."""
    if stratum is None:
        return tuple(sorted(cell))
    return tuple(sorted((*cell, stratum_coordinate(unit, stratum))))


def counting_unit(unit: Sequence[Treatment]) -> str:
    """Return what a balanced unit counts: groups, or participants."""
    policy = unit[0].assign
    if isinstance(policy, AssignBalanced):
        return policy.unit
    return "participants"


def stratifying_field(unit: Sequence[Treatment]) -> tuple[str, str] | None:
    """Return the activity and field a stratified unit waits for, or None."""
    policy = unit[0].assign
    if isinstance(policy, AssignStratified):
        return (policy.by.activity_key, policy.by.field_key)
    return None


def within_order(treatment: Treatment, *, seed: Seed, visit_id: str) -> list[str]:
    """Return the order a within-subject treatment delivers its levels in.

    A counterbalanced order is decided by the durable counts, which this layer does
    not hold, so the caller passes the counts in as the seed's identity. A
    randomized order is decided by the visit alone.
    """
    return shuffled(seed(f"order:{visit_id}:{treatment.key}"), treatment.level_keys)


def counterbalanced_order(
    treatment: Treatment, *, counts: Mapping[Cell, int], seed: Seed, version_id: str
) -> list[str]:
    """Return the least used order of one within-subject treatment's levels.

    Counterbalancing is balance over orders rather than over levels, so the orders
    are counted in the same durable counter under a name of their own.
    """
    orders = ["-".join(one) for one in _permutations(list(treatment.level_keys))]
    ranked = shuffled(seed(f"order:{version_id}:{treatment.key}"), orders)
    rank = {label: index for index, label in enumerate(ranked)}
    best = min(
        orders,
        key=lambda label: (counts.get(order_cell(treatment, label), 0), rank[label]),
    )
    return best.split("-")


def order_cell(treatment: Treatment, order: str) -> Cell:
    """Return the counter cell one within-subject order is counted in."""
    return ((f"{treatment.key}.order", order),)


def _permutations(items: list[str]) -> list[list[str]]:
    """Return every order of the items, in a stable order."""
    if len(items) <= 1:
        return [items]
    found: list[list[str]] = []
    for index, item in enumerate(items):
        rest = items[:index] + items[index + 1 :]
        found.extend([item, *tail] for tail in _permutations(rest))
    return found


# --- the durable half: recording -----------------------------------------------


def assignment_id_for(derive: Derive, visit_id: str, unit_name: str) -> str:
    """Return the one aggregate this visit and unit always assign on."""
    return derive("visitplan", f"assignment:{visit_id}:{unit_name}")


def exposure_id_for(derive: Derive, occurrence_id: str, treatment_key: str) -> str:
    """Return the one aggregate this occurrence and factor always expose on."""
    return derive("activity", f"exposure:{occurrence_id}:{treatment_key}")


def allocation_id_for(derive: Derive, study_version_id: str) -> str:
    """Return the one counter aggregate this study version always counts on."""
    return derive("visitplan", f"allocation:{study_version_id}")


def recorded_levels(store: Store, assignment_id: str) -> dict[str, str]:
    """Return the levels already assigned on one aggregate, or nothing."""
    state = store.load_aggregate(assignment_id)
    if not isinstance(state, dict):
        return {}
    found = cast("dict[str, Any]", state).get("levels")
    if not isinstance(found, dict):
        return {}
    return {
        str(key): str(value) for key, value in cast("dict[str, Any]", found).items()
    }


def recorded_assignments(store: Store, assignment_id: str) -> list[TreatmentAssignment]:
    """Return the assignment records committed on one aggregate."""
    state = store.load_aggregate(assignment_id)
    if not isinstance(state, dict):
        return []
    written = cast("dict[str, Any]", state).get("assignments")
    if not isinstance(written, list):
        return []
    return [
        TreatmentAssignment.model_validate(one) for one in cast("list[Any]", written)
    ]


def read_allocation(store: Store, allocation_id: str) -> AllocationState | None:
    """Return the durable counter for one study version, or None for none yet."""
    state = store.load_aggregate(allocation_id)
    if not isinstance(state, dict):
        return None
    return AllocationState.model_validate(state)


def assignment_records(
    levels: Mapping[str, str],
    unit: Sequence[Treatment],
    *,
    visit_id: str,
    assigned_at: str,
) -> list[TreatmentAssignment]:
    """Build one record per factor in a unit, all naming the same moment."""
    written: list[TreatmentAssignment] = []
    for treatment in unit:
        body = {
            "treatment_key": treatment.key,
            "level_key": levels[treatment.key],
            "scope": treatment.scope,
            "visit_id": visit_id,
        }
        written.append(
            TreatmentAssignment(
                **body,  # pyright: ignore[reportArgumentType]
                assigned_at=assigned_at,
                assignment_digest=compute_digest(body),
            )
        )
    return written


def exposure_record(
    *,
    visit_id: str,
    treatment_key: str,
    level_key: str,
    occurrence_id: str,
    exposed_at: str,
) -> TreatmentExposure:
    """Build the record that one occurrence actually delivered one level."""
    body = {
        "visit_id": visit_id,
        "treatment_key": treatment_key,
        "level_key": level_key,
        "occurrence_id": occurrence_id,
    }
    return TreatmentExposure(
        **body,  # pyright: ignore[reportArgumentType]
        exposed_at=exposed_at,
        exposure_digest=compute_digest(body),
    )


def next_allocation(
    allocation: AllocationState | None,
    *,
    study_version: StudyVersionRef,
    cell: Cell,
    unit_counts: str,
) -> AllocationState:
    """Return the counter with one more unit placed in one cell."""
    entries = list(allocation.cells) if allocation is not None else []
    coordinates = [
        CellLevel(treatment_key=key, level_key=level)  # pyright: ignore[reportArgumentType]
        for key, level in sorted(cell)
    ]
    updated: list[AllocationCellCount] = []
    placed = False
    for entry in entries:
        same = tuple(sorted((one.treatment_key, one.level_key) for one in entry.cell))
        if same == tuple(sorted(cell)):
            placed = True
            updated.append(
                AllocationCellCount(
                    cell=entry.cell,
                    groups=entry.groups + (1 if unit_counts == "groups" else 0),
                    participants=entry.participants
                    + (0 if unit_counts == "groups" else 1),
                )
            )
        else:
            updated.append(entry)
    if not placed:
        updated.append(
            AllocationCellCount(
                cell=coordinates,
                groups=1 if unit_counts == "groups" else 0,
                participants=0 if unit_counts == "groups" else 1,
            )
        )
    revision = allocation.version.revision + 1 if allocation is not None else 1
    body = {
        "study_version": study_version.model_dump(mode="json", exclude_none=True),
        "cells": [one.model_dump(mode="json", exclude_none=True) for one in updated],
    }
    return AllocationState(
        **body,  # pyright: ignore[reportArgumentType]
        version=VersionStamp(revision=revision, etag=etag(body)),
    )


async def claim_cell(
    *,
    allocation_id: str,
    study_version: StudyVersionRef,
    cell: Cell,
    unit_counts: str,
    context: CommandContext,
    store: Store,
) -> bool:
    """Add one unit to one cell of the durable counter, or report the loss.

    The commit names the revision the caller read, so a claim written between the
    read and the commit wins and this one is refused. The caller re-reads and
    chooses again against the count that just landed, which is what keeps balance
    correct when two participants arrive together.
    """
    current = read_allocation(store, allocation_id)
    updated = next_allocation(
        current, study_version=study_version, cell=cell, unit_counts=unit_counts
    )
    receipt = await commit_command(
        context,
        command=_COUNT,
        new_state=updated.model_dump(mode="json", exclude_none=True),
        result=TypedObject(
            schema=updated.schema,
            data={
                "study_version_id": study_version.study_version_id,
                "cell": _label(tuple(sorted(cell))),
                "revision": updated.version.revision,
            },
        ),
        store=store,
        expected_revision=current.version.revision if current is not None else None,
    )
    return receipt.outcome == "accepted"


async def record_assignment(
    *,
    assignment_id: str,
    unit: Sequence[Treatment],
    levels: Mapping[str, str],
    visit_id: str,
    assigned_at: str,
    context: CommandContext,
    store: Store,
) -> bool:
    """Commit one unit's assignment, once and for the whole visit.

    The aggregate holds every factor of the unit, because a crossed unit is one
    decision: recording ``difficulty=hard`` without ``partner=ai`` would be half a
    cell. The head keeps the resolved levels beside the records, so reading what a
    participant was assigned needs no reconstruction.
    """
    written = assignment_records(
        levels, unit, visit_id=visit_id, assigned_at=assigned_at
    )
    state: dict[str, Any] = {
        **written[0].model_dump(mode="json", exclude_none=True),
        "assignments": [
            one.model_dump(mode="json", exclude_none=True) for one in written
        ],
        "levels": dict(sorted(levels.items())),
    }
    receipt = await commit_command(
        context,
        command=_ASSIGN,
        new_state=state,
        result=TypedObject(
            schema=written[0].schema,
            data={
                "visit_id": visit_id,
                "unit": unit_key(unit),
                "levels": dict(sorted(levels.items())),
            },
        ),
        store=store,
    )
    return receipt.outcome == "accepted"


async def record_exposure(
    *,
    exposure_id: str,
    visit_id: str,
    treatment_key: str,
    level_key: str,
    occurrence_id: str,
    exposed_at: str,
    context: CommandContext,
    store: Store,
) -> bool:
    """Commit that one activity occurrence actually delivered one level."""
    exposure = exposure_record(
        visit_id=visit_id,
        treatment_key=treatment_key,
        level_key=level_key,
        occurrence_id=occurrence_id,
        exposed_at=exposed_at,
    )
    receipt = await commit_command(
        context,
        command=_EXPOSE,
        new_state=exposure.model_dump(mode="json", exclude_none=True),
        result=TypedObject(
            schema=exposure.schema,
            data={
                "visit_id": visit_id,
                "treatment_key": treatment_key,
                "level_key": level_key,
                "occurrence_id": occurrence_id,
            },
        ),
        store=store,
    )
    return receipt.outcome == "accepted"


__all__ = [
    "ASSIGNMENT_SCHEMA",
    "CLAIM_ATTEMPTS",
    "EXPOSURE_SCHEMA",
    "Cell",
    "allocation_id_for",
    "assignment_id_for",
    "assignment_records",
    "cells_of",
    "choose",
    "claim_cell",
    "counterbalanced_order",
    "counting_unit",
    "counts_of",
    "draw",
    "exposure_id_for",
    "exposure_record",
    "next_allocation",
    "order_cell",
    "read_allocation",
    "record_assignment",
    "record_exposure",
    "recorded_assignments",
    "recorded_levels",
    "shuffled",
    "stratifying_field",
    "stratum_coordinate",
    "stratum_of",
    "unit_key",
    "units",
    "within_order",
]
