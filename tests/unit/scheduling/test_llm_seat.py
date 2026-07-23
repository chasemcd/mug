"""An LLM seat, end to end: a model call becomes a scheduled action on a seat.

This test composes the two agent-stack families the way a study does. It builds an
async controller that renders an observation to a provider payload, calls the model
through ``mug.providers`` (a deterministic ``FakeProvider`` stands in for a vendor),
and parses the output to a discrete action. The scheduler awaits that controller
under a deadline and records the decision; the decided action is applied to a
``ScheduledSeat``, which the game loop then samples through the same seam a person's
input uses. It proves the whole hookup: model call and decision both recorded, the
seat holds the decided action, and the loop steps on it.

The composition (the ``llm_controller`` below) lives here, not in the core, because
``mug.scheduling`` and ``mug.providers`` are siblings in the layer graph: the study
wires them together above both.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from typing import Any

from mug.game.controllers import ScheduledSeat
from mug.game.env import GymEnv, StepResult
from mug.game.runtime import RenderPacket, run_episode
from mug.game.surface import Surface
from mug.kernel import Digest, Duration
from mug.providers import AgentVersion, FakeProvider, ModelProvider, SecretResolver
from mug.runtime import CommandContext
from mug.scheduling import DecisionRequest, FallbackRule, Scheduler
from mug.scheduling.runtime import AsyncController, DecisionContext, NewContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_START = datetime(2026, 7, 22, 0, 0, 0, tzinfo=timezone.utc)
_DEADLINE = "2026-07-22T00:00:01.000000Z"
_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)


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


def _agent() -> AgentVersion:
    return AgentVersion(
        agent_version_id="agentver_" + _UUID.format(0x430),
        agent_definition_id="agentdef_" + _UUID.format(0x431),
        agent_key="foraging-partner",
        version_number=1,
        provider="anthropic",
        model_selector="claude-sonnet-4-5",
        prompt_version_id="promptver_" + _UUID.format(0x440),
        parameters_digest=_DIGEST,
        tool_version_ids=[],
        fallback_policy_key="foraging-fallback",
        secret_name="chat-provider-key",
    )


def _request() -> DecisionRequest:
    return DecisionRequest(
        decision_id="decision_" + _UUID.format(0xB01),
        actor_id="actor_" + _UUID.format(0x411),
        channel_key="game",
        execution_mode="server",
        episode_generation=1,
        source_observation_digest=_DIGEST,
        deadline=_DEADLINE,
        validity_window=Duration(microseconds=500000),
        submitted_at="2026-07-22T00:00:00.000000Z",
    )


def _llm_controller(
    *,
    provider: ModelProvider,
    agent_version: AgentVersion,
    resolve_secret: SecretResolver,
    new_context: NewContext,
) -> AsyncController:
    """Compose a provider into the scheduler's async controller seam.

    This is the LLM hookup a study writes: render the observation to a provider
    payload, call the model, and parse the output to a discrete action. The render
    and parse are environment-specific, so the study owns them; the scheduler that
    awaits this controller never sees the provider behind it.
    """

    def render(observation: Any) -> dict[str, int]:
        return {"cell": int(observation[0])}

    def parse(output: Any) -> int:
        return int(output["action"])

    async def decide(ctx: DecisionContext) -> int:
        # Content-address the model call to the decision, so a retry coalesces.
        modelcall_id = "modelcall_" + ctx.request.decision_id.split("_", 1)[1]
        result = await provider.invoke(
            modelcall_id=modelcall_id,
            agent_version=agent_version,
            payload=render(ctx.observation),
            new_context=new_context,
            resolve_secret=resolve_secret,
        )
        assert result.output is not None
        return parse(result.output)

    return decide


class _RecordingEnv:
    """A fake environment: observation is the step count; it records actions."""

    def __init__(self) -> None:
        self._t = 0
        self.actions: list[int] = []

    def reset(self, *, seed: int | None = None) -> tuple[list[float], dict[str, Any]]:
        self._t = 0
        return [0.0], {}

    def step(
        self, action: int
    ) -> tuple[list[float], float, bool, bool, dict[str, Any]]:
        self.actions.append(action)
        self._t += 1
        return [float(self._t)], -1.0, self._t >= 3, False, {}


def _render(surface: Surface, state: StepResult) -> None:
    surface.circle(x=0.5, y=0.5, radius=0.02, color="#f00", object_id="dot")


async def test_an_llm_decision_drives_a_scheduled_seat() -> None:
    """A model call becomes a scheduled action the game loop reads off the seat."""
    store, factory = InMemoryStore(), _Factory()
    provider = ModelProvider(
        store=store,
        adapter=FakeProvider(lambda payload: {"action": payload["cell"] % 3}),
        now=lambda: _START,
        new_generation_id=lambda: "generation_" + _UUID.format(0xC10),
    )
    agent = _agent()
    controller = _llm_controller(
        provider=provider,
        agent_version=agent,
        resolve_secret=lambda _: "sk-secret",
        new_context=factory,
    )
    scheduler = Scheduler(
        store=store,
        now=lambda: _START,
        fallback=FallbackRule(on_timeout="repeat-last", on_stale="repeat-last"),
        default_action=0,
    )
    seat = ScheduledSeat(default_action=0)
    request = _request()

    outcome = await scheduler.decide(
        request=request,
        observation=[2.0],
        controller=controller,
        new_context=factory,
        last_action=seat.current(),
    )
    seat.apply(outcome.action)

    # The decision is produced and the seat holds the parsed model action (2 % 3).
    assert outcome.result.outcome == "produced"
    assert outcome.action == 2
    assert seat.current() == 2
    # Both the model call and the decision are recorded on their own streams.
    modelcall_id = "modelcall_" + request.decision_id.split("_", 1)[1]
    call_head = store.load_aggregate(modelcall_id)
    assert call_head is not None
    assert call_head["schema"]["name"] == "mug.api-13.provider-response"
    decision_head = store.load_aggregate(request.decision_id)
    assert decision_head is not None
    assert decision_head["schema"]["name"] == "mug.api-12.decision-result"


async def test_a_scheduled_seat_drives_the_stepping_loop() -> None:
    """The held-action seat satisfies the loop seam exactly as a person's input."""
    env_instance = _RecordingEnv()
    seat = ScheduledSeat(default_action=1)  # the scheduler would set this action
    frames: list[RenderPacket] = []

    async def sink(packet: RenderPacket) -> None:
        frames.append(packet)

    summary = await run_episode(
        GymEnv(lambda: env_instance),  # type: ignore[arg-type]
        render=_render,
        channel_key="game",
        episode_id="episode_" + _UUID.format(0x7),
        interaction_id="interaction_" + _UUID.format(0x6),
        seat_key="left",
        input_state=seat,
        sink=sink,
        now=lambda: "2026-07-22T00:00:00.000000Z",
        fps=0,
        max_steps=10,
    )

    # The seat supplies its held action every frame, so the env sees a constant 1.
    assert env_instance.actions == [1, 1, 1]
    assert summary.frames == 3
