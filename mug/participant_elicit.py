"""Elicit a preference inside a live conversation, and record what it settled.

A standalone comparison (``mug.participant_comparison``) asks about runs that are
already over. This module asks *during* the conversation: the model writes more
than one reply to what the participant just said, the participant picks the one
they would rather have had, and the thread goes on from it. It is the RLHF
collection loop, run as an experiment rather than as a labelling queue.

The elicitation is built from three pieces that already exist, so it adds one
record producer and no new machinery:

- **The candidates are real messages.** Each one is posted to the channel and
  recorded as a durable generation with its own private provenance, exactly as an
  ordinary reply is (W16). Only the chosen one is delivered and taken into the
  room's context; the rest are committed, undelivered, and kept. That unchosen
  reply exists nowhere else -- a public preference dataset keeps the rejected text
  and loses everything about where it came from.
- **The judgement is an API-18 annotation.** The blinding, the seed-committed
  display order, the fixed-revision idempotency, and the quality evidence are the
  preference service as it stands. What is new is only that the activity does not
  end when the answer does.
- **The join is one API-08 record.** ``CandidateReplySet`` names the prompt, every
  candidate, the one that was kept, and the response that chose it.

Three properties are worth stating, because they are what a reader of the data
depends on:

**Nothing is presented that is not already recorded.** The candidates are posted
and their generations written *before* the participant is shown anything, so a
refresh mid-elicitation restores the same candidates rather than spending the
model calls again, and a participant who leaves without answering still leaves a
complete record of what the model wrote.

**An answer names a candidate, never a side of the screen.** The display order is
a seed-committed permutation and the participant answers in blinded handles, which
the mount maps back to candidate keys before anything is recorded. A per-axis
rating carries the candidate key for the same reason.

**Which turns are elicited is derived, not drawn.** A sampled study asks on a
fraction of the turns, and which fraction is decided from the deployment secret
and the prompt message. So the same conversation elicits at the same places
whenever it is replayed, and the sampling is reproducible from the record instead
of being a number nobody can check.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from mug.authoring import Axis, Elicit
from mug.conversation import ChatMessage, ConversationChannel
from mug.gateway import Gateway
from mug.kernel import (
    DataHandlingRef,
    Digest,
    PrincipalRef,
    WireCommandEnvelope,
)
from mug.preferences import (
    DimensionRating,
    PreferenceAssignment,
    PreferenceProtocol,
    PreferenceService,
)
from mug.preferences.compile import comparison_task
from mug.preferences.runtime import response_id_for
from mug.runtime import CommandContext
from mug.storage import Store

_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_ENVELOPE_DIGEST = Digest(algorithm="sha-256", hex="0" * 64)

# The derivation roles. Each keeps one derived value independent of the others, so
# a display handle can never be re-derived from an assignment identifier.
_ASSIGNMENT_ROLE = "prefassign"
_QUERY_ROLE = "prefquery"
_PROTOCOL_DEFINITION_ROLE = "prefdef"
_PROTOCOL_VERSION_ROLE = "prefver"
_ORDER_SEED_ROLE = "preference-display-order"
_SAMPLE_SEED_ROLE = "inline-preference-sample"

# The schema name an assignment head carries, so a reader can tell an elicitation
# that is still open from one that has been answered.
_ASSIGNMENT_SCHEMA = "mug.api-18.preference-assignment"

# What an elicited turn compares: replies in a conversation.
_CANDIDATE_KIND = "chat-message"

# The whole of the unsigned range the sampling fraction is read against.
_UNIT = float(1 << 64)


@dataclass(frozen=True)
class Candidate:
    """One reply competing for a turn: the posted message and what it says.

    ``actor_id`` is the model seat that wrote it, which is the thing a blinded
    presentation must not carry to the browser -- with ``Elicit.between`` the seat
    *is* the condition under test.
    """

    message: ChatMessage
    text: str
    actor_id: str

    @property
    def key(self) -> str:
        """The candidate key: the reply's own message id, and nothing beside it."""
        return self.message.message_id


@dataclass(frozen=True)
class Answer:
    """What a participant said about one elicited turn."""

    choice: str
    verdict: str = "choice"
    ratings: tuple[DimensionRating, ...] = ()
    response_time_ms: int = 0
    idempotency_key: str | None = None


def _no_candidates() -> dict[str, Candidate]:
    """Return an empty, typed candidate map for an elicitation's default."""
    return {}


def _no_handles() -> dict[str, str]:
    """Return an empty, typed handle map for an elicitation's default."""
    return {}


@dataclass(frozen=True)
class Elicitation:
    """One turn's open elicitation: what was assigned, and what is on the screen.

    ``order`` is the committed display order of the candidate keys, and ``handles``
    is the blinded handle each is shown behind. The participant answers in handles
    and the mount maps back, so no reply's identity reaches the browser.
    """

    assignment: PreferenceAssignment
    protocol: PreferenceProtocol
    prompt_message_id: str
    channel_key: str
    ask: str
    ties: bool
    skippable: bool
    axes: tuple[Axis, ...] = ()
    candidates: dict[str, Candidate] = field(default_factory=_no_candidates)
    handles: dict[str, str] = field(default_factory=_no_handles)

    @property
    def order(self) -> tuple[str, ...]:
        """The candidate keys in the order this participant was shown them."""
        return tuple(self.assignment.candidate_display_order)

    def handle_of(self, candidate_key: str) -> str:
        """Return the blinded handle one candidate is shown behind."""
        return self.handles.get(candidate_key, "")

    def key_of(self, handle: str) -> str | None:
        """Return the candidate a handle names, or None when it names none."""
        for key, shown in self.handles.items():
            if shown == handle and handle:
                return key
        return None

    def frame(self) -> dict[str, Any]:
        """Build the frame that puts this elicitation on the participant's screen."""
        return {
            "type": "chat_candidates",
            "assignment_id": self.assignment.assignment_id,
            "prompt_message_id": self.prompt_message_id,
            "channel": self.channel_key,
            "ask": self.ask,
            "ties": self.ties,
            "skippable": self.skippable,
            "options": [
                {
                    "handle": self.handle_of(key),
                    "text": self.candidates[key].text,
                }
                for key in self.order
                if key in self.candidates
            ],
            "axes": [
                {
                    "key": axis.key,
                    "ask": axis.ask,
                    "scope": axis.scope,
                    "points": axis.points,
                    "low": axis.low,
                    "high": axis.high,
                }
                for axis in self.axes
            ],
        }


def elicits(gateway: Gateway, spec: Elicit, prompt_message_id: str) -> bool:
    """Return whether this turn is one of the turns the study elicits.

    A study that elicits every turn asks nothing of the sampler. A study that
    samples derives the decision from the deployment secret and the prompt message,
    so the same conversation elicits at the same places however often it is run,
    and a reader can check the rate against the record rather than trust it.
    """
    if spec.sample >= 1.0:
        return True
    drawn = gateway.derived_seed(_SAMPLE_SEED_ROLE, prompt_message_id)
    return int.from_bytes(drawn[:8], "big") / _UNIT < spec.sample


def assignment_id_for(
    gateway: Gateway, flow_id: str, channel_key: str, prompt_message_id: str
) -> str:
    """Return the one assignment identifier this elicited turn always gives."""
    return gateway.derived_id(
        _ASSIGNMENT_ROLE, f"{flow_id}:{channel_key}:{prompt_message_id}"
    )


async def open_elicitation(
    *,
    gateway: Gateway,
    store: Store,
    spec: Elicit,
    principal: PrincipalRef,
    flow_id: str,
    enrollment_id: str,
    channel_key: str,
    prompt_message_id: str,
    candidates: Sequence[Candidate],
) -> Elicitation | None:
    """Assign this turn's blinded candidate set, and return what to put on screen.

    Two candidates that say the same thing are not a comparison, so a set whose
    replies are byte-identical is refused here and the turn goes on with the first
    of them. A model asked for two samples at temperature zero writes the same
    reply twice, and asking a participant to prefer one of two identical texts
    would record a coin toss as a judgement.

    A reconnection reads the assignment the store already holds, so the order and
    the handles are the ones that were recorded rather than ones recomputed beside
    them.
    """
    if len(candidates) < 2:
        return None
    if len({candidate.text for candidate in candidates}) < len(candidates):
        return None
    assignment_id = assignment_id_for(
        gateway, flow_id, channel_key, prompt_message_id
    )
    by_key = {candidate.key: candidate for candidate in candidates}
    protocol = _protocol(gateway, spec, assignment_id)
    service = PreferenceService(store=store)
    assignment = _recorded_assignment(store, assignment_id)
    if assignment is None:
        await service.declare(
            context=_mint(
                gateway,
                principal,
                command="preference.declare",
                target_id=protocol.protocol_version_id,
                data={"channel_key": channel_key},
                idem=_fresh_idem(gateway),
            ),
            protocol=protocol,
        )
        context = _mint(
            gateway,
            principal,
            command="preference.assign",
            target_id=assignment_id,
            data={"channel_key": channel_key, "flow_id": flow_id},
            idem=_fresh_idem(gateway),
        )
        receipt, assignment = await service.assign(
            context=context,
            protocol=protocol,
            query_id=gateway.derived_id(
                _QUERY_ROLE, f"{flow_id}:{channel_key}:{prompt_message_id}"
            ),
            enrollment_id=enrollment_id,
            candidate_keys=list(by_key),
            seed=gateway.derived_seed(_ORDER_SEED_ROLE, assignment_id),
        )
        if receipt.outcome != "accepted":
            return None
    return Elicitation(
        assignment=assignment,
        protocol=protocol,
        prompt_message_id=prompt_message_id,
        channel_key=channel_key,
        ask=spec.ask,
        ties=spec.ties,
        skippable=spec.skippable,
        axes=spec.axes,
        candidates=by_key,
        handles={
            key: gateway.derived_handle(f"inline-candidate:{assignment_id}:{key}")
            for key in assignment.candidate_display_order
        },
    )


def read_answer(
    elicitation: Elicitation, frame: Mapping[str, Any]
) -> Answer | None:
    """Read one answer frame, mapping every blinded handle back to its candidate.

    An answer that names a handle nobody was shown is not an answer. A tie is only
    read when the study offered one, and a rating for an axis this elicitation does
    not carry is dropped rather than recorded against a dimension the protocol
    never declared.
    """
    choice = elicitation.key_of(cast("str", frame.get("choice", "")))
    verdict = frame.get("verdict")
    if not isinstance(verdict, str) or verdict not in ("choice", "tie", "both-bad"):
        verdict = "choice"
    if verdict != "choice" and not elicitation.ties:
        verdict = "choice"
    if choice is None:
        # A tie still resolves to a reply, so the thread has one to go on with:
        # the first the participant was shown, which is the one they read first.
        if verdict == "choice" or not elicitation.order:
            return None
        choice = elicitation.order[0]
    elapsed = frame.get("response_time_ms")
    idem = frame.get("idempotency_key")
    return Answer(
        choice=choice,
        verdict=verdict,
        ratings=_ratings(elicitation, frame.get("ratings")),
        response_time_ms=max(0, int(elapsed)) if isinstance(elapsed, int) else 0,
        idempotency_key=idem if isinstance(idem, str) else None,
    )


def _ratings(
    elicitation: Elicitation, written: Any
) -> tuple[DimensionRating, ...]:
    """Read the per-axis answers of one frame into the records they are kept as."""
    if not isinstance(written, list):
        return ()
    declared = {axis.key: axis for axis in elicitation.axes}
    read: list[DimensionRating] = []
    for item in cast("list[Any]", written):
        if not isinstance(item, dict):
            continue
        entry = cast("dict[str, Any]", item)
        axis = declared.get(cast("str", entry.get("axis", "")))
        value = entry.get("value")
        if axis is None or not isinstance(value, int):
            continue
        option = entry.get("option")
        key = (
            elicitation.key_of(option)
            if isinstance(option, str) and option
            else None
        )
        # The midpoint favours neither candidate, and it is the only answer that
        # names none. Everything else must resolve to a candidate that was shown.
        if (key is None) != (value == 0):
            continue
        if not 0 <= value <= axis.points:
            continue
        read.append(
            DimensionRating(
                dimension_key=axis.key, candidate_key=key, value=value
            )
        )
    return tuple(read)


@dataclass(frozen=True)
class Settled:
    """What one settled elicitation recorded: the reply kept, and where it was."""

    choice: str
    response_id: str
    streams: tuple[str, ...] = ()


async def settle(
    elicitation: Elicitation,
    answer: Answer,
    *,
    gateway: Gateway,
    store: Store,
    channel: ConversationChannel,
    principal: PrincipalRef,
    now: Callable[[], str],
) -> Settled | None:
    """Record the judgement, its quality evidence, and the branch it resolved.

    The three writes are the three the family already fences: the response commits
    against the assignment revision, the quality evidence against the response
    revision, and the candidate set is its own aggregate keyed by the prompt. So a
    retry replays to the same records and a second, different answer is refused --
    a participant judges one turn once, however many times their client sends it.

    A refused response means this turn was already answered, so the reply the first
    answer kept is returned and the thread goes on with that one rather than
    branching a second time.
    """
    assignment_id = elicitation.assignment.assignment_id
    response_id = response_id_for(assignment_id)
    service = PreferenceService(store=store)
    context = _mint(
        gateway,
        principal,
        command="preference.respond",
        target_id=response_id,
        data={"choice": answer.choice, "verdict": answer.verdict},
        idem=answer.idempotency_key or _fresh_idem(gateway),
    )
    receipt, _ = await service.respond(
        context=context,
        assignment_id=assignment_id,
        choice=answer.choice,
        presented_order=list(elicitation.order),
        submitted_at=now(),
        verdict=answer.verdict,
        ratings=list(answer.ratings),
    )
    if receipt.outcome != "accepted":
        recorded = _recorded_choice(store, response_id)
        return None if recorded is None else Settled(recorded, response_id)
    streams = [context.stream_id]
    quality_id = gateway.derived_id("prefresponse", f"quality:{response_id}")
    quality = _mint(
        gateway,
        principal,
        command="preference.attest-quality",
        target_id=quality_id,
        data={"response_time_ms": answer.response_time_ms},
        idem=_fresh_idem(gateway),
    )
    await service.attest_quality(
        context=quality,
        assignment_id=assignment_id,
        # Nothing failed an attention check, because an elicited turn runs none:
        # the conversation is the task. The time it took is the signal here, and a
        # judgement returned in no time is one an analysis should be able to find.
        attention_check_passed=True,
        response_time_ms=answer.response_time_ms,
    )
    set_id = gateway.derived_id("message", f"candidate-set:{assignment_id}")
    joined = _mint(
        gateway,
        principal,
        command="chat.candidate-set",
        target_id=set_id,
        data={"selected": answer.choice},
        idem=_fresh_idem(gateway),
    )
    await channel.candidate_set(
        context=joined,
        prompt_message_id=elicitation.prompt_message_id,
        candidate_message_ids=list(elicitation.order),
        selected_message_id=answer.choice,
        preference_response_id=response_id,
    )
    streams.append(joined.stream_id)
    return Settled(answer.choice, response_id, tuple(streams))


def _protocol(
    gateway: Gateway, spec: Elicit, assignment_id: str
) -> PreferenceProtocol:
    """Build the protocol one elicited turn is answered under.

    It is blinded and shuffled without asking, because the candidates are replies
    of one conversation: which reply came from which seat, and which was shown
    first, are exactly the things a preference must not be able to read.
    """
    return PreferenceProtocol(
        # The protocol shares the assignment's identifier body, which is how a
        # reader joins an answer to the question it answered: the frozen assignment
        # names its query but not its protocol, and a derived identifier could only
        # be re-derived by something holding the deployment secret. Sharing the body
        # is the same convention that puts an aggregate's events on one stream.
        protocol_version_id=f"{_PROTOCOL_VERSION_ROLE}_"
        + assignment_id.split("_", 1)[1],
        protocol_definition_id=gateway.derived_id(
            _PROTOCOL_DEFINITION_ROLE, "inline-chat-preference"
        ),
        candidate_kind=_CANDIDATE_KIND,
        task=comparison_task(
            kind="pairwise", prompt=spec.ask, ties=spec.ties, axes=spec.axes
        ),
        blinded=True,
        randomize_order=True,
    )


def _recorded_assignment(
    store: Store, assignment_id: str
) -> PreferenceAssignment | None:
    """Return the assignment this turn already recorded, when it recorded one."""
    state = store.load_aggregate(assignment_id)
    if not isinstance(state, dict):
        return None
    body = cast("dict[str, Any]", state)
    if body.get("schema", {}).get("name") != _ASSIGNMENT_SCHEMA:
        return None
    return PreferenceAssignment.model_validate(body)


def _recorded_choice(store: Store, response_id: str) -> str | None:
    """Return the candidate an already-answered turn kept, when it is readable."""
    state = store.load_aggregate(response_id)
    if not isinstance(state, dict):
        return None
    choice = cast("dict[str, Any]", state).get("choice")
    return choice if isinstance(choice, str) else None


def _envelope(
    command_name: str, target_id: str, data: dict[str, Any], idem: str
) -> WireCommandEnvelope:
    """Build the wire envelope for one elicitation command."""
    schema = {
        "name": "mug.command-envelope",
        "version": 0,
        "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
    }
    return WireCommandEnvelope.model_validate(
        {
            "schema": schema,
            "protocol_version": "0.1.0",
            "command": {"name": command_name, "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-000000000001",
            "idempotency_key": idem,
            "target": {"id": target_id},
            "payload": {
                "schema": {
                    "name": "mug.edge.payload",
                    "version": 0,
                    "digest": _ENVELOPE_DIGEST.model_dump(mode="json"),
                },
                "data": data,
            },
        }
    )


def _mint(
    gateway: Gateway,
    principal: PrincipalRef,
    *,
    command: str,
    target_id: str,
    data: dict[str, Any],
    idem: str,
) -> CommandContext:
    """Mint the trusted context for one elicitation command."""
    return gateway.mint(
        _envelope(command, target_id, data, idem),
        principal=principal,
        data_handling=_RESEARCH,
    )


def _fresh_idem(gateway: Gateway) -> str:
    """Mint one well-formed idempotency key for a write that carries none."""
    body = gateway.new_id("request").split("_", 1)[1].replace("-", "")
    return "idem_" + body[:21] + "A"


__all__ = [
    "Answer",
    "Candidate",
    "Elicitation",
    "Settled",
    "assignment_id_for",
    "elicits",
    "open_elicitation",
    "read_answer",
    "settle",
]
