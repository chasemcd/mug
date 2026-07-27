"""The full dataset export reads a whole study ledger and splits it by kind.

This drives the real flow, capture, and preference services over one shared
store, then exports the whole dataset. The export produces one ``ExportBundle``
and ``LineageRecord`` per non-empty dataset kind: ``events`` (the universal
spine), ``trajectories`` (the game episode), and ``preferences`` (the
annotation). A kind with no event -- here ``conversations`` -- yields no bundle.

The tests prove the properties the definition of done names: the bundles carry
only canonical event envelopes (a payload digest per row, never a raw value),
each bundle's lineage names its source streams, and the export is reproducible
-- the same ledger and the same injected ids produce byte-identical artifacts
and identical digests.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from typing import Any, cast

from mug.content import (
    AdvanceFlowCommand,
    MaterializeFlowCommand,
    advance_flow,
    demo_study,
    materialize_flow,
)
from mug.export import (
    DATASET_KINDS,
    collect_dataset_rows,
    export_study_dataset,
)
from mug.export.types import GitProvenanceRef
from mug.game.capture import capture_episode
from mug.game.env import EnvFactory, GymEnv
from mug.game.runtime import EpisodeSummary, InputState, run_episode
from mug.game.surface import Surface
from mug.gateway import Gateway
from mug.kernel import (
    DataHandlingRef,
    Digest,
    PrincipalRef,
    WireCommandEnvelope,
    compute_digest,
)
from mug.kernel.refs import StudyVersionRef
from mug.preferences import PreferenceService
from mug.preferences.runtime import response_id_for
from mug.preferences.types import ComparisonTask, PreferenceProtocol
from mug.runtime import CommandContext
from mug.storage import InMemoryStore

_UUID = "019b6000-0000-7000-8000-{:012x}"
_PARTICIPANT = PrincipalRef(
    kind="participant", id="participant_019b6000-0000-7000-8000-0000000000aa"
)
_RESEARCH = DataHandlingRef(privacy_labels=["research"])
_A_DIGEST = Digest(algorithm="sha-256", hex="a" * 64)
_FLOW_ID = "visitplan_019b6000-0000-7000-8000-00000000000a"
_VISIT_ID = "visit_019b6000-0000-7000-8000-00000000000b"
_EPISODE = "episode_019b6000-0000-7000-8000-00000000000e"
_ASSIGNMENT = "prefassign_019b6000-0000-7000-8000-000000000101"
_STUDY = StudyVersionRef(
    study_id="study_019b6000-0000-7000-8000-000000000001",
    study_version_id="studyver_019b6000-0000-7000-8000-000000000010",
    version_number=2,
    manifest_digest=_A_DIGEST,
)
_GIT = GitProvenanceRef(commit="0" * 40, branch="main", dirty=False)


def _mint(
    gateway: Gateway, name: str, target: str, data: dict[str, Any], idem: str
) -> CommandContext:
    envelope = {
        "schema": {
            "name": "mug.command-envelope",
            "version": 0,
            "digest": _A_DIGEST.model_dump(mode="json"),
        },
        "protocol_version": "0.1.0",
        "command": {"name": name, "version": 0},
        "request_id": "request_019b6000-0000-7000-8000-000000000001",
        "idempotency_key": idem,
        "target": {"id": target},
        "payload": {
            "schema": {
                "name": "mug.edge.payload",
                "version": 0,
                "digest": _A_DIGEST.model_dump(mode="json"),
            },
            "data": data,
        },
    }
    return gateway.mint(
        WireCommandEnvelope.model_validate(envelope),
        principal=_PARTICIPANT,
        data_handling=_RESEARCH,
    )


def _idem(tag: str) -> str:
    return "idem_" + tag.ljust(21, "0") + "A"


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


def _render(surface: Surface, state: Any) -> None:
    surface.circle(x=0.5, y=0.5, radius=0.02, color="#f00", object_id="dot")


async def _play() -> EpisodeSummary:
    async def sink(_packet: Any) -> None:
        return None

    return await run_episode(
        GymEnv(cast("EnvFactory", lambda: _FakeEnv())),
        render=_render,
        channel_key="fake-game",
        episode_id=_EPISODE,
        interaction_id="interaction_019b6000-0000-7000-8000-00000000000f",
        seat_key="player",
        input_state=InputState({"Go": 1}, 0),
        sink=sink,
        now=lambda: "2026-07-21T00:00:00.000000Z",
        fps=0,
        max_steps=10,
    )


async def _advance(
    gateway: Gateway,
    store: InMemoryStore,
    revision: int,
    answers: dict[str, Any],
    idem: str,
    captured: list[str] | None = None,
) -> None:
    streams = captured or []
    context = _mint(
        gateway,
        "flow.advance",
        _FLOW_ID,
        {
            "answers": answers,
            "expected_revision": revision,
            "captured_streams": streams,
        },
        idem,
    )
    await advance_flow(
        AdvanceFlowCommand(
            answers=answers, expected_revision=revision, captured_streams=streams
        ),
        study=demo_study(),
        context=context,
        store=store,
    )


class _PrefContexts:
    """Mint command contexts on the preference assignment aggregate."""

    def __init__(self, aggregate_id: str) -> None:
        self._aggregate_id = aggregate_id
        self._counter = itertools.count(1)

    def next(self, aggregate_id: str | None = None) -> CommandContext:
        n = next(self._counter)
        aggregate = aggregate_id or self._aggregate_id
        body = _UUID.format(0x200 + n)
        return CommandContext.model_validate(
            {
                "command_id": "command_" + body,
                "receipt_id": "receipt_" + body,
                "error_id": "error_" + body,
                "idempotency_key": "idem_" + f"{n + 100:021d}" + "A",
                "event_id": "event_" + body,
                "stream_id": "stream_" + aggregate.split("_", 1)[1],
                "producer": {
                    "epoch_id": "prodepoch_" + _UUID.format(9),
                    "sequence": n,
                    "content_digest": _A_DIGEST.model_dump(mode="json"),
                },
                "aggregate_id": aggregate,
                "principal": {
                    "kind": "service",
                    "id": "service_" + _UUID.format(0xA),
                },
                "recorded_at": "2026-07-22T00:00:00.000000Z",
                "event_data_handling": {"privacy_labels": ["research"]},
            }
        )


def _protocol() -> PreferenceProtocol:
    return PreferenceProtocol(
        protocol_version_id="prefver_" + _UUID.format(0x010),
        protocol_definition_id="prefdef_" + _UUID.format(0x011),
        candidate_kind="trajectory",
        task=ComparisonTask(kind="pairwise", prompt="Which run is better?"),
        blinded=True,
        randomize_order=True,
    )


async def _seed_study(store: InMemoryStore) -> None:
    """Record a flow, a captured episode, and one preference annotation."""
    gateway = Gateway()
    await materialize_flow(
        MaterializeFlowCommand(visit_id=_VISIT_ID),
        study=demo_study(),
        context=_mint(
            gateway, "flow.materialize", _FLOW_ID, {"visit_id": _VISIT_ID}, _idem("m")
        ),
        store=store,
        **_plan_args(gateway),  # pyright: ignore[reportArgumentType]
    )
    await _advance(gateway, store, 1, {"agree": "yes"}, _idem("c"))
    await _advance(gateway, store, 2, {"mood": 4}, _idem("s"))

    summary = await _play()
    capture_context = _mint(
        gateway, "episode.capture", _EPISODE, {"episode_id": _EPISODE}, _idem("e")
    )
    await capture_episode(
        summary, visit_id=_VISIT_ID, context=capture_context, store=store
    )
    await _advance(gateway, store, 3, {}, _idem("g"), [capture_context.stream_id])
    await _advance(gateway, store, 4, {}, _idem("d"))

    service = PreferenceService(store=store)
    contexts = _PrefContexts(_ASSIGNMENT)
    _, assignment = await service.assign(
        context=contexts.next(),
        protocol=_protocol(),
        query_id="prefquery_" + _UUID.format(0x002),
        enrollment_id="enrollment_" + _UUID.format(0x003),
        candidate_keys=["policy-a", "policy-b"],
        seed=b"per-participant-seed",
    )
    order = assignment.candidate_display_order
    await service.respond(
        context=contexts.next(response_id_for(_ASSIGNMENT)),
        assignment_id=_ASSIGNMENT,
        choice=order[0],
        presented_order=order,
        submitted_at="2026-07-22T00:00:05.000000Z",
    )


def _ids() -> tuple[Any, Any]:
    """A deterministic id minter pair: artifact ids and upload ids by counter."""
    artifacts = itertools.count(1)
    uploads = itertools.count(1)

    def new_artifact_id() -> str:
        return "artifact_" + _UUID.format(0xA00 + next(artifacts))

    def new_upload_id() -> str:
        return "upload_" + _UUID.format(0xB00 + next(uploads))

    return new_artifact_id, new_upload_id


async def _export(store: InMemoryStore) -> Any:
    new_artifact_id, new_upload_id = _ids()
    return await export_study_dataset(
        store=store,
        artifacts=store,
        study_version=_STUDY,
        git_provenance=_GIT,
        new_artifact_id=new_artifact_id,
        new_upload_id=new_upload_id,
        now=lambda: "2026-07-23T00:00:00.000000Z",
    )


async def test_the_export_splits_the_ledger_into_one_bundle_per_kind() -> None:
    """Events, trajectories, and preferences each get a bundle; none is empty."""
    store = InMemoryStore()
    await _seed_study(store)

    export = await _export(store)
    kinds = [bundle.dataset_kind for bundle in export.bundles]

    # events, trajectories, preferences -- in DATASET_KINDS order; no conversations.
    assert kinds == ["events", "trajectories", "preferences"]
    assert "conversations" not in kinds
    by_kind = {b.dataset_kind: b for b in export.bundles}

    # The events bundle is the whole spine; each semantic kind is a subset of it.
    assert by_kind["trajectories"].row_count == 4  # three transitions + boundary
    assert by_kind["preferences"].row_count == 2  # assign + respond
    assert by_kind["events"].row_count >= (
        by_kind["trajectories"].row_count + by_kind["preferences"].row_count
    )


async def test_the_events_bundle_covers_every_recorded_event() -> None:
    """The events bundle row count equals the whole ledger's event count."""
    store = InMemoryStore()
    await _seed_study(store)

    grouped = collect_dataset_rows(store)
    all_events = grouped["events"].rows
    export = await _export(store)
    events_bundle = next(b for b in export.bundles if b.dataset_kind == "events")
    assert events_bundle.row_count == len(all_events)
    # Every kind's streams are a subset of the events streams.
    events_lineage = next(
        r for r in export.lineage if r.export_key == "dataset-events"
    )
    for record in export.lineage:
        assert set(record.source_stream_ids) <= set(events_lineage.source_stream_ids)


async def test_a_bundle_carries_only_payload_free_canonical_envelopes() -> None:
    """Each exported row is a canonical envelope with a digest, never a value."""
    store = InMemoryStore()
    await _seed_study(store)

    export = await _export(store)
    events_bundle = next(b for b in export.bundles if b.dataset_kind == "events")
    assert events_bundle.artifact.media_type == "application/x-ndjson"

    data = await store.read_artifact(events_bundle.artifact.artifact_id)
    rows = [json.loads(line) for line in data.decode("utf-8").splitlines()]
    assert len(rows) == events_bundle.row_count
    for row in rows:
        assert "payload_digest" in row  # the row names its payload by digest
        assert "stream_position" in row
        assert "answers" not in row  # never a raw form answer
        assert "observation" not in row  # never a raw observation


async def test_the_dataset_export_is_reproducible_from_the_ledger() -> None:
    """The same ledger and the same injected ids reproduce identical digests."""
    store = InMemoryStore()
    await _seed_study(store)

    first = await _export(store)
    second = await _export(store)

    first_by_kind = {b.dataset_kind: b for b in first.bundles}
    second_by_kind = {b.dataset_kind: b for b in second.bundles}
    assert first_by_kind.keys() == second_by_kind.keys()
    for kind, bundle in first_by_kind.items():
        other = second_by_kind[kind]
        assert bundle.bundle_digest == other.bundle_digest
        assert bundle.artifact.digest == other.artifact.digest
        assert bundle.lineage_digest == other.lineage_digest
        # The artifact bytes are byte-identical across the two exports.
        left = await store.read_artifact(bundle.artifact.artifact_id)
        right = await store.read_artifact(other.artifact.artifact_id)
        assert left == right


async def test_the_export_names_its_dataset_kinds_and_binds_the_row_schema() -> None:
    """The result carries a row-schema binding for each exported kind."""
    store = InMemoryStore()
    await _seed_study(store)

    export = await _export(store)
    bound_kinds = [binding.dataset_kind for binding in export.bindings]
    assert bound_kinds == ["events", "trajectories", "preferences"]
    for binding in export.bindings:
        assert binding.dataset_kind in DATASET_KINDS
        # Every kind's rows are canonical event envelopes.
        assert binding.row_schema.name == "mug.api-10.event-envelope"


async def test_each_research_kind_exports_the_values_behind_its_rows() -> None:
    """A spine of digests is not a dataset, so the export carries the values too."""
    store = InMemoryStore()
    await _seed_study(store)

    export = await _export(store)

    kinds = [values.dataset_kind for values in export.values]
    # The visit plan travels as values of its own: it is what each participant was
    # given, and the orders it drew have no other exported trace.
    assert kinds == ["trajectories", "preferences", "plans"]
    rows = await _values_rows(store, export, "preferences")
    # Every record of the annotation, each still the head of its own aggregate: the
    # assignment says who was asked and under which committed order, and the
    # response says what they chose. One written over the other would be one record
    # and one silently lost.
    states = {row["state"]["schema"]["name"]: row["state"] for row in rows}
    assert set(states) == {
        "mug.api-18.preference-assignment",
        "mug.api-18.preference-response",
    }
    choice = states["mug.api-18.preference-response"]
    assert choice["choice"] in choice["presented_order"]
    assert states["mug.api-18.preference-assignment"]["enrollment_id"]


async def test_a_values_row_re_derives_the_digest_its_exported_row_bound() -> None:
    """The values are evidence because they check against the exported spine."""
    store = InMemoryStore()
    await _seed_study(store)

    export = await _export(store)
    rows = await _values_rows(store, export, "preferences")
    bundle = next(b for b in export.bundles if b.dataset_kind == "preferences")
    data = await store.read_artifact(bundle.artifact.artifact_id)
    events = [json.loads(line) for line in data.decode("utf-8").splitlines()]

    for row in rows:
        stream = row["stream_id"]
        # One stream can carry more than one aggregate -- an annotation's assignment
        # and its response share a stream, because they are one lineage -- so the
        # binding a values row must satisfy is that the ledger bound *this* state,
        # not that it was the last thing the stream recorded.
        bound = {
            event["payload_digest"]["hex"]
            for event in events
            if event["stream_position"]["stream_id"] == stream
        }
        assert compute_digest(row["state"]).hex in bound, (
            "the exported values are not the values the ledger bound"
        )


async def test_the_exported_values_are_reproducible_from_the_ledger() -> None:
    """One ledger and one set of injected ids give one values artifact."""
    store = InMemoryStore()
    await _seed_study(store)

    first = await _export(store)
    second = await _export(store)

    for left, right in zip(first.values, second.values, strict=True):
        assert left.dataset_kind == right.dataset_kind
        assert left.artifact.digest == right.artifact.digest


async def _values_rows(
    store: InMemoryStore, export: Any, kind: str
) -> list[dict[str, Any]]:
    """Read one kind's exported values back into its rows."""
    values = next(v for v in export.values if v.dataset_kind == kind)
    data = await store.read_artifact(values.artifact.artifact_id)
    rows = [json.loads(line) for line in data.decode("utf-8").splitlines()]
    assert len(rows) == values.row_count
    return cast("list[dict[str, Any]]", rows)


def _seeding(gateway: Gateway) -> Callable[[str], bytes]:
    """The seed source a plan draws its orders from."""
    return lambda role: gateway.derived_seed("treatment", role)


def _plan_args(gateway: Gateway) -> dict[str, object]:
    """The identity and seed a plan is drafted with, for a study with no design."""
    return {
        "study_version": StudyVersionRef(
            study_id=gateway.derived_id("study", "test"),
            study_version_id=gateway.derived_id("studyver", "test"),
            version_number=1,
            manifest_digest=Digest(algorithm="sha-256", hex="0" * 64),
        ),
        "derive": gateway.derived_id,
        "seed": _seeding(gateway),
    }
