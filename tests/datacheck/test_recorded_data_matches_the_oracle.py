"""The data check: what the platform recorded is what actually happened.

Everything else about a browser run checks the platform against itself. The client
reports state hashes, the server re-executes the run and compares -- both halves are
this code, so a fault in what a value *means* is invisible to it. That is the
standing failure in this repo: a record with a producer, a reader, and a passing test
whose shape no outside party can read.

This is the outside party. ``tests/datacheck/oracle.py`` states what the environment
must answer, computed by repeating its arithmetic rather than by running it, and
``vectors.json`` pins the resulting digests. A real participant's run then goes
through the whole platform -- the socket, the parts, the staging, the seal, the
verification, the capture -- and what comes out of the **store** is compared against
that file, frame by frame.

So this fails if the platform drops a frame, repeats one, reorders two, truncates a
run, loses a part boundary, records a different action against a frame, or changes
how any of it is hashed or serialized. None of which the self-consistent checks can
see.

Re-pin the vectors only on purpose:
``uv run python -m tests.datacheck.generate_vectors``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from mug.app import build_demo_app
from mug.client import RealtimeCommand
from mug.game.browser import BrowserGameSpec
from mug.game.capture import recorded_trajectory
from mug.game.capture_parts import FRAMES_PER_PART
from mug.game.determinism import state_hash
from mug.game.env import GymEnv
from mug.game.trajectory import read_trajectory
from mug.gateway import Gateway
from mug.kernel import Digest, SchemaRef
from mug.storage import InMemoryStore
from tests.datacheck.oracle import (
    BENCH_BUNDLE,
    BENCH_FRAMES,
    BENCH_SEED,
    bench_actions,
    bench_observations,
)

VECTORS: dict[str, Any] = json.loads(
    (Path(__file__).with_name("vectors.json")).read_text()
)
_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_SEAT = "player"


def _spec() -> BrowserGameSpec:
    return BrowserGameSpec(
        channel_key="bench",
        source_bundle=BENCH_BUNDLE,
        requires=(),
        action_bindings={"ArrowRight": 1},
        default_action=0,
        seed=BENCH_SEED,
        max_steps=BENCH_FRAMES,
        countdown_seconds=0,
    )


def _command(tag: str, channel: str) -> dict[str, Any]:
    return RealtimeCommand(
        command_id=f"command_019b6000-0000-7000-8000-0000000{tag.rjust(5, '0')}",
        channel_key=channel,
        intent_schema=SchemaRef(name="mug.demo.intent", version=0, digest=_A_DIGEST),
        payload_digest=_A_DIGEST,
        # Right-padding collides: "1" and "10" pad to the same key, and the
        # platform then correctly refuses the second as a replay of the first.
        idempotency_key="idem_" + tag.rjust(21, "0") + "A",
        submitted_at="2026-07-28T00:00:00.000000Z",
    ).model_dump(mode="json", exclude_none=True)


def _played(manifest: dict[str, Any], spec: BrowserGameSpec) -> list[dict[str, Any]]:
    """Build the transitions an honest client reports, by running the bundle.

    The client is entitled to run the environment -- that is what a participant's
    browser does. What makes this a check rather than a tautology is that the values
    it produces are compared against the oracle before anything else happens.
    """
    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)
    env = GymEnv(namespace["make_env"], seed=spec.seed)
    env.reset()
    transitions: list[dict[str, Any]] = []
    for frame, action in enumerate(bench_actions(), start=1):
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
                "recorded_at": "2026-07-28T00:00:00.000000Z",
            }
        )
    return transitions


def _report(
    socket: Any,
    manifest: dict[str, Any],
    transitions: list[dict[str, Any]],
    *,
    per_part: int,
    upto: int | None = None,
) -> None:
    """Report the run the way a client does: in parts, closing the last one."""
    actions = bench_actions()
    total = upto if upto is not None else len(transitions)
    closing = upto is None
    for sent, at in enumerate(range(0, total, per_part)):
        end = min(at + per_part, total)
        final = closing and end == total
        episode: dict[str, Any] = {"transitions": transitions[at:end]}
        if final:
            episode["boundary"] = {
                "episode_id": manifest["episode_id"],
                "interaction_id": manifest["interaction_id"],
                "kind": "reset",
                "end_frame_exclusive": total,
                "authority": "browser",
                "state_hash": transitions[total - 1]["state_digest"],
            }
        socket.send_json(
            {
                "type": "command",
                "command": _command(str(sent + 3), "game.capture"),
                "payload": {
                    "episode": episode,
                    "actions": actions[at:end],
                    "first_frame": at + 1,
                    "final": final,
                    "generation": 1,
                },
            }
        )
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"


def _run(per_part: int, *, upto: int | None = None) -> tuple[InMemoryStore, str]:
    """Play the bench run through the whole platform and return the store."""
    store = InMemoryStore()
    spec = _spec()
    app = build_demo_app(store=store, gateway=Gateway(), browser_game=spec)
    client = TestClient(app)
    with client.websocket_connect("/ws") as socket:
        assert socket.receive_json()["type"] == "handshake_ack"
        assert socket.receive_json()["delivery"]["kind"] == "preload"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "consent"
        socket.send_json(
            {
                "type": "command",
                "command": _command("1", "flow.advance"),
                "payload": {"answers": {"agree": "yes"}},
            }
        )
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        assert socket.receive_json()["delivery"]["form"]["form_key"] == "survey"
        socket.send_json(
            {
                "type": "command",
                "command": _command("2", "flow.advance"),
                "payload": {"answers": {"mood": 4}},
            }
        )
        assert socket.receive_json()["ack"]["ack_kind"] == "parsed"
        assert socket.receive_json()["ack"]["ack_kind"] == "accepted"
        manifest = socket.receive_json()["delivery"]["manifest"]

        transitions = _played(manifest, spec)
        _report(socket, manifest, transitions, per_part=per_part, upto=upto)
    return store, str(manifest["episode_id"])


def _recorded(
    store: InMemoryStore, episode_id: str
) -> tuple[dict[str, Any], list[Any]]:
    """Read back what the platform recorded: the episode, and its values."""
    episode = store.load_aggregate(episode_id)
    assert isinstance(episode, dict), "the run recorded no episode at all"
    ref = recorded_trajectory(store, episode_id)
    assert ref is not None, "the episode names no recorded trajectory"
    raw = asyncio.run(store.read_artifact(ref.artifact_id))
    return episode, read_trajectory(raw)


# -- the oracle itself ----------------------------------------------------------


def test_the_environment_answers_what_the_oracle_says_it_must() -> None:
    """Before anything is recorded, the bench must be the bench.

    If this fails, every other check in this file is meaningless -- they would be
    comparing the platform against an environment that had changed underneath them.
    """
    spec = _spec()
    namespace: dict[str, Any] = {}
    exec(spec.source_bundle, namespace)
    env = GymEnv(namespace["make_env"], seed=spec.seed)
    env.reset()

    observed = [env.step(action).observation for action in bench_actions()]

    assert observed == bench_observations()
    assert observed == VECTORS["observations"], (
        "the environment no longer answers what the pinned vectors say it does"
    )


# -- the platform ---------------------------------------------------------------


def test_a_run_collected_through_the_platform_matches_the_vectors() -> None:
    """The whole check: play the bench, then read the store against the file.

    Nothing here recomputes what the answer should be. The expected values are the
    committed vectors, so this fails on any change to what is recorded or to how it
    is written down.
    """
    store, episode_id = _run(per_part=FRAMES_PER_PART)
    episode, frames = _recorded(store, episode_id)

    assert episode["frame_count"] == VECTORS["frames"]
    assert episode["verification"] == "deterministic"
    assert episode["state_hash"]["hex"] == VECTORS["final_state_hash"]
    assert episode["state_hash_chain_digest"]["hex"] == VECTORS["chain_digest"]

    # Every frame, in order, with the action that produced it and the observation
    # the environment answered. The frame numbers are checked as a sequence, so a
    # dropped or repeated frame cannot pass by having the right count.
    assert [one.frame_number for one in frames] == list(range(1, VECTORS["frames"] + 1))
    assert [one.actions[_SEAT] for one in frames] == VECTORS["actions"]
    assert [one.observations[_SEAT] for one in frames] == VECTORS["observations"]
    # And the values the environment reported alongside them.
    assert [one.rewards[_SEAT] for one in frames] == [
        float(one) for one in VECTORS["actions"]
    ]
    assert [one.info["at"] for one in frames] == [
        one[0] for one in VECTORS["observations"]
    ]

    # The per-frame digests the ledger committed are the oracle's, recomputed from
    # the values that were actually recorded rather than from the report.
    assert [
        state_hash(one.observations[_SEAT]).hex for one in frames
    ] == VECTORS["state_digests"]


def test_the_reporting_cadence_does_not_change_what_is_recorded() -> None:
    """However the run is sliced, the recorded run is the same run.

    A run split across parts is staged, indexed, read back and joined before it is
    verified. That is a lot of machinery between a participant and a record, and
    this is what says the machinery is transparent to the data: two very different
    slicings of one run must record byte-identical values.

    Reporting the whole of a run this long in a single command is not among the
    cases, because it no longer fits the transport's frame bound -- which is the
    fact that made reporting in parts necessary in the first place.
    """
    whole, first = _recorded(*_run(per_part=FRAMES_PER_PART))
    split, second = _recorded(*_run(per_part=7))

    assert whole["frame_count"] == split["frame_count"] == VECTORS["frames"]
    assert whole["state_hash_chain_digest"] == split["state_hash_chain_digest"]
    assert [one.as_row() for one in first] == [one.as_row() for one in second]
    # And both are the vectors, not merely each other.
    assert [one.observations[_SEAT] for one in first] == VECTORS["observations"]


def test_an_abandoned_run_records_an_exact_prefix() -> None:
    """A run cut short is the first N frames of the bench, and nothing else.

    Not "about N frames", and not N frames of something slightly different: the
    prefix must be the same data it would have been had the participant played on.
    """
    cut = 90
    store, episode_id = _run(per_part=FRAMES_PER_PART, upto=cut)
    episode, frames = _recorded(store, episode_id)

    assert episode["frame_count"] == cut
    assert episode["verification"] == "deterministic"
    assert episode["state_hash"]["hex"] == VECTORS["state_digests"][cut - 1]
    assert [one.frame_number for one in frames] == list(range(1, cut + 1))
    assert [one.actions[_SEAT] for one in frames] == VECTORS["actions"][:cut]
    assert [one.observations[_SEAT] for one in frames] == VECTORS["observations"][:cut]
