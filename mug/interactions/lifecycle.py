"""Record how an interaction started, how it ended, and why.

``Interaction`` has a status -- forming, active, completed, aborted -- and nothing
committed one to the store, so a study could not answer the questions an operator
asks every day: how many people are playing right now, how many finished, and what
happened to the ones who did not. There were no terminal reasons at all, so
"aborted" was as much as anyone could say.

This module is the projection. It is deliberately two things and no more.

**The frozen record is the head.** The aggregate commits the API-06 ``Interaction``
with one runtime key beside it, ``lifecycle``, holding what the record has no field
for: when it opened, when it closed, the reason it closed, and what became of each
member. Same shape as the visit plan and its pointer.

**A terminal reason is a closed set.** Free text would become free text, and a study
that wants to know how many sessions ended in partner loss would be counting
strings. The seven reasons below are what can actually happen to an interaction, and
a caller that means something else is refused rather than accommodated.

**Nothing here is an operator's answer.** The projection carries interaction ids,
visit ids, actor ids, and reasons -- all pseudonymous, all internal. No external
identity, no credential, and no participant text ever reaches it, which is what
makes it safe to read without authentication inside a deployment and what parity
fixture 10 asks for.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Annotated, Any, Final, Literal

from pydantic import Field

from mug.interactions.types import ChannelInstance, Interaction, Membership
from mug.kernel import (
    CommandTypeRef,
    TypedObject,
    UtcInstant,
    VersionStamp,
    etag,
)
from mug.kernel._base import KernelModel
from mug.kernel.ids import ActorInstanceId, VisitId
from mug.runtime import CommandContext, commit_command
from mug.storage import Store

# Why an interaction ended. A closed set, because counting reasons is the whole
# point of recording them.
TERMINAL_REASONS: Final[tuple[str, ...]] = (
    "completed",
    "partner_lost",
    "excluded",
    "abandoned",
    "timed_out",
    "operator_stopped",
    "error",
)

# Which reasons mean the interaction did what it was for. The rest are outcomes a
# study has to be able to see, not failures to hide.
_SUCCEEDED: Final[frozenset[str]] = frozenset({"completed"})

_OPEN = CommandTypeRef(name="interaction.open", version=0)
_FINALIZE = CommandTypeRef(name="interaction.finalize", version=0)
_CHANNEL = CommandTypeRef(name="interaction.channel", version=0)
_MEMBERSHIP = CommandTypeRef(name="interaction.membership", version=0)


def _no_members() -> list[MemberDisposition]:
    """Return an empty, typed member list for an interaction's default."""
    return []


class MemberDisposition(KernelModel):
    """What became of one member of an interaction, and when."""

    visit_id: VisitId
    actor_id: ActorInstanceId | None = None
    seat_key: Annotated[str, Field(max_length=128)] | None = None
    left_at: UtcInstant | None = None
    reason: Literal[
        "completed",
        "partner_lost",
        "excluded",
        "abandoned",
        "timed_out",
        "operator_stopped",
        "error",
    ] | None = None


class Lifecycle(KernelModel):
    """The runtime half of an interaction record: its span and its ending.

    This is the ``lifecycle`` key beside the frozen ``Interaction``, holding what
    changes as the interaction runs and what the frozen record has no field for.
    """

    activity_key: Annotated[str, Field(max_length=128)] | None = None
    opened_at: UtcInstant
    closed_at: UtcInstant | None = None
    terminal_reason: Literal[
        "completed",
        "partner_lost",
        "excluded",
        "abandoned",
        "timed_out",
        "operator_stopped",
        "error",
    ] | None = None
    members: Annotated[list[MemberDisposition], Field(max_length=64)] = Field(
        default_factory=_no_members
    )
    version: VersionStamp


def lifecycle_of(state: Mapping[str, Any] | None) -> Lifecycle | None:
    """Return the lifecycle held beside a committed interaction, or None."""
    if not isinstance(state, Mapping):
        return None
    found = state.get("lifecycle")
    if not isinstance(found, Mapping):
        return None
    try:
        return Lifecycle.model_validate(found)
    except ValueError:
        return None


def interaction_of(state: Mapping[str, Any] | None) -> Interaction | None:
    """Return the frozen interaction committed on one aggregate, or None."""
    if not isinstance(state, Mapping):
        return None
    body = {key: value for key, value in state.items() if key != "lifecycle"}
    try:
        return Interaction.model_validate(body)
    except ValueError:
        return None


def _aggregate(interaction: Interaction, lifecycle: Lifecycle) -> dict[str, Any]:
    """Draft the state one interaction aggregate commits."""
    return {
        **interaction.model_dump(mode="json", exclude_none=True),
        "lifecycle": lifecycle.model_dump(mode="json", exclude_none=True),
    }


async def open_interaction(
    interaction: Interaction,
    *,
    activity_key: str | None,
    opened_at: str,
    context: CommandContext,
    store: Store,
) -> bool:
    """Commit that one interaction has opened, at the activity it belongs to.

    A repeated open is refused by the store, which is the right answer: the first
    opening is when it opened, and a reconnection does not restart an interaction.
    """
    body: dict[str, Any] = {
        "activity_key": activity_key,
        "opened_at": opened_at,
        "members": [
            MemberDisposition(visit_id=visit_id).model_dump(  # pyright: ignore[reportArgumentType]
                mode="json", exclude_none=True
            )
            for visit_id in interaction.visit_ids
        ],
    }
    lifecycle = Lifecycle(
        **body,  # pyright: ignore[reportArgumentType]
        version=VersionStamp(revision=1, etag=etag(body)),
    )
    receipt = await commit_command(
        context,
        command=_OPEN,
        new_state=_aggregate(interaction, lifecycle),
        result=TypedObject(
            schema=interaction.schema,
            data={
                "outcome": "opened",
                "interaction_id": interaction.interaction_id,
                "status": interaction.status,
                "revision": 1,
            },
        ),
        store=store,
    )
    return receipt.outcome == "accepted"


def membership_id_for(
    derive: Callable[[str, str], str],
    interaction_id: str,
    actor_id: str,
    channel_key: str,
) -> str:
    """Return the aggregate one actor's access to one channel is recorded under.

    API-06 mints no identifier kind for a membership, so it borrows the
    ``interaction`` kind under a derived seed -- the same substitution the
    monitoring decision makes, and for the same reason: the record is real, the
    identifier kind for it is not.
    """
    seed = f"membership:{interaction_id}:{actor_id}:{channel_key}"
    return derive("interaction", seed)


async def record_channel(
    instance: ChannelInstance, *, context: CommandContext, store: Store
) -> bool:
    """Commit one live channel of an interaction, with its ordering guarantee."""
    receipt = await commit_command(
        context,
        command=_CHANNEL,
        new_state=instance.model_dump(mode="json", exclude_none=True),
        result=TypedObject(
            schema=instance.schema,
            data={
                "outcome": "opened",
                "channel_instance_id": instance.channel_instance_id,
                "channel_key": instance.channel_key,
            },
        ),
        store=store,
    )
    return receipt.outcome == "accepted"


async def record_membership(
    membership: Membership, *, context: CommandContext, store: Store
) -> bool:
    """Commit one actor's access to one channel of an interaction.

    Access ``none`` is recorded as well as ``read_write``, and that is the point:
    a study that gives one participant a coaching channel has to be able to show
    that the other participant did not have it. Silence is not evidence of
    exclusion; a recorded ``none`` is.
    """
    receipt = await commit_command(
        context,
        command=_MEMBERSHIP,
        new_state=membership.model_dump(mode="json", exclude_none=True),
        result=TypedObject(
            schema=membership.schema,
            data={
                "outcome": "recorded",
                "actor_id": membership.actor_id,
                "channel_key": membership.channel_key,
                "access": membership.access,
            },
        ),
        store=store,
    )
    return receipt.outcome == "accepted"


async def finalize_interaction(
    *,
    interaction_id: str,
    reason: str,
    closed_at: str,
    context: CommandContext,
    store: Store,
    left: Sequence[str] = (),
) -> bool:
    """Close one interaction with a recorded reason, and say who left.

    ``left`` names the visits the reason applies to -- the partner who dropped, the
    participant who was excluded. Everyone else is recorded as having finished the
    interaction, because they did: whatever ended it, it did not end for them by
    their own doing, and an analysis that cannot tell those apart cannot tell a
    dropout from a bystander.

    An interaction that has already closed is left as it stands. The first ending is
    the ending, and a second reason written over it would be a story about the
    process rather than about the participants.
    """
    if reason not in TERMINAL_REASONS:
        raise ValueError(f"{reason!r} is not a terminal reason an interaction has")
    raw = store.load_aggregate(interaction_id)
    interaction = interaction_of(raw)
    current = lifecycle_of(raw)
    if interaction is None or current is None or current.closed_at is not None:
        return False
    departed = set(left)
    body: dict[str, Any] = {
        "activity_key": current.activity_key,
        "opened_at": current.opened_at,
        "closed_at": closed_at,
        "terminal_reason": reason,
        "members": [
            member.model_copy(
                update={
                    "left_at": closed_at,
                    "reason": reason if member.visit_id in departed else "completed",
                }
            ).model_dump(mode="json", exclude_none=True)
            for member in current.members
        ],
    }
    lifecycle = Lifecycle(
        **body,  # pyright: ignore[reportArgumentType]
        version=VersionStamp(
            revision=current.version.revision + 1, etag=etag(body)
        ),
    )
    closed = interaction.model_copy(
        update={
            "status": "completed" if reason in _SUCCEEDED else "aborted",
            "version": VersionStamp(
                revision=interaction.version.revision + 1,
                etag=etag(body),
            ),
        }
    )
    receipt = await commit_command(
        context,
        command=_FINALIZE,
        new_state=_aggregate(closed, lifecycle),
        result=TypedObject(
            schema=interaction.schema,
            data={
                "outcome": reason,
                "interaction_id": interaction_id,
                "status": closed.status,
                "revision": closed.version.revision,
            },
        ),
        store=store,
        expected_revision=current.version.revision,
    )
    return receipt.outcome == "accepted"


class InteractionView(KernelModel):
    """One row of the operator's read-only view of the interactions.

    Every field is internal and pseudonymous. There is no external identity, no
    credential, no participant text, and no study content in it, which is what lets
    it be read without becoming a second way to reach the data.
    """

    interaction_id: Annotated[str, Field(max_length=61)]
    status: Literal["forming", "active", "completed", "aborted"]
    activity_key: Annotated[str, Field(max_length=128)] | None = None
    channels: Annotated[list[str], Field(max_length=32)]
    participants: int
    opened_at: UtcInstant
    closed_at: UtcInstant | None = None
    terminal_reason: Annotated[str, Field(max_length=64)] | None = None


def view_of(state: Mapping[str, Any] | None) -> InteractionView | None:
    """Return the operator's row for one committed interaction, or None."""
    interaction = interaction_of(state)
    lifecycle = lifecycle_of(state)
    if interaction is None or lifecycle is None:
        return None
    return InteractionView(
        interaction_id=interaction.interaction_id,
        status=interaction.status,
        activity_key=lifecycle.activity_key,
        channels=list(interaction.channels),
        participants=len(interaction.visit_ids),
        opened_at=lifecycle.opened_at,
        closed_at=lifecycle.closed_at,
        terminal_reason=lifecycle.terminal_reason,
    )


def operator_view(store: Store) -> list[InteractionView]:
    """Return every interaction this deployment has recorded, newest first.

    Live and completed together, because an operator's first question is "what is
    happening", and the answer is only useful beside "what happened".
    """
    rows = [
        view
        for aggregate_id, state in store.scan_aggregates()
        if aggregate_id.startswith("interaction_")
        and (view := view_of(state)) is not None
    ]
    return sorted(
        rows, key=lambda row: (row.opened_at, row.interaction_id), reverse=True
    )


__all__ = [
    "TERMINAL_REASONS",
    "InteractionView",
    "Lifecycle",
    "MemberDisposition",
    "finalize_interaction",
    "interaction_of",
    "lifecycle_of",
    "open_interaction",
    "operator_view",
    "view_of",
]
