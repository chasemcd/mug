"""Drive one agent seat in a chat channel: decide, call the model, post the reply.

This is the chat analog of ``AgentEpisode``. Where the episode runner joins the game
loop and the provider for an LLM *seat*, ``ChatAgent`` joins the conversation channel
(API-08) and the provider (API-13) for an LLM *turn*. It lives in ``mug.agents``, the
one layer that may import both the channel (below it) and the provider (below it),
because the channel must not import the provider -- exactly as the game loop holds the
seat seam but never the scheduler.

One turn runs in three steps, each recorded as canonical evidence:

1. **Decide to speak.** The pure ``may_activate`` policy (``mug.conversation.turns``)
   says whether the model may activate now, under the channel's turn policy and the
   activation cap. A turn that may not activate posts nothing.
2. **Call the model.** The provider runs one recorded model call over the rendered
   recent context. A refused or errored call posts nothing -- silence is the turn's
   fallback -- so a provider outage never fabricates a reply.
3. **Post and pin.** The reply posts back to the channel as a message the agent
   authored, and its content digest *is* the model output's own digest, so the reply
   is recorded by digest exactly as the model output is (and the durable output tape
   can rehydrate the verbatim reply on replay). A context snapshot pins the request
   digest and the messages the model saw, the chat analog of a decision's
   source-observation digest.

The channel does not hold message text (it records a content digest), so the study
injects ``compose``: it turns the recent messages into the model payload, closing
over its own content resolver. This keeps the core out of message-content resolution,
exactly as the observation encoder keeps it out of environment state.

The runtime is a producer boundary: the caller injects the context factory that mints
a fresh ``CommandContext`` per record (the model call, the posted message, and the
snapshot), so a test drives a whole turn with a fixed clock and no socket.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from mug.conversation import ChatMessage, ConversationChannel, TurnPolicy, may_activate
from mug.kernel import CommandReceipt, compute_digest
from mug.providers import AgentVersion, ModelProvider, ProviderResponse
from mug.providers.runtime import NewContext, Output, Payload, SecretResolver
from mug.runtime import answering

# The study turns the recent messages into the model payload (it resolves the message
# text from its own content store). The core stays out of content resolution.
ComposePrompt = Callable[[list[ChatMessage]], Payload]


@dataclass(frozen=True)
class ChatReply:
    """The reply one turn produced: the recorded message and its raw output.

    ``message`` is the canonical evidence -- it names the reply by digest, exactly as
    the model output is named by digest. ``output`` is the model's raw output, held
    only for the caller and never persisted here, so a transport can render the
    reply to a participant while the ledger keeps the digest. A call replayed from a
    terminal head carries no raw output, so ``output`` is ``None`` there; the durable
    output tape (API-16) is what rehydrates the verbatim text on a replay.
    ``stream_id`` is the stream the reply committed on, so a transport reports where
    the turn's lineage lives without guessing at the id derivation.
    ``response`` is the provider's own response record -- the resolved model, the
    usage, and the output digest -- which a transport needs to record the reply as a
    durable generation. Without it a live reply could never become a preference
    candidate, because there would be no provenance to record beside it.
    """

    message: ChatMessage
    output: Output = None
    stream_id: str | None = None
    response: ProviderResponse | None = None
    modelcall_id: str | None = None


@dataclass(frozen=True)
class PendingReply:
    """A completed model call that has not been posted to the channel yet.

    Composing a turn and publishing it are separate because a room may hold several
    model seats. Their calls run at the same time -- two models thinking one after
    the other is latency nobody asked for -- but their replies must enter the
    channel in the order the study declared, not in the order the providers
    happened to finish. So the calls are composed concurrently and the publications
    are a serialized loop.
    """

    payload: Payload
    included_message_ids: list[str]
    response: ProviderResponse
    output: Output
    modelcall_id: str


@dataclass(frozen=True)
class ChatTurn:
    """The identifiers one chat turn mints: the reply, its snapshot, and the call.

    The caller (the gateway) content-addresses these ids and passes them as data, so
    the runtime mints no identifiers of its own. ``reply_message_id`` and
    ``snapshot_id`` are the two aggregates the turn writes; ``modelcall_id`` is the
    model call's stream; ``idempotency_key`` guards the posted message.
    """

    reply_message_id: str
    snapshot_id: str
    modelcall_id: str
    idempotency_key: str


class ChatAgent:
    """Compose the channel and the provider to run one LLM chat turn.

    The agent holds the injected build and runtime -- the pinned ``AgentVersion``, the
    provider, the channel, the turn policy, the agent's actor id, and the prompt
    composer -- and exposes one operation, ``take_turn``. It owns the running count of
    the model's activations this turn, so the activation cap holds across turns.
    """

    def __init__(
        self,
        *,
        agent_version: AgentVersion,
        provider: ModelProvider,
        channel: ConversationChannel,
        policy: TurnPolicy,
        agent_actor_id: str,
        compose: ComposePrompt,
        resolve_secret: SecretResolver | None = None,
        visibility: Literal["public", "team", "private"] = "public",
    ) -> None:
        self._agent_version = agent_version
        self._provider = provider
        self._channel = channel
        self._policy = policy
        self._agent_actor_id = agent_actor_id
        self._compose = compose
        self._resolve_secret = resolve_secret
        self._visibility: Literal["public", "team", "private"] = visibility
        self._activations = 0

    @property
    def actor_id(self) -> str:
        """Return the actor the replies of this seat are authored by."""
        return self._agent_actor_id

    @property
    def activations(self) -> int:
        """Return how much of this turn's model budget the seat has spent.

        The budget is what stops a study from turning one message into a storm of
        model calls, so what it counts is worth being able to read. D08-5 says a
        candidate set is one activation however many candidates it holds, and this
        is where that claim is checkable.
        """
        return self._activations

    def begin_turn(self) -> None:
        """Start a new turn: give the model its full activation budget again.

        ``max_model_activations_per_turn`` caps the activations of *one* turn, so a
        caller that runs turn after turn -- a live channel, where each participant
        message opens a turn -- calls this at the start of each one. A caller that
        never calls it keeps one budget for the life of the agent.
        """
        self._activations = 0

    async def take_turn(
        self,
        *,
        turn: ChatTurn,
        recent: list[ChatMessage],
        new_context: NewContext,
        mentioned: bool = False,
        is_my_turn: bool = True,
        moderator_cleared: bool = False,
    ) -> ChatReply | None:
        """Run one chat turn; return the posted reply, or None when it stays silent.

        The turn posts nothing when the policy does not admit it or when the model
        does not complete. A completed call posts the reply (its content digest is the
        model output digest) and records the context snapshot, then counts one
        activation toward the cap. The returned reply carries the raw model output
        beside the recorded message, so a transport renders the text to a participant
        while only the digest enters the ledger.
        """
        pending = await self.compose_turn(
            turn=turn,
            recent=recent,
            new_context=new_context,
            mentioned=mentioned,
            is_my_turn=is_my_turn,
            moderator_cleared=moderator_cleared,
        )
        if pending is None:
            return None
        return await self.publish(pending, turn=turn, new_context=new_context)

    async def compose_turn(
        self,
        *,
        turn: ChatTurn,
        recent: list[ChatMessage],
        new_context: NewContext,
        mentioned: bool = False,
        is_my_turn: bool = True,
        moderator_cleared: bool = False,
    ) -> PendingReply | None:
        """Decide, and call the model. Nothing is posted to the channel here.

        This is the half of a turn that a room may run for several seats at once,
        because a model call touches only its own model-call stream. What it returns
        is what ``publish`` needs, and what a seat that stays silent does not return
        at all.
        """
        if not may_activate(
            self._policy,
            activations_so_far=self._activations,
            mentioned=mentioned,
            is_my_turn=is_my_turn,
            moderator_cleared=moderator_cleared,
        ):
            return None

        payload = self._compose(recent)
        result = await self._provider.invoke(
            modelcall_id=turn.modelcall_id,
            agent_version=self._agent_version,
            payload=payload,
            new_context=new_context,
            resolve_secret=self._resolve_secret,
        )
        if result.response is None or result.response.output_digest is None:
            return None  # a refusal or an error stays silent (the turn's fallback)
        return PendingReply(
            payload=payload,
            included_message_ids=[m.message_id for m in recent],
            response=result.response,
            output=result.output,
            modelcall_id=turn.modelcall_id,
        )

    async def compose_candidates(
        self,
        *,
        turns: Sequence[ChatTurn],
        recent: list[ChatMessage],
        new_context: NewContext,
        mentioned: bool = False,
        is_my_turn: bool = True,
        moderator_cleared: bool = False,
    ) -> list[PendingReply]:
        """Call the model once for each candidate reply this turn may present.

        Every candidate answers the same prompt, so the model reads one context and
        the calls differ only by their model-call identity. They run at the same
        time, because two candidates thinking one after the other is latency for
        nothing.

        **One candidate set is one activation.** The turn is asked for once, and the
        budget is spent once whatever ``n`` is (D08-5), because the alternative lets
        a study widen a turn's model budget by asking for more candidates. The
        activation is spent here rather than at publication, for the same reason the
        room applies its own budget before the calls: the calls are already made.

        A model that stays silent, errors, or is refused contributes no candidate,
        so a set that comes back short is a set the caller must not present.
        """
        if not may_activate(
            self._policy,
            activations_so_far=self._activations,
            mentioned=mentioned,
            is_my_turn=is_my_turn,
            moderator_cleared=moderator_cleared,
        ):
            return []
        self._activations += 1
        payload = self._compose(recent)
        included = [message.message_id for message in recent]
        results = await asyncio.gather(
            *(
                self._provider.invoke(
                    modelcall_id=turn.modelcall_id,
                    agent_version=self._agent_version,
                    payload=payload,
                    new_context=new_context,
                    resolve_secret=self._resolve_secret,
                )
                for turn in turns
            )
        )
        composed: list[PendingReply] = []
        for turn, result in zip(turns, results, strict=True):
            if result.response is None or result.response.output_digest is None:
                continue
            composed.append(
                PendingReply(
                    payload=payload,
                    included_message_ids=list(included),
                    response=result.response,
                    output=result.output,
                    modelcall_id=turn.modelcall_id,
                )
            )
        return composed

    async def publish(
        self,
        pending: PendingReply,
        *,
        turn: ChatTurn,
        new_context: NewContext,
        caused_by: str | None = None,
        counts: bool = True,
    ) -> ChatReply:
        """Post one composed reply to the channel and pin the context it read.

        This is the half a room serializes, so the channel's order is the study's
        declared seat order rather than whichever provider answered first.

        ``caused_by`` is the event of the message this reply answers. Each message
        is its own aggregate on its own stream, so without it a reply and its prompt
        are two records with no stated relation; with it, an analysis can follow
        what answered what without one order being imposed over all of them.

        ``counts`` is unset for one reply of a candidate set, whose single
        activation ``compose_candidates`` already spent. Counting each candidate
        again would let a set of three spend the budget of three turns.
        """
        assert pending.response.output_digest is not None
        posted, message = await self._channel.post(
            context=answering(new_context(turn.reply_message_id), caused_by),
            message_id=turn.reply_message_id,
            author_actor_id=self._agent_actor_id,
            content_digest=pending.response.output_digest,
            visibility=self._visibility,
            idempotency_key=turn.idempotency_key,
        )
        await self._channel.snapshot(
            context=new_context(turn.snapshot_id),
            message_id=turn.reply_message_id,
            model_request_digest=compute_digest(pending.payload),
            included_message_ids=pending.included_message_ids,
        )
        if counts:
            self._activations += 1
        return ChatReply(
            message=message,
            output=pending.output,
            stream_id=_stream_of(posted),
            response=pending.response,
            modelcall_id=pending.modelcall_id,
        )


def _stream_of(receipt: CommandReceipt) -> str | None:
    """Return the stream one accepted commit wrote to, or None when it wrote none."""
    positions = receipt.stream_positions
    if not positions:
        return None
    return max(positions.items(), key=lambda item: item[1])[0]


__all__ = ["ChatAgent", "ChatReply", "ChatTurn", "ComposePrompt", "PendingReply"]
