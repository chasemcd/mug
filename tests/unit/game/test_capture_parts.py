"""A run reports as it plays, so leaving early costs the tail and not the whole.

The client used to hold a browser-run episode in the tab and report it once, at the
end. A participant who closed the tab at frame four hundred of six hundred left no
record of anything -- the report was one command, so it was all or nothing at the
worst moment in the round.

Each reported slice is now staged as a content-addressed artifact and named on a
small progress aggregate. What is checked here is the part of that which has to hold
before any of it is worth doing: the parts are a contiguous prefix, a repeat costs
nothing, the identity a later process needs is in the record it can find, and the
whole run assembles back to exactly what a single report used to carry.
"""

from __future__ import annotations

from typing import Any

import pytest

from mug.admission import AdmissionPolicy, capture_frame_bytes
from mug.game.capture_parts import (
    FRAMES_PER_PART,
    AssembledRun,
    ClaimedPart,
    PartOutOfOrder,
    RunIdentity,
    assemble,
    claim_bytes,
    parse_claim,
    progress_aggregate_id,
    read_progress,
    record_part,
    unsealed_runs,
)
from mug.gateway import Gateway
from mug.kernel import PrincipalRef, WireCommandEnvelope
from mug.kernel.privacy import DataHandlingRef
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_EPISODE = "episode_" + _UUID.format(0xA00)
_INTERACTION = "interaction_" + _UUID.format(0xA01)
_VISIT = "visit_" + _UUID.format(0xA02)
_PARTICIPANT = PrincipalRef(kind="participant", id="participant_" + _UUID.format(0xA03))
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_A_DIGEST = {"algorithm": "sha-256", "hex": "a" * 64}

_RUN = RunIdentity(
    episode_id=_EPISODE,
    interaction_id=_INTERACTION,
    channel_key="play",
    visit_id=_VISIT,
    seat_key="agent-0",
    activity_key="round-one",
    generation=1,
)


def _transition(frame: int) -> dict[str, Any]:
    return {
        "interaction_id": _INTERACTION,
        "channel_key": "play",
        "episode_id": _EPISODE,
        "frame_number": frame,
        "action_digest": _A_DIGEST,
        "state_digest": _A_DIGEST,
        "authority": "browser",
        "applied_decisions": [],
        "recorded_at": "2026-07-28T00:00:00.000000Z",
    }


def _part(first: int, count: int, *, final: bool = False) -> ClaimedPart:
    frames = list(range(first, first + count))
    return ClaimedPart(
        first_frame=first,
        transitions=[_transition(frame) for frame in frames],
        actions=[frame % 3 for frame in frames],
        partner_actions=[frame % 2 for frame in frames],
        final=final,
        boundary=(
            {
                "episode_id": _EPISODE,
                "interaction_id": _INTERACTION,
                "kind": "reset",
                "end_frame_exclusive": first + count - 1,
                "authority": "browser",
                "state_hash": _A_DIGEST,
            }
            if final
            else None
        ),
    )


class _Reporter:
    """One participant's client, reporting parts into a real store."""

    def __init__(self) -> None:
        self.gateway = Gateway()
        self.store = InMemoryStore()
        self._sent = 0

    def _context(self) -> Any:
        self._sent += 1
        envelope = WireCommandEnvelope.model_validate(
            {
                "schema": {
                    "name": "mug.command-envelope",
                    "version": 0,
                    "digest": _A_DIGEST,
                },
                "protocol_version": "0.1.0",
                "command": {"name": "episode.report_part", "version": 0},
                "request_id": "request_" + _UUID.format(1),
                "idempotency_key": f"idem_part_{self._sent:016d}A",
                "target": {"id": progress_aggregate_id(_EPISODE)},
                "payload": {
                    "schema": {
                        "name": "mug.edge.payload",
                        "version": 0,
                        "digest": _A_DIGEST,
                    },
                    "data": {"episode_id": _EPISODE, "part": self._sent},
                },
            }
        )
        return self.gateway.mint(
            envelope, principal=_PARTICIPANT, data_handling=_RESEARCH
        )

    async def send(self, part: ClaimedPart) -> Any:
        return await record_part(
            part,
            run=_RUN,
            context=self._context(),
            store=self.store,
            artifacts=self.store,
            new_artifact_id=lambda: self.gateway.new_id("artifact"),
            new_upload_id=lambda: self.gateway.new_id("upload"),
            now=lambda: "2026-07-28T00:00:0" + str(self._sent % 10) + ".000000Z",
        )


def test_a_claim_survives_being_written_and_read_back() -> None:
    """The staged bytes are the part, so a later process reads what was reported."""
    part = _part(1, 3, final=True)

    assert parse_claim(claim_bytes(part)) == part


async def test_a_run_reported_in_parts_assembles_into_the_whole() -> None:
    """Three reports join back into exactly what one report used to carry."""
    reporter = _Reporter()
    for part in (_part(1, 100), _part(101, 100), _part(201, 50, final=True)):
        assert (await reporter.send(part)).outcome == "accepted"

    progress = read_progress(reporter.store, _EPISODE)
    assert progress is not None
    assert progress.high_water == 250
    assert progress.closed
    assert len(progress.parts) == 3

    run = await assemble(progress, artifacts=reporter.store)
    assert isinstance(run, AssembledRun)
    assert run.frames == 250
    assert len(run.actions) == 250
    assert len(run.partner_actions) == 250
    # The frames are in order and none is missing: a seal must never have to guess.
    assert [one["frame_number"] for one in run.transitions] == list(range(1, 251))
    assert run.closed
    assert run.boundary is not None


async def test_a_participant_who_leaves_early_leaves_what_they_played() -> None:
    """The whole point: an abandoned run holds its frames, not nothing.

    Nothing closed the episode, so the run is open -- but the four hundred frames
    that were played are staged, named, and assemble in order, which is what a seal
    later turns into a recorded episode.
    """
    reporter = _Reporter()
    for first in (1, 101, 201, 301):
        await reporter.send(_part(first, 100))

    progress = read_progress(reporter.store, _EPISODE)
    assert progress is not None
    assert not progress.closed
    assert progress.high_water == 400

    run = await assemble(progress, artifacts=reporter.store)
    assert run.frames == 400
    assert not run.closed
    assert run.boundary is None


async def test_a_repeated_part_costs_nothing() -> None:
    """A client that did not see its acknowledgement sends the same part again."""
    reporter = _Reporter()
    await reporter.send(_part(1, 100))
    before = read_progress(reporter.store, _EPISODE)
    assert before is not None

    again = await reporter.send(_part(1, 100))
    assert again.outcome == "accepted"

    after = read_progress(reporter.store, _EPISODE)
    assert after is not None
    # Not merely the same high-water mark: no second artifact was staged, so the
    # run did not quietly grow a duplicate of its own first hundred frames.
    assert len(after.parts) == len(before.parts) == 1
    assert after.high_water == before.high_water == 100


async def test_a_part_that_does_not_continue_the_run_is_refused() -> None:
    """A gap would make the seal guess, and an overlap would double-count."""
    reporter = _Reporter()
    await reporter.send(_part(1, 100))

    with pytest.raises(PartOutOfOrder, match="contiguous"):
        await reporter.send(_part(150, 50))
    with pytest.raises(PartOutOfOrder, match="overlap"):
        await reporter.send(_part(50, 100))

    progress = read_progress(reporter.store, _EPISODE)
    assert progress is not None
    assert progress.high_water == 100


async def test_the_seal_needs_no_session_to_find_what_it_seals() -> None:
    """A sweep after a restart has an episode id and nothing else.

    So the run's identity is on the record it can find, and the record is found by
    deriving its address rather than by holding an index.
    """
    reporter = _Reporter()
    await reporter.send(_part(1, 100))

    # A second process, with no memory of the participant.
    cold = read_progress(reporter.store, _EPISODE)
    assert cold is not None
    assert cold.run == _RUN

    waiting = unsealed_runs(reporter.store, before="2026-07-29T00:00:00.000000Z")
    assert [one.run.episode_id for one in waiting] == [_EPISODE]
    # A run touched after the cutoff is still being played, and is left alone.
    assert unsealed_runs(reporter.store, before="2026-07-27T00:00:00.000000Z") == []


def test_one_part_fits_the_transport_that_has_to_carry_it() -> None:
    """The reporting cadence must fit the frame bound, or nothing is ever reported.

    This is the guard on a number that has already caused one outage. A report
    larger than the transport accepts is refused before it is parsed, and the
    participant finds out at the end of the round with nothing recorded. Raising
    ``FRAMES_PER_PART`` past what a frame may hold would bring that back, silently.
    """
    assert capture_frame_bytes(FRAMES_PER_PART) <= AdmissionPolicy().max_frame_bytes


async def test_a_run_that_divides_evenly_closes_on_a_part_with_no_frames() -> None:
    """The closing part carries the boundary, and sometimes nothing else.

    A run whose length is a multiple of the reporting cadence has already reported
    every frame by the time it ends, so the part that closes it has only the
    boundary to say. Refusing that refused the *last* report of every such run --
    the round played to its own limit, which is the ordinary way a timed game ends.
    """
    reporter = _Reporter()
    await reporter.send(_part(1, 100))
    await reporter.send(_part(101, 100))

    closing = ClaimedPart(
        first_frame=201,
        transitions=[],
        actions=[],
        partner_actions=[],
        final=True,
        boundary={
            "episode_id": _EPISODE,
            "interaction_id": _INTERACTION,
            "kind": "reset",
            "end_frame_exclusive": 200,
            "authority": "browser",
            "state_hash": _A_DIGEST,
        },
    )
    assert (await reporter.send(closing)).outcome == "accepted"

    progress = read_progress(reporter.store, _EPISODE)
    assert progress is not None
    assert progress.closed
    # The frames it already had, and not one more.
    assert progress.high_water == 200

    run = await assemble(progress, artifacts=reporter.store)
    assert run.frames == 200
    assert run.closed
    assert run.boundary is not None
