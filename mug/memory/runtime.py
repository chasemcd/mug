"""The agent-memory runtime: read and compare-and-swap one memory value (API-15).

The API-15 family (``mug.memory``) owns four records -- the ``MemoryScope`` that
declares a scope and its experimental treatment, and the ``MemoryRead``,
``MemoryProposal``, and ``MemoryCommit`` of the compare-and-swap cycle over a memory
value -- but adds no runtime. This module is that runtime. It drives the cycle
through the shared command spine (``mug.runtime``), so a memory's lineage is a
canonical event stream: each commit is one event on the memory's own stream, and the
stream is the full, ordered history of the value.

One rule governs the swap, and it is the whole point of the family: a proposal names
the base version it read, and a commit applies only if that base is still the current
version. Two agents that read the same base and both propose cannot both win; the
second commit reads a newer current version and is refused. The refusal is not a
silent retry -- an agent memory is a scientific record, so a stale proposal raises,
and the caller must re-read and re-propose against the new base. The store's own
revision guard enforces the same swap a second way, so the guarantee holds even under
a race the domain check does not catch.

Provenance travels with the value: a proposal and its commit both name the decision
that produced the new value, so the ledger records not just what the memory became
but which decision changed it.

The runtime is a producer boundary, so the caller injects the clock and mints the
``CommandContext`` for each commit on the memory's stream, exactly as every other
family service takes an already-minted context.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, cast

from mug.kernel import (
    CommandReceipt,
    CommandTypeRef,
    Digest,
    TypedObject,
    UtcInstant,
    VersionStamp,
)
from mug.memory.types import (
    MemoryCommit,
    MemoryProposal,
    MemoryRead,
    MemoryScope,
    MemoryScopeName,
)
from mug.runtime import CommandContext, commit_command
from mug.storage import Store

_MemoryRecord = MemoryScope | MemoryRead | MemoryProposal | MemoryCommit

_DECLARE = CommandTypeRef(name="memory.declare", version=0)
_COMMIT = CommandTypeRef(name="memory.commit", version=0)

_INSTANT = "%Y-%m-%dT%H:%M:%S.%fZ"

# The version of an empty memory: revision 1 with the zero etag. A revision is a
# positive integer, so the empty base is revision 1 and a first commit advances to
# revision 2; the empty memory then has a well-formed base to compare and swap
# against, exactly like a committed one.
_EMPTY_VERSION = VersionStamp(revision=1, etag="sha256:" + "0" * 64)

# The content digest a read of an empty memory names: the zero digest. It marks
# "nothing committed yet", distinct from any real content the proposer will build.
_EMPTY_DIGEST = Digest(algorithm="sha-256", hex="0" * 64)


class StaleMemoryVersion(Exception):
    """A proposal read a base version that is no longer the current version.

    Another commit advanced the memory since the proposer read it, so the swap is
    stale. The runtime refuses it rather than retry, because an agent memory is a
    scientific record; the caller re-reads the current value and re-proposes against
    the new base.
    """


class MemoryLedger:
    """Read and compare-and-swap one agent-memory value through the command spine.

    The ledger holds the injected impurity -- the store and the clock -- and exposes
    the memory cycle: ``current`` and ``read`` project the committed value, ``propose``
    builds a keyed proposal, and ``commit`` applies the swap under the base-version
    check. Each commit takes a ``CommandContext`` the caller minted for the memory's
    aggregate (its ``aggregate_id`` is the memory id).
    """

    def __init__(self, *, store: Store, now: Callable[[], datetime]) -> None:
        self._store = store
        self._now = now

    def current(self, memory_id: str) -> tuple[Digest | None, VersionStamp]:
        """Return the memory's current content digest and version.

        A memory that has never committed returns ``(None, the empty base)``; a
        committed memory returns its latest content digest and the version it reached.
        This is a synchronous projection over the aggregate head, so a proposer reads
        it before it proposes.
        """
        head = self._store.load_aggregate(memory_id)
        if head is None or not _is_commit(head):
            return None, _EMPTY_VERSION
        commit = MemoryCommit.model_validate(head)
        return commit.committed_digest, commit.new_version

    def read(self, *, memory_id: str, scope_kind: MemoryScopeName) -> MemoryRead:
        """Project one read of the memory's current value and base version.

        The read names the content digest a proposer will build on and the base
        version it must swap against. A read of an empty memory names the zero content
        digest and the empty base, so the first proposer has a base to read.
        """
        content, version = self.current(memory_id)
        return MemoryRead(
            memory_id=memory_id,
            scope_kind=scope_kind,
            content_digest=content or _EMPTY_DIGEST,
            base_version=version,
            read_at=self._instant(),
        )

    def propose(
        self,
        *,
        memory_id: str,
        scope_kind: MemoryScopeName,
        proposed_digest: Digest,
        base_version: VersionStamp,
        decision_id: str,
    ) -> MemoryProposal:
        """Build one proposal of a new value, keyed to the base version it read.

        The proposal is pure data; it names the base version so the commit can check
        it, and the decision that produced the value for provenance.
        """
        return MemoryProposal(
            memory_id=memory_id,
            scope_kind=scope_kind,
            proposed_digest=proposed_digest,
            base_version=base_version,
            provenance_decision_id=decision_id,
        )

    async def commit(
        self, *, context: CommandContext, proposal: MemoryProposal
    ) -> tuple[CommandReceipt, MemoryCommit]:
        """Apply the proposal's swap if its base is still current, else refuse.

        The ledger reads the current version. A proposal whose base does not match the
        current version is stale and raises ``StaleMemoryVersion``. A matching base
        commits the swap: the new version advances the revision by one and its etag
        binds the committed content. The commit updates the aggregate against its store
        revision, so a concurrent commit that reads the same base loses the revision
        race and its receipt is a no-effect rejection.
        """
        content, current = self.current(proposal.memory_id)
        if proposal.base_version.revision != current.revision:
            raise StaleMemoryVersion(proposal.memory_id)

        new_version = VersionStamp(
            revision=current.revision + 1,
            etag="sha256:" + proposal.proposed_digest.hex,
        )
        commit = MemoryCommit(
            memory_id=proposal.memory_id,
            scope_kind=proposal.scope_kind,
            committed_digest=proposal.proposed_digest,
            prior_version=current,
            new_version=new_version,
            provenance_decision_id=proposal.provenance_decision_id,
        )
        expected = (
            None if content is None else self._store.revision_of(proposal.memory_id)
        )
        receipt = await commit_command(
            context,
            command=_COMMIT,
            new_state=_state(commit),
            result=_typed(commit),
            store=self._store,
            expected_revision=expected,
        )
        return receipt, commit

    async def declare_scope(
        self, *, context: CommandContext, scope: MemoryScope
    ) -> CommandReceipt:
        """Record one memory scope declaration (its kind, treatment, and owner).

        The scope is its own aggregate (the caller names its id), so an experiment
        records how it treats a scope -- shared, isolated, or ablated -- as canonical
        evidence beside the values in it.
        """
        return await commit_command(
            context,
            command=_DECLARE,
            new_state=_state(scope),
            result=_typed(scope),
            store=self._store,
        )

    def _instant(self) -> UtcInstant:
        """Return the current instant in the canonical wire form."""
        return self._now().astimezone(timezone.utc).strftime(_INSTANT)


def _state(record: _MemoryRecord) -> dict[str, Any]:
    """Dump one memory record to its canonical persisted form."""
    return record.model_dump(mode="json", exclude_none=True)


def _typed(record: _MemoryRecord) -> TypedObject:
    """Wrap one memory record as the command result that carries its own schema."""
    return TypedObject(schema=record.schema, data=_state(record))


def _is_commit(state: Any) -> bool:
    """Return whether an aggregate head is a recorded memory commit."""
    if not isinstance(state, dict):
        return False
    schema = cast("dict[str, Any]", state).get("schema")
    if not isinstance(schema, dict):
        return False
    return cast("dict[str, Any]", schema).get("name") == "mug.api-15.memory-commit"


__all__ = [
    "MemoryLedger",
    "StaleMemoryVersion",
]
