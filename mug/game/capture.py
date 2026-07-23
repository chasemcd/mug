"""Commit a played episode as canonical events on the episode stream.

The stepping loop produces the normalized ``GameTransition`` per frame and the
closing ``EpisodeBoundary`` but holds no store. This service takes the finished
``EpisodeSummary`` and a minted context and commits the whole run in one atomic
append: one event per transition, then the boundary, all on the episode's stream.
Each event binds its own record digest, so the stream is the ordered, canonical
lineage the export later reads. For single-player the accepted stream is the
experienced stream, so there is no rollback and no decision evidence yet.

The service is authority-neutral. The server loop hands it server-authored
transitions; the browser path hands it client-authored transitions with the
same contract. The aggregate records who held authority for the run.
"""

from __future__ import annotations

from typing import Any

from mug.game.runtime import EpisodeSummary
from mug.game.types import EpisodeBoundary, GameTransition
from mug.kernel import (
    CommandReceipt,
    CommandTypeRef,
    Digest,
    TypedObject,
    compute_digest,
)
from mug.runtime import CommandContext, LedgerEvent, commit_capture, result_ref
from mug.storage import Store

_CAPTURE_COMMAND = CommandTypeRef(name="episode.capture", version=0)
_RESULT_SCHEMA_NAME = "mug.command-result.visit-transition"


def _ledger_event(record: GameTransition | EpisodeBoundary) -> LedgerEvent:
    """Bind one transition or boundary as a canonical event to append."""
    return LedgerEvent(
        event_schema=record.schema,
        payload_digest=compute_digest(
            record.model_dump(mode="json", exclude_none=True)
        ),
    )


def _aggregate(
    summary: EpisodeSummary,
    verification: str | None,
    state_hash_chain_digest: Digest | None,
) -> dict[str, Any]:
    """Draft the episode aggregate state the capture commit records.

    A browser capture also records how the server verified the run and, when it
    re-executed the run, the chain digest that binds the verified trajectory. A
    server-run capture passes neither, so the aggregate keeps its original shape.
    """
    boundary = summary.boundary
    aggregate: dict[str, Any] = {
        "episode_id": boundary.episode_id,
        "interaction_id": boundary.interaction_id,
        "channel_key": summary.channel_key,
        "seat_key": summary.seat_key,
        "authority": boundary.authority,
        "frame_count": summary.frames,
        "outcome": boundary.kind,
        "state_hash": boundary.state_hash.model_dump(mode="json"),
    }
    if verification is not None:
        aggregate["verification"] = verification
    if state_hash_chain_digest is not None:
        aggregate["state_hash_chain_digest"] = state_hash_chain_digest.model_dump(
            mode="json"
        )
    return aggregate


async def capture_episode(
    summary: EpisodeSummary,
    *,
    visit_id: str,
    context: CommandContext,
    store: Store,
    verification: str | None = None,
    state_hash_chain_digest: Digest | None = None,
) -> CommandReceipt:
    """Commit an episode's transitions and boundary to the episode stream."""
    events = [_ledger_event(transition) for transition in summary.transitions]
    events.append(_ledger_event(summary.boundary))
    result = TypedObject(
        schema=result_ref(_RESULT_SCHEMA_NAME),
        data={
            "outcome": "captured",
            "visit_id": visit_id,
            "status": summary.boundary.kind,
            "revision": 1,
        },
    )
    return await commit_capture(
        context,
        command=_CAPTURE_COMMAND,
        new_state=_aggregate(summary, verification, state_hash_chain_digest),
        events=events,
        result=result,
        store=store,
    )


__all__ = ["capture_episode"]
