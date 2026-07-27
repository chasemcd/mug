"""Assemble and validate an API-16 replay bundle from a recorded interaction.

A replay bundle is the durable, self-contained record of one interaction that a
later run replays. It is pinned by a ``ReplayManifest`` (``mug.replay.types``): the
capabilities it offers, the artifacts it carries (the canonical event streams, and
the decision tape when a model drove a seat), the schema bundle it validates
against, and an integrity digest that binds the whole set.

This module builds that bundle from recorded data alone, so it runs at export or
replay time, never during the interaction. It reads each canonical stream through
``mug.runtime.read_ledger``, serializes it to newline-delimited JSON (the one
export format, D13-1), and persists it as a content-addressed artifact through the
object store (``mug.storage.ArtifactStore``). The decision tape, when present, is
persisted the same way. The manifest names every artifact by its digest, so a
tampered or divergent artifact does not match and the bundle is refused.

The bundle is deterministic by construction: the serialization sorts keys and the
digests come from the bytes, so the same interaction assembles a byte-identical
bundle every time. ``validate_replay_bundle`` re-reads every artifact and
recomputes its digest, so it proves the bundle replays byte-identically and refuses
one whose bytes have diverged from the manifest.

This module assembles a server-or-browser bundle. By default the scope is
canonical-only; pass an ``ExperiencedInput`` to widen it to the client-side
experienced stream and its lineage back to the canonical events. The peer-to-peer
scope lives in ``mug.replay.p2p`` (a p2p bundle closes over the mesh evidence, not
one canonical stream), so this builder fails closed on a ``p2p`` execution mode.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from mug.kernel import (
    ArtifactRef,
    DataHandlingRef,
    SchemaRef,
    compute_digest,
)
from mug.replay.types import (
    CapabilityLevels,
    DecisionTape,
    DeterminismDeclaration,
    ExecutionMode,
    ExperiencedFrameLineageEntry,
    ExperiencedStreamReplay,
    ReplayBundleValidation,
    ReplayManifest,
    ReproductionScope,
    replay_schema,
)
from mug.runtime import read_ledger
from mug.storage import (
    ArtifactStore,
    Store,
    digest_of,
    json_bytes,
    jsonl_bytes,
    stage_artifact,
)

# The media types the bundle persists: streams as newline-delimited JSON, the
# manifest sidecars (the tape, the schema bundle) as plain JSON.
_NDJSON = "application/x-ndjson"
_JSON = "application/json"


@dataclass(frozen=True)
class ExperiencedInput:
    """The client-side experienced stream and its lineage back to the canonical.

    A browser or p2p participant sees a stream of frames -- some delivered, some
    speculative, some later corrected or skipped -- that is not the canonical
    event order. This input carries that experienced stream so a bundle reproduces
    what the participant actually saw, joined to the canonical events it derives
    from. ``frames`` is the ordered experienced frame records the bundle persists;
    ``frames_schema`` pins their schema; ``canonical_event_ids`` names every
    canonical event the lineage refers to; and ``lineage`` joins each experienced
    frame to its canonical origin (a corrected frame must name a known canonical
    event, an invariant the manifest enforces).
    """

    frames: Sequence[dict[str, object]]
    frames_schema: SchemaRef
    canonical_event_ids: Sequence[str]
    lineage: Sequence[ExperiencedFrameLineageEntry]


@dataclass(frozen=True)
class ReplayBundle:
    """One assembled replay bundle: its manifest, its artifacts, and its verdict.

    ``manifest`` pins the bundle. ``validation`` is the fresh-build verdict (valid
    by construction, no external calls, nothing modified). ``decision_tape`` is the
    model-and-bot tape when a model drove a seat, else ``None``. ``stream_artifacts``
    maps each canonical stream id to the artifact that holds its events, and
    ``event_count`` is the total canonical events the bundle carries.
    """

    manifest: ReplayManifest
    validation: ReplayBundleValidation
    decision_tape: DecisionTape | None
    stream_artifacts: dict[str, ArtifactRef]
    event_count: int


async def build_replay_bundle(
    *,
    store: Store,
    artifacts: ArtifactStore,
    interaction_id: str,
    stream_ids: Sequence[str],
    new_artifact_id: Callable[[], str],
    new_upload_id: Callable[[], str],
    now: Callable[[], str],
    data_handling: DataHandlingRef,
    execution_mode: ExecutionMode = "server",
    decision_tape: DecisionTape | None = None,
    determinism: DeterminismDeclaration | None = None,
    experienced: ExperiencedInput | None = None,
    trajectory: ArtifactRef | None = None,
    render: ArtifactRef | None = None,
) -> ReplayBundle:
    """Assemble one replay bundle from an interaction's canonical streams.

    Each stream in ``stream_ids`` is read, serialized to newline-delimited JSON, and
    persisted as an artifact; the decision tape and the schema bundle are persisted
    the same way. The manifest names every artifact by digest and binds the set with
    an integrity digest. The bundle is deterministic: the same recorded data yields a
    byte-identical bundle. ``determinism`` set marks a byte-deterministic replay and
    turns on the deterministic capability; unset leaves a visual-only bundle.

    ``experienced`` set widens the scope to ``canonical-and-experienced``: the
    client-side experienced stream is persisted as an artifact and the manifest
    carries its lineage back to the canonical events, so the bundle reproduces what
    the participant saw, not only the canonical order. Unset leaves a canonical-only
    bundle.

    The p2p scope is deferred here, so a ``p2p`` mode is refused; ``mug.replay.p2p``
    assembles a p2p bundle from the mesh evidence a p2p replay must close over.
    """
    if execution_mode == "p2p":
        raise ValueError(
            "p2p replay-bundle assembly lives in mug.replay.p2p (needs p2p evidence)"
        )

    stream_artifacts: dict[str, ArtifactRef] = {}
    refs: list[ArtifactRef] = []
    event_count = 0
    for stream_id in stream_ids:
        events = read_ledger(store, stream_id)
        event_count += len(events)
        ref = await stage_artifact(
            artifacts,
            data=_jsonl(
                [event.model_dump(mode="json", exclude_none=True) for event in events]
            ),
            media_type=_NDJSON,
            new_artifact_id=new_artifact_id,
            new_upload_id=new_upload_id,
            now=now,
            data_handling=data_handling,
        )
        stream_artifacts[stream_id] = ref
        refs.append(ref)

    if decision_tape is not None:
        tape_data = json_bytes(
            decision_tape.model_dump(mode="json", exclude_none=True)
        )
        refs.append(
            await stage_artifact(
                artifacts,
                data=tape_data,
                media_type=_JSON,
                new_artifact_id=new_artifact_id,
                new_upload_id=new_upload_id,
                now=now,
                data_handling=data_handling,
            )
        )

    experienced_replay: ExperiencedStreamReplay | None = None
    if experienced is not None:
        experienced_ref = await stage_artifact(
            artifacts,
            data=_jsonl(list(experienced.frames)),
            media_type=_NDJSON,
            new_artifact_id=new_artifact_id,
            new_upload_id=new_upload_id,
            now=now,
            data_handling=data_handling,
        )
        refs.append(experienced_ref)
        experienced_replay = ExperiencedStreamReplay(
            experienced_frames_schema=experienced.frames_schema,
            experienced_stream=experienced_ref,
            canonical_event_ids=list(experienced.canonical_event_ids),
            experienced_lineage=list(experienced.lineage),
        )

    schema_bundle = await stage_artifact(
        artifacts,
        data=json_bytes(
            {"family": "mug.api-16", "bundle_digest": replay_schema().bundle_digest}
        ),
        media_type=_JSON,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=now,
        data_handling=data_handling,
    )
    refs.append(schema_bundle)

    for recorded in (trajectory, render):
        if recorded is not None:
            refs.append(recorded)

    # The capabilities the bundle can actually deliver, from the artifacts it
    # carries. A deterministic replay steps the recorded actions; a visual replay
    # draws the recorded frames. Neither is a promise the manifest may make alone.
    capabilities = CapabilityLevels(
        visual=render is not None or trajectory is not None,
        deterministic=determinism is not None and trajectory is not None,
    )
    if not (capabilities.visual or capabilities.deterministic):
        # The frozen manifest has always required a replay to declare a capability.
        # Refusing here says which recorded evidence is missing, instead of failing
        # inside the model or -- as this did before -- asserting a visual capability
        # with no frames behind it.
        raise ValueError(
            "a replay bundle needs a recorded trajectory or a render stream; "
            "this run recorded neither, so no replay is possible"
        )

    scope: ReproductionScope = (
        "canonical-and-experienced" if experienced is not None else "canonical-only"
    )
    integrity = compute_digest(
        {
            "interaction_id": interaction_id,
            "execution_mode": execution_mode,
            "reproduction_scope": scope,
            "artifacts": sorted(ref.digest.hex for ref in refs),
            "schema_bundle": schema_bundle.digest.hex,
            "deterministic": capabilities.deterministic,
            "visual": capabilities.visual,
        }
    )
    manifest = ReplayManifest(
        interaction_id=interaction_id,
        execution_mode=execution_mode,
        capability_levels=capabilities,
        reproduction_scope=scope,
        experienced_stream_replay=experienced_replay,
        determinism=determinism,
        artifact_refs=refs,
        schema_bundle=schema_bundle,
        integrity_digest=integrity,
    )
    validation = ReplayBundleValidation(
        interaction_id=interaction_id,
        valid=True,
        external_calls_made=False,
        modified_artifact_ids=[],
        verification="deterministic" if determinism is not None else "visual-fallback",
    )
    return ReplayBundle(
        manifest=manifest,
        validation=validation,
        decision_tape=decision_tape,
        stream_artifacts=stream_artifacts,
        event_count=event_count,
    )


async def validate_replay_bundle(
    *, artifacts: ArtifactStore, manifest: ReplayManifest
) -> ReplayBundleValidation:
    """Re-read every artifact and confirm its bytes match the manifest's digest.

    The bundle replays byte-identically only if every artifact's stored bytes still
    hash to the digest the manifest names. An artifact whose bytes have diverged is
    reported in ``modified_artifact_ids`` and makes the bundle invalid, so a tampered
    or corrupted bundle is refused rather than replayed. The read makes no external
    call, so ``external_calls_made`` is always false.
    """
    modified: list[str] = []
    seen: set[str] = set()
    for ref in [*manifest.artifact_refs, manifest.schema_bundle]:
        if ref.artifact_id in seen:
            continue
        seen.add(ref.artifact_id)
        data = await artifacts.read_artifact(ref.artifact_id)
        if digest_of(data).hex != ref.digest.hex:
            modified.append(ref.artifact_id)
    return ReplayBundleValidation(
        interaction_id=manifest.interaction_id,
        valid=not modified,
        external_calls_made=False,
        modified_artifact_ids=modified,
        verification="deterministic"
        if manifest.capability_levels.deterministic
        else "visual-fallback",
    )


_jsonl = jsonl_bytes


__all__ = [
    "ExperiencedInput",
    "ReplayBundle",
    "build_replay_bundle",
    "validate_replay_bundle",
]
