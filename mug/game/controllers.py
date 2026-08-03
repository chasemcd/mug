"""Local seat controllers: let a bot, not a websocket, supply a seat's action.

The API-05 casting family owns the records that declare who drives a seat -- the
``ControllerBinding``, the ``SeatAgentBinding`` that joins an environment agent to
an actor, the ``AgentActorSpec`` cast slot, and the ``OnnxPolicy`` inference
declaration -- but adds no runtime. This module is the runtime for the *local*
controllers, the ones that decide without a model provider or the scheduler: a
heuristic that defers to a study function, and a typed ONNX policy.

A controller satisfies the game loop's ``SeatActionSource`` seam: it decides one
discrete action from the current observation. So the server-authoritative loop
drives a bot exactly as it drives a person; only the source of the action differs.

Every controller here takes ``decide_every``, the frame skip: how many frames pass
between one decision and the next. A partner that decides thirty times a second
changes its mind faster than a person can read it, so a study says how often its
partner acts, and ``between`` says what the seat does on the frames in between
(see ``Pace``, which says why that second answer is a study's to make).

The core stays environment-agnostic. The decision function of a heuristic and the
observation-to-scores inference of an ONNX policy are both study- and environment-
specific, so the study injects them; this module owns only the seat seam, the
registry that resolves a binding to its controller, and the typed action selection
(argmax, or a temperature sample) that the ``OnnxPolicy`` record declares. A
controller kind that needs a model provider and the scheduler (an ``llm``) is not
a local controller; the registry refuses it until P3b/P3c land it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from mug.casting import (
    AgentActorSpec,
    CastDeclaration,
    ControllerBinding,
    OnnxPolicy,
    SeatAgentBinding,
)
from mug.game.runtime import SeatActionSource
from mug.game.seams import SeatView

Observation = Any
Policy = Callable[[Observation], int]
Infer = Callable[[Observation], Sequence[float]]
Draw = Callable[[], float]

# The controller kinds this module drives without the scheduler (RP-5).
_LOCAL_KINDS = frozenset({"scripted-policy", "rl-model"})


class ControllerUnavailable(Exception):
    """A binding could not be resolved to a local seat controller.

    The binding names a human seat (a websocket drives it), a controller kind that
    needs the scheduler and a model provider, or a reference no controller is
    registered for. The caller cannot supply the seat's action from this module.
    """


class Pace:
    """How often a seat decides, and what it does on the frames between.

    A game runs at its own speed, and a partner that decides on every one of thirty
    frames a second twitches: it changes its mind faster than a person can see it
    move, and it looks less like a teammate than like interference. So a seat
    decides every ``every`` frames. This is the frame skip a study sets; ``every=1``
    decides on every frame, which is what a seat does unless the study says
    otherwise. The first frame always decides, so a seat never opens a run on an
    action it did not choose.

    **What it does between decisions is a study's choice, and it changes the
    policy.** Two answers are right for different games:

    - ``between=None`` **holds** the decision. A seat steering something that keeps
      moving -- a slime that must keep pressing left -- wants this, because letting
      go is itself a decision.
    - ``between=<action>`` does that action instead, which is nearly always the
      game's own idle action. A seat on a grid wants this: repeating one step of a
      walk five times walks five squares, so a partner asked to step towards a pot
      arrives somewhere past it.

    A policy trained to act once per environment step is a policy that meets the
    second case: pacing it any other way plays a different policy from the one that
    was trained, and it will not look broken -- it will look bad.

    The count is the seat's own, not the loop's. A controller is asked once per
    frame for the seat it drives, so counting the asks counts the frames -- and a
    seat that joins late is paced from where it joined rather than from a frame
    number it was not there for.
    """

    def __init__(self, every: int = 1, between: int | None = None) -> None:
        if every < 1:
            raise ValueError("a seat decides at least once every frame")
        self._every = int(every)
        self._between = between
        self._asked = 0
        self._held = 0

    def due(self) -> bool:
        """Return whether this frame is one the seat decides on."""
        due = self._asked % self._every == 0
        self._asked += 1
        return due

    def hold(self, action: int) -> int:
        """Keep one decided action, and give it back."""
        self._held = int(action)
        return self._held

    def between(self) -> int:
        """Return what the seat does on a frame it did not decide on."""
        return self._held if self._between is None else int(self._between)


class HeuristicController:
    """A seat controller that defers to a study-supplied decision function.

    The policy maps an observation to a discrete action. The function is study- and
    environment-specific, so it lives in the study, never in the core; this
    controller only adapts it to the seat seam.

    ``decide_every`` is the frame skip: the policy is asked every that many frames.
    ``between`` is what the seat does on the frames it does not decide on -- the
    game's idle action, or the held decision when it is not named. See ``Pace``,
    which says why the two answers suit different games.

    ``sees`` is what the policy is shown, when an observation is not enough. A
    heuristic that plans a route reads the grid, the pots, and where the other player
    is standing, and none of that is in an observation. With one, the loop calls
    ``sees(env, agent_id)`` on the live environment and hands the policy that instead
    (``mug.game.seams.SeatView``).
    """

    def __init__(
        self,
        policy: Policy,
        *,
        decide_every: int = 1,
        between: int | None = None,
        sees: SeatView | None = None,
    ) -> None:
        self._policy = policy
        self._pace = Pace(decide_every, between)
        self.sees = sees

    def decide(self, observation: object) -> int:
        """Return the action the policy chooses, or what it does between."""
        if not self._pace.due():
            return self._pace.between()
        return self._pace.hold(int(self._policy(observation)))


class OnnxController:
    """A seat controller that runs a typed ONNX inference policy (API-05).

    The controller owns the typed action selection the ``OnnxPolicy`` record
    declares: an argmax over the scores, or a temperature sample drawn from a
    study-supplied random source. The observation-to-scores inference -- the ONNX
    session and the declared preprocessing, both environment-specific -- is the
    injected ``infer`` callable, so this module imports no ONNX runtime and holds
    no environment detail. The study's ``infer`` honors the policy's declared
    preprocessing; the controller honors its declared selection.
    """

    def __init__(
        self,
        policy: OnnxPolicy,
        infer: Infer,
        *,
        draw: Draw | None = None,
        decide_every: int = 1,
        between: int | None = None,
        sees: SeatView | None = None,
    ) -> None:
        if policy.selection_mode == "sample" and draw is None:
            raise ControllerUnavailable("a sampling policy needs a random draw")
        self._policy = policy
        self._infer = infer
        self._draw = draw
        self._pace = Pace(decide_every, between)
        self.sees = sees

    def decide(self, observation: object) -> int:
        """Score the observation, then select an action by the policy's mode.

        ``decide_every`` paces the inference as well as the action: a network that
        is asked every fifth frame runs a fifth as often, which is what makes a
        heavy exported policy affordable in a live game. A network trained to act
        once per environment step should name ``between``, because holding its last
        action is a different policy from the one that was trained.
        """
        if not self._pace.due():
            return self._pace.between()
        return self._pace.hold(self._selected(observation))

    def _selected(self, observation: object) -> int:
        """Return the action this policy's declared selection makes of the scores."""
        scores = list(self._infer(observation))
        if not scores:
            raise ControllerUnavailable("the policy produced no action scores")
        if self._policy.selection_mode == "argmax":
            return _argmax(scores)
        draw = self._draw
        if draw is None:  # pragma: no cover - guarded in __init__
            raise ControllerUnavailable("a sampling policy needs a random draw")
        return _sample(scores, self._policy.temperature or 1.0, draw())


class ScheduledSeat:
    """A seat whose choice a scheduler sets asynchronously, sampled each frame.

    This is the bridge from the asynchronous scheduler (API-12, P3c) to the
    synchronous game loop. A person's input holds the latest keypress and the loop
    samples it each frame; a scheduled seat holds the latest decision the same way,
    so a slow model never blocks a fast frame. The scheduler decides off the frame
    clock and calls ``apply``; the loop reads the seat through the
    ``SeatActionSource`` seam.

    **What the seat holds is a choice, and a choice need not be an action.** An
    agent that answers in seconds cannot usefully choose one frame of movement, so
    it may decide something that lasts -- a job, a destination -- and ``carry_out``
    is then what that looks like on any one frame. With no ``carry_out`` the choice
    **is** the action and the seat holds it, which is what every scheduled seat did
    before a coarser grain was possible.

    Before the first decision the seat has chosen nothing, which is not the same as
    having chosen the idle action: ``carry_out`` is told ``None`` and may act on
    that. With no ``carry_out`` a seat that has chosen nothing supplies the default
    action.

    The seat imports nothing from the scheduler -- the scheduler updates it through
    the duck-typed ``apply`` call -- so it stays below the scheduler in the layer
    graph, beside the other local controllers.
    """

    def __init__(
        self,
        *,
        default_action: int = 0,
        carry_out: Callable[[int | None], int | None] | None = None,
    ) -> None:
        self._default = int(default_action)
        self._carry_out = carry_out
        self._chosen: int | None = None

    def apply(self, action: int | None) -> None:
        """Set what the seat has chosen, until the next decision chooses again.

        ``None`` un-chooses: it is what a decision that fell back leaves behind, and
        it is different from choosing the idle action. A seat carrying out a job
        that is told a decision failed has been told nothing, not told to stop.
        """
        self._chosen = None if action is None else int(action)

    def current(self) -> int:
        """Return the choice the seat holds now (the scheduler's ``last_action``).

        It is the **choice** and not the action, because that is what a repeat-last
        fallback repeats: repeating the frame of movement a job happened to need is
        not repeating the job.
        """
        return self._default if self._chosen is None else self._chosen

    def decide(self, observation: object) -> int:
        """Return this frame's action, ignoring the observation as a person's does."""
        if self._carry_out is None:
            return self._default if self._chosen is None else self._chosen
        acted = self._carry_out(self._chosen)
        return self._default if acted is None else int(acted)


class ControllerRegistry:
    """Resolve the local seat controller a ``ControllerBinding`` names.

    The registry holds one controller per pinned controller reference (an agent
    version id). It resolves a non-human binding to its controller, and refuses a
    binding it cannot drive locally: a human-input binding, a controller kind that
    needs the scheduler, or a reference no controller is registered for.
    """

    def __init__(self, controllers: dict[str, SeatActionSource]) -> None:
        self._controllers = dict(controllers)

    def resolve(self, binding: ControllerBinding) -> SeatActionSource:
        """Return the controller that drives one binding, or refuse the binding."""
        if binding.controller_kind == "human-input":
            raise ControllerUnavailable("a human-input binding has no controller")
        if binding.controller_kind not in _LOCAL_KINDS:
            raise ControllerUnavailable(
                f"a {binding.controller_kind} binding needs the scheduler"
            )
        ref = binding.controller_ref
        if ref is None or ref not in self._controllers:
            raise ControllerUnavailable(f"no controller registered for {ref}")
        return self._controllers[ref]


def agent_seats(cast: CastDeclaration) -> set[str]:
    """Return the seats a cast fills with a pinned agent, not a human.

    A software seat needs a controller; a human seat is driven by its websocket. A
    between-subject treatment slot is not resolved here: the assigned level fixes
    the seat only once a participant is enrolled (API-06), so it is left out.
    """
    return {
        seat for seat, slot in cast.cast.items() if isinstance(slot, AgentActorSpec)
    }


def bind_seat_controllers(
    *,
    bindings: Iterable[ControllerBinding],
    seat_bindings: Iterable[SeatAgentBinding],
    registry: ControllerRegistry,
) -> dict[str, SeatActionSource]:
    """Resolve, per software seat, the controller that supplies its action.

    The join is by actor: each non-human ``ControllerBinding`` names an actor, and
    a ``SeatAgentBinding`` maps that actor to its seat, so the result is keyed by
    seat so the game loop reads it. A human-input binding is skipped -- its
    websocket drives the seat. A binding whose actor has no seat, or that the
    registry cannot resolve, raises ``ControllerUnavailable``.
    """
    seat_of = {binding.actor_id: binding.seat_key for binding in seat_bindings}
    resolved: dict[str, SeatActionSource] = {}
    for binding in bindings:
        if binding.controller_kind == "human-input":
            continue
        seat_key = seat_of.get(binding.actor_id)
        if seat_key is None:
            raise ControllerUnavailable(f"no seat is bound to actor {binding.actor_id}")
        resolved[seat_key] = registry.resolve(binding)
    return resolved


def _argmax(scores: Sequence[float]) -> int:
    """Return the index of the greatest score (the first on a tie)."""
    best = 0
    for index, value in enumerate(scores):
        if value > scores[best]:
            best = index
    return best


def _sample(scores: Sequence[float], temperature: float, draw: float) -> int:
    """Return an index sampled from the softmax of the scores at a temperature."""
    weights = _softmax(scores, temperature)
    cumulative = 0.0
    for index, weight in enumerate(weights):
        cumulative += weight
        if draw < cumulative:
            return index
    return len(weights) - 1


def _softmax(scores: Sequence[float], temperature: float) -> list[float]:
    """Return the softmax of the scores, scaled by the temperature."""
    scaled = [value / temperature for value in scores]
    peak = max(scaled)
    exponentials = [math.exp(value - peak) for value in scaled]
    total = sum(exponentials)
    return [value / total for value in exponentials]


__all__ = [
    "ControllerRegistry",
    "ControllerUnavailable",
    "HeuristicController",
    "OnnxController",
    "Pace",
    "ScheduledSeat",
    "SeatActionSource",
    "agent_seats",
    "bind_seat_controllers",
]
