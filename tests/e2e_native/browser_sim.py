"""A simulated browser for the peer-to-peer mount, for end-to-end tests.

The legacy suite drove two real Chromium windows through a Flask server. That is
still worth doing once (``test_browser_mesh_browser.py``), but it cannot be the
whole story: a real browser makes a run slow, and it makes latency, packet loss,
and a hidden tab into things a test *hopes for* rather than things it *states*.

So this module plays the part of the browser's edge exactly, and nothing more. It
speaks the real API-09 frames over a real websocket to the real application, it
runs the real shipped mesh runtime, and it carries the real packet codec over
simulated data channels whose delay and loss the test names. Everything the server
does is real: the launch gate, the flow, matchmaking, signalling relay, the start
barrier, capture reconciliation, artifact persistence, and episode recording.

Only two things are simulated, and both are stated here rather than hidden: WebRTC
(the signalling payloads are opaque to the server, so the peers exchange
placeholders) and the data channels themselves.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from fastapi import FastAPI
from starlette.testclient import WebSocketTestSession

from mug.game.browser_mesh import mesh_run_config
from mug.game.browser_mesh_driver import MeshDriver, boot_mesh_driver

_T = TypeVar("_T")


def off_thread(build: Callable[[], _T]) -> _T:
    """Run one setup step on a thread with no event loop of its own.

    Playwright's synchronous API drives its own event loop on the test thread, and
    the launch gate provisions its first ticket with ``asyncio.run``, which refuses
    to start inside a running loop. Every application in this suite is therefore
    built on another thread, so a browser test and a simulated one can share a
    process without one quietly breaking the other.
    """
    box: list[_T] = []
    thread = threading.Thread(target=lambda: box.append(build()))
    thread.start()
    thread.join(timeout=120)
    if not box:
        raise AssertionError("the application never finished building")
    return box[0]


class Rng:
    """A small deterministic generator, so a test never uses the global one."""

    def __init__(self, seed: int) -> None:
        self._state = seed & 0x7FFFFFFF or 1

    def unit(self) -> float:
        """Return the next value in the half-open unit interval."""
        self._state = (self._state * 48271) % 2147483647
        return self._state / 2147483647


def _no_windows() -> dict[str, tuple[int, int]]:
    """Return the empty silent-window map, typed for the strict checker."""
    return {}


def _no_delays() -> dict[tuple[str, str], int]:
    """Return the empty per-direction delay map, typed for the strict checker."""
    return {}


@dataclass(frozen=True)
class Link:
    """How the simulated data channels carry packets between the browsers."""

    latency: int = 0
    jitter: int = 0
    loss: float = 0.0
    silent: Mapping[str, tuple[int, int]] = field(default_factory=_no_windows)
    slow: Mapping[tuple[str, str], int] = field(default_factory=_no_delays)


def _answers_for(form: dict[str, Any]) -> dict[str, Any]:
    """Answer one form from its own specification.

    A choice takes its first option, a rating takes the middle of its scale, and
    text is left empty unless the field is required. So the harness satisfies a
    study it has never seen, and a form that changes does not break it.
    """
    answers: dict[str, Any] = {}
    for question in form["fields"]:
        if not question.get("required", False) and question["kind"] == "text":
            continue
        if question["kind"] == "choice":
            answers[question["field_key"]] = question["options"][0]
        elif question["kind"] == "likert":
            answers[question["field_key"]] = max(1, int(question["scale"]) // 2)
        else:
            answers[question["field_key"]] = "an answer"
    return answers


class BrowserSim:
    """One simulated browser: its socket, its room bindings, and its driver."""

    def __init__(self, socket: WebSocketTestSession, tag: str) -> None:
        self.socket = socket
        self.tag = tag
        self.manifest: dict[str, Any] = {}
        self.bootstrap: dict[str, Any] = {}
        self.start: dict[str, Any] = {}
        self.driver: MeshDriver | None = None
        self.finish: dict[str, Any] | None = None
        self.abort: dict[str, Any] | None = None
        self.answered: list[str] = []
        self._requests = 0

    # -- the flow --------------------------------------------------------------

    def play_to_the_game(self) -> None:
        """Answer whatever the study asks, and stop when the game arrives.

        The harness reads each form the study sends and answers it from its own
        specification, so it walks any authored study rather than the demo's two
        fixed forms. That is the point: a study puts its own consent, its own
        instructions, and its own surveys before the game.
        """
        assert self.socket.receive_json()["type"] == "handshake_ack"
        preload = self.socket.receive_json()
        assert preload["delivery"]["kind"] == "preload"
        self.manifest = preload["delivery"]["manifest"]
        assert self.manifest["mode"] == "peer"
        game = self._walk_until("game")
        assert game["mode"] == "peer"

    def play_to_the_next_game(self) -> None:
        """Leave the room that just ended and walk on to the study's next game.

        A study may play twice -- a practice round and then the real one -- and
        each round is its own room. Everything the last room bound is dropped
        here, so a stale handle or a stale driver can not be mistaken for this
        round's.
        """
        self.bootstrap = {}
        self.start = {}
        self.driver = None
        self.finish = None
        assert self._walk_until("game")["mode"] == "peer"

    def finish_the_study(self) -> dict[str, Any]:
        """Answer everything after the game and return the completion delivery."""
        return self._walk_until("complete")

    def _walk_until(self, kind: str, limit: int = 32) -> dict[str, Any]:
        """Answer each activity the study presents until the named kind arrives."""
        for _ in range(limit):
            delivery = self._delivery()
            self.answered.append(str(delivery.get("activity_key", delivery["kind"])))
            if delivery["kind"] == kind:
                return delivery
            if delivery["kind"] == "form":
                self._advance(_answers_for(delivery["form"]))
            elif delivery["kind"] == "content":
                self._advance({})
            else:
                raise AssertionError(
                    f"browser {self.tag} reached a {delivery['kind']} activity"
                    f" while looking for {kind}"
                )
        raise AssertionError(f"browser {self.tag} never reached a {kind} activity")

    def _delivery(self) -> dict[str, Any]:
        message: dict[str, Any] = self.socket.receive_json()
        assert message["type"] == "delivery", message
        return message["delivery"]

    def _advance(self, answers: dict[str, Any]) -> None:
        """Submit one flow-advance command and read both acknowledgements."""
        self.socket.send_json(
            {
                "type": "command",
                "command": {
                    "command_id": f"command_019b6000-0000-7000-8000-{self._next(12)}",
                    "channel_key": "flow.advance",
                    "intent_schema": {
                        "name": "mug.demo.intent",
                        "version": 0,
                        "digest": {"algorithm": "sha-256", "hex": "a" * 64},
                    },
                    "payload_digest": {"algorithm": "sha-256", "hex": "a" * 64},
                    "idempotency_key": "idem_" + self._next(21) + "A",
                    "submitted_at": "2026-07-25T00:00:00.000000Z",
                },
                "payload": {"answers": answers},
            }
        )
        assert self.socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert self.socket.receive_json()["ack"]["ack_kind"] == "accepted"

    def _next(self, width: int) -> str:
        """Return one fresh, well-formed identifier body for this browser."""
        self._requests += 1
        return f"{self.tag}{self._requests:0{width - len(self.tag)}d}"

    # -- the room --------------------------------------------------------------

    def await_frame(self, kind: str, limit: int = 40) -> dict[str, Any]:
        """Read frames until the named one arrives, and keep what it carried.

        An abort ends the wait for anything else. A room that aborted will never
        send a start or a finish, so a test that kept reading would block on a
        socket that has nothing more to say -- and a hang says far less about what
        went wrong than the abort reason does.
        """
        for _ in range(limit):
            message: dict[str, Any] = self.socket.receive_json()
            if message.get("type") == "p2p_mesh_abort":
                self.abort = message["abort"]
            if message.get("type") == "p2p_mesh_finish":
                self.finish = message["finish"]
            if message.get("type") == kind:
                return message
            if self.abort is not None and kind != "p2p_mesh_abort":
                raise AssertionError(
                    f"browser {self.tag} wanted a {kind} frame but the room aborted:"
                    f" {self.abort['reason']}"
                )
        raise AssertionError(f"browser {self.tag} never received a {kind} frame")

    def take_bootstrap(self) -> dict[str, Any]:
        """Read this browser's own room bootstrap."""
        self.bootstrap = self.await_frame("p2p_bootstrap")["bootstrap"]
        return self.bootstrap

    @property
    def handle(self) -> str:
        """Return this browser's own public peer handle."""
        return str(self.bootstrap["local_peer_handle"])

    @property
    def peers(self) -> tuple[str, ...]:
        """Return the other peers' public handles."""
        return tuple(peer["peer_handle"] for peer in self.bootstrap["peers"])

    @property
    def is_capture_owner(self) -> bool:
        """Return whether this browser is the room's designated capture owner."""
        return self.handle == self.bootstrap["capture_owner_handle"]

    def _room_frame(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        """Wrap one outbound room frame with its room and generation binding."""
        return {
            "schema": {
                "name": name,
                "version": 0,
                "digest": self.bootstrap["schema"]["digest"],
            },
            "room_handle": self.bootstrap["room_handle"],
            "negotiation_generation": self.bootstrap["negotiation_generation"],
            **body,
        }

    def send_signal(self, target: str, kind: str) -> None:
        """Send one opaque signalling frame toward a remote peer."""
        signal = self._room_frame(
            "mug.api-09.p2p-signal",
            {
                "request_id": f"request_019b6000-0000-7000-8000-{self._next(12)}",
                "target_peer_handle": target,
                "signal_kind": kind,
            },
        )
        if kind != "end_of_candidates":
            signal["payload_json"] = json.dumps({"sdp": kind})
        self.socket.send_json({"type": "p2p_signal", "signal": signal})

    def send_ready(self) -> None:
        """Report every link validated, which is what crosses the start barrier."""
        self.socket.send_json(
            {
                "type": "p2p_peer_ready",
                "ready": self._room_frame(
                    "mug.api-09.p2p-peer-ready",
                    {"validated_peer_handles": sorted(self.peers)},
                ),
            }
        )

    def boot_driver(self, seed: int | None = None) -> MeshDriver:
        """Build this browser's mesh driver from its manifest and its room."""
        study: dict[str, Any] = {}
        exec(self.manifest["source_bundle"], study)
        config = mesh_run_config(
            self.manifest,
            local_peer_handle=self.handle,
            peer_handles=self.peers,
            room_handle=str(self.bootstrap["room_handle"]),
            negotiation_generation=int(self.bootstrap["negotiation_generation"]),
            seed=int(self.start["seed"] if seed is None else seed),
        )
        self.driver = boot_mesh_driver(
            json.dumps(config), study["make_replica"], study.get("draw")
        )
        return self.driver

    def send_complete(self, trajectory_hex: str | None = None) -> None:
        """Report this browser's own finished trajectory claim.

        ``trajectory_hex`` names a different run than the one this browser played,
        which is how a test states that two peers disagree.
        """
        assert self.driver is not None
        claim = self._claim()
        if trajectory_hex is not None:
            claim["trajectory_digest"] = {
                "algorithm": "sha-256",
                "hex": trajectory_hex,
            }
        self.socket.send_json(
            {
                "type": "p2p_peer_complete",
                "complete": self._room_frame("mug.api-09.p2p-peer-complete", claim),
            }
        )

    def send_capture(self, payload_json: str | None = None) -> None:
        """Submit the whole trajectory, which only the capture owner may do."""
        assert self.driver is not None
        payload = (
            self.driver.capture_payload_json() if payload_json is None else payload_json
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self.socket.send_json(
            {
                "type": "p2p_capture_submission",
                "submission": self._room_frame(
                    "mug.api-09.p2p-capture-submission",
                    {
                        **self._claim(),
                        "payload_json": payload,
                        "payload_digest": {"algorithm": "sha-256", "hex": digest},
                    },
                ),
            }
        )

    def _claim(self) -> dict[str, Any]:
        """Return the trajectory digest and frame count this browser claims."""
        assert self.driver is not None
        from mug.game.browser_mesh import verify_mesh_capture

        verified = verify_mesh_capture(self.driver.capture_payload_json())
        return {
            "trajectory_digest": verified.trajectory_digest.model_dump(mode="json"),
            "frame_count": verified.frame_count,
        }


def negotiate(browsers: Sequence[BrowserSim]) -> None:
    """Exchange the signalling frames the room relays, then report readiness.

    The server never reads a signalling payload, so the exchange only has to be
    the right *shape*: every ordered pair trades a description and a candidate,
    and every browser reads exactly what the relay delivered to it. A test that
    got the shape wrong would deadlock here rather than pass quietly.
    """
    for sender in browsers:
        for target in sender.peers:
            receiver = next(item for item in browsers if item.handle == target)
            for kind in ("offer", "candidate", "end_of_candidates"):
                sender.send_signal(target, kind)
                ack = sender.await_frame("p2p_signal_ack")["ack"]
                assert ack["status"] == "queued", ack
                delivered = receiver.await_frame("p2p_signal_delivery")["signal"]
                assert delivered["source_peer_handle"] == sender.handle
    for browser in browsers:
        browser.send_ready()


def run_room_mesh(
    browsers: Sequence[BrowserSim],
    *,
    link: Link | None = None,
    scripts: Mapping[str, Sequence[int]] | None = None,
    seed: int = 4242,
    ticks: int = 600,
) -> None:
    """Play the whole episode over the simulated data channels between browsers.

    The loop is lockstep, so the run is reproducible: a test that names a latency
    of six ticks gets exactly six ticks every time.
    """
    link = link or Link()
    drivers = {browser.handle: browser.boot_driver() for browser in browsers}
    handles = list(drivers)
    # Every peer presses a different, changing key by default. A mesh whose seats
    # all held one action would never contradict a repeat-last prediction, so no
    # rollback would fire and a latency test would prove nothing.
    scripts = scripts or {
        handle: [(tick * 7 + index * 3) % 5 for tick in range(ticks)]
        for index, handle in enumerate(handles)
    }
    rng = Rng(seed)
    queue: list[tuple[int, str, str, str]] = []

    for tick in range(ticks):
        for due, receiver, sender, text in queue:
            if due == tick:
                drivers[receiver].receive(sender, text)
        queue = [item for item in queue if item[0] > tick]

        for sender in handles:
            script = scripts.get(sender, ())
            action = script[tick] if tick < len(script) else 0
            window = link.silent.get(sender)
            hidden = window is not None and window[0] <= tick < window[1]
            for text in drivers[sender].tick(action):
                for receiver in handles:
                    if receiver == sender:
                        continue
                    if hidden:
                        assert window is not None
                        queue.append((window[1] + 1, receiver, sender, text))
                        continue
                    if json.loads(text)["kind"] == "input" and rng.unit() < link.loss:
                        continue
                    latency = link.slow.get((sender, receiver), link.latency)
                    spread = (
                        0
                        if link.jitter <= 0
                        else int(rng.unit() * (2 * link.jitter + 1)) - link.jitter
                    )
                    queue.append(
                        (max(tick + 1, tick + latency + spread), receiver, sender, text)
                    )

        if all(driver.ready_to_finalize() for driver in drivers.values()):
            break

    for driver in drivers.values():
        driver.finalize()


def report_and_capture(browsers: Sequence[BrowserSim]) -> None:
    """Claim the run on every socket, then submit the payload from the owner."""
    for browser in browsers:
        browser.send_complete()
    owner = next(browser for browser in browsers if browser.is_capture_owner)
    owner.send_capture()


def launch_urls(app: FastAPI, tickets: Sequence[str]) -> list[str]:
    """Return the launch-link query strings the simulated browsers connect with."""
    return [f"/ws?ticket={ticket}" for ticket in tickets]


__all__ = [
    "BrowserSim",
    "Link",
    "Rng",
    "launch_urls",
    "negotiate",
    "off_thread",
    "report_and_capture",
    "run_room_mesh",
]
