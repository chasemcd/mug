"""Where in the game each message was said: the anchor between two orderings.

A composed activity runs a game and a conversation in one interaction, and the two
are not ordered the same way. The game channel is ordered per producer, because
each seat's own frames are in order and no clock puts one seat's frame before
another's. The conversation is ordered totally, because every message goes through
the server. Forcing them into one sequence would invent an order nobody
experienced, which NS-06 refuses in as many words.

So the two are related rather than merged. One ``MessageAnchor`` per message says
which episode was running and which frame the participant had been shown when they
said it. The anchors become one newline-delimited artifact in the
content-addressed store, and the episode aggregate names it beside the trajectory
it already names. That is what lets a replay show the messages against game
progress: read the episode, read its trajectory and its anchors, and lay one along
the other.

The frame number is the render frame. The stepping loop steps the environment once
per rendered frame, so for a server-run episode it is the environment step as well;
an authority that renders and steps at different rates records the frame it showed,
because that is what the participant was looking at when they typed.

Evidence that can not be checked against the ledger is not evidence, which is why
``verify_anchors`` exists: every anchor must name a message the conversation really
recorded, and a frame the episode really reached.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

from mug.storage import jsonl_bytes, read_jsonl

# The media type of a recorded anchor tape: one JSON object per anchored message.
MESSAGE_ANCHOR_MEDIA_TYPE = "application/x-ndjson"


@dataclass(frozen=True)
class MessageAnchor:
    """One message, placed in the game that was running when it was said.

    ``sequence`` is the message's own place in its channel's total order, so an
    anchor is joined to the conversation by the pair (``channel_key``,
    ``sequence``) as well as by ``message_id``.
    """

    message_id: str
    channel_key: str
    sequence: int
    episode_id: str
    frame_number: int
    said_at: str


def anchor_bytes(anchors: Sequence[MessageAnchor]) -> bytes:
    """Serialize the anchors of one episode as one newline-delimited artifact."""
    return jsonl_bytes(
        [
            {
                "message_id": anchor.message_id,
                "channel_key": anchor.channel_key,
                "sequence": anchor.sequence,
                "episode_id": anchor.episode_id,
                "frame_number": anchor.frame_number,
                "said_at": anchor.said_at,
            }
            for anchor in anchors
        ]
    )


def read_anchors(data: bytes) -> list[MessageAnchor]:
    """Read back the anchors of one episode from its recorded artifact."""
    rows: list[dict[str, Any]] = read_jsonl(data)
    return [
        MessageAnchor(
            message_id=str(row["message_id"]),
            channel_key=str(row["channel_key"]),
            sequence=int(row["sequence"]),
            episode_id=str(row["episode_id"]),
            frame_number=int(row["frame_number"]),
            said_at=str(row["said_at"]),
        )
        for row in rows
    ]


def verify_anchors(
    anchors: Sequence[MessageAnchor],
    *,
    episode_id: str,
    frames: int,
    message_ids: Collection[str],
) -> None:
    """Check the anchors against the episode and the conversation they claim.

    An anchor that names a message nobody said, an episode this is not, or a frame
    the run never reached is not weak evidence: it is a false statement about what
    the participant experienced. Raises ``ValueError`` on the first one found.
    """
    known = set(message_ids)
    for anchor in anchors:
        if anchor.episode_id != episode_id:
            raise ValueError(
                f"anchor for {anchor.message_id} names episode "
                f"{anchor.episode_id}, not {episode_id}"
            )
        if anchor.message_id not in known:
            raise ValueError(f"anchor names a message nobody said: {anchor.message_id}")
        if not 0 <= anchor.frame_number <= frames:
            raise ValueError(
                f"anchor for {anchor.message_id} names frame "
                f"{anchor.frame_number} of a run that reached {frames}"
            )


__all__ = [
    "MESSAGE_ANCHOR_MEDIA_TYPE",
    "MessageAnchor",
    "anchor_bytes",
    "read_anchors",
    "verify_anchors",
]
