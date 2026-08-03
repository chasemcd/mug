"""Sealing decides what happened, for a run that ended and one that was left.

The claim this file makes is the reason the whole part-reporting design exists: a
participant who stops playing part-way through leaves the frames they played, and
they are recorded to the same standard as a run that finished. The server
re-executes whatever prefix arrived and matches every state hash, so nothing is
recorded on a client's word alone.

It also holds the line that must not move: a run whose reported hashes do not match
the re-execution records nothing, abandoned or not.
"""

from __future__ import annotations

from typing import Any

from mug.game.browser import BrowserGameSpec
from mug.game.capture_parts import (
    ClaimedPart,
    RunIdentity,
    progress_aggregate_id,
    read_progress,
    record_part,
)
from mug.game.determinism import state_hash
from mug.game.env import GymEnv
from mug.gateway import Gateway
from mug.kernel import PrincipalRef, WireCommandEnvelope
from mug.kernel.privacy import DataHandlingRef
from mug.replay.seal import seal_abandoned, seal_run
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_EPISODE = "episode_" + _UUID.format(0xB00)
_INTERACTION = "interaction_" + _UUID.format(0xB01)
_VISIT = "visit_" + _UUID.format(0xB02)
_PARTICIPANT = PrincipalRef(kind="participant", id="participant_" + _UUID.format(0xB03))
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_A_DIGEST = {"algorithm": "sha-256", "hex": "a" * 64}

# A tiny environment whose observation follows only from the actions, so a test can
# reason about the run without an environment package.
_BUNDLE = """
class _Ramp:
    def reset(self, seed=None):
        self.at = 0.0
        return [self.at], {}

    def step(self, action):
        self.at += float(action) + 1.0
        return [self.at], 0.0, False, False, {}


def make_env():
    return _Ramp()
"""

_RUN = RunIdentity(
    episode_id=_EPISODE,
    interaction_id=_INTERACTION,
    channel_key="ramp",
    visit_id=_VISIT,
    seat_key="agent-0",
    activity_key="round-one",
    generation=1,
)


def _spec(**extra: Any) -> BrowserGameSpec:
    return BrowserGameSpec(
        channel_key="ramp",
        source_bundle=_BUNDLE,
        requires=(),
        action_bindings={"ArrowRight": 1},
        default_action=1,
        seed=7,
        max_steps=600,
        **extra,
    )


class _Client:
    """A participant's browser, playing honestly and reporting as it goes."""

    def __init__(self, spec: BrowserGameSpec) -> None:
        self.spec = spec
        self.gateway = Gateway()
        self.store = InMemoryStore()
        self._sent = 0
        namespace: dict[str, Any] = {}
        exec(spec.source_bundle, namespace)
        self._env = GymEnv(namespace["make_env"], seed=spec.seed)
        self._env.reset()
        self._frame = 0

    def context(self, target: str, tag: str) -> Any:
        self._sent += 1
        envelope = WireCommandEnvelope.model_validate(
            {
                "schema": {
                    "name": "mug.command-envelope",
                    "version": 0,
                    "digest": _A_DIGEST,
                },
                "protocol_version": "0.1.0",
                "command": {"name": "episode.report_part", "version": 0},
                "request_id": "request_" + _UUID.format(1),
                # The kernel wants 21 body characters and a terminator, so the tag
                # and the counter are padded into exactly that.
                "idempotency_key": (
                    "idem_" + f"{tag}{self._sent}".ljust(21, "0")[:21] + "A"
                ),
                "target": {"id": target},
                "payload": {
                    "schema": {
                        "name": "mug.edge.payload",
                        "version": 0,
                        "digest": _A_DIGEST,
                    },
                    "data": {"episode_id": _EPISODE, "n": self._sent},
                },
            }
        )
        return self.gateway.mint(
            envelope, principal=_PARTICIPANT, data_handling=_RESEARCH
        )

    def _play(self, count: int, *, forge: bool = False) -> ClaimedPart:
        transitions: list[dict[str, Any]] = []
        actions: list[int] = []
        first = self._frame + 1
        for _ in range(count):
            action = 1
            state = self._env.step(action)
            self._frame += 1
            digest = state_hash(state.observation).model_dump(mode="json")
            transitions.append(
                {
                    "interaction_id": _INTERACTION,
                    "channel_key": "ramp",
                    "episode_id": _EPISODE,
                    "frame_number": self._frame,
                    "action_digest": state_hash(action).model_dump(mode="json"),
                    "state_digest": _A_DIGEST if forge else digest,
                    "authority": "browser",
                    "applied_decisions": [],
                    "recorded_at": "2026-07-28T00:00:00.000000Z",
                }
            )
            actions.append(action)
        return ClaimedPart(
            first_frame=first,
            transitions=transitions,
            actions=actions,
            partner_actions=[],
            final=False,
        )

    async def report(self, count: int, *, forge: bool = False) -> None:
        part = self._play(count, forge=forge)
        await record_part(
            part,
            run=_RUN,
            context=self.context(progress_aggregate_id(_EPISODE), "part"),
            store=self.store,
            artifacts=self.store,
            new_artifact_id=lambda: self.gateway.new_id("artifact"),
            new_upload_id=lambda: self.gateway.new_id("upload"),
            now=lambda: "2026-07-28T00:00:00.000000Z",
        )

    async def seal(self) -> Any:
        progress = read_progress(self.store, _EPISODE)
        assert progress is not None
        return await seal_run(
            progress,
            spec=self.spec,
            capture_context=self.context(_EPISODE, "cap"),
            sealed_context=self.context(progress_aggregate_id(_EPISODE), "seal"),
            epoch_id=self.gateway.new_id("prodepoch"),
            store=self.store,
            artifacts=self.store,
            new_artifact_id=lambda: self.gateway.new_id("artifact"),
            new_upload_id=lambda: self.gateway.new_id("upload"),
            now=lambda: "2026-07-28T00:00:00.000000Z",
        )


async def test_a_participant_who_leaves_part_way_through_is_recorded() -> None:
    """Four hundred frames of six hundred are four hundred frames.

    Nobody closed the episode. The server writes the boundary at the last frame that
    arrived, re-executes the prefix, and matches every hash -- so the run is recorded
    as a verified episode rather than discarded for being incomplete.
    """
    client = _Client(_spec())
    for _ in range(4):
        await client.report(100)

    outcome = await client.seal()

    assert outcome.recorded
    assert outcome.frames == 400
    assert not outcome.closed
    assert outcome.verification == "deterministic"

    episode = client.store.load_aggregate(_EPISODE)
    assert isinstance(episode, dict)
    assert episode["frame_count"] == 400
    assert episode["verification"] == "deterministic"
    # The values exist too: what is recorded is the server's own re-execution of
    # the frames that were really played.
    assert episode["trajectory"]


async def test_a_run_the_client_closed_is_sealed_at_its_own_boundary() -> None:
    """A finished round is recorded exactly as one end-of-round report always was."""
    client = _Client(_spec())
    await client.report(100)
    await client.report(50)
    progress = read_progress(client.store, _EPISODE)
    assert progress is not None

    outcome = await client.seal()

    assert outcome.recorded
    assert outcome.frames == 150
    assert outcome.verification == "deterministic"


async def test_a_forged_prefix_records_nothing() -> None:
    """The line that must not move: a run that does not match records nothing.

    Sealing an incomplete run must not become a way to launder one. The prefix is
    re-executed exactly as a whole run is.
    """
    client = _Client(_spec())
    await client.report(100)
    await client.report(100, forge=True)

    outcome = await client.seal()

    assert not outcome.recorded
    assert outcome.reason is not None
    assert client.store.load_aggregate(_EPISODE) is None


async def test_a_sealed_run_is_not_sealed_twice() -> None:
    """Two sweeps must not record one run as two episodes."""
    client = _Client(_spec())
    await client.report(100)

    first = await client.seal()
    second = await client.seal()

    assert first.recorded
    assert not second.recorded
    assert second.reason == "already-sealed"


async def test_a_study_that_cannot_be_re_executed_still_records_its_prefix() -> None:
    """A declared visual fallback is honoured when sealing a partial run too."""
    client = _Client(_spec(verification="visual-fallback"))
    await client.report(100, forge=True)

    outcome = await client.seal()

    assert outcome.recorded
    assert outcome.verification == "visual-fallback"
    assert outcome.frames == 100


async def test_a_process_that_died_mid_round_loses_nothing() -> None:
    """The sweep is the backstop, and it is why the claims are staged durably.

    A closing connection runs a hook. A process that is killed runs nothing at all,
    so the parts must be recoverable by something that never saw the participant --
    which is exactly what a restart, or a second replica, is.
    """
    client = _Client(_spec())
    await client.report(120)

    # Nothing sealed it: no hook ran. A later process sweeps the store it shares.
    outcomes = await seal_abandoned(
        spec=client.spec,
        before="2026-07-29T00:00:00.000000Z",
        store=client.store,
        artifacts=client.store,
        mint=lambda target, purpose: client.context(target, purpose[:4]),
        new_id=client.gateway.new_id,
        now=lambda: "2026-07-28T00:00:00.000000Z",
    )

    assert [one.recorded for one in outcomes] == [True]
    assert outcomes[0].frames == 120
    recorded = client.store.load_aggregate(_EPISODE)
    assert isinstance(recorded, dict)
    assert recorded["frame_count"] == 120

    # And a second sweep records nothing further: one run is one episode.
    again = await seal_abandoned(
        spec=client.spec,
        before="2026-07-29T00:00:00.000000Z",
        store=client.store,
        artifacts=client.store,
        mint=lambda target, purpose: client.context(target, purpose[:4]),
        new_id=client.gateway.new_id,
        now=lambda: "2026-07-28T00:00:00.000000Z",
    )
    assert again == []


async def test_a_run_still_being_played_is_left_alone() -> None:
    """A sweep must not take a round away from someone in the middle of it."""
    client = _Client(_spec())
    await client.report(40)

    outcomes = await seal_abandoned(
        spec=client.spec,
        # Everything reported at or after this instant is still live.
        before="2026-07-27T00:00:00.000000Z",
        store=client.store,
        artifacts=client.store,
        mint=lambda target, purpose: client.context(target, purpose[:4]),
        new_id=client.gateway.new_id,
        now=lambda: "2026-07-28T00:00:00.000000Z",
    )

    assert outcomes == []
    assert client.store.load_aggregate(_EPISODE) is None
