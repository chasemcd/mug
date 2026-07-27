"""What the treatment runtime does when a write does not go its way.

The happy path is covered end to end in `tests/unit/app/test_treatment_flow.py`.
These two tests are about the paths a browser cannot drive: another participant
claiming the same cell in the same instant, and an assignment that does not commit.
Both are guards that decide whether the recorded data is true, so both are held to
what they promise rather than left to be believed.
"""

from __future__ import annotations

import itertools
from typing import Any

from mug.content import Choice, Form, Page, Study
from mug.content.plan import occurrence_id_for
from mug.content.treatments import assign_visit, record_exposures
from mug.gateway import Gateway
from mug.kernel import DataHandlingRef, Digest, PrincipalRef, WireCommandEnvelope
from mug.kernel.refs import StudyVersionRef
from mug.runtime import CommandContext
from mug.storage import InMemoryStore
from mug.visits.assignment import (
    Cell,
    allocation_id_for,
    assignment_id_for,
    assignment_records,
    exposure_id_for,
    next_allocation,
    read_allocation,
    recorded_levels,
)
from mug.visits.design import Assign, Treatment

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_PARTICIPANT = PrincipalRef(
    kind="participant", id="participant_019b6000-0000-7000-8000-0000000000aa"
)
_VISIT = "visit_019b6000-0000-7000-8000-0000000000b1"
_VERSION = StudyVersionRef(
    study_id="study_019b6000-0000-7000-8000-0000000000c1",
    study_version_id="studyver_019b6000-0000-7000-8000-0000000000c2",
    version_number=1,
    manifest_digest=_A_DIGEST,
)


def _study(treatment: Treatment) -> Study:
    return Study(
        Form("consent", Choice("agree", "Do you consent?", ["yes", "no"])),
        Page("instructions", treatment.map({"easy": "slow", "hard": "fast"})),
    )


def _minting(gateway: Gateway) -> Any:
    """Mint one real command context per call, as the transport does."""
    counter = itertools.count(1)

    async def mint(command_name: str, aggregate_id: str) -> CommandContext:
        return gateway.mint(
            WireCommandEnvelope.model_validate(
                {
                    "schema": {
                        "name": "mug.command-envelope",
                        "version": 0,
                        "digest": _A_DIGEST.model_dump(mode="json"),
                    },
                    "protocol_version": "0.1.0",
                    "command": {"name": command_name, "version": 0},
                    "request_id": "request_019b6000-0000-7000-8000-000000000001",
                    "idempotency_key": f"idem_{next(counter):021d}A",
                    "target": {"id": aggregate_id},
                    "payload": {
                        "schema": {
                            "name": "mug.edge.payload",
                            "version": 0,
                            "digest": _A_DIGEST.model_dump(mode="json"),
                        },
                        "data": {"visit_id": _VISIT},
                    },
                }
            ),
            principal=_PARTICIPANT,
            data_handling=_RESEARCH,
        )

    return mint


async def _assign(
    store: InMemoryStore, gateway: Gateway, study: Study
) -> dict[str, str]:
    return await assign_visit(
        study,
        visit_id=_VISIT,
        study_version=_VERSION,
        store=store,
        derive=gateway.derived_id,
        seed=lambda role: gateway.derived_seed("treatment", role),
        now=lambda: "2026-07-26T00:00:00.000000Z",
        mint=_minting(gateway),
    )


class _Contended(InMemoryStore):
    """A store where one other participant claims a cell in the same instant.

    The first write to the counter loses: another claim lands between the read and
    the commit, so the commit's expected revision is stale. This is the race the
    retry exists for, and it cannot be produced from a browser.
    """

    def __init__(self, allocation_id: str, cell: Cell) -> None:
        super().__init__()
        self._allocation_id = allocation_id
        self._cell = cell
        self._raced = False

    async def commit(self, **fields: Any) -> Any:
        if fields.get("aggregate_id") == self._allocation_id and not self._raced:
            self._raced = True
            other = next_allocation(
                None,
                study_version=_VERSION,
                cell=self._cell,
                unit_counts="participants",
            )
            await super().commit(
                command_id="command_019b6000-0000-7000-8000-0000000000ff",
                idempotency_key="idem_" + "f" * 21 + "A",
                aggregate_id=self._allocation_id,
                expected_revision=None,
                new_state=other.model_dump(mode="json", exclude_none=True),
                durability_profile="standard",
            )
        return await super().commit(**fields)


async def test_a_lost_claim_re_reads_the_counter_and_chooses_again() -> None:
    """Two participants at once must not both be given the emptiest cell."""
    difficulty = Treatment(
        "difficulty", {"easy": "slow", "hard": "fast"}, assign=Assign.balanced()
    )
    gateway = Gateway(secret=b"a-shared-deployment-secret------")
    allocation_id = allocation_id_for(gateway.derived_id, _VERSION.study_version_id)
    # The competitor takes "easy". A run that never re-reads would take it too.
    store = _Contended(allocation_id, (("difficulty", "easy"),))

    levels = await _assign(store, gateway, _study(difficulty))

    assert levels == {"difficulty": "hard"}
    allocation = read_allocation(store, allocation_id)
    assert allocation is not None
    assert sum(one.participants for one in allocation.cells) == 2


async def test_an_assignment_that_does_not_commit_exposes_nothing() -> None:
    """A level nobody was assigned must not appear in the data as delivered.

    The participant still sees a page -- the author's first level stands in, because
    turning them away over a write is worse -- but nothing is recorded as having
    been delivered, because it was not a condition.
    """
    difficulty = Treatment(
        "difficulty", {"easy": "slow", "hard": "fast"}, assign=Assign.balanced()
    )
    study = _study(difficulty)
    gateway = Gateway(secret=b"a-shared-deployment-secret------")
    store = InMemoryStore()

    # Something else already holds the aggregate the assignment would create, so the
    # create is refused. It is not an assignment, so no level is read back from it.
    assignment_id = assignment_id_for(gateway.derived_id, _VISIT, "difficulty")
    mint = _minting(gateway)
    await store.commit(
        command_id=(await mint("treatment.other", assignment_id)).command_id,
        idempotency_key="idem_" + "b" * 21 + "A",
        aggregate_id=assignment_id,
        expected_revision=None,
        new_state={"something": "else"},
        durability_profile="standard",
    )

    levels = await _assign(store, gateway, study)
    assert levels == {}
    assert recorded_levels(store, assignment_id) == {}

    occurrence = occurrence_id_for(gateway.derived_id, _VISIT, "instructions")
    written = await record_exposures(
        study,
        activity_key="instructions",
        occurrence_id=occurrence,
        visit_id=_VISIT,
        levels=levels,
        store=store,
        derive=gateway.derived_id,
        now=lambda: "2026-07-26T00:00:00.000000Z",
        mint=mint,
    )
    assert written == []
    assert (
        store.load_aggregate(
            exposure_id_for(gateway.derived_id, occurrence, "difficulty")
        )
        is None
    )


def test_one_assignment_record_is_written_for_each_factor_of_a_unit() -> None:
    """A crossed unit is one decision, and each factor is still its own record."""
    first = Treatment("a", ["x", "y"])
    second = Treatment("b", ["p", "q"])
    written = assignment_records(
        {"a": "x", "b": "q"},
        (first, second),
        visit_id=_VISIT,
        assigned_at="2026-07-26T00:00:00.000000Z",
    )

    assert [one.treatment_key for one in written] == ["a", "b"]
    assert [one.level_key for one in written] == ["x", "q"]
    # A participant assignment names a visit and never a group; the frozen record
    # refuses the other way round, so this is the shape it enforces.
    assert all(one.group_id is None for one in written)
