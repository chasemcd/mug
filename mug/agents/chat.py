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

from collections.abc import Callable
from dataclasses import dataclass

from mug.conversation import ChatMessage, ConversationChannel, TurnPolicy, may_activate
from mug.kernel import compute_digest
from mug.providers import AgentVersion, ModelProvider
from mug.providers.runtime import NewContext, Payload, SecretResolver

# The study turns the recent messages into the model payload (it resolves the message
# text from its own content store). The core stays out of content resolution.
ComposePrompt = Callable[[list[ChatMessage]], Payload]


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
    ) -> None:
        self._agent_version = agent_version
        self._provider = provider
        self._channel = channel
        self._policy = policy
        self._agent_actor_id = agent_actor_id
        self._compose = compose
        self._resolve_secret = resolve_secret
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
    ) -> ChatMessage | None:
        """Run one chat turn; return the posted reply, or None when it stays silent.

        The turn posts nothing when the policy does not admit it or when the model
        does not complete. A completed call posts the reply (its content digest is the
        model output digest) and records the context snapshot, then counts one
        activation toward the cap.
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

        _, message = await self._channel.post(
            context=new_context(turn.reply_message_id),
            message_id=turn.reply_message_id,
            author_actor_id=self._agent_actor_id,
            content_digest=result.response.output_digest,
            visibility="public",
            idempotency_key=turn.idempotency_key,
        )
        await self._channel.snapshot(
            context=new_context(turn.snapshot_id),
            message_id=turn.reply_message_id,
            model_request_digest=compute_digest(payload),
            included_message_ids=[m.message_id for m in recent],
        )
        self._activations += 1
        return message


__all__ = ["ChatAgent", "ChatTurn", "ComposePrompt"]
