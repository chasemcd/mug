"""The four assignment policies, and the durable counts they read.

`mug.visits.assignment` decides which level a participant gets. These tests hold
the pure half to what each policy promises, because a policy that quietly does
something else is a study whose conclusions are wrong and whose data looks fine.

Every draw here comes from a seed, so each test states the answer rather than
asserting a distribution: the point of seeding from the server secret is that the
result is reproducible for us and unpredictable for the participant.
"""

from __future__ import annotations

from collections.abc import Sequence

from mug.kernel import Digest
from mug.kernel.refs import StudyVersionRef
from mug.visits.assignment import (
    Cell,
    cells_of,
    choose,
    counterbalanced_order,
    counting_unit,
    counts_of,
    next_allocation,
    order_cell,
    shuffled,
    stratifying_field,
    stratum_of,
    unit_key,
    units,
)
from mug.visits.design import Assign, Design, Order, Treatment, Unit
from mug.visits.types import FieldRef

_VERSION = StudyVersionRef(
    study_id="study_019b6000-0000-7000-8000-0000000000a1",
    study_version_id="studyver_019b6000-0000-7000-8000-0000000000a2",
    version_number=1,
    manifest_digest=Digest(algorithm="sha-256", hex="0" * 64),
)


def _seed(role: str) -> bytes:
    """A stand-in for the gateway's secret-seeded derivation."""
    return f"secret::{role}".encode().ljust(32, b"\0")[:32]


def _levels(cell: Cell) -> dict[str, str]:
    return dict(cell)


def _fill(
    treatment: Treatment, visits: Sequence[str], *, stratum: str | None = None
) -> list[str]:
    """Assign a run of visits in turn, counting each one as it lands."""
    allocation = None
    unit = (treatment,)
    drawn: list[str] = []
    for visit_id in visits:
        cell = choose(
            unit,
            counts=counts_of(allocation, counting_unit(unit)),
            seed=_seed,
            study_version_id=_VERSION.study_version_id,
            visit_id=visit_id,
            stratum=stratum,
        )
        drawn.append(_levels(cell)[treatment.key])
        counted = (
            tuple(sorted(cell))
            if stratum is None
            else tuple(sorted((*cell, (f"{treatment.key}.stratum", stratum))))
        )
        allocation = next_allocation(
            allocation,
            study_version=_VERSION,
            cell=counted,
            unit_counts=counting_unit(unit),
        )
    return drawn


def test_a_balanced_factor_keeps_the_cells_even() -> None:
    """Eight participants over two levels is four and four, not near enough."""
    difficulty = Treatment("difficulty", ["easy", "hard"], assign=Assign.balanced())
    drawn = _fill(difficulty, [f"visit-{index}" for index in range(8)])

    assert drawn.count("easy") == 4
    assert drawn.count("hard") == 4
    # Even at every point, not only at the end: a study stopped after six has three
    # and three, which is what balancing is for.
    assert drawn[:6].count("easy") == 3


def test_a_random_factor_does_not_balance_and_does_not_pretend_to() -> None:
    """Random means random. It is a different promise from balanced."""
    coin = Treatment("coin", ["heads", "tails"], assign=Assign.random())
    drawn = _fill(coin, [f"visit-{index}" for index in range(8)])

    assert set(drawn) == {"heads", "tails"}
    # The counts are read and ignored: the same visit draws the same level whatever
    # has landed before it, which is what makes a random assignment independent.
    repeated = choose(
        (coin,),
        counts={cell: 99 for cell in cells_of((coin,))},
        seed=_seed,
        study_version_id=_VERSION.study_version_id,
        visit_id="visit-0",
    )
    assert _levels(repeated)["coin"] == drawn[0]


def test_a_blocked_factor_completes_each_block_before_the_next() -> None:
    """Every block holds each level once, so an early stop is still even."""
    arm = Treatment("arm", ["a", "b", "c"], assign=Assign.blocked())
    drawn = _fill(arm, [f"visit-{index}" for index in range(6)])

    assert sorted(drawn[:3]) == ["a", "b", "c"]
    assert sorted(drawn[3:]) == ["a", "b", "c"]


def test_a_block_is_ordered_by_the_study_and_never_by_the_visit() -> None:
    """Two participants in one block must read one order, or it is not a block."""
    arm = Treatment("arm", ["a", "b"], assign=Assign.blocked())
    first = _fill(arm, ["visit-x", "visit-y"])
    second = _fill(arm, ["visit-y", "visit-x"])

    assert first == second


def test_a_stratified_factor_balances_inside_each_stratum() -> None:
    """Left-handers are split evenly, and so are right-handers, separately."""
    handed = Treatment(
        "layout",
        ["wide", "narrow"],
        assign=Assign.stratified(
            by=FieldRef(activity_key="pre", field_key="handedness")
        ),
    )
    left = _fill(handed, [f"l-{index}" for index in range(4)], stratum="left")
    right = _fill(handed, [f"r-{index}" for index in range(4)], stratum="right")

    assert left.count("wide") == 2
    assert right.count("wide") == 2
    assert stratifying_field((handed,)) == ("pre", "handedness")


def test_a_stratum_name_is_folded_from_whatever_was_answered() -> None:
    """A participant answers in their own words; a cell coordinate is a key."""
    assert stratum_of("Left") == "left"
    assert stratum_of("Native speaker") == "native-speaker"
    assert stratum_of(4) == "s-4"
    assert stratum_of("") == "s-none"
    assert stratum_of("!!!") == "s-none"


def test_a_crossed_design_is_one_unit_and_balances_its_cells_jointly() -> None:
    """A factorial study balances combinations; two factors alone do not."""
    difficulty = Treatment("difficulty", ["easy", "hard"])
    partner = Treatment("partner", ["human", "ai"])
    design = Design(cross=[difficulty, partner])

    grouped = units([difficulty, partner], design)
    assert len(grouped) == 1
    assert unit_key(grouped[0]) == "difficulty+partner"
    assert len(cells_of(grouped[0])) == 4

    alone = units([difficulty, partner], None)
    assert [unit_key(one) for one in alone] == ["difficulty", "partner"]


def test_a_crossed_design_fills_every_cell_before_repeating_one() -> None:
    """Four cells and four participants is one each, which is the whole point."""
    difficulty = Treatment("difficulty", ["easy", "hard"])
    partner = Treatment("partner", ["human", "ai"])
    unit = units([difficulty, partner], Design(cross=[difficulty, partner]))[0]

    allocation = None
    seen: list[Cell] = []
    for index in range(4):
        cell = choose(
            unit,
            counts=counts_of(allocation, "participants"),
            seed=_seed,
            study_version_id=_VERSION.study_version_id,
            visit_id=f"visit-{index}",
        )
        seen.append(tuple(sorted(cell)))
        allocation = next_allocation(
            allocation,
            study_version=_VERSION,
            cell=tuple(sorted(cell)),
            unit_counts="participants",
        )
    assert len(set(seen)) == 4


def test_a_counterbalanced_order_uses_the_least_used_order_so_far() -> None:
    """Counterbalancing is balance over orders, counted like any other cell."""
    rounds = Treatment(
        "rounds", ["first", "second"], within=True, order=Order.COUNTERBALANCED
    )
    allocation = None
    drawn: list[str] = []
    for _ in range(4):
        order = counterbalanced_order(
            rounds,
            counts=counts_of(allocation, "participants"),
            seed=_seed,
            version_id=_VERSION.study_version_id,
        )
        drawn.append("-".join(order))
        allocation = next_allocation(
            allocation,
            study_version=_VERSION,
            cell=order_cell(rounds, "-".join(order)),
            unit_counts="participants",
        )
    assert drawn.count("first-second") == 2
    assert drawn.count("second-first") == 2


def test_the_counter_counts_groups_or_participants_as_the_author_asked() -> None:
    """A group of four is one group and four participants; they are not one number."""
    shared = Treatment(
        "layout", ["wide", "narrow"], assign=Assign.balanced(unit=Unit.GROUPS)
    )
    assert counting_unit((shared,)) == "groups"

    allocation = next_allocation(
        None,
        study_version=_VERSION,
        cell=(("layout", "wide"),),
        unit_counts="groups",
    )
    assert allocation.cells[0].groups == 1
    assert allocation.cells[0].participants == 0
    assert counts_of(allocation, "groups") == {(("layout", "wide"),): 1}
    assert counts_of(allocation, "participants") == {(("layout", "wide"),): 0}


def test_the_counter_adds_to_a_cell_it_already_holds() -> None:
    """A second participant in one cell is two, not two cells of one."""
    allocation = next_allocation(
        None, study_version=_VERSION, cell=(("a", "x"),), unit_counts="participants"
    )
    allocation = next_allocation(
        allocation,
        study_version=_VERSION,
        cell=(("a", "x"),),
        unit_counts="participants",
    )
    assert len(allocation.cells) == 1
    assert allocation.cells[0].participants == 2
    assert allocation.version.revision == 2


def test_a_seeded_shuffle_is_the_same_order_everywhere() -> None:
    """Reproducibility is the point: no process entropy reaches a draw."""
    items = ["a", "b", "c", "d"]
    assert shuffled(_seed("one"), items) == shuffled(_seed("one"), items)
    assert shuffled(_seed("one"), items) != shuffled(_seed("two"), items)
    assert sorted(shuffled(_seed("one"), items)) == items
