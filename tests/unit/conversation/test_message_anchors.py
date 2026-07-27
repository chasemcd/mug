"""What was said, and where in the game it was said: the anchor tape (NS-06).

A composed activity holds two orderings that must be related without being merged.
The anchor tape is the relation, and like every other artifact in this platform it
is only evidence if it can be checked against the ledger: an anchor naming a frame
the run never reached is not weak evidence, it is a false statement about what the
participant was looking at.

So ``verify_anchors`` is the point of this module, and these are the three ways it
can be lied to.
"""

from __future__ import annotations

import pytest

from mug.conversation.anchors import (
    MessageAnchor,
    anchor_bytes,
    read_anchors,
    verify_anchors,
)

_SAID = "2026-07-27T09:00:00.000000Z"


def _anchor(**overrides: object) -> MessageAnchor:
    fields: dict[str, object] = {
        "message_id": "message_019b6000-0000-7000-8000-000000000001",
        "channel_key": "talk",
        "sequence": 1,
        "episode_id": "episode_019b6000-0000-7000-8000-0000000000a1",
        "frame_number": 12,
        "said_at": _SAID,
    }
    fields.update(overrides)
    return MessageAnchor(**fields)  # pyright: ignore[reportArgumentType]


def _check(anchors: list[MessageAnchor], *, frames: int = 40) -> None:
    verify_anchors(
        anchors,
        episode_id=_anchor().episode_id,
        frames=frames,
        message_ids=[one.message_id for one in anchors],
    )


def test_the_tape_reads_back_exactly_as_it_was_written() -> None:
    """One line per anchored message, and nothing lost in the round trip."""
    anchors = [_anchor(), _anchor(message_id="message_x", sequence=2, frame_number=30)]
    assert read_anchors(anchor_bytes(anchors)) == anchors


def test_an_anchor_within_the_run_verifies() -> None:
    """A message said at a frame the run really reached is what the tape is for."""
    _check([_anchor(frame_number=0), _anchor(frame_number=40)])


def test_a_frame_the_run_never_reached_is_refused() -> None:
    """The run stepped forty frames, so nothing was said at the hundredth."""
    with pytest.raises(ValueError, match="names frame 100 of a run that reached 40"):
        _check([_anchor(frame_number=100)])


def test_a_negative_frame_is_refused() -> None:
    """Before the run began is not a frame of the run."""
    with pytest.raises(ValueError, match="names frame -1"):
        _check([_anchor(frame_number=-1)])


def test_an_anchor_for_a_message_nobody_said_is_refused() -> None:
    """A tape may only place messages the conversation really recorded."""
    with pytest.raises(ValueError, match="a message nobody said"):
        verify_anchors(
            [_anchor()],
            episode_id=_anchor().episode_id,
            frames=40,
            message_ids=[],
        )


def test_an_anchor_belonging_to_another_run_is_refused() -> None:
    """Each run records what was said during **it**, and says which run it is."""
    with pytest.raises(ValueError, match="names episode"):
        verify_anchors(
            [_anchor(episode_id="episode_other")],
            episode_id=_anchor().episode_id,
            frames=40,
            message_ids=[_anchor().message_id],
        )


def test_a_run_nobody_spoke_during_verifies_and_carries_nothing() -> None:
    """Silence is a valid tape. It is simply not recorded, which is not the same."""
    _check([])
    assert anchor_bytes([]) == b""
