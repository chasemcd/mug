"""The LLM agent runtime: drive an author's ``LLMAgent`` with the built stack.

This is the runtime behind the author-facing ``mug.authoring.LLMAgent``. It sits
above the provider and scheduler families -- which are siblings and cannot import
each other -- and composes them: it turns the author's ``get_prompt`` into a model
call through the built ``ModelProvider`` (P3b), reads the reply back into an action
with ``parse_reply``, and carries the model's own reasoning forward with ``reflect``.
The result is an ``AsyncController`` the built ``Scheduler`` (P3c) awaits under a
deadline, so a slow model never blocks a frame and every call is recorded.

The split is deliberate. ``LLMAgent`` is an immutable *definition* in the authoring
layer, with stateless methods. ``LLMController`` here is the per-seat *runtime*: it
holds the live environment, the growing ``Thoughts`` buffer, and the ``History`` the
loop feeds it, and it calls the definition's methods with that state on each
decision. ``compile_agent`` pins the definition into the frozen ``AgentVersion`` the
provider needs.

The durable thought tape (API-16) is now available: a study injects an
``OutputTape`` into the ``ModelProvider`` (``mug.providers``), and a completed model
output is persisted content-addressed by its digest and rehydrated on a replay. So a
decision that reasons over its own prior model output -- a carried thought -- replays
exactly: a retry after a crash re-derives the reply and the action instead of
falling back. The tape is opt-in; without it the controller still runs, but a replay
sees the output by digest only. ``mug.replay.build_decision_tape`` assembles the
API-16 tape from an episode's recorded calls for a replay bundle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from mug.authoring import (
    Chat,
    Fallback,
    History,
    LLMAgent,
    Message,
    Provider,
    Step,
    Thoughts,
)
from mug.kernel import compute_digest
from mug.providers import AgentVersion, ModelCallResult, ModelProvider
from mug.providers.runtime import NewContext, SecretResolver
from mug.providers.types import Provider as ProviderName
from mug.scheduling.runtime import DecisionContext

# The author's provider enum maps to the internal provider name the record carries.
_PROVIDER: dict[Provider, ProviderName] = {
    Provider.OPENAI: "openai",
    Provider.ANTHROPIC: "anthropic",
    Provider.OSS: "oss",
    Provider.HTTP: "http",
}

# The credential name a keyless local provider carries. The frozen record still names
# a secret, so a local run (Ollama) names this well-known no-op key instead of a real
# credential; the runtime resolves no value for it and passes no secret to the adapter.
LOCAL_NO_KEY = "local-no-key"

# The providers that may run without a credential. A hosted provider always needs a
# key, so an agent that names one without a ``secret`` is refused at compile time.
_KEYLESS_PROVIDERS: frozenset[Provider] = frozenset({Provider.OSS, Provider.HTTP})


class ControllerDecodeMiss(Exception):
    """The reply could not be read as a legal action; the seat must fall back.

    The controller raises this when ``parse_reply`` returns ``None``. The scheduler
    catches it, records the decision as failed, and applies the seat fallback -- so
    an unreadable reply degrades to the fallback action, never to a guess.
    """


@dataclass(frozen=True)
class AgentIds:
    """The pinned identifiers a published agent build carries.

    In a full study these come from ``AgentCatalog.publish``; ``compile_agent`` takes
    them as data so the runtime mints no identifiers of its own.
    """

    agent_version_id: str
    agent_definition_id: str
    agent_key: str
    version_number: int
    prompt_version_id: str
    fallback_policy_key: str


def compile_agent(agent: LLMAgent, *, ids: AgentIds) -> AgentVersion:
    """Pin an author's ``LLMAgent`` definition into the frozen ``AgentVersion``.

    The provider enum and the sampling configuration become the record's typed
    fields; the parameters that shape a call fold into ``parameters_digest`` so the
    build is content-addressed. The secret is named, never valued.

    A hosted provider needs a credential, so an agent that names one without a
    ``secret`` is refused. A local provider (Ollama) needs none: the agent leaves
    ``secret`` unset, and the build names the well-known ``LOCAL_NO_KEY`` so the
    frozen record still carries a secret name while the runtime resolves no value.
    """
    parameters_digest = compute_digest(
        {
            "model": agent.model,
            "temperature": agent.temperature,
            "decides_every": agent.decides_every,
            "on_timeout": agent.on_timeout.value,
        }
    )
    return AgentVersion(
        agent_version_id=ids.agent_version_id,
        agent_definition_id=ids.agent_definition_id,
        agent_key=ids.agent_key,
        version_number=ids.version_number,
        provider=_PROVIDER[agent.provider],
        model_selector=agent.model,
        prompt_version_id=ids.prompt_version_id,
        parameters_digest=parameters_digest,
        tool_version_ids=[],
        fallback_policy_key=ids.fallback_policy_key,
        secret_name=_secret_name(agent),
    )


def _secret_name(agent: LLMAgent) -> str:
    """Return the credential name a build names, or refuse a keyless hosted agent.

    An agent that sets ``secret`` names it. An agent that leaves it unset must use a
    keyless provider (a local Ollama runner); it then names ``LOCAL_NO_KEY``. A
    hosted provider with no secret is a mistake, so this refuses it with a clear
    message rather than name a no-op key the provider would reject at call time.
    """
    if agent.secret is not None:
        return agent.secret
    if agent.provider not in _KEYLESS_PROVIDERS:
        raise ValueError(
            f"provider {agent.provider.name} needs a credential; "
            f"set `secret` on the agent (the name is bound at deploy)"
        )
    return LOCAL_NO_KEY


def timeout_fallback(agent: LLMAgent) -> Fallback:
    """Return the author's declared timeout fallback (for the scheduler to apply)."""
    return agent.on_timeout


class LLMController:
    """Drive one seat with an ``LLMAgent`` definition and the built provider.

    ``decide`` is the ``AsyncController`` the scheduler awaits: it builds the prompt
    from the definition, calls the model, carries a thought forward, and reads the
    reply into an action. The controller holds the per-seat runtime state -- the live
    environment, the ``Thoughts`` the model builds up, and the ``History`` the loop
    records -- and calls the stateless definition methods with it.
    """

    def __init__(
        self,
        *,
        agent: LLMAgent,
        agent_version: AgentVersion,
        provider: ModelProvider,
        env: Any,
        agent_id: str,
        new_context: NewContext,
        resolve_secret: SecretResolver | None = None,
        history: History | None = None,
        chat: Chat | None = None,
        thoughts: Thoughts | None = None,
    ) -> None:
        self._agent = agent
        self._agent_version = agent_version
        self._provider = provider
        self._env = env
        self._agent_id = agent_id
        self._new_context = new_context
        self._resolve_secret = resolve_secret
        self.history = history if history is not None else History()
        self.chat = chat if chat is not None else Chat()
        self.thoughts = thoughts if thoughts is not None else Thoughts()
        # Every model call this seat makes, in call order, so the episode runner can
        # hand them to ``build_decision_tape`` at the end for a replay bundle.
        self.results: list[ModelCallResult] = []
        # What this seat said on its last decision, waiting to be published. It is
        # held here rather than returned, because the scheduler decides *actions*:
        # a deadline and a fallback are about what a seat does, not what it says.
        self.pending_message: str | None = None

    async def decide(self, ctx: DecisionContext) -> int:
        """Build the prompt, call the model, and return the parsed action.

        The reply's carried thought (from ``reflect``) is appended before the action
        is read, so the model builds on its own reasoning next step. An unreadable
        reply raises ``ControllerDecodeMiss`` so the scheduler applies the fallback.
        """
        prompt = self._agent.get_prompt(
            self._env, self._agent_id, self.history, self.chat, self.thoughts
        )
        modelcall_id = "modelcall_" + ctx.request.decision_id.split("_", 1)[1]
        payload: dict[str, Any] = {"messages": [{"role": "user", "content": prompt}]}
        if self._agent.temperature is not None:
            payload["temperature"] = self._agent.temperature
        # A keyless local agent resolves no secret, so the adapter receives none; a
        # hosted agent resolves its named credential through the injected resolver.
        resolve_secret = (
            self._resolve_secret if self._agent.secret is not None else None
        )
        result = await self._provider.invoke(
            modelcall_id=modelcall_id,
            agent_version=self._agent_version,
            payload=payload,
            new_context=self._new_context,
            resolve_secret=resolve_secret,
        )
        self.results.append(result)
        reply = _reply_text(result.output)
        thought = self._agent.reflect(reply, self._env, self._agent_id)
        if thought is not None:
            self.thoughts.append(thought)
        # What the seat says is read out **before** the action, because an
        # unreadable action must not cost the participant a message the model
        # really produced. A reply that says "going left" and then names no action
        # anybody can read has still said it, and the seat falls back on the action
        # alone. The two are judged apart, which is what NS-07 asks for.
        self.pending_message = self._agent.say(reply, self._env, self._agent_id)
        action = self._agent.parse_reply(reply, self._env, self._agent_id)
        if action is None:
            raise ControllerDecodeMiss(f"could not read an action from: {reply!r}")
        return int(action)

    def take_message(self) -> str | None:
        """Take what this seat said on its last decision, if it said anything.

        Taking rather than reading is what keeps one reply from being published
        twice: a decision that says something says it once, and a later decision
        that says nothing does not repeat it.
        """
        said, self.pending_message = self.pending_message, None
        return said

    def record_step(self, step: Step) -> None:
        """Append one game transition to the history the agent reads next decision."""
        self.history.append(step)

    def record_message(self, message: Message) -> None:
        """Append one chat message to the chat the agent reads next decision."""
        self.chat.append(message)


def _reply_text(output: Any) -> str:
    """Extract the reply text from a provider output, whatever its shape.

    A completed chat call returns text, or a mapping with a text-like field; a
    replayed or empty output falls back to its string form (which the default parser
    reads as an unreadable reply, so the seat falls back).
    """
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        mapping = cast("dict[str, Any]", output)
        for key in ("text", "reply", "content", "message"):
            value = mapping.get(key)
            if isinstance(value, str):
                return value
    return str(cast("object", output))


__all__ = [
    "LOCAL_NO_KEY",
    "AgentIds",
    "ControllerDecodeMiss",
    "LLMController",
    "compile_agent",
    "timeout_fallback",
]
