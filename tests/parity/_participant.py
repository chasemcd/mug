"""A participant walking a study, for the parity fixtures.

Every required reference fixture is the same shape: somebody connects, answers
what they are asked, plays what they are given, and reaches the end. The
interesting part is never the websocket bookkeeping, so it lives here and each
fixture states only what it proves.

Two rules this harness keeps, because a fixture that broke either would look like
a platform defect:

- **Each participant mints its own command identifiers.** Two participants in one
  fixture must not send the same idempotency key, or the second one is refused as
  a repeat of the first and the fixture records a conflict it never meant to test.
- **A read waits for the frame it wants and drops the rest.** The order of acks,
  deliveries, and pushed frames is the platform's to choose.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

from starlette.testclient import WebSocketTestSession

from mug.client import RealtimeCommand
from mug.game.browser import BrowserGameSpec
from mug.game.determinism import state_hash
from mug.game.env import GymEnv
from mug.kernel import Digest, SchemaRef

A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_INTENT = SchemaRef(name="mug.parity.intent", version=0, digest=A_DIGEST)
_ID_BODY = "019b6000-0000-7000-8000-{:012x}"


class Commands:
    """Mint the command envelopes for one participant, each one distinct.

    ``tag`` separates one participant from another. It is part of both the command
    id and the idempotency key, so two participants in one fixture never collide
    and a repeat within one participant still reads as the repeat it is.
    """

    def __init__(self, tag: int = 0) -> None:
        self._tag = tag
        self._n = 0

    def next(self, channel: str) -> RealtimeCommand:
        """Return the next command envelope on one channel."""
        self._n += 1
        serial = self._tag * 1000 + self._n
        return RealtimeCommand(
            command_id="command_" + _ID_BODY.format(serial),
            channel_key=channel,
            intent_schema=_INTENT,
            payload_digest=A_DIGEST,
            idempotency_key="idem_" + f"p{self._tag}n{serial}".rjust(21, "0") + "A",
            submitted_at="2026-07-27T00:00:00.000000Z",
        )

    def envelope(self, channel: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Return the whole command message a client sends."""
        return {
            "type": "command",
            "command": self.next(channel).model_dump(mode="json", exclude_none=True),
            "payload": payload,
        }


class Participant:
    """One connected participant, read and driven by what they are shown."""

    def __init__(self, socket: WebSocketTestSession, tag: int = 0) -> None:
        self._socket = socket
        self.commands = Commands(tag)
        self.resume_token: str | None = None

    @property
    def socket(self) -> WebSocketTestSession:
        """Return this participant's own connection.

        A test about somebody leaving needs the connection itself, because that is
        what leaving is: the socket goes, and the server finds out on its own
        schedule rather than being told.
        """
        return self._socket

    def handshake(self) -> Participant:
        """Read the handshake and keep the token a reconnection needs."""
        message = cast("dict[str, Any]", self._socket.receive_json())
        assert message["type"] == "handshake_ack", message
        self.resume_token = cast("str | None", message.get("resume_token"))
        return self

    def read(self) -> dict[str, Any]:
        """Return the next message of any kind."""
        return cast("dict[str, Any]", self._socket.receive_json())

    def delivery(self, kind: str | None = None, limit: int = 40) -> dict[str, Any]:
        """Return the next delivery, or the next one of a named kind."""
        for _ in range(limit):
            message = self.read()
            if message.get("type") != "delivery":
                continue
            delivered = cast("dict[str, Any]", message["delivery"])
            if kind is None or delivered.get("kind") == kind:
                return delivered
        raise AssertionError(f"no {kind or 'delivery'} frame arrived")

    def frames(self, limit: int = 400) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Collect the pushed game frames, then return what followed them.

        A drawn game pushes a render packet beside each stepped frame, so both are
        collected: what follows the run is the first message that is neither.
        """
        collected: list[dict[str, Any]] = []
        for _ in range(limit):
            message = self.read()
            if message.get("type") in ("frame", "render"):
                collected.append(message)
                continue
            return collected, message
        raise AssertionError("the frames never ended")

    def rest(self) -> dict[str, Any]:
        """Read the rest between two rounds and say the participant is ready."""
        collected, message = self.frames()
        del collected
        assert message["type"] == "interval", message
        self._socket.send_json({"type": "interval_done"})
        return message

    def advance(self, answers: dict[str, Any] | None = None) -> None:
        """Answer the current step and move on."""
        self._socket.send_json(
            self.commands.envelope("flow.advance", {"answers": answers or {}})
        )

    def send(self, channel: str, payload: dict[str, Any]) -> None:
        """Send one command on a named channel."""
        self._socket.send_json(self.commands.envelope(channel, payload))

    def completion(self) -> dict[str, Any]:
        """Read on until the study says it is finished."""
        return self.delivery("complete", limit=80)


def honest_browser_run(
    manifest: dict[str, Any], spec: BrowserGameSpec, actions: list[int]
) -> dict[str, Any]:
    """Return the episode an honest browser reports for one run of the bundle.

    The bundle is the same Python the participant browser runs under Pyodide, so
    running it here proves the shipped source really steps and really draws. The
    server re-executes it to verify, and a run whose hashes did not come from the
    bundle is refused.
    """
    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)
    env = GymEnv(namespace["make_env"], seed=spec.seed)
    env.reset()
    transitions: list[dict[str, Any]] = []
    state = None
    for frame, action in enumerate(actions, start=1):
        state = env.step(action)
        transitions.append(
            {
                "interaction_id": manifest["interaction_id"],
                "channel_key": manifest["channel_key"],
                "episode_id": manifest["episode_id"],
                "frame_number": frame,
                "action_digest": state_hash(action).model_dump(mode="json"),
                "state_digest": state_hash(state.observation).model_dump(mode="json"),
                "authority": "browser",
                "applied_decisions": [],
                "recorded_at": "2026-07-27T00:00:00.000000Z",
            }
        )
    assert state is not None
    return {
        "transitions": transitions,
        "boundary": {
            "episode_id": manifest["episode_id"],
            "interaction_id": manifest["interaction_id"],
            "kind": "reset",
            "end_frame_exclusive": len(actions),
            "authority": "browser",
            "state_hash": state_hash(state.observation).model_dump(mode="json"),
        },
    }


def heads(store: Any, schema_name: str) -> list[dict[str, Any]]:
    """Return every recorded aggregate head of one schema name."""
    found: list[dict[str, Any]] = []
    for _aggregate_id, state in cast(
        "Iterator[tuple[str, Any]]", store.scan_aggregates()
    ):
        if not isinstance(state, dict):
            continue
        head = cast("dict[str, Any]", state)
        schema = head.get("schema")
        if isinstance(schema, dict) and cast("dict[str, Any]", schema).get(
            "name"
        ) == schema_name:
            found.append(head)
    return found


def episodes(store: Any) -> list[dict[str, Any]]:
    """Return every recorded episode head."""
    found: list[dict[str, Any]] = []
    for aggregate_id, state in cast(
        "Iterator[tuple[str, Any]]", store.scan_aggregates()
    ):
        if aggregate_id.startswith("episode_") and isinstance(state, dict):
            found.append(cast("dict[str, Any]", state))
    return found


__all__ = [
    "A_DIGEST",
    "Commands",
    "Participant",
    "episodes",
    "heads",
    "honest_browser_run",
]
