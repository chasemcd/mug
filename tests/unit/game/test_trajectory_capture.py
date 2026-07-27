"""A recorded run keeps what happened, and it is checkable against the ledger.

Before this, a captured episode committed one canonical event per frame, and an
event binds a digest and carries no payload -- so the ledger proved a frame happened
and nobody could say what the participant did or what it earned. A study exported
digests and no dependent variable, and a "deterministic replay" had no actions to
re-execute.

These tests drive the real loop, the real capture, and the real store: the run's
values are staged as one content-addressed artifact, the artifact re-derives the
digests the ledger recorded, a replay is driven from the artifact with no
hand-supplied actions, and an artifact that does not match the ledger is reported
rather than trusted.
"""

from __future__ import annotations

from typing import Any, cast

from mug.game.capture import capture_episode
from mug.game.env import EnvFactory, GymEnv
from mug.game.runtime import EpisodeSummary, InputState, run_episode
from mug.game.trajectory import (
    TrajectoryFrame,
    actions_for,
    read_trajectory,
    trajectory_bytes,
    verify_trajectory,
)
from mug.gateway import Gateway
from mug.kernel import (
    ArtifactRef,
    DataHandlingRef,
    Digest,
    PrincipalRef,
    WireCommandEnvelope,
    compute_digest,
)
from mug.replay import replay_episode
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_PARTICIPANT = PrincipalRef(
    kind="participant", id="participant_019b6000-0000-7000-8000-0000000000aa"
)
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_EPISODE = "episode_019b6000-0000-7000-8000-00000000000e"
_INTERACTION = "interaction_019b6000-0000-7000-8000-00000000000f"
_VISIT = "visit_019b6000-0000-7000-8000-00000000000b"
_SEAT = "player"


class _CountingEnv:
    """A tiny environment whose observation, reward, and metrics all move.

    Every recorded field has to differ per frame, or a test cannot tell a real
    recording from a repeated one.
    """

    def __init__(self) -> None:
        self._t = 0

    def reset(self, *, seed: int | None = None) -> tuple[list[float], dict[str, Any]]:
        self._t = 0
        return [0.0], {}

    def step(
        self, action: int
    ) -> tuple[list[float], float, bool, bool, dict[str, Any]]:
        self._t += 1
        return (
            [float(self._t), float(action)],
            float(action) * 2.0,
            self._t >= 3,
            False,
            {"steps": self._t},
        )


class _ReplayEnv:
    """The same environment behind the hermetic replay seam.

    The player steps a snapshot environment and hashes the whole state it returns,
    so a replay checks hidden state too, not only what a seat saw.
    """

    def __init__(self) -> None:
        self._env = _CountingEnv()

    def reset(self) -> object:
        return self._env.reset()[0]

    def step(self, action: int) -> object:
        observation, reward, terminated, truncated, info = self._env.step(action)
        return [observation, reward, terminated, truncated, info]

    def snapshot(self) -> object:
        return self._env._t  # pyright: ignore[reportPrivateUsage]

    def restore(self, state: object) -> None:
        self._env._t = int(cast("int", state))  # pyright: ignore[reportPrivateUsage]


def _now() -> str:
    return "2026-07-26T00:00:00.000000Z"


def _mint(gateway: Gateway) -> CommandContext:
    envelope = WireCommandEnvelope.model_validate(
        {
            "schema": {
                "name": "mug.command-envelope",
                "version": 0,
                "digest": _A_DIGEST.model_dump(mode="json"),
            },
            "protocol_version": "0.1.0",
            "command": {"name": "episode.capture", "version": 0},
            "request_id": "request_019b6000-0000-7000-8000-000000000001",
            "idempotency_key": "idem_0123456789abcdefghijkA",
            "target": {"id": _EPISODE},
            "payload": {
                "schema": {
                    "name": "mug.edge.payload",
                    "version": 0,
                    "digest": _A_DIGEST.model_dump(mode="json"),
                },
                "data": {"episode_id": _EPISODE},
            },
        }
    )
    return gateway.mint(envelope, principal=_PARTICIPANT, data_handling=_RESEARCH)


async def _play(gateway: Gateway) -> EpisodeSummary:
    """Run one three-frame episode through the real loop."""

    async def sink(_packet: Any) -> None:
        return None

    return await run_episode(
        GymEnv(cast("EnvFactory", _CountingEnv)),
        render=lambda surface, state: None,
        channel_key="counting",
        episode_id=_EPISODE,
        interaction_id=_INTERACTION,
        seat_key=_SEAT,
        input_state=InputState({"Go": 1}, 1),
        sink=sink,
        now=_now,
        fps=0,
        max_steps=10,
    )


async def _capture(
    store: InMemoryStore, gateway: Gateway, summary: EpisodeSummary
) -> ArtifactRef | None:
    """Capture the run and return the trajectory artifact it recorded."""
    await capture_episode(
        summary,
        visit_id=_VISIT,
        context=_mint(gateway),
        store=store,
        artifacts=store,
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=_now,
    )
    state = cast("dict[str, Any]", store.load_aggregate(_EPISODE))
    recorded = state.get("trajectory")
    return None if recorded is None else ArtifactRef.model_validate(recorded)


async def test_the_loop_records_what_happened_on_every_frame() -> None:
    """Actions, observations, rewards, flags, and metrics all reach the summary."""
    summary = await _play(Gateway())

    assert [frame.frame_number for frame in summary.trajectory] == [1, 2, 3]
    first = summary.trajectory[0]
    assert first.actions == {_SEAT: 1}
    assert first.observations == {_SEAT: [1.0, 1.0]}
    assert first.rewards == {_SEAT: 2.0}
    # The environment's own metrics are kept, not dropped on the floor.
    assert first.info == {"steps": 1}
    # The run ended on the environment's terminal, and the record says so.
    assert summary.trajectory[-1].terminated is True


async def test_the_capture_stages_the_values_and_the_episode_names_them() -> None:
    """A study reads its data from the episode, with no side channel."""
    store, gateway = InMemoryStore(), Gateway()
    summary = await _play(gateway)

    ref = await _capture(store, gateway, summary)

    assert ref is not None
    assert ref.media_type == "application/x-ndjson"
    frames = read_trajectory(await store.read_artifact(ref.artifact_id))
    assert [frame.rewards[_SEAT] for frame in frames] == [2.0, 2.0, 2.0]
    assert [frame.info["steps"] for frame in frames] == [1, 2, 3]


async def test_the_recorded_values_re_derive_the_ledger_digests() -> None:
    """The artifact is evidence because it checks against the canonical stream."""
    store, gateway = InMemoryStore(), Gateway()
    summary = await _play(gateway)
    ref = await _capture(store, gateway, summary)
    assert ref is not None

    frames = read_trajectory(await store.read_artifact(ref.artifact_id))

    assert verify_trajectory(summary.transitions, frames) == []
    # The binding is the digest the transition already committed to.
    assert compute_digest(frames[0].actions) == summary.transitions[0].action_digest
    assert compute_digest(frames[0].observations) == summary.transitions[0].state_digest


async def test_a_trajectory_that_is_not_the_run_is_reported() -> None:
    """Values that disagree with the ledger are named, never quietly accepted."""
    summary = await _play(Gateway())
    frames = read_trajectory(trajectory_bytes(summary.trajectory))
    tampered = [
        frames[0],
        TrajectoryFrame(
            frame_number=frames[1].frame_number,
            actions={_SEAT: 99},
            observations=frames[1].observations,
            rewards=frames[1].rewards,
            terminated=frames[1].terminated,
            truncated=frames[1].truncated,
            info=frames[1].info,
        ),
        frames[2],
    ]

    assert verify_trajectory(summary.transitions, tampered) == [2]


async def test_a_shorter_trajectory_reports_the_frames_it_cannot_account_for() -> None:
    """A partial record is a gap, not a pass."""
    summary = await _play(Gateway())
    frames = read_trajectory(trajectory_bytes(summary.trajectory))

    assert verify_trajectory(summary.transitions, frames[:1]) == [2, 3]


async def test_a_recorded_run_replays_with_no_hand_supplied_actions() -> None:
    """The recorded actions drive the replay, which is what makes a run replayable.

    The player used to take its actions from its caller, and the only callers were
    tests, because nothing had ever written them down.
    """
    store, gateway = InMemoryStore(), Gateway()
    summary = await _play(gateway)
    ref = await _capture(store, gateway, summary)
    assert ref is not None
    frames = read_trajectory(await store.read_artifact(ref.artifact_id))

    run = replay_episode(
        env=_ReplayEnv(),
        actions=actions_for(frames, _SEAT),
        interaction_id=_INTERACTION,
        episode_id=_EPISODE,
    )

    assert len(run.checks) == 3
    assert run.validation.external_calls_made is False


async def test_a_trajectory_serializes_to_the_same_bytes_every_time() -> None:
    """One recorded run is one artifact digest, so a bundle is reproducible."""
    summary = await _play(Gateway())

    once = trajectory_bytes(summary.trajectory)
    twice = trajectory_bytes(read_trajectory(once))

    assert once == twice
