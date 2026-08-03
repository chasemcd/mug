"""Real browsers, a real mesh, a bad connection, and the run that should have been.

``test_browser_mesh_browser.py`` proves the wiring: two Chromium contexts boot
Pyodide, open real data channels, and finish an episode. It plays on a perfect
link, presses no keys, and checks that a record exists. That is the easiest case
the mesh ever meets, and the one where a rollback defect is invisible.

This module supplies what a real browser test needs to say something stronger.

**The connection misbehaves.** ``mesh_impairment.js`` wraps the send side of the
real ``RTCDataChannel`` and delays, drops, reorders, or holds back the game
packets. Everything else stays real: real WebRTC, real SCTP, real Pyodide, the
shipped rollback engine.

**Both participants play.** The keys are pressed through Playwright's keyboard,
so the input arrives as a participant's input arrives -- against a live clock,
with no relation to the frame boundary -- and the two peers contend for the same
token instead of standing still.

**The recorded run is checked against an outside statement of the truth.** The
inputs cannot be pinned in advance here, because they come from a real clock. But
each peer says what its inputs were, on the wire, as it plays them, and the shim
keeps that traffic. So the true trajectory is one bare replica stepped with the
inputs the peers *sent* -- no engine, no prediction, no rollback -- and the
recorded run must equal it, action for action and hash for hash.

That last part is what a peer-to-peer check otherwise cannot have. The server
never re-executes a mesh episode: it re-derives the trajectory digest from the
frames the owner submitted and confirms every peer claimed the same one. A
rollback that rebuilt the wrong frames in the same way on every replica passes
that exactly.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

import pytest
import uvicorn
from fastapi import FastAPI
from playwright.sync_api import BrowserContext, Page

from examples.tandem.browser_mesh_env import tandem_mesh_spec
from mug.app import build_study_app
from mug.content import Game, Study
from mug.content import Page as ContentPage
from mug.game.browser_mesh import BrowserMeshSpec
from mug.game.browser_mesh_driver import CAPTURE_SCHEMA
from mug.game.determinism import state_hash
from mug.gateway import Gateway
from mug.kernel import PrincipalRef
from mug.launch import provision_launch_ticket
from mug.participant_p2p_types import BrowserP2PConfig
from mug.storage import ArtifactStaging, FinalizedArtifact, InMemoryStore
from tests.e2e_native.browser_sim import off_thread

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS_ROOT = _REPO_ROOT / "ts"
_SHELL = _TS_ROOT / "src" / "client" / "index.html"
_DIST_WEB = _TS_ROOT / "dist-web"
_BOOTSTRAP = _DIST_WEB / "client" / "bootstrap.js"
_IMPAIRMENT = Path(__file__).with_name("mesh_impairment.js")

# The label the mesh data channel carries (``mug.game.signalling``). The shim
# impairs that channel and nothing else the page opens.
CHANNEL_LABEL = "mug-mesh-data"

# What the client tells a participant once the episode barrier has closed. It is
# how a test knows the episode is over without watching the frames.
FINISHED = "peer game finished"

_RESEARCHER = PrincipalRef(
    kind="researcher", id="researcher_019b6000-0000-7000-8000-0000000000ab"
)

INSTRUCTIONS = """
# Working together

Use the **arrow keys** to move your square. Reach the gold token before the
other player does.
"""

INTERVAL = """
# Between rounds

Take a moment. Continue when you are ready.
"""

DEBRIEF = """
# Thank you

That is the end of the study.
"""


# -- serving the study ----------------------------------------------------------


def _free_port() -> int:
    """Return a port the operating system says is free right now."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _ensure_web_built() -> None:
    """Build the TypeScript web client on demand; tolerate a failed build."""
    if _BOOTSTRAP.exists():
        return
    tsc = _TS_ROOT / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        return
    subprocess.run(
        [str(tsc), "-p", "tsconfig.web.json"],
        cwd=_TS_ROOT,
        capture_output=True,
        check=False,
        timeout=180,
    )


def _assemble_web_root(destination: Path) -> Path:
    """Lay out the served root: the shell plus the compiled client and kernel."""
    shutil.copy(_SHELL, destination / "index.html")
    shutil.copy(
        _SHELL.parents[3] / "mug" / "webclient" / "app.css",
        destination / "app.css",
    )
    shutil.copytree(_DIST_WEB / "client", destination / "client")
    shutil.copytree(_DIST_WEB / "kernel", destination / "kernel")
    return destination


def require_web_client() -> None:
    """Skip the test unless the browser client can actually be served."""
    if subprocess.run(["which", "node"], capture_output=True).returncode != 0:
        pytest.skip("node is not on the path")
    _ensure_web_built()
    if not _BOOTSTRAP.exists():
        pytest.skip("ts/dist-web is not built; run `npm run build:web` in ts/")


class CapturingStore(InMemoryStore):
    """A store that keeps the bytes of every artifact the platform finalized.

    The trajectory a mesh room agrees on is staged as an artifact and named by an
    opaque receipt the browsers hold. Nothing the server keeps points back to it
    by a public name, so a test that wants the frames the peers agreed on reads
    them as they are written. This overrides the port method rather than the
    store's private state, so it says only what any artifact writer would say.
    """

    def __init__(self) -> None:
        super().__init__()
        self.finalized: list[bytes] = []

    async def finalize_artifact(
        self,
        staging: ArtifactStaging,
        data: bytes,
        *,
        artifact_id: str,
        finalized_at: str,
        content_encoding: Literal["identity", "gzip", "zstd", "br"] = "identity",
    ) -> FinalizedArtifact:
        """Finalize the bytes and keep a copy for the test to read."""
        self.finalized.append(data)
        return await super().finalize_artifact(
            staging,
            data,
            artifact_id=artifact_id,
            finalized_at=finalized_at,
            content_encoding=content_encoding,
        )


def _study(rounds: int) -> Study:
    """Return a short study that plays the game ``rounds`` times.

    Each round is its own game activity. A browser mesh plays one round per
    activity and the application refuses ``Game(..., episodes=2)`` with a message
    that says so, because one room plays one episode.

    A screen sits between the rounds, the way a study gives a participant a rest.
    It also gives the test a boundary it can see: the packets one round sent are
    read and cleared there, so two rounds are never mistaken for one.
    """
    steps: list[Any] = [ContentPage("instructions", INSTRUCTIONS)]
    for index in range(rounds):
        steps.append(Game(f"round-{index + 1}"))
        if index < rounds - 1:
            steps.append(ContentPage(f"interval-{index + 1}", INTERVAL))
    steps.append(ContentPage("debrief", DEBRIEF))
    return Study(*steps)


@dataclass
class MeshBench:
    """One served study, its store, and one launch link for every peer."""

    base_url: str
    store: CapturingStore
    links: list[str]
    spec: BrowserMeshSpec
    seed: int

    def frame_millis(self) -> float:
        """How long one frame of this game lasts."""
        return 1000.0 / self.spec.fps

    def late_millis(self) -> int:
        """The delay past which a packet cannot reach a peer in time.

        A peer schedules its own input ``input_delay`` frames ahead, so a packet
        that takes longer than that to arrive reaches a peer that has already
        stepped the frame it belongs to. That peer had to predict the input and
        then correct itself, which is the whole point of the engine.
        """
        return int(self.spec.input_delay * self.frame_millis())


@contextmanager
def serve_mesh(
    tmp_path: Path,
    *,
    peers: int = 2,
    rounds: int = 1,
    max_steps: int = 60,
    fps: int = 15,
    seed: int = 7,
) -> Iterator[MeshBench]:
    """Serve the Tandem mesh study and yield one launch link for every peer.

    The room's capture deadline is deliberately left to the platform. It used to
    be a flat sixty seconds that began when the server released the start barrier
    -- before the browsers had downloaded the Python runtime -- and these runs hit
    it more than once on a slow fetch. The mount now derives it from the game, so
    running here on the shipped default is part of what these tests check.
    """
    require_web_client()
    web_root = _assemble_web_root(tmp_path)
    store = CapturingStore()
    gateway = Gateway()
    spec = replace(
        tandem_mesh_spec(), max_steps=max_steps, fps=fps, countdown_seconds=0
    )

    def build() -> tuple[FastAPI, list[str]]:
        app = build_study_app(
            study=_study(rounds),
            store=store,
            gateway=gateway,
            browser_p2p=BrowserP2PConfig(
                channel_key="tandem",
                size=peers,
                game=spec,
                seed=seed,
            ),
            require_launch=True,
            web_root=web_root,
        )
        extra = [
            asyncio.run(
                provision_launch_ticket(gateway, store, researcher=_RESEARCHER)
            ).ticket_handle
            for _ in range(peers - 1)
        ]
        return app, extra

    app, extra = off_thread(build)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    tickets = [str(app.state.launch_ticket), *extra]
    try:
        yield MeshBench(
            base_url=base,
            store=store,
            links=[f"{base}/?ticket={ticket}" for ticket in tickets],
            spec=spec,
            seed=seed,
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)


# -- the misbehaving connection --------------------------------------------------


@dataclass(frozen=True)
class Impairment:
    """What the connection under one browser does to that peer's packets.

    Every field is a way a real peer-to-peer link misbehaves. ``partition_ms``
    cuts the peer off for a window measured from its first game packet, which is
    the shape of a closed lid or a phone that changes network: nothing leaves,
    and it all arrives together when the connection comes back.
    """

    latency_ms: int = 0
    jitter_ms: int = 0
    loss: float = 0.0
    partition_ms: tuple[int, int] | None = None
    seed: int = 20260729

    def label(self) -> str:
        """A short name for the condition, for a test id."""
        parts = []
        if self.latency_ms:
            parts.append(f"latency={self.latency_ms}ms")
        if self.jitter_ms:
            parts.append(f"jitter={self.jitter_ms}ms")
        if self.loss:
            parts.append(f"loss={self.loss}")
        if self.partition_ms:
            parts.append(f"cut={self.partition_ms[0]}-{self.partition_ms[1]}ms")
        return ",".join(parts) or "clean"


def install_impairment(
    context: BrowserContext, impairment: Impairment, *, late_ms: int
) -> None:
    """Install the shim in one browser context, before any page script runs."""
    config = {
        "label": CHANNEL_LABEL,
        "seed": impairment.seed,
        "latency_ms": impairment.latency_ms,
        "jitter_ms": impairment.jitter_ms,
        "loss": impairment.loss,
        "partition_ms": list(impairment.partition_ms)
        if impairment.partition_ms
        else None,
        "late_ms": late_ms,
    }
    source = _IMPAIRMENT.read_text().replace("__CONFIG__", json.dumps(config))
    context.add_init_script(script=source)


def impairment_counts(page: Page) -> dict[str, int]:
    """Return what the shim did to one page's traffic."""
    value = page.evaluate("() => window.__mugImpairment ?? null")
    assert value is not None, "the impairment shim never ran in this page"
    return {key: int(count) for key, count in value.items()}


# What the client says when a room finishes: how long it ran, and how many times this
# peer rolled back and replayed to get there.
_FINISHED = re.compile(r"finished \((\d+) frames, (\d+) corrections\)")


def corrections(page: Page) -> int:
    """Return how many times this peer rolled back and replayed.

    It is read off the client's own finish line rather than out of a test hook, so
    what is asserted is what the participant was told.

    This is the one thing the wire cannot say. The impairment counts prove a packet
    was lost, held, or late; they cannot prove the **engine** did anything about it.
    A mesh whose input delay swallowed every impairment, or whose engine never ran,
    would land on the right trajectory and pass every other check in this file.
    """
    said = page.locator("#status").inner_text()
    found = _FINISHED.search(said)
    assert found is not None, (
        f"this peer never reported a finished room; its status line said {said!r}"
    )
    return int(found.group(2))


# -- walking the study in a real browser ------------------------------------------


def read_and_continue(page: Page, heading: str, *, timeout: int = 60_000) -> None:
    """Read one page of the author's own text and continue, as a participant does."""
    page.wait_for_selector(f"text={heading}", timeout=timeout)
    page.get_by_role("button", name="Continue").click()


def wait_for_the_game(page: Page, *, timeout: int = 180_000) -> None:
    """Wait until this browser is on a game activity that has not finished yet.

    The first run of a session downloads the whole Python runtime from a CDN, so
    the wait is generous.

    The second clause matters in a study with more than one round: the client
    mounts the canvas a moment before it reports that it is waiting for another
    player, so a round that only waited for the canvas could still be reading the
    previous round's closing message and stop before it started.
    """
    page.wait_for_selector("canvas", timeout=timeout)
    page.wait_for_function(
        "() => !(document.querySelector('#status')?.textContent ?? '')"
        f".includes('{FINISHED}')",
        timeout=timeout,
    )


_CYCLES = [
    ["ArrowRight", "ArrowDown", "ArrowRight", "ArrowUp"],
    ["ArrowDown", "ArrowLeft", "ArrowUp", "ArrowLeft"],
    ["ArrowUp", "ArrowRight", "ArrowDown", "ArrowRight"],
    ["ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown"],
]


def play_with_the_keys(
    pages: Sequence[Page], *, timeout: float = 240.0, hold_ms: int = 200
) -> None:
    """Play every peer with the arrow keys until the episode closes.

    A mesh test that presses no keys plays the one trajectory where a rollback
    defect cannot show: every peer predicts the default action, every prediction
    is right, and nothing is ever corrected. Here each browser holds a different
    key at a different time, so the peers meet on the same squares and a wrong
    prediction changes what both of them see.

    The keys are real key events through the browser, and their timing has no
    relation to the frame boundary. That is the point: a participant's key does
    not land on a frame either.

    The loop ends on the client's own report that the episode closed, so it plays
    for exactly as long as the episode lasts however slowly the runtime booted.
    """
    held: list[str | None] = [None] * len(pages)
    started = time.monotonic()
    deadline = started + timeout
    # What each peer reported and when. A browser mesh failure is otherwise a
    # single line of final text, and the question is always which step was slow.
    timeline: list[list[tuple[float, str]]] = [[] for _ in pages]
    step = 0
    while time.monotonic() < deadline:
        for index, page in enumerate(pages):
            text = _status(page)
            if not timeline[index] or timeline[index][-1][1] != text:
                timeline[index].append((time.monotonic() - started, text))
        if all(FINISHED in _status(page) for page in pages):
            break
        for index, page in enumerate(pages):
            key = _CYCLES[index % len(_CYCLES)][step % 4]
            previous = held[index]
            if previous is not None:
                page.keyboard.up(previous)
            page.keyboard.down(key)
            held[index] = key
        step += 1
        time.sleep(hold_ms / 1000.0)
    for index, page in enumerate(pages):
        previous = held[index]
        if previous is not None:
            page.keyboard.up(previous)
    unfinished = [
        index for index, page in enumerate(pages) if FINISHED not in _status(page)
    ]
    if unfinished:
        told = "\n".join(
            f"  peer {index}: "
            + " -> ".join(f"[{at:5.1f}s] {text}" for at, text in entries)
            for index, entries in enumerate(timeline)
        )
        refused = _refusal(pages)
        assert refused is None, (
            f"the room refused the round: {refused}.\n"
            "That is the platform working -- it records a run only when the peers "
            "agree on it -- but the round is lost. `MeshEngine.finalize` force-"
            "promotes the frames still speculative at the barrier, so a peer whose "
            "partner's input never arrived exports its own **prediction** for that "
            "frame; two peers missing different inputs then hold different "
            "trajectories. Measured on this machine, the harshest link loses a round "
            f"this way about one time in six.\n{told}"
        )
        raise AssertionError(
            f"the episode barrier never closed for peers {unfinished}, and no peer "
            f"said why. What each peer reported, and when:\n{told}"
        )


# What the client says when the room refused the round rather than recording it.
_STOPPED = re.compile(r"the peer game stopped: (\S+)")


def _refusal(pages: Sequence[Page]) -> str | None:
    """Return why the room refused this round, or nothing if it did not refuse."""
    for page in pages:
        found = _STOPPED.search(_status(page))
        if found is not None:
            return found.group(1)
    return None


def _status(page: Page) -> str:
    """Return what the client is currently telling this participant."""
    return page.locator("#status").inner_text()


# -- what the run recorded --------------------------------------------------------


def recorded_captures(bench: MeshBench) -> list[dict[str, Any]]:
    """Return every trajectory the rooms agreed on, in the order they were made."""
    payloads: list[dict[str, Any]] = []
    for data in bench.store.finalized:
        try:
            value = json.loads(data)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("schema") == CAPTURE_SCHEMA:
            payloads.append(value)
    return payloads


def recorded_episodes(bench: MeshBench) -> list[dict[str, Any]]:
    """Return every peer-authority episode the server wrote."""
    return [
        state
        for _, state in bench.store.scan_aggregates()
        if isinstance(state, dict) and state.get("authority") == "peer"
    ]


# -- the oracle -------------------------------------------------------------------


def take_packets(pages: Sequence[Page]) -> list[str]:
    """Take every game packet the peers have sent since the last call.

    The log is emptied as it is read, so the next episode starts from nothing.
    Frame numbers restart at zero in a new episode, and two rounds read together
    would look like one peer contradicting itself.
    """
    texts: list[str] = []
    for page in pages:
        taken = page.evaluate(
            "() => (window.__mugPackets ?? []).splice(0)",
        )
        texts.extend(str(one) for one in taken)
    return texts


def sent_inputs(texts: Sequence[str]) -> dict[str, dict[int, int]]:
    """Return what every peer said its own inputs were, as it sent them.

    The shim keeps each peer's outgoing packets before it impairs them, so this
    is the input schedule the peers played, taken from the wire and not from the
    record the mesh later produced. Each packet repeats the last few frames of
    the sender's input, so a value seen twice must be the same value twice; a
    peer that contradicted itself would be a fault in its own right.
    """
    inputs: dict[str, dict[int, int]] = {}
    for text in texts:
        try:
            packet = json.loads(text)
        except ValueError:
            continue
        if not isinstance(packet, dict) or packet.get("kind") != "input":
            continue
        sender = str(packet["sender"])
        schedule = inputs.setdefault(sender, {})
        for raw_frame, raw_action in packet["inputs"]:
            frame, action = int(raw_frame), int(raw_action)
            if schedule.get(frame, action) != action:
                raise AssertionError(
                    f"peer {sender} sent two different actions for frame {frame}"
                )
            schedule[frame] = action
    return inputs


def true_actions(
    peers: Sequence[str],
    schedules: Mapping[str, Mapping[int, int]],
    frame: int,
    *,
    input_delay: int,
    default_action: int,
) -> dict[str, int]:
    """Return the action set frame ``frame`` must step, with perfect information.

    A peer schedules its input ``input_delay`` frames ahead, so the opening frames
    carry the default action on every peer and nothing is submitted for them.
    """
    if frame < input_delay:
        return dict.fromkeys(peers, default_action)
    missing = [peer for peer in peers if frame not in schedules.get(peer, {})]
    if missing:
        raise AssertionError(
            f"frame {frame} has no sent input from {missing}, so the run cannot be "
            "checked against what the peers played"
        )
    return {peer: schedules[peer][frame] for peer in peers}


def oracle_frames(
    bench: MeshBench,
    peers: Sequence[str],
    schedules: Mapping[str, Mapping[int, int]],
    frames: int,
) -> list[dict[str, Any]]:
    """Return the trajectory the mesh must have produced, computed without it.

    One bare replica of the study's own bundle, stepped with the inputs the peers
    sent. No engine, no prediction, no rollback, no network. Agreeing with this is
    a statement about what the episode *was*, not about what the peers agreed on.
    """
    namespace: dict[str, Any] = {}
    exec(bench.spec.source_bundle, namespace)
    replica = namespace["make_replica"](sorted(peers), bench.seed)
    rows: list[dict[str, Any]] = []
    for frame in range(frames):
        actions = true_actions(
            sorted(peers),
            schedules,
            frame,
            input_delay=bench.spec.input_delay,
            default_action=bench.spec.default_action,
        )
        observation, rewards, terminated, truncated, info = replica.step(dict(actions))
        rows.append(
            {
                "frame_number": frame,
                "actions": dict(sorted(actions.items())),
                "rewards": {key: float(rewards[key]) for key in sorted(rewards)},
                "terminated": bool(terminated),
                "truncated": bool(truncated),
                "info": info,
                "state_hash": state_hash(observation).hex,
            }
        )
    return rows


def assert_the_participants_played(
    bench: MeshBench, capture: Mapping[str, Any]
) -> None:
    """Every peer actually moved, so the run is not the do-nothing trajectory.

    A browser mesh test can look thorough and still play the one episode where
    nothing can go wrong. If the keys never reach the game, every peer holds the
    default action, every prediction about every peer is right, and no rollback
    ever happens. The oracle would agree with the record perfectly and say
    nothing at all.
    """
    default = bench.spec.default_action
    for peer in capture["frozen_peer_handles"]:
        played = {int(frame["actions"][peer]) for frame in capture["frames"]}
        assert played - {default}, (
            f"peer {peer} held the default action for the whole episode, so the "
            "keys never reached the game and this run proves nothing"
        )


def assert_agrees_with_the_oracle(
    bench: MeshBench,
    capture: Mapping[str, Any],
    schedules: Mapping[str, Mapping[int, int]],
) -> None:
    """The recorded episode is the episode the peers' own inputs imply."""
    frames = list(capture["frames"])
    assert frames, "the room recorded an episode with no frames"
    assert_the_participants_played(bench, capture)
    peers = sorted(capture["frozen_peer_handles"])
    truth = oracle_frames(bench, peers, schedules, len(frames))
    assert frames == truth, (
        "the peers agreed on a trajectory that is not the one their own inputs "
        "imply; the mesh converged on the wrong answer"
    )


__all__ = [
    "CHANNEL_LABEL",
    "FINISHED",
    "CapturingStore",
    "Impairment",
    "MeshBench",
    "assert_agrees_with_the_oracle",
    "assert_the_participants_played",
    "impairment_counts",
    "install_impairment",
    "oracle_frames",
    "play_with_the_keys",
    "read_and_continue",
    "recorded_captures",
    "recorded_episodes",
    "require_web_client",
    "sent_inputs",
    "serve_mesh",
    "take_packets",
    "true_actions",
    "wait_for_the_game",
]
