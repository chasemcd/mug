"""``build_replay_bundle`` assembles a durable, self-verifying replay bundle.

These tests capture one episode into the canonical ledger, then assemble a replay
bundle over its stream through the real gateway, runtime spine, and in-memory object
store. They prove: the manifest pins every artifact by digest and validates against
the frozen API-16 schema; the bundle carries the model decision tape when a model
drove a seat; ``validate_replay_bundle`` confirms a fresh bundle replays
byte-identically; a bundle whose stored bytes diverge from the manifest is refused;
and the deterministic capability turns on only when a determinism basis is declared.
"""

from __future__ import annotations

from typing import Any, cast

from mug.game.capture import capture_episode
from mug.game.env import EnvFactory, GymEnv
from mug.game.runtime import EpisodeSummary, InputState, run_episode
from mug.gateway import Gateway
from mug.kernel import (
    DataHandlingRef,
    Digest,
    PrincipalRef,
    SchemaRef,
    StreamPosition,
    WireCommandEnvelope,
)
from mug.providers import ModelCallResult, ProviderResponse, Usage
from mug.replay import (
    ExperiencedInput,
    build_decision_tape,
    build_replay_bundle,
    replay_schema,
    validate_replay_bundle,
)
from mug.replay.types import (
    DeterminismDeclaration,
    EnvHooks,
    ExperiencedFrameLineageEntry,
    SnapshotCoverage,
)
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
_UUID = "019b6000-0000-7000-8000-{:012x}"


class _FakeEnv:
    def __init__(self) -> None:
        self._t = 0

    def reset(self, *, seed: int | None = None) -> tuple[list[float], dict[str, Any]]:
        self._t = 0
        return [0.0], {}

    def step(
        self, action: int
    ) -> tuple[list[float], float, bool, bool, dict[str, Any]]:
        self._t += 1
        return [float(self._t)], -1.0, self._t >= 3, False, {}


def _now() -> str:
    return "2026-07-21T00:00:00.000000Z"


def _mint(gateway: Gateway) -> CommandContext:
    envelope = {
        "schema": {
            "name": "mug.command-envelope",
            "version": 0,
            "digest": _A_DIGEST.model_dump(mode="json"),
        },
        "protocol_version": "0.1.0",
        "command": {"name": "episode.capture", "version": 0},
        "request_id": "request_019b6000-0000-7000-8000-000000000001",
        "idempotency_key": "idem_" + "cap".ljust(21, "0") + "A",
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
    return gateway.mint(
        WireCommandEnvelope.model_validate(envelope),
        principal=_PARTICIPANT,
        data_handling=_RESEARCH,
    )


async def _capture(store: InMemoryStore, gateway: Gateway) -> str:
    """Capture a three-frame episode and return its canonical stream id."""
    inputs = InputState({"Go": 1}, 0)

    async def sink(_packet: Any) -> None:
        return None

    summary: EpisodeSummary = await run_episode(
        GymEnv(cast("EnvFactory", _FakeEnv)),
        render=lambda surface, state: None,
        channel_key="fake-game",
        episode_id=_EPISODE,
        interaction_id=_INTERACTION,
        seat_key="player",
        input_state=inputs,
        sink=sink,
        now=_now,
        fps=0,
        max_steps=10,
    )
    context = _mint(gateway)
    await capture_episode(summary, visit_id=_VISIT, context=context, store=store)
    return context.stream_id


def _tape() -> Any:
    modelcall_id = "modelcall_" + _UUID.format(0xC01)
    response = ProviderResponse(
        modelcall_id=modelcall_id,
        generation_id="generation_" + _UUID.format(1),
        outcome="completed",
        resolved_model="fake",
        usage=Usage(input_tokens=1, output_tokens=1, cost_micros=1),
        output_digest=Digest(algorithm="sha-256", hex="c" * 64),
        completed_at="2026-07-22T00:00:00.000000Z",
    )
    result = ModelCallResult(
        modelcall_id=modelcall_id, request=None, response=response, error=None
    )
    return build_decision_tape(interaction_id=_INTERACTION, results=[result])


def _determinism() -> DeterminismDeclaration:
    return DeterminismDeclaration(
        env_hooks=EnvHooks(snapshot_restore=True, state_hash=True),
        snapshot_coverage=SnapshotCoverage(
            environment_state=True,
            platform_state=True,
            python_random_state=True,
            numpy_random_state=True,
            mug_javascript_rng_state=True,
        ),
        state_hash_chain_digest=Digest(algorithm="sha-256", hex="d" * 64),
    )


async def test_a_fresh_bundle_pins_its_artifacts_and_validates() -> None:
    """The manifest names the stream and tape by digest and re-reads as valid."""
    store, gateway = InMemoryStore(), Gateway()
    stream_id = await _capture(store, gateway)

    bundle = await build_replay_bundle(
        store=store,
        artifacts=store,
        interaction_id=_INTERACTION,
        stream_ids=[stream_id],
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=_now,
        data_handling=_RESEARCH,
        decision_tape=_tape(),
    )

    # The bundle carries the stream's four canonical events plus the tape artifact.
    assert bundle.event_count == 4
    assert stream_id in bundle.stream_artifacts
    # stream artifact + tape artifact + schema bundle are all pinned in the manifest.
    assert len(bundle.manifest.artifact_refs) == 3
    assert bundle.manifest.reproduction_scope == "canonical-only"
    # The manifest validates against the frozen API-16 schema.
    instance = bundle.manifest.model_dump(mode="json", exclude_none=True)
    assert replay_schema().is_valid("ReplayManifest", instance)
    # Re-reading every artifact confirms the bundle replays byte-identically.
    verdict = await validate_replay_bundle(artifacts=store, manifest=bundle.manifest)
    assert verdict.valid is True
    assert verdict.modified_artifact_ids == []


async def test_a_divergent_bundle_is_refused() -> None:
    """A stored artifact whose bytes diverge from the manifest makes it invalid."""
    store, gateway = InMemoryStore(), Gateway()
    stream_id = await _capture(store, gateway)
    bundle = await build_replay_bundle(
        store=store,
        artifacts=store,
        interaction_id=_INTERACTION,
        stream_ids=[stream_id],
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=_now,
        data_handling=_RESEARCH,
    )
    tampered = bundle.stream_artifacts[stream_id].artifact_id
    # Diverge the stored bytes behind the pinned digest, as corruption would.
    store._objects[tampered] = b"tampered\n"  # pyright: ignore[reportPrivateUsage]

    verdict = await validate_replay_bundle(artifacts=store, manifest=bundle.manifest)

    assert verdict.valid is False
    assert verdict.modified_artifact_ids == [tampered]


async def test_the_deterministic_capability_needs_a_declared_basis() -> None:
    """Without a determinism basis a bundle is visual-only; with one it is not."""
    store, gateway = InMemoryStore(), Gateway()
    stream_id = await _capture(store, gateway)

    visual = await build_replay_bundle(
        store=store,
        artifacts=store,
        interaction_id=_INTERACTION,
        stream_ids=[stream_id],
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=_now,
        data_handling=_RESEARCH,
    )
    deterministic = await build_replay_bundle(
        store=store,
        artifacts=store,
        interaction_id=_INTERACTION,
        stream_ids=[stream_id],
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=_now,
        data_handling=_RESEARCH,
        determinism=_determinism(),
    )

    assert visual.manifest.capability_levels.deterministic is False
    assert visual.manifest.determinism is None
    assert visual.validation.verification == "visual-fallback"
    assert deterministic.manifest.capability_levels.deterministic is True
    assert deterministic.manifest.determinism is not None
    assert deterministic.validation.verification == "deterministic"


def _experienced() -> ExperiencedInput:
    """Build a client-side experienced stream with a delivered-then-corrected frame."""
    stream = "stream_" + _UUID.format(0xF01)
    event_one = "event_" + _UUID.format(0xE01)
    event_two = "event_" + _UUID.format(0xE02)
    frames_schema = SchemaRef(name="mug.api-10.evidence", version=0, digest=_A_DIGEST)
    lineage = [
        ExperiencedFrameLineageEntry(
            stream_position=StreamPosition(stream_id=stream, sequence=1),
            delivery_kind="delivered",
            canonical_event_id=event_one,
        ),
        ExperiencedFrameLineageEntry(
            stream_position=StreamPosition(stream_id=stream, sequence=2),
            delivery_kind="speculative",
        ),
        ExperiencedFrameLineageEntry(
            stream_position=StreamPosition(stream_id=stream, sequence=3),
            delivery_kind="corrected",
            canonical_event_id=event_two,
            supersedes_experienced_position=StreamPosition(
                stream_id=stream, sequence=2
            ),
        ),
    ]
    return ExperiencedInput(
        frames=[{"frame": 1}, {"frame": 2}, {"frame": 3}],
        frames_schema=frames_schema,
        canonical_event_ids=[event_one, event_two],
        lineage=lineage,
    )


async def test_an_experienced_bundle_carries_its_stream_and_lineage() -> None:
    """An experienced input widens the scope and pins the experienced stream."""
    store, gateway = InMemoryStore(), Gateway()
    stream_id = await _capture(store, gateway)

    bundle = await build_replay_bundle(
        store=store,
        artifacts=store,
        interaction_id=_INTERACTION,
        stream_ids=[stream_id],
        new_artifact_id=lambda: gateway.new_id("artifact"),
        new_upload_id=lambda: gateway.new_id("upload"),
        now=_now,
        data_handling=_RESEARCH,
        experienced=_experienced(),
    )

    manifest = bundle.manifest
    assert manifest.reproduction_scope == "canonical-and-experienced"
    replay = manifest.experienced_stream_replay
    assert replay is not None
    # The experienced stream artifact is pinned in the manifest's artifact set.
    assert replay.experienced_stream in manifest.artifact_refs
    assert len(replay.experienced_lineage) == 3
    # The manifest validates against the frozen API-16 schema.
    instance = manifest.model_dump(mode="json", exclude_none=True)
    assert replay_schema().is_valid("ReplayManifest", instance)
    # The whole bundle, experienced stream included, replays byte-identically.
    verdict = await validate_replay_bundle(artifacts=store, manifest=manifest)
    assert verdict.valid is True


async def test_p2p_mode_is_refused_until_its_evidence_is_built() -> None:
    """A p2p bundle needs its evidence, so the assembler fails closed on that mode."""
    store, gateway = InMemoryStore(), Gateway()
    stream_id = await _capture(store, gateway)

    try:
        await build_replay_bundle(
            store=store,
            artifacts=store,
            interaction_id=_INTERACTION,
            stream_ids=[stream_id],
            new_artifact_id=lambda: gateway.new_id("artifact"),
            new_upload_id=lambda: gateway.new_id("upload"),
            now=_now,
            data_handling=_RESEARCH,
            execution_mode="p2p",
        )
    except ValueError as error:
        assert "p2p" in str(error)
    else:  # pragma: no cover - the call must raise
        raise AssertionError("p2p mode must be refused")
