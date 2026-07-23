"""Local seat controllers supply a seat's action in place of a websocket.

These tests drive ``mug.game.controllers`` with fake decision functions and fake
inference, with no ONNX runtime and no socket. They prove the seat seam: a
heuristic defers to a study function, an ONNX policy selects by its declared mode
(argmax, or a temperature sample), the registry resolves a binding to a local
controller and refuses one it cannot drive, the binder keys controllers by seat,
and a controller drives the real stepping loop exactly as a person would.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from mug.casting import (
    AgentActorSpec,
    CastDeclaration,
    ControllerBinding,
    OnnxPolicy,
    SeatAgentBinding,
)
from mug.casting.types import HumanActorSpec, OnnxPreprocessing
from mug.game.controllers import (
    ControllerRegistry,
    ControllerUnavailable,
    HeuristicController,
    OnnxController,
    agent_seats,
    bind_seat_controllers,
)
from mug.game.env import EnvFactory, GymEnv, StepResult
from mug.game.runtime import RenderPacket, run_episode
from mug.game.surface import Surface

_UUID = "019b6000-0000-7000-8000-{:012x}"
_ACTOR = "actor_" + _UUID.format(1)
_HUMAN_ACTOR = "actor_" + _UUID.format(2)
_REF = "agentver_" + _UUID.format(3)
_BINDING = "controller_" + _UUID.format(4)
_SEATBIND = "seatbind_" + _UUID.format(5)
_INTERACTION = "interaction_" + _UUID.format(6)
_EPISODE = "episode_" + _UUID.format(7)


def _onnx(mode: str, *, temperature: float | None = None) -> OnnxPolicy:
    return OnnxPolicy(
        policy_ref="cartpole@v1",
        preprocessing=OnnxPreprocessing(transform="identity"),
        selection_mode=cast("Any", mode),
        temperature=temperature,
    )


def _binding(kind: str, *, capability: str = "game-action") -> ControllerBinding:
    return ControllerBinding(
        binding_id=cast("Any", _BINDING),
        actor_id=cast("Any", _ACTOR),
        channel_key="game",
        capability=cast("Any", capability),
        controller_kind=cast("Any", kind),
        controller_ref=cast("Any", None if kind == "human-input" else _REF),
    )


def _seat_binding(actor_id: str, seat_key: str) -> SeatAgentBinding:
    return SeatAgentBinding(
        seat_agent_binding_id=cast("Any", _SEATBIND),
        interaction_id=cast("Any", _INTERACTION),
        actor_id=cast("Any", actor_id),
        seat_key=seat_key,
        env_agent_id="agent-0",
    )


def test_a_heuristic_controller_defers_to_the_study_function() -> None:
    """The heuristic returns whatever the injected decision function chooses."""
    controller = HeuristicController(lambda observation: int(observation[0]) % 2)
    assert controller.decide([4.0]) == 0
    assert controller.decide([3.0]) == 1


def test_an_argmax_policy_selects_the_greatest_score() -> None:
    """An argmax ONNX policy returns the index of the greatest inference score."""
    controller = OnnxController(_onnx("argmax"), lambda _: [0.1, 0.9, 0.3])
    assert controller.decide([0.0]) == 1


def test_a_sampling_policy_draws_from_the_softmax() -> None:
    """A sampling policy maps a random draw through the softmax to an action.

    With a low temperature the softmax concentrates on the greatest score, so it
    owns almost the whole unit interval: a mid draw lands on that action, while a
    draw at the very top falls through to the last action, and a draw at the very
    bottom lands on the first.
    """
    scores = [0.0, 2.0, 0.0]

    def _at(draw: float) -> int:
        policy = _onnx("sample", temperature=0.5)
        return OnnxController(policy, lambda _: scores, draw=lambda: draw).decide([0.0])

    assert _at(0.5) == 1  # the concentrated argmax owns the middle of the interval
    assert _at(0.999999) == 2
    assert _at(0.0) == 0


def test_a_sampling_policy_needs_a_random_draw() -> None:
    """A sampling policy without a draw source is refused at construction."""
    with pytest.raises(ControllerUnavailable):
        OnnxController(_onnx("sample", temperature=1.0), lambda _: [1.0])


def test_an_empty_score_vector_is_refused() -> None:
    """A policy that produces no scores cannot select an action."""
    controller = OnnxController(_onnx("argmax"), lambda _: [])
    with pytest.raises(ControllerUnavailable):
        controller.decide([0.0])


def test_the_registry_resolves_a_local_binding() -> None:
    """A scripted-policy binding resolves to its registered controller."""
    controller = HeuristicController(lambda _: 0)
    registry = ControllerRegistry({_REF: controller})
    assert registry.resolve(_binding("scripted-policy")) is controller


def test_the_registry_refuses_a_human_binding() -> None:
    """A human-input binding has no controller; the registry refuses it."""
    registry = ControllerRegistry({})
    with pytest.raises(ControllerUnavailable):
        registry.resolve(_binding("human-input"))


def test_the_registry_refuses_a_binding_that_needs_the_scheduler() -> None:
    """An llm binding needs a model provider and the scheduler; it is refused."""
    registry = ControllerRegistry({_REF: HeuristicController(lambda _: 0)})
    with pytest.raises(ControllerUnavailable):
        registry.resolve(_binding("llm", capability="action-plan"))


def test_the_registry_refuses_an_unregistered_reference() -> None:
    """A binding whose controller reference is unknown is refused."""
    registry = ControllerRegistry({})
    with pytest.raises(ControllerUnavailable):
        registry.resolve(_binding("rl-model"))


def test_the_binder_keys_controllers_by_seat() -> None:
    """The binder joins each software binding to its seat and skips the human."""
    controller = HeuristicController(lambda _: 0)
    registry = ControllerRegistry({_REF: controller})
    resolved = bind_seat_controllers(
        bindings=[_binding("scripted-policy"), _binding("human-input")],
        seat_bindings=[_seat_binding(_ACTOR, "left")],
        registry=registry,
    )
    assert resolved == {"left": controller}


def test_the_binder_refuses_a_binding_with_no_seat() -> None:
    """A software binding whose actor has no seat cannot be placed."""
    registry = ControllerRegistry({_REF: HeuristicController(lambda _: 0)})
    with pytest.raises(ControllerUnavailable):
        bind_seat_controllers(
            bindings=[_binding("scripted-policy")],
            seat_bindings=[],
            registry=registry,
        )


def test_agent_seats_names_the_software_seats_only() -> None:
    """A cast's agent slots are software seats; a human slot is not."""
    cast_decl = CastDeclaration(
        activity_key="round",
        seats=["bot", "person"],
        cast={
            "bot": AgentActorSpec(kind="agent", agent_ref="bot@v1"),
            "person": HumanActorSpec(kind="human"),
        },
    )
    assert agent_seats(cast_decl) == {"bot"}


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


async def test_a_controller_drives_the_stepping_loop() -> None:
    """A heuristic controller supplies the seat action each frame of an episode.

    The loop reads the controller through the same seam a person's input uses, so
    the actions the environment sees are exactly the controller's decisions over
    the observations the loop presents.
    """
    env_instance = _RecordingEnv()
    controller = HeuristicController(lambda observation: int(observation[0]))
    frames: list[RenderPacket] = []

    async def sink(packet: RenderPacket) -> None:
        frames.append(packet)

    summary = await run_episode(
        GymEnv(cast("EnvFactory", lambda: env_instance)),
        render=_render,
        channel_key="game",
        episode_id=_EPISODE,
        interaction_id=_INTERACTION,
        seat_key="left",
        input_state=controller,
        sink=sink,
        now=lambda: "2026-07-22T00:00:00.000000Z",
        fps=0,
        max_steps=10,
    )

    # The observation before each step is the prior step count, so the recorded
    # actions are the controller's decision over 0, 1, 2 -- and the env ends at 3.
    assert env_instance.actions == [0, 1, 2]
    assert summary.solved is True
    assert summary.frames == 3
