"""Participant state that outlives the activity that wrote it (API-04).

A study is a sequence of activities and a participant meets them one at a time.
Anything they carry from one to the next -- what they chose, what a page worked
out, how far they got -- has to live somewhere the next activity can read. Legacy
kept one mutable blob per session and let the last write win. This keeps
**namespaces**: each one is declared by the study, versioned on its own, and says
who may read it and who may write it.

**A namespace is declared or it does not exist.** A page cannot invent one, because
a store no study declared is a store nobody analyses and nobody finds in an export.
The declaration carries the policy too, so "the participant may write their notes
but not their score" is a study's to state and this module's to enforce. R-13
distrusts what a client asserts, and a value a page could write is a value a
participant could choose.

**A write names the version it read.** Two open tabs are the ordinary case rather
than the exceptional one, and last-write-wins silently loses whichever the
participant thought they were using. A stale write is refused and told what it lost
to, so the caller can re-read and decide.

**The value is an artifact; the record is a pointer.** ``StateDocument`` carries a
content digest and no content, so the ledger stays payload-free. The bytes go to the
content-addressed store under an identifier derived from their own digest, which is
what makes one value written twice one stored object.

**Carrying across parts is the point** (NS-08). A participant who comes back for the
second part of a study enters a new visit under the same enrollment. What they built
up in the first part is carried into it -- but **only for the namespaces the second
part declares**. A part that does not ask for a namespace does not receive it, and
that is a rule about consent and scope rather than an optimisation: state a later
part never declared is state its participants were never told it would read.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from mug.kernel import (
    CommandTypeRef,
    DataHandlingRef,
    Digest,
    SchemaRef,
    VersionStamp,
    etag,
)
from mug.runtime import (
    CommandContext,
    CommandReceipt,
    TypedObject,
    commit_command,
)
from mug.storage import ArtifactStore, Store, digest_of, stage_artifact
from mug.visits.types import StateDocument

# The media type of one namespace's stored value: one JSON object.
STATE_MEDIA_TYPE = "application/json"

_NAMESPACE = re.compile(r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$")

_WRITE = CommandTypeRef(name="state.write", version=0)

_RESEARCH = DataHandlingRef(privacy_labels=["research"])

# Who a namespace admits. ``participant`` means the page they are looking at may do
# it; ``study`` means only the platform may, on the study's behalf.
Party = Literal["participant", "study"]


@dataclass(frozen=True)
class State:
    """One namespace of participant state that outlives the activity writing it.

    ``key`` names it, and that name is what a page and an export both use.
    ``write`` says who may change it and ``read`` who may see it. Both default to
    the participant, because the ordinary case is a page keeping something for a
    later page; a study that keeps a running score the participant must not see
    writes ``State("score", write="study", read="study")``.
    """

    key: str
    write: Party = "participant"
    read: Party = "participant"

    def __post_init__(self) -> None:
        if not _NAMESPACE.match(self.key):
            raise ValueError(
                f"the state namespace {self.key!r} is not a name a record can carry:"
                " lower-case words joined by one '-', '_' or '.'"
            )


@dataclass(frozen=True)
class StateWrite:
    """What one write left behind: the new value, and the receipt that proves it."""

    value: StateValue
    receipt: CommandReceipt


@dataclass(frozen=True)
class StateValue:
    """What one namespace holds, and the revision a write to it must name."""

    namespace: str
    value: dict[str, Any]
    revision: int


class StaleState(Exception):
    """A write named a revision that is no longer the current one.

    ``current`` is what the namespace holds now, so the caller re-reads from the
    exception rather than racing the store again.
    """

    def __init__(self, current: StateValue) -> None:
        super().__init__(
            f"the namespace {current.namespace!r} moved on to revision "
            f"{current.revision}"
        )
        self.current = current


class UndeclaredState(Exception):
    """A namespace nobody declared, or one this party may not touch."""


# Mint one derived identifier from a kind and the words that fix it.
DeriveId = Callable[[str, str], str]

# Mint one fresh identifier of a kind.
NewId = Callable[[str], str]

# Read the current UTC instant in the canonical wire form.
Now = Callable[[], str]


def declared(states: Iterable[State]) -> dict[str, State]:
    """Return the declared namespaces by key, refusing one declared twice."""
    by_key: dict[str, State] = {}
    for state in states:
        if state.key in by_key:
            raise ValueError(f"the state namespace {state.key!r} is declared twice")
        by_key[state.key] = state
    return by_key


def readable(
    states: Mapping[str, State], party: Party = "participant"
) -> tuple[str, ...]:
    """Return the namespaces one party may read, in the order they were declared."""
    return tuple(key for key, state in states.items() if state.read == party)


def _admits(
    states: Mapping[str, State], namespace: str, party: Party, doing: str
) -> State:
    """Return the declared namespace, or refuse the party that may not do this."""
    state = states.get(namespace)
    if state is None:
        known = ", ".join(sorted(states)) or "none"
        raise UndeclaredState(
            f"the study declares no state namespace {namespace!r} (it declares: "
            f"{known})"
        )
    allowed = state.write if doing == "write" else state.read
    if allowed != party:
        raise UndeclaredState(
            f"the {party} may not {doing} the state namespace {namespace!r}"
        )
    return state


def state_id(derive: DeriveId, visit_id: str, namespace: str) -> str:
    """Return the aggregate one visit's namespace lives on.

    It is derived, so a later connection, a later process, and a replay all find
    the state that exists rather than opening a second one beside it. A
    ``StateDocument`` carries no identifier of its own -- it is identified by the
    visit and the namespace -- and API-04 mints no identifier kind for one, so it
    borrows the ``visitplan`` kind under a derived seed. That is the same
    substitution a membership makes, for the same reason: the record is real and
    the identifier kind for it is not.
    """
    return derive("visitplan", f"state:{visit_id}:{namespace}")


def _artifact_id(derive: DeriveId, digest: Digest) -> str:
    """Return the object identifier one value's own digest gives it.

    The value is content-addressed, so the identifier comes from the bytes rather
    than from a counter: the same value written by two visits is one object, and a
    reader that holds the digest can find it without the record naming a location.
    """
    return derive("artifact", f"state:{digest.hex}")


def _value_bytes(value: Mapping[str, Any]) -> bytes:
    """Serialize one namespace's value canonically, so equal values are one object."""
    return json.dumps(dict(value), separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _content_schema(namespace: str) -> SchemaRef:
    """Return the pinned shape one namespace's value claims to have.

    A study declares the namespace, not a schema for what goes in it, so the
    reference names the namespace itself. It is what an export reads to group the
    values that belong together, and what a later study version bumps when the
    shape it keeps there changes.
    """
    name = f"mug.state.{namespace}"
    return SchemaRef(
        name=name,
        version=1,
        digest=Digest(
            algorithm="sha-256", hex=hashlib.sha256(name.encode()).hexdigest()
        ),
    )


async def read_state(
    store: Store,
    *,
    derive: DeriveId,
    visit_id: str,
    namespace: str,
) -> StateValue:
    """Return what one visit's namespace holds, or an empty value at revision zero.

    A namespace nobody has written yet reads as empty rather than as missing, so a
    page's first read and its hundredth are the same shape.
    """
    head = store.load_aggregate(state_id(derive, visit_id, namespace))
    if head is None:
        return StateValue(namespace=namespace, value={}, revision=0)
    document = cast("dict[str, Any]", head)
    digest = cast("dict[str, Any]", document["content_digest"])
    version = cast("dict[str, Any]", document["version"])
    data = await cast("ArtifactStore", store).read_artifact(
        _artifact_id(derive, Digest(**digest))
    )
    value = cast("dict[str, Any]", json.loads(data.decode("utf-8")))
    return StateValue(
        namespace=namespace, value=value, revision=int(version["revision"])
    )


async def write_state(
    store: Store,
    *,
    context: CommandContext,
    states: Mapping[str, State],
    derive: DeriveId,
    new_id: NewId,
    now: Now,
    visit_id: str,
    namespace: str,
    value: Mapping[str, Any],
    revision: int,
    by: Party = "participant",
) -> StateWrite:
    """Write one namespace, refusing a stale revision and an undeclared name.

    ``revision`` is what the writer read. Zero is what a namespace nobody has
    written yet reads as, so a first write and a later one are the same call.
    """
    _admits(states, namespace, by, "write")
    current = await read_state(
        store, derive=derive, visit_id=visit_id, namespace=namespace
    )
    if current.revision != revision:
        raise StaleState(current)
    return await _commit(
        store,
        context=context,
        derive=derive,
        new_id=new_id,
        now=now,
        visit_id=visit_id,
        namespace=namespace,
        value=value,
        revision=revision + 1,
    )


async def _commit(
    store: Store,
    *,
    context: CommandContext,
    derive: DeriveId,
    new_id: NewId,
    now: Now,
    visit_id: str,
    namespace: str,
    value: Mapping[str, Any],
    revision: int,
) -> StateWrite:
    """Stage one namespace's bytes and commit the pointer that names them."""
    data = _value_bytes(value)
    artifact = await stage_artifact(
        cast("ArtifactStore", store),
        data=data,
        media_type=STATE_MEDIA_TYPE,
        new_artifact_id=lambda: _artifact_id(derive, digest_of(data)),
        new_upload_id=lambda: new_id("upload"),
        now=now,
        data_handling=_RESEARCH,
    )
    body: dict[str, Any] = {
        "visit_id": visit_id,
        "namespace": namespace,
        "content_schema": _content_schema(namespace).model_dump(
            mode="json", exclude_none=True
        ),
        "content_digest": artifact.digest.model_dump(mode="json", exclude_none=True),
    }
    document = StateDocument(
        **body, version=VersionStamp(revision=revision, etag=etag(body))
    )
    receipt = await commit_command(
        context,
        command=_WRITE,
        # The first write creates the aggregate and every later one updates it, so
        # the store's own optimistic check names the revision this write read. The
        # namespace's revision and the aggregate's move together, which is what
        # makes the refusal one check rather than two that can disagree.
        expected_revision=None if revision <= 1 else revision - 1,
        new_state=document.model_dump(mode="json", exclude_none=True),
        result=TypedObject(
            schema=document.schema,
            data={
                "outcome": "written",
                "namespace": namespace,
                "revision": revision,
            },
        ),
        store=store,
    )
    return StateWrite(
        value=StateValue(namespace=namespace, value=dict(value), revision=revision),
        receipt=receipt,
    )


async def carry_state(
    store: Store,
    *,
    new_context: Callable[[str], CommandContext],
    states: Mapping[str, State],
    derive: DeriveId,
    new_id: NewId,
    now: Now,
    from_visit: str,
    into_visit: str,
) -> tuple[str, ...]:
    """Carry the earlier visit's state into a new one, and return what was carried.

    **Only the namespaces this part declares are carried** (NS-08). A part that does
    not ask for a namespace does not receive it, so what a participant built up in
    one part does not leak into a part that never said it would read it. A namespace
    the earlier part never wrote is not carried either, because there is nothing to
    carry and an empty document would claim there was.

    The value is not copied. It is content-addressed, so the new visit's pointer
    names the object the old one named; carrying is a new record, not new bytes.
    """
    carried: list[str] = []
    for namespace in states:
        found = await read_state(
            store, derive=derive, visit_id=from_visit, namespace=namespace
        )
        if found.revision == 0:
            continue
        await _commit(
            store,
            context=new_context(state_id(derive, into_visit, namespace)),
            derive=derive,
            new_id=new_id,
            now=now,
            visit_id=into_visit,
            namespace=namespace,
            value=found.value,
            revision=1,
        )
        carried.append(namespace)
    return tuple(carried)


async def read_all(
    store: Store,
    *,
    derive: DeriveId,
    visit_id: str,
    namespaces: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Return what each named namespace holds, for one delivery to a page."""
    found: dict[str, dict[str, Any]] = {}
    for namespace in namespaces:
        held = await read_state(
            store, derive=derive, visit_id=visit_id, namespace=namespace
        )
        found[namespace] = held.value
    return found


__all__ = [
    "STATE_MEDIA_TYPE",
    "StaleState",
    "State",
    "StateValue",
    "StateWrite",
    "UndeclaredState",
    "carry_state",
    "declared",
    "read_all",
    "read_state",
    "readable",
    "state_id",
    "write_state",
]
