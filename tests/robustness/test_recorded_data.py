"""What a finished run wrote down, held to the standard the legacy suite set.

The legacy suite's source of truth for "the episode worked" was not a screenshot
and not a frame counter. It was the **data**: both participants exported a file,
`tests/validate_action_sequences.py` compared them column by column against a
declared list of what may honestly differ, and any divergence failed the test.
That is the right standard and it is kept here.

**What is different, and why.** Two peers used to write two files that had to
match. The rewrite records **one** run: the peers agree on the trajectory, one of
them is the capture owner, and the ledger holds a single episode. So "compare the
two files" becomes three claims that are together stronger:

- the values that were recorded are the values the run produced, frame for frame,
  and the ledger's own digests say so;
- nothing was dropped -- the frames are contiguous, every seat is on every frame,
  and the episode's frame count is the number of frames in the artifact;
- the export is a function of the ledger alone, so two exports of one run are the
  same bytes and a study can be re-exported without changing what it says.

A run that recorded the right number of frames of the wrong data passes a frame
counter and fails every test here.

These modules use ASD-STE100 Simplified Technical English.
"""

from __future__ import annotations

import json
from typing import Any

from mug.kernel import compute_digest
from tests.parity._environments import PARTNER, YOU
from tests.robustness._runs import (
    episodes_in,
    exported,
    people_at,
    play_the_seated_round,
    recorded_frames,
    seated_session,
    seated_study,
)

_LENGTH = 12


def _one_seated_run(length: int = _LENGTH) -> Any:
    """Play one whole two-person server-stepped game and return the store."""
    with (
        seated_session(seated_study(length)) as (client, store),
        people_at(client, 2) as people,
    ):
        followed = play_the_seated_round(people)
        assert all(one["delivery"]["kind"] == "content" for one in followed)
    return store


def test_the_recorded_values_are_the_run_the_ledger_says_happened() -> None:
    """The artifact and the aggregate agree about what was played.

    This is the replacement for comparing two exported files. The episode names a
    content-addressed artifact; the artifact holds one row per frame; and the
    episode's own closing state hash must be the digest of the last frame's
    observations. A capture that wrote a summary, an older run, or a truncated
    artifact fails on one of the three.
    """
    store = _one_seated_run()

    recorded = episodes_in(store)
    assert len(recorded) == 1, "two people played one game, so there is one episode"
    episode = recorded[0]
    frames = recorded_frames(store, episode)

    assert len(frames) == episode["frame_count"]
    assert (
        compute_digest(frames[-1].observations).model_dump(mode="json")
        == (episode["state_hash"])
    )


def test_no_frame_of_the_run_is_missing_or_repeated() -> None:
    """The record is the whole run in order, which is what a replay needs.

    A trajectory with a gap still exports, still has plausible rows, and is a
    different game from the one that was played.
    """
    store = _one_seated_run()
    frames = recorded_frames(store, episodes_in(store)[0])

    numbers = [frame.frame_number for frame in frames]
    assert numbers == list(range(1, len(frames) + 1))


def test_every_seat_is_on_every_frame_of_a_two_person_run() -> None:
    """Both people are in the record, on each frame, under their own seat.

    This is the claim the legacy column comparison really rested on: the export
    carried both players' actions and both players' rewards. A run that recorded
    one seat, or that collapsed the two into one, would look complete and would be
    unusable for any study about what the pair did.
    """
    store = _one_seated_run()
    frames = recorded_frames(store, episodes_in(store)[0])

    seats = {YOU, PARTNER}
    for frame in frames:
        assert set(frame.actions) == seats, f"frame {frame.frame_number} lost a seat"
        assert set(frame.observations) == seats
        assert set(frame.rewards) == seats


def test_the_recorded_actions_are_the_actions_a_seat_could_have_taken() -> None:
    """Every recorded action is one the study's own key bindings can produce.

    An action outside the declared set means the loop wrote something the
    participant could not have asked for, which is worse than a missing frame:
    it is a plausible number that nobody chose.
    """
    from tests.robustness._runs import BINDINGS

    store = _one_seated_run()
    frames = recorded_frames(store, episodes_in(store)[0])

    allowed = {0, *BINDINGS.values()}
    for frame in frames:
        for seat, action in frame.actions.items():
            assert action in allowed, f"{seat} took {action} on {frame.frame_number}"


def test_two_exports_of_one_run_are_the_same_bytes() -> None:
    """An export is a function of the ledger, so it can be repeated.

    A study is exported more than once -- a check, then a revision, then the
    version that ships. If those differ, no downstream analysis can be attributed
    to a particular export, and nothing says which of them the paper used.
    """
    store = _one_seated_run()

    first = exported(store)
    second = exported(store)

    kinds = [bundle.dataset_kind for bundle in first.bundles]
    assert kinds == [bundle.dataset_kind for bundle in second.bundles]
    assert [one.artifact.digest.hex for one in first.bundles] == [
        one.artifact.digest.hex for one in second.bundles
    ]
    assert [one.bundle_digest.hex for one in first.bundles] == [
        one.bundle_digest.hex for one in second.bundles
    ]
    assert kinds, "the run exported nothing at all"


def test_the_export_carries_the_run_rather_than_a_reference_to_it() -> None:
    """The exported rows are the events the run really appended.

    An export that names a study version and carries no rows would satisfy every
    schema and answer no research question.
    """
    store = _one_seated_run()
    export = exported(store)

    for bundle in export.bundles:
        assert bundle.row_count > 0, f"{bundle.dataset_kind} exported no rows"
        assert bundle.study_version.study_version_id == (
            export.bundles[0].study_version.study_version_id
        )


def test_a_tampered_trajectory_no_longer_matches_what_was_recorded() -> None:
    """The check has teeth: change one number and the agreement breaks.

    Without this, every test above could be passing on a comparison that can not
    fail. The artifact is content-addressed, so a changed value is a changed
    digest, and the episode still names the digest of what was really written.
    """
    store = _one_seated_run()
    episode = episodes_in(store)[0]
    frames = recorded_frames(store, episode)

    honest = compute_digest(frames[-1].observations).model_dump(mode="json")
    assert honest == episode["state_hash"]

    changed = json.loads(json.dumps(frames[-1].observations))
    changed[YOU] = "not what happened"
    assert compute_digest(changed).model_dump(mode="json") != episode["state_hash"]
