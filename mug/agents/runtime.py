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

import time
from dataclasses import dataclass
from typing import Any, cast

from mug.authoring import (
    Fallback,
    History,
    LLMAgent,
    Message,
    Provider,
    Step,
    Thoughts,
    Transcript,
)
from mug.diagnostics import Diagnostics, NullDiagnostics
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

# What a warm-up asks. It is deliberately not the study's own prompt: building that
# means reading the environment, and the environment a round is about to be played on
# must not be read or reset by anything but the round. Short, so the reply is short.
_WARM_UP = "Reply with the single word READY."

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
        chat: Transcript | None = None,
        thoughts: Thoughts | None = None,
        diagnostics: Diagnostics | None = None,
        seat_key: str = "",
    ) -> None:
        self._agent = agent
        self._agent_version = agent_version
        self._provider = provider
        self._env = env
        self._agent_id = agent_id
        self._new_context = new_context
        self._resolve_secret = resolve_secret
        self.history = history if history is not None else History()
        self.chat = chat if chat is not None else Transcript()
        self.thoughts = thoughts if thoughts is not None else Thoughts()
        # Every model call this seat makes, in call order, so the episode runner can
        # hand them to ``build_decision_tape`` at the end for a replay bundle.
        self.results: list[ModelCallResult] = []
        # What this seat said on its last decision, waiting to be published. It is
        # held here rather than returned, because the scheduler decides *actions*:
        # a deadline and a fallback are about what a seat does, not what it says.
        self.pending_message: str | None = None
        # What this seat says about itself while it runs, for a person watching. The
        # provider writes down the call and the reply, because every model call in
        # the platform goes through it; this writes down what only a seat knows --
        # whether an action could be read out of a reply, and what it chose to say.
        self.diagnostics: Diagnostics = diagnostics or NullDiagnostics()
        # What a note about this seat is labelled with, and what a reader joins it
        # to. The label is the **author's own name** for the agent, because it is
        # the only one of the three a person chose: an environment numbers its
        # agents, and the seat key follows the environment, so a table of model
        # seats reads "agent.action 1" and says nothing at all. The seat key and
        # the agent id are carried as fields, where the records name them.
        self.seat_key = seat_key or agent_id
        self.label = agent_version.agent_key or self.seat_key

    async def decide(self, ctx: DecisionContext) -> int:
        """Build the prompt, call the model, and return the parsed action.

        The reply's carried thought (from ``reflect``) is appended before the action
        is read, so the model builds on its own reasoning next step. An unreadable
        reply raises ``ControllerDecodeMiss`` so the scheduler applies the fallback.
        """
        modelcall_id = "modelcall_" + ctx.request.decision_id.split("_", 1)[1]
        reply = await self._ask(modelcall_id, why="decision")
        action = self._agent.parse_reply(reply, self._env, self._agent_id)
        if action is None:
            # The one failure that looks exactly like a partner standing still. It
            # is written down as its own thing, because "the model answered and
            # nobody could read it" and "the model never answered" are two faults
            # with two fixes, and a fallback action makes them look the same.
            self.diagnostics.note(
                "agent.unreadable",
                subject=self.label,
                modelcall_id=modelcall_id,
                reply=reply,
            )
            raise ControllerDecodeMiss(f"could not read an action from: {reply!r}")
        self.diagnostics.note(
            "agent.action",
            subject=self.label,
            modelcall_id=modelcall_id,
            action=int(action),
            action_name=self._named(int(action)),
        )
        return int(action)

    async def answer(self, modelcall_id: str) -> str | None:
        """Call the model for what it says alone, and return it.

        This is the seat between rounds. Nothing is stepping, so there is no action
        to read and no decision to record: what the model produces is words or it is
        silence, and either is a whole answer. The prompt, the carried thought and
        the recorded model call are the same as any other turn, because the seat is
        the same seat -- a partner that answered in a different voice while it was
        resting would not be the one they played with.

        A model that names an action and says nothing has said nothing. It is not
        an error and nothing is put on the screen for it.
        """
        await self._ask(modelcall_id, why="rest")
        return self.take_message()

    def _named(self, action: int) -> str:
        """Return the study's own name for one action, for a reader.

        The study is asked only when somebody is watching: naming an action means
        calling into the study's ``available_actions``, and a run nobody is reading
        must not pay for a label nobody sees.
        """
        if not self.diagnostics.watching:
            return ""
        try:
            names = self._agent.available_actions(self._env, self._agent_id)
        except Exception:
            return ""
        return names[action] if 0 <= action < len(names) else ""

    async def warm_up(self, modelcall_id: str, *, on: Any = None) -> bool:
        """Reach the model once before the game, and say whether it answered.

        Two things are wrong with finding out during the round. A provider that
        cannot be reached -- a runner nobody started, a model nobody pulled, a
        credential that has expired -- shows up as a partner that stands still,
        which is the one picture a participant cannot read; and a runner that has
        let the model out of memory reloads it on the first call, in front of
        somebody who is by then looking at a kitchen. A model is unloaded after
        minutes of quiet, and a participant spends minutes on the consent form.

        So the call is made **before** the round: a wait before a game starts is a
        wait somebody can read, and a partner frozen in a running kitchen is not.

        It goes through the whole real path -- this seat's provider, adapter,
        model and credential -- because a probe down a different path proves
        nothing about the one a decision takes.

        ``on`` is a **throwaway** environment, of the same kind the round will use
        and never the round's own. With one, the warm-up asks the study's real
        question rather than a stand-in, and that is where the time goes: a runner
        reuses its cached reading of the longest prefix a call shares with the last
        one, so a warm-up written in the study's own words leaves the fixed part of
        every later prompt already read. Measured on a local llama3.2, the first
        decision of a round went from reading 850 ms of prompt to reading 330 ms.
        A stand-in prompt shares nothing, so it warms the model and not the words.

        It also proves more: a ``get_prompt`` that raises on a fresh environment is
        an author's own bug, and this finds it before a participant does rather than
        as a partner that never moves.

        **It touches neither the round's environment nor the seat.** The environment
        it reads is one made to be thrown away, so nothing the round will play is
        read or reset. The reply is not reflected on and nothing is taken from it,
        so the seat's carried thought and the words it is holding are exactly what
        they were: a warm-up that primed the seat with an answer to a question the
        study never asked would be worse than no warm-up.
        """
        started = time.perf_counter()
        try:
            result = await self._provider.invoke(
                modelcall_id=modelcall_id,
                agent_version=self._agent_version,
                payload={"messages": [{"role": "user", "content": self._warm(on)}]},
                new_context=self._new_context,
                resolve_secret=(
                    self._resolve_secret if self._agent.secret is not None else None
                ),
                purpose="warm-up",
            )
        except Exception as raised:
            self.diagnostics.note(
                "agent.unreachable",
                subject=self.label,
                model=self._agent.model,
                provider=self._agent.provider.name,
                error=type(raised).__name__,
                message=str(raised),
            )
            return False
        answered = result.error is None
        self.diagnostics.note(
            "agent.warm" if answered else "agent.unreachable",
            subject=self.label,
            model=self._agent.model,
            provider=self._agent.provider.name,
            took_ms=int((time.perf_counter() - started) * 1000),
            error_class=None if result.error is None else result.error.error_class,
        )
        return answered

    def _warm(self, on: Any) -> str:
        """Return what to warm the model with: the study's question, or a stand-in.

        A study that cannot be asked its own question on a fresh environment still
        gets a warm-up, because the half that finds an unreachable provider does not
        need a prompt at all. What it loses is the cached reading, and it is told so.
        """
        if on is None:
            return _WARM_UP
        try:
            return self._agent.get_prompt(
                on, self._agent_id, History(), Transcript(), Thoughts()
            )
        except Exception as raised:
            self.diagnostics.note(
                "agent.warm_prompt_failed",
                subject=self.label,
                error=type(raised).__name__,
                message=str(raised),
            )
            return _WARM_UP

    async def _ask(self, modelcall_id: str, *, why: str = "decision") -> str:
        """Run one model call for this seat and take everything but the action.

        It is the whole of a turn except reading the action out, so a turn that has
        no action to read (a seat between rounds) is this and no more. The thought
        is carried and what the seat says is held, in that order.
        """
        # A turn opens the group a reader reads: everything between here and what the
        # seat says came from one ask. ``why`` is what tells a rest between rounds
        # apart from a decision inside one -- the two look identical in the ledger,
        # because a rest turn records no decision at all.
        self.diagnostics.note(
            "agent.turn",
            subject=self.label,
            modelcall_id=modelcall_id,
            why=why,
            agent_id=self._agent_id,
            seat_key=self.seat_key,
            model=self._agent.model,
            provider=self._agent.provider.name,
            decides_every=self._agent.decides_every,
            heard=len(self.chat),
            steps=len(self.history),
            thoughts=len(self.thoughts),
        )
        prompt = self._agent.get_prompt(
            self._env, self._agent_id, self.history, self.chat, self.thoughts
        )
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
            self.diagnostics.note(
                "agent.thought",
                subject=self.label,
                modelcall_id=modelcall_id,
                thought=thought,
            )
        # What the seat says is read out **before** the action, because an
        # unreadable action must not cost the participant a message the model
        # really produced. A reply that says "going left" and then names no action
        # anybody can read has still said it, and the seat falls back on the action
        # alone. The two are judged apart, which is what NS-07 asks for.
        self.pending_message = self._agent.say(reply, self._env, self._agent_id)
        # Silence is written down as loudly as speech. A seat that says nothing looks
        # from the outside exactly like a seat that was never asked, and the whole
        # reason to watch a rest between rounds is to tell the two apart.
        self.diagnostics.note(
            "agent.said" if self.pending_message else "agent.silent",
            subject=self.label,
            modelcall_id=modelcall_id,
            text=self.pending_message,
        )
        return reply

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
