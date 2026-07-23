"""The LLM agent facade drives an author's ``LLMAgent`` through the built stack.

These tests drive ``mug.agents`` against the in-memory store with a fixed clock, a
capturing fake adapter, and hand-built command contexts. They prove the facade an
author sees: a definition compiles to a frozen agent version, a reply is read into
an action, the model's own thoughts carry across steps, the chat and the history are
visible in the prompt the author builds, and the whole thing decides through the
built scheduler -- producing an action, or falling back when the reply is unreadable.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import ClassVar

import pytest

from mug.agents import LOCAL_NO_KEY, AgentIds, LLMController, compile_agent
from mug.agents.adapters import HttpRequest, HttpResponse, OllamaAdapter
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
from mug.kernel import Digest, Duration
from mug.providers import ModelCall, ModelCompletion, ModelProvider, Usage
from mug.runtime import CommandContext
from mug.scheduling import DecisionRequest, FallbackRule, Scheduler
from mug.scheduling.runtime import DecisionContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)

_IDS = AgentIds(
    agent_version_id="agentver_" + _UUID.format(0x430),
    agent_definition_id="agentdef_" + _UUID.format(0x431),
    agent_key="cooking-partner",
    version_number=1,
    prompt_version_id="promptver_" + _UUID.format(0x440),
    fallback_policy_key="cooking-fallback",
)


class _Env:
    """A fake environment: named actions, a text view, and a hashable state."""

    ACTIONS: ClassVar[list[str]] = ["UP", "DOWN", "LEFT", "RIGHT", "INTERACT", "WAIT"]

    def __init__(self) -> None:
        self.tick = 0

    def legal_actions(self, agent_id: str) -> list[str]:
        return list(self.ACTIONS)

    def text_view(self, agent_id: str) -> str:
        return f"tick {self.tick}; you are {agent_id}"

    def get_state(self) -> dict[str, int]:
        return {"tick": self.tick}


class CookingPartner(LLMAgent):
    """An author's agent: it shows the plan, partner moves, chat, and the game."""

    provider = Provider.ANTHROPIC
    model = "claude-sonnet-4-5"
    secret = "chat-provider-key"
    decides_every = 4
    on_timeout = Fallback.REPEAT_LAST

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Chat,
        thoughts: Thoughts,
    ) -> str:
        partner = ", ".join(step.action_of("chef-1") or "-" for step in history.last(3))
        said = "; ".join(m.text for m in chat.last(3))
        return (
            f"plan: {thoughts.latest or 'none'}\n"
            f"partner moves: {partner}\n"
            f"chat: {said}\n"
            f"{env.text_view(agent_id)}\n"  # type: ignore[attr-defined]
            f"actions: {', '.join(self.available_actions(env, agent_id))}"
        )


class _Adapter:
    """A fake provider adapter: it records each call and returns scripted replies."""

    def __init__(self, replies: list[str]) -> None:
        self.seen: list[ModelCall] = []
        self._replies = replies
        self._i = 0

    async def __call__(self, call: ModelCall) -> ModelCompletion:
        self.seen.append(call)
        reply = self._replies[min(self._i, len(self._replies) - 1)]
        self._i += 1
        return ModelCompletion(
            outcome="completed",
            resolved_model="fake",
            usage=Usage(input_tokens=1, output_tokens=1, cost_micros=1),
            output={"text": reply},
        )

    def prompt(self, index: int = 0) -> str:
        payload = self.seen[index].payload
        return payload["messages"][0]["content"]


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


def _provider(store: InMemoryStore, adapter: object) -> ModelProvider:
    gens = itertools.count(1)
    return ModelProvider(
        store=store,
        adapter=adapter,  # type: ignore[arg-type]
        now=lambda: _START,
        new_generation_id=lambda: "generation_" + _UUID.format(next(gens)),
    )


def _controller(
    store: InMemoryStore, factory: _Factory, env: _Env, adapter: object
) -> LLMController:
    agent = CookingPartner()
    return LLMController(
        agent=agent,
        agent_version=compile_agent(agent, ids=_IDS),
        provider=_provider(store, adapter),
        env=env,
        agent_id="chef-2",
        new_context=factory,
        resolve_secret=lambda _: "sk-secret",
    )


def _request(seed: int) -> DecisionRequest:
    return DecisionRequest(
        decision_id="decision_" + _UUID.format(seed),
        actor_id="actor_" + _UUID.format(0x411),
        channel_key="game",
        execution_mode="server",
        episode_generation=1,
        source_observation_digest=_DIGEST,
        deadline="2026-07-22T00:00:01.000000Z",
        validity_window=Duration(microseconds=500000),
        submitted_at="2026-07-22T00:00:00.000000Z",
    )


def _ctx(seed: int, env: _Env) -> DecisionContext:
    return DecisionContext(request=_request(seed), observation=env.get_state())


class LocalRunner(LLMAgent):
    """A keyless agent: a local Ollama runner that names no credential."""

    provider = Provider.OLLAMA
    model = "llama3"
    # no `secret`: a local runner needs none

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Chat,
        thoughts: Thoughts,
    ) -> str:
        return (
            f"{env.text_view(agent_id)}\n"  # type: ignore[attr-defined]
            f"actions: {', '.join(self.available_actions(env, agent_id))}"
        )


def test_compile_agent_pins_the_definition() -> None:
    """An author's definition compiles to a frozen agent version by its config."""
    version = compile_agent(CookingPartner(), ids=_IDS)
    assert version.provider == "anthropic"
    assert version.model_selector == "claude-sonnet-4-5"
    assert version.secret_name == "chat-provider-key"
    assert version.agent_version_id == _IDS.agent_version_id
    assert version.parameters_digest.algorithm == "sha-256"


def test_compile_agent_defaults_a_keyless_local_secret() -> None:
    """A keyless local agent compiles: the build names the no-op credential."""
    version = compile_agent(LocalRunner(), ids=_IDS)
    assert version.provider == "oss"
    assert version.secret_name == LOCAL_NO_KEY


def test_compile_agent_requires_a_secret_for_a_hosted_provider() -> None:
    """A hosted provider with no secret is refused with a clear message."""

    class _HostedNoKey(LLMAgent):
        provider = Provider.ANTHROPIC
        model = "claude-sonnet-4-5"

        def get_prompt(
            self,
            env: object,
            agent_id: str,
            history: History,
            chat: Chat,
            thoughts: Thoughts,
        ) -> str:
            return "decide"

    with pytest.raises(ValueError, match="needs a credential"):
        compile_agent(_HostedNoKey(), ids=_IDS)


async def test_a_keyless_agent_decides_with_no_resolver() -> None:
    """A local agent decides end to end through the Ollama adapter and no secret."""
    store, factory, env = InMemoryStore(), _Factory(), _Env()
    seen: list[str | None] = []

    async def transport(request: HttpRequest) -> HttpResponse:
        seen.append(request.headers.get("authorization"))
        return HttpResponse(
            status=200,
            body={
                "model": "llama3",
                "message": {"role": "assistant", "content": "Action: RIGHT"},
                "prompt_eval_count": 1,
                "eval_count": 1,
            },
        )

    agent = LocalRunner()
    controller = LLMController(
        agent=agent,
        agent_version=compile_agent(agent, ids=_IDS),
        provider=_provider(
            store,
            OllamaAdapter(base_url="http://localhost:11434", transport=transport),
        ),
        env=env,
        agent_id="chef-2",
        new_context=factory,
        # no resolve_secret: the keyless agent needs none
    )

    action = await controller.decide(_ctx(0xB01, env))

    assert action == _Env.ACTIONS.index("RIGHT")
    assert seen == [None]  # the local runner sends no auth header
    # The model call was recorded even though no credential was resolved.
    modelcall_id = "modelcall_" + _request(0xB01).decision_id.split("_", 1)[1]
    head = store.load_aggregate(modelcall_id)
    assert head is not None
    assert head["schema"]["name"] == "mug.api-13.provider-response"


async def test_the_controller_reads_a_reply_into_an_action() -> None:
    """The model reasons, ends with an action word, and the controller reads it."""
    store, factory, env = InMemoryStore(), _Factory(), _Env()
    adapter = _Adapter(["I will grab the onion. Action: RIGHT"])
    controller = _controller(store, factory, env, adapter)

    action = await controller.decide(_ctx(0xB01, env))

    assert action == _Env.ACTIONS.index("RIGHT")


async def test_thoughts_carry_forward_across_steps() -> None:
    """The model's own reply is carried into the next step's prompt."""
    store, factory, env = InMemoryStore(), _Factory(), _Env()
    adapter = _Adapter(
        ["Cover the left. Action: LEFT", "Now the pot. Action: INTERACT"]
    )
    controller = _controller(store, factory, env, adapter)

    await controller.decide(_ctx(0xB01, env))
    await controller.decide(_ctx(0xB02, env))

    assert len(controller.thoughts) == 2
    # The second prompt shows the first reply as the plan so far.
    assert "Cover the left. Action: LEFT" in adapter.prompt(1)


async def test_the_chat_is_visible_in_the_prompt() -> None:
    """A human partner's chat instruction reaches the model's prompt."""
    store, factory, env = InMemoryStore(), _Factory(), _Env()
    adapter = _Adapter(["Action: WAIT"])
    controller = _controller(store, factory, env, adapter)
    controller.record_message(Message(sender="chef-1", text="cover the left side"))

    await controller.decide(_ctx(0xB01, env))

    assert "cover the left side" in adapter.prompt(0)


async def test_the_history_is_visible_in_the_prompt() -> None:
    """A past partner move reaches the model's prompt through history."""
    store, factory, env = InMemoryStore(), _Factory(), _Env()
    adapter = _Adapter(["Action: WAIT"])
    controller = _controller(store, factory, env, adapter)
    controller.record_step(Step(tick=1, actions={"chef-1": "UP"}))

    await controller.decide(_ctx(0xB01, env))

    assert "partner moves: UP" in adapter.prompt(0)


def _scheduler(store: InMemoryStore) -> Scheduler:
    return Scheduler(
        store=store,
        now=lambda: _START,
        fallback=FallbackRule(on_timeout="repeat-last", on_stale="repeat-last"),
        default_action=0,
    )


async def test_the_controller_decides_through_the_scheduler() -> None:
    """The scheduler awaits the controller and records a produced decision."""
    store, factory, env = InMemoryStore(), _Factory(), _Env()
    adapter = _Adapter(["Let me help. Action: INTERACT"])
    controller = _controller(store, factory, env, adapter)
    request = _request(0xB01)

    outcome = await _scheduler(store).decide(
        request=request,
        observation=env.get_state(),
        controller=controller.decide,
        new_context=factory,
    )

    assert outcome.result.outcome == "produced"
    assert outcome.action == _Env.ACTIONS.index("INTERACT")
    # Both the decision and the model call are recorded on their own streams.
    decision_head = store.load_aggregate(request.decision_id)
    assert decision_head is not None
    assert decision_head["schema"]["name"] == "mug.api-12.decision-result"
    modelcall_id = "modelcall_" + request.decision_id.split("_", 1)[1]
    call_head = store.load_aggregate(modelcall_id)
    assert call_head is not None
    assert call_head["schema"]["name"] == "mug.api-13.provider-response"


async def test_an_unreadable_reply_falls_back_through_the_scheduler() -> None:
    """A reply with no legal action decodes to a miss, so the seat falls back."""
    store, factory, env = InMemoryStore(), _Factory(), _Env()
    adapter = _Adapter(["I am not sure what to do here."])
    controller = _controller(store, factory, env, adapter)

    outcome = await _scheduler(store).decide(
        request=_request(0xB01),
        observation=env.get_state(),
        controller=controller.decide,
        new_context=factory,
        last_action=2,
    )

    assert outcome.result.outcome == "failed"
    assert outcome.used_fallback is True
    assert outcome.action == 2  # repeat-last reused the last applied action
