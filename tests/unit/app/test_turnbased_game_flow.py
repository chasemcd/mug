"""A participant watches a turn-based (AEC) model episode over the transport.

This test drives the turn-based agent-game application. One participant plays the
flow to the game activity, where two model seats take turns over an AEC environment:
each turn the active seat decides, the loop steps the one move and pushes it to the
socket, and the run is captured and assembled into a replay bundle. The flow then
advances the participant to the debrief. So an AEC episode is reachable by a real
participant, not only a unit test.
"""

from __future__ import annotations

from typing import Any, ClassVar

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from mug.agents import AgentIds, AgentSeatSpec, TurnBasedGameSpec
from mug.app import build_demo_app
from mug.authoring import Chat, Fallback, History, LLMAgent, Provider, Thoughts
from mug.client import RealtimeCommand
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.replay import validate_replay_bundle
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_TURNS = 4
_UUID = "019b6000-0000-7000-8000-{:012x}"


class _DuelAec:
    """A two-seat turn-based AEC game: ``a`` and ``b`` alternate for ``turns`` moves.

    It duck-types the PettingZoo AEC API the ``AecEnv`` adapter reads and also
    answers the controller reads, so the loop steps it and each model reads the same
    live object.
    """

    ACTIONS: ClassVar[list[str]] = ["WAIT", "LEFT", "RIGHT"]

    def __init__(self, *, turns: int = _TURNS) -> None:
        self._turns = turns
        self._order = ("a", "b")
        self.agents: list[str] = []
        self.agent_selection = "a"
        self.rewards: dict[str, float] = {}
        self.terminations: dict[str, bool] = {}
        self.truncations: dict[str, bool] = {}
        self.moves: list[tuple[str, int]] = []

    def reset(self, *, seed: int | None = None) -> None:
        self.agents = list(self._order)
        self.agent_selection = "a"
        self.rewards = dict.fromkeys(self._order, 0.0)
        self.terminations = dict.fromkeys(self._order, False)
        self.truncations = dict.fromkeys(self._order, False)
        self.moves = []

    def observe(self, agent: str) -> list[float]:
        return [float(len(self.moves))]

    def step(self, action: int | None) -> None:
        agent = self.agent_selection
        if self.terminations[agent] or self.truncations[agent]:
            dead = self.agent_selection
            self.agents = [a for a in self.agents if a != dead]
            live = [a for a in self._order if a in self.agents]
            if live:
                self.agent_selection = live[0]
            return
        self.moves.append((agent, int(action or 0)))
        self.rewards = dict.fromkeys(self._order, 0.0)
        self.rewards[agent] = 1.0
        if len(self.moves) >= self._turns:
            self.terminations = dict.fromkeys(self.agents, True)
        index = self._order.index(agent)
        self.agent_selection = self._order[(index + 1) % len(self._order)]

    def legal_actions(self, agent_id: str) -> list[str]:
        return list(self.ACTIONS)

    def text_view(self, agent_id: str) -> str:
        return f"move {len(self.moves)}; you are {agent_id}"


class _Duelist(LLMAgent):
    """An author's agent that answers a fixed move each turn."""

    provider = Provider.OSS
    model = "fake-local"
    decides_every = 1
    on_timeout = Fallback.REPEAT_LAST

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Chat,
        thoughts: Thoughts,
    ) -> str:
        return f"{env.text_view(agent_id)}"  # type: ignore[attr-defined]


def _view(env: Any, agent_id: str) -> str:
    """Render one seat's game as text for its prompt (a study seam)."""
    return env.text_view(agent_id)


async def _adapter(call: ModelCall) -> ModelCompletion:
    return ModelCompletion(
        outcome="completed",
        resolved_model="fake-local",
        usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
        output={"text": "Action: RIGHT"},
    )


def _seat(agent_id: str, tag: int) -> AgentSeatSpec:
    return AgentSeatSpec(
        agent=_Duelist(),
        adapter=_adapter,
        ids=AgentIds(
            agent_version_id="agentver_" + _UUID.format(0x500 + tag),
            agent_definition_id="agentdef_" + _UUID.format(0x510 + tag),
            agent_key=f"duel-{agent_id}",
            version_number=1,
            prompt_version_id="promptver_" + _UUID.format(0x520 + tag),
            fallback_policy_key="duel-fallback",
        ),
        agent_id=agent_id,
        seat_key=f"seat-{agent_id}",
        actor_id="actor_" + _UUID.format(0x300 + tag),
        text_view=_view,
    )


def _spec() -> TurnBasedGameSpec:
    return TurnBasedGameSpec(
        channel_key="duel",
        make_env=_DuelAec,
        seats=(_seat("a", 0), _seat("b", 1)),
        decision_timeout=1.0,
        max_steps=_TURNS + 5,
    )


def _advance_frame(answers: dict[str, Any], tag: str) -> dict[str, Any]:
    command = RealtimeCommand(
        command_id=f"command_019b6000-0000-7000-8000-0000000000{tag}",
        channel_key="flow.advance",
        intent_schema=SchemaRef(name="mug.demo.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        idempotency_key="idem_" + tag.ljust(21, "0") + "A",
        submitted_at="2026-07-22T00:00:00.000000Z",
    )
    return {
        "type": "command",
        "command": command.model_dump(mode="json", exclude_none=True),
        "payload": {"answers": answers},
    }


def _drive_to_game(socket: WebSocketTestSession, tags: tuple[str, str]) -> None:
    assert socket.receive_json()["type"] == "handshake_ack"
    assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"
    socket.send_json(_advance_frame({"agree": "yes"}, tags[0]))
    assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
    assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
    assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"
    socket.send_json(_advance_frame({"mood": 4}, tags[1]))
    assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
    assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
    assert socket.receive_json()["delivery"]["kind"] == "game"


def _drain_frames(
    socket: WebSocketTestSession,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    message = socket.receive_json()
    while message.get("type") == "frame":
        frames.append(message)
        message = socket.receive_json()
    return frames, message


async def test_a_participant_watches_a_turnbased_run_captured_and_bundled() -> None:
    """The seats alternate over the socket; the run captures and bundles, valid."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), turnbased_game=_spec())
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_game(socket, ("01", "02"))
        frames, nxt = _drain_frames(socket)

        # One frame per played turn, and the movers alternate a, b, a, b.
        assert len(frames) == _TURNS
        assert [frame["mover"] for frame in frames] == ["a", "b", "a", "b"]
        assert nxt["delivery"]["kind"] == "content"

    bundle = app.state.replay_bundles[0]
    # One model call per turn folds into the decision tape.
    assert bundle.decision_tape is not None
    assert len(bundle.decision_tape.entries) == _TURNS
    verdict = await validate_replay_bundle(artifacts=store, manifest=bundle.manifest)
    assert verdict.valid is True
