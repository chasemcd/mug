"""The conversation runtime orders, delivers, and snapshots one chat channel.

These tests drive ``mug.conversation.runtime.ConversationChannel`` against the
in-memory store with a fixed clock and hand-built command contexts, and the pure
``may_activate`` turn-policy decision with plain values. They prove: posts take a
monotonic per-channel sequence; a duplicate post coalesces with no gap; delivery and
snapshot record their own evidence; a segment projects a contiguous run; a restart
rebuilds the sequence counter from the recorded messages; and each turn-policy mode
admits or refuses a model activation as its rule and cap say.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone

from mug.conversation import ConversationChannel, TurnPolicy, may_activate
from mug.kernel import Digest, compute_digest
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_INTERACTION = "interaction_" + _UUID.format(0x200)
_HUMAN = "actor_" + _UUID.format(0x300)
_AGENT = "actor_" + _UUID.format(0x301)


class _Factory:
    """Mint a fresh command context on an aggregate's stream, keyed by its id."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def __call__(self, aggregate_id: str) -> CommandContext:
        n = next(self._counter)
        body = _UUID.format(n)
        return CommandContext.model_validate(
            {
                "command_id": "command_" + body,
                "receipt_id": "receipt_" + body,
                "error_id": "error_" + body,
                "idempotency_key": "idem_" + f"{n:021d}" + "A",
                "event_id": "event_" + body,
                "stream_id": "stream_" + aggregate_id.split("_", 1)[1],
                "producer": {
                    "epoch_id": "prodepoch_" + _UUID.format(9),
                    "sequence": n,
                    "content_digest": _DIGEST.model_dump(mode="json"),
                },
                "aggregate_id": aggregate_id,
                "principal": {"kind": "service", "id": "service_" + _UUID.format(0xA)},
                "recorded_at": "2026-07-22T00:00:00.000000Z",
                "event_data_handling": {"privacy_labels": ["research"]},
            }
        )


def _channel(store: InMemoryStore) -> ConversationChannel:
    return ConversationChannel(
        store=store,
        interaction_id=_INTERACTION,
        channel_key="lobby",
        now=lambda: _START,
    )


def _message_id(seed: str) -> str:
    return "message_" + _UUID.format(int(compute_digest(seed).hex[:8], 16) & 0xFFFF)


def _key(n: int) -> str:
    return "idem_" + f"{n:021d}" + "A"


async def test_posts_take_a_monotonic_per_channel_sequence() -> None:
    """Three posts take sequences one, two, three, in order."""
    store, factory = InMemoryStore(), _Factory()
    channel = _channel(store)

    seqs: list[int] = []
    for i, word in enumerate(("hi", "there", "friend")):
        mid = _message_id(word)
        _, message = await channel.post(
            context=factory(mid),
            message_id=mid,
            author_actor_id=_HUMAN,
            content_digest=compute_digest(word),
            visibility="public",
            idempotency_key=_key(i),
        )
        seqs.append(message.sequence)

    assert seqs == [1, 2, 3]
    assert channel.next_sequence == 4


async def test_a_duplicate_post_coalesces_and_leaves_no_gap() -> None:
    """Re-posting the same message id coalesces; the counter does not skip."""
    store, factory = InMemoryStore(), _Factory()
    channel = _channel(store)
    mid = _message_id("only")

    first, _ = await channel.post(
        context=factory(mid),
        message_id=mid,
        author_actor_id=_HUMAN,
        content_digest=compute_digest("only"),
        visibility="public",
        idempotency_key=_key(0),
    )
    assert first.outcome == "accepted"
    assert channel.next_sequence == 2

    dup, _ = await channel.post(
        context=factory(mid),
        message_id=mid,
        author_actor_id=_HUMAN,
        content_digest=compute_digest("only"),
        visibility="public",
        idempotency_key=_key(1),
    )
    # The duplicate is refused (same aggregate id), so the counter stays at 2.
    assert dup.outcome == "rejected"
    assert channel.next_sequence == 2


async def test_delivery_and_snapshot_record_their_evidence() -> None:
    """A delivery names the message sequence; a snapshot names the seen messages."""
    store, factory = InMemoryStore(), _Factory()
    channel = _channel(store)
    mid = _message_id("hello")

    _, message = await channel.post(
        context=factory(mid),
        message_id=mid,
        author_actor_id=_HUMAN,
        content_digest=compute_digest("hello"),
        visibility="public",
        idempotency_key=_key(0),
    )
    delivery_id = "message_" + _UUID.format(0x5A0)
    _, receipt = await channel.deliver(
        context=factory(delivery_id),
        message=message,
        recipient_actor_id=_AGENT,
        evidence_stream="canonical",
    )
    snapshot_id = "message_" + _UUID.format(0x5B0)
    _, snap = await channel.snapshot(
        context=factory(snapshot_id),
        message_id=mid,
        model_request_digest=compute_digest({"ctx": 1}),
        included_message_ids=[mid],
    )

    assert receipt.delivered_sequence == message.sequence
    assert snap.included_message_ids == [mid]


async def test_a_segment_projects_a_contiguous_run() -> None:
    """A segment builder validates that its span matches its message count."""
    store = InMemoryStore()
    channel = _channel(store)

    segment = channel.segment(
        message_ids=[_message_id("a"), _message_id("b"), _message_id("c")],
        start_sequence=1,
        end_sequence=3,
    )
    assert segment.channel_key == "lobby"
    assert segment.start_sequence == 1
    assert segment.end_sequence == 3


async def test_a_restart_rebuilds_the_sequence_counter() -> None:
    """A fresh channel over the same store recovers the next sequence, no reuse."""
    store, factory = InMemoryStore(), _Factory()
    channel = _channel(store)
    for i, word in enumerate(("one", "two")):
        mid = _message_id(word)
        await channel.post(
            context=factory(mid),
            message_id=mid,
            author_actor_id=_HUMAN,
            content_digest=compute_digest(word),
            visibility="public",
            idempotency_key=_key(i),
        )

    # A fresh channel (a restart) folds the store and continues past the last message.
    revived = _channel(store)
    assert revived.next_sequence == 1  # not yet rebuilt
    assert revived.rebuild(store) == 3
    assert revived.next_sequence == 3


def test_the_turn_policy_modes_admit_or_refuse_activation() -> None:
    """Each activation mode admits or refuses a model turn, under the cap."""
    free = TurnPolicy(
        channel_key="lobby", activation="free", max_model_activations_per_turn=2
    )
    assert may_activate(free, activations_so_far=0) is True
    assert may_activate(free, activations_so_far=2) is False  # cap reached

    mention = TurnPolicy(
        channel_key="lobby", activation="mention", max_model_activations_per_turn=1
    )
    assert may_activate(mention, activations_so_far=0, mentioned=True) is True
    assert may_activate(mention, activations_so_far=0, mentioned=False) is False

    rr = TurnPolicy(
        channel_key="lobby", activation="round-robin", max_model_activations_per_turn=1
    )
    assert may_activate(rr, activations_so_far=0, is_my_turn=True) is True
    assert may_activate(rr, activations_so_far=0, is_my_turn=False) is False

    mod = TurnPolicy(
        channel_key="lobby", activation="moderated", max_model_activations_per_turn=1
    )
    assert may_activate(mod, activations_so_far=0, moderator_cleared=True) is True
    assert may_activate(mod, activations_so_far=0, moderator_cleared=False) is False
