"""Read a study's design, and draft the plan one participant will walk.

`mug.visits.design` is what an author writes and `mug.visits.assignment` is how a
level is chosen. This module is the part that knows about a whole ``Study``: which
factors it declares, where each one takes effect, and what the ordered list of
occurrences looks like once the within-subject repeats are expanded.

It is pure. Every identifier it needs is derived by a callable the caller injects,
and every order comes from a seed the caller supplies, so the same study, the same
levels, and the same seeds always draft the same plan. That is what makes a restart
safe: the plan is committed once and reloaded, and nothing is redrawn.

**What the plan records that the flow does not.** The flow is a pointer. The plan
is the record of what this participant was given: the occurrence identifiers, the
order, and a ``parameter_digest`` per occurrence that binds the levels delivered
there. Two participants in different conditions have different digests at the same
activity, which is how a reader tells the conditions apart without trusting a label.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mug.content.study import Activity, Study
from mug.kernel import Digest, compute_digest
from mug.visits.assignment import Cell, order_cell, shuffled
from mug.visits.design import Order, Placement, Treatment, placed
from mug.visits.eligibility import callback_for, entry_node_id
from mug.visits.types import EligibilityCallback, PlannedActivity, RandomizationOutcome

Derive = Callable[[str, str], str]
Seed = Callable[[str], bytes]


def occurrence_id_for(derive: Derive, visit_id: str, occurrence_key: str) -> str:
    """Return the one activity occurrence this visit and step always give.

    Deriving it rather than minting it is what makes a step happen once: a
    participant who submits, loses the receipt, and submits again reaches the same
    occurrence rather than opening a second one. The plan names it, and every record
    of what happened there -- the answers, the exposure -- names the same one.
    """
    return derive("activity", f"occurrence:{visit_id}:{occurrence_key}")


def declared_eligibility(
    study: Study, *, derive: Derive, study_version_id: str
) -> list[EligibilityCallback]:
    """Return the entry rules this study declares, for the plan to carry.

    A study that screens on nothing declares nothing, so ``VisitPlan.eligibility``
    stays absent rather than empty: an empty list would read as "screened, and
    everyone passed", which is a different claim.
    """
    if study.admit is None:
        return []
    on_error = "fail_closed" if study.screen is None else study.screen.on_error
    return [
        callback_for(
            study.admit,
            flow_node_id=entry_node_id(derive, study_version_id),
            rule_key="entry",
            on_error=on_error,
        )
    ]


def sites(study: Study) -> list[tuple[str, Placement]]:
    """Return every placement in the study, as (activity key, placement).

    A step is written as a game or as a page, never both, so one activity holds one
    placement today. Both sources are read because that is what changes when a seat
    becomes an effect site as well (W8), and it costs nothing now.
    """
    found: list[tuple[str, Placement]] = []
    for activity in study.activities:
        for value in (study.games.get(activity.key), study.contents.get(activity.key)):
            placement = placed(value)
            if placement is not None:
                found.append((activity.key, placement))
    return found


def declared_treatments(study: Study) -> tuple[Treatment, ...]:
    """Return the factors this study manipulates, in the order they appear.

    The same object placed at several sites is one factor, which is why the
    de-duplication is by identity: two separately written treatments that happen to
    have the same key and levels are two factors and the study is asked to fix it
    (see ``mug.content.publish``).
    """
    found: list[Treatment] = []
    for _, placement in sites(study):
        if not any(one is placement.treatment for one in found):
            found.append(placement.treatment)
    return tuple(found)


def treatments_at(study: Study, activity_key: str) -> tuple[Treatment, ...]:
    """Return the factors that take effect at one activity."""
    found: list[Treatment] = []
    for key, placement in sites(study):
        if key == activity_key and not any(one is placement.treatment for one in found):
            found.append(placement.treatment)
    return tuple(found)


def between_treatments(study: Study) -> tuple[Treatment, ...]:
    """Return the factors a participant is assigned ONE level of.

    A within-subject factor is not one of them: the participant meets every level,
    so there is nothing to assign and only the order is decided.
    """
    return tuple(one for one in declared_treatments(study) if not one.within)


def within_treatment(study: Study, activity_key: str) -> Treatment | None:
    """Return the within-subject factor one activity repeats for, or None."""
    for treatment in treatments_at(study, activity_key):
        if treatment.within:
            return treatment
    return None


def resolve(value: Any, levels: Mapping[str, str]) -> Any:
    """Return what one authored site delivers under an assigned set of levels.

    A site that holds no treatment delivers what the author wrote, which is the
    common case and the reason a study with no manipulation reads exactly as it did
    before any of this existed.
    """
    placement = placed(value)
    if placement is None:
        return value
    level = levels.get(placement.treatment.key)
    if level is None:
        # No level assigned yet -- a stratified factor before its input exists.
        # The author's first level stands in, and the caller records nothing as
        # delivered, because an exposure that never happened is not evidence.
        level = placement.treatment.level_keys[0]
    return placement.value_for(level)


def spec_for(study: Study, activity_key: str, levels: Mapping[str, str]) -> Any:
    """Return the game specification one activity runs under these levels."""
    return resolve(study.games.get(activity_key), levels)


def activity_for(
    study: Study, activity_key: str, levels: Mapping[str, str]
) -> Activity:
    """Return one activity as this participant meets it, content resolved."""
    activity = study.activity(activity_key)
    placement = study.contents.get(activity_key)
    if placement is None:
        return activity
    return activity.model_copy(update={"content": resolve(placement, levels)})


# --- drafting the plan ---------------------------------------------------------


@dataclass(frozen=True)
class Occurrence:
    """One step of the drafted plan: what runs, and which levels it delivers."""

    key: str
    activity_key: str
    kind: str
    within: dict[str, str]


@dataclass(frozen=True)
class PlanDraft:
    """The ordered occurrences of one visit, and the orders that were drawn."""

    occurrences: tuple[Occurrence, ...]
    outcomes: tuple[RandomizationOutcome, ...]


def draft_plan(
    study: Study,
    *,
    visit_id: str,
    orders: Mapping[str, Sequence[str]],
    derive: Derive,
    seed: Seed,
) -> PlanDraft:
    """Draft the ordered occurrences one participant walks, with their orders.

    A within-subject factor turns its activity into one occurrence per level, in the
    order ``orders`` gives for that factor, and the order itself is recorded as a
    ``RandomizationOutcome`` with a commitment to the seed that drew it. The
    commitment is what lets a deployment later prove the order it showed rather than
    assert it.
    """
    occurrences: list[Occurrence] = []
    outcomes: list[RandomizationOutcome] = []
    for activity in study.activities:
        treatment = within_treatment(study, activity.key)
        if treatment is None:
            occurrences.append(
                Occurrence(
                    key=activity.key,
                    activity_key=activity.key,
                    kind=activity.kind,
                    within={},
                )
            )
            continue
        drawn = list(orders.get(treatment.key, treatment.level_keys))
        for level in drawn:
            occurrences.append(
                Occurrence(
                    key=f"{activity.key}.{level}",
                    activity_key=activity.key,
                    kind=activity.kind,
                    within={treatment.key: level},
                )
            )
        outcomes.append(
            RandomizationOutcome(
                flow_node_id=derive("flownode", f"{visit_id}:{activity.key}"),
                rule_key=treatment.key,
                chosen=drawn,  # pyright: ignore[reportArgumentType]
                seed_commitment=compute_digest(
                    {"seed": seed(f"order:{visit_id}:{treatment.key}").hex()}
                ),
            )
        )
    return PlanDraft(tuple(occurrences), tuple(outcomes))


def drawn_orders(
    study: Study,
    *,
    visit_id: str,
    seed: Seed,
    counterbalance: Callable[[Treatment], list[str]] | None = None,
) -> dict[str, list[str]]:
    """Return the order each within-subject factor delivers its levels in.

    A randomized order is drawn from the visit's own seed and depends on nothing
    else. A counterbalanced order is the least used one so far, which the caller
    supplies because it needs the durable counts this layer does not hold.
    """
    orders: dict[str, list[str]] = {}
    for treatment in declared_treatments(study):
        if not treatment.within:
            continue
        if treatment.order == Order.COUNTERBALANCED and counterbalance is not None:
            orders[treatment.key] = counterbalance(treatment)
        else:
            orders[treatment.key] = shuffled(
                seed(f"order:{visit_id}:{treatment.key}"), treatment.level_keys
            )
    return orders


def order_cells(study: Study, orders: Mapping[str, Sequence[str]]) -> list[Cell]:
    """Return the counter cells the drawn counterbalanced orders belong in."""
    found: list[Cell] = []
    for treatment in declared_treatments(study):
        if treatment.within and treatment.order == Order.COUNTERBALANCED:
            drawn = orders.get(treatment.key)
            if drawn is not None:
                found.append(order_cell(treatment, "-".join(drawn)))
    return found


def levels_at(
    study: Study, occurrence: Occurrence, assigned: Mapping[str, str]
) -> dict[str, str]:
    """Return every level one occurrence delivers: assigned, plus its own."""
    keys = {one.key for one in treatments_at(study, occurrence.activity_key)}
    delivered = {key: level for key, level in assigned.items() if key in keys}
    delivered.update(occurrence.within)
    return dict(sorted(delivered.items()))


def parameter_digest(
    study: Study, occurrence: Occurrence, assigned: Mapping[str, str]
) -> Digest:
    """Return the digest that binds what one occurrence delivers.

    It covers the activity, its kind, and the levels in force there -- so two
    participants in different conditions have different digests at the same step,
    and a participant in no condition at all has the same digest as every other.
    """
    return compute_digest(
        {
            "activity_key": occurrence.activity_key,
            "kind": occurrence.kind,
            "levels": levels_at(study, occurrence, assigned),
        }
    )


def planned_activities(
    study: Study,
    draft: PlanDraft,
    *,
    visit_id: str,
    study_version_id: str,
    assigned: Mapping[str, str],
    derive: Derive,
    pointer: int = 0,
    statuses: Sequence[str] | None = None,
) -> list[PlannedActivity]:
    """Return the plan's activities, each with its identity and its parameters.

    ``statuses`` carries the progress an existing plan already recorded; with none
    the first occurrence is active and the rest are pending, which is a fresh plan.
    """
    written: list[PlannedActivity] = []
    for ordinal, occurrence in enumerate(draft.occurrences):
        if statuses is not None and ordinal < len(statuses):
            status = statuses[ordinal]
        elif ordinal < pointer:
            status = "completed"
        else:
            status = "active" if ordinal == pointer else "pending"
        written.append(
            PlannedActivity(
                occurrence_id=occurrence_id_for(derive, visit_id, occurrence.key),
                activity_definition_id=derive(
                    "activitydef", f"{study_version_id}:{occurrence.activity_key}"
                ),
                flow_node_id=derive(
                    "flownode", f"{study_version_id}:{occurrence.activity_key}"
                ),
                ordinal=ordinal,
                status=status,  # pyright: ignore[reportArgumentType]
                parameter_digest=parameter_digest(study, occurrence, assigned),
            )
        )
    return written


__all__ = [
    "Derive",
    "Occurrence",
    "PlanDraft",
    "Seed",
    "activity_for",
    "between_treatments",
    "declared_treatments",
    "draft_plan",
    "drawn_orders",
    "levels_at",
    "occurrence_id_for",
    "order_cells",
    "parameter_digest",
    "planned_activities",
    "resolve",
    "sites",
    "spec_for",
    "treatments_at",
    "within_treatment",
]
