"""Run one chat activity over the realtime socket: the chat channel's transport.

This is the chat analog of the game stepping loop. Where a game mount owns the
socket to step an environment and record transitions, this mount owns the socket to
carry a conversation and record messages. Both write through the same command spine,
so a conversation's lineage is a canonical event stream like an episode's.

**One connection, one seat in a room.** The conversation itself is a ``ChatRoom``
(``mug.conversation.room``): it holds the channels, the membership, and one
canonical order per channel. A study with one participant forms a room of one, so
the single-participant path and the several-participant path are the same path. A
study with two participants forms a room of two, and each connection is one seat in
it. The room decides who may see and say what; this mount is the socket at one seat.

One exchange runs in five recorded steps:

1. The participant sends a chat frame. The mount posts it through the room, which
   assigns the next sequence on that channel.
2. The room delivers it to every member that may see it, each with its own
   ``DeliveryReceipt`` recorded when it actually arrived.
3. Each model seat the channel activates composes a turn: the turn policy decides
   whether the model may speak, and the provider runs one recorded call. Several
   seats compose **at the same time**, because two models thinking one after the
   other is latency nobody asked for.
4. The composed replies are published **in the study's declared seat order**, so
   the channel's order is what the author wrote and not whichever provider answered
   first.
5. Each reply is delivered the same way the participant's message was.

The channel records a *digest*, never message text: that is the family's privacy
shape, because the ledger names content and does not hold it. The text lives in a
content-addressed artifact, and in the live room for the length of the conversation
so one participant's words can reach another's screen.

**A conversation outlives its connection** (NS-03). With ``durable`` set, the mount
keeps a transcript: a reconnection is sent the committed history and the model turn
that was in flight, and a reply from a generation that has since been superseded
publishes nothing and is recorded as discarded (``mug.conversation.transcript``).

**Each admitted reply is also a durable generation.** A reply the participant read
is a model output like any other, so it is staged in its three forms with a private
provenance artifact beside it (``mug.agents.generation``). That is what lets a study
ask "which of these two answers was better" about a live conversation rather than
only about answers recorded in advance.

The mount holds no clock and no entropy: the transport glue one layer up injects
``new_context``, ``new_id``, and ``now``, exactly as the agent episode mount does,
so a test drives a whole conversation with a fixed clock, a fake provider, and no
socket of its own. A study that elicits a preference inside the conversation also
injects the gateway, because a blinded assignment is derived and not drawn.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, cast

from fastapi import WebSocket, WebSocketDisconnect

from mug.agents import ChatAgent, ChatReply, ChatTurn, PendingReply
from mug.agents.generation import record_reply
from mug.agents.runtime import AgentIds, compile_agent
from mug.authoring import Elicit, LLMAgent
from mug.conversation import ChatMessage, TurnPolicy
from mug.conversation.room import ChatRoom, RoomChannel, RoomMember
from mug.conversation.transcript import (
    TranscriptState,
    history,
    is_current,
    message_artifact_seed,
    opened,
    read_transcript,
    record_transcript,
    transcript_id_for,
    with_candidates,
    with_discarded,
    with_message,
    with_turn_begun,
    with_turn_ended,
)
from mug.gateway import Gateway
from mug.interactions.types import ConnectionLease
from mug.kernel import DataHandlingRef, PrincipalRef, VersionStamp
from mug.participant_elicit import (
    Candidate,
    Elicitation,
    elicits,
    open_elicitation,
    read_answer,
    settle,
)
from mug.providers import ModelProvider
from mug.providers.durable_tape import ArtifactOutputTape
from mug.providers.runtime import (
    NewContext,
    Output,
    Payload,
    ProviderAdapter,
    SecretResolver,
)
from mug.realtime import FrameChannel, Session
from mug.storage import ArtifactStore, Store, stage_artifact

# Mint one runtime-occurrence id of the named kind (the gateway, injected).
NewId = Callable[[str], str]
# Read the conversation's next frame, or None once the participant went away. A
# conversation that owns the socket reads it; one that shares it with a game reads
# the channel the frame router fills.
ReadFrame = Callable[[], Awaitable[dict[str, Any] | None]]
# Turn the recent messages into the model payload. A study overrides this to render
# its own prompt shape; the default renders the transcript.
ComposeChat = Callable[[list[ChatMessage]], Payload]
# Render a model's raw output as the text a participant reads.
RenderReply = Callable[[Output], str]

# A flow records at most 1024 captured streams, so a long conversation reports the
# streams of the messages it posted up to that bound.
_MAX_CAPTURED_STREAMS = 1024

# A participant's own words are research data about a person, so the artifact that
# holds them is classified as such rather than as ordinary operational content.
_PARTICIPANT_TEXT = DataHandlingRef(privacy_labels=["research", "sensitive"])

_DEFAULT_CHANNEL = "chat"

# How many frames one elicitation reads before it stops waiting for a choice. A
# client sends frames of its own and a participant may click an option that is not
# theirs, so the bound is well above one answer; a connection that reaches it has
# stopped choosing, and the thread goes on with the reply shown first.
_MAX_ELICIT_FRAMES = 64


@dataclass(frozen=True)
class ChatSeatSpec:
    """The model seat a study places in a chat channel: who speaks, where, and how.

    ``agent`` is the author's ``LLMAgent`` definition -- its model, prompt, tools,
    and memory -- ``adapter`` is the provider adapter that runs its calls, and
    ``ids`` pins the published build. ``actor_id`` is the recorded actor the replies
    are authored by, and ``resolve_secret`` resolves the agent's credential at call
    time (unset for a keyless local runner).

    ``channel`` is where this seat speaks, and unset means the study's own channel;
    ``hears`` names any further channel it also reads, so a coach that watches the
    public channel and answers in a private one is two words to write. ``policy``
    and ``mention_token`` are this seat's own activation rule: a partner that
    answers everything and a coach that answers only when named are the same room
    with two policies, not two rooms.
    """

    agent: LLMAgent
    adapter: ProviderAdapter
    ids: AgentIds
    actor_id: str
    resolve_secret: SecretResolver | None = None
    channel: str | None = None
    hears: tuple[str, ...] = ()
    policy: TurnPolicy | None = None
    mention_token: str | None = None
    greeting: str | None = None


@dataclass(frozen=True)
class ChatChannel:
    """One channel a study declares in a chat room, and who may be in it.

    ``seats`` names the participant seats that may see it -- ``seat-1``, ``seat-2``,
    in the order the room formed. Left unset, every participant is in it. A channel
    with ``visibility="private"`` and one seat named is a side conversation the
    other participant is never sent and never told exists.
    """

    key: str
    visibility: Literal["public", "team", "private"] = "public"
    seats: tuple[str, ...] | None = None


def _free_turn_policy() -> TurnPolicy:
    """Return the default policy: the model answers each message once."""
    return TurnPolicy(
        channel_key=_DEFAULT_CHANNEL,
        activation="free",
        max_model_activations_per_turn=1,
    )


def _no_seats() -> tuple[ChatSeatSpec, ...]:
    """Return an empty, typed model-seat tuple for a spec's default."""
    return ()


def _no_channels() -> tuple[ChatChannel, ...]:
    """Return an empty, typed channel tuple for a spec's default."""
    return ()


@dataclass(frozen=True)
class ChatSpec:
    """One chat activity a study supplies: its seats, its channels, and its bounds.

    ``seat`` is the one-model spelling and ``seats`` the several-model one; a study
    that writes neither has a conversation with no model in it, which is a
    conversation between participants. ``participants`` is how many people share one
    room, so two participants and one model is ``participants=2``.

    ``channels`` declares the room. Left unset it is one public channel named
    ``channel_key``, which is what a two-party conversation needs. ``policy``
    governs when a model may speak and how often per turn, and a seat may override
    it. ``max_activations_per_turn`` is the room's budget: it caps how many model
    seats may answer one message, so a word that mentions three models does not
    start a response storm.

    ``max_messages`` bounds the conversation, so a participant who never leaves
    still reaches the next activity. ``compose`` and ``render_reply`` are the two
    study seams -- the prompt shape and the reply shape -- and the defaults render a
    plain transcript and read a ``text`` field.

    ``elicit_preference`` asks the participant to choose between candidate replies
    on the turns the study elicits, and the conversation goes on with the reply
    they chose. It needs a gateway at the mount, because everything a participant
    must meet twice -- the assignment, the blinded handles, the display order, and
    which turns are elicited at all -- is derived rather than drawn.

    ``placement`` is where the conversation sits when the activity is also a game:
    ``beside`` it (the default), ``below`` it, or in a ``drawer`` that opens over
    it. It is a design variable rather than decoration -- a transcript below the
    fold is read less than one beside the canvas -- so a study that cares says so.
    An activity that is only a conversation ignores it, because there is nothing to
    place it against.
    """

    seat: ChatSeatSpec | None = None
    seats: tuple[ChatSeatSpec, ...] = field(default_factory=_no_seats)
    channel_key: str = _DEFAULT_CHANNEL
    channels: tuple[ChatChannel, ...] = field(default_factory=_no_channels)
    participants: int = 1
    placement: Literal["beside", "below", "drawer"] = "beside"
    policy: TurnPolicy = field(default_factory=_free_turn_policy)
    max_messages: int = 20
    max_message_length: int = 4000
    context_messages: int = 20
    max_activations_per_turn: int = 2
    mention_token: str | None = None
    greeting: str | None = None
    compose: ComposeChat | None = None
    render_reply: RenderReply | None = None
    normalize: Callable[[Output], Output] | None = None
    elicit_preference: Elicit | None = None

    def __post_init__(self) -> None:
        if self.participants < 1:
            raise ValueError("a chat activity needs at least one participant")
        if self.max_activations_per_turn < 1:
            raise ValueError("a chat turn must admit at least one model activation")
        declared = {channel.key for channel in self.room_channels}
        for seat in self.model_seats:
            missing = [key for key in self.channels_of(seat) if key not in declared]
            if missing:
                raise ValueError(
                    f"chat seat {seat.actor_id!r} names undeclared channels: "
                    + ", ".join(sorted(missing))
                )

    @property
    def model_seats(self) -> tuple[ChatSeatSpec, ...]:
        """Return every model seat, in the order the study declared them."""
        one = (self.seat,) if self.seat is not None else ()
        return (*one, *self.seats)

    @property
    def room_channels(self) -> tuple[ChatChannel, ...]:
        """Return the channels of the room, defaulting to one public channel."""
        return self.channels or (ChatChannel(key=self.channel_key),)

    def channel_of(self, seat: ChatSeatSpec) -> str:
        """Return the channel one seat speaks in: its own, else the study's."""
        return seat.channel or self.channel_key

    def channels_of(self, seat: ChatSeatSpec) -> tuple[str, ...]:
        """Return every channel one seat reads, the one it speaks in first."""
        speaks = self.channel_of(seat)
        return (speaks, *(key for key in seat.hears if key != speaks))

    def policy_for(self, seat: ChatSeatSpec) -> TurnPolicy:
        """Return the activation rule one seat runs under."""
        return seat.policy or self.policy

    def mention_for(self, seat: ChatSeatSpec) -> str | None:
        """Return the word that activates one seat under a mention policy."""
        return seat.mention_token or self.mention_token


# -- the room this connection takes a seat in ------------------------------------


@dataclass(frozen=True)
class RoomSeat:
    """What one connection is given when it joins a conversation.

    ``seat_key`` is the participant seat the room cast it into (``seat-1``,
    ``seat-2``), which is how an authored private channel names who is in it.
    ``lease`` is what makes this connection's writes valid; a room formed with no
    lease authority has none, because there is no second connection to fence.
    """

    room: ChatRoom
    actor_id: str
    seat_key: str
    lease: ConnectionLease | None = None


class ChatRendezvous(Protocol):
    """Match connections into one shared conversation. The app layer implements it."""

    async def join(self, *, visit_id: str, activity_key: str | None) -> RoomSeat:
        """Wait for a room to form and return this connection's seat in it."""
        ...


def _default_render_reply(output: Output) -> str:
    """Render a model's raw output as text: a ``text`` field, else the value."""
    if isinstance(output, dict):
        text = cast("dict[str, Any]", output).get("text")
        if isinstance(text, str):
            return text
    if isinstance(output, str):
        return output
    return "" if output is None else json.dumps(output, sort_keys=True)


def _no_streams() -> list[str]:
    """Return an empty, typed stream list for a run's default."""
    return []


@dataclass(frozen=True)
class ChatDurability:
    """What the mount needs to keep a conversation across connections.

    Without it the conversation lives and dies with the connection, which is what
    every chat mount did before NS-03 asked for a refresh to restore one. With it,
    each message's words are staged as a content-addressed artifact and the durable
    transcript points at them, so a reconnection restores the history and the turn
    that was in flight.
    """

    derive: Callable[[str, str], str]
    artifacts: ArtifactStore
    new_artifact_id: Callable[[str], str]
    new_upload_id: Callable[[], str]
    occurrence_key: str


@dataclass
class _ChatRun:
    """The mutable state of one chat activity while it owns the socket."""

    seat: RoomSeat
    agents: dict[str, ChatAgent]
    streams: list[str] = field(default_factory=_no_streams)
    # The durable enrollment this connection annotates under, when the visit was
    # launch-gated. An ungated demo has none and the elicitation derives a
    # visit-scoped stand-in instead.
    enrollment_id: str | None = None
    state: TranscriptState | None = None
    # The store's own revision of the transcript, or None when nothing is committed
    # yet. Every commit names the revision it read, so two connections writing the
    # same conversation cannot both win.
    committed: int | None = None

    @property
    def room(self) -> ChatRoom:
        """Return the conversation this connection has a seat in."""
        return self.seat.room

    @property
    def participant_actor_id(self) -> str:
        """Return the actor this connection speaks as."""
        return self.seat.actor_id

    def capture(self, stream_id: str | None) -> None:
        """Record one stream this activity wrote to, up to the flow's bound."""
        if stream_id is not None and len(self.streams) < _MAX_CAPTURED_STREAMS:
            self.streams.append(stream_id)


def _role_of(message: ChatMessage, model_actors: frozenset[str]) -> str:
    """Name who wrote one message, in the shape a prompt reads."""
    return "assistant" if message.author_actor_id in model_actors else "user"


def _default_compose(room: ChatRoom, model_actors: frozenset[str]) -> ComposeChat:
    """Build the default prompt composer: the transcript, each line labelled."""

    def compose(recent: list[ChatMessage]) -> Payload:
        return {
            "messages": [
                {
                    "role": _role_of(message, model_actors),
                    "text": room.text_of(message.message_id),
                }
                for message in recent
            ]
        }

    return compose


def _build_agents(
    spec: ChatSpec,
    room: ChatRoom,
    *,
    store: Store,
    new_id: NewId,
    now: Callable[[], datetime],
) -> dict[str, ChatAgent]:
    """Compose one agent per model seat, each on the channel it speaks in."""
    model_actors = frozenset(seat.actor_id for seat in spec.model_seats)
    compose = spec.compose or _default_compose(room, model_actors)
    agents: dict[str, ChatAgent] = {}
    for seat in spec.model_seats:
        provider = ModelProvider(
            store=store,
            adapter=seat.adapter,
            now=now,
            new_generation_id=lambda: new_id("generation"),
        )
        agents[seat.actor_id] = ChatAgent(
            agent_version=compile_agent(seat.agent, ids=seat.ids),
            provider=provider,
            channel=room.channel(spec.channel_of(seat)),
            policy=spec.policy_for(seat),
            agent_actor_id=seat.actor_id,
            compose=compose,
            resolve_secret=seat.resolve_secret,
            visibility=room.visibility_of(spec.channel_of(seat)),
        )
    return agents


def _room_channels(spec: ChatSpec) -> list[RoomChannel]:
    """Turn the authored channels into the room's own declarations."""
    return [
        RoomChannel(key=channel.key, visibility=channel.visibility)
        for channel in spec.room_channels
    ]


def _participant_channels(spec: ChatSpec, seat_key: str) -> tuple[str, ...]:
    """Return the channels one participant seat may see.

    A channel that names no seats is everybody's. A channel that names seats is
    only theirs, and a participant outside it is never sent its messages and is
    never told it exists.
    """
    return tuple(
        channel.key
        for channel in spec.room_channels
        if channel.seats is None or seat_key in channel.seats
    )


def _seat_a_room(
    spec: ChatSpec,
    *,
    store: Store,
    new_id: NewId,
    now: Callable[[], datetime],
) -> RoomSeat:
    """Build the room of one that a solo conversation runs in.

    A study that matches participants supplies a rendezvous instead. This is what a
    connection gets when there is nobody to match it with, and it is the same room
    object, so nothing downstream knows the difference.
    """
    room = ChatRoom(
        store=store,
        interaction_id=new_id("interaction"),
        channels=_room_channels(spec),
        now=now,
    )
    actor_id = new_id("actor")
    room.add_member(
        RoomMember(
            actor_id=actor_id,
            channels=_participant_channels(spec, "seat-1"),
            kind="participant",
        )
    )
    return RoomSeat(room=room, actor_id=actor_id, seat_key="seat-1")


def _place_model_seats(spec: ChatSpec, room: ChatRoom) -> None:
    """Put every model seat in the room, on the channels it reads."""
    for seat in spec.model_seats:
        if room.member(seat.actor_id) is None:
            room.add_member(
                RoomMember(
                    actor_id=seat.actor_id,
                    channels=spec.channels_of(seat),
                    kind="model",
                )
            )


def _fresh_idem(new_id: NewId) -> str:
    """Mint one fresh, well-formed idempotency key from a fresh request id."""
    body = new_id("request").split("_", 1)[1].replace("-", "")
    return "idem_" + body[:21] + "A"


def _reader(websocket: WebSocket, frames: FrameChannel | None) -> ReadFrame:
    """Return where this conversation's frames come from.

    A conversation that owns the socket reads it. A conversation that **shares**
    the socket with a game reads the channel the frame router hands it, because
    two readers on one socket race for every frame (``mug.realtime``).
    """
    if frames is not None:
        return frames.get
    return lambda: _read_frame(websocket)


async def _read_frame(websocket: WebSocket) -> dict[str, Any] | None:
    """Read the next frame from the socket, or None when the participant leaves.

    A frame that is not valid json, or not a json object, is dropped rather than
    ending the conversation: a malformed frame must not cost a participant their
    activity. The caller decides what a well-formed frame means.
    """
    while True:
        try:
            raw = await websocket.receive_text()
        except WebSocketDisconnect:
            return None
        try:
            loaded: Any = json.loads(raw)
        except ValueError:
            continue
        if isinstance(loaded, dict):
            return cast("dict[str, Any]", loaded)


def _participant_text(frame: dict[str, Any], limit: int) -> str:
    """Read one chat frame's text, trimmed and bounded, or empty when it has none."""
    raw = frame.get("text")
    if not isinstance(raw, str):
        return ""
    return raw.strip()[:limit]


def _frame_channel(frame: dict[str, Any], allowed: Sequence[str]) -> str | None:
    """Return the channel a frame names, or the first one this participant is in.

    A frame that names no channel means the first channel of the room, which is
    what a client with one channel sends. A frame that *does* name one is passed
    through as it stands: whether the participant may write there is the room's
    question, and asking it twice would be two places to keep in step. The room
    refuses a channel its member is not in, so a client can not reach a
    conversation it was never put in by naming it.
    """
    named = frame.get("channel")
    if isinstance(named, str):
        return named
    return allowed[0] if allowed else None


async def _send_chat(
    websocket: WebSocket, message: ChatMessage, text: str, *, mine: bool
) -> None:
    """Push one chat message to the participant, with its text and its order."""
    await websocket.send_json(
        {
            "type": "chat",
            "message_id": message.message_id,
            "author_actor_id": message.author_actor_id,
            "channel": message.channel_key,
            "sequence": message.sequence,
            "author": "you" if mine else "them",
            "text": text,
        }
    )


# -- the model turn ---------------------------------------------------------------


def _activated(
    spec: ChatSpec, *, channel_key: str, prompt_text: str
) -> list[ChatSeatSpec]:
    """Return the seats that may answer one message, inside the room's budget.

    The budget is applied *before* the model calls, not after them: a guard that
    lets three models answer and then throws two replies away has already spent the
    three calls. A seat that a mention does not name is skipped here, so a word that
    names one model does not wake the rest of the room.
    """
    eligible: list[ChatSeatSpec] = []
    for seat in spec.model_seats:
        if channel_key not in spec.channels_of(seat):
            continue
        policy = spec.policy_for(seat)
        token = spec.mention_for(seat)
        named = token is None or token.lower() in prompt_text.lower()
        if policy.activation == "mention" and not named:
            continue
        eligible.append(seat)
        if len(eligible) == spec.max_activations_per_turn:
            break
    return eligible


def _turn_ids(new_id: NewId) -> ChatTurn:
    """Mint the identifiers one chat turn writes under."""
    return ChatTurn(
        reply_message_id=new_id("message"),
        snapshot_id=new_id("message"),
        modelcall_id=new_id("modelcall"),
        idempotency_key=_fresh_idem(new_id),
    )


async def _compose_seat(
    run: _ChatRun,
    spec: ChatSpec,
    seat: ChatSeatSpec,
    *,
    turn: ChatTurn,
    new_context: NewContext,
    prompt_text: str,
) -> PendingReply | None:
    """Run one seat's model call over what that seat has actually seen."""
    agent = run.agents[seat.actor_id]
    agent.begin_turn()
    token = spec.mention_for(seat)
    mentioned = True if token is None else token.lower() in prompt_text.lower()
    return await agent.compose_turn(
        turn=turn,
        recent=run.room.context_for(seat.actor_id, limit=spec.context_messages),
        new_context=new_context,
        mentioned=mentioned,
    )


async def _take_turns(
    run: _ChatRun,
    spec: ChatSpec,
    *,
    new_context: NewContext,
    new_id: NewId,
    channel_key: str,
    prompt_text: str,
    caused_by: str | None = None,
) -> list[tuple[ChatSeatSpec, ChatReply]]:
    """Give every activated seat one turn, and publish the replies in seat order.

    The calls run at the same time and the publications run one after another. That
    is the whole point of the split: two models answer in parallel, and the channel
    still records them in the order the study wrote them down, not in the order the
    providers happened to finish.

    ``caused_by`` is the event of the message that opened the turn, and every reply
    names it. Each message is its own aggregate on its own stream, so this is what
    says which answer belonged to which question.
    """
    seats = _activated(spec, channel_key=channel_key, prompt_text=prompt_text)
    if not seats:
        return []
    turns = [_turn_ids(new_id) for _ in seats]
    pending = await asyncio.gather(
        *(
            _compose_seat(
                run,
                spec,
                seat,
                turn=turn,
                new_context=new_context,
                prompt_text=prompt_text,
            )
            for seat, turn in zip(seats, turns, strict=True)
        )
    )
    published: list[tuple[ChatSeatSpec, ChatReply]] = []
    render = spec.render_reply or _default_render_reply
    for seat, turn, composed in zip(seats, turns, pending, strict=True):
        if composed is None:
            continue
        reply = await run.agents[seat.actor_id].publish(
            composed, turn=turn, new_context=new_context, caused_by=caused_by
        )
        run.room.adopt(reply.message, render(reply.output))
        run.capture(reply.stream_id)
        published.append((seat, reply))
    return published


# -- the elicited turn ------------------------------------------------------------


def _elicited(
    spec: ChatSpec, gateway: Gateway | None, prompt_message_id: str
) -> bool:
    """Return whether this turn asks the participant to choose between replies.

    A study that wrote no elicitation never elicits, and one mounted without a
    gateway cannot: a blinded assignment, its handles, and its display order are
    all derived from the deployment secret, and there is nothing honest to fall
    back on. Which turns a sampling study elicits is derived too, so the same
    conversation always elicits in the same places.
    """
    if spec.elicit_preference is None or gateway is None:
        return False
    return elicits(gateway, spec.elicit_preference, prompt_message_id)


def _elicit_seats(spec: ChatSpec, elicit: Elicit, seats: Sequence[ChatSeatSpec]) -> (
    list[tuple[ChatSeatSpec, int]]
):
    """Return the seats that answer an elicited turn, and how many replies each writes.

    A study that named seats compares those seats: each writes one reply, and the
    comparison is between the models. A study that did not compares one seat with
    itself: the seat that would have answered writes ``n`` replies. A named seat
    that is not in this room answers nothing, and the turn is not elicited -- a
    comparison that quietly drops one of its two sides is worse than none.
    """
    if not elicit.seats:
        return [(seats[0], elicit.n)] if seats else []
    by_actor = {seat.actor_id: seat for seat in spec.model_seats}
    named = [by_actor.get(actor) for actor in elicit.seats]
    if any(seat is None for seat in named):
        return []
    return [(cast("ChatSeatSpec", seat), 1) for seat in named]


async def _compose_candidates(
    run: _ChatRun,
    spec: ChatSpec,
    plan: Sequence[tuple[ChatSeatSpec, int]],
    *,
    new_context: NewContext,
    new_id: NewId,
    prompt_text: str,
) -> list[tuple[ChatSeatSpec, ChatTurn, PendingReply]]:
    """Call every seat of the plan for the replies it writes, all at the same time."""
    turns = [[_turn_ids(new_id) for _ in range(count)] for _, count in plan]
    composed = await asyncio.gather(
        *(
            _compose_seat_candidates(
                run, spec, seat, turns=seat_turns, new_context=new_context,
                prompt_text=prompt_text,
            )
            for (seat, _), seat_turns in zip(plan, turns, strict=True)
        )
    )
    written: list[tuple[ChatSeatSpec, ChatTurn, PendingReply]] = []
    for (seat, _), seat_turns, pendings in zip(plan, turns, composed, strict=True):
        for turn, pending in zip(seat_turns, pendings, strict=False):
            written.append((seat, turn, pending))
    return written


async def _compose_seat_candidates(
    run: _ChatRun,
    spec: ChatSpec,
    seat: ChatSeatSpec,
    *,
    turns: Sequence[ChatTurn],
    new_context: NewContext,
    prompt_text: str,
) -> list[PendingReply]:
    """Run one seat's candidate calls over what that seat has actually seen."""
    agent = run.agents[seat.actor_id]
    agent.begin_turn()
    token = spec.mention_for(seat)
    mentioned = True if token is None else token.lower() in prompt_text.lower()
    return await agent.compose_candidates(
        turns=turns,
        recent=run.room.context_for(seat.actor_id, limit=spec.context_messages),
        new_context=new_context,
        mentioned=mentioned,
    )


async def _publish_candidates(
    run: _ChatRun,
    spec: ChatSpec,
    durable: ChatDurability | None,
    written: Sequence[tuple[ChatSeatSpec, ChatTurn, PendingReply]],
    *,
    visit_id: Any,
    prompt_message_id: str,
    store: Store,
    new_context: NewContext,
    caused_by: str | None,
) -> list[tuple[ChatSeatSpec, ChatReply, Candidate]]:
    """Post every candidate to the channel, and record each as a durable generation.

    The candidates are committed **before** the participant is shown anything, so a
    connection that drops mid-elicitation leaves a complete record of what the model
    wrote, and one that comes back does not spend the calls again. They are posted
    but not adopted: the room's order and every model's context take the one reply
    the participant keeps, and nothing else.
    """
    render = spec.render_reply or _default_render_reply
    published: list[tuple[ChatSeatSpec, ChatReply, Candidate]] = []
    staged: list[tuple[str, str]] = []
    for seat, turn, pending in written:
        reply = await run.agents[seat.actor_id].publish(
            pending,
            turn=turn,
            new_context=new_context,
            caused_by=caused_by,
            counts=False,
        )
        run.capture(reply.stream_id)
        text = render(reply.output)
        await _record_reply_generation(
            durable, spec, seat, reply, store=store, new_context=new_context
        )
        if durable is not None:
            # The words of a candidate are staged even when it is never delivered,
            # so a reconnection can put the same choice back on the screen and a
            # reader of the unchosen branch has the text and not only the digest.
            artifact_id = await _stage_text(durable, reply.message.message_id, text)
            staged.append((reply.message.message_id, artifact_id))
        published.append(
            (seat, reply, Candidate(reply.message, text, seat.actor_id))
        )
    if durable is not None and run.state is not None and staged:
        await _commit_state(
            run,
            durable,
            visit_id=visit_id,
            store=store,
            new_context=new_context,
            updated=with_candidates(
                run.state, prompt_message_id=prompt_message_id, written=staged
            ),
        )
    return published


async def _keep(
    run: _ChatRun,
    reply: ChatReply,
    text: str,
    *,
    new_context: NewContext,
    new_id: NewId,
) -> None:
    """Take one reply into the conversation: the room's order, then every screen.

    The delivery is what adds the reply to this connection's own transcript,
    because the sink the mount attached does it. Remembering it here as well would
    write the conversation's own reply into the transcript twice, and a
    reconnection would be told the model said it twice.
    """
    run.room.adopt(reply.message, text)
    await run.room.deliver(reply.message, new_context=new_context, new_id=new_id)


async def _elicit_turn(
    websocket: WebSocket,
    run: _ChatRun,
    spec: ChatSpec,
    durable: ChatDurability | None,
    *,
    elicit: Elicit,
    gateway: Gateway,
    visit_id: Any,
    flow_id: str,
    principal: PrincipalRef,
    store: Store,
    new_context: NewContext,
    new_id: NewId,
    channel_key: str,
    prompt_text: str,
    prompt_message_id: str,
    caused_by: str | None,
    generation: int,
    read: ReadFrame,
) -> bool:
    """Run one turn as a choice between candidate replies, and keep the chosen one.

    Return whether the turn ran. A turn that could not be elicited -- no seat, one
    usable reply, or two replies that say the same thing -- still answers the
    participant with the reply the model wrote, because the calls are already spent
    and silence would be a worse answer than the ordinary one.
    """
    plan = _elicit_seats(
        spec, elicit, _activated(spec, channel_key=channel_key, prompt_text=prompt_text)
    )
    if not plan:
        return False
    written = await _compose_candidates(
        run, spec, plan, new_context=new_context, new_id=new_id,
        prompt_text=prompt_text,
    )
    if not written:
        return True
    if not await _may_publish(
        run, durable, visit_id=visit_id, store=store, new_context=new_context,
        generation=generation,
    ):
        return True
    published = await _publish_candidates(
        run, spec, durable, written,
        visit_id=visit_id,
        prompt_message_id=prompt_message_id,
        store=store,
        new_context=new_context,
        caused_by=caused_by,
    )
    if not published:
        return True
    by_key = {candidate.key: (reply, candidate) for _, reply, candidate in published}
    elicitation = await open_elicitation(
        gateway=gateway,
        store=store,
        spec=elicit,
        principal=principal,
        flow_id=flow_id,
        enrollment_id=_enrollment_of(gateway, run, flow_id),
        channel_key=channel_key,
        prompt_message_id=prompt_message_id,
        candidates=[candidate for _, _, candidate in published],
    )
    chosen = published[0][1].message.message_id
    if elicitation is not None:
        await websocket.send_json(elicitation.frame())
        chosen = await _take_choice(
            websocket, elicitation, run,
            gateway=gateway, store=store, principal=principal, read=read,
        )
    # Only the chosen reply is handed to the room. The rest stay committed to the
    # channel and outside its order, which is what makes them unreachable: nothing
    # delivers a message the room never adopted, then or on any later flush.
    reply, candidate = by_key[chosen]
    await _keep(run, reply, candidate.text, new_context=new_context, new_id=new_id)
    return True


async def _take_choice(
    websocket: WebSocket,
    elicitation: Elicitation,
    run: _ChatRun,
    *,
    gateway: Gateway,
    store: Store,
    principal: PrincipalRef,
    read: ReadFrame,
) -> str:
    """Read frames until the participant chooses, passes, or goes away.

    A participant who passes or leaves records no preference at all: there is no
    judgement to record, and inventing one from the first reply would put a choice
    nobody made into the dataset. The thread still goes on, with the reply they
    were shown first.
    """
    for _ in range(_MAX_ELICIT_FRAMES):
        frame = await read()
        if frame is None or frame.get("type") == "chat_end":
            break
        kind = frame.get("type")
        if kind == "chat_candidate_skip" and elicitation.skippable:
            break
        if kind != "chat_candidate_choice":
            continue
        answer = read_answer(elicitation, frame)
        if answer is None:
            await websocket.send_json(
                {
                    "type": "chat_candidates_error",
                    "code": "validation",
                    "message": "that reply was not one of the ones you were shown",
                }
            )
            continue
        settled = await settle(
            elicitation,
            answer,
            gateway=gateway,
            store=store,
            channel=run.room.channel(elicitation.channel_key),
            principal=principal,
            now=_instant,
        )
        if settled is None:
            break
        run.streams.extend(settled.streams)
        await websocket.send_json(
            {"type": "chat_candidates_ack", "response_id": settled.response_id}
        )
        return settled.choice
    return elicitation.order[0]


def _enrollment_of(gateway: Gateway, run: _ChatRun, flow_id: str) -> str:
    """Return the enrollment an elicited judgement belongs to.

    A launch-gated visit has a durable enrollment. An ungated demo has none, so the
    assignment names the flow's own derived stand-in and the record stays within one
    visit, which is all an ungated run can honestly claim.
    """
    return run.enrollment_id or gateway.derived_id("enrollment", flow_id)


# -- durability -------------------------------------------------------------------


async def _durable_state(
    run: _ChatRun,
    durable: ChatDurability | None,
    *,
    visit_id: str,
    channel_key: str,
    store: Store,
) -> TranscriptState | None:
    """Load or open the durable transcript for this conversation."""
    if durable is None:
        return None
    stored = read_transcript(
        store, transcript_id_for(durable.derive, visit_id, durable.occurrence_key)
    )
    run.committed = None if stored is None else stored.version.revision
    return opened(
        stored,
        visit_id=visit_id,
        interaction_id=run.room.interaction_id,
        channel_key=channel_key,
    )


async def _commit_state(
    run: _ChatRun,
    durable: ChatDurability | None,
    *,
    visit_id: str,
    store: Store,
    new_context: NewContext,
    updated: TranscriptState,
) -> None:
    """Commit the transcript at the revision it was read at, and hold the new one.

    The record's own revision is the store's revision, so a second connection that
    writes between the read and the commit wins and this one is refused rather than
    overwriting the conversation it did not see.
    """
    if durable is None or run.state is None:
        return
    transcript_id = transcript_id_for(
        durable.derive, visit_id, durable.occurrence_key
    )
    revision = (run.committed or 0) + 1
    numbered = updated.model_copy(
        update={
            "version": VersionStamp(
                revision=revision, etag=updated.version.etag
            )
        }
    )
    if await record_transcript(
        numbered,
        transcript_id=transcript_id,
        expected_revision=run.committed,
        context=new_context(transcript_id),
        store=store,
    ):
        run.state = numbered
        run.committed = revision


async def _restore(
    websocket: WebSocket, run: _ChatRun, durable: ChatDurability, store: Store
) -> None:
    """Put the participant back in the conversation they were already having.

    The committed history first, in order, then the pending turn if one was in
    flight. A reconnection that showed an empty screen would be telling them the
    conversation never happened.

    The history goes back into the **room** as well as onto the screen. Otherwise a
    model seat would read an empty conversation while the participant is looking at
    a full one -- which is what happens when one written conversation is placed on
    two activities, because the second activity's room is a new room.
    """
    state = run.state
    if state is None or not state.messages:
        return
    for record in history(state):
        text = (
            await durable.artifacts.read_artifact(record.artifact_id)
        ).decode("utf-8")
        _carry(run, store, record.message_id, text)
        await websocket.send_json(
            {
                "type": "chat",
                "message_id": record.message_id,
                "author_actor_id": record.author_actor_id,
                "author": (
                    "you"
                    if record.author_actor_id == run.participant_actor_id
                    else "them"
                ),
                "sequence": record.sequence,
                "text": text,
                "restored": True,
            }
        )
    if state.pending is not None:
        await websocket.send_json(
            {
                "type": "chat_pending",
                "generation": state.pending.generation,
                "prompt_message_id": state.pending.prompt_message_id,
            }
        )


def _carry(run: _ChatRun, store: Store, message_id: str, text: str) -> None:
    """Carry one already-recorded message back into the room, words and all.

    The record is read from the store rather than rebuilt from the transcript,
    because a context snapshot names the messages a model saw and those have to be
    the messages that were really committed. A message the store no longer holds is
    put on the screen without being put in the context: showing what was said is
    right, and claiming a model read a record nobody can produce is not.
    """
    run.room.remember(message_id, text)
    recorded = store.load_aggregate(message_id)
    if not isinstance(recorded, dict):
        return
    run.room.carry(ChatMessage.model_validate(recorded), text)


async def _record_reply_generation(
    durable: ChatDurability | None,
    spec: ChatSpec,
    seat: ChatSeatSpec,
    reply: ChatReply,
    *,
    store: Store,
    new_context: NewContext,
) -> None:
    """Record one live model reply as a durable generation.

    A reply the participant read is a model output like any other, and a study that
    wants to ask "which of these two answers is better" needs it to be one: the
    three output forms staged, the provider named in a private provenance artifact,
    and the whole thing committed under an address derived from the reply. Without
    this a live conversation could produce nothing a preference activity could ask
    about (see ``mug.agents.generation``).

    A reply with no provider response behind it -- a replay from a terminal head --
    records nothing, because there is nothing to say about where it came from.
    """
    if durable is None or reply.response is None or reply.modelcall_id is None:
        return
    if reply.response.output_digest is None or reply.output is None:
        return
    tape = ArtifactOutputTape(
        durable.artifacts,
        artifact_id_for=durable.new_artifact_id,
        new_upload_id=durable.new_upload_id,
        now=_instant,
        normalize=spec.normalize,
        render=spec.render_reply or _default_render_reply,
    )
    forms = await tape.stage(reply.response.output_digest, reply.output)
    generation_id = durable.derive(
        "generation", f"chat-reply:{reply.message.message_id}"
    )
    await record_reply(
        generation_id=generation_id,
        generation_key=reply.message.message_id,
        input_digest=reply.response.output_digest.hex,
        modelcall_id=reply.modelcall_id,
        build=compile_agent(seat.agent, ids=seat.ids),
        response=reply.response,
        forms=forms,
        artifacts=durable.artifacts,
        artifact_id_for=durable.new_artifact_id,
        new_upload_id=durable.new_upload_id,
        now=_instant,
        context=new_context(generation_id),
        store=store,
    )


async def _stage_text(durable: ChatDurability, message_id: str, text: str) -> str:
    """Store one message's words where the transcript can point at them."""
    reference = await stage_artifact(
        durable.artifacts,
        data=text.encode("utf-8"),
        media_type="text/plain",
        new_artifact_id=lambda: durable.new_artifact_id(
            message_artifact_seed(message_id)
        ),
        new_upload_id=durable.new_upload_id,
        now=lambda: _instant(),
        data_handling=_PARTICIPANT_TEXT,
    )
    return reference.artifact_id


def _instant() -> str:
    """Return the current instant in the wire format the records carry."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


async def run_chat_activity(
    websocket: WebSocket,
    session: Session,
    spec: ChatSpec,
    *,
    store: Store,
    new_context: NewContext,
    new_id: NewId,
    now: Callable[[], datetime],
    durable: ChatDurability | None = None,
    rendezvous: ChatRendezvous | None = None,
    frames: FrameChannel | None = None,
    gateway: Gateway | None = None,
) -> list[str]:
    """Own the socket for one chat activity and return the streams it recorded.

    The loop reads the participant's chat frames, records each exchange as canonical
    evidence, and pushes every message this seat may see back. It ends when the
    participant sends an end frame, when the message bound is reached, or when the
    connection closes. An empty message is ignored and a long one is trimmed, so a
    participant can not post an unbounded payload and can not spend a turn on
    nothing.

    ``rendezvous`` matches this connection with the others in its room. Without one
    the connection is a room of one, which is what a study with a single participant
    per conversation wants. ``durable`` keeps the conversation across connections.
    ``frames`` is set when a game shares this socket: the conversation then reads
    the router's channel rather than the socket, because two readers on one socket
    race for every frame.

    The returned stream ids name the streams this activity committed on, so the flow
    records where the conversation's lineage lives.
    """
    flow_id = session.state.get("flow_id")
    if not isinstance(flow_id, str):
        return []
    visit_id = session.state.get("visit_id")
    activity_key = session.state.get("game_activity_key")
    seat = (
        await rendezvous.join(
            visit_id=visit_id if isinstance(visit_id, str) else "",
            activity_key=activity_key if isinstance(activity_key, str) else None,
        )
        if rendezvous is not None
        else _seat_a_room(spec, store=store, new_id=new_id, now=now)
    )
    _place_model_seats(spec, seat.room)
    session.state["chat_interaction_id"] = seat.room.interaction_id
    enrollment_id = session.state.get("enrollment_id")
    run = _ChatRun(
        seat=seat,
        agents=_build_agents(spec, seat.room, store=store, new_id=new_id, now=now),
        enrollment_id=enrollment_id if isinstance(enrollment_id, str) else None,
    )
    visible = seat.room.visible_channels(run.participant_actor_id)
    if len(spec.room_channels) > 1 or spec.participants > 1:
        # What this client is told the conversation *is*. A channel this
        # participant is not in is absent from it, so their client never learns
        # that the channel exists. A room with one public channel and one
        # participant is told nothing, because there is nothing it does not know.
        await websocket.send_json(
            {"type": "chat_room", "channels": list(visible), "seat": seat.seat_key}
        )

    if durable is not None and isinstance(visit_id, str):
        run.state = await _durable_state(
            run,
            durable,
            visit_id=visit_id,
            channel_key=visible[0] if visible else spec.channel_key,
            store=store,
        )
        await _restore(websocket, run, durable, store)
    else:
        durable = None

    async def sink(message: ChatMessage, text: str) -> None:
        """Push one message this seat may see, and add it to its own transcript."""
        await _send_chat(
            websocket,
            message,
            text,
            mine=message.author_actor_id == run.participant_actor_id,
        )
        await _remember(
            run,
            durable,
            visit_id=visit_id,
            store=store,
            new_context=new_context,
            message=message,
            text=text,
        )

    seat.room.attach(run.participant_actor_id, sink)
    try:
        await _converse(
            websocket,
            run,
            spec,
            durable,
            visit_id=visit_id,
            flow_id=flow_id,
            principal=session.principal,
            store=store,
            new_context=new_context,
            new_id=new_id,
            visible=visible,
            read=_reader(websocket, frames),
            gateway=gateway,
        )
    finally:
        seat.room.detach(run.participant_actor_id)
    return run.streams


async def _greet(
    run: _ChatRun,
    spec: ChatSpec,
    *,
    new_context: NewContext,
    new_id: NewId,
) -> None:
    """Post and deliver each seat's opening message, when the study set one.

    The greeting is posted once for the room, not once per connection: the second
    participant to arrive joins a conversation that has already been opened, and the
    room's fan-out gives them the opener as history rather than as a second hello.
    """
    for index, seat in enumerate(spec.model_seats):
        speaks = spec.channel_of(seat)
        greeting = seat.greeting or (spec.greeting if index == 0 else None)
        if greeting is None or run.room.history(speaks):
            continue
        posted = await run.room.post(
            actor_id=seat.actor_id,
            channel_key=speaks,
            text=greeting,
            message_id=new_id("message"),
            new_context=new_context,
        )
        if posted is None:
            continue
        run.capture(posted.stream_id)
        await run.room.deliver(
            posted.message, new_context=new_context, new_id=new_id
        )


async def _converse(
    websocket: WebSocket,
    run: _ChatRun,
    spec: ChatSpec,
    durable: ChatDurability | None,
    *,
    visit_id: Any,
    flow_id: str,
    principal: PrincipalRef,
    store: Store,
    new_context: NewContext,
    new_id: NewId,
    visible: Sequence[str],
    read: ReadFrame,
    gateway: Gateway | None,
) -> None:
    """Read this seat's frames until the conversation ends, and answer each one."""
    await run.room.flush(
        run.participant_actor_id, new_context=new_context, new_id=new_id
    )
    await _greet(run, spec, new_context=new_context, new_id=new_id)

    posted = 0
    while posted < spec.max_messages:
        frame = await read()
        if frame is None or frame.get("type") == "chat_end":
            return
        if frame.get("type") != "chat":
            continue
        text = _participant_text(frame, spec.max_message_length)
        channel_key = _frame_channel(frame, visible)
        if not text or channel_key is None:
            continue
        posted += 1
        said = await run.room.post(
            actor_id=run.participant_actor_id,
            channel_key=channel_key,
            text=text,
            message_id=new_id("message"),
            new_context=new_context,
        )
        if said is None:
            continue
        message = said.message
        run.capture(said.stream_id)
        # The sink is what adds a message to this connection's transcript, and the
        # room does not deliver an author their own words. So the participant's own
        # message is remembered here, or their transcript would hold only replies.
        await _remember(
            run,
            durable,
            visit_id=visit_id,
            store=store,
            new_context=new_context,
            message=message,
            text=text,
        )
        await run.room.deliver(message, new_context=new_context, new_id=new_id)
        generation = await _begin(
            run,
            durable,
            visit_id=visit_id,
            store=store,
            new_context=new_context,
            prompt_message_id=message.message_id,
        )
        if _elicited(spec, gateway, message.message_id) and await _elicit_turn(
            websocket,
            run,
            spec,
            durable,
            elicit=cast("Elicit", spec.elicit_preference),
            gateway=cast("Gateway", gateway),
            visit_id=visit_id,
            flow_id=flow_id,
            principal=principal,
            store=store,
            new_context=new_context,
            new_id=new_id,
            channel_key=channel_key,
            prompt_text=text,
            prompt_message_id=message.message_id,
            caused_by=said.event_id,
            generation=generation,
            read=read,
        ):
            await _end(
                run, durable, visit_id=visit_id, store=store, new_context=new_context
            )
            continue
        answered = await _take_turns(
            run,
            spec,
            new_context=new_context,
            new_id=new_id,
            channel_key=channel_key,
            prompt_text=text,
            caused_by=said.event_id,
        )
        if not answered:
            await _end(
                run, durable, visit_id=visit_id, store=store, new_context=new_context
            )
            continue
        if not await _may_publish(
            run,
            durable,
            visit_id=visit_id,
            store=store,
            new_context=new_context,
            generation=generation,
        ):
            # Replies begun on a connection that has since been replaced. They are
            # recorded as discarded and shown to nobody: publishing them would put
            # an answer to a question this conversation has moved past into it.
            continue
        for seat, reply in answered:
            await run.room.deliver(
                reply.message, new_context=new_context, new_id=new_id
            )
            await _record_reply_generation(
                durable, spec, seat, reply, store=store, new_context=new_context
            )
        await _end(
            run, durable, visit_id=visit_id, store=store, new_context=new_context
        )


async def _remember(
    run: _ChatRun,
    durable: ChatDurability | None,
    *,
    visit_id: Any,
    store: Store,
    new_context: NewContext,
    message: ChatMessage,
    text: str,
) -> None:
    """Stage one message's words and add it to the durable transcript."""
    if durable is None or run.state is None or not isinstance(visit_id, str):
        return
    artifact_id = await _stage_text(durable, message.message_id, text)
    await _commit_state(
        run,
        durable,
        visit_id=visit_id,
        store=store,
        new_context=new_context,
        updated=with_message(
            run.state,
            message_id=message.message_id,
            author_actor_id=message.author_actor_id,
            artifact_id=artifact_id,
            sequence=message.sequence,
            content_digest=message.content_digest,
            delivered_at=_instant(),
        ),
    )


async def _begin(
    run: _ChatRun,
    durable: ChatDurability | None,
    *,
    visit_id: Any,
    store: Store,
    new_context: NewContext,
    prompt_message_id: str,
) -> int:
    """Open a model turn at the next generation, and return that generation."""
    if durable is None or run.state is None or not isinstance(visit_id, str):
        return 0
    await _commit_state(
        run,
        durable,
        visit_id=visit_id,
        store=store,
        new_context=new_context,
        updated=with_turn_begun(
            run.state, prompt_message_id=prompt_message_id, started_at=_instant()
        ),
    )
    return run.state.generation


async def _may_publish(
    run: _ChatRun,
    durable: ChatDurability | None,
    *,
    visit_id: Any,
    store: Store,
    new_context: NewContext,
    generation: int,
) -> bool:
    """Return whether this reply may still be shown, recording it if it may not."""
    if durable is None or run.state is None or not isinstance(visit_id, str):
        return True
    current = read_transcript(
        store, transcript_id_for(durable.derive, visit_id, durable.occurrence_key)
    )
    if current is not None:
        run.state = current
        run.committed = current.version.revision
    if is_current(run.state, generation):
        return True
    await _commit_state(
        run,
        durable,
        visit_id=visit_id,
        store=store,
        new_context=new_context,
        updated=with_discarded(run.state, generation, discarded_at=_instant()),
    )
    return False


async def _end(
    run: _ChatRun,
    durable: ChatDurability | None,
    *,
    visit_id: Any,
    store: Store,
    new_context: NewContext,
) -> None:
    """Close the model turn, so a reconnection is not told one is still coming."""
    if durable is None or run.state is None or not isinstance(visit_id, str):
        return
    if run.state.pending is None:
        return
    await _commit_state(
        run,
        durable,
        visit_id=visit_id,
        store=store,
        new_context=new_context,
        updated=with_turn_ended(run.state),
    )


__all__ = [
    "ChatChannel",
    "ChatDurability",
    "ChatRendezvous",
    "ChatSeatSpec",
    "ChatSpec",
    "ComposeChat",
    "NewId",
    "RenderReply",
    "RoomSeat",
    "run_chat_activity",
]
