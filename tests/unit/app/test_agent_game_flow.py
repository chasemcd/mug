"""A participant watches a multi-seat model episode over the realtime transport.

This test drives the whole agent-game application. One participant plays the flow to
the game activity, where a two-seat model episode runs on the server: each seat is
driven by a deterministic fake provider, the loop steps both seats, and every stepped
frame is pushed to the socket. The run is captured to the ledger and assembled into a
replay bundle, and the flow advances the participant to the debrief and the
completion code. A final assertion shows the run's decision tape folded into the
bundle, so an agent run produces the same durable, replayable artifact a human run
does.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from mug.agents import AgentGameSpec, AgentIds, AgentSeatSpec
from mug.app import build_demo_app
from mug.authoring import Fallback, History, LLMAgent, Provider, Thoughts, Transcript
from mug.client import RealtimeCommand
from mug.game.multiseat import MultiStepResult
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.providers import ModelCall, ModelCompletion, Usage
from mug.replay import validate_replay_bundle
from mug.storage import InMemoryStore

_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_EPISODE_LEN = 4
_UUID = "019b6000-0000-7000-8000-{:012x}"
_AGENTS = ("north", "south")


class _TwoSeatEnv:
    """A tiny two-seat env: it steps a counter and ends after a fixed length.

    It satisfies both the loop's ``MultiSeatEnv`` seam (reset, step an action set)
    and the controller reads (legal actions, text view), so the loop steps the same
    object the models read.
    """

    ACTIONS: ClassVar[list[str]] = ["LEFT", "RIGHT", "STAY"]

    def __init__(self) -> None:
        self._t = 0

    def reset(self) -> MultiStepResult:
        self._t = 0
        return MultiStepResult(
            observations={agent: [0.0] for agent in _AGENTS},
            rewards=dict.fromkeys(_AGENTS, 0.0),
            terminated=False,
            truncated=False,
        )

    def step(self, actions: Mapping[str, int]) -> MultiStepResult:
        self._t += 1
        terminated = self._t >= _EPISODE_LEN
        return MultiStepResult(
            observations={agent: [float(self._t)] for agent in _AGENTS},
            rewards=dict.fromkeys(_AGENTS, 1.0 if terminated else 0.0),
            terminated=terminated,
            truncated=False,
        )

    def legal_actions(self, agent_id: str) -> list[str]:
        return list(self.ACTIONS)

    def text_view(self, agent_id: str) -> str:
        return f"t={self._t}; you are {agent_id}"


class _Runner(LLMAgent):
    """An author's agent that answers a fixed move each decision."""

    provider = Provider.OSS
    model = "fake-local"
    decides_every = 1
    on_timeout = Fallback.REPEAT_LAST

    def get_prompt(
        self,
        env: object,
        agent_id: str,
        history: History,
        chat: Transcript,
        thoughts: Thoughts,
    ) -> str:
        return f"{env.text_view(agent_id)}"  # type: ignore[attr-defined]


def _view(env: Any, agent_id: str) -> str:
    """Render one seat's game as text for its prompt (a study seam)."""
    return env.text_view(agent_id)


async def _adapter(call: ModelCall) -> ModelCompletion:
    """A deterministic keyless adapter: always answer RIGHT."""
    return ModelCompletion(
        outcome="completed",
        resolved_model="fake-local",
        usage=Usage(input_tokens=1, output_tokens=1, cost_micros=0),
        output={"text": "Action: RIGHT"},
    )


def _seat(agent_id: str, tag: int) -> AgentSeatSpec:
    return AgentSeatSpec(
        agent=_Runner(),
        adapter=_adapter,
        ids=AgentIds(
            agent_version_id="agentver_" + _UUID.format(0x430 + tag),
            agent_definition_id="agentdef_" + _UUID.format(0x431 + tag),
            agent_key=f"runner-{agent_id}",
            version_number=1,
            prompt_version_id="promptver_" + _UUID.format(0x440 + tag),
            fallback_policy_key="runner-fallback",
        ),
        agent_id=agent_id,
        seat_key=f"seat-{agent_id}",
        actor_id="actor_" + _UUID.format(0x300 + tag),
        text_view=_view,
    )


def _agent_spec() -> AgentGameSpec:
    return AgentGameSpec(
        channel_key="agent-game",
        make_env=_TwoSeatEnv,
        seats=(_seat("north", 0), _seat("south", 1)),
        decision_timeout=1.0,
        fps=0,
        max_steps=_EPISODE_LEN + 5,
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


def test_a_participant_watches_and_the_run_is_captured_and_bundled() -> None:
    """The model episode plays over the socket, is captured, and yields a bundle."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), agent_game=_agent_spec())
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_game(socket, ("01", "02"))
        frames, nxt = _drain_frames(socket)

        # The participant watched one frame per stepped tick.
        assert len(frames) == _EPISODE_LEN
        assert [frame["frame_number"] for frame in frames] == list(
            range(1, _EPISODE_LEN + 1)
        )
        # Each frame names both seats' actions.
        assert all(set(frame["actions"]) == set(_AGENTS) for frame in frames)
        # The flow advanced past the game to the debrief.
        assert nxt["delivery"]["kind"] == "content"

    # The run assembled exactly one replay bundle, carrying a decision tape folded
    # from the models' calls, and it re-reads as valid.
    bundles = app.state.replay_bundles
    assert len(bundles) == 1
    bundle = bundles[0]
    assert bundle.decision_tape is not None
    assert len(bundle.decision_tape.entries) == _EPISODE_LEN * len(_AGENTS)
    assert bundle.event_count == _EPISODE_LEN + 1  # transitions + boundary


async def test_the_bundle_of_a_watched_run_validates() -> None:
    """The assembled bundle re-reads byte-identically from the object store."""
    store = InMemoryStore()
    app = build_demo_app(store=store, gateway=Gateway(), agent_game=_agent_spec())
    client = TestClient(app)
    with client, client.websocket_connect("/ws") as socket:
        _drive_to_game(socket, ("11", "12"))
        _drain_frames(socket)

    bundle = app.state.replay_bundles[0]
    verdict = await validate_replay_bundle(artifacts=store, manifest=bundle.manifest)
    assert verdict.valid is True
